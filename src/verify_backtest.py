"""
verify_backtest.py
自動驗證回測結果是否正確。
跑完後每一項顯示 PASS 或 FAIL，有 FAIL 代表邏輯有 bug。

用法：
  python src/verify_backtest.py          # 驗證 BTCUSDT
  python src/verify_backtest.py ETHUSDT
"""

import sys
import json
from pathlib import Path

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports"
CLEAN_DIR  = ROOT / "data" / "clean"
INTERVAL   = "1d"

PASS = "  [PASS]"
FAIL = "  [FAIL]"
WARN = "  [WARN]"


def check(cond: bool, label: str, detail: str = ""):
    tag = PASS if cond else FAIL
    print(f"{tag}  {label}")
    if detail:
        print(f"         {detail}")
    return cond


def main():
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "BTCUSDT"

    trades_path  = REPORT_DIR / f"backtest_trades_{symbol}_{INTERVAL}.csv"
    metrics_path = REPORT_DIR / f"backtest_metrics_{symbol}_{INTERVAL}.json"
    price_path   = CLEAN_DIR  / f"{symbol}_{INTERVAL}.csv"

    # ── 檔案存在？ ────────────────────────────────────────────────────
    print(f"\n{'='*56}")
    print(f"  驗證回測結果：{symbol}")
    print(f"{'='*56}")
    print("\n[1] 檔案存在性")
    ok_t = check(trades_path.exists(),  "交易明細 CSV 存在",  str(trades_path))
    ok_m = check(metrics_path.exists(), "績效指標 JSON 存在", str(metrics_path))
    ok_p = check(price_path.exists(),   "原始價格 CSV 存在",  str(price_path))

    if not (ok_t and ok_m and ok_p):
        print("\n缺少必要檔案，請先執行：")
        print(f"  python src/backtest.py {symbol}")
        return

    trades  = pd.read_csv(trades_path)
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    prices  = pd.read_csv(price_path, parse_dates=["date"])

    # ── 基本格式 ─────────────────────────────────────────────────────
    print("\n[2] 資料格式")
    check(len(trades) > 0,
          "有交易記錄",
          f"共 {len(trades)} 筆")
    check(set(["entry_date","exit_date","entry_price","exit_price",
               "return_pct","hold_days","exit_reason","profit"]).issubset(trades.columns),
          "欄位完整")
    check(trades["entry_price"].gt(0).all(),
          "進場價全部 > 0")
    check(trades["exit_price"].gt(0).all(),
          "出場價全部 > 0")
    check((trades["hold_days"] >= 0).all(),
          "持倉天數全部 >= 0")

    # ── 日期邏輯 ─────────────────────────────────────────────────────
    print("\n[3] 日期邏輯")
    entry_dt = pd.to_datetime(trades["entry_date"])
    exit_dt  = pd.to_datetime(trades["exit_date"])
    check((exit_dt >= entry_dt).all(),
          "出場日 >= 進場日（沒有時光機）",
          f"最長持倉 {trades['hold_days'].max()} 天")
    check(entry_dt.is_monotonic_increasing,
          "進場日期依序遞增（沒有重疊倉位）")

    # ── 勝率手算驗證 ────────────────────────────────────────────────
    print("\n[4] 勝率驗證（手算 vs 報告）")
    manual_wins     = int((trades["return_pct"] > 0).sum())
    manual_win_rate = round(manual_wins / len(trades) * 100, 4)
    reported_wr     = round(metrics["win_rate"], 4)
    check(abs(manual_win_rate - reported_wr) < 0.1,
          f"勝率吻合",
          f"手算 {manual_win_rate}%  報告 {reported_wr}%  差 {abs(manual_win_rate-reported_wr):.4f}%")

    # ── 總報酬複利驗算 ───────────────────────────────────────────────
    print("\n[5] 總報酬驗算（手算複利 vs 報告）")
    manual_equity = 1.0
    for r in trades["return_pct"] / 100:
        manual_equity *= (1 + r)
    manual_total = round((manual_equity - 1) * 100, 4)
    reported_total = round(metrics["total_return_pct"], 4)
    check(abs(manual_total - reported_total) < 0.1,
          "複利總報酬吻合",
          f"手算 {manual_total:.2f}%  報告 {reported_total:.2f}%  差 {abs(manual_total-reported_total):.4f}%")

    # ── 買入持有驗算 ─────────────────────────────────────────────────
    print("\n[6] 買入持有驗算（手算 vs 報告）")
    prices_sorted = prices.sort_values("date").reset_index(drop=True)
    first_close   = float(prices_sorted["close"].iloc[0])
    last_close    = float(prices_sorted["close"].iloc[-1])
    manual_bh     = round((last_close / first_close - 1) * 100, 2)
    reported_bh   = round(metrics["buy_hold_return_pct"], 2)
    check(abs(manual_bh - reported_bh) < 1.0,
          "買入持有報酬吻合",
          f"手算 {manual_bh:.2f}%  報告 {reported_bh:.2f}%")

    # ── 進場價格對照原始資料 ─────────────────────────────────────────
    print("\n[7] 進場價格抽查（對照 data/clean/ 原始資料）")
    print("    抽取頭、中、尾三筆交易，確認進場價 = 隔天開盤價")
    print(f"    {'#':<4} {'進場日':<12} {'次日':<12} {'記錄進場價':>14} {'原始次日open':>14} {'差異':>8}")
    print("    " + "-" * 60)

    price_dict = {}
    for _, row in prices_sorted.iterrows():
        d = str(row["date"].date()) if hasattr(row["date"], "date") else str(row["date"])[:10]
        price_dict[d] = {"open": row["open"], "close": row["close"],
                         "high": row["high"],  "low": row["low"]}

    price_dates = sorted(price_dict.keys())

    sample_idx = [0, len(trades)//2, len(trades)-1]
    spot_ok = True
    # 進場「觸發價」= 當日原始開盤價；entry_price 另含滑價，故比對 trigger 才正確
    has_trigger = "entry_trigger_price" in trades.columns
    for idx in sample_idx:
        t = trades.iloc[idx]
        entry_d = str(t["entry_date"])[:10]
        # 找 entry_date 在價格序列的位置，然後找「前一天」的日期
        # （訊號在前一天收盤產生，次日開盤進場 = entry_date 的 open）
        if entry_d in price_dict:
            raw_open = price_dict[entry_d]["open"]
            trigger = t["entry_trigger_price"] if has_trigger else t["entry_price"]
            diff = abs(raw_open - trigger)
            diff_pct = diff / raw_open * 100
            ok = diff_pct < 0.01   # 允許 0.01% 浮點誤差
            spot_ok = spot_ok and ok
            flag = "OK " if ok else "ERR"
            print(f"    {idx+1:<4} {entry_d:<12} {entry_d:<12} "
                  f"{trigger:>14,.2f} {raw_open:>14,.2f} "
                  f"{diff_pct:>7.4f}% {flag}")
        else:
            print(f"    {idx+1:<4} {entry_d:<12} (找不到此日期)")
            spot_ok = False

    check(spot_ok, "進場價 = 當日開盤價（誤差 < 0.01%）")

    # ── 停損邏輯驗證 ─────────────────────────────────────────────────
    print("\n[8] 停損邏輯驗證")
    sl_trades = trades[trades["exit_reason"] == "stop_loss"]
    if len(sl_trades) > 0:
        # 每筆停損出場的報酬應該約等於設定的停損比例
        # 預設停損 -6%，所以停損出場的 return_pct 應該約 -6%
        sl_returns = sl_trades["return_pct"]
        check(sl_returns.max() < 0,
              "停損出場的損益全部 < 0（沒有停損卻賺錢的矛盾）",
              f"停損出場最大損益 {sl_returns.max():.2f}%")
        check(sl_returns.min() > -20,
              "停損出場損益未超過 -20%（停損有真的生效）",
              f"停損出場損益範圍：{sl_returns.min():.2f}% ~ {sl_returns.max():.2f}%")
    else:
        print(f"{WARN}  無停損出場記錄（停損設太大或信號太準）")

    # ── 停利邏輯驗證 ─────────────────────────────────────────────────
    tp_trades = trades[trades["exit_reason"] == "take_profit"]
    if len(tp_trades) > 0:
        tp_returns = tp_trades["return_pct"]
        check(tp_returns.min() > 0,
              "停利出場的損益全部 > 0（停利有真的生效）",
              f"停利出場損益範圍：{tp_returns.min():.2f}% ~ {tp_returns.max():.2f}%")
    else:
        print(f"{WARN}  無停利出場記錄（停利設太高）")

    # ── 出場次數加總 ─────────────────────────────────────────────────
    print("\n[9] 出場次數加總")
    sl_count = int((trades["exit_reason"] == "stop_loss").sum())
    tp_count = int((trades["exit_reason"] == "take_profit").sum())
    sig_count= int((trades["exit_reason"] == "signal_exit").sum())
    total_check = sl_count + tp_count + sig_count
    check(total_check == len(trades),
          "停損 + 停利 + 訊號出場 = 總交易數",
          f"{sl_count} + {tp_count} + {sig_count} = {total_check}（總數 {len(trades)}）")

    # ── 最終結論 ─────────────────────────────────────────────────────
    print(f"\n{'='*56}")
    print("  驗證完成。若全部 PASS，回測邏輯正確。")
    print(f"  FAIL 的項目代表有 bug，請回報給 Claude 協助修正。")
    print(f"{'='*56}")

    # 順便印出績效摘要讓你確認數字合理
    print(f"\n績效摘要：")
    print(f"  交易次數：{metrics['total_trades']}")
    print(f"  勝率    ：{metrics['win_rate']:.1f}%")
    print(f"  總報酬  ：{metrics['total_return_pct']:+.2f}%  "
          f"（買入持有 {metrics['buy_hold_return_pct']:+.2f}%）")
    print(f"  最大回撤：{metrics['max_drawdown_pct']:.2f}%")
    print(f"  夏普比率：{metrics['sharpe_ratio']:.2f}")


if __name__ == "__main__":
    main()
