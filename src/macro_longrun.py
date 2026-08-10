# -*- coding: utf-8 -*-
"""
macro_longrun.py — 用「2017 起」的加密歷史重跑宏觀預測力檢定（旁路，唯讀）

為什麼要另外跑：
  正式管線的 src/fetch_binance.py 的 DEFAULT_DAYS 1d = 365*5，所以 data/clean
  只有 2021-07 起約 5 年，整段樣本只涵蓋一輪多空、一個升息循環。宏觀因子本來就
  該用「不同利率環境」檢驗，而樣本裡根本沒有第二種環境——這曾是 macro_eval 那個
  t=0.72 最具體、也最可能翻盤的弱點，所以必須實際測掉，而不是留著當藉口。

為什麼不直接改正式管線：
  拉長歷史會讓 prices/indicators/daily_signal 全部重算，所有幣的回測績效數字都會
  跟著變（期間變了）。那是要不要承擔的產品決定，不該為了做一次研究就先動它。
  這支把 K 線抓進 data/raw/（gitignore）自成一份樣本，重用 src/macro_eval 的既有
  函式算同一套統計，正式資料一個位元組都不動。

── 2026-08-10 結論（同 15 幣，只有期間不同）────────────────────────────
  2021-07 起（5 年，191 區段）：順風−逆風 h=5 = +0.81%，HAC t = 0.90
  2017-08 起（8 年，327 區段）：順風−逆風 h=5 = +0.29%，HAC t = 0.32
  樣本量幾乎翻倍、t 值反而從 0.90 掉到 0.32。真有效果的訊號 t 值大致隨 √N 成長，
  這裡反向縮小，是「沒有效果」的典型指紋。
  → 「樣本不夠才測不出來」這條路已經走過並否定：不是資料不夠，是規則本身沒有 edge。
     這也是為什麼宏觀維持背景層、不進 src/scoring.py。

無前視與統計處理完全沿用 src/macro_eval.py（隔日開盤進場、HAC 修正、區段數）。
重跑：python src/macro_longrun.py（首次會抓約 3 千根/幣，之後用快取）
"""
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from src import macro_eval as ME
except ImportError:                      # python src/macro_longrun.py 直接執行時
    import macro_eval as ME

# 這份長樣本只服務研究，放 data/raw（已 gitignore）而不進 data/clean，
# 免得被誤當成正式管線的資料而污染前台與回測。
SCRATCH = ROOT / "data" / "raw" / "macro_longrun_1d"
START_MS = int(datetime(2017, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "LTCUSDT",
           "LINKUSDT", "DOGEUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT", "ATOMUSDT",
           "NEARUSDT", "UNIUSDT", "POLUSDT"]


def fetch_daily(symbol: str) -> pd.DataFrame:
    """Binance 日線全歷史（只取已收盤的 K 棒，與正式管線同一個資料正確性鐵律）。"""
    rows, cursor = [], START_MS
    while True:
        url = (f"https://api.binance.com/api/v3/klines?symbol={symbol}"
               f"&interval=1d&startTime={cursor}&limit=1000")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        batch = json.load(urllib.request.urlopen(req, timeout=30))
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 1000:
            break
        cursor = batch[-1][0] + 1
        time.sleep(0.15)
    if not rows:
        return pd.DataFrame()
    now_ms = int(time.time() * 1000)
    df = pd.DataFrame(rows, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "qav", "trades", "tbb", "tbq", "ignore"])
    df = df[df["close_time"] < now_ms]              # 丟掉尚未收盤的當根
    df["date"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df[["date", "open", "high", "low", "close", "volume"]]


def build_scratch_panels() -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    for sym in SYMBOLS:
        out = SCRATCH / f"{sym}_1d.csv"
        if out.exists():
            continue
        df = fetch_daily(sym)
        if df.empty:
            print(f"  {sym:10s} 無資料")
            continue
        df.to_csv(out, index=False)
        print(f"  {sym:10s} {str(df['date'].min())[:10]} ~ {str(df['date'].max())[:10]}  {len(df)} 根")


def run(label: str, start: str | None) -> dict:
    """跑一次檢定；start 給定則只用該日之後的樣本（用來對照 5 年 vs 8 年）。"""
    macro = ME.load_macro()
    C, O = ME.load_panels()
    if start:
        C, O = C[C.index >= start], O[O.index >= start]
    reg = ME.align_regime(macro, C.index)
    verdicts = reg["verdict"]

    out = {"label": label,
           "period": f"{C.index.min().date()} ~ {C.index.max().date()}",
           "days": int(len(C)), "coins": int(C.shape[1])}
    eps = ME.episodes(verdicts.dropna())
    out["episodes"] = {k: int(v) for k, v in eps.items()}

    for h in (1, 5, 20):
        bk = ME.basket(ME.forward_returns(O, h))
        tbl = ME.regime_table(bk, verdicts, h)
        con = ME.contrast(bk, verdicts, h)
        out[f"h{h}"] = {
            "RISK_ON": (tbl.get("RISK_ON") or {}).get("mean_pct"),
            "RISK_OFF": (tbl.get("RISK_OFF") or {}).get("mean_pct"),
            "diff": con.get("diff_pct"), "t": con.get("t_hac"),
            "n": con.get("n_days"),
        }
    return out


def main() -> None:
    print("抓 2017 起的日線到暫存區（正式資料不動）…")
    build_scratch_panels()

    ME.CLEAN = SCRATCH            # 只換資料來源，統計邏輯完全沿用 src/macro_eval
    long_run = run("2017 起（暫存 8 年樣本）", None)
    same_span = run("2021-07 起（對照：正式管線目前的 5 年樣本）", "2021-07-02")

    for res in (long_run, same_span):
        print("\n" + "=" * 70)
        print(f"  {res['label']}")
        print(f"  {res['period']}  {res['days']} 天 / {res['coins']} 幣")
        print(f"  區段數：{res['episodes']}")
        print(f"  {'持有':<6}{'順風%':>9}{'逆風%':>9}{'差':>9}{'HAC t':>8}{'樣本天':>8}")
        for h in (1, 5, 20):
            r = res[f"h{h}"]
            print(f"  {h:<6}{r['RISK_ON']:>9.2f}{r['RISK_OFF']:>9.2f}"
                  f"{r['diff']:>9.2f}{r['t']:>8.2f}{r['n']:>8}")
    print("\n" + "=" * 70)
    print("  判讀提醒：主檢定仍是 h=5。|t|>2 才算有統計證據；")
    print("  樣本拉長後若仍 <2，就是更確定這套規則測不到 edge，而不是資料不夠。")


if __name__ == "__main__":
    main()
