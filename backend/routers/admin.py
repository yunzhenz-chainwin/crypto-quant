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
from datetime import datetime, timezone, date

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
            "coins_config":  len(app_db.get_coins()),
            "file_kb":       _file_kb(app_db.DB_PATH),
        },
    }


@router.get("/admin/jobs")
def jobs(_: str = Depends(require_admin)):
    return {"jobs": app_db.recent_jobs(50)}
