"""
correlation.py
讀進多支幣的 clean 資料，分析它們彼此的連動關係。
輸出兩張圖到 reports/：
  1. 相關性熱力圖    ：五支幣兩兩的日報酬相關係數
  2. 累積報酬比較圖  ：把每支幣的成長倍數疊在一起比較

關鍵觀念：相關性用『日報酬率』算，不用價格。
  價格會長期一起往上飄，直接算會讓所有幣看起來都高度相關（假象）。
  改用每天的漲跌幅，才能真正看出「是否同方向波動」。

用法：
  python correlation.py                              # 用預設五支幣
  python correlation.py BTCUSDT ETHUSDT              # 自訂

需先安裝：
  python -m pip install matplotlib
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

INTERVAL = "1d"
ROOT = Path(__file__).resolve().parent.parent
CLEAN_DIR = ROOT / "data" / "clean"
REPORT_DIR = ROOT / "reports"

DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]


def load_closes(symbols: list[str]) -> pd.DataFrame:
    """把每支幣的收盤價讀進來，用日期對齊成一張寬表（每支幣一欄）。"""
    series = {}
    for sym in symbols:
        path = CLEAN_DIR / f"{sym}_{INTERVAL}.csv"
        if not path.exists():
            print(f"  跳過 {sym}（找不到 {path.name}）")
            continue
        df = pd.read_csv(path, parse_dates=["date"])
        s = df.set_index("date")["close"]
        s.index = s.index.tz_localize(None)        # 去掉時區，方便對齊
        series[sym.replace("USDT", "")] = s        # 欄名用 BTC、ETH… 比較好看
    if not series:
        sys.exit("沒有任何資料可讀。")
    # 用 inner join 對齊：只保留所有幣都有資料的共同日期
    return pd.DataFrame(series).dropna()


def plot_heatmap(returns: pd.DataFrame) -> Path:
    corr = returns.corr()                          # 兩兩相關係數矩陣（-1 ~ 1）

    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(corr, cmap="RdYlGn", vmin=-1, vmax=1)

    ax.set_xticks(range(len(corr)))
    ax.set_yticks(range(len(corr)))
    ax.set_xticklabels(corr.columns)
    ax.set_yticklabels(corr.index)

    # 每格寫上數字
    for i in range(len(corr)):
        for j in range(len(corr)):
            ax.text(j, i, f"{corr.iloc[i, j]:.2f}",
                    ha="center", va="center", color="black", fontsize=10)

    ax.set_title("Daily Return Correlation", fontsize=13, pad=12)
    fig.colorbar(im, ax=ax, shrink=0.8, label="correlation")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "correlation_heatmap.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out, corr


def plot_cumulative(closes: pd.DataFrame) -> Path:
    # 把每支幣正規化成「從 1 開始的成長倍數」，才能公平比較漲幅
    growth = closes / closes.iloc[0]

    fig, ax = plt.subplots(figsize=(12, 6))
    for col in growth.columns:
        ax.plot(growth.index, growth[col], lw=1.2, label=col)
    ax.axhline(1, color="#999", lw=0.6)            # 1 = 起點，在線上=賺、線下=賠
    ax.set_title("Cumulative Growth (normalized to 1 at start)", fontsize=13)
    ax.set_ylabel("growth multiple (x)")
    ax.legend()
    ax.grid(alpha=0.2)

    out = REPORT_DIR / "cumulative_growth.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out


def main():
    symbols = [s.upper() for s in sys.argv[1:]] or DEFAULT_SYMBOLS
    closes = load_closes(symbols)
    returns = closes.pct_change().dropna()         # 日報酬率 = 每天漲跌幅

    print(f"\n比較幣別：{', '.join(closes.columns)}")
    print(f"共同期間：{closes.index.min().date()} ~ {closes.index.max().date()}"
          f"（{len(closes)} 天）\n")

    heat_out, corr = plot_heatmap(returns)
    cum_out = plot_cumulative(closes)

    # 終端機也印出相關係數矩陣
    print("日報酬相關係數矩陣：")
    print(corr.round(2).to_string())

    # 順手算每支幣的年化波動度（風險高低）
    vol = returns.std() * np.sqrt(365)
    print("\n年化波動度（越高越劇烈）：")
    print((vol * 100).round(1).astype(str).add(" %").to_string())

    print(f"\n圖表已存到：\n  {heat_out}\n  {cum_out}")


if __name__ == "__main__":
    main()