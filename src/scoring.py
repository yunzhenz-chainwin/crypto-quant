"""
scoring.py — 共用的訊號計分核心（前端建議與回測共用同一套邏輯）

過去訊號邏輯有兩套、彼此不一致：
  - 前端建議：signal_engine.py 的 6 因子加權計分（≥65 多頭 / ≤35 空頭）
  - 回測買賣：backtest.py 的 3 因子數票（看多條件 ≥2 個就 BULL）
結果「畫面上的多空建議」與「回測買賣的依據」不是同一套，回測無法佐證建議。

這份檔把計分邏輯抽出來成單一真相來源，兩邊都 import 它：
  score_row(...)        → (信心分數 0–100, 各因子明細 dict)
  signal_from_score(s)  → 'BULL' / 'BEAR' / 'NEUTRAL'

純函式、零外部相依，前端後端都能安全 import。
"""


def _fmt_price(v):
    """價位自適應小數位：低價幣（DOGE $0.07）不能被 ,.0f 捨成 0。"""
    if v is None:
        return "—"
    if v < 1:
        return f"{v:,.4f}"
    if v < 100:
        return f"{v:,.2f}"
    return f"{v:,.0f}"


def score_row(rsi, hist, prev_hist, close, ma20, ma60, ma200,
              volume, vol_ma20, bb_upper, bb_lower):
    """
    6 因子信心分數（0–100），50 為中立基準。
    ≥65 → BULL，≤35 → BEAR，其餘 NEUTRAL（門檻見 signal_from_score）。
    回傳 (score, factors)，factors 供前端顯示各因子明細。
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
    # note 帶區間白話（新手看得懂 26 是「跌深超賣」而不只是個數字）
    if rsi is None:
        rsi_note = "無資料"
    else:
        zone = ("跌深超賣" if rsi < 30 else "偏弱" if rsi < 45 else
                "中性" if rsi <= 55 else "偏強" if rsi <= 70 else "漲多超買")
        rsi_note = f"RSI {rsi:.1f}（{zone}）"
    factors["RSI"] = {"score": rsi_score,
                      "value": round(rsi, 1) if rsi is not None else None,
                      "note":  rsi_note,
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
        if   close > ma200: ma200_score, ma200_note = +10, f"站上 MA200 (${_fmt_price(ma200)})"
        else:               ma200_score, ma200_note = -10, f"跌破 MA200 (${_fmt_price(ma200)})"
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


def signal_from_score(score) -> str:
    """信心分數 → 多空標籤。門檻與前端大卡一致：≥65 多頭、≤35 空頭。"""
    if score >= 65:
        return "BULL"
    if score <= 35:
        return "BEAR"
    return "NEUTRAL"
