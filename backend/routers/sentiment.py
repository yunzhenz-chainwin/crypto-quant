"""
sentiment.py — 市場情緒 API 路由

端點：
  GET  /api/sentiment/fear_greed      恐懼貪婪指數（alternative.me，免費）
  GET  /api/sentiment/news            最新新聞（RSS 即時抓取並存入 DB）
  GET  /api/sentiment/news/history    查詢歷史新聞（依日期，從 SQLite）
  GET  /api/sentiment/news/dates      資料庫中有紀錄的日期清單
  GET  /api/sentiment/summary         每日新聞情緒分數（全市場或單幣，讀彙總表）
  POST /api/sentiment/news/backfill   回補歷史新聞（HackerNews 免費 API）

新聞來源（全部免費、免金鑰）：
  即時（每 30 分鐘）：9 家 RSS（英文 6 + 中文 2 + 原 3 家）＋ Google News 中文聚合（市場級）
  幣種級（每日）    ：Google News 逐幣查詢（中文，如「以太幣 OR ethereum」）
  歷史              ：HackerNews Algolia API，不需帳號，可追溯至 2006 年

情緒判讀：加權中英雙語詞庫（v2）。舊版純英文等權詞庫有 87% 新聞被判 neutral 的問題；
GPT 批次標註為下一階段（需金鑰），詞庫版永遠保留作為降級方案。
"""
import re
import time
import feedparser
import requests
from fastapi import APIRouter
from backend.services.news_store import (
    save_articles, query_by_date, available_dates, total_count,
    aggregate_daily, load_sentiment_daily,
)
from backend.services.reader import load_fear_greed_history

router = APIRouter()

# ── 記憶體快取 ───────────────────────────────────────────────────────────────
# 避免每次 API 請求都重新抓取外部資料
# 格式：{ "cache_key": { "ts": 存入時間, "data": 資料 } }
_cache = {}
CACHE_TTL = 1800  # 新聞快取 30 分鐘（避免請求太頻繁）

# ── RSS 新聞來源（全部免費，不需要 API 金鑰；2026-07-02 全數實測可用）────────
RSS_SOURCES = [
    ("CoinTelegraph",   "https://cointelegraph.com/rss"),
    ("CoinDesk",        "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Decrypt",         "https://decrypt.co/feed"),
    ("TheBlock",        "https://www.theblock.co/rss.xml"),
    ("CryptoSlate",     "https://cryptoslate.com/feed/"),
    ("Blockworks",      "https://blockworks.co/feed/"),
    ("BitcoinMagazine", "https://bitcoinmagazine.com/feed"),
    ("動區BlockTempo",   "https://www.blocktempo.com/feed/"),
    ("鏈新聞ABMedia",    "https://abmedia.io/feed/"),
]

# Google News RSS 聚合（免金鑰）：一條查詢可撈全網 ~100 篇，含中文媒體。
# 市場級查詢加進 30 分鐘排程；幣種級查詢（15 幣）走每日排程，見 fetch_coin_news_google()。
GOOGLE_NEWS_MARKET = (
    "https://news.google.com/rss/search?"
    "q=%E5%8A%A0%E5%AF%86%E8%B2%A8%E5%B9%A3%20OR%20%E6%AF%94%E7%89%B9%E5%B9%A3%20OR%20crypto"
    "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
)

