"""
news_store.py — 新聞歷史紀錄資料庫

資料庫位置：data/news.db（使用 Python 內建的 SQLite，不需額外安裝套件）

資料表 news 欄位說明：
  url          : 文章網址，設為 UNIQUE，確保同一篇文章不會重複存入
  title        : 標題（英文，來自 RSS 或 HackerNews）
  domain       : 來源網站，例如 CoinTelegraph、coindesk.com
  category     : 自動分類（市場行情 / 監管法規 / 機構投資 / 技術發展 / 安全事件）
  sentiment    : 情緒標記（bullish 看多 / bearish 看空 / neutral 中立）
  published_at : 文章發布日期（YYYY-MM-DD，由來源提供）
  fetched_at   : 本系統存入時間（UTC 時間戳，歷史查詢用這欄過濾）

索引說明：
  idx_fetched  : 依 fetched_at 加速歷史查詢（依日期過濾時用到）
  idx_category : 依 category 加速分類過濾
"""
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta

# 資料庫路徑：從本檔往上兩層到專案根目錄，再進 data/
DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "news.db"


def _connect() -> sqlite3.Connection:
    """建立資料庫連線；row_factory 讓查詢結果可以用欄位名稱取值（類似 dict）"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn, table: str, column: str, decl: str):
    """若資料表缺少某欄位就補上（既有資料庫的安全遷移，可重複執行）。"""
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_db():
    """建立資料表與索引（若已存在則略過，可安全重複呼叫）"""
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")  # 更耐當機、讀寫不互鎖
        conn.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                url          TEXT    UNIQUE,       -- 唯一鍵，防止重複存入同一篇
                title        TEXT    NOT NULL,
                domain       TEXT,                 -- 來源（CoinDesk、HackerNews 等）
                category     TEXT,                 -- 關鍵字自動分類結果
                sentiment    TEXT,                 -- bullish / bearish / neutral
                published_at TEXT,                 -- 文章原始發布日期
                fetched_at   TEXT    NOT NULL      -- 本系統存入時間（UTC）
            )
        """)
        # 日期索引讓「查某天新聞」快 10 倍以上
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fetched ON news(fetched_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_category ON news(category)")
        # 歷史查詢以「發布日期」為準，故也對 published_at 建索引
        conn.execute("CREATE INDEX IF NOT EXISTS idx_published ON news(published_at)")
        # 欄位遷移：coins = 標題比對到的相關幣種（逗號分隔 ticker，如 "BTC,ETH"）
        _ensure_column(conn, "news", "coins", "TEXT")
        # 每日新聞情緒彙總（symbol='MARKET' 為全市場；分數 -100（極空）~ +100（極多））
        conn.execute("""
            CREATE TABLE IF NOT EXISTS news_sentiment_daily (
                date       TEXT NOT NULL,
                symbol     TEXT NOT NULL,          -- 'MARKET' 或幣種 ticker（BTC、ETH…）
                score      INTEGER,                -- 加權情緒分數 -100 ~ +100
                n_total    INTEGER,
                n_bull     INTEGER,
                n_bear     INTEGER,
                top_json   TEXT,                   -- 當日代表性標題（JSON 陣列）
                updated_at TEXT NOT NULL,
                PRIMARY KEY (date, symbol)
            )
        """)
        conn.commit()


def _norm_title(title: str) -> str:
    """標題正規化（去重比對用）：小寫、去空白與標點、去 Google News 的「 - 來源」尾巴。"""
    t = (title or "").rsplit(" - ", 1)[0].lower()
    return "".join(ch for ch in t if ch.isalnum())


def save_articles(articles: list[dict]) -> int:
    """
    批次存入文章，已存在的 URL 自動略過（INSERT OR IGNORE）。
    另做「標題去重」：同一則新聞常被多個來源轉載（尤其 Google News 聚合 vs 原站 RSS），
    URL 不同但標題相同 → 以正規化標題比對最近 7 天既有資料，重複就跳過。
    回傳：這次實際新增的筆數
    """
    if not articles:
        return 0
    # 用 UTC 時間記錄「何時存入系統」，與文章發布時間分開
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    saved = 0
    with _connect() as conn:
        recent_titles = {
            _norm_title(r[0]) for r in conn.execute(
                "SELECT title FROM news WHERE fetched_at >= ?", (week_ago,)).fetchall()
        }
        for a in articles:
            try:
                key = _norm_title(a["title"])
                if key and key in recent_titles:
                    continue                     # 轉載重複，跳過
                conn.execute(
                    """INSERT OR IGNORE INTO news
                       (url, title, domain, category, sentiment, published_at, fetched_at, coins)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        a["url"], a["title"], a.get("domain", ""),
                        a.get("category", ""), a.get("sentiment", "neutral"),
                        a.get("published_at", ""), now, a.get("coins", ""),
                    ),
                )
                # changes() 回傳 1 = 真正新增；0 = 被 IGNORE（重複）
                if conn.execute("SELECT changes()").fetchone()[0]:
                    saved += 1
                    recent_titles.add(key)
            except Exception:
                continue  # 單筆失敗不影響其他筆
        conn.commit()
    return saved


def query_by_date(date: str, category: str = None) -> list[dict]:
    """
    查詢某一天「發布」的新聞（依文章原始發布日 published_at，不是系統存入時間）。

    這樣 backfill 進來的歷史新聞才會出現在它真正的發布日期下，
    而不是全部擠在「按下匯入的那天」。

    Args:
        date:     YYYY-MM-DD 格式，例如 '2025-01-15'
        category: 可選分類過濾；不傳則回傳全部分類
    """
    sql = "SELECT * FROM news WHERE substr(published_at, 1, 10) = ? "
    params = [date]
    if category:
        sql += "AND category = ? "
        params.append(category)
    sql += "ORDER BY published_at DESC, fetched_at DESC"

    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def query_recent(days: int = 7, category: str = None) -> list[dict]:
    """查詢最近 N 天的新聞（從今天往回算，用於快速取得近期概覽）"""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    sql = "SELECT * FROM news WHERE fetched_at >= ? "
    params = [cutoff]
    if category:
        sql += "AND category = ? "
        params.append(category)
    sql += "ORDER BY fetched_at DESC"

    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def available_dates() -> list[str]:
    """
    回傳資料庫中有新聞「發布」紀錄的日期清單（最近 90 個有資料的日期，倒序）。
    前端「歷史查詢」下拉選單的資料來源。

    用 GLOB 過濾掉格式不正確的舊資料（早期 RSS 曾把日期存成 'Wed, 24 Ju'），
    只列出合法的 YYYY-MM-DD。
    """
    with _connect() as conn:
        rows = conn.execute(
            """SELECT DISTINCT substr(published_at, 1, 10) AS d
               FROM news
               WHERE published_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*'
               ORDER BY d DESC
               LIMIT 90"""
        ).fetchall()
    return [r["d"] for r in rows]


def total_count() -> int:
    """回傳資料庫所有新聞總筆數，顯示在前端底部統計區"""
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]


# ── 每日新聞情緒彙總 ─────────────────────────────────────────────────────────
# 情緒 → 權重（分數 = (多-空)/總數 × 100，四捨五入，夾在 -100~100）
def aggregate_daily(dates: list[str] = None) -> int:
    """
    把 news 表彙總成「每日 × 幣種」情緒分數，寫入 news_sentiment_daily。
    - symbol='MARKET'：當日全部新聞
    - symbol=ticker（BTC…）：coins 欄含該幣的新聞
    dates 不給就只算「今天 + 昨天」（排程滾動更新用）；給日期清單則重算那些天（回補用）。
    回傳寫入的列數。
    """
    if not dates:
        today = datetime.now(timezone.utc).date()
        dates = [str(today - timedelta(days=1)), str(today)]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    written = 0
    with _connect() as conn:
        for d in dates:
            rows = conn.execute(
                "SELECT title, sentiment, coins, category FROM news "
                "WHERE substr(published_at,1,10) = ?", (d,)).fetchall()
            if not rows:
                continue
            # 分組：MARKET + 各幣
            groups: dict[str, list] = {"MARKET": list(rows)}
            for r in rows:
                for tk in (r["coins"] or "").split(","):
                    tk = tk.strip()
                    if tk:
                        groups.setdefault(tk, []).append(r)
            for sym, items in groups.items():
                n_bull = sum(1 for i in items if i["sentiment"] == "bullish")
                n_bear = sum(1 for i in items if i["sentiment"] == "bearish")
                n = len(items)
                score = round((n_bull - n_bear) / n * 100) if n else 0
                # 代表性標題：非中立優先，最多 3 則
                tops = [i["title"] for i in items if i["sentiment"] != "neutral"][:3] \
                       or [i["title"] for i in items[:2]]
                conn.execute(
                    "INSERT OR REPLACE INTO news_sentiment_daily "
                    "(date, symbol, score, n_total, n_bull, n_bear, top_json, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (d, sym, score, n, n_bull, n_bear,
                     json.dumps(tops, ensure_ascii=False), now))
                written += 1
        conn.commit()
    return written


def load_sentiment_daily(symbol: str = "MARKET", days: int = 30) -> list[dict]:
    """讀某幣（或全市場）最近 N 天的每日情緒分數，升冪回傳。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT date, score, n_total, n_bull, n_bear, top_json "
            "FROM news_sentiment_daily WHERE symbol=? "
            "ORDER BY date DESC LIMIT ?", (symbol.upper(), days)).fetchall()
    out = []
    for r in rows[::-1]:
        d = dict(r)
        try:
            d["top"] = json.loads(d.pop("top_json") or "[]")
        except Exception:
            d["top"] = []
        out.append(d)
    return out


# 模組載入時自動建表，確保任何環境下資料庫都已準備好
init_db()
