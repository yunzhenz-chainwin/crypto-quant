# -*- coding: utf-8 -*-
"""
signal_scorecard.py — 訊號「成績單」分析(唯讀,不改任何資料)

問題:目前的 6 因子訊號到底有沒有「預測力」?
做法(無偷看未來):
  - 每次訊號『首次出現』(onset)那天 i,訊號於收盤可知 → 隔天 open[i+1] 進場
  - N 天後 open[i+1+N] 結算報酬
  - 偏多算「之後上漲」為命中;偏空算「之後下跌」為命中
  - 對照基準 = 任一天進場的同期報酬(代表「躺著抱」)
  - 跳過暖身期 SKIP=200(MA200 需 200 天)

重跑:  python src/signal_scorecard.py

※ 結論與當時數據見 docs/訊號研究記錄.md（原 訊號成績單分析 已併入）。改了訊號邏輯後重跑此檔,即可對照 edge 變化。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from src.backtest import load_indicators, compute_signals

COINS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT', 'LINKUSDT',
         'ADAUSDT', 'AVAXUSDT', 'DOTUSDT', 'ATOMUSDT', 'MATICUSDT', 'UNIUSDT', 'LTCUSDT', 'NEARUSDT']
SKIP = 200
HORIZONS = [5, 10, 20]


def analyze(symbol):
    df = load_indicators(symbol)
    sigs = compute_signals(df)
    opens = df['open'].to_numpy(dtype=float)
    n = len(df)
    res = {}
    for N in HORIZONS:
        bull, bear, base = [], [], []
        for i in range(SKIP, n - 1 - N):
            entry, exitp = opens[i + 1], opens[i + 1 + N]
            if not (entry > 0 and exitp > 0):
                continue
            r = exitp / entry - 1.0
            base.append(r)
            if sigs[i] == 'BULL' and sigs[i - 1] != 'BULL':
                bull.append(r)
            elif sigs[i] == 'BEAR' and sigs[i - 1] != 'BEAR':
                bear.append(r)
        res[N] = (np.array(bull), np.array(bear), np.array(base))
    return res


def main():
    pool = {N: ([], [], []) for N in HORIZONS}
    percoin = {}
    for c in COINS:
        r = analyze(c)
        percoin[c] = r
        for N in HORIZONS:
            for k in range(3):
                pool[N][k].extend(r[N][k].tolist())

    pct = lambda x: f'{100 * x:5.1f}%'
    pp = lambda x: f'{100 * x:+4.1f}pp'
    rp = lambda x: f'{100 * x:+5.2f}%'

    print('=' * 78)
    print('訊號成績單 — 15 幣彙總(onset 進場,N 天後開盤結算;基準=任一天進場)')
    print('=' * 78)
    for N in HORIZONS:
        bull, bear, base = (np.array(pool[N][k]) for k in range(3))
        base_up, base_avg = (base > 0).mean(), base.mean()
        print(f'\n── 持有 {N} 天 ──  (基準: 上漲率 {pct(base_up)}, 平均 {rp(base_avg)})')
        if len(bull):
            h = (bull > 0).mean()
            print(f'  偏多  樣本 {len(bull):4d}   命中率 {pct(h)}  (vs基準 {pp(h - base_up)})   '
                  f'平均報酬 {rp(bull.mean())}  (vs基準 {pp(bull.mean() - base_avg)})')
        if len(bear):
            h = (bear < 0).mean()
            print(f'  偏空  樣本 {len(bear):4d}   命中率 {pct(h)}  (vs基準 {pp(h - (1 - base_up))})   '
                  f'平均報酬 {rp(bear.mean())}  (vs基準 {pp(bear.mean() - base_avg)})')

    print('\n' + '=' * 78)
    print('各幣明細(持有 10 天)')
    print('=' * 78)
    print(f'{"幣":8}{"偏多N":>6}{"命中":>7}{"vs基準":>8}{"平均":>8}   {"偏空N":>6}{"命中":>7}{"平均":>8}')
    N = 10
    for c in COINS:
        bull, bear, base = percoin[c][N]
        base_up = (base > 0).mean()
        bl = (f'{len(bull):6d}{pct((bull > 0).mean()):>7}{pp((bull > 0).mean() - base_up):>8}{rp(bull.mean()):>8}'
              if len(bull) else f'{0:6d}{"-":>7}{"-":>8}{"-":>8}')
        be = (f'{len(bear):6d}{pct((bear < 0).mean()):>7}{rp(bear.mean()):>8}'
              if len(bear) else f'{0:6d}{"-":>7}{"-":>8}')
        print(f'{c.replace("USDT", ""):8}{bl}   {be}')


if __name__ == '__main__':
    main()
