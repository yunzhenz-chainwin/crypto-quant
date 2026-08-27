"""
scheduler.py — 背景排程任務

排程說明：
  每日 09:00  run_pipeline()        從 Binance 抓取最新 K 線 → 計算技術指標 → 更新相關性矩陣
              （台灣 09:00 = UTC 01:00，日棒 UTC 00:00 收盤後才抓；舊版排 01:00 會固定慢一根）
  每小時 :06  run_hourly_pipeline() 抓 BTC/ETH 等主流幣 1h K 線（增量）→ 算指標 → 入庫
  每 30 分鐘  fetch_news_job()      從 RSS 抓取最新新聞並存入資料庫
  每日 03:30  run_sqlite_backup()   以 SQLite online backup API 備份 WAL 資料庫

使用 APScheduler 的 BackgroundScheduler，在 FastAPI 啟動時一起跑（非阻塞）
"""
import functools
import os
import subprocess
import threading
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from backend.routers.sentiment import _fetch_and_save
from backend.services import app_db as app_db_service, news_store
from backend.services.app_db import (
    get_enabled_symbols, get_hourly_symbols, start_job, finish_job,
    ingest_market_data, backfill_daily_signals, fetch_fear_greed_history,
    market_stats, register_forecast_model, load_forecast_snapshot,
    save_forecast_snapshot, resolve_mature_forecast_outcomes, AppendOnlyConflict,
)
from backend.services.reader import load_prices
from backend.services.forecast_scorecard import build_forecast_scorecard
from backend.services.sqlite_backup import backup_sqlite_databases, prune_managed_backups
from src.forecasting import (
    MODEL_VERSION, SUPPORTED_HORIZONS, generate_forecast,
    latest_completed_daily_date, model_metadata,
)

# 專案根目錄（相對於本檔往上一層）
ROOT   = Path(__file__).resolve().parent.parent
# 使用虛擬環境裡的 Python，確保套件版本一致
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")

# 資料最多可落後幾天；超過視為抓取失敗（而非靜默沿用舊資料）
MAX_DATA_LAG_DAYS = 2


def _backup_directory() -> Path:
    configured = os.getenv("SQLITE_BACKUP_DIR")
    return Path(configured).expanduser() if configured else ROOT / "data" / "backups" / "sqlite"


def _backup_retention_count() -> int:
    try:
        configured = int(os.getenv("SQLITE_BACKUP_KEEP", "14"))
    except ValueError:
        configured = 14
    return max(1, min(configured, 365))


def run_sqlite_backup():
    """Back up WAL databases through SQLite's consistent online backup API."""
    job_id = start_job("sqlite_backup")
    try:
        backup_root = _backup_directory()
        results = backup_sqlite_databases(
            {
                "app": app_db_service.DB_PATH,
                "news": news_store.DB_PATH,
            },
            backup_root,
        )
        removed = prune_managed_backups(
            backup_root,
            keep_per_database=_backup_retention_count(),
        )
        total_bytes = sum(int(item["size_bytes"]) for item in results)
        finish_job(
            job_id,
            "success",
            f"{len(results)} DB · {total_bytes} bytes · pruned {len(removed)}",
        )
        print(
            f"[scheduler] sqlite backup done "
            f"({len(results)} DB, {total_bytes} bytes, pruned {len(removed)})"
        )
        return {
            "status": "success",
            "backups": results,
            "pruned": len(removed),
        }
    except Exception as exc:
        finish_job(job_id, "failed", str(exc))
        print(f"[scheduler] sqlite backup failed: {exc}")
        return {"status": "failed", "error": str(exc)}


def _run_step(name: str, args: list, env: dict):
    """
    跑一個子流程；若結束碼非 0 直接拋例外（帶上 stderr 末段）。
    取代舊版「subprocess.run 不檢查結果」→ 抓取失敗被靜默吞掉、最後還假性成功的坑。
    """
    proc = subprocess.run(args, env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-8:])
        raise RuntimeError(f"{name} 失敗 (exit {proc.returncode})：\n{tail}")
    return proc


# ── 同型工作互斥（排程觸發與後台手動觸發共用同一把鎖）──────────────────────
# APScheduler 的 max_instances=1 只擋得住排程自己重入，擋不掉後台 /admin/ops/run
# 的手動觸發。兩條路徑同時跑同一支 fetch 腳本會並發讀寫同一份 CSV，寫出欄數不對
# 的殘列（2026-08-04 事故：癱瘓日線與時線管線 6 天）。這裡讓兩者共用同一把鎖。
_JOB_LOCKS = {
    "daily_pipeline":  threading.Lock(),
    "hourly_pipeline": threading.Lock(),
    "news_fetch":      threading.Lock(),
}


