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
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pathlib import Path

from backend.routers import meta, prices, indicators, correlation, signals, backtest, sentiment, admin, ai
from backend.scheduler import start_scheduler
from backend.services import app_db

# React build 輸出目錄（npm run build 產生）
DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


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

# 允許本地開發時的跨域請求；正式環境前後端同源，CORS 不影響
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 使用紀錄 middleware（access_log）─────────────────────────────────────────
# 只記錄業務 API（/api/*）的路徑、幣種、狀態碼與延遲，供後台使用分析／熱門 API 統計。
# 靜態資源與 SPA fallback 不記；寫入失敗一律吞掉，絕不影響請求本身（#113）。
@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    try:
        path = request.url.path
        if path.startswith("/api/"):
            symbol = request.query_params.get("symbol")
            if not symbol:
                # 從 /api/prices/BTCUSDT 這類路徑抓最後一段像 symbol 的（結尾 USDT）
                tail = path.rstrip("/").rsplit("/", 1)[-1].upper()
                if tail.endswith("USDT"):
                    symbol = tail
            latency_ms = int((time.perf_counter() - start) * 1000)
            app_db.log_access(path, symbol, response.status_code, latency_ms)
    except Exception:
        pass  # 記錄是輔助功能，任何錯誤都不能讓正常請求失敗
    return response

# ── 各功能模組的路由（全部掛在 /api 下）─────────────────────────────────────
app.include_router(meta.router,        prefix="/api")  # /api/symbols, /api/status
app.include_router(prices.router,      prefix="/api")  # /api/prices/{symbol}
app.include_router(indicators.router,  prefix="/api")  # /api/indicators/{symbol}
app.include_router(correlation.router, prefix="/api")  # /api/correlation
app.include_router(signals.router,     prefix="/api")  # /api/signals
app.include_router(backtest.router,    prefix="/api")  # /api/backtest/{symbol}
app.include_router(sentiment.router,   prefix="/api")  # /api/sentiment/...
app.include_router(admin.router,       prefix="/api")  # /api/admin/... (後台,需登入)
app.include_router(ai.router,          prefix="/api")  # /api/ai/... (AI 分析機器人)

# ── 正式環境：FastAPI 直接提供 React build 的靜態檔 ─────────────────────────
# 只在 frontend/dist/ 存在時掛載（本地開發時不存在，不影響開發流程）
if DIST.exists():
    # /assets/* 直接回傳對應靜態資源（JS / CSS / 圖片）
    app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="assets")

    # 根路徑與所有其他路徑都回傳 index.html，讓 React Router 接管
    @app.get("/")
    def serve_root():
        return FileResponse(str(DIST / "index.html"))

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        # 若請求的是真實存在的靜態檔（如 favicon.svg）就直接回傳
        target = DIST / full_path
        if target.exists() and target.is_file():
            return FileResponse(str(target))
        return FileResponse(str(DIST / "index.html"))
