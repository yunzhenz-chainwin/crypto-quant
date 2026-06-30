# -*- coding: utf-8 -*-
"""
signal_experiments.py — 訊號改良實驗（唯讀，不改任何資料）

延續 signal_scorecard.py 的發現（現行 6 因子訊號無 forward edge），
這裡並排測試多個「進場規則變體」，用同一把尺評分：

  方法（無偷看未來，與成績單一致）：
    - 變體在第 i 天收盤可知 → 隔天 open[i+1] 進場
    - N 天後 open[i+1+N] 結算報酬
    - 只看「首次出現(onset)」那天進場，緩解訊號持續造成的樣本重疊
    - 基準 = 任一天進場的同期報酬（代表「躺著抱」）
    - 跳過暖身期 SKIP=200（MA200 需 200 天）

  評分：變體的 onset 報酬要「一致地」beat 基準（命中率↑、平均報酬↑），
        且樣本夠多，才算有 edge。beat 不了 → 沒 edge，不上線。

變體：
  baseline    現行 BULL（score≥65）             —— 重現成績單
  A_反向      把現行 BEAR(score≤35) 當買點       —— 反向/抄底測試
  B1_趨勢過濾 BULL 且 站上MA200 且 MA200上彎      —— 只在趨勢盤聽訊號
  B2_不追高   BULL 且 RSI<60 且 布林位置<0.8      —— 濾掉已過熱的追高
  B3_回檔買   站上MA200 且 RSI<45 且 動能轉上     —— 趨勢中買回檔（換進場邏輯）
  D1_極度恐懼 恐懼貪婪 FNG≤20                     —— 純情緒抄底
  D2_BULL恐懼 BULL 且 FNG≤30                     —— 訊號搭極端恐懼

重跑：python src/signal_experiments.py
"""
import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from src.backtest import load_indicators, compute_signals

COINS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT', 'LINKUSDT',
         'ADAUSDT', 'AVAXUSDT', 'DOTUSDT', 'ATOMUSDT', 'MATICUSDT', 'UNIUSDT', 'LTCUSDT', 'NEARUSDT']
SKIP = 200
HORIZONS = [5, 10, 20]
DB_PATH = ROOT / "data" / "app.db"

# 變體顯示順序（baseline 一定排第一，當參考線）
ORDER = ['baseline', 'A_反向', 'B1_趨勢過濾', 'B2_不追高', 'B3_回檔買', 'D1_極度恐懼', 'D2_BULL恐懼']


def load_fng() -> dict:
    """讀恐懼貪婪歷史 date->value（0–100）。"""
    conn = sqlite3.connect(str(DB_PATH))
    d = {row[0]: row[1] for row in conn.execute("SELECT date, value FROM fear_greed")}
    conn.close()
    return d


FNG = load_fng()


def _onset(cond: np.ndarray) -> np.ndarray:
    """cond 布林陣列 → onset（今天 True 且昨天 False）。"""
    out = np.zeros(len(cond), dtype=bool)
    out[1:] = cond[1:] & ~cond[:-1]
    return out


def build_variants(df: pd.DataFrame, sigs) -> dict:
    """回傳 {變體名: cond 布林陣列}；cond[i]=第 i 天收盤可知的『做多狀態』。"""
    n = len(df)

    def col(k):
        return df[k].to_numpy(dtype=float) if k in df.columns else np.full(n, np.nan)

    close = col('close'); rsi = col('RSI'); ma200 = col('MA200'); hist = col('HIST')
    bbu = col('BB_UPPER'); bbl = col('BB_LOWER')
    width = bbu - bbl
    bbpct = np.where(width > 0, (close - bbl) / np.where(width > 0, width, 1), 0.5)

    sig = np.asarray(sigs)
    bull = sig == 'BULL'
    bear = sig == 'BEAR'

    above200 = close > ma200
    ma200_up = np.zeros(n, dtype=bool)
    ma200_up[20:] = ma200[20:] > ma200[:-20]          # MA200 近 20 日上彎
    mom_up = np.zeros(n, dtype=bool)
    mom_up[1:] = hist[1:] > hist[:-1]                  # MACD 動能轉上

    dates = pd.to_datetime(df['date'], utc=True, errors='coerce').dt.strftime('%Y-%m-%d').to_numpy()
    fng = np.array([FNG.get(d, np.nan) for d in dates], dtype=float)

    return {
        'baseline':    bull,
        'A_反向':      bear,
        'B1_趨勢過濾': bull & above200 & ma200_up,
        'B2_不追高':   bull & (rsi < 60) & (bbpct < 0.8),
        'B3_回檔買':   above200 & (rsi < 45) & mom_up,
        'D1_極度恐懼': fng <= 20,
        'D2_BULL恐懼': bull & (fng <= 30),
    }


