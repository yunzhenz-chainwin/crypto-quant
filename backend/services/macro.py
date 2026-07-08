# -*- coding: utf-8 -*-
"""
macro.py — 宏觀環境引擎（規則式，無需 GPT）

抓「會影響加密貨幣的宏觀數字」→ 用規則判斷對加密是「順風/逆風」→ 彙總整體風險偏好：
  DXY 美元指數、VIX 恐慌指數、US10Y 美債殖利率、S&P500、黃金、BTC 主導率、加密總市值

設計原則（依使用者要求）：分析邏輯/標籤用「英文」（key、impact、verdict），
對外顯示欄位一律轉「中文」（*_zh）。政治/事件的「文字解讀」需 LLM，待 GPT 開通後另接加值層。

資料源皆免金鑰：Yahoo Finance chart API + CoinGecko global。
快取 15 分鐘（宏觀變化慢、且尊重來源速率）；單一來源失敗不影響其他因子。
"""
from __future__ import annotations
import json
import time
import urllib.request
from datetime import datetime, timezone
from urllib.parse import quote

_CACHE: dict = {"ts": 0.0, "data": None}
_TTL = 900  # 15 分鐘

_IMPACT_ZH = {"TAILWIND": "順風", "HEADWIND": "逆風", "NEUTRAL": "中性"}


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.load(r)


