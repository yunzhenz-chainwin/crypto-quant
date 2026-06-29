"""
scheduler.py — 背景排程任務

排程說明：
  每日 01:00  run_pipeline()    從 Binance 抓取最新 K 線 → 計算技術指標 → 更新相關性矩陣
  每 30 分鐘  fetch_news_job()  從 RSS 抓取最新新聞並存入資料庫

使用 APScheduler 的 BackgroundScheduler，在 FastAPI 啟動時一起跑（非阻塞）
"""
import subprocess
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from backend.routers.sentiment import _fetch_and_save
from backend.services.app_db import (
    get_enabled_symbols, start_job, finish_job,
    ingest_market_data, backfill_daily_signals, fetch_fear_greed_history,
)

# 專案根目錄（相對於本檔往上一層）
ROOT   = Path(__file__).resolve().parent.parent
# 使用虛擬環境裡的 Python，確保套件版本一致
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")


def run_pipeline():
    """
    每日資料更新流程（每天 01:00 執行）

    執行順序：
    1. fetch_binance.py  — 從 Binance API 下載最新日線 K 線資料
    2. indicators.py     — 計算每個幣種的技術指標（MA / RSI / MACD…）
    3. correlation.py    — 計算各幣種之間的相關性矩陣

    幣種清單改由 app_config 集中管理（後台可增刪），不再四處寫死。
    整個流程記入 job_runs，供後台「監控」頁查看成功 / 失敗與時間。
    """
    print("[scheduler] starting daily pipeline...")
    job_id = start_job("daily_pipeline")
    env = {"PYTHONIOENCODING": "utf-8"}
    try:
        symbols = get_enabled_symbols()

        # 1) 抓最新日線（傳入集中設定的幣種清單）
        subprocess.run([PYTHON, str(ROOT / "src" / "fetch_binance.py"), *symbols], env=env)

        # 2) indicators.py 需要幣種代號作為參數，每個幣種各跑一次
        for sym in symbols:
            subprocess.run([PYTHON, str(ROOT / "src" / "indicators.py"), sym], env=env)

        # 3) 重算相關性矩陣（同樣傳入幣種清單）
        subprocess.run([PYTHON, str(ROOT / "src" / "correlation.py"), *symbols], env=env)

        # 4) 同步進資料庫:K線/指標 + 重算每日訊號歷史 + 更新恐懼貪婪歷史
        ing = ingest_market_data()
        sig = backfill_daily_signals()
        try:
            fetch_fear_greed_history(0)
        except Exception as e:
            print(f"[scheduler] fear_greed history skip: {e}")

        finish_job(job_id, "success",
                   f"{len(symbols)} 幣種 · 入庫 {ing['prices']} 筆 · 訊號 {sig} 筆")
        print(f"[scheduler] daily pipeline done (prices {ing['prices']}, signals {sig})")
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
    scheduler.add_job(run_pipeline,    "cron",     hour=1, minute=0)  # 每日 01:00
    scheduler.add_job(fetch_news_job,  "interval", minutes=30)        # 每 30 分鐘
    scheduler.start()
    return scheduler
