# -*- coding: utf-8 -*-
"""
momentum_signal.py — 防禦型跨幣動量「正式訊號服務」（供後台即時呼叫）

把研究驗證過的成品策略，變成平台可以每天呼叫的服務：
  策略 = 動量 mom30 + BTC>100日均 regime + top5 等權 + 波動度目標 30%

提供：
  today_signal()      今日該怎麼做（抱現金 / 持有哪幾幣、各幾 %）
  strategy_metrics()  策略績效（全期 + 樣本外 + 對照市場）
  cached_strategy()   兩者合一、加快取（鍵=資料 mtime）

無偷看未來：訊號用「截至今天收盤」的資料算。
※ 績效為回測、偏樂觀、未經實盤，僅供參考，非績效承諾。
"""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CLEAN = ROOT / "data" / "clean"
INTERVAL = "1d"
L, K, R = 30, 5, 10           # 動量回看 / 持有幾幣 / 換倉天數
REGIME_N, VOLWIN = 100, 20    # regime 均線 / 波動估計窗
TARGET_VOL, COST = 0.30, 0.0015
ANN = np.sqrt(365.0)
SKIP = 200


def load_panels():
    closes, opens = {}, {}
    for p in sorted(CLEAN.glob(f"*_{INTERVAL}.csv")):
        sym = p.stem.replace(f"_{INTERVAL}", "")
        df = pd.read_csv(p, parse_dates=["date"]).sort_values("date")
        s = df.set_index("date")
        closes[sym] = s["close"].astype(float); opens[sym] = s["open"].astype(float)
    C = pd.DataFrame(closes).sort_index()
    # 對齊尾端:某幣可能比別人多抓一天（例如剛換上、已抓到今天的 POL），會讓最後一列
    # 只有它有值、其他幣含 BTC 為 NaN → regime 均線變 NaN。以 BTC 最後有效日截斷。
    last = C["BTCUSDT"].last_valid_index() if "BTCUSDT" in C.columns else None
    if last is not None:
        C = C.loc[:last]
    O = pd.DataFrame(opens).sort_index().reindex(C.index)
    return C, O


def today_signal(C, O):
    """用截至最後一天收盤的資料，算出「今天該怎麼做」。"""
    t = len(C) - 1
    btc = C["BTCUSDT"]; ma = btc.rolling(REGIME_N).mean()
    date = str(C.index[t])[:10]
    btc_px, ma_px = float(btc.iloc[t]), float(ma.iloc[t]) if pd.notna(ma.iloc[t]) else None
    on = (ma_px is not None) and (btc_px > ma_px)

    if not on:
        reason = (f"BTC {btc_px:,.0f} < 100日均 {ma_px:,.0f}（空頭）" if ma_px is not None
                  else f"BTC {btc_px:,.0f}（100日均資料不足，保守抱現金）")
        return {"date": date, "regime": "cash",
                "regime_reason": reason,
                "exposure_pct": 0, "cash_pct": 100, "picks": [],
                "note": "空頭 → 建議抱現金、不進場"}

    mom = (C.iloc[t] / C.iloc[t - L] - 1) * 100
    ranked = mom.dropna().sort_values(ascending=False)
    topk = list(ranked.head(K).index)
    dret = C.pct_change()
    win = dret[topk].iloc[max(0, t - VOLWIN + 1):t + 1]
    bvol = float((win * (1.0 / K)).sum(axis=1).std() * ANN)
    exposure = min(1.0, TARGET_VOL / bvol) if bvol > 0 else 0.0
    picks = [{"symbol": s.replace("USDT", ""),
              "momentum": round(float(ranked[s]), 1),
              "weight": round(exposure / K * 100, 1)} for s in topk]
    return {"date": date, "regime": "invested",
            "regime_reason": f"BTC {btc_px:,.0f} > 100日均 {ma_px:,.0f}（多頭）",
            "exposure_pct": round(exposure * 100), "cash_pct": round(100 - exposure * 100),
            "picks": picks,
            "note": f"多頭 → 投入約 {round(exposure*100)}%（其餘現金），持有以下 {K} 幣"}


