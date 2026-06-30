# -*- coding: utf-8 -*-
"""
cross_sectional_hardened.py — 跨幣動量 + regime + 風控強化（壓回撤）（唯讀）

基礎：動量 top-K + BTC>100日均 regime（cross_sectional_regime.py 驗過會賺、樣本外正）。
問題：回撤仍大（全期 -58%、樣本外 -34%）。這裡疊加三個標準風控，目標「壓回撤、保報酬」：

  1. 更多持倉   K 由 5 → 8（分散單幣風險）
  2. 反波動加權 權重 ∝ 1/近期波動（波動大的幣權重小，而非等權）
  3. 波動度目標 整體曝險 = min(1, 目標波動 / 近期實際波動)；太亂就降曝險、轉部分現金

無偷看未來：第 t 天收盤算動量/波動 → open[t+1] 進場 → 持有 R 天。切 in/out-of-sample。

重跑：python src/cross_sectional_hardened.py
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
COST = 0.0015
VOLWIN = 20          # 估近期波動的回看天數
ANN = np.sqrt(365.0)


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


def backtest(C, O, L=30, K=5, R=10, regimeN=100,
             weighting="equal", target_vol=None):
    mom = C / C.shift(L) - 1.0
    dret = C.pct_change()
    btc = C["BTCUSDT"]
    regime = btc > btc.rolling(regimeN).mean()
    dates = C.index; n = len(dates); coins = list(C.columns)
    w_prev = pd.Series(0.0, index=coins)
    strat, bench, periods, expo = [], [], [], []
    t = SKIP
    while t + 1 + R < n:
        enter = O.iloc[t + 1]; exit_ = O.iloc[t + 1 + R]
        valid = enter.notna() & exit_.notna() & (enter > 0)
        ret_coins = exit_ / enter - 1.0
        bench_ret = float(ret_coins[valid[valid].index].mean()) if valid.any() else 0.0
        w_new = pd.Series(0.0, index=coins)
        exposure = 0.0
        risk_on = bool(regime.iloc[t]) if pd.notna(regime.iloc[t]) else False
        m = mom.iloc[t].dropna()
        m = m[m.index.isin(valid[valid].index)]
        if risk_on and len(m) >= 6:
            topk = list(m.sort_values(ascending=False).head(K).index)
            # 近期各幣波動（年化）
            win = dret[topk].iloc[max(0, t - VOLWIN + 1):t + 1]
            vol = win.std() * ANN
            vol = vol.replace(0, np.nan)
            if weighting == "invvol" and vol.notna().any():
                w = (1.0 / vol).fillna(0.0)
                w = w / w.sum() if w.sum() > 0 else pd.Series(1.0 / len(topk), index=topk)
            else:
                w = pd.Series(1.0 / len(topk), index=topk)
            exposure = 1.0
            if target_vol:
                bret = (win[w.index] * w).sum(axis=1)        # 該組合近期日報酬
                pv = float(bret.std() * ANN)
                exposure = min(1.0, target_vol / pv) if pv > 0 else 0.0
            for c in w.index:
                w_new[c] = exposure * float(w[c])
        turnover = (w_new - w_prev).abs().sum()
        port = float((w_new * ret_coins.reindex(coins).fillna(0)).sum()) - COST * turnover
        strat.append(port); bench.append(bench_ret); periods.append(dates[t]); expo.append(exposure)
        w_prev = w_new
        t += R
    return pd.Series(strat, index=periods), pd.Series(bench, index=periods), float(np.mean(expo))


def metrics(r, R):
    if len(r) == 0:
        return dict(cagr=0, sharpe=0, mdd=0)
    eq = (1 + r).cumprod()
    years = len(r) * R / 365.0
    cagr = (float(eq.iloc[-1]) ** (1 / years) - 1) * 100 if years > 0.3 else 0.0
    sharpe = float(r.mean() / r.std() * np.sqrt(365.0 / R)) if r.std() > 0 else 0.0
    mdd = float(((eq - eq.cummax()) / eq.cummax()).min()) * 100
    return dict(cagr=cagr, sharpe=sharpe, mdd=mdd)


def main():
    C, O = load_panels()
    mkt = metrics(backtest(C, O)[1], 10)
    print("=" * 104)
    print(f"跨幣動量 + regime + 風控強化（壓回撤）· {C.shape[1]} 幣 · {str(C.index.min())[:10]}~{str(C.index.max())[:10]}")
    print(f"基礎 = 動量 mom30 + BTC>100日均 regime；對照市場(等權) 全期 CAGR ≈ {mkt['cagr']:+.1f}%")
    print("=" * 104)

    variants = [
        ("基準 top5 等權(無目標)",     dict(K=5, weighting="equal")),
        ("+ 波動目標 60%",           dict(K=5, weighting="equal", target_vol=0.60)),
        ("+ 波動目標 50%",           dict(K=5, weighting="equal", target_vol=0.50)),
        ("+ 波動目標 40%",           dict(K=5, weighting="equal", target_vol=0.40)),
        ("+ 波動目標 30%",           dict(K=5, weighting="equal", target_vol=0.30)),
        ("+ 波動目標 25%",           dict(K=5, weighting="equal", target_vol=0.25)),
    ]
    print(f"\n{'強化手法':<26}{'平均曝險':>8}{'全期CAGR':>10}{'全期回撤':>9}{'全期Sharpe':>11}"
          f"{'樣本外CAGR':>11}{'樣本外回撤':>11}{'樣本外Sharpe':>13}")
    print("-" * 104)
    for label, kw in variants:
        s, b, avg_expo = backtest(C, O, R=10, **kw)
        k = int(len(s) * 0.6)
        allm = metrics(s, 10); oos = metrics(s.iloc[k:], 10)
        star = " ★" if (oos["cagr"] > 0 and allm["mdd"] > -40 and oos["mdd"] > -30) else ""
        print(f"{label:<26}{avg_expo*100:>6.0f}%{allm['cagr']:>+9.1f}%{allm['mdd']:>+8.1f}%"
              f"{allm['sharpe']:>11.2f}{oos['cagr']:>+10.1f}%{oos['mdd']:>+10.1f}%{oos['sharpe']:>12.2f}{star}")

    print("\n" + "=" * 104)
    print("判讀：目標是【回撤明顯縮小】(全期由 -58% 往 -30~-40% 壓)且【CAGR、Sharpe 不崩、樣本外仍正】。")
    print("      平均曝險 < 100% 表示波動目標讓它在亂市降槓桿/抱現金 —— 這正是壓回撤的來源。")


if __name__ == "__main__":
    main()
