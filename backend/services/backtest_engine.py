import sys
from collections import OrderedDict
from pathlib import Path
from threading import RLock

# 讓 backend 可以 import src/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from src.backtest import (
    load_indicators,
    compute_signals,
    parameter_sweep,
    run_backtest,
    compute_metrics,
    walk_forward_split_report,
    random_entry_baseline,
    REPORT_DIR,
    INTERVAL,
)

# 記憶體快取:key = (幣種, 量化後參數…, 指標檔 mtime) → 結果。
# 含 mtime 代表資料更新(每日排程重產指標)後快取會自動失效；LRU 上限
# 則避免公開查詢用大量參數組合無限吃掉記憶體。
MAX_CACHE_ENTRIES = 64
MAX_EQUITY_CHART_POINTS = 600
_cache: OrderedDict = OrderedDict()
_cache_lock = RLock()


def _normalise_params(stop_loss: float, take_profit: float,
                      fee_rate: float, slippage_rate: float) -> tuple[float, float, float, float]:
    """Canonicalise public parameters so equivalent floats share one cache key."""
    return (
        round(float(stop_loss), 2),
        round(float(take_profit), 2),
        round(float(fee_rate), 4),
        round(float(slippage_rate), 4),
    )


def _cache_get(key):
    with _cache_lock:
        value = _cache.get(key)
        if value is not None:
            _cache.move_to_end(key)
        return value


def _cache_put(key, value):
    with _cache_lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > MAX_CACHE_ENTRIES:
            _cache.popitem(last=False)


def _compact_equity_curve(curve: list[dict], max_points: int = MAX_EQUITY_CHART_POINTS) -> list[dict]:
    """Keep the chart payload bounded while retaining endpoints and extrema.

    Risk metrics are still computed from every daily observation.  This only
    reduces redundant pixels sent to the browser for visualization.
    """
    if not curve:
        return []
    if max_points < 2:
        raise ValueError("max_points must be at least 2")

    count = len(curve)
    if count <= max_points:
        indices = set(range(count))
    else:
        indices = {
            round(position * (count - 1) / (max_points - 1))
            for position in range(max_points)
        }
        for field in ("equity", "bh"):
            valid = [
                (index, float(point[field]))
                for index, point in enumerate(curve)
                if point.get(field) is not None
            ]
            if valid:
                indices.add(min(valid, key=lambda item: item[1])[0])
                indices.add(max(valid, key=lambda item: item[1])[0])

    return [
        {
            "date": curve[index].get("date"),
            "equity": curve[index].get("equity"),
            "bh": curve[index].get("bh"),
        }
        for index in sorted(indices)
    ]


def _indicators_mtime(symbol: str) -> float:
    try:
        return (REPORT_DIR / f"indicators_{symbol}_{INTERVAL}.csv").stat().st_mtime
    except OSError:
        return 0.0


def get_backtest(symbol: str,
                 stop_loss: float = -0.06,
                 take_profit: float = 0.20,
                 fee_rate: float = 0.001,
                 slippage_rate: float = 0.0005) -> dict:
    stop_loss, take_profit, fee_rate, slippage_rate = _normalise_params(
        stop_loss, take_profit, fee_rate, slippage_rate,
    )
    key = (symbol, stop_loss, take_profit, fee_rate, slippage_rate,
           _indicators_mtime(symbol))
    cached = _cache_get(key)
    if cached is not None:
        return cached

    df = load_indicators(symbol)
    if df.empty:
        return {"error": "no indicator data"}

    # 訊號只與指標有關 → 算一次,主回測與參數掃描共用(掃描只變停損停利)
    signals = compute_signals(df)

    trades = run_backtest(
        df,
        stop_loss=stop_loss,
        take_profit=take_profit,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        signals=signals,
    )
    metrics = compute_metrics(trades, df)

    # 隨機進場基準：同筆數/同持有天數/同停損停利，只有「買的日子」亂選（固定種子可重現）。
    # 回答「策略的選時是否贏過亂選」——非關鍵功能，失敗回 None、前端優雅降級。
    baseline = None
    if "error" not in metrics:
        try:
            baseline = random_entry_baseline(
                df, trades, metrics["total_return_pct"],
                stop_loss=stop_loss, take_profit=take_profit,
                fee_rate=fee_rate, slippage_rate=slippage_rate)
        except Exception:
            baseline = None

    split = walk_forward_split_report(
        df,
        stop_loss=stop_loss,
        take_profit=take_profit,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
    )
    sweep = parameter_sweep(
        df,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        signals=signals,
    )

    full_curve = metrics.get("equity_curve", [])
    display_curve = _compact_equity_curve(full_curve)
    result = {
        "symbol":  symbol,
        "params":  {
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "fee_rate": fee_rate,
            "slippage_rate": slippage_rate,
        },
        "period":  {
            "start": str(df["date"].min().date()),
            "end":   str(df["date"].max().date()),
        },
        "metrics": {k: v for k, v in metrics.items() if k != "equity_curve"},
        "random_baseline": baseline,
        "equity_curve": display_curve,
        "equity_curve_sampling": {
            "frequency": "daily",
            "source_points": len(full_curve),
            "display_points": len(display_curve),
            "method": "evenly_spaced_with_extrema",
        },
        "recent_trades": trades,  # 全部交易（前端明細表顯示全部、與後台一致；K 線僅畫視窗內可見的標記）
        "validation": split,
        "parameter_sweep": sweep[:5],
    }
    _cache_put(key, result)
    return result
