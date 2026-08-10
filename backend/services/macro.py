# -*- coding: utf-8 -*-
"""
macro.py — 宏觀環境引擎（規則式，無需 GPT）

抓「會影響加密貨幣的宏觀數字」→ 用規則判斷對加密是「順風/逆風」→ 彙總整體風險偏好：
  DXY 美元指數、VIX 恐慌指數、US10Y 美債殖利率、S&P500、黃金、BTC 主導率、加密總市值

2026-08 起這一層不再只是「現在的數字」，補上三件讓它有分析價值的東西：
  1. 規則核心抽到 src/macro_regime.py — 面板顯示的環境與被回頭驗證的環境是同一套定義
  2. evidence  — src/macro_eval.py 的歷史檢定結果（含「其實不顯著」也照實回傳）
  3. linkage   — 加密與各宏觀序列的 60 日滾動相關，回答「此刻宏觀該不該當一回事」
說白話：面板不只講「現在順風還逆風」，還講「這個判斷有多少證據」與「現在總經
對加密的影響力有多大」。沒有證據的部分一律照實說沒有，不靠措辭撐場面。

設計原則（依使用者要求）：分析邏輯/標籤用「英文」（key、impact、verdict），
對外顯示欄位一律轉「中文」（*_zh）。政治/事件的「文字解讀」需 LLM，待 GPT 開通後另接加值層。

資料源皆免金鑰：Yahoo Finance chart API + CoinGecko global。
快取 15 分鐘（宏觀變化慢、且尊重來源速率）；單一來源失敗不影響其他因子。
"""
from __future__ import annotations
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.macro_regime import (       # noqa: E402 — 需先設定 sys.path 才能 import src/
    DRIVER_KEYS, IMPACT_ZH, LABEL_ZH, aggregate, build_factor, summary_zh,
)

_CACHE: dict = {"ts": 0.0, "data": None}
_TTL = 900  # 15 分鐘

EVIDENCE_PATH = ROOT / "reports" / "macro_evidence.json"
_EVIDENCE_CACHE: dict = {"mtime": None, "data": None}

# 連動強度的中文標籤（linkage 的 key 來自 macro_eval.LINK_SERIES）
_LINK_LABEL_ZH = {"SPX": "美股標普 500", "DXY": "美元指數",
                  "VIX": "恐慌指數 VIX", "GOLD": "黃金"}

# ── 資料出處（每個數字都要能被讀者自己追回原始頁面查證）──────────────────────
# 標的代號是查證的關鍵：光寫「Yahoo Finance」沒辦法核對，寫 ^VIX 才能自己去對收盤價。
_YAHOO_QUOTE = "https://finance.yahoo.com/quote/"
_FACTOR_SOURCE = {
    "DXY":   {"provider": "Yahoo Finance", "symbol": "DX-Y.NYB"},
    "VIX":   {"provider": "Yahoo Finance", "symbol": "^VIX"},
    "US10Y": {"provider": "Yahoo Finance", "symbol": "^TNX"},
    "SPX":   {"provider": "Yahoo Finance", "symbol": "^GSPC"},
    "GOLD":  {"provider": "Yahoo Finance", "symbol": "GC=F"},
    "BTC_DOM":    {"provider": "CoinGecko", "symbol": "CoinGecko global",
                   "url": "https://www.coingecko.com/en/global-charts"},
    "TOTAL_MCAP": {"provider": "CoinGecko", "symbol": "CoinGecko global",
                   "url": "https://www.coingecko.com/en/global-charts"},
}

# 面板底部的來源清單（誰提供了什麼、免金鑰、可自行查證）
SOURCES = [
    {"provider": "Yahoo Finance", "url": "https://finance.yahoo.com",
     "detail_zh": "美元指數、VIX、美債 10Y、標普 500、黃金的日線收盤"},
    {"provider": "CoinGecko", "url": "https://www.coingecko.com/en/global-charts",
     "detail_zh": "BTC 主導率、加密總市值（24h 動能）"},
    {"provider": "Binance", "url": "https://www.binance.com",
     "detail_zh": "BTC 日線收盤（計算與宏觀的連動強度用）"},
]


def _with_source(factor: dict, as_of: str | None = None) -> dict:
    """替因子附上「哪裡來的、哪個代號、哪一天的收盤」。"""
    src = _FACTOR_SOURCE.get(factor["key"])
    if src:
        factor["source"] = {
            "provider": src["provider"],
            "symbol": src["symbol"],
            "url": src.get("url") or (_YAHOO_QUOTE + quote(src["symbol"], safe="")),
            "as_of": as_of,
        }
    return factor


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.load(r)