def _backtest(C, O):
    mom = C / C.shift(L) - 1.0
    dret = C.pct_change()
    btc = C["BTCUSDT"]; regime = btc > btc.rolling(REGIME_N).mean()
    n = len(C); coins = list(C.columns)
    w_prev = pd.Series(0.0, index=coins)
    strat, bench, periods = [], [], []
    t = SKIP
    while t + 1 + R < n:
        enter = O.iloc[t + 1]; exit_ = O.iloc[t + 1 + R]
        valid = enter.notna() & exit_.notna() & (enter > 0)
        ret_coins = exit_ / enter - 1.0
        bench_ret = float(ret_coins[valid[valid].index].mean()) if valid.any() else 0.0
        w_new = pd.Series(0.0, index=coins); exposure = 0.0
        on = bool(regime.iloc[t]) if pd.notna(regime.iloc[t]) else False
        m = mom.iloc[t].dropna(); m = m[m.index.isin(valid[valid].index)]
        if on and len(m) >= 6:
            topk = list(m.sort_values(ascending=False).head(K).index)
            win = dret[topk].iloc[max(0, t - VOLWIN + 1):t + 1]
            pv = float((win * (1.0 / K)).sum(axis=1).std() * ANN)
            exposure = min(1.0, TARGET_VOL / pv) if pv > 0 else 0.0
            for c in topk:
                w_new[c] = exposure / K
        turnover = (w_new - w_prev).abs().sum()
        port = float((w_new * ret_coins.reindex(coins).fillna(0)).sum()) - COST * turnover
        strat.append(port); bench.append(bench_ret); periods.append(C.index[t])
        w_prev = w_new; t += R
    return pd.Series(strat, index=periods), pd.Series(bench, index=periods)


def _perf(r):
    if len(r) == 0:
        return {"cagr": 0, "mdd": 0, "sharpe": 0}
    eq = (1 + r).cumprod(); yrs = len(r) * R / 365.0
    cagr = (float(eq.iloc[-1]) ** (1 / yrs) - 1) * 100 if yrs > 0.3 else 0.0
    mdd = float(((eq - eq.cummax()) / eq.cummax()).min()) * 100
    sharpe = float(r.mean() / r.std() * np.sqrt(365.0 / R)) if r.std() > 0 else 0.0
    return {"cagr": cagr, "mdd": mdd, "sharpe": sharpe}


def strategy_metrics(C, O):
    strat, bench = _backtest(C, O)
    k = int(len(strat) * 0.6)
    full, oos, mkt = _perf(strat), _perf(strat.iloc[k:]), _perf(bench)
    return {"as_of": str(C.index[-1])[:10],
            "cagr": round(full["cagr"], 1), "mdd": round(full["mdd"], 1), "sharpe": round(full["sharpe"], 2),
            "oos_cagr": round(oos["cagr"], 1), "oos_mdd": round(oos["mdd"], 1), "oos_sharpe": round(oos["sharpe"], 2),
            "market_cagr": round(mkt["cagr"], 1)}


_CACHE: dict = {}


def _version():
    return max((p.stat().st_mtime for p in CLEAN.glob(f"*_{INTERVAL}.csv")), default=0.0)


def cached_strategy():
    v = _version()
    if _CACHE.get("ver") != v:
        C, O = load_panels()
        _CACHE["ver"] = v
        _CACHE["data"] = {"strategy": "防禦型跨幣動量（mom30 + BTC>100日均 + top5 + 波動目標30%）",
                          "today": today_signal(C, O), "perf": strategy_metrics(C, O)}
    return _CACHE["data"]


if __name__ == "__main__":
    import json
    print(json.dumps(cached_strategy(), ensure_ascii=False, indent=2))
