"""Leakage-safe metrics for probabilistic forecasts and abstention policies.

The evaluator only consumes predictions whose outcomes have already resolved.
It intentionally keeps training and threshold tuning out of this module so the
same scorecard can be used for rules, statistical baselines, and future ML
models.  All public helpers return plain Python objects suitable for JSON.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from typing import Any

import numpy as np


def _as_finite_vector(
    values: Iterable[float],
    name: str,
    *,
    allow_empty: bool = False,
) -> np.ndarray:
    array = np.asarray(list(values), dtype=float)
    if array.ndim != 1 or (array.size == 0 and not allow_empty):
        qualifier = (
            "a one-dimensional sequence"
            if allow_empty
            else "a non-empty one-dimensional sequence"
        )
        raise ValueError(f"{name} must be {qualifier}")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain only finite values")
    return array


def _safe_ratio(numerator: float | int, denominator: float | int) -> float | None:
    """Return a finite ratio, or null when the metric is undefined."""

    return None if denominator == 0 else float(numerator / denominator)


def _roc_auc(probabilities: np.ndarray, outcomes: np.ndarray) -> float | None:
    """Mann-Whitney ROC-AUC with deterministic average ranks for score ties."""

    positives = int(outcomes.sum())
    negatives = int(outcomes.size - positives)
    if positives == 0 or negatives == 0:
        return None
    order = np.argsort(probabilities, kind="mergesort")
    sorted_probabilities = probabilities[order]
    ranks = np.empty(probabilities.size, dtype=float)
    start = 0
    while start < probabilities.size:
        end = start + 1
        while (
            end < probabilities.size
            and sorted_probabilities[end] == sorted_probabilities[start]
        ):
            end += 1
        # Ranks are one-based; every member of a tie receives its average rank.
        ranks[order[start:end]] = (start + 1 + end) / 2.0
        start = end
    positive_rank_sum = float(ranks[outcomes == 1].sum())
    return float(
        (positive_rank_sum - positives * (positives + 1) / 2.0)
        / (positives * negatives)
    )


def _average_precision(probabilities: np.ndarray, outcomes: np.ndarray) -> float | None:
    """Tie-stable average precision (step-wise area under the PR curve)."""

    positives = int(outcomes.sum())
    negatives = int(outcomes.size - positives)
    if positives == 0 or negatives == 0:
        return None
    order = np.argsort(-probabilities, kind="mergesort")
    sorted_probabilities = probabilities[order]
    sorted_outcomes = outcomes[order]
    true_positives = 0
    selected = 0
    previous_recall = 0.0
    area = 0.0
    start = 0
    while start < probabilities.size:
        end = start + 1
        while (
            end < probabilities.size
            and sorted_probabilities[end] == sorted_probabilities[start]
        ):
            end += 1
        true_positives += int(sorted_outcomes[start:end].sum())
        selected += end - start
        recall = true_positives / positives
        precision = true_positives / selected
        area += (recall - previous_recall) * precision
        previous_recall = recall
        start = end
    return float(area)


def binary_classification_metrics(
    probabilities: Iterable[float],
    outcomes: Iterable[int],
    *,
    threshold: float = 0.5,
) -> dict[str, Any]:
    """Return threshold and ranking metrics for a binary probability forecast.

    A forecast is labelled positive when ``probability >= threshold``. Ratios
    with a zero denominator are returned as ``None`` instead of being silently
    coerced to zero. ROC-AUC and average precision require both outcome classes;
    empty and single-class samples therefore return ``None`` for those ranking
    metrics.
    """

    probs = _as_finite_vector(probabilities, "probabilities", allow_empty=True)
    actual = _as_finite_vector(outcomes, "outcomes", allow_empty=True)
    if probs.size != actual.size:
        raise ValueError("probabilities and outcomes must have equal length")
    if ((probs < 0) | (probs > 1)).any():
        raise ValueError("probabilities must be between 0 and 1")
    if not np.isin(actual, (0.0, 1.0)).all():
        raise ValueError("outcomes must contain only 0 or 1")
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")

    predicted = (probs >= threshold).astype(int)
    labels = actual.astype(int)
    true_positives = int(((predicted == 1) & (labels == 1)).sum())
    false_positives = int(((predicted == 1) & (labels == 0)).sum())
    true_negatives = int(((predicted == 0) & (labels == 0)).sum())
    false_negatives = int(((predicted == 0) & (labels == 1)).sum())
    precision = _safe_ratio(true_positives, true_positives + false_positives)
    recall = _safe_ratio(true_positives, true_positives + false_negatives)
    specificity = _safe_ratio(true_negatives, true_negatives + false_positives)
    f1 = _safe_ratio(
        2 * true_positives,
        2 * true_positives + false_positives + false_negatives,
    )
    balanced_accuracy = (
        None
        if recall is None or specificity is None
        else float((recall + specificity) / 2.0)
    )
    mcc_denominator = float(
        np.sqrt(
            (true_positives + false_positives)
            * (true_positives + false_negatives)
            * (true_negatives + false_positives)
            * (true_negatives + false_negatives)
        )
    )
    mcc = _safe_ratio(
        true_positives * true_negatives - false_positives * false_negatives,
        mcc_denominator,
    )
    return {
        "observations": int(probs.size),
        "positive_class": "up (realized_return_pct > 0; flat is non-up)",
        "positive_support": int(labels.sum()),
        "negative_support": int(labels.size - labels.sum()),
        "classification_threshold": float(threshold),
        "confusion_matrix": {
            "true_positive": true_positives,
            "false_positive": false_positives,
            "true_negative": true_negatives,
            "false_negative": false_negatives,
        },
        "accuracy": _safe_ratio(true_positives + true_negatives, labels.size),
        "precision": precision,
        "recall": recall,
        "sensitivity": recall,
        "specificity": specificity,
        "f1_score": f1,
        "balanced_accuracy": balanced_accuracy,
        "matthews_correlation_coefficient": mcc,
        "roc_auc": _roc_auc(probs, labels),
        "average_precision": _average_precision(probs, labels),
    }


def _baseline_vector(
    baseline_probability: float | Iterable[float] | None,
    actual: np.ndarray,
) -> np.ndarray:
    if baseline_probability is None:
        return np.full(actual.size, float(actual.mean()), dtype=float)
    if np.isscalar(baseline_probability):
        baseline = np.full(actual.size, float(baseline_probability), dtype=float)
    else:
        baseline = _as_finite_vector(baseline_probability, "baseline_probability")
        if baseline.size != actual.size:
            raise ValueError("baseline_probability and outcomes must have equal length")
    if ((baseline < 0) | (baseline > 1)).any():
        raise ValueError("baseline_probability must be between 0 and 1")
    return baseline


def risk_coverage_curve(
    probabilities: Iterable[float],
    outcomes: Iterable[int],
    *,
    confidence: Iterable[float] | None = None,
    classification_threshold: float = 0.5,
) -> list[dict[str, float | int]]:
    """Return classification risk as progressively less-confident cases enter.

    Points are emitted only at confidence ties, so selecting a threshold never
    splits otherwise identical predictions.  ``classification_risk`` is the
    error rate; lower is better.  Brier score is included because accuracy can
    hide badly calibrated probabilities.
    """

    probs = _as_finite_vector(probabilities, "probabilities", allow_empty=True)
    actual = _as_finite_vector(outcomes, "outcomes", allow_empty=True)
    if probs.size != actual.size:
        raise ValueError("probabilities and outcomes must have equal length")
    if ((probs < 0) | (probs > 1)).any():
        raise ValueError("probabilities must be between 0 and 1")
    if not np.isin(actual, (0.0, 1.0)).all():
        raise ValueError("outcomes must contain only 0 or 1")
    if not 0 <= classification_threshold <= 1:
        raise ValueError("classification_threshold must be between 0 and 1")
    if confidence is None:
        certainty = np.maximum(probs, 1.0 - probs)
    else:
        certainty = _as_finite_vector(confidence, "confidence", allow_empty=True)
        if certainty.size != probs.size:
            raise ValueError("confidence and probabilities must have equal length")
        if ((certainty < 0) | (certainty > 1)).any():
            raise ValueError("confidence must be between 0 and 1")

    # mergesort makes ordering deterministic even when confidence ties occur.
    if probs.size == 0:
        return []

    order = np.argsort(-certainty, kind="mergesort")
    sorted_confidence = certainty[order]
    sorted_probs = probs[order]
    sorted_actual = actual[order]
    correct = (
        (sorted_probs >= classification_threshold).astype(float) == sorted_actual
    ).astype(float)
    cumulative_correct = np.cumsum(correct)
    cumulative_brier = np.cumsum((sorted_probs - sorted_actual) ** 2)

    curve: list[dict[str, float | int]] = []
    for index in range(probs.size):
        if index + 1 < probs.size and sorted_confidence[index + 1] == sorted_confidence[index]:
            continue
        count = index + 1
        accuracy = float(cumulative_correct[index] / count)
        curve.append(
            {
                "min_confidence": float(sorted_confidence[index]),
                "observations": int(count),
                "coverage": float(count / probs.size),
                "classification_risk": float(1.0 - accuracy),
                "selective_accuracy": accuracy,
                "brier_score": float(cumulative_brier[index] / count),
            }
        )
    return curve


def evaluate_binary_forecasts(
    probabilities: Iterable[float],
    outcomes: Iterable[int],
    *,
    baseline_probability: float | Iterable[float] | None = None,
    classification_threshold: float = 0.5,
    confidence_threshold: float = 0.60,
    bins: int = 10,
    statuses: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Evaluate probability quality, calibration, and selective predictions.

    ``baseline_probability`` may be a scalar or one point-in-time probability
    per forecast.  The vector form is important for honest replay: a baseline
    observed at forecast time must not be replaced by the final full-sample
    positive rate.  ``statuses`` optionally reports the same decision metrics
    separately for ``ready``, ``abstain``, or future policy states.
    """

    probs = _as_finite_vector(probabilities, "probabilities", allow_empty=True)
    actual = _as_finite_vector(outcomes, "outcomes", allow_empty=True)
    if probs.size != actual.size:
        raise ValueError("probabilities and outcomes must have equal length")
    if ((probs < 0) | (probs > 1)).any():
        raise ValueError("probabilities must be between 0 and 1")
    if not np.isin(actual, (0.0, 1.0)).all():
        raise ValueError("outcomes must contain only 0 or 1")
    if not 0 <= classification_threshold <= 1:
        raise ValueError("classification_threshold must be between 0 and 1")
    if not 0.5 <= confidence_threshold <= 1.0:
        raise ValueError("confidence_threshold must be between 0.5 and 1")
    if bins < 2:
        raise ValueError("bins must be at least 2")

    classification = binary_classification_metrics(
        probs,
        actual,
        threshold=classification_threshold,
    )
    if probs.size == 0:
        if statuses is not None and len(list(statuses)) != 0:
            raise ValueError("statuses and probabilities must have equal length")
        if baseline_probability is not None and not np.isscalar(baseline_probability):
            empty_baseline = _as_finite_vector(
                baseline_probability,
                "baseline_probability",
                allow_empty=True,
            )
            if empty_baseline.size:
                raise ValueError("baseline_probability and outcomes must have equal length")
        return {
            "observations": 0,
            "positive_rate": None,
            "brier_score": None,
            "baseline_brier_score": None,
            "brier_skill_score": None,
            "log_loss": None,
            "baseline_log_loss": None,
            "expected_calibration_error": None,
            "calibration_bins": [],
            **classification,
            "confidence_threshold": float(confidence_threshold),
            "committed_predictions": 0,
            "coverage": None,
            "selective_accuracy": None,
            "status_metrics": {},
            "risk_coverage_curve": [],
        }

    baseline = _baseline_vector(baseline_probability, actual)
    brier_losses = (probs - actual) ** 2
    baseline_losses = (baseline - actual) ** 2
    brier = float(brier_losses.mean())
    clipped = np.clip(probs, 1e-15, 1 - 1e-15)
    log_loss = float(-np.mean(actual * np.log(clipped) + (1 - actual) * np.log(1 - clipped)))
    clipped_baseline = np.clip(baseline, 1e-15, 1 - 1e-15)
    baseline_log_loss = float(
        -np.mean(
            actual * np.log(clipped_baseline)
            + (1 - actual) * np.log(1 - clipped_baseline)
        )
    )
    baseline_brier = float(baseline_losses.mean())
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
    predicted = (probs >= classification_threshold).astype(float)
    selective_accuracy = (
        float((predicted[committed] == actual[committed]).mean())
        if committed_count
        else None
    )

    status_metrics: dict[str, dict[str, float | int | None]] = {}
    if statuses is not None:
        status_array = np.asarray(list(statuses), dtype=object)
        if status_array.ndim != 1 or status_array.size != probs.size:
            raise ValueError("statuses and probabilities must have equal length")
        for status in sorted({str(value) for value in status_array}):
            selected = np.asarray([str(value) == status for value in status_array], dtype=bool)
            count = int(selected.sum())
            classification_for_status = binary_classification_metrics(
                probs[selected],
                actual[selected],
                threshold=classification_threshold,
            )
            status_metrics[status] = {
                "observations": count,
                "coverage": float(count / probs.size),
                "accuracy": float((predicted[selected] == actual[selected]).mean()),
                "brier_score": float(brier_losses[selected].mean()),
                "baseline_brier_score": float(baseline_losses[selected].mean()),
                "brier_skill_score": (
                    None
                    if float(baseline_losses[selected].mean()) == 0
                    else float(
                        1
                        - float(brier_losses[selected].mean())
                        / float(baseline_losses[selected].mean())
                    )
                ),
                "mean_confidence": float(confidence[selected].mean()),
                **classification_for_status,
            }

    return {
        "observations": int(probs.size),
        "positive_rate": float(actual.mean()),
        "brier_score": brier,
        "baseline_brier_score": baseline_brier,
        "brier_skill_score": brier_skill,
        "log_loss": log_loss,
        "baseline_log_loss": baseline_log_loss,
        "expected_calibration_error": float(ece),
        "calibration_bins": calibration,
        **classification,
        "confidence_threshold": float(confidence_threshold),
        "committed_predictions": committed_count,
        "coverage": float(committed_count / probs.size),
        "selective_accuracy": selective_accuracy,
        "status_metrics": status_metrics,
        "risk_coverage_curve": risk_coverage_curve(
            probs,
            actual,
            classification_threshold=classification_threshold,
        ),
    }