def _yahoo(sym: str):
    """
    回傳 (最新收盤, 近 5 交易日變動%, 該收盤的日期)；失敗回 None。

    一併帶回日期是為了讓前台能標出「這個數字是哪一天的收盤」：
    各序列的交易日並不一致（例如美股休市當天黃金與美元照常交易），
    不標日期的話，畫面會讓人以為七個數字都是同一時點的，那才是真正的失真。
    """
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(sym, safe='')}?interval=1d&range=1mo"
        d = _get(url)
        result = d["chart"]["result"][0]
        stamps = result["timestamp"]
        raw = result["indicators"]["quote"][0]["close"]
        pairs = [(t, c) for t, c in zip(stamps, raw) if c is not None]
        if len(pairs) < 2:
            return None
        closes = [c for _, c in pairs]
        last = closes[-1]
        ref = closes[-6] if len(closes) >= 6 else closes[0]
        chg = (last / ref - 1.0) * 100 if ref else 0.0
        as_of = datetime.fromtimestamp(pairs[-1][0], timezone.utc).strftime("%Y-%m-%d")
        return last, chg, as_of
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


def _extra_factor(key, label_zh, value, change_pct, impact, note_zh, unit=""):
    """情境參考因子（BTC 主導率 / 總市值）：不在 macro_regime 的規則內，不參與彙總。"""
    return {
        "key": key, "label_zh": label_zh,
        "value": round(value, 2), "unit": unit,
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
        "impact": impact, "impact_zh": IMPACT_ZH[impact], "note_zh": note_zh,
    }


# ── 歷史檢定結果（src/macro_eval.py 產出）─────────────────────────────────
def load_evidence() -> dict | None:
    """
    讀 reports/macro_evidence.json（排程每日重產）。依檔案 mtime 快取，改檔即生效。

    刻意連「不顯著」也原樣帶出：這份的用途是替面板的說法定調，
    證據弱的時候前台必須跟著把話講輕，而不是隱藏證據只留結論。
    """
    try:
        mtime = EVIDENCE_PATH.stat().st_mtime
    except OSError:
        return None
    if _EVIDENCE_CACHE["mtime"] != mtime:
        try:
            with open(EVIDENCE_PATH, encoding="utf-8") as f:
                _EVIDENCE_CACHE["data"] = json.load(f)
            _EVIDENCE_CACHE["mtime"] = mtime
        except Exception:
            return None
    return _EVIDENCE_CACHE["data"]


def _evidence_summary(ev: dict | None) -> dict | None:
    """把檢定結果壓成前台可直接顯示的一句話 + 可信度等級。"""
    if not ev:
        return None
    primary = ev.get("primary_test") or {}
    if not primary.get("available"):
        return None
    diff, t = primary.get("diff_pct"), primary.get("t_hac")
    strong = primary.get("significant")
    period = ev.get("period") or {}
    eps = ev.get("regime_episodes") or {}
    n_eps = eps.get("RISK_ON", 0) + eps.get("RISK_OFF", 0)
    if strong:
        level, level_zh = "SUPPORTED", "有統計證據"
        text = (f"歷史上「順風」之後 5 日的平均報酬比「逆風」高 {diff:+.2f}%"
                f"（t={t}，達統計顯著）。")
    else:
        level, level_zh = "DIRECTIONAL_ONLY", "方向一致但未達顯著"
        text = (f"歷史上「順風」之後 5 日的平均報酬比「逆風」高 {diff:+.2f}%，"
                f"但統計上不顯著（t={t}）。方向合理、強度不足，"
                f"僅供背景參考，不足以當買賣依據。")
    return {
        "level": level, "level_zh": level_zh,
        "diff_pct": diff, "t_hac": t,
        "sample_zh": f"樣本 {period.get('start')}~{period.get('end')}，"
                     f"順風/逆風共 {n_eps} 個獨立區段",
        "text_zh": text,
        # 讓讀者知道這個結論是「誰的資料、用哪支程式、怎麼算」算出來的，能自己重跑核對
        "basis_zh": "算法：src/macro_eval.py（隔日開盤進場、Newey-West 修正重疊視窗）；"
                    "資料：Yahoo Finance 宏觀日線 + Binance 日線收盤。"
                    "重跑：python src/macro_eval.py",
    }


# ── 連動強度：此刻宏觀對加密的影響力 ─────────────────────────────────────
_LINK_CACHE: dict = {"ts": 0.0, "data": None}


def _compute_linkage() -> dict | None:
    """
    BTC 與各宏觀序列的 60 日滾動相關（讀 DB，與研究腳本同一個函式）。
    資料不足或出錯回 None——這是加值資訊，不該讓主面板一起壞掉。

    自己快取 15 分鐘：它只跟每日收盤有關，但判讀路徑（每次 AI 分析）也會用到，
    不快取等於每次分析都重算 1200 列滾動相關。
    """
    now = time.time()
    if _LINK_CACHE["data"] is not None and now - _LINK_CACHE["ts"] <= _TTL:
        return _LINK_CACHE["data"]
    data = _compute_linkage_uncached()
    if data is not None:
        _LINK_CACHE["data"], _LINK_CACHE["ts"] = data, now
    return data