def job_is_running(job_type: str) -> bool:
    """該型工作目前是否有人在跑。只探詢不取鎖，給後台 API 先擋掉明顯的重複觸發。"""
    lock = _JOB_LOCKS.get(job_type)
    return bool(lock and lock.locked())


@contextmanager
def _job_slot(job_type: str):
    """取得同型工作的獨占槽位；取不到就 yield False。

    刻意非阻塞：寧可跳過這一輪，也不要讓請求排隊堆在同一份 CSV 上。
    """
    lock = _JOB_LOCKS.get(job_type)
    if lock is None:
        yield True
        return
    acquired = lock.acquire(blocking=False)
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()


def _exclusive(job_type: str):
    """同型工作互斥裝飾器。已有人在跑就跳過本輪，不疊加。

    擋的是「同一個行程內」的並發（排程執行緒 + 後台手動觸發執行緒），這正是
    ops_run 用 job_runs 查詢擋不住的 TOCTOU 空窗。跨行程的重複實例不在守備
    範圍內，那要靠只跑單一實例的部署紀律。
    """
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with _job_slot(job_type) as acquired:
                if not acquired:
                    print(f"[scheduler] {job_type} 上一輪尚未結束，跳過本輪"
                          f"（避免並發讀寫同一份 CSV）")
                    return None
                return fn(*args, **kwargs)
        return wrapper
    return deco


def _assert_data_fresh():
    """
    檢查資料庫最新日期是否夠新；落後超過 MAX_DATA_LAG_DAYS 天就視為抓取失敗。
    這道防線能抓到「子流程結束碼 0、卻沒帶回新資料」（例如 API 回空）的隱性失敗。
    回傳 (最新日期字串, 落後天數)。
    """
    # 只看日線。原本用跨 interval 的 date_max，時線一有髒資料就會讓這裡的 strptime
    # 直接炸掉，把「日線其實抓得好好的」也一併標成失敗（2026-08-04 事故）。
    stats = market_stats()
    date_max = (stats.get("date_max_by_interval", {}).get("1d") or "")[:10]
    if not date_max:
        raise RuntimeError("資料庫沒有任何日線資料")
    today = datetime.now(timezone.utc).date()
    try:
        latest = datetime.strptime(date_max, "%Y-%m-%d").date()
    except ValueError as exc:
        raise RuntimeError(f"日線最新日期格式異常：{date_max!r}（資料庫可能有髒資料）") from exc
    lag = (today - latest).days
    if lag > MAX_DATA_LAG_DAYS:
        raise RuntimeError(f"資料未更新：最新只到 {date_max}（落後 {lag} 天），fetch 可能失敗")
    return date_max, lag


