"""
ai_analyst.py — AI 分析機器人（規則引擎 + GPT API 互相輔助）

設計理念（兩個腦互相輔助、互相檢核）：
  1. 「規則引擎」：純本地、確定性。把 6 因子計分、日線/小時線指標、恐懼貪婪、
     新聞情緒整理成結構化事實，並產出白話分析。零外部相依，永遠可用。
  2. 「GPT 分析」：把規則引擎整理好的結構化事實（JSON）連同固定提示詞餵給
     GPT API，要求「只根據提供的數據」做深度解讀 → 用本地數據 ground 住 GPT，
     防止幻覺；GPT 則補足規則引擎寫不出來的跨面向綜合研判。
  3. 交叉檢核：GPT 回傳 JSON 內含立場（偏多/偏空/中性），系統比對本地立場，
     不一致時標記 agreement=False，前端顯示「兩個分析來源觀點不一致」提醒。

GPT 設定來源（優先序）：
  環境變數 OPENAI_API_KEY / OPENAI_MODEL / OPENAI_BASE_URL
  → 後台設定 app_config 的 'ai'（{api_key, model, base_url}，/admin 可改）
  沒有金鑰時自動降級：只回規則引擎分析，前端照常可用。

成本保護：GPT 呼叫每小時上限（預設 80 次，AI_HOURLY_CAP 可調）；
分析結果快取 15 分鐘（同幣種+同資料版本不重打 API）。
"""
import json
import os
import re
import time
from collections import deque
from datetime import datetime, timezone

import requests

from backend.services.app_db import (
    get_config, get_coins,
    save_ai_analysis, load_ai_analysis, log_ai_chat, log_ai_usage,
)
from backend.services.reader import (
    load_prices, load_indicators, load_fear_greed_history,
    available_symbols, data_versions,
)
from backend.services.signal_engine import get_signal
from backend.services.news_store import query_recent

DEFAULT_MODEL    = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
GPT_TIMEOUT      = 45          # 秒
CACHE_TTL        = 15 * 60     # 完整分析快取 15 分鐘
HOURLY_CAP       = int(os.getenv("AI_HOURLY_CAP", "80"))  # GPT 每小時呼叫上限

_cache: dict = {}              # {cache_key: {"ts":…, "data":…}}
_gpt_calls = deque()           # 最近一小時的 GPT 呼叫時間戳（成本保護）


# ── GPT 設定 ─────────────────────────────────────────────────────────────────
def gpt_config() -> dict:
    """回傳 {api_key, model, base_url, source}；環境變數優先於後台設定。"""
    cfg = get_config("ai", {}) or {}
    key = os.getenv("OPENAI_API_KEY") or cfg.get("api_key") or ""
    return {
        "api_key":  key.strip(),
        "model":    os.getenv("OPENAI_MODEL") or cfg.get("model") or DEFAULT_MODEL,
        "base_url": (os.getenv("OPENAI_BASE_URL") or cfg.get("base_url")
                     or DEFAULT_BASE_URL).rstrip("/"),
        "source":   "env" if os.getenv("OPENAI_API_KEY") else ("db" if cfg.get("api_key") else None),
    }


def gpt_enabled() -> bool:
    return bool(gpt_config()["api_key"])


def _rate_ok() -> bool:
    """滑動視窗：最近一小時 GPT 呼叫是否已達上限。"""
    now = time.time()
    while _gpt_calls and now - _gpt_calls[0] > 3600:
        _gpt_calls.popleft()
    return len(_gpt_calls) < HOURLY_CAP


