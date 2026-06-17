"""
sentiment.py — 市場情緒 API 路由

端點：
  GET  /api/sentiment/fear_greed      恐懼貪婪指數（alternative.me，免費）
  GET  /api/sentiment/news            最新新聞（RSS 即時抓取並存入 DB）
  GET  /api/sentiment/news/history    查詢歷史新聞（依日期，從 SQLite）
  GET  /api/sentiment/news/dates      資料庫中有紀錄的日期清單
  POST /api/sentiment/news/backfill   回補歷史新聞（HackerNews 免費 API）

新聞來源：
  即時：CoinTelegraph / CoinDesk / Decrypt RSS，排程每 30 分鐘更新
  歷史：HackerNews Algolia API，不需帳號，可追溯至 2006 年
"""
import time
import feedparser
import requests
from fastapi import APIRouter
from backend.services.news_store import save_articles, query_by_date, available_dates, total_count

router = APIRouter()

# ── 記憶體快取 ───────────────────────────────────────────────────────────────
# 避免每次 API 請求都重新抓取外部資料
# 格式：{ "cache_key": { "ts": 存入時間, "data": 資料 } }
_cache = {}
CACHE_TTL = 1800  # 新聞快取 30 分鐘（避免請求太頻繁）

# ── RSS 新聞來源（全部免費，不需要 API 金鑰）───────────────────────────────────
RSS_SOURCES = [
    ("CoinTelegraph", "https://cointelegraph.com/rss"),
    ("CoinDesk",      "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Decrypt",       "https://decrypt.co/feed"),
]

# ── 情緒關鍵字 ───────────────────────────────────────────────────────────────
# 把標題拆成單字，計算符合 BULL / BEAR 哪一組較多，多的那邊決定情緒
BULL_WORDS = {
    "surge", "rally", "gain", "rise", "bull", "high", "record",
    "approve", "adoption", "buy", "invest", "launch", "partnership",
    "etf", "inflow", "growth", "soar", "jump", "win", "pass", "boost",
}
BEAR_WORDS = {
    "crash", "fall", "drop", "bear", "low", "ban", "hack", "scam",
    "fraud", "sell", "dump", "warning", "fear", "loss", "risk",
    "suspend", "halt", "decline", "plunge", "tumble", "arrest",
    "lawsuit", "penalty", "seized",
}

# ── 新聞分類規則（依優先序排列）─────────────────────────────────────────────
# 越前面優先度越高：安全事件 > 監管法規 > 機構投資 > 技術發展 > 市場行情
# 「市場行情」放最後，作為無其他符合時的預設值（fallback）
CATEGORIES = [
    ("安全事件", {
        "hack", "hacked", "exploit", "scam", "fraud", "phishing",
        "stolen", "steal", "attack", "vulnerability", "breach",
        "seized", "ponzi", "rug", "rugpull",
    }),
    ("監管法規", {
        "sec", "regulation", "regulator", "ban", "legal", "law",
        "congress", "senate", "bill", "government", "policy",
        "compliance", "court", "lawsuit", "cbdc", "sanction",
        "treasury", "finra", "cftc", "approve", "reject",
    }),
    ("機構投資", {
        "etf", "fund", "institutional", "blackrock", "fidelity",
        "grayscale", "microstrategy", "reserve", "billion", "million",
        "corporate", "company", "invest", "purchase", "acquisition",
    }),
    ("技術發展", {
        "upgrade", "protocol", "network", "layer", "defi", "nft",
        "smart", "contract", "mainnet", "testnet", "developer",
        "update", "fork", "staking", "wallet", "bridge", "rollup",
    }),
    ("市場行情", {
        "price", "market", "trading", "bull", "bear", "rally",
        "crash", "surge", "drop", "high", "low", "volume",
        "support", "resistance", "ath", "correction",
    }),
]


def _categorize(title: str) -> str:
    """
    依標題關鍵字自動分類新聞
    把標題拆成單字集合，與每個分類的關鍵字取交集（&）
    第一個有交集的分類就是結果（所以排列順序決定優先度）
    """
    words = set(title.lower().replace(",", " ").replace(".", " ").split())
    for name, keywords in CATEGORIES:
        if words & keywords:
            return name
    return "市場行情"  # 沒有符合的關鍵字就歸入最通用的市場行情


def _sentiment(title: str) -> str:
    """
    依標題關鍵字判斷情緒（看多 / 看空 / 中立）
    計算 BULL_WORDS 和 BEAR_WORDS 各出現幾個，多的那邊獲勝
    """
    words = set(title.lower().split())
    bull = len(words & BULL_WORDS)
    bear = len(words & BEAR_WORDS)
    if bull > bear:
        return "bullish"
    if bear > bull:
        return "bearish"
    return "neutral"


