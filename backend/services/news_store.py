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
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

# 資料庫路徑：從本檔往上兩層到專案根目錄，再進 data/
DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "news.db"


def _connect() -> sqlite3.Connection:
    """建立資料庫連線；row_factory 讓查詢結果可以用欄位名稱取值（類似 dict）"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """建立資料表與索引（若已存在則略過，可安全重複呼叫）"""
    with _connect() as conn:
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
        conn.commit()


def save_articles(articles: list[dict]) -> int:
    """
    批次存入文章，已存在的 URL 自動略過（INSERT OR IGNORE）
    回傳：這次實際新增的筆數
    """
    if not articles:
        return 0
    # 用 UTC 時間記錄「何時存入系統」，與文章發布時間分開
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    saved = 0
    with _connect() as conn:
        for a in articles:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO news
                       (url, title, domain, category, sentiment, published_at, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        a["url"], a["title"], a.get("domain", ""),
                        a.get("category", ""), a.get("sentiment", "neutral"),
                        a.get("published_at", ""), now,
                    ),
                )
                # changes() 回傳 1 = 真正新增；0 = 被 IGNORE（重複）
                if conn.execute("SELECT changes()").fetchone()[0]:
                    saved += 1
            except Exception:
                continue  # 單筆失敗不影響其他筆
        conn.commit()
    return saved


def query_by_date(date: str, category: str = None) -> list[dict]:
    """
    查詢某一天的新聞

    Args:
        date:     YYYY-MM-DD 格式，例如 '2025-01-15'
        category: 可選分類過濾；不傳則回傳全部分類

    LIKE 'YYYY-MM-DD%' 可比對完整 datetime 字串（含時分秒）
    """
    sql = "SELECT * FROM news WHERE fetched_at LIKE ? "
    params = [f"{date}%"]
    if category:
        sql += "AND category = ? "
        params.append(category)
    sql += "ORDER BY fetched_at DESC"

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
    回傳資料庫中有新聞紀錄的日期清單（最近 90 天，倒序）
    前端「歷史查詢」下拉選單的資料來源
    """
    with _connect() as conn:
        rows = conn.execute(
            """SELECT DISTINCT substr(fetched_at, 1, 10) as d
               FROM news
               ORDER BY d DESC
               LIMIT 90"""
        ).fetchall()
    return [r["d"] for r in rows]


def total_count() -> int:
    """回傳資料庫所有新聞總筆數，顯示在前端底部統計區"""
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]


# 模組載入時自動建表，確保任何環境下資料庫都已準備好
init_db()
