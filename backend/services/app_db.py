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
import os
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

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
    {"symbol": "POLUSDT",  "zh": "Polygon", "ticker": "POL",   "enabled": True},
    {"symbol": "UNIUSDT",  "zh": "Uniswap", "ticker": "UNI",   "enabled": True},
    {"symbol": "LTCUSDT",  "zh": "萊特幣",  "ticker": "LTC",   "enabled": True},
    {"symbol": "NEARUSDT", "zh": "Near幣",  "ticker": "NEAR",  "enabled": True},
]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class AppendOnlyConflict(ValueError):
    """Raised when code attempts to replace an immutable research record."""


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
        # AI 分析快取（持久化：重啟後仍在；cache_key 內含資料版本，資料更新自動失效）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_analysis (
                cache_key    TEXT PRIMARY KEY,
                symbol       TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                json         TEXT NOT NULL
            )
        """)
        # AI 對話紀錄（問答歷史；保留 90 天，見 cleanup_ai）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_chat (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                ts       TEXT NOT NULL,
                symbol   TEXT,
                question TEXT,
                answer   TEXT,
                source   TEXT,      -- gpt / local / error
                model    TEXT
            )
        """)
        # GPT 用量（成本監控：每次呼叫的 token 數；分析/問答/測試都記）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_usage (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                ts                TEXT NOT NULL,
                kind              TEXT,     -- analysis / ask / test
                model             TEXT,
                prompt_tokens     INTEGER,
                completion_tokens INTEGER,
                ok                INTEGER,  -- 1 成功 / 0 失敗
                error             TEXT
            )
        """)
        # 回測「逐筆進出場」明細：每筆一列（供前台/後台查勝率、報酬、持有天數）。
        # 進場＝信心分數首次≥65（隔日開盤買）、出場＝分數首次≤35（隔日開盤賣）或
        # −6% 停損 / +20% 停利觸價，先到先出——與 src/backtest.py（前台即時 API）同一套。
        conn.execute("""
            CREATE TABLE IF NOT EXISTS backtest_trade (
                symbol      TEXT NOT NULL,
                interval    TEXT NOT NULL DEFAULT '1d',
                entry_date  TEXT NOT NULL,
                exit_date   TEXT,
                entry_price REAL, exit_price REAL,
                entry_trigger_price REAL, exit_trigger_price REAL,
                return_pct  REAL, gross_return_pct REAL, cost_pct REAL,
                hold_days   INTEGER,
                exit_reason TEXT,           -- signal_exit / stop_loss / take_profit
                profit      INTEGER,        -- 1 賺 / 0 賠
                PRIMARY KEY (symbol, interval, entry_date)
            )
        """)
        # 回測「整體績效」摘要：每幣一列。與 backtest_trade 分兩張表：粒度不同
        # （摘要是一對多的父列），分表欄位才不混雜、查詢也單純（符合正規化）。
        conn.execute("""
            CREATE TABLE IF NOT EXISTS backtest_summary (
                symbol      TEXT NOT NULL,
                interval    TEXT NOT NULL DEFAULT '1d',
                total_trades INTEGER,
                win_rate REAL,
                total_return_pct REAL, cagr_pct REAL,
                max_drawdown_pct REAL, sharpe_ratio REAL,
                avg_hold_days REAL, profit_factor REAL,
                avg_win_pct REAL, avg_loss_pct REAL,
                buy_hold_return_pct REAL, excess_return_pct REAL,
                signal_exits INTEGER, stop_loss_exits INTEGER, take_profit_exits INTEGER,
                stop_loss REAL, take_profit REAL, fee_rate REAL, slippage_rate REAL,
                period_start TEXT, period_end TEXT,
                updated_at  TEXT,
                PRIMARY KEY (symbol, interval)
            )
        """)
        # 研究預測採不可變快照：同一模型、資料日、週期只可寫入一次。
        # 預測到期後另寫 outcome，不回頭修改當時的預測內容。
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_registry (
                model_version   TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                status          TEXT NOT NULL,
                research        INTEGER NOT NULL CHECK (research = 1),
                methodology_json TEXT NOT NULL,
                created_at      TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS forecast_snapshot (
                forecast_id  TEXT PRIMARY KEY,
                symbol       TEXT NOT NULL,
                horizon_days INTEGER NOT NULL CHECK (horizon_days IN (1, 5, 10)),
                as_of         TEXT NOT NULL,
                generated_at  TEXT NOT NULL,
                model_version TEXT NOT NULL,
                status        TEXT NOT NULL,
                payload_json  TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                UNIQUE (symbol, horizon_days, as_of, model_version),
                FOREIGN KEY (model_version) REFERENCES model_registry(model_version)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS forecast_outcome (
                forecast_id        TEXT PRIMARY KEY,
                target_as_of       TEXT NOT NULL,
                resolved_at        TEXT NOT NULL,
                realized_return_pct REAL NOT NULL,
                actual_direction   TEXT NOT NULL,
                payload_json       TEXT NOT NULL,
                created_at         TEXT NOT NULL,
                FOREIGN KEY (forecast_id) REFERENCES forecast_snapshot(forecast_id)
            )
        """)
        # v2 adds the canonical input hash to snapshot identity.  The legacy
        # tables above are deliberately retained unchanged and immutable so a
        # migration never rewrites historical research records.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS forecast_snapshot_v2 (
                forecast_id    TEXT PRIMARY KEY,
                symbol         TEXT NOT NULL,
                horizon_days   INTEGER NOT NULL CHECK (horizon_days IN (1, 5, 10)),
                as_of           TEXT NOT NULL,
                generated_at    TEXT NOT NULL,
                model_version   TEXT NOT NULL,
                input_hash      TEXT NOT NULL,
                data_version    TEXT NOT NULL,
                reference_close REAL NOT NULL,
                status          TEXT NOT NULL,
                payload_json    TEXT NOT NULL,
                created_at      TEXT NOT NULL,
                UNIQUE (symbol, horizon_days, as_of, model_version, input_hash),
                FOREIGN KEY (model_version) REFERENCES model_registry(model_version)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS forecast_outcome_v2 (
                forecast_id         TEXT PRIMARY KEY,
                target_as_of        TEXT NOT NULL,
                resolved_at         TEXT NOT NULL,
                realized_return_pct REAL NOT NULL,
                actual_direction    TEXT NOT NULL,
                payload_json        TEXT NOT NULL,
                created_at          TEXT NOT NULL,
                FOREIGN KEY (forecast_id) REFERENCES forecast_snapshot_v2(forecast_id)
            )
        """)
        # Database-level guards make append-only a property of the store, not
        # merely a convention of the Python helper functions.
        for _table in (
            "model_registry", "forecast_snapshot", "forecast_outcome",
            "forecast_snapshot_v2", "forecast_outcome_v2",
        ):
            conn.execute(f"""
                CREATE TRIGGER IF NOT EXISTS {_table}_no_update
                BEFORE UPDATE ON {_table}
                BEGIN SELECT RAISE(ABORT, '{_table} is append-only'); END
            """)
            conn.execute(f"""
                CREATE TRIGGER IF NOT EXISTS {_table}_no_delete
                BEFORE DELETE ON {_table}
                BEGIN SELECT RAISE(ABORT, '{_table} is append-only'); END
            """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_started ON job_runs(started_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_access_ts   ON access_log(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prices_sym  ON prices(symbol, interval, ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ind_sym     ON indicators(symbol, interval, ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bt_trade    ON backtest_trade(symbol, interval, entry_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_chat_ts  ON ai_chat(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_usage_ts ON ai_usage(ts)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_forecast_lookup "
            "ON forecast_snapshot(symbol, horizon_days, as_of, model_version)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_forecast_v2_lookup "
            "ON forecast_snapshot_v2(symbol, horizon_days, as_of, model_version, input_hash)"
        )
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


# 小時線只追蹤主流幣（資料量大，先開 BTC/ETH；後台可改 app_config 的 hourly_symbols）
DEFAULT_HOURLY_SYMBOLS = ["BTCUSDT", "ETHUSDT"]


def get_hourly_symbols() -> list[str]:
    """要抓 1h 小時線的幣種清單（同時要求該幣目前為啟用狀態）。"""
    enabled = set(get_enabled_symbols())
    return [s for s in get_config("hourly_symbols", DEFAULT_HOURLY_SYMBOLS) if s in enabled]


def coin_data_status(interval: str = "1d") -> dict:
    """每個幣在 prices 表的資料狀態（筆數 + 最新日期）；給後台幣種管理頁。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT symbol, COUNT(*) AS rows, substr(MAX(ts),1,10) AS last_date "
            "FROM prices WHERE interval=? GROUP BY symbol", (interval,),
        ).fetchall()
    return {r["symbol"]: {"rows": r["rows"], "last_date": r["last_date"]} for r in rows}


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


