# -*- coding: utf-8 -*-
"""
macro_regime.py — 宏觀環境「規則核心」（單一真相來源）

為什麼要有這一份：
  原本宏觀規則寫死在 backend/services/macro.py 的即時面板裡，只看得到「現在」。
  沒有歷史 → 無法驗證這套規則到底有沒有分析價值，面板就只是裝飾。
  這份把「判斷規則」抽成純函式（零 I/O、零外部相依），讓三邊共用同一套定義：
    1. 即時面板（backend/services/macro.py）— Yahoo 近月資料算「現在」的環境
    2. 歷史重建（src/macro_eval.py）      — DB 的 macro_daily 逐日重算同一套標籤
    3. 前台/AI 判讀                        — 顯示的環境與被驗證的環境是同一個東西
  與 src/scoring.py 的用意相同：畫面上講的，跟被檢驗的，必須是同一套標準。

門檻的來源與凍結（重要，攸關證據可信度）：
  下列門檻是 2026-07 建即時面板時憑總經常識訂的（強美元／高 VIX／殖利率上行 = 逆風），
  當時完全沒有看過任何「未來報酬」。macro_eval.py 是拿這組「事先就定好的規則」
  去測它對加密的預測力，屬於乾淨的檢定。
  ⚠ 因此禁止依 macro_eval 的結果回頭調整這裡的門檻——一旦回調，證據就從
    「事先規則的檢定」退化成「事後配適」，等同 #133 被攔阻的那個做法。

設計原則（沿用專案慣例）：分析邏輯與 enum 用英文（key / impact / verdict），
對外顯示欄位一律中文（*_zh）。
"""
from __future__ import annotations

# 進入整體風險偏好彙總的四個主要驅動；GOLD 等只當情境參考，不投票
DRIVER_KEYS = ("DXY", "VIX", "US10Y", "SPX")

# 變動率的回看根數：5 個交易日（即時面板取 closes[-6] 當基準，語意相同）
LOOKBACK = 5

IMPACT_ZH = {"TAILWIND": "順風", "HEADWIND": "逆風", "NEUTRAL": "中性"}
VERDICT_ZH = {
    "RISK_ON":  "順風（風險偏好）",
    "RISK_OFF": "逆風（風險趨避）",
    "NEUTRAL":  "中性（多空拉鋸）",
}
VERDICT_TONE = {"RISK_ON": "good", "RISK_OFF": "bad", "NEUTRAL": "warn"}

LABEL_ZH = {
    "DXY":   "美元指數",
    "VIX":   "恐慌指數 VIX",
    "US10Y": "美債 10Y 殖利率",
    "SPX":   "標普 500",
    "GOLD":  "黃金",
}


def classify(key: str, value, change_pct):
    """
    單一因子 → (impact, note_zh)。value 為最新值、change_pct 為 5 交易日變動 %。

    資料不足（value/change_pct 為 None）時回 (None, None)，由呼叫端決定略過該因子，
    而不是硬給 NEUTRAL——「沒抓到」與「判定中性」是兩件事，混在一起會稀釋彙總分母。
    """
    if key == "VIX":
        # VIX 看「水位」而非變動：20 附近是長期常態，25 以上才是真的在避險
        if value is None:
            return None, None
        if value >= 25:
            return "HEADWIND", f"恐慌偏高（{value:.0f}）→ 市場避險，壓抑風險資產"
        if value <= 16:
            return "TAILWIND", f"波動平靜（{value:.0f}）→ 風險偏好高，利加密"
        return "NEUTRAL", f"恐慌中性（{value:.0f}）"

    if change_pct is None:
        return None, None

    if key == "DXY":
        # 加密以美元計價：美元走強本身就是逆風
        if change_pct > 0.5:
            return "HEADWIND", "美元走強 → 加密（以美元計價）承壓"
        if change_pct < -0.5:
            return "TAILWIND", "美元走弱 → 資金外溢至風險資產，利加密"
        return "NEUTRAL", "美元指數持平，影響有限"

    if key == "US10Y":
        # 殖利率上行＝無風險報酬變好，資金沒理由留在高風險資產
        if change_pct > 2:
            return "HEADWIND", "殖利率上行 → 無風險報酬升、資金離開風險資產"
        if change_pct < -2:
            return "TAILWIND", "殖利率下行 → 利風險資產"
        return "NEUTRAL", "殖利率持平"

    if key == "SPX":
        # 加密近年與美股風險同向（見 /api/correlation）
        if change_pct > 1:
            return "TAILWIND", "美股偏多 → 風險偏好上升，加密同向受惠"
        if change_pct < -1:
            return "HEADWIND", "美股走弱 → 風險趨避，加密同向承壓"
        return "NEUTRAL", "美股持平"

    if key == "GOLD":
        # 情境參考：與 BTC 同屬「價值儲存」敘事，但方向解讀分歧，不投票
        return "NEUTRAL", "避險情緒參考；與 BTC 同屬『價值儲存』敘事"

    return "NEUTRAL", ""