def run_forecast_pipeline():
    """Seal today's research forecasts and append any newly matured outcomes.

    This runs after the daily market pipeline so forecasts exist even when no
    user opens the site.  Existing snapshots are reused verbatim; a retry can
    never replace the prediction that was originally recorded for that day.
    """
    job_id = start_job("forecast_pipeline")
    try:
        symbols = get_enabled_symbols()
        now = datetime.now(timezone.utc)
        cutoff = latest_completed_daily_date(now).isoformat()
        register_forecast_model(model_metadata())

        created = 0
        cached = 0
        abstained = 0
        missing_symbols = []
        rows_by_symbol = {}

        for symbol in symbols:
            rows = [
                row for row in load_prices(symbol, interval="1d")
                if row.get("date") and str(row["date"])[:10] <= cutoff
            ]
            rows_by_symbol[symbol] = rows
            if not rows:
                missing_symbols.append(symbol)
                continue
            as_of = max(str(row["date"])[:10] for row in rows)

            for horizon in SUPPORTED_HORIZONS:
                # Build the deterministic input identity before looking up a
                # snapshot. The same as_of can legitimately have a new hash
                # when an exchange corrects historical candles.
                payload = generate_forecast(
                    symbol,
                    horizon,
                    rows,
                    as_of=as_of,
                    now=now,
                )
                existing = load_forecast_snapshot(
                    symbol, horizon, as_of, MODEL_VERSION, payload["input_hash"]
                )
                if existing is not None:
                    cached += 1
                    if existing.get("status") != "ready":
                        abstained += 1
                    continue

                try:
                    save_forecast_snapshot(payload)
                    created += 1
                    if payload.get("status") != "ready":
                        abstained += 1
                except AppendOnlyConflict:
                    # An API request or another scheduler invocation may have
                    # won the append race. The immutable stored row is final.
                    stored = load_forecast_snapshot(
                        symbol, horizon, as_of, MODEL_VERSION, payload["input_hash"]
                    )
                    if stored is None:
                        raise
                    cached += 1
                    if stored.get("status") != "ready":
                        abstained += 1

        # Use all completed rows currently in the DB so older pending forecasts
        # can resolve when their Nth future daily candle has arrived.
        def _price_loader(symbol):
            return rows_by_symbol.get(symbol) or load_prices(symbol, interval="1d")

        outcomes = resolve_mature_forecast_outcomes(_price_loader)
        # The scorecard is derived on demand from the append-only ledger. Run
        # it only after outcomes resolve so this job's summary reflects the new
        # evidence immediately; a scorecard error must not rewrite or discard
        # the snapshots/outcomes that were already appended successfully.
        try:
            scorecard = build_forecast_scorecard(model_version=MODEL_VERSION)
            scorecard_summary = {
                "status": scorecard["status"],
                "data_as_of": scorecard["data_as_of"],
                "observations": scorecard["overall"]["observations"],
            }
        except Exception as scorecard_error:
            scorecard_summary = {
                "status": "failed",
                "error": str(scorecard_error),
            }
        summary = {
            "status": "success",
            "symbols": len(symbols),
            "created": created,
            "cached": cached,
            "abstained": abstained,
            "resolved": len(outcomes),
            "missing_symbols": missing_symbols,
            "scorecard": scorecard_summary,
        }
        message = (
            f"{len(symbols)} 幣 · 新增 {created} · 已存在 {cached} · "
            f"拒答 {abstained} · 到期 {len(outcomes)}"
        )
        if missing_symbols:
            message += f" · 缺資料 {','.join(missing_symbols)}"
        finish_job(job_id, "success", message)
        print(f"[scheduler] forecast pipeline done ({message})")
        return summary
    except Exception as exc:
        finish_job(job_id, "failed", str(exc))
        print(f"[scheduler] forecast pipeline failed: {exc}")
        return {"status": "failed", "error": str(exc)}