def pinball_loss(
    predictions: Iterable[float],
    outcomes: Iterable[float],
    quantile: float,
) -> float:
    """Return mean pinball loss for a single predictive quantile."""

    predicted = _as_finite_vector(predictions, "predictions")
    actual = _as_finite_vector(outcomes, "outcomes")
    if predicted.size != actual.size:
        raise ValueError("predictions and outcomes must have equal length")
    if not 0 < quantile < 1:
        raise ValueError("quantile must be between 0 and 1")
    residual = actual - predicted
    return float(np.maximum(quantile * residual, (quantile - 1.0) * residual).mean())


def evaluate_prediction_intervals(
    lower_bounds: Iterable[float],
    upper_bounds: Iterable[float],
    outcomes: Iterable[float],
    *,
    nominal_coverage: float = 0.80,
    medians: Iterable[float] | None = None,
) -> dict[str, Any]:
    """Measure coverage, sharpness, pinball loss, interval score, and WIS.

    For the forecast contract's q10/q50/q90, use the default 80% nominal
    coverage and pass q50 as ``medians``.  The one-interval WIS follows the
    standard weighting: median absolute error has weight 0.5 and the interval
    score has weight ``alpha / 2``; their sum is divided by ``K + 0.5`` with
    one central interval (``K = 1``).
    """

    lower = _as_finite_vector(lower_bounds, "lower_bounds")
    upper = _as_finite_vector(upper_bounds, "upper_bounds")
    actual = _as_finite_vector(outcomes, "outcomes")
    if not (lower.size == upper.size == actual.size):
        raise ValueError("lower_bounds, upper_bounds and outcomes must have equal length")
    if (lower > upper).any():
        raise ValueError("lower_bounds cannot exceed upper_bounds")
    if not 0 < nominal_coverage < 1:
        raise ValueError("nominal_coverage must be between 0 and 1")

    alpha = 1.0 - nominal_coverage
    covered = (actual >= lower) & (actual <= upper)
    widths = upper - lower
    under = np.maximum(lower - actual, 0.0)
    over = np.maximum(actual - upper, 0.0)
    interval_scores = widths + (2.0 / alpha) * under + (2.0 / alpha) * over
    lower_quantile = alpha / 2.0
    upper_quantile = 1.0 - alpha / 2.0
    result: dict[str, Any] = {
        "observations": int(actual.size),
        "nominal_coverage": float(nominal_coverage),
        "coverage": float(covered.mean()),
        "coverage_error": float(covered.mean() - nominal_coverage),
        "mean_width": float(widths.mean()),
        "median_width": float(np.median(widths)),
        "lower_pinball_loss": pinball_loss(lower, actual, lower_quantile),
        "upper_pinball_loss": pinball_loss(upper, actual, upper_quantile),
        "mean_interval_score": float(interval_scores.mean()),
        "weighted_interval_score": None,
        "median_pinball_loss": None,
    }
    if medians is not None:
        median = _as_finite_vector(medians, "medians")
        if median.size != actual.size:
            raise ValueError("medians and outcomes must have equal length")
        if ((median < lower) | (median > upper)).any():
            raise ValueError("medians must lie within lower_bounds and upper_bounds")
        median_absolute_error = np.abs(actual - median)
        denominator = 1.5
        wis = (0.5 * median_absolute_error + (alpha / 2.0) * interval_scores) / denominator
        result["weighted_interval_score"] = float(wis.mean())
        result["median_pinball_loss"] = pinball_loss(median, actual, 0.5)
    return result


