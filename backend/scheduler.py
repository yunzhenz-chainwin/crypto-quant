"""
scheduler.py — 背景排程任務

排程說明：
  每日 01:00  run_pipeline()        從 Binance 抓取最新 K 線 → 計算技術指標 → 更新相關性矩陣
  每小時 :06  run_hourly_pipeline() 抓 BTC/ETH 等主流幣 1h K 線（增量）→ 算指標 → 入庫
  每 30 分鐘  fetch_news_job()      從 RSS 抓取最新新聞並存入資料庫

使用 APScheduler 的 BackgroundScheduler，在 FastAPI 啟動時一起跑（非阻塞）
"""
import os
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from backend.routers.sentiment import _fetch_and_save
from backend.services.app_db import (
    get_enabled_symbols, get_hourly_symbols, start_job, finish_job,
    ingest_market_data, backfill_daily_signals, fetch_fear_greed_history,
    market_stats,
)

# 專案根目錄（相對於本檔往上一層）
ROOT   = Path(__file__).resolve().parent.parent
# 使用虛擬環境裡的 Python，確保套件版本一致
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")

# 資料最多可落後幾天；超過視為抓取失敗（而非靜默沿用舊資料）
MAX_DATA_LAG_DAYS = 2


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


def _assert_data_fresh():
    """
    檢查資料庫最新日期是否夠新；落後超過 MAX_DATA_LAG_DAYS 天就視為抓取失敗。
    這道防線能抓到「子流程結束碼 0、卻沒帶回新資料」（例如 API 回空）的隱性失敗。
    回傳 (最新日期字串, 落後天數)。
    """
    date_max = (market_stats().get("date_max") or "")[:10]
    if not date_max:
        raise RuntimeError("資料庫沒有任何日線資料")
    today = datetime.now(timezone.utc).date()
    lag = (today - datetime.strptime(date_max, "%Y-%m-%d").date()).days
    if lag > MAX_DATA_LAG_DAYS:
        raise RuntimeError(f"資料未更新：最新只到 {date_max}（落後 {lag} 天），fetch 可能失敗")
    return date_max, lag


def run_pipeline():
    """
    每日資料更新流程（每天 01:00 執行）

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

        # 5) 新鮮度防線：資料若沒更新到近期就視為失敗（抓出隱性失敗，避免假性成功）
        date_max, lag = _assert_data_fresh()

        # 6) 更新恐懼貪婪歷史（非關鍵，失敗只略過不影響整體）
        try:
            fetch_fear_greed_history(0)
        except Exception as e:
            print(f"[scheduler] fear_greed history skip: {e}")

        # 7) 幣種級新聞（Google News 逐幣查詢）+ 重算近 3 天每日情緒彙總（非關鍵）
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

        # 8) AI 紀錄保留政策：清掉過期的分析快取與 90 天前的對話/用量紀錄（非關鍵）
        try:
            from backend.services.app_db import cleanup_ai
            cleanup_ai()
        except Exception as e:
            print(f"[scheduler] ai cleanup skip: {e}")

        # 9) data/raw 原始 JSON 保留 7 天（時線每小時抓取會持續累積，非關鍵）
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

        finish_job(job_id, "success",
                   f"{len(symbols)} 幣種 · 入庫 {ing['prices']} 筆 · 訊號 {sig} 筆 · 最新 {date_max}")
        print(f"[scheduler] daily pipeline done (prices {ing['prices']}, signals {sig}, latest {date_max})")
    except Exception as e:
        finish_job(job_id, "failed", str(e))
        print(f"[scheduler] daily pipeline failed: {e}")


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
    scheduler.add_job(run_pipeline, "cron", hour=1, minute=0,
                      id="daily_pipeline", replace_existing=True,
                      max_instances=1, coalesce=True)              # 每日 01:00
    scheduler.add_job(run_hourly_pipeline, "cron", minute=6,
                      id="hourly_pipeline", replace_existing=True,
                      max_instances=1, coalesce=True)              # 每小時 :06（1h K 棒收盤後）
    scheduler.add_job(fetch_news_job, "interval", minutes=30,
                      id="news_fetch", replace_existing=True,
                      max_instances=1, coalesce=True)              # 每 30 分鐘
    scheduler.start()
    return scheduler
