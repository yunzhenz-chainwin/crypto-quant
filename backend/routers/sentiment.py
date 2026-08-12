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
import html
import re
import time
from datetime import datetime, timezone
import feedparser
import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from backend.routers.admin import require_admin   # 寫入型端點的登入保護
from backend.services.rate_limiter import RATE_LIMITER, enforce_rate_limit
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

# 中文別名／簡體變體。後台幣種設定每顆幣只能填一個中文名（app_db.DEFAULT_COINS），
# 但中文語料是這個庫的大宗（動區 1335 則、鏈新聞 817 則，再加上大量 GN:* 中文媒體），
# 而它們的用字不會剛好等於後台那一個：繁簡混用、同一顆幣好幾種譯名。
#
# 為什麼現在才需要補：舊版的幣種過濾有 "CRYPTO" 萬用條件，幾乎永遠篩得到東西，
# 漏標看不出來。改成嚴格讀 coins 欄之後，漏標就等於「這篇新聞從該幣的清單裡消失」。
# 實測 2026-07-01 之後有 137 則標題明確點名某顆幣、coins 欄卻是空的（BTC 107、ETH 30）。
#
# 收錄原則：只放「幾乎不會出現在其他語境」的詞。刻意不收的例子——
#   幣安／币安（交易所名，大量非 BNB 新聞都會提到）、雪崩（天災）、宇宙（太常見）、
#   比特（會命中「比特幣」以外的詞）。寧可漏標也不要誤標：誤標會寫進 news.coins
#   永久保存，還會污染 aggregate_daily() 的單幣情緒分組。
#
# 未收錄的四顆幣：LINK 的後台中文名是「鏈鏈」（疑似打錯，中文媒體多半直接寫
# Chainlink）；POL／UNI／NEAR 的後台中文名是純 ASCII（Polygon／Uniswap／Near幣），
# 會被 _coin_patterns() 的 isascii() 判斷濾掉 —— 這四顆目前只靠英文比對。
COIN_ZH_ALIASES = {
    "BTC":  ["比特币"],
    "ETH":  ["以太幣", "以太币", "乙太坊", "乙太幣"],
    "SOL":  ["索拉纳"],
    "BNB":  ["币安币"],
    "XRP":  ["瑞波币"],
    "DOGE": ["狗狗币"],
    "ADA":  ["艾达币", "卡爾達諾", "卡尔达诺"],
    "AVAX": ["雪崩币"],
    "DOT":  ["波卡幣", "波卡币"],
    "ATOM": ["宇宙币"],
    "LTC":  ["莱特币"],
}


# _coin_patterns() 每篇文章都會被呼叫一次，而它每次都重新開 app.db 讀 get_coins()。
# 實測約 2.4 ms/次：一輪 RSS 265 篇 ≈ 0.64 s、每日幣種級 375 篇 ≈ 0.9 s，全都花在
# 重複開檔上，納入摘要後比對量還會更大。
# 幣種設定可由後台隨時修改（admin.py 的 coins_add / coins_update / coins_remove），
# 所以不能永久快取 —— 用短 TTL 自我失效就夠：抓取排程是每 30 分鐘一輪，TTL 300 秒
# 等於「同一輪共用一份、下一輪必定重讀」，後台改完最多 5 分鐘生效，而下一批新聞
# 本來就要等最多 30 分鐘才進來，所以這個延遲在外部完全觀察不到。
_COIN_PATTERNS_TTL = 300
_coin_patterns_cache = {"ts": 0.0, "data": None}


