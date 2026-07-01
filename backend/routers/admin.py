"""
admin.py — 後台管理台 API（全部掛在 /api/admin，除登入外都需帶 token）

認證：環境變數 ADMIN_USER / ADMIN_PASS 設定帳密；登入成功發一個 HMAC 簽章的
token（純標準庫，不需額外套件），前端帶在 Authorization: Bearer <token>。
本機自用預設 admin / admin；正式環境請用環境變數覆蓋並設定 ADMIN_SECRET。

目前實作（P2 v1：登入 + 監控）：
  POST /api/admin/login       帳密 → token
  GET  /api/admin/health      系統 / 排程 / 資料新鮮度
  GET  /api/admin/db/stats    資料庫統計（news.db + app.db）
  GET  /api/admin/jobs        最近操作 / 排程紀錄
（操作觸發、內容管理、使用分析為後續 P2/P3 階段）
"""
import os
import time
import hmac
import base64
import hashlib
import sqlite3
from datetime import datetime, timezone, date, timedelta

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Depends
from pydantic import BaseModel

from backend.services.reader import last_updated
from backend.services import app_db, news_store

router = APIRouter()

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin123")  # 可用環境變數 ADMIN_PASS 覆蓋成強密碼
_SECRET    = os.getenv("ADMIN_SECRET", "dev-secret-change-me").encode()
TOKEN_TTL  = 8 * 3600  # token 有效 8 小時


# ── token：HMAC 簽章，純標準庫（payload.signature，base64url）──────────────────
def _make_token(user: str) -> str:
    payload = f"{user}:{int(time.time()) + TOKEN_TTL}".encode()
    sig = hmac.new(_SECRET, payload, hashlib.sha256).digest()
    return (base64.urlsafe_b64encode(payload).decode() + "."
            + base64.urlsafe_b64encode(sig).decode())


