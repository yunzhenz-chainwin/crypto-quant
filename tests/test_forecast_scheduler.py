from backend import scheduler
from src.forecasting import MODEL_VERSION


def _scorecard_summary(status="unverifiable", observations=0):
    return {
        "status": status,
        "data_as_of": None,
        "overall": {"observations": observations},
    }


def _valid_price_rows(count=180):
    # Keep the fixture independent of pandas and calendar helpers used by the
    # implementation while still providing monotonically ordered daily data.
    import pandas as pd

    dates = pd.date_range("2025-01-01", periods=count, freq="D")
    return [
        {"date": day.strftime("%Y-%m-%d"), "close": 100.0 + index}
        for index, day in enumerate(dates)
    ]


def test_forecast_pipeline_appends_three_horizons_and_resolves(monkeypatch):
    saved = []
    finished = []
    lookups = []
    order = []

    monkeypatch.setattr(scheduler, "get_enabled_symbols", lambda: ["BTCUSDT"])
    monkeypatch.setattr(scheduler, "load_prices", lambda symbol, interval="1d": _valid_price_rows())
    monkeypatch.setattr(scheduler, "start_job", lambda kind: 42)
    monkeypatch.setattr(scheduler, "finish_job", lambda *args: finished.append(args))
    monkeypatch.setattr(scheduler, "register_forecast_model", lambda metadata: metadata)
    monkeypatch.setattr(
        scheduler, "load_forecast_snapshot",
        lambda *args: lookups.append(args) or None,
    )
    monkeypatch.setattr(scheduler, "save_forecast_snapshot", lambda payload: saved.append(payload) or payload)
    monkeypatch.setattr(
        scheduler,
        "resolve_mature_forecast_outcomes",
        lambda loader: order.append("resolve") or [{"forecast_id": "resolved"}],
    )
    monkeypatch.setattr(
        scheduler,
        "build_forecast_scorecard",
        lambda **kwargs: order.append("scorecard") or _scorecard_summary(
            "insufficient_evidence", 1
        ),
    )

    result = scheduler.run_forecast_pipeline()

    assert result["status"] == "success"
    assert result["created"] == 3
    assert result["resolved"] == 1
    assert result["scorecard"]["status"] == "insufficient_evidence"
    assert result["scorecard"]["observations"] == 1
    assert order == ["resolve", "scorecard"]
    assert {item["horizon_days"] for item in saved} == {1, 5, 10}
    assert all(item["model_version"] == MODEL_VERSION for item in saved)
    assert all(len(args) == 5 and args[4] == saved[0]["input_hash"] for args in lookups)
    assert finished[-1][1] == "success"


def test_forecast_pipeline_reuses_immutable_snapshots(monkeypatch):
    saved = []
    existing = {"status": "abstain", "model_version": MODEL_VERSION}

    monkeypatch.setattr(scheduler, "get_enabled_symbols", lambda: ["BTCUSDT"])
    monkeypatch.setattr(scheduler, "load_prices", lambda symbol, interval="1d": _valid_price_rows())
    monkeypatch.setattr(scheduler, "start_job", lambda kind: 7)
    monkeypatch.setattr(scheduler, "finish_job", lambda *args: None)
    monkeypatch.setattr(scheduler, "register_forecast_model", lambda metadata: metadata)
    monkeypatch.setattr(scheduler, "load_forecast_snapshot", lambda *args: existing)
    monkeypatch.setattr(scheduler, "save_forecast_snapshot", lambda payload: saved.append(payload))
    monkeypatch.setattr(scheduler, "resolve_mature_forecast_outcomes", lambda loader: [])
    monkeypatch.setattr(
        scheduler, "build_forecast_scorecard", lambda **kwargs: _scorecard_summary()
    )

    result = scheduler.run_forecast_pipeline()

    assert result["status"] == "success"
    assert result["created"] == 0
    assert result["cached"] == 3
    assert result["abstained"] == 3
    assert saved == []


def test_forecast_pipeline_appends_revised_same_day_inputs(monkeypatch):
    rows = _valid_price_rows()
    store = {}

    monkeypatch.setattr(scheduler, "get_enabled_symbols", lambda: ["BTCUSDT"])
    monkeypatch.setattr(scheduler, "load_prices", lambda symbol, interval="1d": rows)
    monkeypatch.setattr(scheduler, "start_job", lambda kind: 9)
    monkeypatch.setattr(scheduler, "finish_job", lambda *args: None)
    monkeypatch.setattr(scheduler, "register_forecast_model", lambda metadata: metadata)
    monkeypatch.setattr(
        scheduler,
        "load_forecast_snapshot",
        lambda symbol, horizon, as_of, model, input_hash: store.get((horizon, input_hash)),
    )
    monkeypatch.setattr(
        scheduler,
        "save_forecast_snapshot",
        lambda payload: store.setdefault((payload["horizon_days"], payload["input_hash"]), payload),
    )
    monkeypatch.setattr(scheduler, "resolve_mature_forecast_outcomes", lambda loader: [])
    monkeypatch.setattr(
        scheduler, "build_forecast_scorecard", lambda **kwargs: _scorecard_summary()
    )

    first = scheduler.run_forecast_pipeline()
    first_hashes = {payload["input_hash"] for payload in store.values()}
    rows[10] = {**rows[10], "close": rows[10]["close"] + 0.25}
    second = scheduler.run_forecast_pipeline()
    all_hashes = {payload["input_hash"] for payload in store.values()}

    assert first["created"] == 3
    assert second["created"] == 3
    assert len(first_hashes) == 1
    assert len(all_hashes) == 2
    assert len(store) == 6


def test_scorecard_failure_does_not_discard_completed_forecast_pipeline(monkeypatch):
    finished = []
    monkeypatch.setattr(scheduler, "get_enabled_symbols", lambda: ["BTCUSDT"])
    monkeypatch.setattr(
        scheduler, "load_prices", lambda symbol, interval="1d": _valid_price_rows()
    )
    monkeypatch.setattr(scheduler, "start_job", lambda kind: 13)
    monkeypatch.setattr(scheduler, "finish_job", lambda *args: finished.append(args))
    monkeypatch.setattr(scheduler, "register_forecast_model", lambda metadata: metadata)
    monkeypatch.setattr(scheduler, "load_forecast_snapshot", lambda *args: None)
    monkeypatch.setattr(scheduler, "save_forecast_snapshot", lambda payload: payload)
    monkeypatch.setattr(scheduler, "resolve_mature_forecast_outcomes", lambda loader: [])

    def _failed_scorecard(**kwargs):
        raise RuntimeError("scorecard unavailable")

    monkeypatch.setattr(scheduler, "build_forecast_scorecard", _failed_scorecard)

    result = scheduler.run_forecast_pipeline()

    assert result["status"] == "success"
    assert result["created"] == 3
    assert result["scorecard"] == {
        "status": "failed",
        "error": "scorecard unavailable",
    }
    assert finished[-1][1] == "success"
