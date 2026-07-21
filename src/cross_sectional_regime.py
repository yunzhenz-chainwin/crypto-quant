# -*- coding: utf-8 -*-
"""
cross_sectional_regime.py — 跨幣動量 + 市場 regime 過濾 驗證（唯讀）

cross_sectional_validate.py 顯示：跨幣動量扣成本後邊際、且絕對報酬負、回撤 -75%，
主因是「空頭時還抱著一籃子最強的爛幣」。這裡加 regime 過濾：

  多頭（BTC 站上 N 日均線）→ 持有 top-K 動量幣
  空頭（BTC 跌破 N 日均線）→ 轉現金（報酬 0，仍計切換成本）

對每個設定並排比較「無過濾 / BTC>100MA / BTC>200MA」，看回撤與絕對報酬有沒有改善，
並切 in-sample(前60%) / out-of-sample(後40%)。無偷看未來。

重跑：python src/cross_sectional_regime.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from src.cross_sectional import realized_holding_returns, max_drawdown_from_returns

CLEAN = ROOT / "data" / "clean"
INTERVAL = "1d"
SKIP = 200
COST = 0.0015


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


def regime_signal(C, N):
    """BTC 站上 N 日均線 = 多頭(True)。N=0 表示不過濾(永遠 True)。"""
    if N == 0:
        return pd.Series(True, index=C.index)
    btc = C["BTCUSDT"]
    return btc > btc.rolling(N).mean()


def backtest(C, O, L, K, R, regime, cost=COST):
    mom = C / C.shift(L) - 1.0
    dates = C.index
    n = len(dates)
    coins = list(C.columns)
    w_prev = pd.Series(0.0, index=coins)
    strat, bench, periods = [], [], []
    in_mkt = 0
    t = SKIP
    while t + 1 + R < n:
        enter = O.iloc[t + 1]; exit_ = O.iloc[t + 1 + R]
        ret_coins = realized_holding_returns(enter, exit_)
        risk_on = bool(regime.iloc[t]) if pd.notna(regime.iloc[t]) else False
        m = mom.iloc[t].dropna()
        if len(m) < 6:
            t += R; continue
        w_new = pd.Series(0.0, index=coins)
        if risk_on:
            topk = m.sort_values(ascending=False).head(K).index
            filled = [coin for coin in topk if pd.notna(ret_coins.get(coin))]
            w_new[filled] = 1.0 / len(topk)
            in_mkt += 1
        turnover = (w_new - w_prev).abs().sum()
        gross_port = float((w_new * ret_coins.reindex(coins).fillna(0.0)).sum())
        port = max(-1.0, gross_port - cost * turnover)
        bench_ret = float(ret_coins.dropna().mean()) if ret_coins.notna().any() else 0.0
        strat.append(port); bench.append(bench_ret); periods.append(dates[t])
        w_prev = w_new
        t += R
    s = pd.Series(strat, index=periods); b = pd.Series(bench, index=periods)
    frac = in_mkt / max(1, len(strat))
    return s, b, frac


def metrics(r, R):
    if len(r) == 0:
        return dict(cagr=0, sharpe=0, mdd=0)
    eq = (1 + r).cumprod()
    years = len(r) * R / 365.0
    cagr = (float(eq.iloc[-1]) ** (1 / years) - 1) * 100 if years > 0.3 else 0.0
    sharpe = float(r.mean() / r.std() * np.sqrt(365.0 / R)) if r.std() > 0 else 0.0
    mdd = max_drawdown_from_returns(r)
    return dict(cagr=cagr, sharpe=sharpe, mdd=mdd)


def main():
    C, O = load_panels()
    print("=" * 104)
    print(f"跨幣動量 + 市場 regime 過濾 · {C.shape[1]} 幣 · {str(C.index.min())[:10]}~{str(C.index.max())[:10]}")
    print(f"多頭(BTC>N日均)持有 top-K 動量、空頭轉現金；純做多、扣成本 {COST*100:.2f}%/單位換手；對照=全體等權")
    print("=" * 104)

    configs = [(14, 3, 5), (14, 5, 10), (30, 5, 10)]
    regimes = [(0, "無過濾"), (100, "BTC>100日均"), (200, "BTC>200日均")]

    for (L, K, R) in configs:
        print(f"\n── 動量 mom{L} / top{K} / 每{R}天換倉 ──   (市場全期 CAGR ≈ "
              f"{metrics(backtest(C, O, L, K, R, regime_signal(C, 0))[1], R)['cagr']:+.1f}%)")
        print(f"   {'過濾':<12}{'進場時間':>8}{'全期CAGR':>10}{'全期回撤':>9}{'全期Sharpe':>11}"
              f"{'樣本外CAGR':>11}{'樣本外回撤':>11}{'樣本外Sharpe':>13}")
        for (N, rlabel) in regimes:
            s, b, frac = backtest(C, O, L, K, R, regime_signal(C, N))
            k = int(len(s) * 0.6)
            allm = metrics(s, R); oos = metrics(s.iloc[k:], R)
            star = " ★" if (oos["cagr"] > 0 and allm["mdd"] > -45) else ""
            print(f"   {rlabel:<12}{frac*100:>6.0f}%{allm['cagr']:>+9.1f}%{allm['mdd']:>+8.1f}%"
                  f"{allm['sharpe']:>11.2f}{oos['cagr']:>+10.1f}%{oos['mdd']:>+10.1f}%{oos['sharpe']:>12.2f}{star}")

    print("\n" + "=" * 104)
    print("判讀：regime 過濾應讓【回撤大幅縮小】且【絕對 CAGR 轉正】；樣本外 CAGR>0 + 回撤可接受(★) = 較可能真的可用。")


if __name__ == "__main__":
    main()
