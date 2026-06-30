# -*- coding: utf-8 -*-
"""
cross_sectional_validate.py — 跨幣動量「扣成本 + 樣本外」驗證（唯讀）

cross_sectional.py 發現「跨幣動量（強者恆強）」有毛 edge。
這裡做能不能「真的用」的驗證：
  - 純做多 top-K（不放空，較實際）
  - 每 R 天換倉一次（降低換手），equal weight
  - 扣交易成本（依實際換手量計）
  - 對照基準 = 全體等權（= 市場、buy & hold 概念）
  - 切 in-sample（前 60%）/ out-of-sample（後 40%）看會不會樣本外失效

無偷看未來：第 t 天收盤算動量 → open[t+1] 進場 → 持有 R 天 → 再平衡。

重跑：python src/cross_sectional_validate.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

CLEAN = ROOT / "data" / "clean"
INTERVAL = "1d"
SKIP = 200
COST = 0.0015          # 每單位換手量的成本（≈ 來回 0.3% 的一半計在單邊變動上，保守）


def load_panels():
    closes, opens = {}, {}
    for p in sorted(CLEAN.glob(f"*_{INTERVAL}.csv")):
        sym = p.stem.replace(f"_{INTERVAL}", "")
        df = pd.read_csv(p, parse_dates=["date"]).sort_values("date")
        s = df.set_index("date")
        closes[sym] = s["close"].astype(float)
        opens[sym] = s["open"].astype(float)
    C = pd.DataFrame(closes).sort_index()
    O = pd.DataFrame(opens).sort_index().reindex(C.index)
    return C, O


def backtest(C, O, L, K, R, cost=COST):
    """純做多 top-K 動量，每 R 天再平衡，扣成本。回傳每期淨報酬與基準每期報酬。"""
    mom = C / C.shift(L) - 1.0
    dates = C.index
    n = len(dates)
    coins = list(C.columns)
    w_prev = pd.Series(0.0, index=coins)

    strat, bench, periods = [], [], []
    t = SKIP
    while t + 1 + R < n:
        m = mom.iloc[t].dropna()
        # 進出場價：open[t+1] → open[t+1+R]
        enter = O.iloc[t + 1]
        exit_ = O.iloc[t + 1 + R]
        valid = enter.notna() & exit_.notna() & (enter > 0)
        m = m[m.index.isin(valid[valid].index)]
        if len(m) < 6:
            t += R
            continue
        topk = m.sort_values(ascending=False).head(K).index
        w_new = pd.Series(0.0, index=coins)
        w_new[topk] = 1.0 / len(topk)
        turnover = (w_new - w_prev).abs().sum()
        ret_coins = (exit_ / enter - 1.0)
        port = float((w_new * ret_coins).sum()) - cost * turnover
        # 基準：全體等權
        vmask = valid[valid].index
        bench_ret = float(ret_coins[vmask].mean())
        strat.append(port); bench.append(bench_ret)
        periods.append(dates[t])
        w_prev = w_new
        t += R
    return pd.Series(strat, index=periods), pd.Series(bench, index=periods), R


def metrics(returns, R):
    if len(returns) == 0:
        return dict(n=0, total=0, cagr=0, sharpe=0, mdd=0, hit=0)
    eq = (1 + returns).cumprod()
    total = float(eq.iloc[-1] - 1) * 100
    years = len(returns) * R / 365.0
    cagr = (float(eq.iloc[-1]) ** (1 / years) - 1) * 100 if years > 0.3 else 0.0
    sharpe = float(returns.mean() / returns.std() * np.sqrt(365.0 / R)) if returns.std() > 0 else 0.0
    peak = eq.cummax(); mdd = float(((eq - peak) / peak).min()) * 100
    hit = float((returns > 0).mean()) * 100
    return dict(n=len(returns), total=total, cagr=cagr, sharpe=sharpe, mdd=mdd, hit=hit)


def split_metrics(strat, bench, R):
    k = int(len(strat) * 0.6)
    out = {}
    for label, sl in [("全期", slice(None)), ("樣本內(前60%)", slice(0, k)), ("樣本外(後40%)", slice(k, None))]:
        out[label] = (metrics(strat.iloc[sl], R), metrics(bench.iloc[sl], R))
    return out


def main():
    C, O = load_panels()
    print("=" * 100)
    print(f"跨幣動量 — 扣成本 + 樣本外驗證 · {C.shape[1]} 幣 · {str(C.index.min())[:10]}~{str(C.index.max())[:10]}")
    print(f"純做多 top-K、每 R 天換倉、成本 {COST*100:.2f}%/單位換手；對照=全體等權（市場）")
    print("=" * 100)

    configs = [(14, 3, 5), (14, 5, 10), (30, 3, 10), (30, 5, 10), (30, 5, 20), (14, 4, 10)]
    print(f"\n{'設定(L/K/R)':<14}{'區間':<14}{'策略CAGR':>10}{'市場CAGR':>10}{'超額':>8}"
          f"{'策略Sharpe':>11}{'最大回撤':>9}{'命中':>7}{'期數':>6}")
    print("-" * 100)
    for (L, K, R) in configs:
        strat, bench, _ = backtest(C, O, L, K, R)
        sm = split_metrics(strat, bench, R)
        tag = f"mom{L}/top{K}/{R}d"
        for label in ("全期", "樣本內(前60%)", "樣本外(後40%)"):
            s, b = sm[label]
            excess = s["cagr"] - b["cagr"]
            star = " ★" if (label == "樣本外(後40%)" and excess > 3 and s["cagr"] > b["cagr"]) else ""
            print(f"{tag if label=='全期' else '':<14}{label:<14}{s['cagr']:>+9.1f}%{b['cagr']:>+9.1f}%"
                  f"{excess:>+7.1f}%{s['sharpe']:>11.2f}{s['mdd']:>+8.1f}%{s['hit']:>6.1f}%{s['n']:>6}{star}")
        print("-" * 100)

    print("\n判讀：看『樣本外(後40%)』策略 CAGR 是否仍贏市場（超額為正、★）、Sharpe 是否>市場、回撤可不可接受。")
    print("      樣本外仍贏 = edge 較可能是真的；樣本外失效 = 樣本內過擬合。")


if __name__ == "__main__":
    main()
