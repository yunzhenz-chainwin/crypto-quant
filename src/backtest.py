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

# 與前端 signal_engine 共用同一套 6 因子計分（兩種執行方式都要能 import）：
#   python src/backtest.py      → sys.path[0] 是 src/，走 `from scoring`
#   from src.backtest import …  → 專案根在 path，走 `from src.scoring`
try:
    from src.scoring import score_row, signal_from_score
except ImportError:
    from scoring import score_row, signal_from_score


# ── 資料載入 ──────────────────────────────────────────────────────────
def load_indicators(symbol: str) -> pd.DataFrame:
    path = REPORT_DIR / f"indicators_{symbol}_{INTERVAL}.csv"
    if not path.exists():
        sys.exit(f"找不到 {path}，請先執行：python src/indicators.py {symbol}")
    df = pd.read_csv(path, parse_dates=["date"])
    return df.sort_values("date").reset_index(drop=True)


# ── 訊號計算（與前端共用 src/scoring 的 6 因子計分）──────────────────
def _col(df, key):
    """取欄位的 numpy 陣列;欄位不存在則回傳全 NaN(視為缺值)。"""
    return df[key].to_numpy() if key in df.columns else np.full(len(df), np.nan)


def _num(v):
    """numpy 值 → float;NaN / 缺值回 None。"""
    return float(v) if (v is not None and v == v) else None


def compute_signals(df: pd.DataFrame) -> list[str]:
    """逐日計算訊號，回傳與 df 等長的訊號清單。
    sigs[i] = 第 i 天收盤後可得知的訊號（用第 i 天 vs 第 i-1 天資料計算）。
    進場條件：sigs[i-1]=='BULL' and sigs[i-2]!='BULL' → 第 i 天開盤買入（隔日開盤）。

    使用與前端「信心分數」完全相同的 6 因子計分（src/scoring.score_row），
    確保回測驗證的策略 == 畫面上建議的策略（分數 ≥65 視為 BULL）。
    """
    n = len(df)
    if n == 0:
        return []
    # 一次取出所有欄位為 numpy 陣列,迴圈內用整數索引(不逐列 .iloc,快很多)
    rsi = _col(df, "RSI");   hist = _col(df, "HIST");  close = _col(df, "close")
    ma20 = _col(df, "MA20"); ma60 = _col(df, "MA60");  ma200 = _col(df, "MA200")
    vol = _col(df, "volume"); vma = _col(df, "VOL_MA20")
    bbu = _col(df, "BB_UPPER"); bbl = _col(df, "BB_LOWER")

    sigs = ["NEUTRAL"]  # index 0：第一天無前日資料，給預設 NEUTRAL
    for i in range(1, n):
        score, _ = score_row(
            _num(rsi[i]), _num(hist[i]), _num(hist[i - 1]),
            _num(close[i]), _num(ma20[i]), _num(ma60[i]), _num(ma200[i]),
            _num(vol[i]), _num(vma[i]), _num(bbu[i]), _num(bbl[i]),
        )
        sigs.append(signal_from_score(score))
    return sigs


