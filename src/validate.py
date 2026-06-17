"""
validate.py
讀進 data/clean/ 的日線 CSV，自動檢查資料是否乾淨。
檢查五件事：缺天、重複、OHLC 邏輯、時間順序、空值。
跑完印出摘要，並把報告存到 reports/。

用法：
  python validate.py                 # 預設驗證 BTCUSDT
  python validate.py ETHUSDT         # 指定幣別
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

INTERVAL = "1d"
ROOT = Path(__file__).resolve().parent.parent
CLEAN_DIR = ROOT / "data" / "clean"
REPORT_DIR = ROOT / "reports"


def load(symbol: str) -> pd.DataFrame:
    path = CLEAN_DIR / f"{symbol}_{INTERVAL}.csv"
    if not path.exists():
        sys.exit(f"找不到檔案：{path}（請先用 fetch_binance.py 抓資料）")
    df = pd.read_csv(path, parse_dates=["date"])
    return df.sort_values("date").reset_index(drop=True)


def check(df: pd.DataFrame) -> list[str]:
    """跑所有檢查，回傳一份訊息清單（每行一個檢查結果）。"""
    lines = []

    # 1) 空值
    n_null = int(df.isna().sum().sum())
    lines.append(f"[{'PASS' if n_null == 0 else 'FAIL'}] 空值：共 {n_null} 格")

    # 2) 重複日期
    dup = df["date"].duplicated().sum()
    lines.append(f"[{'PASS' if dup == 0 else 'FAIL'}] 重複日期：{dup} 筆")

    # 3) 時間是否嚴格遞增
    mono = df["date"].is_monotonic_increasing and dup == 0
    lines.append(f"[{'PASS' if mono else 'FAIL'}] 時間嚴格遞增：{mono}")

    # 4) 缺天（日線：相鄰日期應差 1 天）
    gaps = df["date"].diff().dt.days.dropna()
    missing = gaps[gaps > 1]
    n_missing_days = int((missing - 1).sum()) if len(missing) else 0
    lines.append(
        f"[{'PASS' if n_missing_days == 0 else 'WARN'}] "
        f"缺天：{len(missing)} 個斷點、共缺約 {n_missing_days} 天"
    )
    if len(missing):
        for idx in missing.index[:5]:                      # 只列前 5 個斷點
            prev, curr = df.loc[idx - 1, "date"], df.loc[idx, "date"]
            lines.append(f"        斷點：{prev.date()} → {curr.date()}")

    # 5) OHLC 邏輯
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    bad_hl = (h < l).sum()                                 # 最高 < 最低
    bad_h = ((h < o) | (h < c)).sum()                      # 最高沒涵蓋開/收
    bad_l = ((l > o) | (l > c)).sum()                      # 最低沒涵蓋開/收
    nonpos = ((df[["open", "high", "low", "close"]] <= 0).sum().sum())
    ohlc_ok = (bad_hl + bad_h + bad_l + nonpos) == 0
    lines.append(f"[{'PASS' if ohlc_ok else 'FAIL'}] OHLC 邏輯：")
    lines.append(f"        high<low：{bad_hl}　high未涵蓋開/收：{bad_h}")
    lines.append(f"        low未涵蓋開/收：{bad_l}　非正值：{nonpos}")

    return lines


def main():
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "BTCUSDT"
    df = load(symbol)

    header = [
        f"資料驗證報告 — {symbol} {INTERVAL}",
        f"產生時間：{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
        f"資料筆數：{len(df)}　期間：{df['date'].min().date()} ~ {df['date'].max().date()}",
        "-" * 48,
    ]
    body = check(df)
    report = "\n".join(header + body)

    print("\n" + report + "\n")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"validation_{symbol}_{INTERVAL}.txt"
    out.write_text(report, encoding="utf-8")
    print(f"報告已存到：{out}")


if __name__ == "__main__":
    main()