def _verify_token(token: str):
    try:
        p_b64, s_b64 = token.split(".")
        payload = base64.urlsafe_b64decode(p_b64)
        sig     = base64.urlsafe_b64decode(s_b64)
        expected = hmac.new(_SECRET, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        user, exp = payload.decode().split(":")
        if int(exp) < int(time.time()):
            return None
        return user
    except Exception:
        return None


def require_admin(authorization: str = Header(None)) -> str:
    """FastAPI 相依：保護所有需登入的後台端點。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="需要登入")
    user = _verify_token(authorization[7:])
    if not user:
        raise HTTPException(status_code=401, detail="登入逾時或無效，請重新登入")
    return user


class LoginReq(BaseModel):
    username: str
    password: str


@router.post("/admin/login")
def login(body: LoginReq):
    if body.username == ADMIN_USER and body.password == ADMIN_PASS:
        return {"ok": True, "token": _make_token(body.username), "user": body.username}
    raise HTTPException(status_code=401, detail="帳號或密碼錯誤")


# ── 監控：系統健康 / 資料新鮮度 ──────────────────────────────────────────────
def _last_job(job_type: str):
    """從最近紀錄中找某類工作的最新一筆。"""
    for j in app_db.recent_jobs(50):
        if j["job_type"] == job_type:
            return j
    return None


@router.get("/admin/health")
def health(_: str = Depends(require_admin)):
    today = datetime.now(timezone.utc).date()
    updated = last_updated()  # {symbol: 'YYYY-MM-DD'}
    coins = []
    for sym, d in sorted(updated.items()):
        try:
            lag = (today - date.fromisoformat(d)).days
        except Exception:
            lag = None
        coins.append({
            "symbol": sym, "last_date": d, "lag_days": lag,
            "stale": (lag is not None and lag > 2),  # 落後超過 2 天視為過期
        })
    fresh = sum(1 for c in coins if not c["stale"])
    return {
        "server_time":     datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "symbols_total":   len(coins),
        "symbols_fresh":   fresh,
        "coins":           coins,
        "last_pipeline":   _last_job("daily_pipeline"),
        "last_news_fetch": _last_job("news_fetch"),
    }


# ── 監控：資料庫統計 ─────────────────────────────────────────────────────────
def _table_count(db_path, table) -> int:
    try:
        with sqlite3.connect(str(db_path)) as c:
            return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except Exception:
        return 0


def _file_kb(path) -> float:
    try:
        return round(os.path.getsize(path) / 1024, 1)
    except Exception:
        return 0.0


@router.get("/admin/db/stats")
def db_stats(_: str = Depends(require_admin)):
    with sqlite3.connect(str(news_store.DB_PATH)) as c:
        c.row_factory = sqlite3.Row
        news_total = c.execute("SELECT COUNT(*) FROM news").fetchone()[0]
        cats = [dict(r) for r in c.execute(
            "SELECT category, COUNT(*) AS n FROM news GROUP BY category ORDER BY n DESC")]
        sources = [dict(r) for r in c.execute(
            "SELECT domain, COUNT(*) AS n FROM news "
            "GROUP BY domain ORDER BY n DESC LIMIT 8")]
    return {
        "news": {
            "total":         news_total,
            "categories":    cats,
            "top_sources":   sources,
            "publish_dates": len(news_store.available_dates()),
            "file_kb":       _file_kb(news_store.DB_PATH),
        },
        "app": {
            "job_runs":      _table_count(app_db.DB_PATH, "job_runs"),
            "access_log":    _table_count(app_db.DB_PATH, "access_log"),
            "daily_signal":  _table_count(app_db.DB_PATH, "daily_signal"),
            "fear_greed":    _table_count(app_db.DB_PATH, "fear_greed"),
            "tasks":         _table_count(app_db.DB_PATH, "tasks"),
            "coins_config":  len(app_db.get_coins()),
            "file_kb":       _file_kb(app_db.DB_PATH),
        },
        "market": app_db.market_stats(),  # 入庫的 K 線 / 指標概況
    }


@router.get("/admin/jobs")
def jobs(_: str = Depends(require_admin)):
    return {"jobs": app_db.recent_jobs(50)}


# ── 工作項目 / 進度追蹤 ──────────────────────────────────────────────────────
class TaskCreateReq(BaseModel):
    title: str
    detail: str = ""
    notes: str = ""                  # 備註 / 交接說明（多行）
    status: str = "planned"          # planned / in_progress / done
    phase: str = ""
    planned_date: Optional[str] = None


class TaskUpdateReq(BaseModel):
    title: Optional[str] = None
    detail: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    phase: Optional[str] = None
    planned_date: Optional[str] = None
    done_date: Optional[str] = None
    sort_order: Optional[int] = None


def _dump(model) -> dict:
    """相容 pydantic v1 / v2,只取有給值的欄位。"""
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=True)
    return model.dict(exclude_none=True)


@router.get("/admin/tasks")
def get_tasks(_: str = Depends(require_admin)):
    return {"tasks": app_db.list_tasks()}


@router.post("/admin/tasks")
def add_task(body: TaskCreateReq, _: str = Depends(require_admin)):
    # 未指定分類 → 依標題自動判斷領域
    phase = body.phase or app_db.suggest_category(body.title, body.detail)
    # 未指定預計日 → 自動估算需要幾天,填上 今天 + 天數
    planned = body.planned_date
    est_days = None
    if not planned:
        est_days = app_db.estimate_days(body.title, body.detail, phase)
        planned = (datetime.now(timezone.utc).date() + timedelta(days=est_days)).isoformat()
    tid = app_db.create_task(body.title, body.detail, body.status,
                             phase, planned, notes=body.notes)
    return {"ok": True, "id": tid, "phase": phase,
            "planned_date": planned, "estimated_days": est_days}


@router.put("/admin/tasks/{task_id}")
def edit_task(task_id: int, body: TaskUpdateReq, _: str = Depends(require_admin)):
    return {"ok": app_db.update_task(task_id, _dump(body))}


@router.delete("/admin/tasks/{task_id}")
def remove_task(task_id: int, _: str = Depends(require_admin)):
    return {"ok": app_db.delete_task(task_id)}


# ── 手動把最新 K 線 / 指標匯入資料庫 ─────────────────────────────────────────
@router.post("/admin/ingest")
def ingest(_: str = Depends(require_admin)):
    jid = app_db.start_job("ingest_market")
    try:
        r = app_db.ingest_market_data()
        app_db.finish_job(jid, "success",
                          f"{r['prices']} 筆行情 / {r['indicators']} 筆指標")
        return {"ok": True, **r}
    except Exception as e:
        app_db.finish_job(jid, "failed", str(e))
        return {"ok": False, "error": str(e)}


# ── 幣種管理（新增 / 啟用停用 / 編輯 / 移除；啟用停用即時生效，不需重啟）──────
class CoinAddReq(BaseModel):
    symbol: str
    zh: str = ""
    ticker: str = ""


class CoinPatchReq(BaseModel):
    zh: Optional[str] = None
    ticker: Optional[str] = None
    enabled: Optional[bool] = None


@router.get("/admin/coins")
def coins_list(_: str = Depends(require_admin)):
    coins = app_db.get_coins()
    status = app_db.coin_data_status()
    today = datetime.now(timezone.utc).date()
    out = []
    for c in coins:
        st = status.get(c["symbol"], {})
        last = st.get("last_date")
        lag = None
        if last:
            try:
                lag = (today - date.fromisoformat(last)).days
            except Exception:
                lag = None
        out.append({
            "symbol": c["symbol"], "zh": c.get("zh", ""), "ticker": c.get("ticker", ""),
            "enabled": c.get("enabled", True),
            "rows": st.get("rows", 0), "last_date": last, "lag_days": lag,
            "stale": (lag is not None and lag > 2), "has_data": st.get("rows", 0) > 0,
        })
    return {"coins": out, "enabled": sum(1 for c in out if c["enabled"])}


@router.post("/admin/coins")
def coins_add(body: CoinAddReq, _: str = Depends(require_admin)):
    symbol = body.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="請輸入幣種代號")
    if not symbol.endswith("USDT"):        # 只輸入 BTC 也接受，自動補 USDT
        symbol += "USDT"
    coins = app_db.get_coins()
    if any(c["symbol"] == symbol for c in coins):
        raise HTTPException(status_code=400, detail=f"{symbol} 已在清單中")
    jid = app_db.start_job("add_coin")
    try:
        r = app_db.fetch_and_ingest_symbol(symbol)
        if not r.get("rows"):
            raise RuntimeError("抓不到任何資料，代號可能不存在於 Binance")
        base = symbol.replace("USDT", "")
        coins.append({
            "symbol": symbol,
            "zh": body.zh.strip() or base,
            "ticker": body.ticker.strip() or base,
            "enabled": True,
        })
        app_db.set_config("coins", coins)
        app_db.finish_job(jid, "success", f"{symbol} · {r['rows']} 筆 · 最新 {r['last_date']}")
        return {"ok": True, **r}
    except Exception as e:
        app_db.finish_job(jid, "failed", str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/admin/coins/{symbol}")
def coins_update(symbol: str, body: CoinPatchReq, _: str = Depends(require_admin)):
    symbol = symbol.upper()
    coins = app_db.get_coins()
    hit = False
    for c in coins:
        if c["symbol"] == symbol:
            if body.zh is not None:      c["zh"] = body.zh.strip()
            if body.ticker is not None:  c["ticker"] = body.ticker.strip()
            if body.enabled is not None: c["enabled"] = bool(body.enabled)
            hit = True
            break
    if not hit:
        raise HTTPException(status_code=404, detail=f"{symbol} 不存在")
    app_db.set_config("coins", coins)
    return {"ok": True}


@router.delete("/admin/coins/{symbol}")
def coins_remove(symbol: str, _: str = Depends(require_admin)):
    symbol = symbol.upper()
    coins = app_db.get_coins()
    kept = [c for c in coins if c["symbol"] != symbol]
    if len(kept) == len(coins):
        raise HTTPException(status_code=404, detail=f"{symbol} 不存在")
    app_db.set_config("coins", kept)
    return {"ok": True, "removed": symbol, "note": "已從清單移除（歷史資料仍保留在資料庫）"}


# ── 資料庫檢視(唯讀瀏覽各表)─────────────────────────────────────────────────
# 白名單:只允許看這些表,並標明它在哪個 DB 檔(避免任意表名 / SQL 注入)
def _table_registry():
    return {
        "prices":       (app_db.DB_PATH,    "行情 K線"),
        "indicators":   (app_db.DB_PATH,    "技術指標"),
        "daily_signal": (app_db.DB_PATH,    "每日訊號"),
        "fear_greed":   (app_db.DB_PATH,    "恐懼貪婪"),
        "tasks":        (app_db.DB_PATH,    "工作項目"),
        "app_config":   (app_db.DB_PATH,    "設定"),
        "job_runs":     (app_db.DB_PATH,    "操作紀錄"),
        "access_log":   (app_db.DB_PATH,    "使用紀錄"),
        "news":         (news_store.DB_PATH, "新聞"),
    }


@router.get("/admin/db/tables")
def db_table_list(_: str = Depends(require_admin)):
    out = []
    for name, (path, label) in _table_registry().items():
        out.append({"name": name, "label": label, "rows": _table_count(path, name)})
    return {"tables": out}


@router.get("/admin/db/table/{name}")
def db_table_rows(
    name: str,
    symbol:   Optional[str] = None,
    interval: Optional[str] = None,
    limit:    int = 50,
    offset:   int = 0,
    _: str = Depends(require_admin),
):
    reg = _table_registry()
    if name not in reg:                       # 只允許白名單內的表
        raise HTTPException(status_code=404, detail="未知或不允許的資料表")
    path, label = reg[name]
    limit = max(1, min(int(limit), 500))      # 一次最多 500 筆
    offset = max(0, int(offset))

    with sqlite3.connect(str(path)) as c:
        c.row_factory = sqlite3.Row
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({name})").fetchall()]
        where, params = [], []
        if symbol and "symbol" in cols:
            where.append("symbol = ?"); params.append(symbol.upper())
        if interval and "interval" in cols:
            where.append("interval = ?"); params.append(interval)
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        # 排序欄:優先時間,其次 id;皆無則用第一欄
        order = "ts" if "ts" in cols else "date" if "date" in cols else \
                "fetched_at" if "fetched_at" in cols else "id" if "id" in cols else cols[0]
        total = c.execute(f"SELECT COUNT(*) FROM {name}{wsql}", params).fetchone()[0]
        rows = c.execute(
            f"SELECT * FROM {name}{wsql} ORDER BY {order} DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()

    return {
        "name": name, "label": label, "columns": cols,
        "rows": [dict(r) for r in rows], "total": total,
        "limit": limit, "offset": offset,
        "has_symbol": "symbol" in cols, "has_interval": "interval" in cols,
    }


# ── 指標交叉驗證(用獨立演算法逐點比對,確認指標計算正確)─────────────────────
@router.get("/admin/verify/indicators")
def verify_indicators(_: str = Depends(require_admin)):
    from src.verify_indicators import cached_result
    return cached_result()              # 與前台 /status 共用同一份快取


# ── 訊號預測力(成績單,即時看現行訊號有沒有 forward edge)──────────────────────
@router.get("/admin/signal/scorecard")
def signal_scorecard(_: str = Depends(require_admin)):
    from src.signal_eval import cached_scorecard
    return cached_scorecard()           # 快取鍵含 scoring.py mtime,改訊號後自動重算


# ── 防禦型跨幣動量「正式策略訊號」(今日建議 + 績效)──────────────────────────
@router.get("/admin/strategy")
def strategy(_: str = Depends(require_admin)):
    from src.momentum_signal import cached_strategy
    return cached_strategy()