def aggregate(impacts: dict) -> dict:
    """
    四個主要驅動的 impact → 整體風險偏好。
    impacts：{key: impact}，只有 DRIVER_KEYS 會被計票，缺的因子不計入分母。

    net = 順風數 − 逆風數；|net| >= 2 才表態，避免 1 比 0 這種雜訊被講成方向。
    """
    votes = [impacts[k] for k in DRIVER_KEYS if impacts.get(k)]
    net = votes.count("TAILWIND") - votes.count("HEADWIND")
    if net >= 2:
        verdict = "RISK_ON"
    elif net <= -2:
        verdict = "RISK_OFF"
    else:
        verdict = "NEUTRAL"
    return {
        "verdict": verdict,
        "verdict_zh": VERDICT_ZH[verdict],
        "tone": VERDICT_TONE[verdict],
        "net": int(net),
        "n_drivers": len(votes),
    }


def summary_zh(factors: list[dict]) -> str:
    """把逐因子的順風/逆風攤成一句話（面板抬頭用）。"""
    tw = [f["label_zh"] for f in factors if f.get("impact") == "TAILWIND"]
    hw = [f["label_zh"] for f in factors if f.get("impact") == "HEADWIND"]
    parts = []
    if hw:
        parts.append("逆風：" + "、".join(hw))
    if tw:
        parts.append("順風：" + "、".join(tw))
    return "；".join(parts) if parts else "宏觀因子多為中性，方向不明。"


def build_factor(key: str, value, change_pct, unit: str = "") -> dict | None:
    """
    單一因子的完整顯示物件（面板與歷史共用同一個形狀）。
    資料不足回 None。
    """
    impact, note = classify(key, value, change_pct)
    if impact is None:
        return None
    return {
        "key": key,
        "label_zh": LABEL_ZH.get(key, key),
        "value": round(value, 2) if value is not None else None,
        "unit": unit,
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
        "impact": impact,
        "impact_zh": IMPACT_ZH[impact],
        "note_zh": note,
    }


def regime_series(frame, lookback: int = LOOKBACK, ffill_limit: int = 5):
    """
    宏觀日資料（寬表）→ 逐日的 regime 標籤序列。

    frame：pandas DataFrame，索引為日期（遞增），欄位含 dxy / vix / us10y / spx（小寫）。
    回傳同索引的 DataFrame，欄位：
      DXY_impact / VIX_impact / US10Y_impact / SPX_impact、net、verdict

    無前視：第 t 列只用第 t 列與第 t-lookback 列的值（皆為當日收盤後可知），
    不碰任何 t 之後的資料。前 lookback 列因無基準而變動率為 NaN → 該因子不投票。

    ffill_limit：各序列先往前補值再判讀（只補過去、仍然無前視）。
      美股假日（如陣亡將士紀念日）黃金與美元照常交易、股債休市，若不補值，那幾天
      會因「湊不齊 4 個驅動」被強制判成 NEUTRAL，憑空製造出環境轉折。實際上那天
      交易者手上就是沿用前一個收盤，補值才是忠實反映當下可得的資訊。
    """
    import numpy as np
    import pandas as pd

    if ffill_limit:
        frame = frame.ffill(limit=ffill_limit)

    cols = {"DXY": "dxy", "VIX": "vix", "US10Y": "us10y", "SPX": "spx"}
    out = pd.DataFrame(index=frame.index)
    impacts = {}
    for key, col in cols.items():
        if col not in frame.columns:
            impacts[key] = pd.Series([None] * len(frame), index=frame.index)
            continue
        s = pd.to_numeric(frame[col], errors="coerce")
        ref = s.shift(lookback)
        chg = (s / ref - 1.0) * 100.0
        chg = chg.where(np.isfinite(chg))
        col_impact = [
            classify(key, None if pd.isna(v) else float(v),
                     None if pd.isna(c) else float(c))[0]
            for v, c in zip(s, chg)
        ]
        impacts[key] = pd.Series(col_impact, index=frame.index)
        out[f"{key}_impact"] = impacts[key]
        out[f"{key}_change_pct"] = chg

    votes = pd.DataFrame({k: v for k, v in impacts.items()})
    out["net"] = (votes.eq("TAILWIND").sum(axis=1)
                  - votes.eq("HEADWIND").sum(axis=1)).astype(int)
    out["n_drivers"] = votes.notna().sum(axis=1).astype(int)
    # 因子不足（例如序列開頭）時不表態，避免用 1 個因子就喊 RISK_ON
    out["verdict"] = np.where(
        out["n_drivers"] < len(DRIVER_KEYS), "NEUTRAL",
        np.where(out["net"] >= 2, "RISK_ON",
                 np.where(out["net"] <= -2, "RISK_OFF", "NEUTRAL")))
    return out