def _coin_patterns() -> list[tuple[str, list[str], list[str]]]:
    """[(ticker, [英文整字...], [中文子字串...]), ...]，來源 = 後台幣種設定（短 TTL 快取）。"""
    now = time.time()
    if _coin_patterns_cache["data"] is not None \
       and now - _coin_patterns_cache["ts"] < _COIN_PATTERNS_TTL:
        return _coin_patterns_cache["data"]
    from backend.services.app_db import get_coins
    pats = []
    for c in get_coins():
        tk = (c.get("ticker") or c["symbol"].replace("USDT", "")).upper()
        en = [tk.lower()] + COIN_EN_NAMES.get(tk, [])
        # 後台設定的中文名（純 ASCII 的視同沒填）＋ 內建別名；dict.fromkeys 去重保序，
        # 避免後台之後把中文名改成剛好等於某個別名時出現重複比對。
        zh_cfg = [c["zh"]] if c.get("zh") and not c["zh"].isascii() else []
        zh = list(dict.fromkeys(zh_cfg + COIN_ZH_ALIASES.get(tk, [])))
        pats.append((tk, en, zh))
    # 只有成功組完才寫入快取；get_coins() 若拋例外就照舊往外拋，不會快取到壞值
    _coin_patterns_cache["data"] = pats
    _coin_patterns_cache["ts"] = now
    return pats


# 這些英文全名同時是普通英文字（ripple effect／an avalanche of selling／the cosmos／
# polygon／into the ether），只在「標題」比對時採用，掃摘要內文一律跳過。
# 實測語料（正式庫 11,178 則標題）：cosmos 的 145 次命中幾乎都是 NASA COSMOS、
# NVIDIA Cosmos、Cosmos Health、New York Cosmos，與 ATOM 無關；polygon 也混著
# Peugeot Polygon Concept 這類。標題只有 7.2 字都已如此，85 字的內文只會更糟。
SUMMARY_UNSAFE_EN = {"ether", "ripple", "avalanche", "cosmos", "polygon"}


def _coin_hits(text: str, strict: bool = False) -> list[str]:
    """
    回傳這段文字相關的幣種 ticker 清單（依 _coin_patterns() 的順序）。

    英文 ticker / 全名走整字比對、中文名走子字串比對。整字比對是關鍵：
    改成子字串會讓 UNI 命中 "community"、SOL 命中 "sold"、ETH 命中 "whether"。

    strict=True 是「給 RSS 摘要用」的收斂版本，只保留不會誤中的樣式：
      - 丟掉裸 ticker：near / uni / link / dot / atom / pol 這些本身就是英文字，
        整字比對在 7.2 字的標題上勉強可用，掃 500 字（約 85 字詞）的內文就是誤標
        機器。以正式語料的每字出現率外推到 85 字：near 19.7%、uni 7.8%、link 6.3%、
        dot 5.4%、atom 3.3%、pol 1.8% —— 等於每 5 篇市場新聞就有 1 篇被標成 NEAR。
        誤標會寫進 news.coins 永久保存，再污染 aggregate_daily() 的單幣分組與
        signal_engine 的「（全市場）」降級標註，所以摘要寧可漏標也不能誤標。
      - 丟掉 SUMMARY_UNSAFE_EN 那批「同時是普通英文字」的全名。
      - 改收 $TICKER 寫法（$btc / $near）：內文點名某幣的慣用寫法，且不會誤中
        （tokenizer 有保留 $，見下方 re.split 的字元集）。
      - 保留多字全名（near protocol / binance coin）與中文名：實測 11,178 則標題裡
        最可能誤中的「鏈鏈」也只命中 1 則，而且是真的 LINK 新聞。
    """
    t = text.lower()
    words = set(re.split(r"[^a-z0-9$]+", t))
    hits = []
    for tk, en_names, zh_names in _coin_patterns():
        if strict:
            # 一定要建新 list：_coin_patterns() 回的是共享快取物件，就地改會污染整份快取
            en_names = [n for n in en_names
                        if n != tk.lower() and n not in SUMMARY_UNSAFE_EN]
            en_names.append(f"${tk.lower()}")
        hit = any(n in words for n in en_names if " " not in n) \
           or any(n in t for n in en_names if " " in n) \
           or any(n in text for n in zh_names)
        if hit:
            hits.append(tk)
    return hits


