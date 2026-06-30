# -*- coding: utf-8 -*-
"""
cross_sectional.py — 橫斷面（跨幣比較）找 edge 的「全方法掃描」（唯讀，不改資料）

單一幣看自己的技術指標已證實無 forward edge（見 docs/訊號改良實驗.md）。
這裡換維度：每天把 15 幣「互相比較、排名」，做多排名前段 / 放空後段，
測各種跨幣訊號有沒有預測力。

方法（無偷看未來）：
  - 訊號在第 t 天「收盤」算出（只用到 t 為止的資料）
  - 隔天 open[t+1] 進場、N 天後 open[t+1+N] 出場
  - 每天依訊號排名：前 1/3 做多、後 1/3 放空
  - 衡量：
      L-S   = 多方平均報酬 − 空方平均報酬（多空價差，最能看「排名有沒有資訊」）
      L-Mkt = 多方平均報酬 − 全體平均（純做多超額，較實際；不必放空）
  - 對照基準：全體等權（= 市場）的同期報酬

測試的跨幣訊號：
  動量 mom_L      = 過去 L 天報酬（強者恆強）   L = 7/14/30/60/90
  反轉 rev_L      = −過去 L 天報酬（弱者反彈）   L = 3/7
  低波動 lowvol   = −過去 30 天報酬波動度
  乖離 distMA20   = −(收盤/MA20 − 1)（離均線最遠者反彈）
  相對BTC rsBTC_L = 過去 L 天報酬 − BTC 同期報酬

注意：以下為「毛報酬」（未扣成本）。橫斷面每日換倉的成本不低；
若毛報酬有 edge，再做「低換手 / 扣成本」版驗證是否淨賺。

重跑：python src/cross_sectional.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

CLEAN = ROOT / "data" / "clean"
INTERVAL = "1d"
SKIP = 200          # 暖身（與其他實驗一致）
QUANTILE = 1 / 3    # 前/後 1/3 做多/放空
MIN_COINS = 6       # 當天有效幣數不足就跳過


def load_panels():
    closes, opens = {}, {}
    for p in sorted(CLEAN.glob(f"*_{INTERVAL}.csv")):
        sym = p.stem.replace(f"_{INTERVAL}", "")
        df = pd.read_csv(p, parse_dates=["date"]).sort_values("date")
        s = df.set_index("date")
        closes[sym] = s["close"].astype(float)
        opens[sym] = s["open"].astype(float)
    C = pd.DataFrame(closes).sort_index()
    O = pd.DataFrame(opens).sort_index()
    O = O.reindex(C.index)
    return C, O


def fwd_ret(O, H):
    """第 t 天進場 open[t+1] → 出場 open[t+1+H] 的報酬，index 對齊 t。"""
    enter = O.shift(-1)
    exit_ = O.shift(-(1 + H))
    return exit_ / enter - 1.0


def evaluate(signal, fwd, q=QUANTILE):
    """回傳 (long_short series, long_excess series, market series)。"""
    valid = signal.notna() & fwd.notna()
    sig = signal.where(valid)
    fw = fwd.where(valid)
    ncoins = valid.sum(axis=1)
    ranks = sig.rank(axis=1, pct=True)
    longm = ranks >= (1 - q)
    shortm = ranks <= q
    long_ret = fw.where(longm).mean(axis=1)
    short_ret = fw.where(shortm).mean(axis=1)
    market = fw.where(valid).mean(axis=1)
    ok = ncoins >= MIN_COINS
    ls = (long_ret - short_ret)[ok].iloc[SKIP:].dropna()
    lo = (long_ret - market)[ok].iloc[SKIP:].dropna()
    mkt = market[ok].iloc[SKIP:].dropna()
    return ls, lo, mkt


def stat(series, H):
    n = len(series)
    if n == 0:
        return dict(n=0, mean=0, hit=0, ann=0)
    m = float(series.mean()) * 100
    hit = float((series > 0).mean()) * 100
    ann = m * (365.0 / H)                      # 粗估毛年化（重疊取樣）
    return dict(n=n, mean=m, hit=hit, ann=ann)


def build_signals(C):
    rets = lambda L: C / C.shift(L) - 1.0
    vol30 = (C.pct_change().rolling(30).std())
    # MA20 乖離
    ma20 = C.rolling(20).mean()
    dist = -(C / ma20 - 1.0)
    btc = "BTCUSDT"
    sig = {}
    for L in (7, 14, 30, 60, 90):
        sig[(f"動量 mom_{L}", L)] = rets(L)
    for L in (3, 7):
        sig[(f"反轉 rev_{L}", L)] = -rets(L)
    sig[("低波動 lowvol30", 30)] = -vol30
    sig[("乖離 distMA20", 20)] = dist
    if btc in C.columns:
        for L in (14, 30):
            sig[(f"相對BTC rs_{L}", L)] = rets(L).sub(rets(L)[btc], axis=0)
    return sig


def main():
    C, O = load_panels()
    print("=" * 96)
    print(f"橫斷面找 edge 全掃描 — {C.shape[1]} 幣 · {str(C.index.min())[:10]}~{str(C.index.max())[:10]}")
    print("方法：每天排名，多前1/3、空後1/3；隔日 open 進場、N 天後出場；對照=全體等權")
    print("（毛報酬，未扣成本）")
    print("=" * 96)

    signals = build_signals(C)
    HOLDS = [5, 10, 20]
    rows = []
    for (name, _L), sigpanel in signals.items():
        for H in HOLDS:
            fwd = fwd_ret(O, H)
            ls, lo, mkt = evaluate(sigpanel, fwd)
            s_ls, s_lo, s_mkt = stat(ls, H), stat(lo, H), stat(mkt, H)
            rows.append({
                "name": name, "H": H,
                "ls_mean": s_ls["mean"], "ls_hit": s_ls["hit"], "ls_ann": s_ls["ann"],
                "lo_mean": s_lo["mean"], "lo_ann": s_lo["ann"],
                "mkt_ann": s_mkt["ann"], "n": s_ls["n"],
            })

    rows.sort(key=lambda r: r["ls_ann"], reverse=True)

    print(f"\n{'跨幣訊號':<16}{'持有':>4}{'多空/次':>9}{'命中':>7}{'多空年化':>10}{'純多超額/次':>12}"
          f"{'多超額年化':>11}{'市場年化':>10}{'樣本':>7}")
    print("-" * 96)
    for r in rows:
        flag = " ★" if (r["ls_ann"] > 5 and r["ls_hit"] > 52 and r["n"] > 300) else ""
        print(f"{r['name']:<16}{r['H']:>3}天{r['ls_mean']:>+8.2f}%{r['ls_hit']:>6.1f}%"
              f"{r['ls_ann']:>+9.1f}%{r['lo_mean']:>+11.2f}%{r['lo_ann']:>+10.1f}%"
              f"{r['mkt_ann']:>+9.1f}%{r['n']:>7}{flag}")

    print("\n" + "=" * 96)
    print("判讀")
    print("=" * 96)
    best = rows[0]
    cand = [r for r in rows if r["ls_ann"] > 5 and r["ls_hit"] > 52 and r["n"] > 300]
    if cand:
        print(f"  最佳：{best['name']} 持有{best['H']}天 → 多空年化 {best['ls_ann']:+.1f}%、命中 {best['ls_hit']:.1f}%")
        print(f"  有 {len(cand)} 個變體看似有正向多空 edge（★）→ 值得做『扣成本 / 低換手』版進一步驗證。")
    else:
        print(f"  最佳僅 {best['name']} 持有{best['H']}天，多空年化 {best['ls_ann']:+.1f}% → 無明顯穩定 edge。")
    print("  註：以上為毛報酬、重疊取樣的粗估年化；多空需放空、每日換倉成本高，")
    print("      『純多超額』較實際。要當真，需再跑非重疊 + 扣成本版，並看 out-of-sample。")


if __name__ == "__main__":
    main()
