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

# 專案根目錄（相對於本檔往上一層）
ROOT   = Path(__file__).resolve().parent.parent
# 使用虛擬環境裡的 Python，確保套件版本一致
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")


def run_pipeline():
    """
    每日資料更新流程（每天 01:00 執行）

    執行順序：
    1. fetch_binance.py  — 從 Binance API 下載最新日線 K 線資料
    2. indicators.py     — 計算每個幣種的技術指標（MA / RSI / MACD）
    3. correlation.py    — 計算 15 個幣種之間的相關性矩陣

    各腳本用 subprocess 獨立執行，任一腳本失敗不影響其他腳本繼續跑
    """
    print("[scheduler] starting daily pipeline...")
    scripts = [
        ROOT / "src" / "fetch_binance.py",
        ROOT / "src" / "correlation.py",
    ]
    symbols = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
        "DOGEUSDT", "LINKUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT",
        "ATOMUSDT", "MATICUSDT", "UNIUSDT", "LTCUSDT", "NEARUSDT",
    ]

    # 先跑不需要幣種參數的腳本
    for script in scripts:
        subprocess.run([PYTHON, str(script)], env={"PYTHONIOENCODING": "utf-8"})

    # indicators.py 需要幣種代號作為參數，每個幣種各跑一次
    for sym in symbols:
        subprocess.run([PYTHON, str(ROOT / "src" / "indicators.py"), sym],
                       env={"PYTHONIOENCODING": "utf-8"})

    print("[scheduler] daily pipeline done")


def fetch_news_job():
    """
    新聞抓取任務（每 30 分鐘執行一次）
    呼叫 _fetch_and_save() 從 RSS 抓取最新新聞並存入 SQLite
    """
    try:
        articles = _fetch_and_save()
        print(f"[scheduler] news fetched: {len(articles)} articles")
    except Exception as e:
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
