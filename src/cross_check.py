"""
cross_check.py
把 Binance 抓下來的資料，拿去跟「獨立來源」CoinGecko 比對，
確認抓的價格跟真實市場一致。這檢查的是 validate.py 測不到的東西：跨來源一致性。

== 重要觀念（請務必讀） ==
  1. 這支程式『不該被無條件相信』。跑完請『親自』去 coingecko.com 抽查幾天，
     對得上才代表程式邏輯沒問題。程式只是幫你省下逐筆核對的力氣——
     真相的錨點握在你手上，不是握在這支程式或 Claude 手上。
  2. Binance 與 CoinGecko 是兩個獨立來源、計價方式也不同（單一交易所 vs 跨所均價），
     本來就會有微小差異（通常 <1%）。我們要抓的是『差很大』的異常
     （抓錯幣、單位錯、日期錯位），不是要求兩者一模一樣。

== 為什麼比 open、不比 close ==
  CoinGecko 的每日資料點時間戳是當天 00:00 UTC，
  剛好等於 Binance 當天 K 線的『開盤』時刻（open_time 也是 00:00 UTC）。
  所以拿 Binance open ←→ CoinGecko price 同一天比，對齊最準。
  （Binance 的 close 是當天 23:59 UTC，跟 CoinGecko 的 00:00 差了快一天，
    硬比反而會多出系統性誤差，看起來像錯、其實不是。）

== 涵蓋範圍 ==
  CoinGecko 免費方案只給約 1 年日線，所以這支只驗證『最近約一年』。
  搭配 validate.py（全 5 年內部一致）＋ 你手動核對歷史大事件，覆蓋就完整了。

用法：
  python cross_check.py                 # 預設 BTCUSDT
  python cross_check.py ETHUSDT
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

import requests
import pandas as pd

INTERVAL = "1d"
DAYS = 360                 # 跟 CoinGecko 要幾天（免費上限約 365）
WARN_PCT = 2.0             # 差異超過幾 % 就標出來人工查
ROOT = Path(__file__).resolve().parent.parent
CLEAN_DIR = ROOT / "data" / "clean"
REPORT_DIR = ROOT / "reports"

# Binance 幣別代號 → CoinGecko 的 coin id（要加別的幣就在這裡補）
SYMBOL_TO_ID = {
    "BTCUSDT": "bitcoin",
    "ETHUSDT": "ethereum",
    "SOLUSDT": "solana",
    "BNBUSDT": "binancecoin",
    "XRPUSDT": "ripple",
}

CG_URL = "https://api.coingecko.com/api/v3/coins/{id}/market_chart"


def load_binance(symbol: str) -> pd.DataFrame:
    path = CLEAN_DIR / f"{symbol}_{INTERVAL}.csv"
    if not path.exists():
        sys.exit(f"找不到檔案：{path}（請先用 fetch_binance.py 抓資料）")
    df = pd.read_csv(path)
    df["d"] = pd.to_datetime(df["date"], utc=True).dt.date     # 取 UTC 日期當對齊鍵
    return df


def fetch_coingecko(coin_id: str) -> dict:
    """從 CoinGecko 抓每日價格，回傳 {日期: 價格}。"""
    # 免費方案不要帶 interval=daily（付費專屬）；days>90 會自動給日線，留空即可。
    params = {"vs_currency": "usd", "days": DAYS}
    resp = requests.get(CG_URL.format(id=coin_id), params=params, timeout=20)
    if resp.status_code == 429:
        sys.exit("CoinGecko 回應 429（太頻繁），請等一兩分鐘再跑。")
    if resp.status_code != 200:
        sys.exit(f"CoinGecko 回應 {resp.status_code}；若持續失敗，"
                 f"可到 coingecko.com 申請免費 Demo API key 再試。")

    prices = resp.json().get("prices", [])
    out = {}
    for ts_ms, price in prices:
        d = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date()
        if d not in out:                  # 每天只保留第一個點（=當天 00:00 那筆）
            out[d] = price
    return out


def compare(bdf: pd.DataFrame, cg: dict) -> pd.DataFrame:
    rows = []
    for _, r in bdf.iterrows():
        d = r["d"]
        if d in cg:
            b = float(r["open"])          # 用 open 對齊 CoinGecko 的 00:00 價
            c = float(cg[d])
            diff = abs(b - c) / c * 100 if c else float("nan")
            rows.append({"date": d, "binance_open": b, "coingecko": c, "diff_%": diff})
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def main():
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "BTCUSDT"
    if symbol not in SYMBOL_TO_ID:
        sys.exit(f"未知幣別 {symbol}，請在 SYMBOL_TO_ID 補上對應的 CoinGecko id。")

    bdf = load_binance(symbol)
    cg = fetch_coingecko(SYMBOL_TO_ID[symbol])
    cmp = compare(bdf, cg)
    if cmp.empty:
        sys.exit("沒有重疊的日期可比對（檢查資料日期範圍）。")

    over = cmp[cmp["diff_%"] > WARN_PCT]
    lines = [
        f"跨來源比對報告 — {symbol}（Binance open vs CoinGecko）",
        f"產生時間：{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
        f"比對期間：{cmp['date'].min()} ~ {cmp['date'].max()}（最近約 {DAYS} 天）",
        f"比對筆數：{len(cmp)}",
        "-" * 52,
        f"平均差異　：{cmp['diff_%'].mean():.3f}%",
        f"中位數差異：{cmp['diff_%'].median():.3f}%",
        f"最大差異　：{cmp['diff_%'].max():.3f}%（{cmp.loc[cmp['diff_%'].idxmax(), 'date']}）",
        f"差異 > {WARN_PCT}% 的天數：{len(over)} 筆",
    ]

    # 判讀（只是輔助，最終以你親自抽查為準）
    if cmp["diff_%"].mean() < 1 and cmp["diff_%"].max() < 5:
        verdict = "看起來一致：兩個獨立來源高度吻合，資料可信度高。"
    elif cmp["diff_%"].mean() > 20:
        verdict = "差異過大：很可能抓錯幣、單位錯或日期錯位，需回頭檢查 fetch 流程。"
    else:
        verdict = "大致一致，但有少數天差異較大，建議看一下下面列出的日期。"
    lines += ["-" * 52, f"判讀：{verdict}"]

    if len(over):
        lines.append("\n差異較大的日期（前 10 筆）：")
        for _, r in over.head(10).iterrows():
            lines.append(f"  {r['date']}  Binance={r['binance_open']:.2f}  "
                         f"CoinGecko={r['coingecko']:.2f}  差異={r['diff_%']:.2f}%")

    report = "\n".join(lines)
    print("\n" + report + "\n")

    # 把「請你親自抽查」做成程式的一部分：挑頭、中、尾三筆
    sample = cmp.iloc[[0, len(cmp) // 2, -1]]
    print("=" * 52)
    print("請『親自』去 https://www.coingecko.com 查下面三天的價格核對。")
    print("對得上 → 代表這支程式邏輯沒問題，其餘幾百筆才值得信任：")
    for _, r in sample.iterrows():
        print(f"  {r['date']}：本程式說 CoinGecko ≈ {r['coingecko']:.2f} USD")
    print("=" * 52)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"crosscheck_{symbol}_{INTERVAL}.txt"
    out.write_text(report, encoding="utf-8")
    print(f"\n報告已存到：{out}")


if __name__ == "__main__":
    main()