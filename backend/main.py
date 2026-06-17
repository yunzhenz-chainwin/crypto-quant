"""
main.py — FastAPI 應用程式進入點

啟動方式：
  uvicorn backend.main:app --port 8000 --reload

API 前綴一律為 /api，例如：
  /api/symbols          可用幣種清單
  /api/prices/BTCUSDT   K 線資料
  /api/signals          所有幣種訊號
  /api/sentiment/news   最新新聞
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from backend.routers import meta, prices, indicators, correlation, signals, backtest, sentiment
from backend.scheduler import start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan：應用程式啟動 / 關閉時的生命週期管理
    - 啟動時：開始背景排程（每日拉資料、每 30 分鐘抓新聞）
    - 關閉時：乾淨停止排程器，避免背景 thread 殘留
    """
    scheduler = start_scheduler()
    yield              # yield 前是啟動邏輯，yield 後是關閉邏輯
    scheduler.shutdown()


app = FastAPI(title="Crypto Quant API", lifespan=lifespan)

# 允許前端開發伺服器（port 5173）和本地測試（port 3000）跨域請求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 各功能模組的路由（全部掛在 /api 下）─────────────────────────────────────
app.include_router(meta.router,        prefix="/api")  # /api/symbols, /api/status
app.include_router(prices.router,      prefix="/api")  # /api/prices/{symbol}
app.include_router(indicators.router,  prefix="/api")  # /api/indicators/{symbol}
app.include_router(correlation.router, prefix="/api")  # /api/correlation
app.include_router(signals.router,     prefix="/api")  # /api/signals
app.include_router(backtest.router,    prefix="/api")  # /api/backtest/{symbol}
app.include_router(sentiment.router,   prefix="/api")  # /api/sentiment/...
