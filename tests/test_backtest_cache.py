from backend.services import backtest_engine
from backend.routers import backtest as backtest_router


def test_backtest_parameter_normalisation_collapses_float_noise():
    assert backtest_engine._normalise_params(-0.0600000001, 0.1999999999, 0.00101, 0.00049) == (
        -0.06,
        0.20,
        0.001,
        0.0005,
    )


def test_backtest_cache_is_lru_bounded():
    backtest_engine._cache.clear()
    for index in range(backtest_engine.MAX_CACHE_ENTRIES + 5):
        backtest_engine._cache_put((index,), {"index": index})

    assert len(backtest_engine._cache) == backtest_engine.MAX_CACHE_ENTRIES
    assert (0,) not in backtest_engine._cache
    assert (backtest_engine.MAX_CACHE_ENTRIES + 4,) in backtest_engine._cache


def test_equity_chart_compaction_keeps_dates_endpoints_and_extrema():
    curve = [
        {"date": f"2025-01-{index + 1:02d}", "equity": float(index), "bh": float(20 - index)}
        for index in range(20)
    ]
    curve[7]["equity"] = -50.0
    compact = backtest_engine._compact_equity_curve(curve, max_points=6)

    dates = {point["date"] for point in compact}
    assert curve[0]["date"] in dates
    assert curve[-1]["date"] in dates
    assert curve[7]["date"] in dates
    assert all(set(point) == {"date", "equity", "bh"} for point in compact)


def test_backtest_collection_uses_bounded_persisted_summary(monkeypatch):
    expected = [{"symbol": "BTCUSDT", "total_return_pct": 12.3}]
    monkeypatch.setattr(backtest_router, "load_backtest_summary", lambda: expected)
    monkeypatch.setattr(
        backtest_router,
        "get_backtest",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not cold-run all coins")),
    )

    assert backtest_router.backtest_all() == expected