# 專案根目錄與 venv Python（給後台「新增幣種」觸發抓取管線用，與排程同一套）
_ROOT_DIR = DB_PATH.parent.parent
_PYTHON = str(_ROOT_DIR / ".venv" / "Scripts" / "python.exe")


def fetch_and_ingest_symbol(symbol: str) -> dict:
    """
    為單一新幣跑「抓取 → 算指標 → 入庫」（後台新增幣種用）。
    與每日排程用同一批 src 腳本與 venv Python；任一步失敗會丟出例外。
    回傳該幣入庫後的狀態 {symbol, rows, last_date}。
    """
    symbol = symbol.strip().upper()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    for name, args in (
        ("fetch_binance", [_PYTHON, str(_ROOT_DIR / "src" / "fetch_binance.py"), symbol]),
        ("indicators",    [_PYTHON, str(_ROOT_DIR / "src" / "indicators.py"), symbol, "--no-plot"]),
    ):
        proc = subprocess.run(args, env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-6:])
            raise RuntimeError(f"{name} 失敗：{tail}")
    ingest_market_data()
    st = coin_data_status().get(symbol, {})
    return {"symbol": symbol, "rows": st.get("rows", 0), "last_date": st.get("last_date")}


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


def backfill_backtests(symbols: list[str] = None, stop_loss: float = -0.06,
                       take_profit: float = 0.20, fee_rate: float = 0.001,
                       slippage_rate: float = 0.0005) -> dict:
    """
    以「目前的判斷標準」跑歷史回測，把結果寫進資料庫：
      進場＝信心分數首次 ≥65（隔日開盤買）、出場＝分數首次 ≤35（隔日開盤賣）
      或 −6% 停損 / +20% 停利觸價，先到先出。

    逐筆進出場 → backtest_trade；整體績效（勝率/報酬/持有/回撤/夏普…）→ backtest_summary。
    與前台即時 API（src/backtest.py 的 run_backtest / compute_metrics）完全同一套計算，
    可重複執行（先清該幣舊資料再寫，不殘留）。回傳 {symbols, trades}。
    """
    import sys
    sys.path.insert(0, str(DB_PATH.parent.parent))
    from src.backtest import load_indicators, run_backtest, compute_metrics

    if symbols is None:
        symbols = get_enabled_symbols()
    now = _now()
    n_syms = n_trades = 0
    with _connect() as conn:
        for symbol in symbols:
            try:
                df = load_indicators(symbol)
            except SystemExit:
                continue                                  # 該幣無指標檔（理論上不會）
            if df is None or df.empty:
                continue
            trades = run_backtest(df, stop_loss=stop_loss, take_profit=take_profit,
                                  fee_rate=fee_rate, slippage_rate=slippage_rate)
            metrics = compute_metrics(trades, df)

            # 先清該幣舊明細，再寫入本次結果（可重複執行、不殘留）
            conn.execute("DELETE FROM backtest_trade WHERE symbol=? AND interval='1d'", (symbol,))
            conn.executemany(
                "INSERT OR REPLACE INTO backtest_trade "
                "(symbol, interval, entry_date, exit_date, entry_price, exit_price, "
                " entry_trigger_price, exit_trigger_price, return_pct, gross_return_pct, "
                " cost_pct, hold_days, exit_reason, profit) "
                "VALUES (?, '1d', ?,?,?,?,?,?,?,?,?,?,?,?)",
                [(symbol, t["entry_date"], t["exit_date"], t["entry_price"], t["exit_price"],
                  t["entry_trigger_price"], t["exit_trigger_price"], t["return_pct"],
                  t["gross_return_pct"], t["cost_pct"], t["hold_days"], t["exit_reason"],
                  1 if t["profit"] else 0) for t in trades])
            n_trades += len(trades)
            n_syms += 1

            if "error" in metrics:                        # 無交易 → 清該幣摘要，跳過
                conn.execute("DELETE FROM backtest_summary WHERE symbol=? AND interval='1d'", (symbol,))
                continue
            conn.execute(
                "INSERT OR REPLACE INTO backtest_summary "
                "(symbol, interval, total_trades, win_rate, total_return_pct, cagr_pct, "
                " max_drawdown_pct, sharpe_ratio, avg_hold_days, profit_factor, avg_win_pct, "
                " avg_loss_pct, buy_hold_return_pct, excess_return_pct, signal_exits, "
                " stop_loss_exits, take_profit_exits, stop_loss, take_profit, fee_rate, "
                " slippage_rate, period_start, period_end, updated_at) "
                "VALUES (?, '1d', ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (symbol, metrics["total_trades"], metrics["win_rate"], metrics["total_return_pct"],
                 metrics["cagr_pct"], metrics["max_drawdown_pct"], metrics["sharpe_ratio"],
                 metrics["avg_hold_days"], metrics["profit_factor"], metrics["avg_win_pct"],
                 metrics["avg_loss_pct"], metrics["buy_hold_return_pct"], metrics["excess_return_pct"],
                 metrics["signal_exits"], metrics["stop_loss_exits"], metrics["take_profit_exits"],
                 stop_loss, take_profit, fee_rate, slippage_rate,
                 str(df["date"].min())[:10], str(df["date"].max())[:10], now))
        conn.commit()
    return {"symbols": n_syms, "trades": n_trades}