def _fetch_and_save() -> list:
    """
    從三個 RSS 來源抓取最新新聞，存入 SQLite，回傳所有文章

    - 有快取（30 分鐘），避免頻繁請求讓來源封鎖
    - 每個來源最多取 25 篇，避免包含太舊的文章
    - INSERT OR IGNORE 確保重複 URL 自動略過
    """
    now = time.time()
    # 快取未過期則直接回傳，不重新抓取
    if "rss_all" in _cache and now - _cache["rss_all"]["ts"] < CACHE_TTL:
        return _cache["rss_all"]["data"]

    all_items = []
    for source_name, url in RSS_SOURCES:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:25]:
                title = entry.title.strip()
                all_items.append({
                    "title":        title,
                    "url":          entry.link,
                    "published_at": entry.get("published", "")[:10],  # 只取日期部分
                    "domain":       source_name,
                    "sentiment":    _sentiment(title),
                    "category":     _categorize(title),
                })
        except Exception:
            continue  # 單一來源失敗不影響其他來源

    # 依發布日期排序，最新的排前面
    all_items.sort(key=lambda x: x["published_at"], reverse=True)

    saved = save_articles(all_items)
    if saved:
        print(f"[news] saved {saved} new articles")

    _cache["rss_all"] = {"ts": now, "data": all_items}
    return all_items


def _group_by_category(items: list) -> list:
    """
    把文章列表依分類分組，以固定順序回傳
    固定順序：市場行情 → 監管法規 → 機構投資 → 技術發展 → 安全事件
    只回傳有文章的分類（避免顯示空的 tab）
    """
    ORDER = ["市場行情", "監管法規", "機構投資", "技術發展", "安全事件"]
    groups: dict[str, list] = {}
    for item in items:
        cat = item.get("category", "市場行情")
        groups.setdefault(cat, []).append(item)
    return [{"name": c, "items": groups[c]} for c in ORDER if c in groups]


# ── 恐懼貪婪指數 ─────────────────────────────────────────────────────────────
@router.get("/sentiment/fear_greed")
def fear_greed(limit: int = 30):
    """
    取得恐懼貪婪指數（0=極度恐慌，100=極度貪婪）
    來源：alternative.me，完全免費，不需要 API 金鑰
    快取 1 小時（該指數每天只更新一次，無需頻繁請求）
    """
    now = time.time()
    key = f"fng_{limit}"
    if key in _cache and now - _cache[key]["ts"] < 3600:  # 1 小時快取
        return _cache[key]["data"]
    resp = requests.get(
        f"https://api.alternative.me/fng/?limit={limit}", timeout=10
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    _cache[key] = {"ts": now, "data": data}
    return data


# ── 最新新聞 ─────────────────────────────────────────────────────────────────
@router.get("/sentiment/news")
def crypto_news(symbol: str = None, limit: int = 40):
    """
    從 RSS 取得最新新聞，同時存入資料庫

    Args:
        symbol: 幣種代號（例如 BTCUSDT），有傳則優先顯示相關新聞
        limit:  最多回傳幾篇

    若指定幣種但相關文章不足 5 篇，退回顯示全部（避免空白畫面）
    """
    try:
        all_items = _fetch_and_save()
        if symbol:
            ticker = symbol.replace("USDT", "").upper()  # BTCUSDT → BTC
            filtered = [
                i for i in all_items
                if ticker in i["title"].upper()
                or "BITCOIN" in i["title"].upper()
                or "CRYPTO" in i["title"].upper()
            ]
            items = filtered if len(filtered) >= 5 else all_items
        else:
            items = all_items

        return {
            "categories": _group_by_category(items[:limit]),
            "total":      min(len(items), limit),
        }
    except Exception as e:
        return {"categories": [], "total": 0, "error": str(e)}


# ── 歷史新聞查詢 ─────────────────────────────────────────────────────────────
@router.get("/sentiment/news/history")
def news_history(date: str, category: str = None):
    """
    查詢指定日期的歷史新聞（從 SQLite 資料庫）

    Args:
        date:     日期，格式 YYYY-MM-DD
        category: 可選分類（市場行情 / 監管法規 / 機構投資 / 技術發展 / 安全事件）
    """
    items = query_by_date(date, category or None)
    # 排程每 30 分鐘跑一次，同一 URL 當天可能被存入多次，這裡去重
    seen = set()
    unique = []
    for item in items:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)
    return {
        "date":       date,
        "categories": _group_by_category(unique),
        "total":      len(unique),
    }