def _match_coins(text: str) -> str:
    """標題用：相關幣種 ticker，逗號分隔（如 "BTC,ETH"）。比對規則見 _coin_hits()。"""
    return ",".join(_coin_hits(text))


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


# ── RSS 摘要：取值 + 去標籤 ──────────────────────────────────────────────────
# feedparser 6.x 已把 RSS 的 <description> 與 Atom 的 <summary> 正規化成同一個
# entry.summary（entry.description 只是別名，值完全相同），所以讀 summary 就夠；
# 少數只給 Atom <content> 的來源再退回 content[0]["value"]。
# 內容一律是 HTML 片段（<p>、<a>、&nbsp;、&amp;…），必須去標籤 + 解實體才能拿去比對。
# （feedparser 自己已會濾掉 <script>/<style>，這裡處理的是一般排版標籤。）
SUMMARY_RAW_MAX   = 4000   # 有些來源把整篇全文塞進 description，先限長避免做白工
SUMMARY_MAX_CHARS = 500    # 實際保留的純文字長度：夠比對幣種，又不會撐大 API 回應
_HTML_TAG_RE    = re.compile(r"<[^>]+>")
_HTML_TAIL_RE   = re.compile(r"<[^>]*$")   # 限長剛好切在標籤中間時留下的半截 "<a href=…
_WS_RE          = re.compile(r"\s+")
# WordPress 系來源的固定頁尾「The post … appeared first on 媒體名.」——
# 它會把媒體名塞進內文，像 Bitcoin Magazine 這種名字會讓每篇都被誤標成 BTC。
_FEED_FOOTER_RE = re.compile(r"\s*the post\b.*?appeared first on\b.*$", re.I | re.S)


def _strip_html(raw: str) -> str:
    """HTML 片段 → 純文字：去標籤、解實體（&amp; &nbsp; …）、砍來源頁尾、壓多餘空白。"""
    if not isinstance(raw, str) or not raw:
        return ""
    text = _HTML_TAG_RE.sub(" ", raw[:SUMMARY_RAW_MAX])
    text = _HTML_TAIL_RE.sub(" ", text)
    text = html.unescape(text)
    text = _HTML_TAG_RE.sub(" ", text)      # 解實體後可能再露出一層被跳脫的標籤
    text = _HTML_TAIL_RE.sub(" ", text)
    text = _FEED_FOOTER_RE.sub("", text)
    return _WS_RE.sub(" ", text.replace("\xa0", " ")).strip()


def _entry_summary(entry) -> str:
    """
    取 feedparser entry 的摘要純文字；來源沒給就回空字串。

    一律用 entry.get()，不要寫 entry.summary —— 來源沒有 <description> 時
    feedparser 連這個 key 都不會建立，屬性存取會直接丟 AttributeError。
    """
    raw = entry.get("summary") or ""
    if not raw:
        content = entry.get("content") or []      # Atom 只給 <content> 的來源
        if content:
            first = content[0]
            raw = (first.get("value") if isinstance(first, dict) else "") or ""
    return _strip_html(raw)[:SUMMARY_MAX_CHARS]