# ── 固定提示詞（Prompt 設計）──────────────────────────────────────────────────
# 深度分析：要求嚴格 JSON、逐點引用數據、禁止捏造、與規則引擎交叉表態。
SYSTEM_PROMPT_ANALYSIS = """你是「Crypto Quant 量化分析助理」，一位嚴謹、白話的加密貨幣技術分析師。
你的任務：根據系統提供的即時量化數據（JSON），產出一份繁體中文深度分析。

## 鐵則（違反任何一條即為失敗）
1. 只能使用提供的數據推理，嚴禁捏造任何數字、價位、新聞或事件。
2. 每個論點必須引用具體數據佐證，例如「RSI 56.7，中性偏多」。
3. 某項數據缺失時，直接說「該項資料不足」，不得腦補。
4. 禁止保證式語句（必漲、必跌、穩賺）；用機率與條件式語氣。
5. 這是教育性質的技術分析，不是投資建議；正文不必重複免責聲明（系統會統一顯示）。
6. 數據中附有「規則引擎」的初步結論供參考：你可以同意或反對，但都要講出依據；
   不要只是複述它的內容，你的價值在於跨面向的綜合研判與規則寫不出來的觀察。

## 輸出格式：嚴格 JSON（繁體中文），不得輸出 JSON 以外的文字
{
  "stance": "偏多 或 偏空 或 中性",
  "headline": "一句話結論，30 字內，白話",
  "analysis": "主要分析（markdown 條列或短段落，總長 250~450 字）：日線趨勢與動能 → 小時線短線觀察（若提供）→ 情緒與新聞面 → 綜合研判，每一點都要帶數據",
  "risks": ["最重要的風險提醒，最多 4 條"],
  "watch": ["接下來值得觀察的訊號或價位，最多 3 條"],
  "agree_with_rules": true,
  "disagree_reason": "若與規則引擎立場不同才填原因，否則空字串"
}"""

# 問答模式：單輪、限長、同樣被數據 ground 住。
SYSTEM_PROMPT_QA = """你是「Crypto Quant 量化分析助理」。使用者會針對某個幣種提問，
系統同時提供即時量化數據（JSON）與本地規則引擎的分析結論，作為你回答的唯一事實依據。

規則：
1. 只根據提供的數據回答；數據回答不了的問題，老實說「這需要 X 資料，目前系統沒有」。
2. 回答用繁體中文、白話、精簡（300 字內），適合投資新手閱讀；可用 markdown 條列。
3. 涉及數字時引用數據原值；禁止捏造。
4. 不給保證式結論，不催促買賣；可以說明「若出現某條件則偏多/偏空」的思路。
5. 與投資無關的問題（寫程式、閒聊等）請婉拒並拉回本幣種的分析主題。"""


# ── 蒐集結構化事實（context）────────────────────────────────────────────────
def _pct(a, b):
    """b→a 的漲跌幅 %（a 為新值）；資料不足回 None。"""
    try:
        if a is None or b in (None, 0):
            return None
        return round((a - b) / b * 100, 2)
    except Exception:
        return None


def _coin_zh(symbol: str) -> str:
    for c in get_coins():
        if c["symbol"] == symbol:
            return c.get("zh") or symbol
    return symbol


