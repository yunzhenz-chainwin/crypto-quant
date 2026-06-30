# -*- coding: utf-8 -*-
"""
cross_sectional_sanity.py — 抓 bug 的健全性測試（驗證前面跨幣結果「算得對不對」）

1) 隨機訊號：餵隨機排名，多空 edge 應 ≈ 0（若顯著非 0 → 評估流程在無中生有 = 有 bug）
2) 延遲測試：把動量訊號多延遲 1 天，edge 應仍在（略弱）。若消失 → 原本偷看當天資訊
3) 基準獨立重算：用「等權日報酬 cumprod」另算市場 CAGR，對照回測的 −19%
4) 資料抽查：印幾個幣的起訖價，肉眼確認是真實價格

重跑：python src/cross_sectional_sanity.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from src.cross_sectional import load_panels, fwd_ret, evaluate, stat, SKIP

C, O = load_panels()
H = 10
fwd = fwd_ret(O, H)

print("=" * 80)
print("健全性測試（驗證跨幣結果算得對不對）")
print("=" * 80)

# ── 1) 真實動量 vs 隨機訊號 ──
mom14 = C / C.shift(14) - 1.0
ls, lo, mkt = evaluate(mom14, fwd)
real = stat(ls, H)
print(f"\n[1] 真實 mom14（持有10天）：多空年化 {real['ann']:+.1f}%　命中 {real['hit']:.1f}%　樣本 {real['n']}")

anns, hits = [], []
for seed in range(10):
    rng = np.random.default_rng(seed)
    rand = pd.DataFrame(rng.standard_normal(C.shape), index=C.index, columns=C.columns)
    ls_r, _, _ = evaluate(rand, fwd)
    s = stat(ls_r, H)
    anns.append(s["ann"]); hits.append(s["hit"])
print(f"    隨機訊號（10 個種子）：多空年化 範圍 [{min(anns):+.1f}%, {max(anns):+.1f}%]　平均 {np.mean(anns):+.1f}%")
print(f"                          命中 範圍 [{min(hits):.1f}%, {max(hits):.1f}%]（應 ≈ 50%）")
verdict1 = "✓ 通過：真實動量遠在隨機範圍之外 → 不是 bug 生出來的" if real["ann"] > max(anns) + 5 \
    else "✗ 警告：真實動量沒明顯超出隨機 → 存疑"
print(f"    → {verdict1}")

# ── 2) 延遲測試 ──
mom14_lag = mom14.shift(1)            # 用「昨天的動量」，更晚才行動（更保守，絕不偷看）
ls_l, _, _ = evaluate(mom14_lag, fwd)
lag = stat(ls_l, H)
print(f"\n[2] 延遲測試：mom14 多延遲 1 天 → 多空年化 {lag['ann']:+.1f}%（原 {real['ann']:+.1f}%）")
verdict2 = "✓ 通過：延遲後 edge 仍在（略弱）→ 非偷看當天資訊" if lag["ann"] > real["ann"] * 0.3 and lag["ann"] > 5 \
    else "✗ 警告：延遲後 edge 大幅消失 → 疑似 lookahead"
print(f"    → {verdict2}")

# ── 3) 基準獨立重算 ──
ew_ret = C.pct_change().mean(axis=1).iloc[SKIP:]      # 等權、可用幣的每日平均報酬
ew_eq = (1 + ew_ret).cumprod()
yrs = len(ew_eq) / 365.0
ew_cagr = (float(ew_eq.iloc[-1]) ** (1 / yrs) - 1) * 100
btc = C["BTCUSDT"].dropna()
btc_cagr = ((float(btc.iloc[-1]) / float(btc.iloc[0])) ** (365 / (btc.index[-1] - btc.index[0]).days) - 1) * 100
print(f"\n[3] 基準獨立重算：等權籃子 CAGR {ew_cagr:+.1f}%（回測報的市場 ≈ −19%，應相近）")
print(f"    參考：BTC 買入持有 CAGR {btc_cagr:+.1f}%（同期）")

# ── 4) 資料抽查 ──
print(f"\n[4] 資料抽查（起訖收盤，肉眼確認真實）：")
for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
    s = C[sym].dropna()
    print(f"    {sym:9} {str(s.index[0])[:10]} {s.iloc[0]:>10.2f} → {str(s.index[-1])[:10]} {s.iloc[-1]:>10.2f}")

print("\n" + "=" * 80)
print("總結：[1][2] 通過 = 評估流程沒有無中生有 edge、沒偷看未來；[3][4] 對得上 = 資料與基準正確。")
print("（注意：這是驗『算得對』；至於『策略可不可信』另有 倖存者偏差/單一樣本外窗 等限制，見前述。）")
