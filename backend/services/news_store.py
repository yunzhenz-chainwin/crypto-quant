"""
news_store.py — 新聞歷史紀錄資料庫

資料庫位置：data/news.db（使用 Python 內建的 SQLite，不需額外安裝套件）
            可用環境變數 CRYPTO_QUANT_NEWS_DB 覆寫（測試 / 一次性腳本改道用）。
建表時機：import 本模組不會碰資料庫；由 main.py 的 lifespan 呼叫 ensure_ready()，
          或第一次 _connect() 時自動補做。

資料表 news 欄位說明：
  url          : 文章網址，設為 UNIQUE，確保同一篇文章不會重複存入
  title        : 標題（英文，來自 RSS 或 HackerNews）
  domain       : 來源網站，例如 CoinTelegraph、coindesk.com
  category     : 自動分類（市場行情 / 監管法規 / 機構投資 / 技術發展 / 安全事件）
  sentiment    : 情緒標記（bullish 看多 / bearish 看空 / neutral 中立）
                 ※ 只依標題判讀。不要改成連 summary 一起算——那會讓
                   news_sentiment_daily 這條歷史曲線在改版當天出現人為斷層，
                   且舊文章沒有摘要可供重算。
  coins        : 標題（＋摘要）比對到的相關幣種，逗號分隔 ticker，如 "BTC,ETH"。
                 由 sentiment.py 的 _match_coins() 以「整字比對」算出，是判斷
                 「這篇跟哪顆幣有關」的唯一可靠依據；拿 ticker 去比對標題子字串
                 會誤中（UNI 命中 community、SOL 命中 sold、ETH 命中 whether）。
                 本欄位加入之前的舊資料為 NULL，讀取時一律寫
                 (row.get("coins") or "").split(",")。
  summary      : RSS 摘要純文字（已去 HTML 標籤與實體，最長 500 字）。
                 只用於幣種比對，不參與情緒判讀。以下情況為空字串：
                 HackerNews 回補、Google News 來源（其 description 無內文）、
                 以及本欄位加入之前就已存在的舊資料（值為 NULL）。
  published_at : 文章發布日期（YYYY-MM-DD，由來源提供）
  fetched_at   : 本系統存入時間（UTC 時間戳，歷史查詢用這欄過濾）

索引說明：
  idx_fetched  : 依 fetched_at 加速歷史查詢（依日期過濾時用到）
  idx_category : 依 category 加速分類過濾
"""
import json
import os
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta

# 資料庫路徑：從本檔往上兩層到專案根目錄，再進 data/。
# 可用環境變數 CRYPTO_QUANT_NEWS_DB 覆寫——測試與一次性腳本要能改道到暫存檔，
# 否則只要 import 這個模組就等於綁死正式庫（見下方 ensure_ready() 的說明）。
DB_PATH = Path(os.environ.get("CRYPTO_QUANT_NEWS_DB")
               or Path(__file__).resolve().parent.parent.parent / "data" / "news.db")

# 建表／遷移「延到真的要用資料庫時才做」，不在模組載入時做。
# 舊版在檔案最後直接呼叫 init_db()，於是任何 import 都會對正式 data/news.db 跑
# ALTER TABLE：pytest 收集測試、開 REPL、admin 頁只想讀 DB_PATH，全都會踩到，
# 而且呼叫端根本沒有機會先把 DB_PATH 改掉。（這不是假設：驗證流程只是 import
# 了一下，正式庫就被加上了 summary 欄。）
_init_lock = threading.RLock()          # RLock：ensure_ready() 內部還會再進 init_db()
_initialized: set[str] = set()          # 已完成建表／遷移的路徑（DB_PATH 可被改道）