# ── 情緒詞庫 v2（加權、中英雙語）────────────────────────────────────────────
# 英文：整字比對（split 後查集合）；中文：子字串比對（中文無空白分詞）。
# 權重 2 = 強烈字（暴漲/暴跌/駭客…），1 = 一般字。分數 = Σ多方 − Σ空方。
BULL_EN = {
    "surge": 2, "soar": 2, "rally": 2, "skyrocket": 2, "breakout": 2, "ath": 2,
    "rise": 1, "rises": 1, "gain": 1, "gains": 1, "jump": 1, "jumps": 1, "climb": 1,
    "rebound": 1, "recover": 1, "recovery": 1, "bullish": 2, "bull": 1, "record": 1,
    "high": 1, "approve": 1, "approved": 1, "approval": 1, "adoption": 1, "adopt": 1,
    "buy": 1, "buys": 1, "buying": 1, "accumulate": 1, "invest": 1, "investment": 1,
    "launch": 1, "launches": 1, "partnership": 1, "inflow": 2, "inflows": 2,
    "growth": 1, "win": 1, "wins": 1, "pass": 1, "passes": 1, "boost": 1,
    "upgrade": 1, "milestone": 1, "optimism": 1, "optimistic": 1, "green": 1,
}
BEAR_EN = {
    "crash": 2, "plunge": 2, "plunges": 2, "tumble": 2, "collapse": 2, "dump": 2,
    "selloff": 2, "sell-off": 2, "liquidation": 2, "liquidations": 2, "hack": 2,
    "hacked": 2, "exploit": 2, "stolen": 2, "scam": 2, "fraud": 2, "ponzi": 2,
    "fall": 1, "falls": 1, "drop": 1, "drops": 1, "decline": 1, "declines": 1,
    "slide": 1, "slides": 1, "bearish": 2, "bear": 1, "low": 1, "lows": 1,
    "ban": 1, "bans": 1, "sell": 1, "sells": 1, "selling": 1, "warning": 1,
    "warns": 1, "fear": 1, "loss": 1, "losses": 1, "risk": 1, "suspend": 1,
    "halt": 1, "halts": 1, "arrest": 1, "arrested": 1, "lawsuit": 1, "sue": 1,
    "sues": 1, "penalty": 1, "fine": 1, "fined": 1, "seized": 1, "outflow": 2,
    "outflows": 2, "delist": 2, "bankrupt": 2, "bankruptcy": 2, "red": 1,
}
BULL_ZH = {
    "暴漲": 2, "大漲": 2, "飆漲": 2, "狂飆": 2, "創新高": 2, "歷史新高": 2, "突破": 1,
    "上漲": 1, "漲幅": 1, "反彈": 1, "回升": 1, "走高": 1, "看多": 2, "看漲": 2,
    "利多": 2, "利好": 2, "買入": 1, "加倉": 1, "增持": 1, "布局": 1, "流入": 2,
    "通過": 1, "批准": 1, "採用": 1, "合作": 1, "上線": 1, "牛市": 2, "回暖": 1,
    "樂觀": 1, "噴出": 2, "衝上": 1, "站上": 1, "強彈": 2, "收復": 1, "漲逾": 1,
    # 簡體變體（Google News zh-TW 仍會混入簡中媒體，繁體詞比對不到）
    "上涨": 1, "大涨": 2, "暴涨": 2, "飙涨": 2, "创新高": 2, "历史新高": 2,
    "反弹": 1, "涨幅": 1, "涨逾": 1, "买入": 1, "加仓": 1, "利于": 1, "乐观": 1,
}
BEAR_ZH = {
    "暴跌": 2, "大跌": 2, "崩盤": 2, "重挫": 2, "跳水": 2, "血洗": 2, "創新低": 2,
    "下跌": 1, "跌幅": 1, "走低": 1, "回落": 1, "下挫": 1, "看空": 2, "看跌": 2,
    "利空": 2, "拋售": 2, "清算": 2, "爆倉": 2, "流出": 2, "駭客": 2, "被盜": 2,
    "詐騙": 2, "詐欺": 2, "跑路": 2, "禁止": 1, "打壓": 1, "監管趨嚴": 1, "起訴": 1,
    "訴訟": 1, "罰款": 1, "熊市": 2, "恐慌": 1, "警告": 1, "風險": 1, "破產": 2,
    "下架": 2, "凍結": 1, "跌破": 1, "裁員": 1, "失血": 2,
    # 簡體變體
    "崩盘": 2, "创新低": 2, "抛售": 2, "爆仓": 2, "黑客": 2, "被盗": 2,
    "诈骗": 2, "诉讼": 1, "罚款": 1, "风险": 1, "破产": 2, "冻结": 1, "裁员": 1,
}


def _sentiment(title: str) -> str:
    """
    加權雙語情緒判讀：英文整字 + 中文子字串，各自加權計分後相減。
    |分差| >= 1 就給方向（舊版等權且詞庫小，87% 標題被判 neutral → 情緒訊號失效）。
    """
    t = title.lower()
    words = set(re.split(r"[^a-z0-9$-]+", t))
    bull = sum(w for k, w in BULL_EN.items() if k in words)
    bear = sum(w for k, w in BEAR_EN.items() if k in words)
    bull += sum(w for k, w in BULL_ZH.items() if k in title)
    bear += sum(w for k, w in BEAR_ZH.items() if k in title)
    if bull > bear:
        return "bullish"
    if bear > bull:
        return "bearish"
    return "neutral"