def analyze_coin(sym: str, pool: dict):
    """把單幣各變體的 onset 報酬與基準報酬累加進 pool。"""
    df = load_indicators(sym)
    sigs = compute_signals(df)
    opens = df['open'].to_numpy(dtype=float)
    n = len(df)
    variants = build_variants(df, sigs)
    onsets = {k: _onset(v) for k, v in variants.items()}

    for N in HORIZONS:
        for i in range(SKIP, n - 1 - N):
            entry, exitp = opens[i + 1], opens[i + 1 + N]
            if not (entry > 0 and exitp > 0):
                continue
            r = exitp / entry - 1.0
            pool[N]['base'].append(r)
            for k in variants:
                if onsets[k][i]:
                    pool[N][k].append(r)


def main():
    pool = {N: {'base': []} for N in HORIZONS}
    for N in HORIZONS:
        for k in ORDER:
            pool[N][k] = []
    for c in COINS:
        analyze_coin(c, pool)

    pct = lambda x: f'{100 * x:5.1f}%'
    pp = lambda x: f'{100 * x:+4.1f}pp'
    rp = lambda x: f'{100 * x:+5.2f}%'

    print('=' * 92)
    print('訊號改良實驗 — 15 幣彙總（onset 進場，N 天後 open 結算；基準=任一天進場）')
    print('=' * 92)

    best = {}
    for N in HORIZONS:
        base = np.array(pool[N]['base'])
        base_up, base_avg = (base > 0).mean(), base.mean()
        print(f'\n── 持有 {N} 天 ──  基準: 上漲率 {pct(base_up)} · 平均 {rp(base_avg)} · 樣本 {len(base)}')
        print(f'  {"變體":<14}{"樣本":>6}{"命中率":>8}{"vs基準":>9}{"平均報酬":>10}{"vs基準":>9}   評語')
        rows = []
        for k in ORDER:
            arr = np.array(pool[N][k])
            if len(arr) == 0:
                print(f'  {k:<14}{"0":>6}   （無樣本）')
                continue
            hit = (arr > 0).mean()
            avg = arr.mean()
            edge = avg - base_avg                       # 以「平均報酬 vs 基準」為主要 edge 指標
            rows.append((k, len(arr), hit, avg, edge))
            note = ''
            if k != 'baseline':
                if len(arr) < 80:
                    note = '樣本太少，僅參考'
                elif edge > 0.005 and hit - base_up > 0.01:
                    note = '★ 有正向 edge'
                elif edge > 0:
                    note = '略優於基準'
                else:
                    note = '無 edge'
            print(f'  {k:<14}{len(arr):>6}{pct(hit):>8}{pp(hit - base_up):>9}'
                  f'{rp(avg):>10}{pp(edge):>9}   {note}')
        # 紀錄此 horizon 最佳（排除 baseline、樣本>=80）
        cand = [r for r in rows if r[0] != 'baseline' and r[1] >= 80]
        if cand:
            best[N] = max(cand, key=lambda r: r[4])

    print('\n' + '=' * 92)
    print('小結（各持有期 edge 最佳的變體，樣本≥80）')
    print('=' * 92)
    for N in HORIZONS:
        if N in best:
            k, nn, hit, avg, edge = best[N]
            verdict = '★ 值得深入' if edge > 0.005 else ('方向可參考' if edge > 0 else '仍無 edge')
            print(f'  持有 {N:>2} 天：{k:<14} 樣本 {nn:>4}  平均報酬 vs 基準 {pp(edge)}  → {verdict}')
        else:
            print(f'  持有 {N:>2} 天：（無足夠樣本的變體）')
    print('\n註：edge = 變體平均報酬 − 基準平均報酬。要「跨持有期一致為正、且樣本夠」才算數；')
    print('    過濾型變體樣本會變少（onset 變稀），樣本<80 僅供參考。')


if __name__ == '__main__':
    main()