def deterministic_block_bootstrap_ci(
    values: Iterable[float],
    *,
    weights: Iterable[float] | None = None,
    block_size: int = 5,
    n_resamples: int = 1000,
    confidence_level: float = 0.95,
    random_seed: int = 0,
    statistic: Callable[[np.ndarray], float] | None = None,
) -> dict[str, float | int]:
    """Circular moving-block bootstrap confidence interval.

    The seed makes reports reproducible. Contiguous blocks retain short-range
    dependence caused by overlapping forecast horizons. Optional positive
    ``weights`` let a date-clustered interval keep the same row-weighted
    estimand as its headline score when panel counts vary by issue date.
    """

    array = _as_finite_vector(values, "values")
    if not isinstance(block_size, int) or block_size < 1 or block_size > array.size:
        raise ValueError("block_size must be between 1 and the number of values")
    if not isinstance(n_resamples, int) or n_resamples < 1:
        raise ValueError("n_resamples must be a positive integer")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between 0 and 1")
    weight_array = None
    if weights is not None:
        if statistic is not None:
            raise ValueError("weights and a custom statistic cannot be combined")
        weight_array = _as_finite_vector(weights, "weights")
        if weight_array.size != array.size or (weight_array <= 0).any():
            raise ValueError("weights must be positive and match values")
    summary = statistic or (lambda sample: float(np.mean(sample)))
    estimate = (
        float(np.average(array, weights=weight_array))
        if weight_array is not None else float(summary(array))
    )
    rng = np.random.default_rng(random_seed)
    blocks_needed = int(np.ceil(array.size / block_size))
    offsets = np.arange(block_size)
    estimates = np.empty(n_resamples, dtype=float)
    for sample_index in range(n_resamples):
        starts = rng.integers(0, array.size, size=blocks_needed)
        indices = ((starts[:, None] + offsets[None, :]) % array.size).reshape(-1)
        selected = indices[: array.size]
        sample = array[selected]
        estimates[sample_index] = (
            float(np.average(sample, weights=weight_array[selected]))
            if weight_array is not None else float(summary(sample))
        )
    if not np.isfinite(estimates).all():
        raise ValueError("statistic must return a finite value")
    tail = (1.0 - confidence_level) / 2.0
    lower, upper = np.quantile(estimates, [tail, 1.0 - tail])
    return {
        "estimate": estimate,
        "lower": float(lower),
        "upper": float(upper),
        "confidence_level": float(confidence_level),
        "block_size": block_size,
        "n_resamples": n_resamples,
        "random_seed": random_seed,
        "weighted": weight_array is not None,
    }