# ── 新聞分類規則（依優先序排列；en=整字集合、zh=子字串）───────────────────────
# 越前面優先度越高：安全事件 > 監管法規 > 機構投資 > 技術發展 > 市場行情
CATEGORIES = [
    ("安全事件",
     {"hack", "hacked", "exploit", "scam", "fraud", "phishing", "stolen", "steal",
      "attack", "vulnerability", "breach", "seized", "ponzi", "rug", "rugpull"},
     ["駭客", "被盜", "漏洞", "攻擊", "詐騙", "詐欺", "釣魚", "跑路", "資安"]),
    ("監管法規",
     {"sec", "regulation", "regulator", "ban", "legal", "law", "congress", "senate",
      "bill", "government", "policy", "compliance", "court", "lawsuit", "cbdc",
      "sanction", "treasury", "finra", "cftc", "approve", "reject"},
     ["監管", "法規", "法案", "立法", "政府", "央行", "禁止", "合規", "訴訟", "法院",
      "制裁", "審查", "金管會"]),
    ("機構投資",
     {"etf", "fund", "institutional", "blackrock", "fidelity", "grayscale",
      "microstrategy", "reserve", "billion", "million", "corporate", "company",
      "invest", "purchase", "acquisition"},
     ["機構", "基金", "貝萊德", "灰度", "微策略", "儲備", "投資", "收購", "億美元",
      "上市公司", "財庫"]),
    ("技術發展",
     {"upgrade", "protocol", "network", "layer", "defi", "nft", "smart", "contract",
      "mainnet", "testnet", "developer", "update", "fork", "staking", "wallet",
      "bridge", "rollup"},
     ["升級", "協議", "主網", "測試網", "智能合約", "質押", "錢包", "跨鏈", "擴容",
      "開發者", "空投"]),
    ("市場行情",
     {"price", "market", "trading", "bull", "bear", "rally", "crash", "surge",
      "drop", "high", "low", "volume", "support", "resistance", "ath", "correction"},
     ["價格", "行情", "走勢", "漲", "跌", "牛市", "熊市", "支撐", "壓力", "成交量",
      "盤整", "波動"]),
]


def _categorize(title: str) -> str:
    """依標題關鍵字自動分類（英文整字 + 中文子字串；順序決定優先度）。"""
    words = set(title.lower().replace(",", " ").replace(".", " ").split())
    for name, kw_en, kw_zh in CATEGORIES:
        if (words & kw_en) or any(k in title for k in kw_zh):
            return name
    return "市場行情"  # 沒有符合的關鍵字就歸入最通用的市場行情


# ── 幣種標記：標題比對到哪些幣（ticker / 英文全名 / 中文名）────────────────────
# 英文全名對照（設定檔只有 zh + ticker）；比對時 ticker 與全名用整字、中文用子字串。
COIN_EN_NAMES = {
    "BTC": ["bitcoin"], "ETH": ["ethereum", "ether"], "SOL": ["solana"],
    "BNB": ["binance coin"], "XRP": ["ripple"], "DOGE": ["dogecoin"],
    "LINK": ["chainlink"], "ADA": ["cardano"], "AVAX": ["avalanche"],
    "DOT": ["polkadot"], "ATOM": ["cosmos"], "POL": ["polygon"],
    "UNI": ["uniswap"], "LTC": ["litecoin"], "NEAR": ["near protocol"],
}


def _coin_patterns() -> list[tuple[str, list[str], list[str]]]:
    """[(ticker, [英文整字...], [中文子字串...]), ...]，來源 = 後台幣種設定。"""
    from backend.services.app_db import get_coins
    pats = []
    for c in get_coins():
        tk = (c.get("ticker") or c["symbol"].replace("USDT", "")).upper()
        en = [tk.lower()] + COIN_EN_NAMES.get(tk, [])
        zh = [c["zh"]] if c.get("zh") and not c["zh"].isascii() else []
        pats.append((tk, en, zh))
    return pats


def _match_coins(title: str) -> str:
    """回傳標題相關的幣種 ticker，逗號分隔（如 "BTC,ETH"）；無則空字串。"""
    t = title.lower()
    words = set(re.split(r"[^a-z0-9$]+", t))
    hits = []
    for tk, en_names, zh_names in _coin_patterns():
        hit = any(n in words for n in en_names if " " not in n) \
           or any(n in t for n in en_names if " " in n) \
           or any(n in title for n in zh_names)
        if hit:
            hits.append(tk)
    return ",".join(hits)


def _parse_rss_date(entry) -> str:
    """
    RSS 的 published 欄位是 RFC822 格式（例如 'Wed, 24 Jun 2026 10:00:00 +0000'），
    直接取前 10 字會變成 'Wed, 24 Ju' 這種亂碼日期。

    feedparser 已幫我們解析成 struct_time（published_parsed），用它轉成 YYYY-MM-DD
    才正確；若來源沒提供則退回 updated_parsed，再不行就留空字串。
    """
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if t:
        try:
            return time.strftime("%Y-%m-%d", t)
        except Exception:
            return ""
    return ""


def _entry_to_article(entry, source_name: str) -> dict:
    """feedparser entry → 標準文章 dict（含情緒 / 分類 / 幣種標記）。"""
    title = entry.title.strip()
    domain = source_name
    # Google News 的標題尾巴帶「 - 媒體名」，拆出來當 domain、標題留乾淨的部分
    if source_name.startswith("GoogleNews"):
        src = getattr(entry, "source", None)
        media = (src.get("title") if isinstance(src, dict) else getattr(src, "title", "")) or ""
        if " - " in title:
            title = title.rsplit(" - ", 1)[0].strip()
        domain = f"GN:{media}" if media else "GoogleNews"
    return {
        "title":        title,
        "url":          entry.link,
        "published_at": _parse_rss_date(entry),  # RFC822 → YYYY-MM-DD
        "domain":       domain,
        "sentiment":    _sentiment(title),
        "category":     _categorize(title),
        "coins":        _match_coins(title),
    }