# ── 有資料的日期清單 ─────────────────────────────────────────────────────────
@router.get("/sentiment/news/dates")
def news_dates():
    """
    回傳資料庫中有新聞的日期清單（最近 90 天）及總筆數
    前端「歷史查詢」下拉選單的資料來源
    """
    return {"dates": available_dates(), "total": total_count()}


# ── 歷史回補核心邏輯 ─────────────────────────────────────────────────────────
def _hn_fetch_range(from_date: str, to_date: str) -> int:
    """
    從 HackerNews Algolia API 撈指定日期範圍的加密幣新聞

    選用 HackerNews 的原因：
    - 完全免費，不需要 API 金鑰和帳號
    - 資料可追溯到 2006 年
    - Algolia 搜尋引擎支援時間戳範圍過濾（numericFilters）

    重要注意事項：
    - HN Algolia API 不支援 "bitcoin OR ethereum" 語法
    - 改為每個關鍵字分別查詢，最後合併去重

    回傳：實際新存入資料庫的筆數
    """
    import datetime as dt
    from urllib.parse import urlparse

    # 轉換成 Unix timestamp（秒），Algolia 用這格式做時間過濾
    start_ts = int(dt.datetime.strptime(from_date, "%Y-%m-%d").timestamp())
    # 結束日期 +1 天，讓 to_date 當天的文章也包含在內
    end_ts   = int(dt.datetime.strptime(to_date, "%Y-%m-%d").timestamp()) + 86400

    KEYWORDS = ["bitcoin", "ethereum", "cryptocurrency", "crypto", "blockchain"]
    seen_urls    = set()   # 跨關鍵字去重，避免同一篇被存入多次
    all_articles = []

    for keyword in KEYWORDS:
        page = 0
        while True:
            try:
                resp = requests.get(
                    "https://hn.algolia.com/api/v1/search",
                    params={
                        "query":          keyword,
                        "tags":           "story",   # 只取貼文，排除留言
                        "numericFilters": f"created_at_i>{start_ts},created_at_i<{end_ts}",
                        "hitsPerPage":    50,         # 每頁最多 50 筆
                        "page":           page,
                    },
                    timeout=15,
                )
                data  = resp.json()
                hits  = data.get("hits", [])
                pages = data.get("nbPages", 0)  # API 回傳的總頁數

                if not hits:
                    break

                for h in hits:
                    title = h.get("title", "").strip()
                    if not title:
                        continue

                    # Ask HN / Show HN 等自投稿沒有外部連結，改用 HN 文章頁面 URL
                    url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID', '')}"

                    # 跨關鍵字去重（同一篇可能被多個關鍵字搜到）
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    # 將 Unix timestamp 轉成日期字串
                    pub_date = dt.datetime.fromtimestamp(h.get("created_at_i", 0)).strftime("%Y-%m-%d")

                    # 從 URL 取網域，例如 coindesk.com
                    try:
                        domain = urlparse(url).netloc.replace("www.", "") or "HackerNews"
                    except Exception:
                        domain = "HackerNews"

                    all_articles.append({
                        "title":        title,
                        "url":          url,
                        "published_at": pub_date,
                        "domain":       domain,
                        "sentiment":    _sentiment(title),
                        "category":     _categorize(title),
                    })

                page += 1
                if page >= pages or page >= 10:  # 每個關鍵字最多抓 10 頁 = 500 篇
                    break

                time.sleep(0.2)  # 稍微暫停，避免請求太密集被限流

            except Exception as e:
                print(f"[backfill] {keyword} page {page} error: {e}")
                break

    # 所有關鍵字查完後，一次性批次存入（重複 URL 自動略過）
    return save_articles(all_articles)


# ── 歷史回補 API ─────────────────────────────────────────────────────────────
@router.post("/sentiment/news/backfill")
def backfill_news(from_date: str, to_date: str):
    """
    回補歷史新聞：從 HackerNews 抓取指定日期範圍的加密幣文章存入資料庫

    Args:
        from_date: 起始日期，格式 YYYY-MM-DD
        to_date:   結束日期，格式 YYYY-MM-DD

    建議一次不超過 1 個月，太長會耗時較久（每個月約 100~500 篇）
    """
    try:
        saved = _hn_fetch_range(from_date, to_date)
        return {
            "ok":        True,
            "from_date": from_date,
            "to_date":   to_date,
            "saved":     saved,         # 這次新增的筆數
            "db_total":  total_count(), # 資料庫目前的總筆數
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