def load_backtest_summary(symbol: str = None) -> list[dict]:
    """回測整體績效摘要；不給 symbol → 回全部幣，依總報酬遞減排序（跨幣比較用）。"""
    with _connect() as conn:
        if symbol:
            rows = conn.execute(
                "SELECT * FROM backtest_summary WHERE symbol=? AND interval='1d'",
                (symbol.upper(),)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM backtest_summary WHERE interval='1d' "
                "ORDER BY total_return_pct DESC").fetchall()
    return [dict(r) for r in rows]


def load_backtest_trades(symbol: str, limit: int = 0) -> list[dict]:
    """某幣的回測進出場明細（依進場日遞增；limit>0 只回最近 N 筆）。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT entry_date, exit_date, entry_price, exit_price, return_pct, "
            "gross_return_pct, cost_pct, hold_days, exit_reason, profit "
            "FROM backtest_trade WHERE symbol=? AND interval='1d' ORDER BY entry_date",
            (symbol.upper(),)).fetchall()
    out = [dict(r) for r in rows]
    return out[-limit:] if (limit and limit > 0) else out


# ── 研究預測：模型登錄 / 不可變快照 / 到期結果 ─────────────────────────────
def _canonical_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def register_forecast_model(metadata: dict) -> dict:
    """Register one immutable model version; identical retries are idempotent."""
    required = ("model_version", "name", "status", "research", "methodology")
    missing = [key for key in required if key not in metadata]
    if missing:
        raise ValueError(f"model metadata missing: {', '.join(missing)}")
    if metadata["research"] is not True:
        raise ValueError("forecast models must be explicitly marked research")

    version = str(metadata["model_version"])
    methodology_json = _canonical_json(metadata["methodology"])
    with _connect() as conn:
        try:
            conn.execute(
                "INSERT INTO model_registry "
                "(model_version, name, status, research, methodology_json, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (version, str(metadata["name"]), str(metadata["status"]), 1,
                 methodology_json, _now()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            row = conn.execute(
                "SELECT * FROM model_registry WHERE model_version=?", (version,)
            ).fetchone()
            if not row:
                raise
            same = (
                row["name"] == str(metadata["name"])
                and row["status"] == str(metadata["status"])
                and row["research"] == 1
                and row["methodology_json"] == methodology_json
            )
            if not same:
                raise AppendOnlyConflict(f"model version {version} already has different metadata")
    return load_forecast_model(version)


def load_forecast_model(model_version: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM model_registry WHERE model_version=?", (model_version,)
        ).fetchone()
    if not row:
        return None
    return {
        "model_version": row["model_version"],
        "name": row["name"],
        "status": row["status"],
        "research": bool(row["research"]),
        "methodology": json.loads(row["methodology_json"]),
        "created_at": row["created_at"],
    }


def save_forecast_snapshot(payload: dict) -> dict:
    """Append a content-addressed v2 forecast exactly once."""
    required = (
        "forecast_id", "symbol", "horizon_days", "as_of", "generated_at",
        "model_version", "input_hash", "data_version", "reference_close",
        "status", "research",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"forecast payload missing: {', '.join(missing)}")
    if payload["research"] is not True:
        raise ValueError("forecast snapshot must be explicitly marked research")
    if int(payload["horizon_days"]) not in (1, 5, 10):
        raise ValueError("forecast horizon must be 1, 5, or 10 days")
    if not payload["as_of"]:
        raise ValueError("a forecast without as_of cannot be persisted")
    input_hash = str(payload["input_hash"])
    if len(input_hash) != 64 or any(ch not in "0123456789abcdef" for ch in input_hash):
        raise ValueError("forecast input_hash must be a lowercase SHA-256 digest")
    reference_close = float(payload["reference_close"])
    if reference_close <= 0:
        raise ValueError("forecast reference_close must be positive")

    encoded = _canonical_json(payload)
    values = (
        str(payload["forecast_id"]), str(payload["symbol"]).upper(),
        int(payload["horizon_days"]), str(payload["as_of"]),
        str(payload["generated_at"]), str(payload["model_version"]),
        input_hash, str(payload["data_version"]), reference_close,
        str(payload["status"]), encoded, _now(),
    )
    with _connect() as conn:
        try:
            conn.execute(
                "INSERT INTO forecast_snapshot_v2 "
                "(forecast_id, symbol, horizon_days, as_of, generated_at, model_version, "
                "input_hash, data_version, reference_close, status, payload_json, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                values,
            )
            conn.commit()
        except sqlite3.IntegrityError:
            existing = conn.execute(
                "SELECT payload_json FROM forecast_snapshot_v2 WHERE forecast_id=? OR "
                "(symbol=? AND horizon_days=? AND as_of=? AND model_version=? AND input_hash=?)",
                (values[0], values[1], values[2], values[3], values[5], values[6]),
            ).fetchone()
            if existing and existing["payload_json"] == encoded:
                return json.loads(existing["payload_json"])
            raise AppendOnlyConflict(
                "forecast snapshot already exists; immutable history cannot be overwritten"
            )
    return payload


def load_forecast_snapshot(
    symbol: str,
    horizon_days: int,
    as_of: str,
    model_version: str,
    input_hash: str | None = None,
) -> dict | None:
    with _connect() as conn:
        if input_hash is not None:
            row = conn.execute(
                "SELECT payload_json FROM forecast_snapshot_v2 "
                "WHERE symbol=? AND horizon_days=? AND as_of=? AND model_version=? "
                "AND input_hash=?",
                (symbol.upper(), int(horizon_days), as_of, model_version, input_hash),
            ).fetchone()
        else:
            # Compatibility reads may omit the hash. Prefer the newest v2 row,
            # then fall back to a legacy v1 snapshot. The API always supplies
            # input_hash and therefore never uses this ambiguous cache path.
            row = conn.execute(
                "SELECT payload_json FROM forecast_snapshot_v2 "
                "WHERE symbol=? AND horizon_days=? AND as_of=? AND model_version=? "
                "ORDER BY created_at DESC LIMIT 1",
                (symbol.upper(), int(horizon_days), as_of, model_version),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT payload_json FROM forecast_snapshot "
                    "WHERE symbol=? AND horizon_days=? AND as_of=? AND model_version=?",
                    (symbol.upper(), int(horizon_days), as_of, model_version),
                ).fetchone()
    return json.loads(row["payload_json"]) if row else None


def load_forecast_by_id(forecast_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT payload_json FROM forecast_snapshot_v2 WHERE forecast_id=?", (forecast_id,)
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT payload_json FROM forecast_snapshot WHERE forecast_id=?", (forecast_id,)
            ).fetchone()
    return json.loads(row["payload_json"]) if row else None


def pending_forecast_snapshots(
    limit: int = 1000,
    completed_through: str | None = None,
) -> list[dict]:
    """Forecasts that do not yet have a separately appended outcome."""
    bounded_limit = max(1, min(int(limit), 100000))
    maturity_v2 = ""
    maturity_v1 = ""
    params: list = []
    if completed_through:
        # Calendar maturity is only a prefilter. The resolver still requires
        # the exact N-th completed observation, so data gaps cannot resolve a
        # forecast prematurely.
        maturity_v2 = (
            "AND date(s.as_of, '+' || s.horizon_days || ' days') <= date(?) "
        )
        maturity_v1 = maturity_v2
        params.append(completed_through)
    with _connect() as conn:
        v2_rows = conn.execute(
            "SELECT s.payload_json FROM forecast_snapshot_v2 s "
            "LEFT JOIN forecast_outcome_v2 o ON o.forecast_id=s.forecast_id "
            "WHERE o.forecast_id IS NULL " + maturity_v2 +
            "ORDER BY s.as_of, s.symbol, s.horizon_days LIMIT ?",
            (*params, bounded_limit),
        ).fetchall()
        remaining = bounded_limit - len(v2_rows)
        legacy_rows = conn.execute(
            "SELECT s.payload_json FROM forecast_snapshot s "
            "LEFT JOIN forecast_outcome o ON o.forecast_id=s.forecast_id "
            "WHERE o.forecast_id IS NULL " + maturity_v1 +
            "ORDER BY s.as_of, s.symbol, s.horizon_days LIMIT ?",
            (*params, remaining),
        ).fetchall() if remaining > 0 else []
    return [json.loads(row["payload_json"]) for row in [*v2_rows, *legacy_rows]]


def save_forecast_outcome(payload: dict) -> dict:
    """Append one matured outcome without modifying its forecast snapshot."""
    required = (
        "forecast_id", "target_as_of", "resolved_at", "realized_return_pct",
        "actual_direction",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"forecast outcome missing: {', '.join(missing)}")
    encoded = _canonical_json(payload)
    values = (
        str(payload["forecast_id"]), str(payload["target_as_of"]),
        str(payload["resolved_at"]), float(payload["realized_return_pct"]),
        str(payload["actual_direction"]), encoded, _now(),
    )
    with _connect() as conn:
        is_v2 = conn.execute(
            "SELECT 1 FROM forecast_snapshot_v2 WHERE forecast_id=?", (values[0],)
        ).fetchone() is not None
        if not is_v2 and conn.execute(
            "SELECT 1 FROM forecast_snapshot WHERE forecast_id=?", (values[0],)
        ).fetchone() is None:
            raise ValueError("forecast outcome references an unknown snapshot")
        table = "forecast_outcome_v2" if is_v2 else "forecast_outcome"
        try:
            conn.execute(
                f"INSERT INTO {table} "
                "(forecast_id, target_as_of, resolved_at, realized_return_pct, "
                "actual_direction, payload_json, created_at) VALUES (?,?,?,?,?,?,?)",
                values,
            )
            conn.commit()
        except sqlite3.IntegrityError:
            row = conn.execute(
                f"SELECT payload_json FROM {table} WHERE forecast_id=?", (values[0],)
            ).fetchone()
            if row and row["payload_json"] == encoded:
                return json.loads(row["payload_json"])
            raise AppendOnlyConflict(
                "forecast outcome already exists; immutable history cannot be overwritten"
            )
    return payload


def load_forecast_outcome(forecast_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT payload_json FROM forecast_outcome_v2 WHERE forecast_id=?", (forecast_id,)
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT payload_json FROM forecast_outcome WHERE forecast_id=?", (forecast_id,)
            ).fetchone()
    return json.loads(row["payload_json"]) if row else None


def resolve_mature_forecast_outcomes(price_loader, limit: int = 1000, now=None) -> list[dict]:
    """Resolve all mature pending forecasts with a caller-supplied price loader.

    ``price_loader(symbol)`` must return chronological or unsorted dictionaries
    containing ``date`` and ``close``.  The original snapshot remains untouched.
    """
    from src.forecasting import latest_completed_daily_date, resolve_forecast_outcome

    resolved: list[dict] = []
    rows_by_symbol: dict[str, list[dict]] = {}
    result_limit = max(1, min(int(limit), 10000))
    # Scan more candidates than the requested result count so one permanently
    # incomplete symbol cannot starve mature forecasts behind it.
    scan_limit = min(100000, max(10000, result_limit * 10))
    completed_through = latest_completed_daily_date(now).isoformat()
    for snapshot in pending_forecast_snapshots(
        limit=scan_limit,
        completed_through=completed_through,
    ):
        symbol = snapshot["symbol"]
        if symbol not in rows_by_symbol:
            rows_by_symbol[symbol] = list(price_loader(symbol))
        outcome = resolve_forecast_outcome(snapshot, rows_by_symbol[symbol], now=now)
        if outcome is not None:
            try:
                stored = save_forecast_outcome(outcome)
            except AppendOnlyConflict:
                # Cross-process race: the first committed immutable outcome is
                # authoritative. Loading that winner makes retries idempotent
                # even when resolved_at crossed a second boundary.
                stored = load_forecast_outcome(snapshot["forecast_id"])
                if stored is None:
                    raise
            resolved.append(stored)
            if len(resolved) >= result_limit:
                break
    return resolved


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


# ── AI 分析快取 / 對話紀錄 / 用量（ai_analyst.py 用）─────────────────────────
def save_ai_analysis(cache_key: str, symbol: str, data: dict):
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO ai_analysis (cache_key, symbol, generated_at, json) "
            "VALUES (?,?,?,?)",
            (cache_key, symbol, _now(), json.dumps(data, ensure_ascii=False)))
        conn.commit()


def load_ai_analysis(cache_key: str, max_age_sec: int) -> dict | None:
    """讀持久化的分析快取；超過 max_age_sec 視為過期回 None。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT generated_at, json FROM ai_analysis WHERE cache_key=?",
            (cache_key,)).fetchone()
    if not row:
        return None
    try:
        age = (datetime.now(timezone.utc)
               - datetime.strptime(row["generated_at"], "%Y-%m-%d %H:%M:%S")
                 .replace(tzinfo=timezone.utc)).total_seconds()
        if age > max_age_sec:
            return None
        return json.loads(row["json"])
    except Exception:
        return None


