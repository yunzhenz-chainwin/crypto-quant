"""
fetch_binance.py  (多幣 + 長歷史版)
從 Binance 抓多支幣的日線，自動分段回補指定年數的歷史，存成 raw + clean 兩層。

特色：
  - 多幣：一次抓一串幣別
  - 長歷史：用 startTime 分段回補（突破單次 1000 筆上限），自動抓到該幣最早資料為止
  - 速率保護：每次請求間 sleep + 收到 429 自動等待重試

用法：
  python fetch_binance.py                      # 用預設清單與年數
  python fetch_binance.py BTCUSDT ETHUSDT      # 自訂幣別
"""

import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

import requests
import pandas as pd

# ── 設定 ──────────────────────────────────────────────
BASE_URL = "https://api.binance.com/api/v3/klines"
INTERVAL = "1d"
LIMIT = 1000                       # Binance 單次上限
YEARS = 5                          # 要回補幾年
SLEEP = 2                          # 每次請求間隔（秒），調大 = 更保守、更不會被擋
SYMBOL_PAUSE = 5                   # 每抓完一支幣，多休息幾秒再抓下一支

DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

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


def fetch_history(symbol: str, start_ms: int) -> list:
    """從 start_ms 開始，一段一段往後抓到最新，回傳合併後的原始資料。"""
    all_rows, cursor = [], start_ms
    while True:
        batch = _get({
            "symbol": symbol, "interval": INTERVAL,
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
    return all_rows


def save_raw(symbol: str, data: list) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = RAW_DIR / f"{symbol}_{INTERVAL}_{stamp}.json"
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


def save_clean(symbol: str, df: pd.DataFrame) -> Path:
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    path = CLEAN_DIR / f"{symbol}_{INTERVAL}.csv"
    df.to_csv(path, index=False)
    return path


def main():
    symbols = [s.upper() for s in sys.argv[1:]] or DEFAULT_SYMBOLS
    start_ms = int((datetime.now(timezone.utc) - timedelta(days=365 * YEARS)).timestamp() * 1000)

    print(f"目標：{', '.join(symbols)}　回補約 {YEARS} 年\n")
    for sym in symbols:
        print(f"▶ {sym}")
        data = fetch_history(sym, start_ms)
        if not data:
            print(f"  （無資料，跳過——可能該幣別不存在）\n")
            continue
        save_raw(sym, data)
        df = to_clean(data)
        save_clean(sym, df)
        print(f"  共 {len(df)} 根，期間 {df['date'].min().date()} ~ {df['date'].max().date()}\n")
        time.sleep(SYMBOL_PAUSE)

    print("全部完成。")


if __name__ == "__main__":
    main()