def _raw_connect() -> sqlite3.Connection:
    """純連線，不觸發建表；只給 init_db() 自己用（避免遞迴回 ensure_ready()）。"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_ready():
    """確保目前 DB_PATH 指向的資料庫已建表／遷移（每個路徑只做一次）。

    正常情況由 backend/main.py 的 lifespan 在啟動時明確呼叫；排程腳本、一次性
    腳本等其他進入點則靠 _connect() 在第一次真的用到資料庫時自動補做。
    """
    path = str(DB_PATH)
    if path in _initialized:
        return
    with _init_lock:
        if path in _initialized:
            return
        init_db()


def _connect() -> sqlite3.Connection:
    """建立資料庫連線；row_factory 讓查詢結果可以用欄位名稱取值（類似 dict）"""
    ensure_ready()
    return _raw_connect()


def _ensure_column(conn, table: str, column: str, decl: str):
    """若資料表缺少某欄位就補上（既有資料庫的安全遷移，可重複執行）。"""
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_db():
    """建立資料表與索引（若已存在則略過，可安全重複呼叫）

    會實際連線並跑 DDL，所以只在「確定要動這個資料庫」時呼叫；平常請走
    ensure_ready()（有做過就跳過）或直接用 _connect()（第一次會自動補做）。
    """
    with _raw_connect() as conn:
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
        # 欄位遷移：summary = RSS 摘要純文字（幣種比對用）。
        # ALTER TABLE ADD COLUMN 不會重寫既有資料列，既有的一萬多筆一律補成 NULL；
        # _ensure_column 先查 PRAGMA table_info 才決定要不要加，可安全重複執行，
        # 也涵蓋「從 data/backups 還原舊 snapshot 後再自動補欄位」的情境。
        _ensure_column(conn, "news", "summary", "TEXT")
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
    _initialized.add(str(DB_PATH))


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
                       (url, title, domain, category, sentiment, published_at, fetched_at,
                        coins, summary)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        a["url"], a["title"], a.get("domain", ""),
                        a.get("category", ""), a.get("sentiment", "neutral"),
                        a.get("published_at", ""), now, a.get("coins", ""),
                        # 非必填欄位一律用 a.get(欄位, 預設值)：不是每個呼叫端都會給
                        # summary（HackerNews 回補建的 dict 就沒有這個 key）。寫成
                        # a["summary"] 會讓那批整批進到下面的 except 被吞掉，表面上
                        # 只看到 saved=0，變成靜默不存任何新聞。
                        a.get("summary", ""),
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


def source_stats(top: int = 12) -> dict:
    """
    新聞來源的實際分布（前端「資料來源」標示用）。

    為什麼要查實際資料而不是寫死清單：前端原本寫死
    「CoinTelegraph · CoinDesk · Decrypt」三家，但庫裡實際有數百個網域，
    最大宗是動區 BlockTempo，而那三家合計只佔約四分之一——
    寫死的清單不只是漏標，是會讓人誤以為新聞只來自那三家英文媒體。

    domain 以 'GN:' 開頭者＝經 Google News 聚合進來的來源（非我們直接訂閱的 RSS），
    這裡照實分開標示，讓讀者知道哪些是直接來源、哪些是聚合來的。
    """
    with _connect() as conn:
        total, domains = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT domain) FROM news").fetchone()
        rows = conn.execute(
            "SELECT domain, COUNT(*) n FROM news GROUP BY domain "
            "ORDER BY n DESC LIMIT ?", (top,)).fetchall()
        aggregated = conn.execute(
            "SELECT COUNT(*) FROM news WHERE domain LIKE 'GN:%'").fetchone()[0]
    return {
        "total": int(total or 0),
        "domains": int(domains or 0),
        "aggregated": int(aggregated or 0),      # 經 Google News 聚合的則數
        "top": [{"domain": r["domain"], "count": r["n"],
                 "via_aggregator": str(r["domain"] or "").startswith("GN:")}
                for r in rows],
    }


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


# 這裡刻意「不」呼叫 init_db()：import 一個模組不該對正式資料庫做 schema 變更。
# 建表時機有兩個入口——backend/main.py 的 lifespan 明確呼叫 ensure_ready()，
# 以及 _connect() 在第一次真的要讀寫資料庫時自動補做。