def build_context(symbol: str) -> dict:
    """
    把「這顆幣現在的狀態」整理成一包結構化事實：
    日線訊號因子、價格變化、日線指標、小時線短線指標（若有）、恐懼貪婪、近期新聞。
    這包資料同時餵給規則引擎（本地分析）與 GPT（深度分析），是唯一事實來源。
    """
    sig = get_signal(symbol)                       # 6 因子計分 + 各因子白話註記
    daily = load_indicators(symbol, days=31)       # 近 31 天日線（算 7/30 日變化）
    latest = daily[-1] if daily else {}

    closes = [r["close"] for r in daily if r.get("close") is not None]
    price_now = closes[-1] if closes else None
    ctx = {
        "symbol": symbol,
        "name_zh": _coin_zh(symbol),
        "as_of": latest.get("date"),
        "price": price_now,
        "change_pct": {
            "1d":  _pct(price_now, closes[-2]  if len(closes) >= 2  else None),
            "7d":  _pct(price_now, closes[-8]  if len(closes) >= 8  else None),
            "30d": _pct(price_now, closes[0]   if len(closes) >= 31 else None),
        },
        "daily": {
            "signal": sig.get("signal"), "score": sig.get("score"),
            "factors": {k: {"score": v.get("score"), "note": v.get("note"), "label": v.get("label")}
                        for k, v in (sig.get("factors") or {}).items()},
            "rsi": latest.get("RSI"), "ma20": latest.get("MA20"),
            "ma60": latest.get("MA60"), "ma200": latest.get("MA200"),
            "macd_hist": latest.get("HIST"),
            "bb_upper": latest.get("BB_UPPER"), "bb_lower": latest.get("BB_LOWER"),
        },
        "hourly": None,
        "sentiment": {},
        "news": [],
    }

    # 小時線短線視角（只有 BTC/ETH 等有 1h 資料的幣才有）
    if symbol in available_symbols("1h"):
        h = load_indicators(symbol, days=3, interval="1h")
        if len(h) >= 25:
            hl = h[-1]
            h_closes = [r["close"] for r in h if r.get("close") is not None]
            ctx["hourly"] = {
                "as_of": hl.get("date"),
                "change_24h_pct": _pct(h_closes[-1], h_closes[-25] if len(h_closes) >= 25 else None),
                "rsi": hl.get("RSI"),
                "macd_hist": hl.get("HIST"),
                "macd_hist_prev": h[-2].get("HIST") if len(h) >= 2 else None,
                "above_ma20": (hl.get("close") or 0) > (hl.get("MA20") or float("inf")),
                "ma20": hl.get("MA20"), "ma60": hl.get("MA60"),
            }

    # 恐懼貪婪指數（全市場情緒）；label 轉中文
    _FG_ZH = {"Extreme Fear": "極度恐慌", "Fear": "恐慌", "Neutral": "中性",
              "Greed": "貪婪", "Extreme Greed": "極度貪婪"}
    try:
        fg = load_fear_greed_history(days=2)
        if fg:
            ctx["sentiment"]["fear_greed"] = {
                "value": fg[-1]["value"],
                "label": _FG_ZH.get(fg[-1]["label"], fg[-1]["label"]),
            }
    except Exception:
        pass

    # 近 3 天新聞：優先取「標記到這顆幣」的新聞（coins 欄），不足再補全市場頭條
    try:
        ticker = symbol.replace("USDT", "")
        allnews = query_recent(days=3)
        mine = [n for n in allnews if ticker in (n.get("coins") or "").split(",")]
        picked = (mine + [n for n in allnews if n not in mine])[:8]
        ctx["news"] = [{"title": n["title"], "sentiment": n["sentiment"],
                        "category": n["category"], "date": n["published_at"],
                        "about_this_coin": ticker in (n.get("coins") or "").split(",")}
                       for n in picked]
        ctx["sentiment"]["news_3d"] = {
            "total":   len(allnews),
            "bullish": sum(1 for n in allnews if n["sentiment"] == "bullish"),
            "bearish": sum(1 for n in allnews if n["sentiment"] == "bearish"),
            "this_coin_total": len(mine),
            "this_coin_bullish": sum(1 for n in mine if n["sentiment"] == "bullish"),
            "this_coin_bearish": sum(1 for n in mine if n["sentiment"] == "bearish"),
        }
    except Exception:
        pass

    return ctx


# ── 規則引擎：本地白話分析（無金鑰也永遠可用）─────────────────────────────────
_STANCE_ZH = {"BULL": "偏多", "BEAR": "偏空", "NEUTRAL": "中性", "UNKNOWN": "中性"}


