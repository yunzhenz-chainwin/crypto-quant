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
import csv
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


def _ensure_column(conn, table: str, column: str, decl: str):
    """若資料表缺少某欄位就補上（既有資料庫的安全遷移，可重複執行）。"""
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_db():
    """建立所有資料表與索引（可安全重複呼叫）。"""
    with _connect() as conn:
        # WAL 模式:更耐當機、讀寫不互相阻塞(穩定性強化)
        conn.execute("PRAGMA journal_mode=WAL")
        # 舊版 prices/indicators(只有 date 欄)→ 砍掉重建為多週期 schema。
        # 這兩張表的資料可由 CSV 重新匯入,故可安全 drop(只會發生一次)。
        for _tbl in ("prices", "indicators"):
            _info = conn.execute(f"PRAGMA table_info({_tbl})").fetchall()
            if _info and "interval" not in [c[1] for c in _info]:
                conn.execute(f"DROP TABLE {_tbl}")
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
        # 工作項目 / 進度追蹤（後台記錄做了什麼、預計做什麼、何時做）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                title        TEXT    NOT NULL,
                detail       TEXT,                                 -- 一句話簡短說明（清單顯示）
                notes        TEXT,                                 -- 備註 / 交接說明（多行，詳細視窗編輯）
                status       TEXT    NOT NULL DEFAULT 'planned',  -- planned / in_progress / done
                phase        TEXT,                                 -- P0/P1… 或自訂分類
                planned_date TEXT,                                 -- 預計進行日 YYYY-MM-DD
                done_date    TEXT,                                 -- 完成日 YYYY-MM-DD
                sort_order   INTEGER DEFAULT 0,
                created_at   TEXT    NOT NULL,
                updated_at   TEXT    NOT NULL
            )
        """)
        # 加密行情（K 線）入庫：支援多週期(1d / 1h…),ts 為完整時間戳
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                symbol   TEXT NOT NULL,
                interval TEXT NOT NULL DEFAULT '1d',
                ts       TEXT NOT NULL,
                open REAL, high REAL, low REAL, close REAL, volume REAL,
                PRIMARY KEY (symbol, interval, ts)
            )
        """)
        # 技術指標入庫（與 prices 對齊,同樣支援多週期）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS indicators (
                symbol   TEXT NOT NULL,
                interval TEXT NOT NULL DEFAULT '1d',
                ts       TEXT NOT NULL,
                close REAL, ma20 REAL, ma60 REAL, ma200 REAL,
                rsi REAL, macd REAL, signal REAL, hist REAL,
                bb_upper REAL, bb_lower REAL, vol_ma20 REAL,
                PRIMARY KEY (symbol, interval, ts)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_started ON job_runs(started_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_access_ts   ON access_log(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prices_sym  ON prices(symbol, interval, ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ind_sym     ON indicators(symbol, interval, ts)")
        # 既有資料庫的欄位遷移：補上 tasks.notes（備註 / 交接說明）
        _ensure_column(conn, "tasks", "notes", "TEXT")
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


# ── 工作項目 / 進度追蹤（tasks）────────────────────────────────────────────
def list_tasks() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks ORDER BY sort_order ASC, "
            "CASE status WHEN 'in_progress' THEN 0 WHEN 'planned' THEN 1 ELSE 2 END, "
            "id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def create_task(title: str, detail: str = "", status: str = "planned",
                phase: str = "", planned_date: str = None,
                done_date: str = None, sort_order: int = 0, notes: str = "") -> int:
    now = _now()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (title, detail, notes, status, phase, planned_date, done_date, "
            "sort_order, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (title, detail, notes, status, phase, planned_date, done_date, sort_order, now, now),
        )
        conn.commit()
        return cur.lastrowid


# 允許前端更新的欄位（白名單，避免亂改 id / 時間戳）
_TASK_FIELDS = {"title", "detail", "notes", "status", "phase",
                "planned_date", "done_date", "sort_order"}


def update_task(task_id: int, fields: dict) -> bool:
    data = {k: v for k, v in (fields or {}).items() if k in _TASK_FIELDS}
    # 狀態改成 done 而未指定完成日時，自動補上今天
    if data.get("status") == "done" and not data.get("done_date"):
        data["done_date"] = _now()[:10]
    if data.get("status") and data["status"] != "done":
        data.setdefault("done_date", None)  # 退回未完成時清掉完成日
    if not data:
        return False
    data["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in data)
    with _connect() as conn:
        cur = conn.execute(f"UPDATE tasks SET {cols} WHERE id = ?",
                           (*data.values(), task_id))
        conn.commit()
        return cur.rowcount > 0


def delete_task(task_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        return cur.rowcount > 0


def estimate_days(title: str, detail: str = "", phase: str = "") -> int:
    """
    粗估一項工作需要幾天（新增任務未指定預計日時自動填用，使用者可再調整）。
    依「階段規模 + 關鍵字複雜度」加權，夾在 1~10 天。
    """
    text = f"{title} {detail}".lower()
    days = 2  # 基準

    # 分類大致規模（前台/後台改動通常較久）;相容舊的 P0–P4
    cat_add = {"前台": 3, "後台": 2, "資料庫": 2, "訊號/回測": 1,
               "資料抓取": 1, "修復/優化": 0, "其他": 0}
    p = (phase or "").strip()
    if p in cat_add:
        days += cat_add[p]
    else:
        for k, v in {"P0": 1, "P1": 3, "P2": 2, "P3": 2, "P4": 1}.items():
            if p.upper().startswith(k):
                days += v
                break

    # 大工程關鍵字 +2、小修小補 -1、多畫面/元件 +1
    big   = ["重構", "遷移", "整套", "全部", "系統", "架構", "白話", "簡易",
             "管理", "分析", "資料庫", "migration", "refactor"]
    small = ["修正", "調整", "文案", "提示", "翻譯", "刪除", "小", "fix", "tweak"]
    multi = ["頁", "面板", "元件", "畫面", "page"]
    if any(w in text for w in big):
        days += 2
    if any(w in text for w in small):
        days -= 1
    if any(w in text for w in multi):
        days += 1

    return max(1, min(10, days))


# 工作項目分類（用「領域」分，比 P0–P4 直覺；新增時可自動判斷）
TASK_CATEGORIES = ["前台", "後台", "資料庫", "訊號/回測", "資料抓取", "修復/優化", "其他"]


def suggest_category(title: str, detail: str = "") -> str:
    """依標題/說明關鍵字自動歸類，找不到就回『其他』（使用者可再改）。順序=優先序。"""
    text = f"{title} {detail}".lower()
    rules = [
        ("前台",      ["前台", "前端", "畫面", "ui", "卡片", "圖表", "蠟燭", "白話",
                       "簡易", "專業", "手機", "rwd", "導覽", "頁面", "視覺", "辭典"]),
        ("後台",      ["後台", "admin", "監控", "操作頁", "登入", "儀表板", "管理頁", "權限"]),
        ("資料庫",    ["資料庫", "入庫", "sqlite", "遷移", "索引", "schema", "資料表"]),
        ("訊號/回測", ["訊號", "回測", "計分", "指標", "rsi", "macd", "策略",
                       "backtest", "因子", "夏普"]),
        ("資料抓取",  ["抓取", "爬", "fetch", "binance", "新聞", "rss", "回補",
                       "排程", "更新資料", "k 線", "k線"]),
        ("修復/優化", ["修正", "修復", "bug", "優化", "調整", "打磨", "效能",
                       "重構", "清理", "死碼"]),
    ]
    for cat, kws in rules:
        if any(k in text for k in kws):
            return cat
    return "其他"


# ── 加密數值入庫（把既有 CSV 灌進 prices / indicators，供查閱與後續分析）──────
def _f(v):
    """CSV 值轉 float；空字串 / None 視為 NULL。"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def ingest_market_data(interval: str = "1d") -> dict:
    """
    把 data/clean/*_<interval>.csv（K 線）與 reports/indicators_*_<interval>.csv（指標）
    匯入資料庫。用 INSERT OR REPLACE，可重複執行（每日排程後再跑一次即增量更新）。
    ts 存到秒(日線為 00:00:00),搭配 interval 支援 1d / 1h 並存。
    """
    root    = DB_PATH.parent.parent
    clean   = root / "data" / "clean"
    reports = root / "reports"
    p_rows = i_rows = syms = 0

    with _connect() as conn:
        for csv_path in sorted(clean.glob(f"*_{interval}.csv")):
            symbol = csv_path.stem.replace(f"_{interval}", "")
            syms += 1
            with open(csv_path, newline="", encoding="utf-8") as f:
                batch = [
                    (symbol, interval, r["date"][:19], _f(r.get("open")), _f(r.get("high")),
                     _f(r.get("low")), _f(r.get("close")), _f(r.get("volume")))
                    for r in csv.DictReader(f)
                ]
            conn.executemany(
                "INSERT OR REPLACE INTO prices "
                "(symbol, interval, ts, open, high, low, close, volume) "
                "VALUES (?,?,?,?,?,?,?,?)", batch)
            p_rows += len(batch)

            ind_path = reports / f"indicators_{symbol}_{interval}.csv"
            if ind_path.exists():
                with open(ind_path, newline="", encoding="utf-8") as f:
                    ibatch = [
                        (symbol, interval, r["date"][:19], _f(r.get("close")), _f(r.get("MA20")),
                         _f(r.get("MA60")), _f(r.get("MA200")), _f(r.get("RSI")),
                         _f(r.get("MACD")), _f(r.get("SIGNAL")), _f(r.get("HIST")),
                         _f(r.get("BB_UPPER")), _f(r.get("BB_LOWER")), _f(r.get("VOL_MA20")))
                        for r in csv.DictReader(f)
                    ]
                conn.executemany(
                    "INSERT OR REPLACE INTO indicators "
                    "(symbol, interval, ts, close, ma20, ma60, ma200, rsi, macd, signal, hist, "
                    "bb_upper, bb_lower, vol_ma20) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ibatch)
                i_rows += len(ibatch)
        conn.commit()
    return {"interval": interval, "symbols": syms, "prices": p_rows, "indicators": i_rows}


def market_stats() -> dict:
    """prices / indicators 的概況，給後台資料庫頁顯示。"""
    with _connect() as conn:
        p = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
        i = conn.execute("SELECT COUNT(*) FROM indicators").fetchone()[0]
        syms = conn.execute("SELECT COUNT(DISTINCT symbol) FROM prices").fetchone()[0]
        span = conn.execute("SELECT MIN(ts), MAX(ts) FROM prices").fetchone()
        by_int = conn.execute(
            "SELECT interval, COUNT(*) FROM prices GROUP BY interval").fetchall()
    return {"prices": p, "indicators": i, "symbols": syms,
            "date_min": (span[0] or "")[:10], "date_max": (span[1] or "")[:10],
            "by_interval": {r[0]: r[1] for r in by_int}}


def backfill_daily_signals() -> int:
    """
    用全部歷史指標重算「每日訊號快照」填入 daily_signal(逐日逐幣的信心分數/多空)。
    讓前台日後可畫『信心分數歷史走勢』。可重複執行(會先清空重建)。
    """
    import sys
    sys.path.insert(0, str(DB_PATH.parent.parent))
    from src.scoring import score_row, signal_from_score

    reports = DB_PATH.parent.parent / "reports"
    total = 0
    with _connect() as conn:
        conn.execute("DELETE FROM daily_signal")
        for csv_path in sorted(reports.glob("indicators_*_1d.csv")):
            symbol = csv_path.stem.replace("indicators_", "").replace("_1d", "")
            prev_hist = None
            rows = []
            with open(csv_path, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    score, _ = score_row(
                        _f(r.get("RSI")), _f(r.get("HIST")), prev_hist,
                        _f(r.get("close")), _f(r.get("MA20")), _f(r.get("MA60")),
                        _f(r.get("MA200")), _f(r.get("volume")), _f(r.get("VOL_MA20")),
                        _f(r.get("BB_UPPER")), _f(r.get("BB_LOWER")))
                    rows.append((r["date"][:10], symbol, signal_from_score(score),
                                 score, _f(r.get("close")), _f(r.get("RSI"))))
                    prev_hist = _f(r.get("HIST"))
            conn.executemany(
                "INSERT OR REPLACE INTO daily_signal "
                "(date, symbol, signal, score, close, rsi) VALUES (?,?,?,?,?,?)", rows)
            total += len(rows)
        conn.commit()
    return total


def fetch_fear_greed_history(limit: int = 0) -> int:
    """
    從 alternative.me 抓恐懼貪婪指數歷史填入 fear_greed(limit=0 取全部,可追溯至 2018)。
    需要網路;失敗會丟出例外由呼叫端處理。
    """
    import datetime as dt
    import requests
    resp = requests.get(f"https://api.alternative.me/fng/?limit={limit}", timeout=20)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    rows = []
    for d in data:
        ts = int(d["timestamp"])
        date = dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")
        rows.append((date, int(d["value"]), d.get("value_classification", "")))
    with _connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO fear_greed (date, value, label) VALUES (?,?,?)", rows)
        conn.commit()
    return len(rows)


# ── 預設資料 ─────────────────────────────────────────────────────────────────
# 預設工作項目：用真實的專案進度填入（done 為已完成、planned 為待辦）
DEFAULT_TASKS = [
    {"phase": "P0", "status": "done", "title": "統一訊號計分（前端=回測同一套 6 因子）",
     "detail": "新增 src/scoring.py，signal_engine 與 backtest 共用", "done_date": "2026-06-29",
     "notes": "核心:src/scoring.py 的 score_row()／signal_from_score()。要調權重、門檻(≥65 多、≤35 空)只改這裡。"
              "backend/services/signal_engine.py(前端建議)與 src/backtest.py(回測)都 import 它。"
              "改完回測數字會變,需用 `python src/backtest.py <SYM>` 重產 reports/backtest_*,再跑 src/verify_backtest.py 驗證。"},
    {"phase": "P0", "status": "done", "title": "修正新聞歷史改用發布日 + 索引",
     "detail": "query_by_date / available_dates 改 published_at", "done_date": "2026-06-29",
     "notes": "backend/services/news_store.py:查詢與日期清單改用 published_at(原本誤用存入時間 fetched_at),並加 idx_published。"
              "RSS 日期解析在 backend/routers/sentiment.py 的 _parse_rss_date()(RFC822→YYYY-MM-DD)。"},
    {"phase": "P0", "status": "done", "title": "建立後台資料庫與設定集中化",
     "detail": "app.db 五張表 + 幣種清單單一來源", "done_date": "2026-06-29",
     "notes": "backend/services/app_db.py 是後台/系統 DB(data/app.db)。幣種清單單一來源 = get_enabled_symbols(),"
              "存在 app_config 表(key='coins')。scheduler.py 已改讀它。新增欄位用 _ensure_column() 做遷移。"},
    {"phase": "P2", "status": "done", "title": "後台登入（帳密 + token）",
     "detail": "/admin 登入，HMAC 簽章", "done_date": "2026-06-29",
     "notes": "backend/routers/admin.py:帳密用環境變數 ADMIN_USER/ADMIN_PASS(預設 admin/admin123),"
              "token 為 HMAC 簽章、密鑰 ADMIN_SECRET(對外務必覆蓋)。前端 token 存 localStorage 的 cq_admin_token。"
              "所有 /api/admin/* 用 require_admin 相依保護。"},
    {"phase": "P2", "status": "done", "title": "後台監控儀表板",
     "detail": "系統健康 / 資料新鮮度 / 資料庫統計 / 工作紀錄", "done_date": "2026-06-29",
     "notes": "前端 frontend/src/admin/AdminApp.jsx 的 Dashboard。資料來源:/api/admin/health、/db/stats、/jobs。"
              "資料新鮮度 = 比對各 clean CSV 最後日期與今天,落後>2 天標過期。"},
    {"phase": "資料庫", "status": "in_progress", "title": "加密數值入庫（prices / indicators）",
     "detail": "K 線與指標寫入 DB，排程後自動同步", "planned_date": "2026-06-29",
     "notes": "app_db.ingest_market_data() 讀 data/clean/*.csv 與 reports/indicators_*.csv,INSERT OR REPLACE 進 prices/indicators 表。"
              "scheduler.run_pipeline 末段會自動呼叫;後台監控頁有『重新匯入行情』鈕(POST /api/admin/ingest)。"
              "待辦:前台查詢改讀 DB、加每日訊號/恐懼貪婪歷史表。"},
    {"phase": "P2", "status": "planned", "title": "後台操作頁（手動觸發抓取 / 重算 / 回補）",
     "detail": "按鈕觸發背景工作 + 進度", "planned_date": None,
     "notes": "目標:在後台按鈕觸發 fetch_binance / indicators / correlation / 新聞回補,背景執行並記 job_runs、顯示進度。"
              "可重用 scheduler 的 subprocess 機制。"},
    {"phase": "P1", "status": "planned", "title": "前台簡易 / 專業切換 + 三大畫面白話版",
     "detail": "紅綠燈、preset、進階摺疊", "planned_date": None,
     "notes": "目標:Header 加 簡易/專業 切換(localStorage),簡易模式把專業數字換成白話(紅綠燈、溫度計、preset),"
              "老手可切回專業看完整數字。詞庫規劃見 docs/PROJECT_PLAN.md §1.1。"},
    {"phase": "P3", "status": "planned", "title": "後台內容管理（幣種 / 權重 / 新聞）",
     "detail": "增刪幣種、調參數、新聞 CRUD", "planned_date": None,
     "notes": "幣種改 app_config 的 coins;訊號權重需把 scoring 參數抽到設定;新聞 CRUD 操作 news.db。"},
    {"phase": "P3", "status": "planned", "title": "後台使用分析",
     "detail": "造訪量、熱門幣、API 狀況（需先記 access_log）", "planned_date": None,
     "notes": "需先加 middleware 把請求記進 app_db.access_log(已建表、有 log_access()),再做造訪量/熱門幣/錯誤率圖表。"},
    {"phase": "P4", "status": "planned", "title": "打磨（手機 RWD / 新手導覽 / 名詞辭典）",
     "detail": "", "planned_date": None,
     "notes": "手機側邊欄收合、首次造訪導覽、名詞小辭典、刪除死碼(PriceChart/SignalBadge)、效能。"},
]


def _seed_defaults():
    """首次啟動時把預設幣種清單寫入 app_config（已存在則不覆蓋）。"""
    if get_config("coins") is None:
        set_config("coins", DEFAULT_COINS)


def _seed_tasks():
    """tasks 表為空時，植入預設的專案進度，讓後台一進去就有內容。"""
    with _connect() as conn:
        empty = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    if empty:
        for i, t in enumerate(DEFAULT_TASKS):
            create_task(t["title"], t.get("detail", ""), t.get("status", "planned"),
                        t.get("phase", ""), t.get("planned_date"), t.get("done_date"),
                        sort_order=i, notes=t.get("notes", ""))


# 模組載入時自動建表並植入預設值
init_db()
_seed_defaults()
_seed_tasks()
