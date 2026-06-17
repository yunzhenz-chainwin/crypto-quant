"""
backtest.py
把現有的 BULL/BEAR 訊號邏輯跑過歷史資料，計算每筆交易的損益與整體績效。

交易規則：
  進場：訊號從「非 BULL」→「BULL」的隔天開盤買入
  出場（三擇一，先觸發先出）：
    1. 停損：當天最低價 <= 進場價 * (1 + stop_loss)，以停損價出場
    2. 停利：當天最高價 >= 進場價 * (1 + take_profit)，以停利價出場
    3. 訊號：訊號轉 BEAR 的隔天開盤賣出

用法：
  python src/backtest.py                    # 預設 BTCUSDT
  python src/backtest.py ETHUSDT
  python src/backtest.py BTCUSDT -0.08 0.25 # 自訂停損 -8%、停利 +25%
"""

import sys
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports"
INTERVAL = "1d"


# ── 資料載入 ──────────────────────────────────────────────────────────
def load_indicators(symbol: str) -> pd.DataFrame:
    path = REPORT_DIR / f"indicators_{symbol}_{INTERVAL}.csv"
    if not path.exists():
        sys.exit(f"找不到 {path}，請先執行：python src/indicators.py {symbol}")
    df = pd.read_csv(path, parse_dates=["date"])
    return df.sort_values("date").reset_index(drop=True)


# ── 訊號計算（完全複製 signal_engine.py 的邏輯）─────────────────────
def _row_signal(rsi, hist, prev_hist, close, ma20, ma60) -> str:
    bull, bear = [], []

    if rsi is not None:
        if rsi < 35:
            bull.append("rsi_oversold")
        elif rsi > 65:
            bear.append("rsi_overbought")

    if hist is not None and prev_hist is not None:
        if prev_hist < 0 and hist >= 0:
            bull.append("macd_golden")
        elif prev_hist > 0 and hist <= 0:
            bear.append("macd_death")
        elif hist > prev_hist:
            bull.append("macd_strengthening")
        else:
            bear.append("macd_weakening")

    if close and ma20 and ma60:
        if close > ma20 and ma20 > ma60:
            bull.append("ma_bull")
        elif close < ma20 and ma20 < ma60:
            bear.append("ma_bear")

    if len(bull) >= 2:
        return "BULL"
    if len(bear) >= 2:
        return "BEAR"
    return "NEUTRAL"


def compute_signals(df: pd.DataFrame) -> list[str]:
    """逐日計算訊號，回傳與 df 等長的訊號清單。"""
    sigs = ["NEUTRAL", "NEUTRAL"]  # 前兩天沒有前一天可比，給預設值
    for i in range(1, len(df)):
        cur, prv = df.iloc[i], df.iloc[i - 1]
        sig = _row_signal(
            rsi=cur["RSI"] if pd.notna(cur["RSI"]) else None,
            hist=cur["HIST"] if pd.notna(cur["HIST"]) else None,
            prev_hist=prv["HIST"] if pd.notna(prv["HIST"]) else None,
            close=cur["close"] if pd.notna(cur["close"]) else None,
            ma20=cur["MA20"] if pd.notna(cur["MA20"]) else None,
            ma60=cur["MA60"] if pd.notna(cur["MA60"]) else None,
        )
        sigs.append(sig)
    return sigs


