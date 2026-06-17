from backend.services.reader import load_indicators


def _compute_score(rsi, hist, prev_hist, close, ma20, ma60, ma200,
                   volume, vol_ma20, bb_upper, bb_lower):
    """
    7 因子信心分數（0–100），50 為中立基準。
    ≥65 → BULL，≤35 → BEAR，其餘 NEUTRAL。
    """
    score = 50
    factors = {}

    # 1. RSI (±20)
    rsi_score = 0
    if rsi is not None:
        if   rsi < 30: rsi_score = +20
        elif rsi < 35: rsi_score = +12
        elif rsi < 45: rsi_score = +5
        elif rsi > 70: rsi_score = -20
        elif rsi > 65: rsi_score = -12
        elif rsi > 55: rsi_score = -5
    factors["RSI"] = {"score": rsi_score,
                      "value": round(rsi, 1) if rsi is not None else None,
                      "note":  f"RSI {rsi:.1f}" if rsi is not None else "無資料",
                      "label": "RSI 動量"}
    score += rsi_score

    # 2. MACD 交叉 / 動能 (±18 / ±10)
    macd_score = 0
    macd_note  = "無資料"
    if hist is not None and prev_hist is not None:
        if   prev_hist < 0 and hist >= 0:   macd_score, macd_note = +18, "黃金交叉"
        elif prev_hist > 0 and hist <= 0:   macd_score, macd_note = -18, "死亡交叉"
        elif hist > prev_hist:              macd_score, macd_note = +10, "動能增強"
        else:                               macd_score, macd_note = -10, "動能減弱"
    factors["MACD"] = {"score": macd_score, "note": macd_note, "label": "MACD"}
    score += macd_score

    # 3. MA 排列（±15 / ±5）
    ma_score = 0
    ma_note  = "無資料"
    if close and ma20 and ma60:
        if   close > ma20 and ma20 > ma60:   ma_score, ma_note = +15, "多頭排列"
        elif close > ma20:                   ma_score, ma_note = +5,  "站上 MA20"
        elif close < ma20 and ma20 < ma60:   ma_score, ma_note = -15, "空頭排列"
        elif close < ma20:                   ma_score, ma_note = -5,  "跌破 MA20"
        else:                                ma_note = "中立"
    factors["MA"] = {"score": ma_score, "note": ma_note, "label": "均線排列"}
    score += ma_score

    # 4. MA200 長期趨勢 (±10)
    ma200_score = 0
    ma200_note  = "無資料"
    if ma200 and close:
        if   close > ma200: ma200_score, ma200_note = +10, f"站上 MA200 ({ma200:,.0f})"
        else:               ma200_score, ma200_note = -10, f"跌破 MA200 ({ma200:,.0f})"
    factors["MA200"] = {"score": ma200_score, "note": ma200_note, "label": "長期趨勢 MA200"}
    score += ma200_score

    # 5. 成交量確認 (±7)
    vol_score = 0
    vol_note  = "無資料"
    if volume and vol_ma20 and vol_ma20 > 0:
        ratio = volume / vol_ma20
        if   ratio > 1.5:  vol_score, vol_note = +7, f"放量 {ratio:.1f}x（確認訊號）"
        elif ratio > 1.1:  vol_score, vol_note = +4, f"量略增 {ratio:.1f}x"
        elif ratio < 0.6:  vol_score, vol_note = -7, f"縮量 {ratio:.1f}x（訊號可疑）"
        elif ratio < 0.9:  vol_score, vol_note = -4, f"量略縮 {ratio:.1f}x"
        else:              vol_note = f"正常量能 {ratio:.1f}x"
    factors["Volume"] = {"score": vol_score, "note": vol_note, "label": "成交量"}
    score += vol_score

    # 6. 布林通道位置 (±12 / ±7 / ±3)
    bb_score = 0
    bb_note  = "無資料"
    if bb_upper and bb_lower and close:
        bb_width = bb_upper - bb_lower
        if bb_width > 0:
            bb_pct = (close - bb_lower) / bb_width
            if   bb_pct < 0:    bb_score, bb_note = +12, "跌破下軌（超賣）"
            elif bb_pct < 0.2:  bb_score, bb_note = +7,  f"接近下軌 {bb_pct:.0%}"
            elif bb_pct < 0.4:  bb_score, bb_note = +3,  f"下半段 {bb_pct:.0%}"
            elif bb_pct > 1:    bb_score, bb_note = -12, "突破上軌（超買）"
            elif bb_pct > 0.8:  bb_score, bb_note = -7,  f"接近上軌 {bb_pct:.0%}"
            elif bb_pct > 0.6:  bb_score, bb_note = -3,  f"上半段 {bb_pct:.0%}"
            else:               bb_note = f"中間區 {bb_pct:.0%}"
    factors["BB"] = {"score": bb_score, "note": bb_note, "label": "布林通道"}
    score += bb_score

    return max(0, min(100, round(score))), factors


def get_signal(symbol: str) -> dict:
    rows = load_indicators(symbol, days=5)
    if not rows:
        return {"symbol": symbol, "signal": "UNKNOWN", "score": 50, "reasons": [], "factors": {}}

    latest = rows[-1]
    prev   = rows[-2] if len(rows) >= 2 else latest

    rsi      = latest.get("RSI")
    hist     = latest.get("HIST")
    prev_h   = prev.get("HIST")
    close    = latest.get("close")
    ma20     = latest.get("MA20")
    ma60     = latest.get("MA60")
    ma200    = latest.get("MA200")
    volume   = latest.get("volume")
    vol_ma20 = latest.get("VOL_MA20")
    bb_upper = latest.get("BB_UPPER")
    bb_lower = latest.get("BB_LOWER")

    score, factors = _compute_score(
        rsi, hist, prev_h, close, ma20, ma60, ma200,
        volume, vol_ma20, bb_upper, bb_lower,
    )

    if   score >= 65: signal = "BULL"
    elif score <= 35: signal = "BEAR"
    else:             signal = "NEUTRAL"

    reasons = [
        f"{v['label']}：{v['note']}"
        for v in factors.values()
        if v["score"] != 0 and v.get("note") not in (None, "無資料")
    ]

    return {
        "symbol":   symbol,
        "signal":   signal,
        "score":    score,
        "date":     latest.get("date"),
        "close":    close,
        "rsi":      rsi,
        "ma200":    ma200,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "reasons":  reasons,
        "factors":  factors,
    }
