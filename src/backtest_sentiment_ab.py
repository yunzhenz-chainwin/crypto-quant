"""
backtest_sentiment_ab.py — 「技術 6 因子」 vs 「技術 + 新聞情緒 7 因子」A/B 回測對照

目的：用歷史資料實測——把新聞情緒（文字探勘產物）當第 7 因子接進訊號，
到底有沒有改善績效。同一段期間、同一套停損停利，唯一差異＝有沒有餵情緒分數。

資料來源：
  指標   reports/indicators_<SYMBOL>_1d.csv（既有）
  情緒   data/news.db → news_sentiment_daily（該幣優先，缺日退回全市場 MARKET）

用法：
  python src/backtest_sentiment_ab.py                 # 預設 BTCUSDT
  python src/backtest_sentiment_ab.py ETHUSDT

誠實聲明：情緒彙總自 2025-01 起、樣本約 18 個月，per-coin 僅 BTC 天數足夠，
其餘幣多退回全市場情緒。結論屬「參考級」，非長期鐵證。若兩組訊號差異天數極少，
代表 ±8 權重在此門檻下幾乎不改變決策 → 結論「無顯著差異」本身也是誠實結果。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.backtest import load_indicators, compute_signals, run_backtest_report  # noqa: E402
from backend.services.news_store import load_sentiment_daily                    # noqa: E402

SENTIMENT_START = "2025-01-01"   # 情緒資料最早日期；比對窗口從這天起才有意義


def build_sentiment_map(symbol: str):
    """回傳 (合併後每日情緒 map, 診斷 dict)。該幣有資料的日期優先、其餘日退回 MARKET。"""
    ticker = symbol.upper().replace("USDT", "")
    coin = {r["date"]: r["score"] for r in load_sentiment_daily(ticker, days=100000)}
    market = {r["date"]: r["score"] for r in load_sentiment_daily("MARKET", days=100000)}
    merged = dict(market)      # 先鋪全市場
    merged.update(coin)        # 該幣有資料的日期覆蓋掉全市場
    info = {"ticker": ticker, "coin_days": len(coin),
            "market_days": len(market), "merged_days": len(merged)}
    return merged, info


def _date_strings(df):
    return df["date"].map(lambda d: d.date().isoformat() if hasattr(d, "date") else str(d)[:10])


def _row(label, mb, mn, key, dp=2, unit=""):
    """一列對照：指標名 | 6因子 | 7因子 | Δ。缺值以 — 顯示。"""
    b = mb.get(key) if isinstance(mb, dict) else None
    n = mn.get(key) if isinstance(mn, dict) else None
    def f(v):
        return "—" if v is None else (f"{v:.{dp}f}" if dp else f"{int(v)}")
    if b is None or n is None:
        delta = "—"
    else:
        d = n - b
        delta = f"{d:+.{dp}f}" if dp else f"{d:+d}"
    print(f"  {label:<12}{f(b)+unit:>14}{f(n)+unit:>16}{delta+unit:>14}")


def main():
    symbol = (sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT").upper()
    df_full = load_indicators(symbol)

    # 只比對情緒存在的期間，避免前段「兩組完全相同」稀釋結論
    dcol_full = _date_strings(df_full)
    df = df_full[dcol_full >= SENTIMENT_START].reset_index(drop=True)
    if len(df) < 30:
        sys.exit(f"[ERROR] {symbol} 在 {SENTIMENT_START} 之後資料不足（{len(df)} 天），無法比對。")
    dcol = _date_strings(df)

    smap, info = build_sentiment_map(symbol)

    # 兩組訊號：純技術 6 因子 vs 技術+新聞 7 因子
    sigs_base = compute_signals(df)
    sigs_news = compute_signals(df, sentiment_by_date=smap)

    # 診斷：窗口內有幾天真的有情緒分數、兩組訊號差了幾天
    covered = sum(1 for d in dcol if d in smap)
    diff_days = sum(1 for a, b in zip(sigs_base, sigs_news) if a != b)

    rep_base = run_backtest_report(df, signals=sigs_base)
    rep_news = run_backtest_report(df, signals=sigs_news)
    mb, mn = rep_base["metrics"], rep_news["metrics"]

    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  {symbol} 情緒因子 A/B 回測（日線）")
    print(f"  比對期間 : {dcol.iloc[0]} ~ {dcol.iloc[-1]}（{len(df)} 根 K 棒）")
    print(sep)
    print(f"  情緒來源 : {info['ticker']} 自身 {info['coin_days']} 天 + 全市場 {info['market_days']} 天")
    print(f"  窗口內有情緒分數的天數 : {covered} / {len(df)}")
    print(f"  兩組『訊號』不同的天數 : {diff_days}"
          + ("   ← 差異極小，下方績效差距僅供參考" if diff_days < 5 else ""))
    print("-" * 60)

    if "error" in mb or "error" in mn:
        print(f"  6 因子: {mb.get('error', 'ok')}")
        print(f"  7 因子: {mn.get('error', 'ok')}")
        print(sep)
        return

    print(f"  {'指標':<12}{'6 因子':>14}{'7 因子(+情緒)':>16}{'Δ':>14}")
    print("-" * 60)
    _row("交易筆數",   mb, mn, "total_trades",        dp=0)
    _row("勝率",       mb, mn, "win_rate",            dp=1, unit="%")
    _row("總報酬",     mb, mn, "total_return_pct",    dp=2, unit="%")
    _row("買入持有",   mb, mn, "buy_hold_return_pct", dp=2, unit="%")
    _row("超額報酬",   mb, mn, "excess_return_pct",   dp=2, unit="%")
    _row("最大回撤",   mb, mn, "max_drawdown_pct",    dp=2, unit="%")
    _row("Sharpe",     mb, mn, "sharpe_ratio",        dp=2)
    _row("獲利因子",   mb, mn, "profit_factor",       dp=2)
    _row("平均持有天", mb, mn, "avg_hold_days",       dp=1)
    print(sep)
    print("  註：情緒因子權重 ±8，僅在接近 65/35 門檻時可能改變訊號；")
    print("      樣本約 18 個月，結論屬參考級，非長期保證。")
    print(f"{sep}\n")


if __name__ == "__main__":
    main()