def local_analysis(ctx: dict) -> dict:
    """把結構化事實轉成白話分析：立場、逐面向解讀、風險、操作參考。純規則、確定性。"""
    d = ctx["daily"]
    factors = d.get("factors") or {}
    stance = _STANCE_ZH.get(d.get("signal") or "UNKNOWN", "中性")
    score = d.get("score")

    def note(k):
        return (factors.get(k) or {}).get("note") or "資料不足"

    points = []
    # 趨勢（均線排列 + 長期 MA200）
    points.append({"tag": "趨勢", "emoji": "📈",
                   "text": f"均線{note('MA')}；長期趨勢{note('MA200')}。"})
    # 動能（RSI + MACD）；RSI 區間白話化
    rsi = d.get("rsi")
    if rsi is None:
        rsi_txt = "RSI 資料不足"
    else:
        zone = ("超賣區，跌深" if rsi < 30 else "偏弱" if rsi < 45 else
                "中性" if rsi <= 55 else "偏強" if rsi <= 70 else "超買區，漲多")
        rsi_txt = f"RSI {rsi:.1f}（{zone}）"
    points.append({"tag": "動能", "emoji": "⚡",
                   "text": f"{rsi_txt}；MACD {note('MACD')}。"})
    # 量能與位置
    points.append({"tag": "量能", "emoji": "📊", "text": f"成交量：{note('Volume')}。"})
    points.append({"tag": "位置", "emoji": "🎯", "text": f"布林通道：{note('BB')}。"})

    # 短線（1h）視角
    h = ctx.get("hourly")
    if h:
        h_bits = []
        if h.get("change_24h_pct") is not None:
            h_bits.append(f"24 小時 {h['change_24h_pct']:+.2f}%")
        if h.get("rsi") is not None:
            h_bits.append(f"1h RSI {h['rsi']:.0f}")
        if h.get("macd_hist") is not None and h.get("macd_hist_prev") is not None:
            h_bits.append("短線動能" + ("增強" if h["macd_hist"] > h["macd_hist_prev"] else "減弱"))
        h_bits.append("價格在 1h MA20 之" + ("上" if h.get("above_ma20") else "下"))
        points.append({"tag": "短線 1h", "emoji": "⏱", "text": "；".join(h_bits) + "。"})

    # 市場情緒
    s_bits = []
    fg = (ctx.get("sentiment") or {}).get("fear_greed")
    if fg:
        s_bits.append(f"恐懼貪婪指數 {fg['value']}（{fg['label']}）")
    ns = (ctx.get("sentiment") or {}).get("news_3d")
    if ns and ns.get("total"):
        s_bits.append(f"近 3 天新聞 {ns['total']} 則：看多 {ns['bullish']}、看空 {ns['bearish']}")
    if s_bits:
        points.append({"tag": "情緒", "emoji": "🌡", "text": "；".join(s_bits) + "。"})

    # 風險提醒：找「與立場相反 / 可疑」的訊號
    risks = []
    if stance == "偏多":
        if rsi is not None and rsi > 65:
            risks.append(f"RSI 已達 {rsi:.0f}，短線漲多，追高風險升高")
        if (factors.get("Volume") or {}).get("score", 0) < 0:
            risks.append("上漲但量能不足，訊號可信度打折")
        if fg and fg["value"] >= 75:
            risks.append(f"市場情緒過熱（恐懼貪婪 {fg['value']}），歷史上易出現回檔")
    if stance == "偏空":
        if rsi is not None and rsi < 35:
            risks.append(f"RSI 已低至 {rsi:.0f}，超賣後隨時可能技術性反彈，不宜追空")
        if fg and fg["value"] <= 25:
            risks.append(f"市場極度恐慌（{fg['value']}），常是波動最劇烈的階段")
    if h and ctx.get("daily"):
        # 日線與小時線方向矛盾 → 提醒
        h_up = h.get("macd_hist") is not None and h["macd_hist"] > 0
        if stance == "偏多" and not h_up and not h.get("above_ma20"):
            risks.append("日線偏多但 1h 短線轉弱，短期可能先震盪")
        if stance == "偏空" and h_up and h.get("above_ma20"):
            risks.append("日線偏空但 1h 短線反彈中，空單短線有軋空風險")
    if ns and ns.get("bearish", 0) > ns.get("bullish", 0) and stance == "偏多":
        risks.append("近期新聞偏空訊息較多，留意消息面逆風")
    if not risks:
        risks.append("多空訊號互見，方向未明時倉位宜保守")

    # 操作參考（條件式、不催促）
    if stance == "偏多" and (score or 50) >= 75:
        suggestion = "多項指標同步偏多。若已持有可續抱並設好移動停利；空手者避免一次全押，分批並設停損較穩。"
    elif stance == "偏多":
        suggestion = "整體偏多但強度普通。可小倉位試探，跌破 MA20 或訊號轉弱就先退出觀望。"
    elif stance == "偏空" and (score or 50) <= 25:
        suggestion = "多項指標同步偏空。持有者宜考慮減碼或設緊停損；想抄底至少等出現止跌訊號（如 RSI 底背離）再說。"
    elif stance == "偏空":
        suggestion = "偏空但未到極端。不建議急著抄底；等站回 MA20 之上或動能翻正再重新評估。"
    else:
        suggestion = "多空拉鋸、方向不明。此時進出場勝率都不高，建議觀望，等訊號分數突破 65 或跌破 35 再行動。"

    headline = f"{ctx.get('name_zh', ctx['symbol'])}目前{stance}"
    if score is not None:
        headline += f"（信心分數 {score}）"

    return {
        "stance": stance, "signal": d.get("signal"), "score": score,
        "headline": headline, "points": points,
        "risks": risks[:4], "suggestion": suggestion,
    }