def _compute_linkage_uncached() -> dict | None:
    try:
        import pandas as pd
        from backend.services.reader import load_macro_history, load_prices
        from src.macro_eval import linkage

        macro_rows = load_macro_history()
        price_rows = load_prices("BTCUSDT")
        if len(macro_rows) < 200 or len(price_rows) < 200:
            return None
        macro = pd.DataFrame(macro_rows)
        macro.index = pd.DatetimeIndex(pd.to_datetime(macro["date"]))
        prices = pd.DataFrame(price_rows)
        close = pd.Series(
            prices["close"].astype(float).to_numpy(),
            index=pd.DatetimeIndex(pd.to_datetime(prices["date"], utc=True)).tz_convert(None).normalize(),
        )
        out = linkage(close, macro)
        if not out.get("series"):
            return None
        for s in out["series"]:
            s["label_zh"] = _LINK_LABEL_ZH.get(s["key"], s["key"])
        out.update(_linkage_reading(out["series"], out.get("window_days")))
        return out
    except Exception:
        return None


def _linkage_reading(series: list[dict], window: int | None = None) -> dict:
    """
    連動強度 → 白話判讀（純規則）。

    回答兩個實際問題：現在加密最貼著哪一個總經變數走？宏觀讀值該給多少權重？
    強度用最大 |相關|：>=0.5 高、>=0.3 中等、否則低。
    """
    top = max(series, key=lambda s: abs(s["corr"]))
    strength = abs(top["corr"])
    n_years = top["n_obs"] / 252.0
    if strength >= 0.5:
        level, level_zh, weight_zh = "HIGH", "高", "宏觀讀值值得看重"
    elif strength >= 0.3:
        level, level_zh, weight_zh = "MEDIUM", "中等", "宏觀可當背景，別當主因"
    else:
        level, level_zh, weight_zh = "LOW", "低", "加密目前走自己的邏輯，宏觀影響有限"

    direction = "同向" if top["corr"] > 0 else "反向"
    extreme = ""
    if top["percentile"] >= 80:
        extreme = "，為近五年偏高水準"
    elif top["percentile"] <= 20:
        extreme = "，為近五年偏低水準"
    return {
        "level": level, "level_zh": level_zh,
        "top_key": top["key"], "top_corr": top["corr"],
        "text_zh": (f"目前 BTC 與{top['label_zh']}的 60 日相關性為 {top['corr']:+.2f}"
                    f"（{direction}{extreme}），整體連動強度{level_zh}；{weight_zh}。"),
        # 百分位的母體是「BTC 與宏觀都有資料的交易日」，受限於 prices 表只有 2021-07 起，
        # 實際約 1,220 個滾動值（≈5 年），不是宏觀本身的 10 年。寫死年數會跟畫面對不上，
        # 故依實際樣本數換算，資料期間變長時說法會自己跟著改。
        "basis_zh": ("以 BTC（Binance 日線收盤）對各宏觀序列（Yahoo Finance 日線收盤）"
                     f"取 {window} 個交易日的滾動相關；百分位＝目前值在近 {n_years:.0f} 年"
                     f"（{top['n_obs']:,} 個滾動值）中的位置。"),
    }