@_exclusive("daily_pipeline")
def run_pipeline():
    """
    每日資料更新流程（每天 09:00 執行；日線 K 棒 UTC 00:00＝台灣 08:00 收盤後才抓）

    執行順序：
    1. fetch_binance.py  — 從 Binance API 下載最新日線 K 線資料
    2. indicators.py     — 計算每個幣種的技術指標（MA / RSI / MACD…）
    3. correlation.py    — 計算各幣種之間的相關性矩陣

    幣種清單改由 app_config 集中管理（後台可增刪），不再四處寫死。
    整個流程記入 job_runs，供後台「監控」頁查看成功 / 失敗與時間。

    重要：每個子流程都經 _run_step()（檢查結束碼）+ 收尾 _assert_data_fresh()
    （檢查資料新鮮度）；任一步失敗都會讓整個 job 標記 failed，不再「假性成功」。
    """
    print("[scheduler] starting daily pipeline...")
    job_id = start_job("daily_pipeline")
    # 關鍵修正：以 os.environ 為基底再加 PYTHONIOENCODING。
    # 舊版 env={"PYTHONIOENCODING":...} 會把整個環境清空（少了 SystemRoot/PATH），
    # 導致子行程在 Windows 連 DNS 都解析不了 → 每次 fetch 全數失敗卻被吞掉。
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        symbols = get_enabled_symbols()

        # 1) 抓最新日線（傳入集中設定的幣種清單）
        _run_step("fetch_binance",
                  [PYTHON, str(ROOT / "src" / "fetch_binance.py"), *symbols], env)

        # 2) indicators.py 需要幣種代號作為參數，每個幣種各跑一次
        #    --no-plot：PNG 圖沒有任何消費者（前端自繪圖表），只出 CSV 供入庫
        for sym in symbols:
            _run_step(f"indicators[{sym}]",
                      [PYTHON, str(ROOT / "src" / "indicators.py"), sym, "--no-plot"], env)

        # （原步驟 3「correlation.py 重算相關性」已移除：它只產出 PNG 熱圖，
        #   而前台 /api/correlation 是由 reader.load_correlation() 直接讀 DB 計算，
        #   PNG 無人使用。腳本保留於 src/ 供手動分析。）

        # 4) 同步進資料庫：K線/指標 + 重算每日訊號歷史
        ing = ingest_market_data()
        sig = backfill_daily_signals()

        # 4b) 重產 backtest 靜態報表，與即時 API（get_backtest 同一套計算）保持一致，
        #     避免 reports/backtest_* 隨每日資料更新而漂移（#111 / #116）。非關鍵，失敗只記錄。
        try:
            from src.backtest import regenerate_reports
            n_reports = regenerate_reports()
            print(f"[scheduler] regenerated {n_reports} backtest reports")
        except Exception as e:
            print(f"[scheduler] backtest reports skip: {e}")

        # 4c) 回測結果入庫：逐筆進出場 → backtest_trade、整體績效 → backtest_summary。
        #     與 get_backtest 同一套計算，前台/後台可直接查 DB。非關鍵，失敗只記錄。
        try:
            from backend.services.app_db import backfill_backtests
            bt = backfill_backtests(symbols)
            print(f"[scheduler] backtest persisted: {bt['symbols']} syms / {bt['trades']} trades")
        except Exception as e:
            print(f"[scheduler] backtest persist skip: {e}")

        # 5) 新鮮度防線：資料若沒更新到近期就視為失敗（抓出隱性失敗，避免假性成功）
        date_max, lag = _assert_data_fresh()

        # 6) 先封存研究預測並解析成熟結果。此工作自行記錄成功/失敗，
        #    不因研究功能異常而阻斷核心行情資料更新。
        forecast_result = run_forecast_pipeline()

        # 7) 更新恐懼貪婪歷史（非關鍵，失敗只略過不影響整體）
        try:
            fetch_fear_greed_history(0)
        except Exception as e:
            print(f"[scheduler] fear_greed history skip: {e}")

        # 7b) 宏觀日資料 + 重跑預測力檢定。前台的宏觀說法（順風/逆風值多少錢）
        #     直接引用 reports/macro_evidence.json，資料進來了就要讓證據跟著更新，
        #     否則畫面會拿舊檢定替新環境背書。非關鍵，失敗只記錄。
        try:
            from backend.services.app_db import fetch_macro_history
            from src.macro_eval import save_evidence
            macro_counts = fetch_macro_history("1y")
            save_evidence()
            print(f"[scheduler] macro {macro_counts.get('days')} days · evidence updated")
        except Exception as e:
            print(f"[scheduler] macro history skip: {e}")

        # 8) 幣種級新聞（Google News 逐幣查詢）+ 重算近 3 天每日情緒彙總（非關鍵）
        try:
            from backend.routers.sentiment import fetch_coin_news_google
            from backend.services.news_store import aggregate_daily
            n_news = fetch_coin_news_google(symbols)
            from datetime import timedelta as _td
            days3 = [str((datetime.now(timezone.utc) - _td(days=i)).date()) for i in range(3)]
            aggregate_daily(days3)
            print(f"[scheduler] coin news +{n_news}")
        except Exception as e:
            print(f"[scheduler] coin news skip: {e}")

        # 9) AI 紀錄保留政策：清掉過期的分析快取與 90 天前的對話/用量紀錄（非關鍵）
        try:
            from backend.services.app_db import cleanup_ai
            cleanup_ai()
        except Exception as e:
            print(f"[scheduler] ai cleanup skip: {e}")

        # 9b) 系統紀錄保留政策：access_log（每筆 API 請求）與 job_runs（每輪排程）
        #     沒有其他地方清，會無限成長（實測已累積數萬筆），各留最近 30 天（非關鍵）
        try:
            from backend.services.app_db import cleanup_logs
            trimmed = cleanup_logs()
            if trimmed["access_log"] or trimmed["job_runs"]:
                print(f"[scheduler] log cleanup: access_log -{trimmed['access_log']}, "
                      f"job_runs -{trimmed['job_runs']}")
        except Exception as e:
            print(f"[scheduler] log cleanup skip: {e}")

        # 10) data/raw 原始 JSON 保留 7 天（時線每小時抓取會持續累積，非關鍵）
        try:
            import re as _re
            cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y%m%d")
            removed = 0
            for f in (ROOT / "data" / "raw").glob("*.json"):
                m = _re.search(r"_(\d{8})\.json$", f.name)
                if m and m.group(1) < cutoff:
                    f.unlink()
                    removed += 1
            if removed:
                print(f"[scheduler] raw cleanup: {removed} files removed")
        except Exception as e:
            print(f"[scheduler] raw cleanup skip: {e}")

        forecast_note = (
            f"預測 +{forecast_result.get('created', 0)} / "
            f"到期 +{forecast_result.get('resolved', 0)}"
            if forecast_result.get("status") == "success"
            else "預測失敗（詳見 forecast_pipeline）"
        )
        finish_job(job_id, "success",
                   f"{len(symbols)} 幣種 · 入庫 {ing['prices']} 筆 · 訊號 {sig} 筆 · "
                   f"{forecast_note} · 最新 {date_max}")
        print(f"[scheduler] daily pipeline done (prices {ing['prices']}, signals {sig}, latest {date_max})")
    except Exception as e:
        finish_job(job_id, "failed", str(e))
        print(f"[scheduler] daily pipeline failed: {e}")


