"""
fetch_binance.py  (多幣 + 長歷史 + 多週期版)
從 Binance 抓多支幣的 K 線（日線 / 小時線），自動分段回補歷史，存成 raw + clean 兩層。

特色：
  - 多幣：一次抓一串幣別
  - 多週期：--interval 1d / 1h（檔名帶週期：BTCUSDT_1h.csv，與 1d 並存）
  - 長歷史：用 startTime 分段回補（突破單次 1000 筆上限）
  - 增量更新：clean CSV 已存在時，只從「最後一根 K 棒」續抓再合併，
    每小時排程只需 1 次請求，不必整段重抓
  - 速率保護：每次請求間 sleep + 收到 429 自動等待重試

用法：
  python fetch_binance.py                                  # 預設清單，日線
  python fetch_binance.py BTCUSDT ETHUSDT                  # 自訂幣別，日線
  python fetch_binance.py --interval 1h BTCUSDT ETHUSDT    # 小時線（預設回補 730 天）
  python fetch_binance.py --interval 1h --days 365 BTCUSDT # 自訂回補天數
  python fetch_binance.py --full BTCUSDT                   # 忽略既有 CSV，整段重抓
"""

import argparse
import json
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

import requests
import pandas as pd

# ── 設定 ──────────────────────────────────────────────
BASE_URL = "https://api.binance.com/api/v3/klines"
LIMIT = 1000                       # Binance 單次上限
SLEEP = 2                          # 每次請求間隔（秒），調大 = 更保守、更不會被擋
SYMBOL_PAUSE = 5                   # 每抓完一支幣，多休息幾秒再抓下一支

# 各週期預設回補天數（1d 抓 5 年；1h 抓 2 年 ≈ 17,500 根）
DEFAULT_DAYS = {"1d": 365 * 5, "1h": 730}

DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",   # 原有五支
    "DOGEUSDT", "LINKUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", # 新增：迷因/預言機/老牌L1
    "ATOMUSDT", "MATICUSDT", "UNIUSDT", "LTCUSDT", "NEARUSDT",# 新增：跨鏈/L2/DeFi/支付/新興L1
]

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
CLEAN_DIR = ROOT / "data" / "clean"

KLINE_COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]


def _get(params: dict) -> list:
    """打一次 API，內建 429 重試。"""
    for attempt in range(5):
        resp = requests.get(BASE_URL, params=params, timeout=15)
        if resp.status_code == 429:                       # 被限流：等一下再試
            wait = int(resp.headers.get("Retry-After", 2))
            print(f"    收到 429，等待 {wait} 秒後重試…")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("連續被限流，請稍後再跑")


def fetch_history(symbol: str, interval: str, start_ms: int) -> list:
    """從 start_ms 開始，一段一段往後抓到最新，回傳合併後的原始資料。"""
    all_rows, cursor = [], start_ms
    while True:
        batch = _get({
            "symbol": symbol, "interval": interval,
            "startTime": cursor, "limit": LIMIT,
        })
        if not batch:
            break
        all_rows.extend(batch)
        last_open = batch[-1][0]
        if len(batch) < LIMIT:                            # 抓完了（最後一批不滿 1000）
            break
        cursor = last_open + 1                            # 下一段從上一批最後一根的下一刻開始
        time.sleep(SLEEP)
    # 只保留「已收盤」的 K 棒：Binance 會把進行中的那一根一起回傳（close_time 在未來），
    # 存進去會讓指標 / 訊號 / AI 吃到半根資料（量與價都不完整），故一律濾掉。
    # 下一輪排程自然會把新收盤的棒補進來。
    now_ms = int(time.time() * 1000)
    return [r for r in all_rows if r[6] <= now_ms]        # r[6] = close_time


def save_raw(symbol: str, interval: str, data: list) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = RAW_DIR / f"{symbol}_{interval}_{stamp}.json"
    path.write_text(json.dumps(data))
    return path


def to_clean(data: list) -> pd.DataFrame:
    df = pd.DataFrame(data, columns=KLINE_COLS)
    df = df[["open_time", "open", "high", "low", "close", "volume"]].copy()
    df["date"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    df = df[["date", "open", "high", "low", "close", "volume"]]
    df = df.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    return df


def clean_path(symbol: str, interval: str) -> Path:
    return CLEAN_DIR / f"{symbol}_{interval}.csv"


def last_saved_ms(symbol: str, interval: str) -> int | None:
    """讀既有 clean CSV 的最後一根 K 棒時間（ms）；沒有檔案回傳 None。"""
    path = clean_path(symbol, interval)
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, parse_dates=["date"])
        if df.empty:
            return None
        return int(df["date"].max().timestamp() * 1000)
    except Exception:
        return None                  # 檔案壞掉就整段重抓

def save_clean(symbol: str, interval: str, df: pd.DataFrame) -> Path:
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    path = clean_path(symbol, interval)
    df.to_csv(path, index=False)
    return path


def merge_with_existing(symbol: str, interval: str, new_df: pd.DataFrame) -> pd.DataFrame:
    """新抓的資料與既有 CSV 合併（同時間以新資料為準），維持升冪。"""
    path = clean_path(symbol, interval)
    if not path.exists():
        return new_df
    old = pd.read_csv(path, parse_dates=["date"])
    merged = pd.concat([old, new_df], ignore_index=True)
    merged = merged.drop_duplicates("date", keep="last").sort_values("date")
    return merged.reset_index(drop=True)


def parse_args():
    ap = argparse.ArgumentParser(description="Fetch Binance klines (multi-symbol, multi-interval)")
    ap.add_argument("symbols", nargs="*", help="交易對，如 BTCUSDT；不給就用預設清單")
    ap.add_argument("--interval", default="1d", choices=["1d", "1h"], help="K 線週期")
    ap.add_argument("--days", type=int, default=None, help="回補天數（預設 1d=1825、1h=730）")
    ap.add_argument("--full", action="store_true", help="忽略既有 CSV，整段重抓")
    return ap.parse_args()


def main():
    args = parse_args()
    interval = args.interval
    symbols = [s.upper() for s in args.symbols] or DEFAULT_SYMBOLS
    days = args.days or DEFAULT_DAYS[interval]
    full_start_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)

    print(f"Target: {', '.join(symbols)}  interval={interval}  ({days}d history)\n")
    for sym in symbols:
        print(f">> {sym} [{interval}]")
        # 增量：已有 CSV 就從最後一根重抓（該根當時可能未收盤，用新值覆蓋）
        last_ms = None if args.full else last_saved_ms(sym, interval)
        start_ms = last_ms if last_ms else full_start_ms
        mode = "增量" if last_ms else "整段"

        data = fetch_history(sym, interval, start_ms)
        if not data:
            print("  (no data, skipping)\n")
            continue
        save_raw(sym, interval, data)
        df = merge_with_existing(sym, interval, to_clean(data))
        save_clean(sym, interval, df)
        print(f"  {mode} +{len(data)} bars → 共 {len(df)} bars  "
              f"{df['date'].min()} ~ {df['date'].max()}\n")
        if sym != symbols[-1]:
            time.sleep(SYMBOL_PAUSE)

    print("Done.")


if __name__ == "__main__":
    main()