# ── 即時面板 ──────────────────────────────────────────────────────────────
def _compute() -> dict:
    factors = []
    impacts = {}     # 4 個主要風險驅動（DXY/VIX/US10Y/SPX）的 impact，決定整體 verdict

    # 規則一律走 src/macro_regime，與歷史重建同一套定義（改門檻只改那一份）
    for key, unit in (("DXY", ""), ("VIX", ""), ("US10Y", "%"), ("SPX", ""), ("GOLD", "")):
        quote_ = _yahoo(_FACTOR_SOURCE[key]["symbol"])
        if not quote_:
            continue
        value, change, as_of = quote_
        factor = build_factor(key, value, change, unit=unit)
        if not factor:
            continue
        factors.append(_with_source(factor, as_of))
        if key in DRIVER_KEYS:
            impacts[key] = factor["impact"]

    # CoinGecko：BTC 主導率 + 加密總市值（山寨輪動 / 整體動能，情境參考）
    g = _coingecko_global()
    if g:
        # CoinGecko global 是即時快照（非日線收盤），as_of 用取得當下的日期
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        factors.append(_with_source(
            _extra_factor("BTC_DOM", "BTC 主導率", g["btc_dom"], None, "NEUTRAL",
                          "上升＝資金集中 BTC（山寨承壓），下降＝轉進山寨（山寨季）",
                          unit="%"), today))
        mc = g["mcap_24h"]
        imp = "TAILWIND" if mc > 1 else "HEADWIND" if mc < -1 else "NEUTRAL"
        factors.append(_with_source(
            _extra_factor("TOTAL_MCAP", "加密總市值", g["total_mcap"] / 1e12, mc, imp,
                          "全加密市值 24h 動能", unit="兆"), today))

    verdict = aggregate(impacts)
    evidence = _evidence_summary(load_evidence())
    link = _compute_linkage()

    return {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        **verdict,
        "summary_zh": summary_zh(factors),
        "note_zh": "宏觀因子為市場整體背景（非單一幣訊號），依歷史相關性的經驗法則，非保證。",
        "factors": factors,
        "evidence": evidence,
        "linkage": link,
        "sources": SOURCES,
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


# ── 歷史環境（前台時間軸 / 研究用）────────────────────────────────────────
def get_macro_history(days: int = 365) -> dict:
    """
    逐日的宏觀環境標籤（DB 的 macro_daily → src/macro_regime 重算）。

    給前台畫「這一年多數時間是順風還是逆風」的時間軸；也讓任何人能自己核對
    面板今天的判斷與歷史是同一套規則算出來的。
    """
    try:
        import pandas as pd
        from backend.services.reader import load_macro_history
        from src.macro_regime import regime_series

        rows = load_macro_history()
        if len(rows) < 10:
            return {"ok": False, "error": "宏觀歷史資料不足", "points": []}
        frame = pd.DataFrame(rows)
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame["date"]))
        reg = regime_series(frame).tail(max(1, days))
        points = [
            {"date": str(idx.date()), "verdict": row["verdict"], "net": int(row["net"])}
            for idx, row in reg.iterrows()
        ]
        counts = {}
        for p in points:
            counts[p["verdict"]] = counts.get(p["verdict"], 0) + 1
        return {"ok": True, "points": points, "counts": counts,
                "days": len(points), "labels_zh": LABEL_ZH}
    except Exception as e:
        return {"ok": False, "error": str(e), "points": []}


def _daily_regime_snapshot() -> dict | None:
    """
    只讀 DB 的「最新一天環境」：verdict + 逐因子順逆風摘要，完全不連外網。
    供判讀路徑在面板快取是冷的時候使用（寧可用昨天收盤，也不要卡在外部 API）。
    """
    try:
        import pandas as pd
        from backend.services.reader import load_macro_history
        from src.macro_regime import VERDICT_ZH, regime_series

        rows = load_macro_history()
        if len(rows) < 10:
            return None
        frame = pd.DataFrame(rows)
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame["date"]))
        last = regime_series(frame).iloc[-1]
        factors = [
            {"label_zh": LABEL_ZH[key], "impact": last.get(f"{key}_impact")}
            for key in DRIVER_KEYS if last.get(f"{key}_impact")
        ]
        verdict = str(last["verdict"])
        return {
            "date": str(frame.index[-1].date()),
            "verdict": verdict,
            "verdict_zh": VERDICT_ZH.get(verdict, verdict),
            "summary_zh": summary_zh(factors),
        }
    except Exception:
        return None


def macro_snapshot_for_analysis() -> dict | None:
    """
    給判讀層（AI 分析 / 白話解讀）用的宏觀摘要。

    優先用面板的 15 分鐘快取，讓「畫面上的宏觀」與「分析文字裡的宏觀」是同一個判斷；
    快取是冷的就退回 DB 歷史重算——判讀路徑不該為了宏觀去等 6 個外部 API，
    寧可用昨天收盤的環境，也不要讓分析卡住或整個失敗。
    """
    cached = _CACHE.get("data")
    if cached and cached.get("ok"):
        source = "live"
        verdict, verdict_zh = cached["verdict"], cached["verdict_zh"]
        summary = cached.get("summary_zh")
        as_of = cached.get("as_of", "")[:10]
    else:
        daily = _daily_regime_snapshot()
        if not daily:
            return None
        source = "daily"
        verdict, verdict_zh = daily["verdict"], daily["verdict_zh"]
        summary, as_of = daily["summary_zh"], daily["date"]

    # 連動強度只讀 DB，兩條路徑都補得上（快取過的話幾乎零成本）
    link = _compute_linkage()
    evidence = _evidence_summary(load_evidence())
    return {
        "source": source, "as_of": as_of,
        "verdict": verdict, "verdict_zh": verdict_zh,
        "summary_zh": summary,
        "evidence_level": (evidence or {}).get("level"),
        "evidence_zh": (evidence or {}).get("text_zh"),
        "linkage_zh": (link or {}).get("text_zh"),
        "linkage_level": (link or {}).get("level"),
    }


if __name__ == "__main__":
    print(json.dumps(get_macro(), ensure_ascii=False, indent=2))