# ── 回測核心 ──────────────────────────────────────────────────────────
def run_backtest(df: pd.DataFrame,
                 stop_loss: float = -0.06,
                 take_profit: float = 0.20,
                 fee_rate: float = 0.001,
                 slippage_rate: float = 0.0005,
                 signals: list[str] = None) -> list[dict]:
    """
    回傳交易明細清單，每筆包含：
      entry_date, exit_date, entry_price, exit_price,
      return_pct, hold_days, exit_reason
    """
    signals = signals or compute_signals(df)
    # 一次取出價格欄位為陣列(不逐列 .iloc),日期保留為 Timestamp 清單
    opens = df["open"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows  = df["low"].to_numpy(dtype=float)
    dates = df["date"].tolist()
    trades = []
    position = None  # None = 空倉；dict = 持倉中

    for i in range(2, len(df)):
        sig_today = signals[i]
        sig_prev = signals[i - 1]
        sig_prev2 = signals[i - 2]

        if position is None:
            # 進場條件：前一天訊號首次出現 BULL（前兩天不是 BULL）
            if sig_prev == "BULL" and sig_prev2 != "BULL":
                ep = opens[i]
                if ep != ep or ep <= 0:        # NaN(ep!=ep) 或非正值
                    continue
                fill_price = float(ep) * (1 + slippage_rate)
                position = {
                    "entry_date":  str(dates[i].date()),
                    "entry_price": float(fill_price),
                    "entry_trigger_price": float(ep),
                    "stop_price":  ep * (1 + stop_loss),
                    "tp_price":    ep * (1 + take_profit),
                }
        else:
            ep = position["entry_price"]
            exit_price = None
            exit_reason = None

            low  = lows[i]  if lows[i]  == lows[i]  else ep   # nan==nan 為 False
            high = highs[i] if highs[i] == highs[i] else ep

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
                exit_price = float(opens[i])
                exit_reason = "signal_exit"

            if exit_price is not None:
                raw_exit_price = float(exit_price)
                fill_exit_price = raw_exit_price * (1 - slippage_rate)
                gross_ret = (raw_exit_price - position["entry_trigger_price"]) / position["entry_trigger_price"]
                net_ret = (fill_exit_price * (1 - fee_rate)) / (ep * (1 + fee_rate)) - 1
                entry_dt = pd.Timestamp(position["entry_date"])
                exit_dt  = dates[i]
                # 統一為 tz-naive 才能相減
                if hasattr(exit_dt, "tz_convert"):
                    exit_dt = exit_dt.tz_convert(None)
                exit_date_str = str(exit_dt.date())
                trades.append({
                    "entry_date":  position["entry_date"],
                    "exit_date":   exit_date_str,
                    "entry_price": float(round(ep, 4)),
                    "exit_price":  float(round(fill_exit_price, 4)),
                    "entry_trigger_price": float(round(position["entry_trigger_price"], 4)),
                    "exit_trigger_price":  float(round(raw_exit_price, 4)),
                    "gross_return_pct": float(round(gross_ret * 100, 3)),
                    "return_pct":  float(round(net_ret * 100, 3)),
                    "cost_pct":    float(round((gross_ret - net_ret) * 100, 3)),
                    "hold_days":   int((exit_dt - entry_dt).days),
                    "exit_reason": exit_reason,
                    "profit":      bool(net_ret > 0),  # 明確轉成 Python bool
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
    bh_equity = df["close"].astype(float) / float(df["close"].iloc[0])
    bh_peak = bh_equity.cummax()
    bh_dd = (bh_equity - bh_peak) / bh_peak
    bh_max_dd = float(bh_dd.min() * 100)

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
        "buy_hold_max_drawdown_pct": f(bh_max_dd),
        "excess_return_pct":   f(total_return - bh_return),
        "avg_cost_pct":        f(float(np.mean([t.get("cost_pct", 0.0) for t in trades]))),
        "stop_loss_exits":     int(sum(1 for t in trades if t["exit_reason"] == "stop_loss")),
        "take_profit_exits":   int(sum(1 for t in trades if t["exit_reason"] == "take_profit")),
        "signal_exits":        int(sum(1 for t in trades if t["exit_reason"] == "signal_exit")),
        "equity_curve":        equity_curve,
    }


def split_dataframe(df: pd.DataFrame, train_ratio: float = 0.60) -> tuple[pd.DataFrame, pd.DataFrame]:
    """依時間順序切成 in-sample / out-of-sample，不打亂資料。"""
    if df.empty:
        return df.copy(), df.copy()
    split_idx = max(1, min(len(df) - 1, int(len(df) * train_ratio)))
    return df.iloc[:split_idx].copy(), df.iloc[split_idx:].copy()


def run_backtest_report(df: pd.DataFrame,
                        stop_loss: float = -0.06,
                        take_profit: float = 0.20,
                        fee_rate: float = 0.001,
                        slippage_rate: float = 0.0005,
                        signals: list[str] = None) -> dict:
    trades = run_backtest(
        df,
        stop_loss=stop_loss,
        take_profit=take_profit,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        signals=signals,
    )
    metrics = compute_metrics(trades, df)
    return {"trades": trades, "metrics": metrics}


def walk_forward_split_report(df: pd.DataFrame,
                              stop_loss: float = -0.06,
                              take_profit: float = 0.20,
                              fee_rate: float = 0.001,
                              slippage_rate: float = 0.0005,
                              train_ratio: float = 0.60) -> dict:
    train_df, test_df = split_dataframe(df, train_ratio=train_ratio)
    train = run_backtest_report(
        train_df,
        stop_loss,
        take_profit,
        fee_rate,
        slippage_rate,
        signals=compute_signals(train_df),
    )
    test = run_backtest_report(
        test_df,
        stop_loss,
        take_profit,
        fee_rate,
        slippage_rate,
        signals=compute_signals(test_df),
    )

    def compact(metrics: dict) -> dict:
        return {k: v for k, v in metrics.items() if k != "equity_curve"}

    return {
        "train_ratio": train_ratio,
        "in_sample": {
            "period": {
                "start": str(train_df["date"].min().date()),
                "end": str(train_df["date"].max().date()),
            },
            "metrics": compact(train["metrics"]),
        },
        "out_of_sample": {
            "period": {
                "start": str(test_df["date"].min().date()),
                "end": str(test_df["date"].max().date()),
            },
            "metrics": compact(test["metrics"]),
        },
    }


def parameter_sweep(df: pd.DataFrame,
                    stop_losses: list[float] = None,
                    take_profits: list[float] = None,
                    fee_rate: float = 0.001,
                    slippage_rate: float = 0.0005,
                    signals: list[str] = None) -> list[dict]:
    stop_losses = stop_losses or [-0.03, -0.05, -0.06, -0.08, -0.10]
    take_profits = take_profits or [0.10, 0.15, 0.20, 0.25, 0.30]
    rows = []
    # 訊號只與指標有關、與停損停利無關 → 整個掃描共用同一份(可由外部傳入避免重算)
    signals = signals or compute_signals(df)
    for stop_loss in stop_losses:
        for take_profit in take_profits:
            report = run_backtest_report(
                df,
                stop_loss=stop_loss,
                take_profit=take_profit,
                fee_rate=fee_rate,
                slippage_rate=slippage_rate,
                signals=signals,
            )
            metrics = report["metrics"]
            if "error" in metrics:
                continue
            rows.append({
                "stop_loss": float(stop_loss),
                "take_profit": float(take_profit),
                "total_trades": metrics["total_trades"],
                "total_return_pct": metrics["total_return_pct"],
                "buy_hold_return_pct": metrics["buy_hold_return_pct"],
                "excess_return_pct": metrics["excess_return_pct"],
                "max_drawdown_pct": metrics["max_drawdown_pct"],
                "sharpe_ratio": metrics["sharpe_ratio"],
                "profit_factor": metrics["profit_factor"],
                "win_rate": metrics["win_rate"],
            })
    return sorted(rows, key=lambda r: (r["sharpe_ratio"], r["excess_return_pct"]), reverse=True)


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
