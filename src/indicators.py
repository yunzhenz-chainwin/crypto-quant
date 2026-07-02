"""
indicators.py
讀進 data/clean/ 的日線資料，計算三大技術指標，畫成三層圖並存到 reports/。
指標全部只用收盤價、純 pandas 計算（不依賴 pandas-ta，避免相容性問題）：
  - MA20 / MA60 ：簡單移動平均（趨勢）
  - RSI(14)     ：相對強弱（動量，0~100）
  - MACD        ：MACD 線、訊號線、柱狀圖（轉折）

用法：
  python indicators.py                        # 預設 BTCUSDT 日線
  python indicators.py ETHUSDT                # 指定幣別
  python indicators.py BTCUSDT --interval 1h  # 小時線（指標期數同樣以「根」計）
  python indicators.py BTCUSDT --interval 1h --no-plot   # 排程用：只出 CSV 不畫圖

需先安裝繪圖套件：
  python -m pip install matplotlib
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
CLEAN_DIR = ROOT / "data" / "clean"
REPORT_DIR = ROOT / "reports"


def load(symbol: str, interval: str) -> pd.DataFrame:
    path = CLEAN_DIR / f"{symbol}_{interval}.csv"
    if not path.exists():
        sys.exit(f"找不到檔案：{path}（請先用 fetch_binance.py 抓資料）")
    df = pd.read_csv(path, parse_dates=["date"])
    return df.sort_values("date").reset_index(drop=True)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close  = df["close"]
    volume = df["volume"]

    # 1) MA：最近 N 天收盤價的平均
    df["MA20"]  = close.rolling(20).mean()
    df["MA60"]  = close.rolling(60).mean()
    df["MA200"] = close.rolling(200).mean()

    # 2) RSI(14)：用 Wilder 平滑法
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))

    # 3) MACD：快線(EMA12) − 慢線(EMA26)，訊號線是 MACD 的 EMA9
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["MACD"]   = ema12 - ema26
    df["SIGNAL"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["HIST"]   = df["MACD"] - df["SIGNAL"]

    # 4) Bollinger Bands（20 期，±2σ）
    bb_mid         = close.rolling(20).mean()
    bb_std         = close.rolling(20).std(ddof=0)
    df["BB_UPPER"] = bb_mid + 2 * bb_std
    df["BB_LOWER"] = bb_mid - 2 * bb_std

    # 5) 成交量 20 日均量（用於確認訊號強度）
    df["VOL_MA20"] = volume.rolling(20).mean()

    return df


def plot(df: pd.DataFrame, symbol: str, interval: str) -> Path:
    fig, (ax1, ax2, ax3) = plt.subplots(
        3, 1, figsize=(13, 9), sharex=True,
        gridspec_kw={"height_ratios": [3, 1.2, 1.4]},
    )
    fig.suptitle(f"{symbol} {interval} — Technical Indicators", fontsize=14)

    # 上層：價格 + 兩條均線
    ax1.plot(df["date"], df["close"], color="#3a3a3a", lw=1, label="Price")
    ax1.plot(df["date"], df["MA20"], color="#7F77DD", lw=1.2, label="MA20")
    ax1.plot(df["date"], df["MA60"], color="#BA7517", lw=1.2, label="MA60")
    ax1.legend(loc="upper left", fontsize=9)
    ax1.set_ylabel("Price (USDT)")
    ax1.grid(alpha=0.2)

    # 中層：RSI + 超買/超賣線
    ax2.plot(df["date"], df["RSI"], color="#1D9E75", lw=1)
    ax2.axhline(70, color="#D64545", ls="--", lw=0.8, alpha=0.7)
    ax2.axhline(30, color="#3DA35D", ls="--", lw=0.8, alpha=0.7)
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("RSI(14)")
    ax2.text(df["date"].iloc[0], 72, "overbought 70", fontsize=8, color="#D64545")
    ax2.text(df["date"].iloc[0], 22, "oversold 30", fontsize=8, color="#3DA35D")
    ax2.grid(alpha=0.2)

    # 下層：MACD 線、訊號線、柱狀圖
    colors = ["#3DA35D" if v >= 0 else "#D64545" for v in df["HIST"].fillna(0)]
    ax3.bar(df["date"], df["HIST"], color=colors, width=1.0, alpha=0.6)
    ax3.plot(df["date"], df["MACD"], color="#185FA5", lw=1, label="MACD")
    ax3.plot(df["date"], df["SIGNAL"], color="#D85A30", lw=1, ls="--", label="Signal")
    ax3.axhline(0, color="#999", lw=0.6)
    ax3.legend(loc="upper left", fontsize=9)
    ax3.set_ylabel("MACD")
    ax3.grid(alpha=0.2)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"indicators_{symbol}_{interval}.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out


def main():
    ap = argparse.ArgumentParser(description="Compute technical indicators")
    ap.add_argument("symbol", nargs="?", default="BTCUSDT")
    ap.add_argument("--interval", default="1d", choices=["1d", "1h"])
    ap.add_argument("--no-plot", action="store_true", help="只出 CSV，不畫 PNG（小時線排程用）")
    args = ap.parse_args()

    symbol, interval = args.symbol.upper(), args.interval
    df = load(symbol, interval)
    df = add_indicators(df)

    # 存一份含指標的 CSV，方便後續使用
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    csv_out = REPORT_DIR / f"indicators_{symbol}_{interval}.csv"
    df.to_csv(csv_out, index=False)

    png_out = None if args.no_plot else plot(df, symbol, interval)

    # 印出最近幾根的指標數值
    cols = ["date", "close", "MA20", "MA60", "RSI", "MACD", "SIGNAL"]
    print(f"\n{symbol} [{interval}] 最近 5 根指標：")
    print(df[cols].tail().to_string(index=False))
    if png_out:
        print(f"\n圖表已存到：{png_out}")
    print(f"指標數值已存到：{csv_out}")


if __name__ == "__main__":
    main()