import sys
from pathlib import Path

# 讓 backend 可以 import src/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from src.backtest import (
    load_indicators,
    parameter_sweep,
    run_backtest,
    compute_metrics,
    walk_forward_split_report,
)


def get_backtest(symbol: str,
                 stop_loss: float = -0.06,
                 take_profit: float = 0.20,
                 fee_rate: float = 0.001,
                 slippage_rate: float = 0.0005) -> dict:
    df = load_indicators(symbol)
    if df.empty:
        return {"error": "no indicator data"}

    trades = run_backtest(
        df,
        stop_loss=stop_loss,
        take_profit=take_profit,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
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
    )

    return {
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