def _record_value(record: Mapping[str, Any], flat: str, section: str, nested: str) -> Any:
    if flat in record:
        return record.get(flat)
    value = record.get(section)
    return value.get(nested) if isinstance(value, Mapping) else None


def _point_in_time_fallback_baselines(
    records: list[Mapping[str, Any]],
) -> tuple[list[float], int, int]:
    """Fill absent baselines from outcomes already mature at each issue date.

    Baselines are derived separately per symbol/horizon and use Laplace(1,1)
    smoothing. Invalid/missing dates receive the neutral prior 0.5. Crucially,
    this never substitutes the final full-sample positive rate.
    """

    baselines: list[float | None] = []
    missing_indices: list[int] = []
    for index, row in enumerate(records):
        value = row.get("baseline_probability_up")
        if value is None:
            baselines.append(None)
            missing_indices.append(index)
        else:
            baselines.append(float(value))
    if not missing_indices:
        return [float(value) for value in baselines], 0, 0

    groups: defaultdict[tuple[str, int], list[int]] = defaultdict(list)
    for index, row in enumerate(records):
        try:
            horizon = int(row.get("horizon_days"))
        except (TypeError, ValueError):
            horizon = -1
        groups[(str(row.get("symbol") or "unknown"), horizon)].append(index)

    neutral = 0
    for indices in groups.values():
        candidates: list[tuple[str, int]] = []
        for index in indices:
            target_date = (
                records[index].get("target_date")
                or records[index].get("target_as_of")
            )
            if target_date:
                candidates.append((str(target_date), int(records[index]["outcome_up"])))
        candidates.sort(key=lambda item: item[0])
        queries = sorted(
            (
                str(records[index].get("issue_date") or records[index].get("as_of") or ""),
                index,
            )
            for index in indices
            if baselines[index] is None
        )
        matured = 0
        matured_up = 0
        for issue_date, index in queries:
            if not issue_date:
                baselines[index] = 0.5
                neutral += 1
                continue
            while matured < len(candidates) and candidates[matured][0] <= issue_date:
                matured_up += candidates[matured][1]
                matured += 1
            baselines[index] = float((matured_up + 1) / (matured + 2))

    return [float(value) for value in baselines], len(missing_indices), neutral


