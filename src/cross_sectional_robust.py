# -*- coding: utf-8 -*-
"""
cross_sectional_robust.py — 跨幣動量成品的兩項加嚴驗證（唯讀）

成品設定：動量 mom30 + BTC>100日均 regime + top5 等權 + 波動度目標 30%。

(A) Walk-forward（分段穩健度）：
    把 5 年切成多個「日曆年」分段，看策略在每一段（含 2022 大空頭）是不是都贏市場、
    都正報酬。只在一段贏 = 僥倖；段段都贏 = 較穩。

(B) 倖存者偏差壓力測試：
    資料只含「活到今天」的幣。真實世界動量有時會買到後來暴崩的幣。
    這裡「注入死亡事件」：每次持有的幣，以機率 p 在持有期內被強制 −90%（模擬暴崩）。
    看不同 p 下 CAGR / 回撤掉多少 → 量化倖存者偏差最多吃掉多少績效。

重跑：python src/cross_sectional_robust.py
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
VOLWIN = 20
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


def backtest(C, O, L=30, K=5, R=10, regimeN=100, target_vol=0.30, death_rate=0.0, seed=0):
    rng = np.random.default_rng(seed)
    mom = C / C.shift(L) - 1.0
    dret = C.pct_change()
    btc = C["BTCUSDT"]; regime = btc > btc.rolling(regimeN).mean()
    dates = C.index; n = len(dates); coins = list(C.columns)
    w_prev = pd.Series(0.0, index=coins)
    strat, bench, periods = [], [], []
    t = SKIP
    while t + 1 + R < n:
        enter = O.iloc[t + 1]; exit_ = O.iloc[t + 1 + R]
        valid = enter.notna() & exit_.notna() & (enter > 0)
        ret_coins = (exit_ / enter - 1.0)
        bench_ret = float(ret_coins[valid[valid].index].mean()) if valid.any() else 0.0
        w_new = pd.Series(0.0, index=coins); exposure = 0.0
        risk_on = bool(regime.iloc[t]) if pd.notna(regime.iloc[t]) else False
        m = mom.iloc[t].dropna(); m = m[m.index.isin(valid[valid].index)]
        rc = ret_coins.copy()
        if risk_on and len(m) >= 6:
            topk = list(m.sort_values(ascending=False).head(K).index)
            w = pd.Series(1.0 / len(topk), index=topk)
            win = dret[topk].iloc[max(0, t - VOLWIN + 1):t + 1]
            if target_vol:
                pv = float((win * (1.0 / len(topk))).sum(axis=1).std() * ANN)
                exposure = min(1.0, target_vol / pv) if pv > 0 else 0.0
            else:
                exposure = 1.0
            # 倖存者壓力：持有的幣以機率 death_rate 被強制暴崩 −90%
            if death_rate > 0:
                for c in topk:
                    if rng.random() < death_rate:
                        rc[c] = -0.90
            for c in topk:
                w_new[c] = exposure * float(w[c])
        turnover = (w_new - w_prev).abs().sum()
        port = float((w_new * rc.reindex(coins).fillna(0)).sum()) - COST * turnover
        strat.append(port); bench.append(bench_ret); periods.append(dates[t])
        w_prev = w_new; t += R
    return pd.Series(strat, index=periods), pd.Series(bench, index=periods)


def perf(r, R=10):
    if len(r) == 0:
        return dict(cagr=0, mdd=0, total=0)
    eq = (1 + r).cumprod()
    yrs = len(r) * R / 365.0
    cagr = (float(eq.iloc[-1]) ** (1 / yrs) - 1) * 100 if yrs > 0.3 else 0.0
    mdd = float(((eq - eq.cummax()) / eq.cummax()).min()) * 100
    total = float(eq.iloc[-1] - 1) * 100
    return dict(cagr=cagr, mdd=mdd, total=total)


def main():
    C, O = load_panels()
    print("=" * 88)
    print("成品加嚴驗證 — 動量mom30 + BTC>100日均 + top5等權 + 波動目標30%")
    print("=" * 88)

    strat, bench = backtest(C, O)

    # ── (A) Walk-forward：分日曆年 ──
    print("\n【A】Walk-forward（每一年都站得住嗎）")
    print(f"  {'年份':<8}{'策略報酬':>10}{'市場報酬':>10}{'超額':>9}{'策略回撤':>9}  結果")
    s_by = strat.groupby(strat.index.year)
    b_by = bench.groupby(bench.index.year)
    wins = 0; yrs = 0
    for y in sorted(s_by.groups):
        sr = s_by.get_group(y); br = b_by.get_group(y)
        sp = perf(sr); bp = perf(br)
        ex = sp["total"] - bp["total"]
        yrs += 1; win = sp["total"] > bp["total"]; wins += int(win)
        tag = "✓ 贏市場" if win else "✗ 輸市場"
        if sp["total"] > 0 and win:
            tag = "✓ 賺且贏市場"
        print(f"  {y:<8}{sp['total']:>+9.1f}%{bp['total']:>+9.1f}%{ex:>+8.1f}%{sp['mdd']:>+8.1f}%  {tag}")
    print(f"  → {wins}/{yrs} 年贏市場。段段都贏 = 穩；只贏一兩段 = 僥倖。")

    # ── (B) 倖存者偏差壓力測試 ──
    print("\n【B】倖存者偏差壓力測試（持有的幣偶爾暴崩 −90%，看績效掉多少）")
    base = perf(strat)
    print(f"  {'每期每幣暴崩機率':<16}{'CAGR':>9}{'最大回撤':>10}{'vs 無暴崩':>11}")
    print(f"  {'0%（原始）':<16}{base['cagr']:>+8.1f}%{base['mdd']:>+9.1f}%{'—':>11}")
    for p in (0.01, 0.02, 0.05):
        cagrs, mdds = [], []
        for seed in range(8):
            s, _ = backtest(C, O, death_rate=p, seed=seed)
            pp = perf(s); cagrs.append(pp["cagr"]); mdds.append(pp["mdd"])
        mc, mm = np.mean(cagrs), np.mean(mdds)
        print(f"  {p*100:>4.0f}%（每幣每期）{'':<6}{mc:>+8.1f}%{mm:>+9.1f}%{mc-base['cagr']:>+10.1f}%")
    print("  → 看 CAGR 掉多少。即使 5% 暴崩率（很悲觀）後仍正 = 倖存者偏差吃不垮它。")

    print("\n" + "=" * 88)
    print("註：(B) 是『悲觀模擬』補救資料缺死亡幣的問題；真實 top-15 大幣暴崩率遠低於這裡測的。")


if __name__ == "__main__":
    main()