# ── 回測核心 ──────────────────────────────────────────────────────────
def run_backtest(df: pd.DataFrame,
                 stop_loss: float = -0.06,
                 take_profit: float = 0.20) -> list[dict]:
    """
    回傳交易明細清單，每筆包含：
      entry_date, exit_date, entry_price, exit_price,
      return_pct, hold_days, exit_reason
    """
    signals = compute_signals(df)
    trades = []
    position = None  # None = 空倉；dict = 持倉中

    for i in range(2, len(df)):
        today = df.iloc[i]
        sig_today = signals[i]
        sig_prev = signals[i - 1]
        sig_prev2 = signals[i - 2]

        if position is None:
            # 進場條件：前一天訊號首次出現 BULL（前兩天不是 BULL）
            if sig_prev == "BULL" and sig_prev2 != "BULL":
                ep = today["open"]
                if pd.isna(ep) or ep <= 0:
                    continue
                position = {
                    "entry_date":  str(today["date"].date()),
                    "entry_price": float(ep),
                    "stop_price":  ep * (1 + stop_loss),
                    "tp_price":    ep * (1 + take_profit),
                }
        else:
            ep = position["entry_price"]
            exit_price = None
            exit_reason = None

            low  = today["low"]  if pd.notna(today["low"])  else ep
            high = today["high"] if pd.notna(today["high"]) else ep

            # 停損（日內觸及）
            if low <= position["stop_price"]:
                exit_price = position["stop_price"]
                exit_reason = "stop_loss"
            # 停利（日內觸及）
            elif high >= position["tp_price"]:
                exit_price = position["tp_price"]
                exit_reason = "take_profit"
            # 訊號出場：訊號首次轉 BEAR
            elif sig_today == "BEAR" and sig_prev != "BEAR":
                exit_price = float(today["open"])
                exit_reason = "signal_exit"

            if exit_price is not None:
                ret = (exit_price - ep) / ep
                entry_dt = pd.Timestamp(position["entry_date"])
                exit_dt  = today["date"]
                # 統一為 tz-naive 才能相減
                if hasattr(exit_dt, "tz_convert"):
                    exit_dt = exit_dt.tz_convert(None)
                exit_date_str = str(exit_dt.date())
                trades.append({
                    "entry_date":  position["entry_date"],
                    "exit_date":   exit_date_str,
                    "entry_price": float(round(ep, 4)),
                    "exit_price":  float(round(exit_price, 4)),
                    "return_pct":  float(round(ret * 100, 3)),
                    "hold_days":   int((exit_dt - entry_dt).days),
                    "exit_reason": exit_reason,
                    "profit":      bool(ret > 0),  # 明確轉成 Python bool
                })
                position = None

    return trades


# ── 績效指標計算 ──────────────────────────────────────────────────────
def compute_metrics(trades: list[dict], df: pd.DataFrame) -> dict:
    if not trades:
        return {"error": "無交易記錄，可能訊號條件太嚴格"}

    rets = [t["return_pct"] / 100 for t in trades]
    wins   = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]

    win_rate     = len(wins) / len(rets) * 100
    avg_win      = float(np.mean(wins) * 100)   if wins   else 0.0
    avg_loss     = float(np.mean(losses) * 100) if losses else 0.0
    gross_profit = sum(wins)
    gross_loss   = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999.0

    # 複利總報酬
    equity = [1.0]
    for r in rets:
        equity.append(equity[-1] * (1 + r))
    total_return = (equity[-1] - 1) * 100

    # 年化報酬（CAGR）
    years = (pd.Timestamp(trades[-1]["exit_date"]) -
             pd.Timestamp(trades[0]["entry_date"])).days / 365.25
    cagr = ((equity[-1]) ** (1 / years) - 1) * 100 if years > 0.1 else 0.0

    # 最大回撤
    arr = np.array(equity)
    peak     = np.maximum.accumulate(arr)
    drawdown = (arr - peak) / peak
    max_dd   = float(np.min(drawdown) * 100)

    # 夏普比率（以每日報酬近似）
    hold_days = [t["hold_days"] for t in trades]
    avg_hold  = float(np.mean(hold_days))
    if len(rets) > 1 and float(np.std(rets)) > 0:
        sharpe = (float(np.mean(rets)) / float(np.std(rets))) * math.sqrt(
            max(365 / avg_hold, 1))
    else:
        sharpe = 0.0

    # 買入持有比較
    bh_return = (float(df["close"].iloc[-1]) / float(df["close"].iloc[0]) - 1) * 100

    # 權益曲線（供圖表用，每筆交易後的資產倍數）
    equity_curve = [
        {"trade": i + 1, "equity": float(round(e, 4)), "date": trades[i]["exit_date"]}
        for i, e in enumerate(equity[1:])
    ]

    # 全部轉成 Python 原生型別，避免 FastAPI 序列化 numpy 類型失敗
    def f(v): return float(round(float(v), 4))

    return {
        "total_trades":        int(len(trades)),
        "win_rate":            f(win_rate),
        "avg_win_pct":         f(avg_win),
        "avg_loss_pct":        f(avg_loss),
        "profit_factor":       f(profit_factor),
        "total_return_pct":    f(total_return),
        "cagr_pct":            f(cagr),
        "max_drawdown_pct":    f(max_dd),
        "sharpe_ratio":        f(sharpe),
        "avg_hold_days":       f(avg_hold),
        "buy_hold_return_pct": f(bh_return),
        "stop_loss_exits":     int(sum(1 for t in trades if t["exit_reason"] == "stop_loss")),
        "take_profit_exits":   int(sum(1 for t in trades if t["exit_reason"] == "take_profit")),
        "signal_exits":        int(sum(1 for t in trades if t["exit_reason"] == "signal_exit")),
        "equity_curve":        equity_curve,
    }