@_exclusive("hourly_pipeline")
def run_hourly_pipeline():
    """
    小時線資料更新（每小時 :06 執行，等 Binance 收完整點 K 棒）

    只追蹤主流幣（app_config 的 hourly_symbols，預設 BTC/ETH）：
    1. fetch_binance --interval 1h  增量抓（讀既有 CSV 最後一根續抓，通常 1 次請求）
    2. indicators --interval 1h --no-plot  重算該幣小時線指標
    3. ingest_market_data("1h")  入庫（INSERT OR REPLACE，可重複執行）

    首次執行或停機多日也不用特別處理：增量抓會自動從缺口處補齊。
    """
    job_id = start_job("hourly_pipeline")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        symbols = get_hourly_symbols()
        if not symbols:
            finish_job(job_id, "success", "無啟用的小時線幣種，略過")
            return

        _run_step("fetch_binance_1h",
                  [PYTHON, str(ROOT / "src" / "fetch_binance.py"),
                   "--interval", "1h", *symbols], env)
        for sym in symbols:
            _run_step(f"indicators_1h[{sym}]",
                      [PYTHON, str(ROOT / "src" / "indicators.py"),
                       sym, "--interval", "1h", "--no-plot"], env)
        ing = ingest_market_data("1h")

        latest = (market_stats().get("by_interval") or {}).get("1h", 0)
        finish_job(job_id, "success",
                   f"{len(symbols)} 幣種 · 入庫 {ing['prices']} 筆 1h（累計 {latest}）")
        print(f"[scheduler] hourly pipeline done ({ing['prices']} rows)")
    except Exception as e:
        finish_job(job_id, "failed", str(e))
        print(f"[scheduler] hourly pipeline failed: {e}")


@_exclusive("news_fetch")
def fetch_news_job():
    """
    新聞抓取任務（每 30 分鐘執行一次）
    呼叫 _fetch_and_save() 從 RSS 抓取最新新聞並存入 SQLite，並記入 job_runs
    """
    job_id = start_job("news_fetch")
    try:
        articles = _fetch_and_save()
        finish_job(job_id, "success", f"{len(articles)} 篇")
        print(f"[scheduler] news fetched: {len(articles)} articles")
    except Exception as e:
        finish_job(job_id, "failed", str(e))
        print(f"[scheduler] news fetch failed: {e}")


def start_scheduler():
    """
    建立並啟動背景排程器，在 FastAPI lifespan 啟動時呼叫
    回傳 scheduler 物件，讓 lifespan 在關閉時能呼叫 scheduler.shutdown()
    """
    scheduler = BackgroundScheduler()
    # 固定 id + replace_existing：避免同一進程重複註冊，造成同一時刻跑多份（job_runs 出現重複）。
    # max_instances=1 + coalesce：上一輪沒跑完就不疊下一輪（並發打 Binance 容易觸發 429）。
    # 台灣 09:00 = UTC 01:00：日線 K 棒在 UTC 00:00（台灣 08:00）收盤，排在收盤後 1 小時抓，
    # 避免像舊版排在台灣 01:00（= UTC 前一天 17:00、當日日棒尚未收盤）而固定慢一根。
    # misfire_grace_time：喚醒慢或看門狗重啟剛好跨過排程點時，仍在寬限內補跑
    # （配 coalesce=True 只補一次），避免預設 1 秒就整輪丟棄、當天資料靜默停在昨天。
    scheduler.add_job(run_pipeline, "cron", hour=9, minute=0,
                      id="daily_pipeline", replace_existing=True,
                      max_instances=1, coalesce=True,
                      misfire_grace_time=3600)                     # 每日 09:00（台灣）
    scheduler.add_job(run_hourly_pipeline, "cron", minute=6,
                      id="hourly_pipeline", replace_existing=True,
                      max_instances=1, coalesce=True,
                      misfire_grace_time=1800)                     # 每小時 :06（1h K 棒收盤後）
    scheduler.add_job(fetch_news_job, "interval", minutes=30,
                      id="news_fetch", replace_existing=True,
                      max_instances=1, coalesce=True,
                      misfire_grace_time=600)                      # 每 30 分鐘
    scheduler.add_job(run_sqlite_backup, "cron", hour=3, minute=30,
                      id="sqlite_backup", replace_existing=True,
                      max_instances=1, coalesce=True,
                      misfire_grace_time=3600)                     # 每日 03:30
    scheduler.start()
    return scheduler