def _yahoo(sym: str):
    """回傳 (最新收盤, 近 5 交易日變動%)；失敗回 None。"""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(sym, safe='')}?interval=1d&range=1mo"
        d = _get(url)
        closes = [c for c in d["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c is not None]
        if len(closes) < 2:
            return None
        last = closes[-1]
        ref = closes[-6] if len(closes) >= 6 else closes[0]
        chg = (last / ref - 1.0) * 100 if ref else 0.0
        return last, chg
    except Exception:
        return None


def _coingecko_global():
    try:
        g = _get("https://api.coingecko.com/api/v3/global")["data"]
        return {
            "btc_dom": g["market_cap_percentage"]["btc"],
            "total_mcap": g["total_market_cap"]["usd"],
            "mcap_24h": g["market_cap_change_percentage_24h_usd"],
        }
    except Exception:
        return None


def _factor(key, label_zh, value, change_pct, impact, note_zh, unit=""):
    return {
        "key": key, "label_zh": label_zh,
        "value": round(value, 2), "unit": unit,
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
        "impact": impact, "impact_zh": _IMPACT_ZH[impact], "note_zh": note_zh,
    }


def _compute() -> dict:
    factors = []
    drivers = []   # 4 個主要風險驅動（DXY/VIX/US10Y/SPX）的 impact，決定整體 verdict

    # DXY 美元指數：走強→逆風（加密以美元計價，強美元＝風險趨避）
    dxy = _yahoo("DX-Y.NYB")
    if dxy:
        v, c = dxy
        if c > 0.5:    imp, note = "HEADWIND", "美元走強 → 加密（以美元計價）承壓"
        elif c < -0.5: imp, note = "TAILWIND", "美元走弱 → 資金外溢至風險資產，利加密"
        else:          imp, note = "NEUTRAL",  "美元指數持平，影響有限"
        factors.append(_factor("DXY", "美元指數", v, c, imp, note))
        drivers.append(imp)

    # VIX 恐慌指數：高→逆風
    vix = _yahoo("^VIX")
    if vix:
        v, c = vix
        if v >= 25:   imp, note = "HEADWIND", f"恐慌偏高（{v:.0f}）→ 市場避險，壓抑風險資產"
        elif v <= 16: imp, note = "TAILWIND", f"波動平靜（{v:.0f}）→ 風險偏好高，利加密"
        else:         imp, note = "NEUTRAL",  f"恐慌中性（{v:.0f}）"
        factors.append(_factor("VIX", "恐慌指數 VIX", v, c, imp, note))
        drivers.append(imp)

    # US10Y 美債 10 年殖利率：上行→逆風（無風險報酬升，資金離開風險資產）
    ty = _yahoo("^TNX")
    if ty:
        v, c = ty
        if c > 2:    imp, note = "HEADWIND", "殖利率上行 → 無風險報酬升、資金離開風險資產"
        elif c < -2: imp, note = "TAILWIND", "殖利率下行 → 利風險資產"
        else:        imp, note = "NEUTRAL",  "殖利率持平"
        factors.append(_factor("US10Y", "美債 10Y 殖利率", v, c, imp, note, unit="%"))
        drivers.append(imp)

    # S&P500：上漲→順風（加密與美股風險同向，近年高相關）
    spx = _yahoo("^GSPC")
    if spx:
        v, c = spx
        if c > 1:    imp, note = "TAILWIND", "美股偏多 → 風險偏好上升，加密同向受惠"
        elif c < -1: imp, note = "HEADWIND", "美股走弱 → 風險趨避，加密同向承壓"
        else:        imp, note = "NEUTRAL",  "美股持平"
        factors.append(_factor("SPX", "標普 500", v, c, imp, note))
        drivers.append(imp)

    # 黃金：情境參考（不計入 verdict）——與 BTC 同屬「價值儲存」敘事
    gold = _yahoo("GC=F")
    if gold:
        v, c = gold
        factors.append(_factor("GOLD", "黃金", v, c, "NEUTRAL",
                               "避險情緒參考；與 BTC 同屬『價值儲存』敘事"))

    # CoinGecko：BTC 主導率 + 加密總市值（山寨輪動 / 整體動能，情境參考）
    g = _coingecko_global()
    if g:
        dom = g["btc_dom"]
        factors.append(_factor("BTC_DOM", "BTC 主導率", dom, None, "NEUTRAL",
                               f"上升＝資金集中 BTC（山寨承壓），下降＝轉進山寨（山寨季）", unit="%"))
        mc = g["mcap_24h"]
        imp = "TAILWIND" if mc > 1 else "HEADWIND" if mc < -1 else "NEUTRAL"
        factors.append(_factor("TOTAL_MCAP", "加密總市值", g["total_mcap"] / 1e12, mc, imp,
                               "全加密市值 24h 動能", unit="兆"))

    # ── 彙總：4 個主要驅動的（順風 − 逆風）淨值 → 整體風險偏好 ──
    net = drivers.count("TAILWIND") - drivers.count("HEADWIND")
    if net >= 2:    verdict, verdict_zh, tone = "RISK_ON",  "順風（風險偏好）", "good"
    elif net <= -2: verdict, verdict_zh, tone = "RISK_OFF", "逆風（風險趨避）", "bad"
    else:           verdict, verdict_zh, tone = "NEUTRAL",  "中性（多空拉鋸）", "warn"

    tw = [f["label_zh"] for f in factors if f["impact"] == "TAILWIND"]
    hw = [f["label_zh"] for f in factors if f["impact"] == "HEADWIND"]
    parts = []
    if hw: parts.append("逆風：" + "、".join(hw))
    if tw: parts.append("順風：" + "、".join(tw))
    summary_zh = "；".join(parts) if parts else "宏觀因子多為中性，方向不明。"

    return {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "verdict": verdict, "verdict_zh": verdict_zh, "tone": tone, "net": net,
        "summary_zh": summary_zh,
        "note_zh": "宏觀因子為市場整體背景（非單一幣訊號），依歷史相關性的經驗法則，非保證。",
        "factors": factors,
    }


def get_macro() -> dict:
    """快取 15 分鐘。來源失敗時：有舊資料回舊的，沒有才回 error。"""
    now = time.time()
    if _CACHE["data"] is None or now - _CACHE["ts"] > _TTL:
        try:
            data = _compute()
            if data.get("factors"):          # 至少抓到一個因子才更新快取
                _CACHE["data"] = data
                _CACHE["ts"] = now
        except Exception as e:
            if _CACHE["data"] is None:
                return {"ok": False, "error": str(e), "factors": []}
    return _CACHE["data"]


if __name__ == "__main__":
    print(json.dumps(get_macro(), ensure_ascii=False, indent=2))
