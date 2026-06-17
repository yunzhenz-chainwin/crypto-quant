from backend.services.reader import load_indicators


def get_signal(symbol: str) -> dict:
    rows = load_indicators(symbol, days=5)
    if not rows:
        return {"symbol": symbol, "signal": "UNKNOWN", "reasons": []}

    latest = rows[-1]
    prev = rows[-2] if len(rows) >= 2 else latest

    rsi = latest.get("RSI")
    macd_hist = latest.get("HIST")
    prev_hist = prev.get("HIST")
    close = latest.get("close")
    ma20 = latest.get("MA20")
    ma60 = latest.get("MA60")

    bull = []
    bear = []

    if rsi is not None:
        if rsi < 35:
            bull.append(f"RSI {rsi:.1f} 超賣區（< 35）")
        elif rsi > 65:
            bear.append(f"RSI {rsi:.1f} 超買區（> 65）")

    if macd_hist is not None and prev_hist is not None:
        if prev_hist < 0 and macd_hist >= 0:
            bull.append("MACD 柱狀圖從負轉正（黃金交叉）")
        elif prev_hist > 0 and macd_hist <= 0:
            bear.append("MACD 柱狀圖從正轉負（死亡交叉）")
        elif macd_hist > prev_hist:
            bull.append("MACD 動能持續增強")
        else:
            bear.append("MACD 動能持續減弱")

    if close and ma20 and ma60:
        if close > ma20 and ma20 > ma60:
            bull.append(f"收盤 {close:.2f} > MA20 > MA60（多頭排列）")
        elif close < ma20 and ma20 < ma60:
            bear.append(f"收盤 {close:.2f} < MA20 < MA60（空頭排列）")

    if len(bull) >= 2:
        signal = "BULL"
    elif len(bear) >= 2:
        signal = "BEAR"
    else:
        signal = "NEUTRAL"

    return {
        "symbol": symbol,
        "signal": signal,
        "date": latest.get("date"),
        "close": close,
        "rsi": rsi,
        "reasons": bull if signal == "BULL" else bear if signal == "BEAR" else bull + bear,
    }