def _fetch_and_save() -> list:
    """
    從 9 家 RSS ＋ Google News 中文聚合抓取最新新聞，存入 SQLite，回傳所有文章

    - 有快取（30 分鐘），避免頻繁請求讓來源封鎖
    - 每個來源最多取 25 篇（Google News 取 40），避免包含太舊的文章
    - INSERT OR IGNORE + 標題去重確保不重複
    - 存檔後滾動更新「昨天+今天」的每日情緒彙總（news_sentiment_daily）
    """
    now = time.time()
    # 快取未過期則直接回傳，不重新抓取
    if "rss_all" in _cache and now - _cache["rss_all"]["ts"] < CACHE_TTL:
        return _cache["rss_all"]["data"]

    all_items = []
    source_stats = []
    for source_name, url in [*RSS_SOURCES, ("GoogleNews中文", GOOGLE_NEWS_MARKET)]:
        try:
            feed = feedparser.parse(url)
            limit = 40 if source_name.startswith("GoogleNews") else 25
            for entry in feed.entries[:limit]:
                all_items.append(_entry_to_article(entry, source_name))
            source_stats.append(f"{source_name}:{min(len(feed.entries), limit)}")
        except Exception:
            source_stats.append(f"{source_name}:ERR")
            continue  # 單一來源失敗不影響其他來源

    # 依發布日期排序，最新的排前面
    all_items.sort(key=lambda x: x["published_at"], reverse=True)

    saved = save_articles(all_items)
    if saved:
        print(f"[news] saved {saved} new articles ({' '.join(source_stats)})")
    try:
        aggregate_daily()          # 滾動重算 昨天+今天 的每日情緒分數
    except Exception as e:
        print(f"[news] aggregate skip: {e}")

    _cache["rss_all"] = {"ts": now, "data": all_items}
    return all_items


def fetch_coin_news_google(symbols: list[str], per_coin: int = 25) -> int:
    """
    幣種級 Google News 查詢（每日排程用；15 幣 = 15 次請求，太頻繁會被擋故不放 30 分鐘排程）。
    查詢字 = 中文名 OR 英文全名（如「以太幣 OR ethereum」），語系 zh-TW。
    回傳實際新增筆數。
    """
    from urllib.parse import quote
    from backend.services.app_db import get_coins
    zh_map = {c["symbol"]: c.get("zh", "") for c in get_coins()}
    total = 0
    for sym in symbols:
        tk = sym.replace("USDT", "")
        terms = [zh_map.get(sym, ""), *COIN_EN_NAMES.get(tk, [tk.lower()])]
        q = " OR ".join(t for t in terms if t)
        url = (f"https://news.google.com/rss/search?q={quote(q)}"
               f"&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
        try:
            feed = feedparser.parse(url)
            items = [_entry_to_article(e, "GoogleNews幣種") for e in feed.entries[:per_coin]]
            # 幣種查詢來的新聞至少掛上該幣標記（標題比對可能漏掉衍生寫法）
            for it in items:
                if tk not in (it["coins"] or "").split(","):
                    it["coins"] = f"{it['coins']},{tk}".strip(",")
            total += save_articles(items)
            time.sleep(1)          # 溫和節流
        except Exception:
            continue
    return total


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


# ── 恐懼貪婪歷史(讀 DB,供前台歷史走勢圖)────────────────────────────────────
@router.get("/sentiment/fear_greed/history")
def fear_greed_history(days: int = 365):
    """恐懼貪婪指數歷史(全市場),來源 fear_greed 表(排程回補,可追溯至 2018)。"""
    return load_fear_greed_history(days=days)


# ── 每日新聞情緒分數(讀彙總表 news_sentiment_daily)──────────────────────────
@router.get("/sentiment/summary")
def sentiment_summary(symbol: str = "MARKET", days: int = 30):
    """
    每日新聞情緒分數走勢：-100(極空) ~ +100(極多)。
    symbol 給幣種代號(BTCUSDT / BTC 皆可)看單幣；不給或 MARKET = 全市場。
    來源：news_sentiment_daily(30 分鐘排程滾動更新今日,幣種級新聞每日回補)。
    """
    sym = (symbol or "MARKET").upper().replace("USDT", "")
    days = max(1, min(days, 120))
    return {"symbol": sym, "daily": load_sentiment_daily(sym, days)}


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
