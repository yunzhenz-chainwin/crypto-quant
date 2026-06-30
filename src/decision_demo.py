# -*- coding: utf-8 -*-
"""
decision_demo.py — 用真實資料，把「一個決策日」的每一步攤開來看（唯讀）

成品策略：動量mom30 + BTC>100日均 regime + top5 等權 + 波動度目標30%。
本檔挑幾個真實日期，逐關印出：看大盤 → 動量排名挑幣 → 算投入多少 → 之後實際表現。

重跑：python src/decision_demo.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

CLEAN = ROOT / "data" / "clean"
INTERVAL = "1d"
L, K, R = 30, 5, 10
REGIME_N, VOLWIN, TARGET_VOL, ANN = 100, 20, 0.30, np.sqrt(365.0)


def load_panels():
    closes, opens = {}, {}
    for p in sorted(CLEAN.glob(f"*_{INTERVAL}.csv")):
        sym = p.stem.replace(f"_{INTERVAL}", "")
        df = pd.read_csv(p, parse_dates=["date"]).sort_values("date")
        s = df.set_index("date")
        closes[sym] = s["close"].astype(float); opens[sym] = s["open"].astype(float)
    C = pd.DataFrame(closes).sort_index()
    O = pd.DataFrame(opens).sort_index().reindex(C.index)
    return C, O


def show_day(C, O, t):
    date = str(C.index[t])[:10]
    btc = C["BTCUSDT"]
    ma100 = btc.rolling(REGIME_N).mean().iloc[t]
    btc_px = btc.iloc[t]
    on = btc_px > ma100
    print("\n" + "█" * 70)
    print(f"  決策日：{date}")
    print("█" * 70)

    # 關 1：看大盤 regime
    print(f"\n[關1] 看大盤(regime)：BTC 收盤 {btc_px:,.0f}  vs  100日均 {ma100:,.0f}")
    if not on:
        print(f"       → BTC 在均線【之下】= 空頭 → 🛑 全部抱現金，今天不進場。")
        # 顯示接下來市場跌多少（凸顯避開的傷）
        if t + 1 + R < len(C):
            mret = (O.iloc[t + 1 + R] / O.iloc[t + 1] - 1).mean() * 100
            print(f"       (對照：接下來 10 天市場平均 {mret:+.1f}% —— 抱現金避開了它)")
        return
    print(f"       → BTC 在均線【之上】= 多頭 ✓ 繼續挑幣。")

    # 關 2：動量排名
    mom = (C.iloc[t] / C.iloc[t - L] - 1) * 100
    enter = O.iloc[t + 1] if t + 1 < len(O) else None
    valid = mom.dropna()
    if enter is not None:
        valid = valid[enter.reindex(valid.index).notna() & (enter.reindex(valid.index) > 0)]
    ranked = valid.sort_values(ascending=False)
    topk = list(ranked.head(K).index)
    print(f"\n[關2] 動量排名(過去 {L} 天漲幅)，挑前 {K} 名：")
    print(f"       {'排名':<5}{'幣':<9}{'過去30天':>10}")
    for i, (sym, v) in enumerate(ranked.items(), 1):
        mark = " ← 選" if sym in topk else ""
        print(f"       {i:<5}{sym.replace('USDT',''):<9}{v:>+9.1f}%{mark}")

    # 關 3：波動度目標 → 投入多少
    dret = C.pct_change()
    win = dret[topk].iloc[max(0, t - VOLWIN + 1):t + 1]
    basket_vol = float((win * (1.0 / K)).sum(axis=1).std() * ANN) * 100
    exposure = min(1.0, TARGET_VOL / (basket_vol / 100)) if basket_vol > 0 else 0.0
    per = exposure / K * 100
    print(f"\n[關3] 算投入多少(波動度目標)：")
    print(f"       這 5 幣近期波動 ≈ 年化 {basket_vol:.0f}%；目標 {TARGET_VOL*100:.0f}%")
    print(f"       → 總投入 = min(100%, 30%/{basket_vol:.0f}%) = 【{exposure*100:.0f}%】(其餘 {100-exposure*100:.0f}% 現金)")
    print(f"       → 每個幣部位 = {exposure*100:.0f}% / 5 ≈ {per:.1f}%")

    # 結果：之後 10 天實際表現
    if t + 1 + R < len(C):
        exit_ = O.iloc[t + 1 + R]
        rc = (exit_[topk] / enter[topk] - 1) * 100
        port = float((rc / 100 * (exposure / K)).sum()) * 100
        mret = float((O.iloc[t + 1 + R] / O.iloc[t + 1] - 1).mean()) * 100
        print(f"\n[結果] 進場 open[{str(C.index[t+1])[:10]}] → 出場 open[{str(C.index[t+1+R])[:10]}]（10天）：")
        for sym in topk:
            print(f"       {sym.replace('USDT',''):<8} {rc[sym]:>+7.1f}%")
        print(f"       → 投資組合(含現金、扣權重)淨變化 ≈ {port:+.2f}%   (同期市場 {mret:+.1f}%)")


def main():
    C, O = load_panels()
    print("=" * 70)
    print("真實決策日逐步示範 — mom30 + BTC>100日均 + top5 + 波動目標30%")
    print("=" * 70)

    n = len(C)
    # 1) 最新的一天
    show_day(C, O, n - 1)

    # 2) 最近一個「多頭」決策日(有後續 10 天可看結果)
    btc = C["BTCUSDT"]; ma = btc.rolling(REGIME_N).mean()
    for t in range(n - 1 - (R + 1), 250, -1):
        if btc.iloc[t] > ma.iloc[t]:
            show_day(C, O, t)
            break


if __name__ == "__main__":
    main()
