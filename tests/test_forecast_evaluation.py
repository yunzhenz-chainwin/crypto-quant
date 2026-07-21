import json
import math

import pytest

from src.forecast_evaluation import (
    binary_classification_metrics,
    deterministic_block_bootstrap_ci,
    evaluate_binary_forecasts,
    evaluate_prediction_intervals,
    evaluate_replay_records,
    pinball_loss,
    risk_coverage_curve,
)


def test_binary_classification_metrics_cover_threshold_and_ranking_scores():
    metrics = binary_classification_metrics(
        [0.90, 0.80, 0.60, 0.40, 0.30, 0.10],
        [1, 0, 1, 0, 1, 0],
        threshold=0.50,
    )

    assert metrics["classification_threshold"] == 0.5
    assert metrics["confusion_matrix"] == {
        "true_positive": 2,
        "false_positive": 1,
        "true_negative": 2,
        "false_negative": 1,
    }
    assert metrics["precision"] == pytest.approx(2 / 3)
    assert metrics["accuracy"] == pytest.approx(2 / 3)
    assert metrics["recall"] == pytest.approx(2 / 3)
    assert metrics["sensitivity"] == metrics["recall"]
    assert metrics["specificity"] == pytest.approx(2 / 3)
    assert metrics["f1_score"] == pytest.approx(2 / 3)
    assert metrics["balanced_accuracy"] == pytest.approx(2 / 3)
    assert metrics["matthews_correlation_coefficient"] == pytest.approx(1 / 3)
    assert metrics["roc_auc"] == pytest.approx(2 / 3)
    assert metrics["average_precision"] == pytest.approx(0.7555555555555555)
    assert metrics["positive_support"] == 3
    assert metrics["negative_support"] == 3
    assert metrics["positive_class"].startswith("up")


def test_binary_classification_metrics_are_tie_stable():
    first = binary_classification_metrics([0.8, 0.8, 0.2, 0.2], [1, 0, 1, 0])
    second = binary_classification_metrics([0.8, 0.8, 0.2, 0.2], [0, 1, 0, 1])

    assert first["roc_auc"] == second["roc_auc"] == 0.5
    assert first["average_precision"] == second["average_precision"] == 0.5


def test_binary_classification_metrics_return_null_when_undefined():
    empty = binary_classification_metrics([], [])
    single_class = binary_classification_metrics([0.2, 0.8], [1, 1])
    all_flat = binary_classification_metrics([0.2, 0.8], [0, 0])
    no_predicted_positive = binary_classification_metrics([0.1, 0.2], [0, 1])

    assert empty["precision"] is None
    assert empty["accuracy"] is None
    assert empty["recall"] is None
    assert empty["specificity"] is None
    assert empty["f1_score"] is None
    assert empty["balanced_accuracy"] is None
    assert empty["matthews_correlation_coefficient"] is None
    assert empty["roc_auc"] is None
    assert empty["average_precision"] is None
    assert single_class["specificity"] is None
    assert single_class["balanced_accuracy"] is None
    assert single_class["matthews_correlation_coefficient"] is None
    assert single_class["roc_auc"] is None
    assert single_class["average_precision"] is None
    assert all_flat["recall"] is None
    assert all_flat["roc_auc"] is None
    assert all_flat["average_precision"] is None
    assert no_predicted_positive["precision"] is None


def test_empty_binary_forecast_evaluation_returns_null_scores():
    metrics = evaluate_binary_forecasts([], [], baseline_probability=[])

    assert metrics["observations"] == 0
    assert metrics["brier_score"] is None
    assert metrics["log_loss"] is None
    assert metrics["coverage"] is None
    assert metrics["precision"] is None
    assert metrics["roc_auc"] is None
    # The public scorecard contract must emit JSON null, never NaN/Infinity.
    encoded = json.dumps(metrics, allow_nan=False)
    assert '"brier_score": null' in encoded


def test_classification_threshold_includes_probability_tie_as_positive():
    metrics = binary_classification_metrics([0.5, 0.4999], [1, 0], threshold=0.5)

    assert metrics["confusion_matrix"]["true_positive"] == 1
    assert metrics["confusion_matrix"]["true_negative"] == 1
    assert metrics["accuracy"] == 1.0


def test_status_metrics_separate_ready_classification_from_all_forecasts():
    metrics = evaluate_binary_forecasts(
        [0.9, 0.8, 0.7, 0.1],
        [1, 0, 1, 0],
        statuses=["ready", "ready", "abstain", "abstain"],
    )

    ready = metrics["status_metrics"]["ready"]
    assert metrics["observations"] == 4
    assert ready["observations"] == 2
    assert ready["coverage"] == 0.5
    assert ready["positive_support"] == 1
    assert ready["negative_support"] == 1
    assert ready["precision"] == 0.5
    assert ready["roc_auc"] == 1.0


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


def test_fallback_baseline_accepts_ledger_target_as_of_field():
    records = [
        {
            "symbol": "BTCUSDT",
            "issue_date": "2026-01-01",
            "target_as_of": "2026-01-02",
            "horizon_days": 1,
            "probability_up": 0.5,
            "outcome_up": 1,
        },
        {
            "symbol": "BTCUSDT",
            "issue_date": "2026-01-03",
            "target_as_of": "2026-01-04",
            "horizon_days": 1,
            "probability_up": 0.5,
            "outcome_up": 0,
        },
    ]

    scorecard = evaluate_replay_records(records, bootstrap_samples=10)

    # Row 1 has the neutral prior. Row 2 can use row 1 because its target
    # resolved before row 2 was issued: Laplace(1,1) => (1 + 1) / (1 + 2).
    expected = ((0.5 - 1) ** 2 + ((2 / 3) - 0) ** 2) / 2
    assert scorecard["overall"]["baseline_brier_score"] == pytest.approx(expected)
    assert scorecard["baseline_fallback_records"] == 2
    assert scorecard["neutral_baseline_records"] == 0