def _entry_to_article(entry, source_name: str) -> dict:
    """feedparser entry → 標準文章 dict（含摘要 / 情緒 / 分類 / 幣種標記）。"""
    title = entry.title.strip()
    summary = _entry_summary(entry)
    domain = source_name
    # Google News 的標題尾巴帶「 - 媒體名」，拆出來當 domain、標題留乾淨的部分
    if source_name.startswith("GoogleNews"):
        src = getattr(entry, "source", None)
        media = (src.get("title") if isinstance(src, dict) else getattr(src, "title", "")) or ""
        if " - " in title:
            title = title.rsplit(" - ", 1)[0].strip()
        domain = f"GN:{media}" if media else "GoogleNews"
        # Google News 的 description 沒有內文，只是「標題連結 + 媒體名」的 HTML。
        # 拿去比對等於把媒體名當內容（"Bitcoin Magazine" 會讓每篇都被標成 BTC），
        # 標題本身已經比對過了，這裡直接不用。
        summary = ""
    # 幣種標記：標題走完整比對，摘要只走 strict 版（不含裸 ticker 與普通英文字全名）。
    # 把整段摘要餵進完整比對會讓誤標暴增一個量級（見 _coin_hits() 的實測數字），
    # 而 coins 會寫進 DB 永久保存並被 aggregate_daily() 拿去分組，錯了就一路錯下去。
    coins = _coin_hits(title)
    if summary:
        coins += [tk for tk in _coin_hits(summary, strict=True) if tk not in coins]
    return {
        "title":        title,
        "url":          entry.link,
        "published_at": _parse_rss_date(entry),  # RFC822 → YYYY-MM-DD
        "domain":       domain,
        "summary":      summary,
        # ↓ 情緒與分類「只看標題」是刻意的，不要順手改成吃摘要 ↓
        # sentiment 會被存進 news 表，再由 news_store.aggregate_daily() 彙總成
        # news_sentiment_daily 這條歷史曲線（signal_engine 與前端都在讀）。
        # 一旦改成連摘要一起算，新舊文章的評分基準就不同，曲線會在改版當天出現
        # 人為斷層；而舊文章沒有摘要可用，重算也救不回來（實測：對標題追加約
        # 350 字內文後，60% 的文章情緒判讀會改變，其中還有 bull↔bear 直接反轉的）。
        # category 同理：實測「安全事件」佔比會從 3.8% 暴增到 21.7%，因為內文裡
        # 出現一次 attack / breach 就會壓過真正的主題。
        "sentiment":    _sentiment(title),
        "category":     _categorize(title),
        # 摘要只影響「這篇跟哪些幣有關」，不影響情緒與分類。但 coins 正是
        # news_store.aggregate_daily() 的分組依據：摘要多標一顆幣＝那顆幣當天的
        # 文章母體變大、分數跟著動（公式沒變，是分組成員變了），所以摘要那半段
        # 用 strict 比對，寧可漏標也不誤標。
        "coins":        ",".join(coins),
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
def _stored_fear_greed(limit: int) -> list[dict]:
    """Return the newest stored values using the external API response shape."""
    rows = load_fear_greed_history(days=limit)
    data = []
    for row in reversed(rows):
        date_value = str(row.get("date", ""))
        try:
            timestamp = int(
                datetime.strptime(date_value[:10], "%Y-%m-%d")
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )
        except ValueError:
            timestamp = None
        item = {
            "value": str(row.get("value", "")),
            "value_classification": row.get("label", "") or "",
            "time_until_update": None,
        }
        if timestamp is not None:
            item["timestamp"] = str(timestamp)
        data.append(item)
    return data


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

    try:
        # Do not inherit an invalid machine/shell proxy for this public endpoint.
        with requests.Session() as session:
            session.trust_env = False
            resp = session.get(
                f"https://api.alternative.me/fng/?limit={limit}", timeout=10
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
        if not isinstance(data, list):
            raise ValueError("fear and greed response data is not a list")
    except (requests.RequestException, ValueError):
        # A sentiment provider outage must not make the whole dashboard fail.
        if key in _cache:
            return _cache[key]["data"]
        data = _stored_fear_greed(limit)

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
MIN_COIN_ARTICLES = 5   # 單幣相關新聞少於這個數量就退回全市場，避免畫面開天窗


def _coin_tickers(item: dict) -> list[str]:
    """讀一則新聞的 coins 欄，回傳大寫 ticker 清單；沒有這欄或空值回空清單。

    coins 由 _match_coins() 以整字比對算出，是唯一可靠的幣種歸屬依據。
    舊版拿 ticker 對標題做子字串比對會誤中：UNI 命中 "community"、
    SOL 命中 "sold"、ETH 命中 "whether"。
    coins 可能是 None（本欄位加入之前的舊資料），所以一律 `or ""` 後再 split。
    """
    return [t.strip().upper() for t in (item.get("coins") or "").split(",") if t.strip()]


@router.get("/sentiment/news")
def crypto_news(symbol: str = None, limit: int = 40):
    """
    從 RSS 取得最新新聞，同時存入資料庫

    Args:
        symbol: 幣種代號（BTCUSDT / btcusdt / BTC 皆可），有傳則優先顯示相關新聞
        limit:  最多回傳幾篇

    幣種過濾走 coins 欄（整字比對的結果），與 ai_analyst.py 挑新聞的做法一致。
    舊版是拿 ticker 對標題做子字串比對，再 OR 上 "BITCOIN" / "CRYPTO" 兩條萬用條件：
    前者會誤中（UNI→community、SOL→sold、ETH→whether），後者幾乎讓過濾完全失效
    ——BTC 的新聞本來就會被標成 BTC，那兩條不只多餘，對非 BTC 幣種更是錯的。

    若該幣相關文章不足 MIN_COIN_ARTICLES 篇，仍退回顯示全市場（避免空白畫面），
    但這時 fell_back_to_market=True，且每則都帶 about_this_coin 讓前端分得出
    哪幾則真的跟這顆幣有關——不再讓使用者以為整頁都是這顆幣的新聞。
    """
    try:
        all_items = _fetch_and_save()
        # BTCUSDT / btcusdt / BTC → BTC。先 upper 再去尾綴，順序反過來會漏掉小寫的
        # usdt（舊版 symbol.replace("USDT","").upper() 就是這個順序，btcusdt 會算出
        # ticker="BTCUSDT" 而永遠對不上任何幣，靠萬用條件才沒穿幫）。
        # 用 removesuffix 而非 replace，避免把字串中段的 USDT 也切掉。
        ticker = (symbol or "").strip().upper().removesuffix("USDT") or None
        coin_total = None
        fell_back = False

        if ticker:
            mine = [i for i in all_items if ticker in _coin_tickers(i)]
            coin_total = len(mine)
            fell_back = coin_total < MIN_COIN_ARTICLES
            # 相關的太少就退回全市場，但逐則標記，不是整批冒充成這顆幣的新聞。
            # 退回時務必把 mine 排在最前面：all_items 依發布時間排序，那 1-4 則
            # 相關新聞散在約 265 則裡，切 [:limit]（預設 40）幾乎必然一則都不留，
            # 前端卻正在顯示「標有 [XXX] 的才是這顆幣的新聞」——提示指向一個
            # 連一個徽章都沒有的畫面。ai_analyst.py:415 本來就是這樣排的。
            # 用 id() 去重：mine 的元素就是 all_items 裡的同一批 dict 物件，
            # 比 `not in`（走 == 逐欄比較）快，且不受 dict 內容相同影響。
            if fell_back:
                mine_ids = {id(i) for i in mine}
                source = mine + [i for i in all_items if id(i) not in mine_ids]
            else:
                source = mine
            # 一定要複製再加欄位：all_items 是 _fetch_and_save() 的 30 分鐘快取本體，
            # 就地寫入會把這次的旗標留給下一個幣種的請求
            items = [{**i, "about_this_coin": ticker in _coin_tickers(i)} for i in source]
        else:
            items = all_items

        shown = items[:limit]
        return {
            "categories":          _group_by_category(shown),
            "total":               len(shown),   # 語意 = 本次實際回傳的則數（同舊版 min(len,limit)）
            "symbol":              ticker,       # 正規化後的 ticker；沒指定就是 None
            "coin_total":          coin_total,   # 標記到這顆幣的則數；沒指定 symbol 為 None
            "fell_back_to_market": fell_back,    # True = 相關新聞不足，這次顯示的是全市場
        }
    except Exception as e:
        return {"categories": [], "total": 0, "symbol": None,
                "coin_total": None, "fell_back_to_market": False, "error": str(e)}


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


@router.get("/sentiment/sources")
def news_sources():
    """
    新聞的實際來源分布（前端「資料來源」標示用）。

    直接訂閱的 RSS 清單是寫在程式裡的常數（RSS_SOURCES），照實回傳；
    但實際入庫的來源遠不只這些——Google News 聚合會帶進大量第三方媒體，
    所以另外查資料庫給出真實的網域數與前幾大來源，讓畫面上的標示對得起實際資料。
    """
    from backend.services.news_store import source_stats
    stats = source_stats()
    return {
        "rss": [name for name, _ in RSS_SOURCES],
        "aggregator": "Google News（中文聚合，市場級 + 幣種級查詢）",
        "aggregator_prefix": "GN:",
        **stats,
    }


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
    ok_requests     = 0    # 成功取得回應的請求數（用來判斷「是否全部失敗」）
    failed_requests = 0    # 失敗（連線 / HTTP 錯誤）的請求數

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
                resp.raise_for_status()   # HTTP 4xx/5xx 也算失敗，不當成功處理
                ok_requests += 1
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
                        # 少了這欄，save_articles() 會用 a.get("coins","") 存成空字串，
                        # 回補進來的歷史新聞就永遠對不上幣種過濾，也進不了
                        # news_sentiment_daily 的單幣分組（news_store.aggregate_daily）。
                        # HN 沒有摘要可用，只能用標題比對——與 RSS 來的新聞同一套規則。
                        "coins":        _match_coins(title),
                    })

                page += 1
                if page >= pages or page >= 10:  # 每個關鍵字最多抓 10 頁 = 500 篇
                    break

                time.sleep(0.2)  # 稍微暫停，避免請求太密集被限流

            except Exception as e:
                failed_requests += 1
                print(f"[backfill] {keyword} page {page} error: {e}")
                break

    # 所有關鍵字查完後，一次性批次存入（重複 URL 自動略過）
    saved = save_articles(all_articles)
    return saved, {"ok_requests": ok_requests, "failed_requests": failed_requests,
                   "articles_found": len(all_articles)}


