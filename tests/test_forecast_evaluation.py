import math

import pytest

from src.forecast_evaluation import (
    deterministic_block_bootstrap_ci,
    evaluate_binary_forecasts,
    evaluate_prediction_intervals,
    evaluate_replay_records,
    pinball_loss,
    risk_coverage_curve,
)


def test_perfect_binary_forecasts_have_zero_error():
    metrics = evaluate_binary_forecasts([0.0, 1.0, 0.0, 1.0], [0, 1, 0, 1])

    assert metrics["brier_score"] == 0.0
    assert metrics["expected_calibration_error"] == 0.0
    assert metrics["brier_skill_score"] == 1.0
    assert metrics["coverage"] == 1.0
    assert metrics["selective_accuracy"] == 1.0


def test_uncertain_forecasts_abstain_at_configured_threshold():
    metrics = evaluate_binary_forecasts(
        [0.51, 0.49, 0.90, 0.10],
        [1, 0, 1, 0],
        confidence_threshold=0.70,
    )

    assert metrics["committed_predictions"] == 2
    assert metrics["coverage"] == 0.5
    assert metrics["selective_accuracy"] == 1.0
    assert math.isfinite(metrics["log_loss"])


def test_binary_forecasts_reject_invalid_inputs():
    with pytest.raises(ValueError, match="equal length"):
        evaluate_binary_forecasts([0.5], [0, 1])
    with pytest.raises(ValueError, match="between 0 and 1"):
        evaluate_binary_forecasts([1.1], [1])
    with pytest.raises(ValueError, match="only 0 or 1"):
        evaluate_binary_forecasts([0.5], [2])


def test_prediction_interval_metrics_include_boundary_values():
    metrics = evaluate_prediction_intervals(
        [-1.0, 0.0, 2.0],
        [1.0, 2.0, 4.0],
        [-1.0, 3.0, 4.0],
    )

    assert metrics["coverage"] == pytest.approx(2 / 3)
    assert metrics["mean_width"] == 2.0


def test_prediction_intervals_reject_inverted_bounds():
    with pytest.raises(ValueError, match="cannot exceed"):
        evaluate_prediction_intervals([2.0], [1.0], [1.5])


def test_forecast_time_baseline_vector_and_status_metrics_are_preserved():
    metrics = evaluate_binary_forecasts(
        [0.9, 0.8, 0.4, 0.3],
        [1, 0, 0, 1],
        baseline_probability=[0.5, 0.6, 0.5, 0.4],
        statuses=["ready", "ready", "abstain", "abstain"],
    )

    expected_baseline = sum((p - y) ** 2 for p, y in zip([0.5, 0.6, 0.5, 0.4], [1, 0, 0, 1])) / 4
    assert metrics["baseline_brier_score"] == pytest.approx(expected_baseline)
    assert metrics["status_metrics"]["ready"]["coverage"] == 0.5
    assert metrics["status_metrics"]["ready"]["accuracy"] == 0.5
    assert metrics["status_metrics"]["abstain"]["observations"] == 2


def test_risk_coverage_curve_keeps_equal_confidence_predictions_together():
    curve = risk_coverage_curve([0.9, 0.1, 0.7, 0.3], [1, 0, 0, 0])

    assert len(curve) == 2
    assert curve[0]["coverage"] == 0.5
    assert curve[0]["classification_risk"] == 0.0
    assert curve[1]["coverage"] == 1.0
    assert curve[1]["classification_risk"] == 0.25


def test_interval_score_pinball_and_wis_are_reported():
    metrics = evaluate_prediction_intervals(
        [-1.0, -1.0],
        [1.0, 1.0],
        [0.0, 3.0],
        medians=[0.0, 0.0],
    )

    assert metrics["nominal_coverage"] == 0.8
    assert metrics["lower_pinball_loss"] == pytest.approx(
        pinball_loss([-1.0, -1.0], [0.0, 3.0], 0.1)
    )
    assert metrics["upper_pinball_loss"] == pytest.approx(
        pinball_loss([1.0, 1.0], [0.0, 3.0], 0.9)
    )
    assert metrics["mean_interval_score"] == pytest.approx(12.0)
    assert metrics["weighted_interval_score"] == pytest.approx(1.3)


def test_block_bootstrap_is_deterministic_and_validates_block_size():
    first = deterministic_block_bootstrap_ci(
        [1.0, 2.0, 3.0, 4.0], block_size=2, n_resamples=100, random_seed=17
    )
    second = deterministic_block_bootstrap_ci(
        [1.0, 2.0, 3.0, 4.0], block_size=2, n_resamples=100, random_seed=17
    )

    assert first == second
    assert first["estimate"] == 2.5
    assert first["lower"] <= first["estimate"] <= first["upper"]
    with pytest.raises(ValueError, match="block_size"):
        deterministic_block_bootstrap_ci([1.0, 2.0], block_size=3)


def test_weighted_date_cluster_ci_matches_row_weighted_headline_estimand():
    records = [
        {
            "issue_date": "2026-01-01",
            "horizon_days": 1,
            "probability_up": 0.9,
            "baseline_probability_up": 0.5,
            "outcome_up": 1,
        },
        {
            "issue_date": "2026-01-01",
            "horizon_days": 1,
            "probability_up": 0.8,
            "baseline_probability_up": 0.5,
            "outcome_up": 1,
        },
        {
            "issue_date": "2026-01-02",
            "horizon_days": 1,
            "probability_up": 0.9,
            "baseline_probability_up": 0.5,
            "outcome_up": 0,
        },
    ]

    scorecard = evaluate_replay_records(
        records, block_size=2, bootstrap_samples=20, random_seed=9
    )
    expected = (
        scorecard["overall"]["baseline_brier_score"]
        - scorecard["overall"]["brier_score"]
    )
    assert scorecard["brier_advantage_ci"]["weighted"] is True
    assert scorecard["brier_advantage_ci"]["estimate"] == pytest.approx(expected)


def test_replay_scorecard_accepts_flat_and_nested_contracts():
    records = [
        {
            "issue_date": "2026-01-01",
            "horizon_days": 1,
            "status": "ready",
            "probability_up": 0.8,
            "baseline_probability_up": 0.5,
            "outcome_up": 1,
            "return_q10_pct": -1.0,
            "return_q50_pct": 1.0,
            "return_q90_pct": 3.0,
            "realized_return_pct": 2.0,
        },
        {
            "as_of": "2026-01-02",
            "horizon_days": 1,
            "status": "abstain",
            "probabilities": {"up": 0.4},
            "baseline_probability_up": 0.5,
            "outcome_up": 0,
            "return_quantiles_pct": {"q10": -2.0, "q50": 0.0, "q90": 2.0},
            "realized_return_pct": -1.0,
        },
        {"status": "abstain", "probability_up": None, "outcome_up": None},
    ]

    scorecard = evaluate_replay_records(records, bootstrap_samples=20, random_seed=3)

    assert scorecard["records_received"] == 3
    assert scorecard["resolved_records"] == 2
    assert scorecard["excluded_records"] == 1
    assert scorecard["overall"]["status_metrics"]["ready"]["observations"] == 1
    assert scorecard["intervals"]["observations"] == 2
    assert scorecard["brier_advantage_ci"]["block_size"] == 2
    assert scorecard["by_horizon"]["1"]["observations"] == 2
