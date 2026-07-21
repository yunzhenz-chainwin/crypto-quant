import math

import pytest

from src.forecast_evaluation import (
    evaluate_binary_forecasts,
    evaluate_prediction_intervals,
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
