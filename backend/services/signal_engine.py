"""
signal_engine.py — 前端大卡的多空建議與信心分數

計分邏輯抽到 src/scoring.py，與回測（src/backtest.py）共用同一套 6 因子，
確保「畫面建議」與「回測買賣依據」是同一套標準。
"""
import sys
from pathlib import Path

# 確保能 import 專案根目錄下的 src/（無論從哪裡啟動 backend）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.services.reader import load_indicators
from src.scoring import score_row, signal_from_score


def get_signal(symbol: str) -> dict:
    rows = load_indicators(symbol, days=5)
    if not rows:
        return {"symbol": symbol, "signal": "UNKNOWN", "score": 50, "reasons": [], "factors": {}}

    latest = rows[-1]
    prev   = rows[-2] if len(rows) >= 2 else latest

    score, factors = score_row(
        rsi=latest.get("RSI"),       hist=latest.get("HIST"),  prev_hist=prev.get("HIST"),
        close=latest.get("close"),   ma20=latest.get("MA20"),  ma60=latest.get("MA60"),
        ma200=latest.get("MA200"),   volume=latest.get("volume"),
        vol_ma20=latest.get("VOL_MA20"),
        bb_upper=latest.get("BB_UPPER"), bb_lower=latest.get("BB_LOWER"),
    )
    signal = signal_from_score(score)

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
        "close":    latest.get("close"),
        "rsi":      latest.get("RSI"),
        "ma200":    latest.get("MA200"),
        "bb_upper": latest.get("BB_UPPER"),
        "bb_lower": latest.get("BB_LOWER"),
        "reasons":  reasons,
        "factors":  factors,
    }