# ── GPT：深度分析 / 問答 ─────────────────────────────────────────────────────
def _chat(messages: list, want_json: bool, kind: str = "ask") -> tuple[str | None, str | None]:
    """
    呼叫 OpenAI 相容的 chat/completions。回傳 (內容, 錯誤訊息)。
    只送必要參數，避免不同模型（gpt-4o / gpt-5…）參數相容性問題。
    每次呼叫（成功或失敗）都記入 ai_usage（token 用量 / 成本監控）。
    """
    cfg = gpt_config()
    if not cfg["api_key"]:
        return None, "未設定 GPT API 金鑰"
    if not _rate_ok():
        return None, f"已達每小時 GPT 呼叫上限（{HOURLY_CAP} 次），稍後再試"

    body = {"model": cfg["model"], "messages": messages}
    if want_json:
        body["response_format"] = {"type": "json_object"}
    # gpt-5 / o 系列推理模型不接受自訂 temperature，其餘給低溫求穩定
    if not re.match(r"^(gpt-5|o\d)", cfg["model"]):
        body["temperature"] = 0.3

    _gpt_calls.append(time.time())
    err = None
    try:
        resp = requests.post(
            f"{cfg['base_url']}/chat/completions",
            headers={"Authorization": f"Bearer {cfg['api_key']}",
                     "Content-Type": "application/json"},
            json=body, timeout=GPT_TIMEOUT,
        )
        if resp.status_code != 200:
            detail = ""
            try:
                detail = (resp.json().get("error") or {}).get("message", "")[:180]
            except Exception:
                detail = resp.text[:180]
            err = f"GPT API 回應 {resp.status_code}：{detail}"
            return None, err
        j = resp.json()
        usage = j.get("usage") or {}
        log_ai_usage(kind, cfg["model"],
                     usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
                     ok=True)
        return j["choices"][0]["message"]["content"], None
    except requests.Timeout:
        err = "GPT API 逾時（45 秒）"
        return None, err
    except Exception as e:
        err = f"GPT API 連線失敗：{e}"
        return None, err
    finally:
        if err:
            try:
                log_ai_usage(kind, cfg["model"], ok=False, error=err)
            except Exception:
                pass


def _parse_json(text: str) -> dict | None:
    """容錯解析：去掉可能的 ```json 圍欄再 loads。"""
    if not text:
        return None
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    try:
        return json.loads(t)
    except Exception:
        return None


def gpt_analysis(ctx: dict, local: dict) -> tuple[dict | None, str | None]:
    """
    GPT 深度分析。把結構化事實 + 規則引擎初步結論一起餵給 GPT（固定提示詞），
    回傳 (結果 dict, 錯誤訊息)。結果含 stance，供與本地立場交叉比對。
    """
    user_payload = {
        "數據": ctx,
        "規則引擎初步結論": {
            "立場": local["stance"], "信心分數": local["score"],
            "各面向": [f"{p['tag']}：{p['text']}" for p in local["points"]],
        },
    }
    content, err = _chat([
        {"role": "system", "content": SYSTEM_PROMPT_ANALYSIS},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, default=str)},
    ], want_json=True, kind="analysis")
    if err:
        return None, err
    data = _parse_json(content)
    if not data or "stance" not in data:
        return None, "GPT 回傳格式無法解析"
    data["model"] = gpt_config()["model"]
    return data, None


