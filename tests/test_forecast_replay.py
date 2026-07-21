from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from src.forecast_replay import main, replay_forecasts
from src.forecasting import generate_forecast


def _daily_rows(count: int, *, start: datetime | None = None) -> list[dict]:
    origin = start or datetime(2025, 1, 1, tzinfo=timezone.utc)
    return [
        {
            "date": (origin + timedelta(days=index)).isoformat(),
            "close": 100.0 + index,
        }
        for index in range(count)
    ]


def test_replay_baseline_uses_only_outcomes_mature_at_issue_time():
    rows = _daily_rows(130)
    issue_date = rows[120]["date"][:10]

    record = replay_forecasts(
        "BTCUSDT",
        rows,
        horizons=(5,),
        start_date=issue_date,
        end_date=issue_date,
    )[0]

    # At issue index 120 and h=5, origins j=0..115 are mature: 116 outcomes.
    assert record["baseline_observations"] == 116
    assert record["baseline_probability_up"] == pytest.approx((116 + 1) / (116 + 2))
    assert record["baseline_latest_origin_date"] == rows[115]["date"][:10]
    assert record["baseline_latest_target_date"] == issue_date
    assert record["target_date"] == rows[125]["date"][:10]
    assert record["outcome_up"] == 1


def test_replay_forecast_prefix_is_unchanged_when_future_rows_are_appended():
    prefix = _daily_rows(125)
    issue_date = prefix[120]["date"][:10]
    with_future = [*prefix, *_daily_rows(10, start=datetime(2026, 1, 1, tzinfo=timezone.utc))]

    prefix_record = replay_forecasts(
        "ETHUSDT",
        prefix[:121],
        horizons=(5,),
        start_date=issue_date,
        end_date=issue_date,
        include_unresolved=True,
    )[0]
    future_record = replay_forecasts(
        "ETHUSDT",
        with_future,
        horizons=(5,),
        start_date=issue_date,
        end_date=issue_date,
        include_unresolved=True,
    )[0]

    protected_fields = (
        "forecast_id",
        "input_hash",
        "probability_up",
        "return_q10_pct",
        "return_q50_pct",
        "return_q90_pct",
        "status",
        "baseline_probability_up",
        "baseline_observations",
    )
    assert {key: prefix_record[key] for key in protected_fields} == {
        key: future_record[key] for key in protected_fields
    }
    assert prefix_record["outcome_up"] is None


def test_optimized_replay_matches_production_forecast_scoring_fields():
    rows = _daily_rows(140)
    # Add deterministic reversals so this is not limited to one regime.
    for index, row in enumerate(rows):
        row["close"] += ((index % 17) - 8) * 1.7
    issue_index = 130
    issue_date = rows[issue_index]["date"][:10]
    records = replay_forecasts(
        "BTCUSDT", rows, start_date=issue_date, end_date=issue_date
    )
    generated_at = datetime.fromisoformat(rows[issue_index]["date"]) + timedelta(days=1)

    for record in records:
        snapshot = generate_forecast(
            "BTCUSDT",
            record["horizon_days"],
            rows[: issue_index + 1],
            now=generated_at,
        )
        assert record["forecast_id"] == snapshot["forecast_id"]
        assert record["input_hash"] == snapshot["input_hash"]
        assert record["status"] == snapshot["status"]
        assert record["probability_up"] == snapshot["probabilities"]["up"]
        assert record["return_q10_pct"] == snapshot["return_quantiles_pct"]["q10"]
        assert record["return_q50_pct"] == snapshot["return_quantiles_pct"]["q50"]
        assert record["return_q90_pct"] == snapshot["return_quantiles_pct"]["q90"]
        assert record["confidence_score"] == snapshot["confidence"]["score"]


def test_replay_horizon_counts_observations_not_calendar_days():
    rows = _daily_rows(126)
    rows[121]["date"] = (datetime(2025, 7, 1, tzinfo=timezone.utc)).isoformat()
    for index in range(122, 126):
        rows[index]["date"] = (
            datetime(2025, 7, 1, tzinfo=timezone.utc) + timedelta(days=index - 120)
        ).isoformat()
    issue_date = rows[120]["date"][:10]

    record = replay_forecasts(
        "SOLUSDT",
        rows,
        horizons=(1,),
        start_date=issue_date,
        end_date=issue_date,
    )[0]

    assert record["target_date"] == "2025-07-01"


def test_replay_validates_bounds_and_horizons():
    rows = _daily_rows(130)
    with pytest.raises(ValueError, match="unsupported horizons"):
        replay_forecasts("BTCUSDT", rows, horizons=(2,))
    with pytest.raises(ValueError, match="cannot be after"):
        replay_forecasts(
            "BTCUSDT", rows, start_date="2025-03-01", end_date="2025-02-01"
        )


def test_cli_writes_explicit_output_atomically(capsys):
    import pandas as pd

    data_dir = Path(__file__).resolve().parent
    frame = pd.DataFrame(_daily_rows(126))
    source = data_dir / "REPLAYTESTUSDT_1d.csv"
    output = data_dir / ".forecast_replay_cli_test.json"
    issue_date = frame.iloc[120]["date"][:10]
    try:
        frame.to_csv(source, index=False)
        result = main(
            [
                "--data-dir",
                str(data_dir),
                "--symbols",
                "REPLAYTESTUSDT",
                "--horizons",
                "1",
                "--start-date",
                issue_date,
                "--end-date",
                issue_date,
                "--bootstrap-samples",
                "10",
                "--output",
                str(output),
            ]
        )

        assert result == 0
        assert output.is_file()
        stdout_payload = json.loads(capsys.readouterr().out)
        assert stdout_payload["records"] == 1
        assert "f1_score" in stdout_payload["scorecard"]["overall"]
        assert "roc_auc" in stdout_payload["scorecard"]["overall"]
        assert "average_precision" in stdout_payload["scorecard"]["overall"]
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["provenance"]["vintage_exact"] is False
        assert payload["provenance"]["universe_source"] == "explicit_cli_symbols"
        assert payload["provenance"]["source_files"]["REPLAYTESTUSDT"]["sha256"]
        assert payload["warnings"]
        assert not list(data_dir.glob(f".{output.name}.*.tmp"))
    finally:
        source.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
