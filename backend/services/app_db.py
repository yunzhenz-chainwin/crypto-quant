"""
app_db.py — 後台 / 系統用的 SQLite（data/app.db）

集中存放「會隨時間變化、需要被後台監控或管理」的東西。
市場 K 線 / 指標仍維持既有 CSV 檔案管線，不搬進來（資料量小、每日重算良好）。

資料表：
  job_runs     每次排程 / 手動操作的執行紀錄（後台「監控」「操作」頁用）
  access_log   API 請求紀錄（後台「使用分析」頁用，只記路徑與幣種，不記個資）
  app_config   集中設定（幣種清單、因子權重、回測預設…），後台可改
  daily_signal 每日各幣訊號快照（讓前台能畫「信心分數歷史」）
  fear_greed   恐懼貪婪指數歷史（自有，不必每次跟外部 API 還原）

設計與 news_store.py 一致：模組載入時自動建表，任何環境下都已就緒。
"""
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "app.db"

# 預設幣種清單（與 frontend/src/constants/coins.js 對齊）。
# 這是「我們想追蹤的幣」的單一真相來源；後台之後可在此增刪。
DEFAULT_COINS = [
    {"symbol": "BTCUSDT",  "zh": "比特幣",  "ticker": "BTC",   "enabled": True},
    {"symbol": "ETHUSDT",  "zh": "以太坊",  "ticker": "ETH",   "enabled": True},
    {"symbol": "SOLUSDT",  "zh": "索拉納",  "ticker": "SOL",   "enabled": True},
    {"symbol": "BNBUSDT",  "zh": "幣安幣",  "ticker": "BNB",   "enabled": True},
    {"symbol": "XRPUSDT",  "zh": "瑞波幣",  "ticker": "XRP",   "enabled": True},
    {"symbol": "DOGEUSDT", "zh": "狗狗幣",  "ticker": "DOGE",  "enabled": True},
    {"symbol": "LINKUSDT", "zh": "鏈鏈",    "ticker": "LINK",  "enabled": True},
    {"symbol": "ADAUSDT",  "zh": "艾達幣",  "ticker": "ADA",   "enabled": True},
    {"symbol": "AVAXUSDT", "zh": "雪崩幣",  "ticker": "AVAX",  "enabled": True},
    {"symbol": "DOTUSDT",  "zh": "波卡",    "ticker": "DOT",   "enabled": True},
    {"symbol": "ATOMUSDT", "zh": "宇宙幣",  "ticker": "ATOM",  "enabled": True},
    {"symbol": "MATICUSDT","zh": "馬蹄幣",  "ticker": "MATIC", "enabled": True},
    {"symbol": "UNIUSDT",  "zh": "Uniswap", "ticker": "UNI",   "enabled": True},
    {"symbol": "LTCUSDT",  "zh": "萊特幣",  "ticker": "LTC",   "enabled": True},
    {"symbol": "NEARUSDT", "zh": "Near幣",  "ticker": "NEAR",  "enabled": True},
]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    """建立所有資料表與索引（可安全重複呼叫）。"""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_type    TEXT    NOT NULL,   -- fetch / indicators / correlation / backtest / news / backfill
                status      TEXT    NOT NULL,   -- running / success / failed
                started_at  TEXT    NOT NULL,
                finished_at TEXT,
                message     TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS access_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT    NOT NULL,
                path        TEXT    NOT NULL,
                symbol      TEXT,
                status_code INTEGER,
                latency_ms  INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_config (
                key        TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_signal (
                date   TEXT NOT NULL,
                symbol TEXT NOT NULL,
                signal TEXT,
                score  INTEGER,
                close  REAL,
                rsi    REAL,
                PRIMARY KEY (date, symbol)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fear_greed (
                date  TEXT PRIMARY KEY,
                value INTEGER,
                label TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_started ON job_runs(started_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_access_ts   ON access_log(ts)")
        conn.commit()


# ── 設定（app_config）──────────────────────────────────────────────────────
def get_config(key: str, default=None):
    with _connect() as conn:
        row = conn.execute("SELECT value_json FROM app_config WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value_json"]) if row else default


def set_config(key: str, value):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO app_config (key, value_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), _now()),
        )
        conn.commit()


def get_coins() -> list[dict]:
    """完整幣種設定清單（含中文名、是否啟用）。"""
    return get_config("coins", DEFAULT_COINS)


def get_enabled_symbols() -> list[str]:
    """目前啟用要追蹤的幣種代號清單，給排程 / 抓取流程用。"""
    return [c["symbol"] for c in get_coins() if c.get("enabled", True)]


# ── 操作 / 排程紀錄（job_runs）──────────────────────────────────────────────
def start_job(job_type: str) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO job_runs (job_type, status, started_at) VALUES (?, 'running', ?)",
            (job_type, _now()),
        )
        conn.commit()
        return cur.lastrowid


def finish_job(job_id: int, status: str = "success", message: str = ""):
    with _connect() as conn:
        conn.execute(
            "UPDATE job_runs SET status = ?, finished_at = ?, message = ? WHERE id = ?",
            (status, _now(), message, job_id),
        )
        conn.commit()


def recent_jobs(limit: int = 50) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM job_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── 使用紀錄（access_log）──────────────────────────────────────────────────
def log_access(path: str, symbol: str = None, status_code: int = 200, latency_ms: int = 0):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO access_log (ts, path, symbol, status_code, latency_ms) VALUES (?, ?, ?, ?, ?)",
            (_now(), path, symbol, status_code, latency_ms),
        )
        conn.commit()


def _seed_defaults():
    """首次啟動時把預設幣種清單寫入 app_config（已存在則不覆蓋）。"""
    if get_config("coins") is None:
        set_config("coins", DEFAULT_COINS)


# 模組載入時自動建表並植入預設值
init_db()
_seed_defaults()