def log_ai_chat(symbol: str, question: str, answer: str, source: str, model: str = ""):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO ai_chat (ts, symbol, question, answer, source, model) "
            "VALUES (?,?,?,?,?,?)",
            (_now(), symbol, question[:500], answer[:4000], source, model))
        conn.commit()


def log_ai_usage(kind: str, model: str, prompt_tokens: int = 0,
                 completion_tokens: int = 0, ok: bool = True, error: str = ""):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO ai_usage (ts, kind, model, prompt_tokens, completion_tokens, ok, error) "
            "VALUES (?,?,?,?,?,?,?)",
            (_now(), kind, model, prompt_tokens, completion_tokens,
             1 if ok else 0, error[:300]))
        conn.commit()


def ai_stats() -> dict:
    """GPT 用量統計（後台 AI 設定頁顯示）：今日 / 近 7 日呼叫數與 token。"""
    today = _now()[:10]
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    with _connect() as conn:
        def _row(since):
            r = conn.execute(
                "SELECT COUNT(*) n, SUM(ok=0) fails, "
                "COALESCE(SUM(prompt_tokens),0) pt, COALESCE(SUM(completion_tokens),0) ct "
                "FROM ai_usage WHERE ts >= ?", (since,)).fetchone()
            return {"calls": r["n"], "fails": r["fails"] or 0,
                    "prompt_tokens": r["pt"], "completion_tokens": r["ct"]}
        chats = conn.execute("SELECT COUNT(*) FROM ai_chat").fetchone()[0]
        cached = conn.execute("SELECT COUNT(*) FROM ai_analysis").fetchone()[0]
    return {"today": _row(today), "week": _row(week_ago),
            "chat_rows": chats, "analysis_cached": cached}


def cleanup_ai(chat_keep_days: int = 90, analysis_keep_days: int = 7) -> dict:
    """保留政策：分析快取留 7 天（資料版本一變就沒用）、對話/用量留 90 天。"""
    now = datetime.now(timezone.utc)
    cut_chat = (now - timedelta(days=chat_keep_days)).strftime("%Y-%m-%d %H:%M:%S")
    cut_ana  = (now - timedelta(days=analysis_keep_days)).strftime("%Y-%m-%d %H:%M:%S")
    with _connect() as conn:
        a = conn.execute("DELETE FROM ai_analysis WHERE generated_at < ?", (cut_ana,)).rowcount
        c = conn.execute("DELETE FROM ai_chat  WHERE ts < ?", (cut_chat,)).rowcount
        u = conn.execute("DELETE FROM ai_usage WHERE ts < ?", (cut_chat,)).rowcount
        conn.commit()
    return {"analysis": a, "chat": c, "usage": u}


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
              "老手可切回專業看完整數字。詞庫規劃見 docs/archive/PROJECT_PLAN.md §1.1。"},
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