def evaluate_replay_records(
    records: Iterable[Mapping[str, Any]],
    *,
    confidence_threshold: float = 0.60,
    bins: int = 10,
    block_size: int = 5,
    bootstrap_samples: int = 1000,
    random_seed: int = 0,
) -> dict[str, Any]:
    """Build a scorecard from replay or immutable forecast-ledger records.

    Required resolved fields are ``probability_up``/``probabilities.up`` and
    ``outcome_up``. Point-in-time baselines use ``baseline_probability_up``;
    absent baselines are reconstructed from outcomes already mature at each
    issue date and counted in ``baseline_fallback_records``. Interval metrics
    are reported only for rows carrying q10, q50, q90 and realized returns.
    """

    supplied = list(records)
    usable: list[Mapping[str, Any]] = []
    for record in supplied:
        probability = _record_value(record, "probability_up", "probabilities", "up")
        outcome = record.get("outcome_up")
        if probability is None or outcome not in (0, 1, 0.0, 1.0):
            continue
        usable.append(record)
    if not usable:
        return {
            "records_received": len(supplied),
            "resolved_records": 0,
            "excluded_records": len(supplied),
            "baseline_fallback_records": 0,
            "neutral_baseline_records": 0,
            "overall": None,
            "intervals": None,
            "brier_advantage_ci": None,
            "by_horizon": {},
        }

    probabilities = [
        float(_record_value(row, "probability_up", "probabilities", "up"))
        for row in usable
    ]
    outcomes = [int(row["outcome_up"]) for row in usable]
    statuses = [str(row.get("status") or "unknown") for row in usable]
    baselines, baseline_fallback_records, neutral_baseline_records = (
        _point_in_time_fallback_baselines(usable)
    )
    overall = evaluate_binary_forecasts(
        probabilities,
        outcomes,
        baseline_probability=baselines,
        confidence_threshold=confidence_threshold,
        bins=bins,
        statuses=statuses,
    )

    interval_rows: list[tuple[float, float, float, float]] = []
    for row in usable:
        q10 = _record_value(row, "return_q10_pct", "return_quantiles_pct", "q10")
        q50 = _record_value(row, "return_q50_pct", "return_quantiles_pct", "q50")
        q90 = _record_value(row, "return_q90_pct", "return_quantiles_pct", "q90")
        realized = row.get("realized_return_pct")
        values = (q10, q50, q90, realized)
        if all(value is not None and np.isfinite(float(value)) for value in values):
            interval_rows.append(tuple(float(value) for value in values))
    intervals = None
    if interval_rows:
        lower, median, upper, realized = zip(*interval_rows)
        intervals = evaluate_prediction_intervals(
            lower,
            upper,
            realized,
            nominal_coverage=0.80,
            medians=median,
        )

    # Pair model and forecast-time baseline losses, then cluster all symbols on
    # the same issue date before the moving-block bootstrap.
    dated_advantage: defaultdict[str, list[float]] = defaultdict(list)
    for row, probability, outcome, baseline in zip(usable, probabilities, outcomes, baselines):
        issue_date = str(row.get("issue_date") or row.get("as_of") or "unknown")
        advantage = (baseline - outcome) ** 2 - (probability - outcome) ** 2
        dated_advantage[issue_date].append(float(advantage))
    ordered_dates = sorted(dated_advantage)
    ordered_advantage = np.asarray(
        [np.mean(dated_advantage[key]) for key in ordered_dates], dtype=float,
    )
    issue_date_weights = np.asarray(
        [len(dated_advantage[key]) for key in ordered_dates], dtype=float,
    )
    advantage_ci = None
    if ordered_advantage.size:
        effective_block_size = min(block_size, int(ordered_advantage.size))
        advantage_ci = deterministic_block_bootstrap_ci(
            ordered_advantage,
            weights=issue_date_weights,
            block_size=effective_block_size,
            n_resamples=bootstrap_samples,
            random_seed=random_seed,
        )
        advantage_ci["unit"] = "row-weighted paired Brier advantage, block-clustered by issue date"

    by_horizon: dict[str, Any] = {}
    horizons = sorted(
        {int(row["horizon_days"]) for row in usable if row.get("horizon_days") is not None}
    )
    for horizon in horizons:
        selected = []
        for index, row in enumerate(usable):
            try:
                row_horizon = int(row.get("horizon_days"))
            except (TypeError, ValueError):
                continue
            if row_horizon == horizon:
                selected.append(index)
        by_horizon[str(horizon)] = evaluate_binary_forecasts(
            [probabilities[index] for index in selected],
            [outcomes[index] for index in selected],
            baseline_probability=[baselines[index] for index in selected],
            confidence_threshold=confidence_threshold,
            bins=bins,
            statuses=[statuses[index] for index in selected],
        )

    return {
        "records_received": len(supplied),
        "resolved_records": len(usable),
        "excluded_records": len(supplied) - len(usable),
        "baseline_fallback_records": baseline_fallback_records,
        "neutral_baseline_records": neutral_baseline_records,
        "overall": overall,
        "intervals": intervals,
        "brier_advantage_ci": advantage_ci,
        "by_horizon": by_horizon,
    }
