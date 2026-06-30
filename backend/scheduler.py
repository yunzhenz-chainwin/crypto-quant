"""
scheduler.py — 背景排程任務

排程說明：
  每日 01:00  run_pipeline()    從 Binance 抓取最新 K 線 → 計算技術指標 → 更新相關性矩陣
  每 30 分鐘  fetch_news_job()  從 RSS 抓取最新新聞並存入資料庫

使用 APScheduler 的 BackgroundScheduler，在 FastAPI 啟動時一起跑（非阻塞）
"""
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from backend.routers.sentiment import _fetch_and_save
from backend.services.app_db import (
    get_enabled_symbols, start_job, finish_job,
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
        for sym in symbols:
            _run_step(f"indicators[{sym}]",
                      [PYTHON, str(ROOT / "src" / "indicators.py"), sym], env)

        # 3) 重算相關性矩陣（同樣傳入幣種清單）
        _run_step("correlation",
                  [PYTHON, str(ROOT / "src" / "correlation.py"), *symbols], env)

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

        finish_job(job_id, "success",
                   f"{len(symbols)} 幣種 · 入庫 {ing['prices']} 筆 · 訊號 {sig} 筆 · 最新 {date_max}")
        print(f"[scheduler] daily pipeline done (prices {ing['prices']}, signals {sig}, latest {date_max})")
    except Exception as e:
        finish_job(job_id, "failed", str(e))
        print(f"[scheduler] daily pipeline failed: {e}")


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
    scheduler.add_job(fetch_news_job, "interval", minutes=30,
                      id="news_fetch", replace_existing=True,
                      max_instances=1, coalesce=True)              # 每 30 分鐘
    scheduler.start()
    return scheduler