# ── CLI 報告輸出 ──────────────────────────────────────────────────────
def print_report(symbol: str, metrics: dict, trades: list[dict], df: pd.DataFrame):
    if "error" in metrics:
        print(f"\n[ERROR] {metrics['error']}")
        return

    sep = "=" * 58
    print(f"\n{sep}")
    print(f"  {symbol} Backtest Report")
    print(f"  Period : {df['date'].min().date()} ~ {df['date'].max().date()}")
    print(sep)
    print(f"  Total Trades      : {metrics['total_trades']}")
    print(f"  Win Rate          : {metrics['win_rate']}%")
    print(f"  Avg Win           : +{metrics['avg_win_pct']}%")
    print(f"  Avg Loss          : {metrics['avg_loss_pct']}%")
    print(f"  Profit Factor     : {metrics['profit_factor']}  (>1 = overall profitable)")
    print(f"{'-'*58}")
    print(f"  Total Return      : {metrics['total_return_pct']:+.2f}%")
    print(f"  CAGR              : {metrics['cagr_pct']:+.2f}%")
    print(f"  Max Drawdown      : {metrics['max_drawdown_pct']:.2f}%")
    print(f"  Sharpe Ratio      : {metrics['sharpe_ratio']}")
    print(f"  Avg Hold Days     : {metrics['avg_hold_days']} days")
    print(f"{'-'*58}")
    print(f"  Buy & Hold Return : {metrics['buy_hold_return_pct']:+.2f}%  (benchmark)")
    print(f"{'-'*58}")
    print(f"  Exits: stop_loss {metrics['stop_loss_exits']} / "
          f"take_profit {metrics['take_profit_exits']} / "
          f"signal {metrics['signal_exits']}")
    print(f"{sep}")

    print(f"\nLast 5 Trades (for manual verification):")
    print(f"{'#':<4} {'Entry':<12} {'Exit':<12} {'EntryPx':>12} {'ExitPx':>12} "
          f"{'Ret%':>8} {'Days':>5} Result  Reason")
    print("-" * 80)
    for n, t in enumerate(trades[-5:], start=len(trades) - 4):
        flag = "WIN " if t["profit"] else "LOSS"
        print(f"{n:<3} {t['entry_date']:<12} {t['exit_date']:<12} "
              f"{t['entry_price']:>12,.2f} {t['exit_price']:>12,.2f} "
              f"{t['return_pct']:>+7.2f}% {t['hold_days']:>4}d "
              f"{flag} {t['exit_reason']}")


def main():
    args = sys.argv[1:]
    symbol     = args[0].upper() if args else "BTCUSDT"
    stop_loss  = float(args[1]) if len(args) > 1 else -0.06
    take_profit= float(args[2]) if len(args) > 2 else 0.20

    df     = load_indicators(symbol)
    trades = run_backtest(df, stop_loss=stop_loss, take_profit=take_profit)
    metrics= compute_metrics(trades, df)

    print_report(symbol, metrics, trades, df)

    # 儲存交易明細與指標 JSON
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(trades).to_csv(
        REPORT_DIR / f"backtest_trades_{symbol}_{INTERVAL}.csv", index=False)

    metrics_out = {k: v for k, v in metrics.items() if k != "equity_curve"}
    with open(REPORT_DIR / f"backtest_metrics_{symbol}_{INTERVAL}.json",
              "w", encoding="utf-8") as f:
        json.dump(metrics_out, f, indent=2, ensure_ascii=False)

    print(f"\n已儲存：reports/backtest_trades_{symbol}_{INTERVAL}.csv")
    print(f"已儲存：reports/backtest_metrics_{symbol}_{INTERVAL}.json")


if __name__ == "__main__":
    main()
