"""Metrics for evaluating probabilistic forecasts and abstention policies.

The functions in this module deliberately operate on resolved, out-of-sample
predictions.  They do not train or tune a model, which keeps the same evaluator
usable for rules, statistical baselines, and future ML models.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np


def _as_finite_vector(values: Iterable[float], name: str) -> np.ndarray:
    array = np.asarray(list(values), dtype=float)
    if array.ndim != 1 or array.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional sequence")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain only finite values")
    return array


def evaluate_binary_forecasts(
    probabilities: Iterable[float],
    outcomes: Iterable[int],
    *,
    baseline_probability: float | None = None,
    confidence_threshold: float = 0.60,
    bins: int = 10,
) -> dict:
    """Evaluate calibrated binary probabilities and a selective policy.

    ``probabilities`` are probabilities of the positive class and ``outcomes``
    must contain only 0/1 values.  Predictions whose winning-class confidence
    is below ``confidence_threshold`` are treated as abstentions.
    """

    probs = _as_finite_vector(probabilities, "probabilities")
    actual = _as_finite_vector(outcomes, "outcomes")
    if probs.size != actual.size:
        raise ValueError("probabilities and outcomes must have equal length")
    if ((probs < 0) | (probs > 1)).any():
        raise ValueError("probabilities must be between 0 and 1")
    if not np.isin(actual, (0.0, 1.0)).all():
        raise ValueError("outcomes must contain only 0 or 1")
    if not 0.5 <= confidence_threshold <= 1.0:
        raise ValueError("confidence_threshold must be between 0.5 and 1")
    if bins < 2:
        raise ValueError("bins must be at least 2")

    brier = float(np.mean((probs - actual) ** 2))
    clipped = np.clip(probs, 1e-15, 1 - 1e-15)
    log_loss = float(-np.mean(actual * np.log(clipped) + (1 - actual) * np.log(1 - clipped)))

    base = float(actual.mean()) if baseline_probability is None else float(baseline_probability)
    if not 0 <= base <= 1:
        raise ValueError("baseline_probability must be between 0 and 1")
    baseline_brier = float(np.mean((base - actual) ** 2))
    brier_skill = None if baseline_brier == 0 else float(1 - brier / baseline_brier)

    # Equal-width Expected Calibration Error. Probability 1.0 belongs to the
    # final bin rather than falling outside the right-open intervals.
    bin_ids = np.minimum((probs * bins).astype(int), bins - 1)
    ece = 0.0
    calibration = []
    for bin_id in range(bins):
        selected = bin_ids == bin_id
        count = int(selected.sum())
        if count == 0:
            continue
        mean_probability = float(probs[selected].mean())
        observed_rate = float(actual[selected].mean())
        ece += (count / probs.size) * abs(mean_probability - observed_rate)
        calibration.append(
            {
                "bin": bin_id,
                "count": count,
                "mean_probability": mean_probability,
                "observed_rate": observed_rate,
            }
        )

    confidence = np.maximum(probs, 1 - probs)
    committed = confidence >= confidence_threshold
    committed_count = int(committed.sum())
    predicted = (probs >= 0.5).astype(float)
    selective_accuracy = (
        float((predicted[committed] == actual[committed]).mean())
        if committed_count
        else None
    )

    return {
        "observations": int(probs.size),
        "positive_rate": float(actual.mean()),
        "brier_score": brier,
        "baseline_brier_score": baseline_brier,
        "brier_skill_score": brier_skill,
        "log_loss": log_loss,
        "expected_calibration_error": float(ece),
        "calibration_bins": calibration,
        "confidence_threshold": float(confidence_threshold),
        "committed_predictions": committed_count,
        "coverage": float(committed_count / probs.size),
        "selective_accuracy": selective_accuracy,
    }


def evaluate_prediction_intervals(
    lower_bounds: Iterable[float],
    upper_bounds: Iterable[float],
    outcomes: Iterable[float],
) -> dict:
    """Measure empirical interval coverage and average interval width."""

    lower = _as_finite_vector(lower_bounds, "lower_bounds")
    upper = _as_finite_vector(upper_bounds, "upper_bounds")
    actual = _as_finite_vector(outcomes, "outcomes")
    if not (lower.size == upper.size == actual.size):
        raise ValueError("lower_bounds, upper_bounds and outcomes must have equal length")
    if (lower > upper).any():
        raise ValueError("lower_bounds cannot exceed upper_bounds")

    covered = (actual >= lower) & (actual <= upper)
    widths = upper - lower
    return {
        "observations": int(actual.size),
        "coverage": float(covered.mean()),
        "mean_width": float(widths.mean()),
        "median_width": float(np.median(widths)),
    }