def ask(symbol: str, question: str, history: list | None = None) -> dict:
    """
    問答模式：使用者針對幣種提問。GPT 可用時由 GPT 回答（以數據 + 本地分析 ground），
    不可用時回本地分析的摘要作為降級答案。

    history：最近幾輪對話 [{"q": 問, "a": 答}, ...]（前端傳來，最多取 3 輪），
    讓 GPT 能接住「那如果跌破呢？」這類追問；規則引擎降級路徑用不到它。
    每次問答（含降級）都記入 ai_chat（90 天保留）。
    """
    ctx = build_context(symbol)
    local = local_analysis(ctx)
    question = question.strip()[:500]

    if gpt_enabled():
        user_payload = {
            "使用者問題": question,
            "數據": ctx,
            "規則引擎分析": local,
        }
        messages = [{"role": "system", "content": SYSTEM_PROMPT_QA}]
        # 帶入最近 3 輪對話（截斷答案，控制 token）
        for h in (history or [])[-3:]:
            if h.get("q"):
                messages.append({"role": "user", "content": str(h["q"])[:500]})
            if h.get("a"):
                messages.append({"role": "assistant", "content": str(h["a"])[:1200]})
        messages.append({"role": "user",
                         "content": json.dumps(user_payload, ensure_ascii=False, default=str)})
        content, err = _chat(messages, want_json=False, kind="ask")
        if content:
            log_ai_chat(symbol, question, content, "gpt", gpt_config()["model"])
            return {"answer": content, "source": "gpt", "model": gpt_config()["model"],
                    "stance": local["stance"]}
        fallback_note = f"（GPT 暫時無法使用：{err}，以下為規則引擎摘要）\n\n"
    else:
        fallback_note = "（尚未設定 GPT API 金鑰，以下為規則引擎摘要；到後台「AI 設定」補上金鑰即可啟用智慧問答）\n\n"

    # 降級：用本地分析組一段回答
    lines = [fallback_note + f"**{local['headline']}**", ""]
    lines += [f"- {p['emoji']} **{p['tag']}**：{p['text']}" for p in local["points"]]
    lines += ["", f"⚠️ {local['risks'][0]}" if local["risks"] else "",
              f"💡 {local['suggestion']}"]
    answer = "\n".join(l for l in lines if l is not None)
    log_ai_chat(symbol, question, answer, "local")
    return {"answer": answer, "source": "local", "stance": local["stance"]}


# ── 對外主入口：完整分析（含快取）────────────────────────────────────────────
def analyze(symbol: str, use_gpt: bool = True, force: bool = False) -> dict:
    """
    回傳 {local, gpt, gpt_status, agreement, ...}。
    - local 永遠有值（規則引擎）。
    - gpt 只在金鑰可用且呼叫成功時有值；gpt_status 說明原因（disabled/error 訊息）。
    - agreement：兩個來源立場是否一致（gpt 有值時才有意義）。
    快取鍵含資料版本：資料一更新（每小時/每日排程後）快取自動失效。
    """
    ver = data_versions()
    key = f"{symbol}|{use_gpt}|{ver.get('1d')}|{ver.get('1h')}|{gpt_config()['model']}"
    hit = _cache.get(key)
    if hit and not force and time.time() - hit["ts"] < CACHE_TTL:
        return hit["data"]
    # 記憶體沒中 → 查持久化快取（重啟後仍在；含 GPT 的結果尤其值得保留）
    if not force:
        db_hit = load_ai_analysis(key, CACHE_TTL)
        if db_hit:
            _cache[key] = {"ts": time.time(), "data": db_hit}
            return db_hit

    ctx = build_context(symbol)
    local = local_analysis(ctx)
    out = {
        "symbol": symbol,
        "name_zh": ctx.get("name_zh"),
        "as_of": ctx.get("as_of"),
        "price": ctx.get("price"),
        "has_hourly": ctx.get("hourly") is not None,
        "local": local,
        "gpt": None,
        "gpt_status": "disabled" if not gpt_enabled() else "skipped",
        "agreement": None,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }

    if use_gpt and gpt_enabled():
        gpt, err = gpt_analysis(ctx, local)
        if gpt:
            out["gpt"] = gpt
            out["gpt_status"] = "ok"
            out["agreement"] = (gpt.get("stance") == local["stance"])
        else:
            out["gpt_status"] = f"error: {err}"

    _cache[key] = {"ts": time.time(), "data": out}
    try:
        save_ai_analysis(key, symbol, out)   # 持久化：重啟不失效、可回顧歷史
    except Exception:
        pass
    return out


def test_gpt() -> dict:
    """後台「測試連線」：打一個極小的請求驗證金鑰/模型/網路。"""
    content, err = _chat(
        [{"role": "user", "content": "回覆兩個字：正常"}], want_json=False, kind="test")
    if err:
        return {"ok": False, "error": err}
    return {"ok": True, "model": gpt_config()["model"], "reply": (content or "")[:40]}
