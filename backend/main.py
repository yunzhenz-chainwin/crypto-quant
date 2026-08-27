"""
main.py — FastAPI 應用程式進入點

啟動方式（會設定本機安全環境變數）：
  cd frontend
  npm run start

API 前綴一律為 /api，例如：
  /api/symbols          可用幣種清單
  /api/prices/BTCUSDT   K 線資料
  /api/signals          所有幣種訊號
  /api/sentiment/news   最新新聞
"""
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from contextlib import asynccontextmanager
from pathlib import Path

from backend.routers import meta, prices, indicators, correlation, signals, backtest, sentiment, admin, ai, macro, forecast
from backend.scheduler import start_scheduler
from backend.services import app_db, news_store
from backend.services.security_hardening import (
    SecurityHeadersMiddleware,
    load_admin_security_config,
)

# React build 輸出目錄（npm run build 產生）
DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan：應用程式啟動 / 關閉時的生命週期管理
    - 啟動時：建表 / 遷移資料庫，然後開始背景排程（每日拉資料、每 30 分鐘抓新聞）
    - 關閉時：乾淨停止排程器，避免背景 thread 殘留
    """
    # 資料庫建表 / 遷移在這裡明確做一次。以前是 app_db.py 與 news_store.py 在
    # 模組載入時自動跑，於是「import 一下就會改到正式 DB」——pytest 收集測試、
    # 開 REPL 都會踩到，且呼叫端沒機會先把 DB_PATH 改掉。改成由啟動流程負責，
    # 誰動了資料庫一目瞭然（其他進入點仍由 _connect() 第一次使用時自動補做）。
    app_db.ensure_ready()
    news_store.ensure_ready()
    scheduler = start_scheduler()
    yield              # yield 前是啟動邏輯，yield 後是關閉邏輯
    scheduler.shutdown()


# 對外模式（透過通道曝露於公網）時關閉 /docs、/redoc、/openapi.json，避免把
# admin／變更端點的完整攻擊面公開給未驗證訪客；dev／非對外模式維持開啟，不影響
# 開發流程。外部模式的偵測與其他模組一致（load_admin_security_config().external，
# 讀 CRYPTO_QUANT_MODE 等環境變數）。
_EXTERNAL = load_admin_security_config().external
_DOCS_KWARGS = (
    {"docs_url": None, "redoc_url": None, "openapi_url": None} if _EXTERNAL else {}
)

app = FastAPI(title="Crypto Quant API", lifespan=lifespan, **_DOCS_KWARGS)

# 允許本地開發時的跨域請求；正式環境前後端同源，CORS 不影響
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:3000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)


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
            # log_access 會 connect＋INSERT＋COMMIT，是阻塞式 SQLite 寫入；每日／每小時
            # 拉資料的交易握著 WAL 寫鎖時可能卡上數秒。直接在事件迴圈上跑會凍住整個
            # server，改丟到 threadpool，避免因為一筆記錄拖垮所有排隊中的請求。
            await run_in_threadpool(
                app_db.log_access, path, symbol, response.status_code, latency_ms
            )
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
app.include_router(macro.router,       prefix="/api")  # /api/macro (宏觀環境,規則式)
app.include_router(forecast.router,    prefix="/api")  # /api/forecast/{symbol} (研究型預測)

# ── 正式環境：FastAPI 直接提供 React build 的靜態檔 ─────────────────────────
# 只在 frontend/dist/ 存在時掛載（本地開發時不存在，不影響開發流程）
if DIST.exists():
    # /assets/* 直接回傳對應靜態資源（JS / CSS / 圖片）
    app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="assets")

    # index.html 一律 no-cache：改版後瀏覽器/通道每次都會重新驗證、拿到最新版
    # （/assets/* 是雜湊檔名、內容不變，仍可長快取）。修「改了前端卻看到舊畫面」。
    _INDEX_HEADERS = {"Cache-Control": "no-cache, must-revalidate"}

    # 根路徑與所有其他路徑都回傳 index.html，讓 React Router 接管
    @app.get("/")
    def serve_root():
        return FileResponse(str(DIST / "index.html"), headers=_INDEX_HEADERS)

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        # /api/* 底下沒對到路由（打錯路徑或用錯 HTTP method）不該落到 SPA fallback：
        # 回 200＋index.html 會讓前端 fetch 把 HTML 當 JSON 解析而失敗，反而遮蔽路由
        # 問題。這類請求一律回 JSON 404，真正的 SPA 路徑（非 /api）維持照舊回 index.html。
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        # 若請求的是真實存在的靜態檔（如 favicon.svg）就直接回傳
        # resolve 後必須仍在 dist 內；同時防禦 ../、編碼斜線與 symlink 越界。
        dist_root = DIST.resolve()
        try:
            target = (dist_root / full_path).resolve()
            target.relative_to(dist_root)
        except (OSError, RuntimeError, ValueError):
            raise HTTPException(status_code=404, detail="Not found")
        if target.exists() and target.is_file():
            return FileResponse(str(target))
        return FileResponse(str(DIST / "index.html"), headers=_INDEX_HEADERS)