# ── 歷史回補 API（2026-07-06 安全修補：掛上後台登入保護，不再對外開放寫入）──
@router.post("/sentiment/news/backfill")
def backfill_news(
    request: Request,
    from_date: str,
    to_date: str,
    _admin: str = Depends(require_admin),
):
    """
    回補歷史新聞：從 HackerNews 抓取指定日期範圍的加密幣文章存入資料庫

    Args:
        from_date: 起始日期，格式 YYYY-MM-DD
        to_date:   結束日期，格式 YYYY-MM-DD

    建議一次不超過 1 個月，太長會耗時較久（每個月約 100~500 篇）
    需帶後台 token（Authorization: Bearer …）——這是寫入型端點，避免被外部濫用。
    """
    enforce_rate_limit(
        request,
        scope="news_backfill_hour",
        limit=2,
        window_seconds=3600,
        limiter=RATE_LIMITER,
    )
    enforce_rate_limit(
        request,
        scope="news_backfill_day",
        limit=10,
        window_seconds=24 * 3600,
        limiter=RATE_LIMITER,
    )
    try:
        saved, meta = _hn_fetch_range(from_date, to_date)
    except Exception as e:
        # 非預期錯誤：明確回 502，不要假性成功
        raise HTTPException(status_code=502, detail=f"回補失敗：{e}")
    # 所有請求都失敗（來源 / 網路異常）→ 回 502，避免「saved:0 卻顯示成功」誤導使用者
    if meta["ok_requests"] == 0:
        raise HTTPException(
            status_code=502,
            detail=f"來源 HackerNews API 全部請求失敗（{meta['failed_requests']} 次），未回補任何資料",
        )
    return {
        "ok":              True,
        "from_date":       from_date,
        "to_date":         to_date,
        "saved":           saved,           # 這次新增的筆數
        "db_total":        total_count(),   # 資料庫目前的總筆數
        "ok_requests":     meta["ok_requests"],
        "failed_requests": meta["failed_requests"],
    }
