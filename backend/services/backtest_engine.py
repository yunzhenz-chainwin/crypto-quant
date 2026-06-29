import sys
from pathlib import Path

# 讓 backend 可以 import src/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from src.backtest import (
    load_indicators,
    compute_signals,
    parameter_sweep,
    run_backtest,
    compute_metrics,
    walk_forward_split_report,
    REPORT_DIR,
    INTERVAL,
)

# 記憶體快取:key = (幣種, 參數…, 指標檔 mtime) → 結果。
# 含 mtime 代表資料更新(每日排程重產指標)後快取會自動失效,不會回舊結果。
_cache: dict = {}


def _indicators_mtime(symbol: str) -> float:
    try:
        return (REPORT_DIR / f"indicators_{symbol}_{INTERVAL}.csv").stat().st_mtime
    except OSError:
        return 0.0


def get_backtest(symbol: str,
                 stop_loss: float = -0.06,
                 take_profit: float = 0.20,
                 fee_rate: float = 0.001,
                 slippage_rate: float = 0.0005) -> dict:
    key = (symbol, stop_loss, take_profit, fee_rate, slippage_rate,
           _indicators_mtime(symbol))
    if key in _cache:
        return _cache[key]

    df = load_indicators(symbol)
    if df.empty:
        return {"error": "no indicator data"}

    # 訊號只與指標有關 → 算一次,主回測與參數掃描共用(掃描只變停損停利)
    signals = compute_signals(df)

    trades = run_backtest(
        df,
        stop_loss=stop_loss,
        take_profit=take_profit,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        signals=signals,
    )
    metrics = compute_metrics(trades, df)
    split = walk_forward_split_report(
        df,
        stop_loss=stop_loss,
        take_profit=take_profit,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
    )
    sweep = parameter_sweep(
        df,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        signals=signals,
    )

    result = {
        "symbol":  symbol,
        "params":  {
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "fee_rate": fee_rate,
            "slippage_rate": slippage_rate,
        },
        "period":  {
            "start": str(df["date"].min().date()),
            "end":   str(df["date"].max().date()),
        },
        "metrics": {k: v for k, v in metrics.items() if k != "equity_curve"},
        "equity_curve": metrics.get("equity_curve", []),
        "recent_trades": trades[-20:],  # 最近 20 筆，夠前端顯示
        "validation": split,
        "parameter_sweep": sweep[:5],
    }
    _cache[key] = result
    return result
