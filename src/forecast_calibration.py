"""Leakage-safe probability-calibration challengers for forecast research.

This module deliberately does not alter :mod:`src.forecasting` or its model
version.  It produces point-in-time Platt and beta-calibration *challengers*
alongside the identity/raw probability.  Every issue-date batch is transformed
before outcomes resolving on that same date are admitted to future fits.

Only NumPy is required.  The calibrators use deterministic, regularized
logistic Newton/IRLS fits with monotonicity constraints, so one issue-date
mapping cannot reverse ranking within its batch. Because mappings evolve over
time, pooled cross-date AUC can still change and is checked separately. No
function in this file deploys or promotes a model automatically.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

import numpy as np

from src.forecast_evaluation import evaluate_binary_forecasts


SCHEMA_VERSION = "forecast-calibration-research-v1"
CALIBRATOR_VERSION = "monotone-platt-beta-v1"
DEFAULT_MIN_CALIBRATION_SAMPLES = 180
DEFAULT_MIN_CALIBRATION_ISSUE_DATES = 90
DEFAULT_MIN_CLASS_SAMPLES = 30
DEFAULT_PROBABILITY_CLIP = 1e-6
DEFAULT_L2 = 1.0
DEFAULT_PROMOTION_MIN_SAMPLES = 1000
DEFAULT_PROMOTION_MIN_ISSUE_DATES = 180
DEFAULT_PROMOTION_MIN_CLASS_SAMPLES = 100
DEFAULT_MAX_ROC_AUC_DEGRADATION = 0.002
DEFAULT_PROMOTION_CONFIDENCE_LEVEL = 0.95
DEFAULT_PROMOTION_BOOTSTRAP_SAMPLES = 1000
CHALLENGER_METHODS = ("platt", "beta")


def _day(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _probability(record: Mapping[str, Any]) -> float | None:
    value = record.get("probability_up")
    if value is None and isinstance(record.get("probabilities"), Mapping):
        value = record["probabilities"].get("up")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0.0 <= number <= 1.0 else None


def _baseline_probability(record: Mapping[str, Any]) -> float | None:
    try:
        number = float(record.get("baseline_probability_up"))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0.0 <= number <= 1.0 else None


def _outcome(record: Mapping[str, Any]) -> int | None:
    value = record.get("outcome_up")
    if value in (0, 0.0, False):
        return 0
    if value in (1, 1.0, True):
        return 1
    return None


def _horizon(record: Mapping[str, Any]) -> int | None:
    try:
        value = int(record.get("horizon_days"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _explicit_symbol(record: Mapping[str, Any]) -> str | None:
    value = str(record.get("symbol") or "").strip().upper()
    return value if value and value != "UNKNOWN" else None


def _canonical_record(record: Mapping[str, Any]) -> dict[str, Any]:
    issue_date = _day(record.get("issue_date") or record.get("as_of"))
    target_date = _day(record.get("target_date") or record.get("target_as_of"))
    model_version = str(record.get("model_version") or "unknown")
    canonical = {
        "forecast_id": (
            str(record.get("forecast_id")) if record.get("forecast_id") is not None else None
        ),
        "symbol": _explicit_symbol(record) or "UNKNOWN",
        "horizon_days": _horizon(record),
        "model_version": model_version,
        "issue_date": issue_date,
        "target_date": target_date,
        "raw_probability_up": _probability(record),
        "baseline_probability_up": _baseline_probability(record),
        "outcome_up": _outcome(record),
        "status": record.get("status"),
    }
    fingerprint_payload = {
        key: canonical[key]
        for key in (
            "forecast_id",
            "symbol",
            "horizon_days",
            "model_version",
            "issue_date",
            "target_date",
            "raw_probability_up",
            "baseline_probability_up",
            "outcome_up",
        )
    }
    canonical["record_fingerprint"] = sha256(
        json.dumps(
            fingerprint_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).hexdigest()[:24]
    return canonical


def _group_key(record: Mapping[str, Any]) -> tuple[str, int] | None:
    horizon = record.get("horizon_days")
    if not isinstance(horizon, int) or horizon <= 0:
        return None
    model_version = record.get("model_version")
    if (
        not isinstance(model_version, str)
        or not model_version.strip()
        or model_version.strip().lower() == "unknown"
    ):
        return None
    # Symbols intentionally pool, but revisions from different model versions
    # never share a calibrator.
    return model_version.strip(), horizon


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _objective(
    features: np.ndarray,
    outcomes: np.ndarray,
    parameters: np.ndarray,
    prior: np.ndarray,
    penalties: np.ndarray,
) -> float:
    linear = features @ parameters
    likelihood = np.logaddexp(0.0, linear) - outcomes * linear
    regularization = 0.5 * np.sum(penalties * (parameters - prior) ** 2)
    return float(likelihood.sum() + regularization)


def _fit_logistic_irls(
    features: np.ndarray,
    outcomes: np.ndarray,
    *,
    prior: np.ndarray,
    penalties: np.ndarray,
    initial: np.ndarray | None = None,
    nonnegative_indices: tuple[int, ...] = (),
    max_iterations: int = 100,
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    """Fit a small regularized logistic model with projected Newton steps."""

    parameters = (
        prior.astype(float, copy=True)
        if initial is None
        else np.asarray(initial, dtype=float).copy()
    )
    if parameters.shape != prior.shape or not np.isfinite(parameters).all():
        return {
            "ok": False,
            "reason": "invalid_initial_parameters",
            "iterations": 0,
        }
    for index in nonnegative_indices:
        parameters[index] = max(0.0, float(parameters[index]))
    converged = False
    iterations = 0
    for iterations in range(1, max_iterations + 1):
        fitted = _sigmoid(features @ parameters)
        weights = np.maximum(fitted * (1.0 - fitted), 1e-10)
        gradient = features.T @ (fitted - outcomes)
        gradient += penalties * (parameters - prior)
        hessian = features.T @ (features * weights[:, None])
        hessian += np.diag(penalties + 1e-10)
        projected_gradient = gradient.copy()
        for index in nonnegative_indices:
            if parameters[index] <= 1e-10 and projected_gradient[index] > 0.0:
                projected_gradient[index] = 0.0
        if float(np.max(np.abs(projected_gradient))) <= 1e-7:
            converged = True
            break

        free = np.ones(parameters.size, dtype=bool)
        for index in nonnegative_indices:
            if parameters[index] <= 1e-10 and gradient[index] >= 0.0:
                free[index] = False
        if not free.any():
            converged = True
            break
        try:
            free_step = np.linalg.solve(
                hessian[np.ix_(free, free)], gradient[free]
            )
        except np.linalg.LinAlgError:
            free_step = np.linalg.lstsq(
                hessian[np.ix_(free, free)], gradient[free], rcond=None
            )[0]
        step = np.zeros_like(parameters)
        step[free] = free_step
        if not np.isfinite(step).all():
            return {
                "ok": False,
                "reason": "non_finite_newton_step",
                "iterations": iterations,
            }

        proposal = parameters - step
        for index in nonnegative_indices:
            proposal[index] = max(0.0, float(proposal[index]))
        current_objective = _objective(
            features, outcomes, parameters, prior, penalties
        )
        accepted = False
        scale = 1.0
        candidate = parameters
        while scale >= 2.0**-20:
            candidate = parameters + scale * (proposal - parameters)
            for index in nonnegative_indices:
                candidate[index] = max(0.0, float(candidate[index]))
            candidate_objective = _objective(
                features, outcomes, candidate, prior, penalties
            )
            if candidate_objective <= current_objective + 1e-12:
                accepted = True
                break
            scale *= 0.5
        if not accepted:
            # Newton directions can be unreliable when a coefficient hits a
            # monotonicity boundary. A diagonally scaled projected-gradient
            # step remains a descent direction and makes constant/singular
            # probability streams fail-safe instead of failing spuriously.
            scale = 1.0 / max(1.0, float(np.max(np.diag(hessian))))
            while scale >= 2.0**-40:
                candidate = parameters - scale * projected_gradient
                for index in nonnegative_indices:
                    candidate[index] = max(0.0, float(candidate[index]))
                if _objective(features, outcomes, candidate, prior, penalties) <= (
                    current_objective + 1e-12
                ):
                    accepted = True
                    break
                scale *= 0.5
            if not accepted:
                return {
                    "ok": False,
                    "reason": "line_search_failed",
                    "iterations": iterations,
                }

        delta = float(np.max(np.abs(candidate - parameters)))
        parameters = candidate
        if delta <= tolerance:
            converged = True
            break

    if not converged or not np.isfinite(parameters).all():
        return {
            "ok": False,
            "reason": "optimizer_did_not_converge",
            "iterations": iterations,
        }
    return {
        "ok": True,
        "parameters": parameters,
        "iterations": iterations,
        "objective": _objective(features, outcomes, parameters, prior, penalties),
    }


def _method_features(
    method: str, probabilities: np.ndarray, probability_clip: float
) -> np.ndarray:
    clipped = np.clip(probabilities, probability_clip, 1.0 - probability_clip)
    if method == "platt":
        return np.column_stack(
            (np.log(clipped) - np.log1p(-clipped), np.ones(clipped.size))
        )
    if method == "beta":
        return np.column_stack(
            (np.log(clipped), -np.log1p(-clipped), np.ones(clipped.size))
        )
    raise ValueError(f"unsupported calibration method: {method}")


def _fit_method(
    method: str,
    probabilities: np.ndarray,
    outcomes: np.ndarray,
    *,
    probability_clip: float,
    l2: float,
    initial_parameters: np.ndarray | None = None,
) -> dict[str, Any]:
    features = _method_features(method, probabilities, probability_clip)
    if method == "platt":
        prior = np.asarray([1.0, 0.0])
        penalties = np.asarray([l2, max(1e-6, l2 * 0.1)])
        constrained = (0,)
        names = ("slope", "intercept")
    else:
        # logit(p) = log(p) + -log(1-p), hence [1, 1, 0] is identity.
        prior = np.asarray([1.0, 1.0, 0.0])
        penalties = np.asarray([l2, l2, max(1e-6, l2 * 0.1)])
        constrained = (0, 1)
        names = ("alpha", "beta", "intercept")
    fitted = _fit_logistic_irls(
        features,
        outcomes,
        prior=prior,
        penalties=penalties,
        initial=initial_parameters,
        nonnegative_indices=constrained,
    )
    # A warm start is only a computational shortcut. If it ever gives the
    # optimizer trouble, retry from the immutable identity prior so behavior
    # remains fail-safe and statistically unchanged.
    if not fitted["ok"] and initial_parameters is not None:
        fitted = _fit_logistic_irls(
            features,
            outcomes,
            prior=prior,
            penalties=penalties,
            nonnegative_indices=constrained,
        )
    if not fitted["ok"]:
        return fitted
    parameters = np.asarray(fitted.pop("parameters"), dtype=float)
    if any(parameters[index] < -1e-12 for index in constrained):
        return {
            "ok": False,
            "reason": "non_monotone_fit_rejected",
            "iterations": fitted["iterations"],
        }
    return {
        **fitted,
        "parameters": {
            name: float(value) for name, value in zip(names, parameters, strict=True)
        },
        "parameter_vector": parameters,
        "monotone": True,
    }


def _apply_method(
    method: str,
    probability: float,
    parameters: np.ndarray,
    probability_clip: float,
) -> float:
    feature = _method_features(
        method, np.asarray([probability], dtype=float), probability_clip
    )
    transformed = float(_sigmoid(feature @ parameters)[0])
    return float(np.clip(transformed, probability_clip, 1.0 - probability_clip))


def _training_evidence(training: Sequence[Mapping[str, Any]]) -> dict[str, int | str | None]:
    positives = sum(int(row["outcome_up"] == 1) for row in training)
    negatives = len(training) - positives
    issue_dates = sorted({str(row["issue_date"]) for row in training})
    target_dates = sorted({str(row["target_date"]) for row in training})
    return {
        "calibration_samples": len(training),
        "calibration_issue_dates": len(issue_dates),
        "positive_outcomes": positives,
        "negative_outcomes": negatives,
        "training_first_issue_date": issue_dates[0] if issue_dates else None,
        "training_last_issue_date": issue_dates[-1] if issue_dates else None,
        "latest_mature_target_date": target_dates[-1] if target_dates else None,
    }


def _warmup_reasons(
    evidence: Mapping[str, Any],
    *,
    min_samples: int,
    min_issue_dates: int,
    min_class_samples: int,
) -> list[str]:
    reasons = []
    if int(evidence["calibration_samples"]) < min_samples:
        reasons.append(f"calibration_samples<{min_samples}")
    if int(evidence["calibration_issue_dates"]) < min_issue_dates:
        reasons.append(f"calibration_issue_dates<{min_issue_dates}")
    if int(evidence["positive_outcomes"]) < min_class_samples:
        reasons.append(f"positive_outcomes<{min_class_samples}")
    if int(evidence["negative_outcomes"]) < min_class_samples:
        reasons.append(f"negative_outcomes<{min_class_samples}")
    return reasons


def _fallback_challenger(
    raw_probability: float,
    evidence: Mapping[str, Any],
    reason: str,
) -> dict[str, Any]:
    return {
        "probability_up": raw_probability,
        "fit_status": "fallback_raw",
        "fallback": True,
        "fallback_reason": reason,
        "parameters": None,
        "monotone": None,
        **evidence,
    }


def walk_forward_calibrate(
    records: Iterable[Mapping[str, Any]],
    *,
    min_samples: int = DEFAULT_MIN_CALIBRATION_SAMPLES,
    min_issue_dates: int = DEFAULT_MIN_CALIBRATION_ISSUE_DATES,
    min_class_samples: int = DEFAULT_MIN_CLASS_SAMPLES,
    probability_clip: float = DEFAULT_PROBABILITY_CLIP,
    l2: float = DEFAULT_L2,
    reliability_bins: int = 10,
    warm_start: bool = True,
) -> dict[str, Any]:
    """Create identity, Platt, and beta probabilities in chronological order.

    Fits pool symbols but remain separate for each ``model_version`` and
    ``horizon_days``.  For issue date ``t``, training records must have a valid
    label and ``target_date < t``.  The strict inequality is intentional: all
    forecasts in the same issue-date batch are emitted before outcomes
    resolving on that date enter the next fit.
    """

    if min_samples < 1 or min_issue_dates < 1 or min_class_samples < 1:
        raise ValueError("minimum sample, issue-date, and class counts must be positive")
    if not 0.0 < probability_clip < 0.5:
        raise ValueError("probability_clip must be between 0 and 0.5")
    if not math.isfinite(l2) or l2 <= 0:
        raise ValueError("l2 must be a positive finite number")
    if reliability_bins < 2:
        raise ValueError("reliability_bins must be at least 2")

    canonical = [_canonical_record(record) for record in records]
    canonical.sort(
        key=lambda row: (
            row["issue_date"] is None,
            row["issue_date"] or "9999-12-31",
            row["model_version"],
            row["horizon_days"] or 0,
            row["symbol"],
            row["record_fingerprint"],
        )
    )
    seen_forecast_ids: set[str] = set()
    seen_forecast_units: set[tuple[Any, ...]] = set()
    for row in canonical:
        forecast_id = row.get("forecast_id")
        normalized_forecast_id = (
            str(forecast_id).strip() if forecast_id is not None else ""
        )
        forecast_unit = (
            row.get("model_version"),
            row.get("symbol"),
            row.get("horizon_days"),
            row.get("issue_date"),
        )
        if (
            normalized_forecast_id
            and normalized_forecast_id in seen_forecast_ids
        ) or forecast_unit in seen_forecast_units:
            raise ValueError(
                "duplicate forecast identity; calibration requires one first-issued "
                "row per forecast_id or model/symbol/horizon/issue_date"
            )
        if normalized_forecast_id:
            seen_forecast_ids.add(normalized_forecast_id)
        seen_forecast_units.add(forecast_unit)
    input_rows = []
    for row in canonical:
        payload = {key: value for key, value in row.items() if key != "record_fingerprint"}
        input_rows.append(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        )
    input_sha256 = sha256("\n".join(sorted(input_rows)).encode("ascii")).hexdigest()

    training_pools: defaultdict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in canonical:
        key = _group_key(row)
        if (
            key is not None
            and row["issue_date"] is not None
            and row["target_date"] is not None
            and row["target_date"] > row["issue_date"]
            and _explicit_symbol(row) is not None
            and row["raw_probability_up"] is not None
            and row["outcome_up"] is not None
        ):
            training_pools[key].append(row)
    target_dates: dict[tuple[str, int], list[str]] = {}
    for key, pool in training_pools.items():
        pool.sort(
            key=lambda row: (
                row["target_date"],
                row["issue_date"],
                row["symbol"],
                row["record_fingerprint"],
            )
        )
        target_dates[key] = [str(row["target_date"]) for row in pool]

    output: list[dict[str, Any]] = []
    fit_cache: dict[tuple[str, int, str], dict[str, Any]] = {}
    previous_fit: dict[tuple[str, int, str], np.ndarray] = {}
    for row in canonical:
        raw = row["raw_probability_up"]
        issue_date = row["issue_date"]
        key = _group_key(row)
        base_output = {
            **row,
            "research_only": True,
            "evaluation_role": "walk_forward_oos",
            "identity_probability_up": raw,
            "platt_probability_up": None,
            "beta_probability_up": None,
            "calibration_group": (
                {
                    "model_version": key[0],
                    "horizon_days": key[1],
                    "symbol_pooling": "cross_symbol",
                }
                if key is not None
                else None
            ),
        }
        if (
            raw is None
            or issue_date is None
            or key is None
            or _explicit_symbol(row) is None
        ):
            missing = []
            if raw is None:
                missing.append("valid_probability_up")
            if issue_date is None:
                missing.append("valid_issue_date")
            if _explicit_symbol(row) is None:
                missing.append("explicit_symbol")
            if key is None:
                if not isinstance(row.get("horizon_days"), int):
                    missing.append("valid_horizon_days")
                model_text = str(row.get("model_version") or "unknown").strip()
                if not model_text or model_text.lower() == "unknown":
                    missing.append("explicit_model_version")
            reason = "missing:" + ",".join(missing)
            base_output["calibration_status"] = "abstain"
            base_output["calibration_abstain_reason"] = reason
            base_output["challengers"] = {
                method: {
                    "probability_up": None,
                    "fit_status": "abstain",
                    "fallback": False,
                    "fallback_reason": reason,
                    "parameters": None,
                    "monotone": None,
                }
                for method in CHALLENGER_METHODS
            }
            output.append(base_output)
            continue

        cache_key = (key[0], key[1], issue_date)
        cached = fit_cache.get(cache_key)
        if cached is None:
            pool = training_pools.get(key, [])
            cutoff = bisect_left(target_dates.get(key, []), issue_date)
            training = pool[:cutoff]
            evidence = _training_evidence(training)
            reasons = _warmup_reasons(
                evidence,
                min_samples=min_samples,
                min_issue_dates=min_issue_dates,
                min_class_samples=min_class_samples,
            )
            method_fits: dict[str, Any] = {}
            if reasons:
                reason = ";".join(reasons)
                for method in CHALLENGER_METHODS:
                    method_fits[method] = {
                        "fit": None,
                        "fallback_reason": reason,
                    }
            else:
                train_probabilities = np.asarray(
                    [item["raw_probability_up"] for item in training], dtype=float
                )
                train_outcomes = np.asarray(
                    [item["outcome_up"] for item in training], dtype=float
                )
                for method in CHALLENGER_METHODS:
                    fit = _fit_method(
                        method,
                        train_probabilities,
                        train_outcomes,
                        probability_clip=probability_clip,
                        l2=l2,
                        initial_parameters=(
                            previous_fit.get((key[0], key[1], method))
                            if warm_start
                            else None
                        ),
                    )
                    if fit["ok"]:
                        previous_fit[(key[0], key[1], method)] = np.asarray(
                            fit["parameter_vector"], dtype=float
                        ).copy()
                    method_fits[method] = {
                        "fit": fit if fit["ok"] else None,
                        "fallback_reason": None if fit["ok"] else str(fit["reason"]),
                        "failed_fit": fit if not fit["ok"] else None,
                    }
            cached = {"evidence": evidence, "method_fits": method_fits}
            fit_cache[cache_key] = cached

        evidence = cached["evidence"]
        challengers: dict[str, dict[str, Any]] = {}
        for method in CHALLENGER_METHODS:
            fit_entry = cached["method_fits"][method]
            fit = fit_entry["fit"]
            if fit is None:
                challenger = _fallback_challenger(
                    raw, evidence, str(fit_entry["fallback_reason"])
                )
            else:
                calibrated = _apply_method(
                    method,
                    raw,
                    np.asarray(fit["parameter_vector"], dtype=float),
                    probability_clip,
                )
                challenger = {
                    "probability_up": calibrated,
                    "fit_status": "calibrated",
                    "fallback": False,
                    "fallback_reason": None,
                    "parameters": fit["parameters"],
                    "monotone": bool(fit["monotone"]),
                    "optimizer_iterations": int(fit["iterations"]),
                    **evidence,
                }
            challengers[method] = challenger
            base_output[f"{method}_probability_up"] = challenger["probability_up"]
        base_output["calibration_status"] = (
            "calibrated"
            if all(value["fit_status"] == "calibrated" for value in challengers.values())
            else "fallback_raw"
        )
        base_output["calibration_abstain_reason"] = None
        base_output["challengers"] = challengers
        output.append(base_output)

    comparisons = {
        method: paired_method_comparison(
            output, method=method, reliability_bins=reliability_bins
        )
        for method in CHALLENGER_METHODS
    }
    grouped_output: defaultdict[tuple[str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for row in output:
        key = _group_key(row)
        if key is not None:
            grouped_output[key].append(row)
    comparisons_by_group: dict[str, Any] = {}
    for (model_version, horizon), group_records in sorted(grouped_output.items()):
        label = f"{model_version}|horizon={horizon}"
        comparisons_by_group[label] = {
            "model_version": model_version,
            "horizon_days": horizon,
            "records": len(group_records),
            "methods": {
                method: paired_method_comparison(
                    group_records, method=method, reliability_bins=reliability_bins
                )
                for method in CHALLENGER_METHODS
            },
        }
    issue_values = sorted(
        {str(row["issue_date"]) for row in canonical if row["issue_date"] is not None}
    )
    target_values = sorted(
        {str(row["target_date"]) for row in canonical if row["target_date"] is not None}
    )
    training_cutoffs = sorted(
        {
            str(details["latest_mature_target_date"])
            for row in output
            for details in row.get("challengers", {}).values()
            if isinstance(details, Mapping)
            and details.get("latest_mature_target_date") is not None
        }
    )
    configuration_payload = {
        "calibrator_version": CALIBRATOR_VERSION,
        "methods": list(CHALLENGER_METHODS),
        "group_by": ["model_version", "horizon_days"],
        "cross_symbol_pooling": True,
        "maturity_rule": "target_date < current_issue_date",
        "same_issue_date_batched": True,
        "minimum_calibration_samples": min_samples,
        "minimum_calibration_issue_dates": min_issue_dates,
        "minimum_class_samples": min_class_samples,
        "probability_clip": probability_clip,
        "l2": l2,
        "reliability_bins": reliability_bins,
        "optimizer_warm_start": bool(warm_start),
    }
    configuration_sha256 = sha256(
        json.dumps(
            configuration_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).hexdigest()
    artifact_id = "cal_" + sha256(
        f"{CALIBRATOR_VERSION}:{input_sha256}:{configuration_sha256}".encode("ascii")
    ).hexdigest()[:24]
    return {
        "schema_version": SCHEMA_VERSION,
        "calibrator_version": CALIBRATOR_VERSION,
        "artifact_id": artifact_id,
        "research_only": True,
        "production_model_changed": False,
        "methods": ["identity", *CHALLENGER_METHODS],
        "policy": {
            "group_by": ["model_version", "horizon_days"],
            "cross_symbol_pooling": True,
            "maturity_rule": "target_date < current_issue_date",
            "same_issue_date_batched": True,
            "minimum_calibration_samples": min_samples,
            "minimum_calibration_issue_dates": min_issue_dates,
            "minimum_class_samples": min_class_samples,
            "probability_clip": probability_clip,
            "l2": l2,
            "optimizer_warm_start": bool(warm_start),
            "optimizer_warm_start_semantics": (
                "previous issue-date parameters initialize the same full-data objective"
            ),
            "configuration_sha256": configuration_sha256,
            "hyperparameter_selection": "caller_supplied_externally_unverified",
            "predeclaration_verified_by_module": False,
            "automatic_winner_selection": False,
            "automatic_production_promotion": False,
        },
        "artifact_provenance": {
            "artifact_id": artifact_id,
            "calibrator_version": CALIBRATOR_VERSION,
            "configuration_sha256": configuration_sha256,
            "input_records_sha256": input_sha256,
            "symbols": sorted({str(row["symbol"]) for row in canonical}),
            "model_versions": sorted({str(row["model_version"]) for row in canonical}),
            "horizons_days": sorted(
                {
                    int(row["horizon_days"])
                    for row in canonical
                    if row["horizon_days"] is not None
                }
            ),
            "issue_date_range": {
                "first": issue_values[0] if issue_values else None,
                "last": issue_values[-1] if issue_values else None,
            },
            "target_date_range": {
                "first": target_values[0] if target_values else None,
                "last": target_values[-1] if target_values else None,
            },
            "latest_training_cutoff": (
                training_cutoffs[-1] if training_cutoffs else None
            ),
            "training_cutoff_rule": "target_date strictly before each issue_date",
            "data_vintage": "inherited_from_input_replay",
        },
        "records_received": len(canonical),
        "records_emitted": len(output),
        "calibrated_records": sum(
            row["calibration_status"] == "calibrated" for row in output
        ),
        "fallback_records": sum(
            row["calibration_status"] == "fallback_raw" for row in output
        ),
        "abstained_records": sum(
            row["calibration_status"] == "abstain" for row in output
        ),
        "comparisons": comparisons,
        "comparisons_by_group": comparisons_by_group,
        "comparison_warning": (
            "Descriptive paired walk-forward results only. Predeclare one challenger "
            "and confirm an untouched evaluation protocol before a promotion gate. "
            "A per-date monotone mapping can still change pooled cross-date AUC and "
            "the probability>=0.5 decision policy; review both explicitly."
        ),
        "records": output,
    }


def _finite_probability(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0.0 <= number <= 1.0 else None


def _binary_metrics(probabilities: np.ndarray, outcomes: np.ndarray) -> dict[str, Any]:
    clipped = np.clip(probabilities, 1e-15, 1.0 - 1e-15)
    diagnostics = evaluate_binary_forecasts(
        probabilities.tolist(), outcomes.astype(int).tolist()
    )
    return {
        "observations": int(outcomes.size),
        "brier_score": float(np.mean((probabilities - outcomes) ** 2)),
        "log_loss": float(
            -np.mean(outcomes * np.log(clipped) + (1.0 - outcomes) * np.log1p(-clipped))
        ),
        "mean_probability": float(probabilities.mean()),
        "positive_rate": float(outcomes.mean()),
        "classification_threshold": diagnostics["classification_threshold"],
        "accuracy": diagnostics["accuracy"],
        "precision": diagnostics["precision"],
        "recall": diagnostics["recall"],
        "specificity": diagnostics["specificity"],
        "f1_score": diagnostics["f1_score"],
        "balanced_accuracy": diagnostics["balanced_accuracy"],
        "matthews_correlation_coefficient": diagnostics[
            "matthews_correlation_coefficient"
        ],
        "roc_auc": diagnostics["roc_auc"],
        "average_precision": diagnostics["average_precision"],
        "expected_calibration_error": diagnostics["expected_calibration_error"],
    }


def equal_mass_reliability(
    probabilities: Iterable[float], outcomes: Iterable[int], *, bins: int = 10
) -> list[dict[str, float | int]]:
    """Return deterministic equal-count reliability bins."""

    probs = np.asarray(list(probabilities), dtype=float)
    actual = np.asarray(list(outcomes), dtype=float)
    if probs.ndim != 1 or probs.size == 0 or probs.size != actual.size:
        raise ValueError("probabilities and outcomes must be non-empty equal-length vectors")
    if not np.isfinite(probs).all() or ((probs < 0) | (probs > 1)).any():
        raise ValueError("probabilities must be finite and between 0 and 1")
    if not np.isin(actual, (0.0, 1.0)).all():
        raise ValueError("outcomes must contain only 0 or 1")
    if bins < 2:
        raise ValueError("bins must be at least 2")
    order = np.argsort(probs, kind="mergesort")
    sorted_probs = probs[order]
    tie_groups: list[np.ndarray] = []
    start = 0
    while start < order.size:
        end = start + 1
        while end < order.size and sorted_probs[end] == sorted_probs[start]:
            end += 1
        tie_groups.append(order[start:end])
        start = end

    group_count = min(bins, len(tie_groups))
    groups: list[np.ndarray] = []
    position = 0
    for bin_index in range(group_count):
        bins_left = group_count - bin_index
        if bins_left == 1:
            take = len(tie_groups) - position
        else:
            maximum_take = len(tie_groups) - position - (bins_left - 1)
            remaining_size = sum(
                selected.size for selected in tie_groups[position:]
            )
            target_size = remaining_size / bins_left
            take = 1
            current_size = int(tie_groups[position].size)
            while take < maximum_take:
                next_size = current_size + int(tie_groups[position + take].size)
                if abs(next_size - target_size) > abs(current_size - target_size):
                    break
                current_size = next_size
                take += 1
        groups.append(np.concatenate(tie_groups[position : position + take]))
        position += take
    result = []
    for index, selected in enumerate(groups):
        selected_probs = probs[selected]
        selected_actual = actual[selected]
        result.append(
            {
                "bin": index,
                "count": int(selected.size),
                "min_probability": float(selected_probs.min()),
                "max_probability": float(selected_probs.max()),
                "mean_probability": float(selected_probs.mean()),
                "observed_rate": float(selected_actual.mean()),
                "calibration_gap": float(
                    selected_probs.mean() - selected_actual.mean()
                ),
            }
        )
    return result


def _calibration_intercept_slope(
    probabilities: np.ndarray, outcomes: np.ndarray
) -> dict[str, Any]:
    if outcomes.size < 10:
        return {"estimable": False, "reason": "observations<10", "intercept": None, "slope": None}
    positives = int(outcomes.sum())
    if positives == 0 or positives == outcomes.size:
        return {"estimable": False, "reason": "single_outcome_class", "intercept": None, "slope": None}
    features = _method_features("platt", probabilities, DEFAULT_PROBABILITY_CLIP)
    fit = _fit_logistic_irls(
        features,
        outcomes,
        prior=np.asarray([1.0, 0.0]),
        penalties=np.asarray([1e-6, 1e-6]),
    )
    if not fit["ok"]:
        return {
            "estimable": False,
            "reason": str(fit["reason"]),
            "intercept": None,
            "slope": None,
        }
    parameters = np.asarray(fit["parameters"], dtype=float)
    return {
        "estimable": True,
        "reason": None,
        "intercept": float(parameters[1]),
        "slope": float(parameters[0]),
        "estimator": "near-unpenalized logistic diagnostic",
    }


def paired_method_comparison(
    records: Iterable[Mapping[str, Any]],
    *,
    method: str,
    reliability_bins: int = 10,
) -> dict[str, Any]:
    """Compare one predeclared challenger with identity on identical OOS rows."""

    if method not in CHALLENGER_METHODS:
        raise ValueError(f"method must be one of {CHALLENGER_METHODS}")
    paired: list[tuple[Mapping[str, Any], float, float, float | None, int]] = []
    for row in records:
        challenger = row.get("challengers")
        details = challenger.get(method) if isinstance(challenger, Mapping) else None
        if not isinstance(details, Mapping) or details.get("fit_status") != "calibrated":
            continue
        raw = _finite_probability(row.get("identity_probability_up"))
        candidate = _finite_probability(details.get("probability_up"))
        baseline = _finite_probability(row.get("baseline_probability_up"))
        outcome = _outcome(row)
        if raw is not None and candidate is not None and outcome is not None:
            paired.append((row, raw, candidate, baseline, outcome))
    if not paired:
        return {
            "method": method,
            "status": "unverifiable",
            "paired_observations": 0,
            "paired_issue_dates": 0,
            "positive_outcomes": 0,
            "negative_outcomes": 0,
            "identity": None,
            "challenger": None,
            "forecast_time_baseline": None,
            "challenger_brier_skill_score": None,
            "candidate_minus_identity": None,
        }
    raw_values = np.asarray([item[1] for item in paired], dtype=float)
    candidate_values = np.asarray([item[2] for item in paired], dtype=float)
    outcomes = np.asarray([item[4] for item in paired], dtype=float)
    raw_metrics = _binary_metrics(raw_values, outcomes)
    candidate_metrics = _binary_metrics(candidate_values, outcomes)
    baseline_values = [item[3] for item in paired]
    baseline_metrics = None
    candidate_brier_skill_score = None
    if all(value is not None for value in baseline_values):
        baseline_metrics = _binary_metrics(
            np.asarray(baseline_values, dtype=float), outcomes
        )
        baseline_brier = float(baseline_metrics["brier_score"])
        if baseline_brier > 0.0:
            candidate_brier_skill_score = float(
                1.0 - float(candidate_metrics["brier_score"]) / baseline_brier
            )
    issue_dates = {
        normalized
        for item in paired
        if (
            normalized := _day(
                item[0].get("issue_date") or item[0].get("as_of")
            )
        )
        is not None
    }
    raw_metrics["calibration_intercept_slope"] = _calibration_intercept_slope(
        raw_values, outcomes
    )
    raw_metrics["equal_mass_reliability"] = equal_mass_reliability(
        raw_values, outcomes, bins=reliability_bins
    )
    candidate_metrics["calibration_intercept_slope"] = _calibration_intercept_slope(
        candidate_values, outcomes
    )
    candidate_metrics["equal_mass_reliability"] = equal_mass_reliability(
        candidate_values, outcomes, bins=reliability_bins
    )
    return {
        "method": method,
        "status": "descriptive_only",
        "paired_observations": len(paired),
        "paired_issue_dates": len(issue_dates),
        "positive_outcomes": int(outcomes.sum()),
        "negative_outcomes": int(outcomes.size - outcomes.sum()),
        "identity": raw_metrics,
        "challenger": candidate_metrics,
        "forecast_time_baseline": baseline_metrics,
        "challenger_brier_skill_score": candidate_brier_skill_score,
        "candidate_minus_identity": {
            "brier_score": float(
                candidate_metrics["brier_score"] - raw_metrics["brier_score"]
            ),
            "log_loss": float(
                candidate_metrics["log_loss"] - raw_metrics["log_loss"]
            ),
        },
        "winner_selected": False,
    }


def _paired_loss_advantage_by_issue_date(
    records: Iterable[Mapping[str, Any]], method: str, *, reference: str = "identity"
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    if reference not in {"identity", "forecast_time_baseline"}:
        raise ValueError("reference must be identity or forecast_time_baseline")
    daily_brier: defaultdict[str, list[float]] = defaultdict(list)
    daily_log_loss: defaultdict[str, list[float]] = defaultdict(list)
    for row in records:
        challengers = row.get("challengers")
        details = challengers.get(method) if isinstance(challengers, Mapping) else None
        if not isinstance(details, Mapping) or details.get("fit_status") != "calibrated":
            continue
        issue_date = _day(row.get("issue_date") or row.get("as_of"))
        raw = _finite_probability(
            row.get("identity_probability_up")
            if reference == "identity"
            else row.get("baseline_probability_up")
        )
        candidate = _finite_probability(details.get("probability_up"))
        outcome = _outcome(row)
        if issue_date is None or raw is None or candidate is None or outcome is None:
            continue
        raw_clipped = float(np.clip(raw, 1e-15, 1.0 - 1e-15))
        candidate_clipped = float(np.clip(candidate, 1e-15, 1.0 - 1e-15))
        raw_log = -(
            outcome * math.log(raw_clipped)
            + (1 - outcome) * math.log1p(-raw_clipped)
        )
        candidate_log = -(
            outcome * math.log(candidate_clipped)
            + (1 - outcome) * math.log1p(-candidate_clipped)
        )
        daily_brier[issue_date].append(
            (raw - outcome) ** 2 - (candidate - outcome) ** 2
        )
        daily_log_loss[issue_date].append(raw_log - candidate_log)
    dates = sorted(set(daily_brier) & set(daily_log_loss))
    return (
        np.asarray([np.mean(daily_brier[value]) for value in dates], dtype=float),
        np.asarray([np.mean(daily_log_loss[value]) for value in dates], dtype=float),
        dates,
    )


def _deterministic_block_mean_ci(
    values: np.ndarray,
    *,
    block_size: int,
    n_resamples: int,
    confidence_level: float,
    random_seed: int,
) -> dict[str, Any] | None:
    if values.size == 0:
        return None
    resolved_block_size = min(block_size, int(values.size))
    rng = np.random.default_rng(random_seed)
    blocks_needed = int(np.ceil(values.size / resolved_block_size))
    offsets = np.arange(resolved_block_size)
    estimates = np.empty(n_resamples, dtype=float)
    for sample_index in range(n_resamples):
        starts = rng.integers(0, values.size, size=blocks_needed)
        indices = ((starts[:, None] + offsets[None, :]) % values.size).reshape(-1)
        estimates[sample_index] = float(values[indices[: values.size]].mean())
    tail = (1.0 - confidence_level) / 2.0
    lower, upper = np.quantile(estimates, [tail, 1.0 - tail])
    return {
        "estimate": float(values.mean()),
        "lower": float(lower),
        "upper": float(upper),
        "confidence_level": confidence_level,
        "issue_dates": int(values.size),
        "block_size": resolved_block_size,
        "n_resamples": n_resamples,
        "random_seed": random_seed,
        "estimand": "equal-weighted mean of per-issue-date paired loss advantages",
    }


def paired_promotion_gate(
    records: Iterable[Mapping[str, Any]],
    *,
    method: str,
    evaluation_protocol_confirmed: bool = False,
    exact_vintage_confirmed: bool = False,
    decision_policy_impact_confirmed: bool = False,
    min_samples: int = DEFAULT_PROMOTION_MIN_SAMPLES,
    min_issue_dates: int = DEFAULT_PROMOTION_MIN_ISSUE_DATES,
    min_class_samples: int = DEFAULT_PROMOTION_MIN_CLASS_SAMPLES,
    min_brier_improvement: float = 0.0,
    log_loss_noninferiority_margin: float = 0.0,
    max_roc_auc_degradation: float = DEFAULT_MAX_ROC_AUC_DEGRADATION,
    block_size: int | None = None,
    bootstrap_samples: int = DEFAULT_PROMOTION_BOOTSTRAP_SAMPLES,
    confidence_level: float = DEFAULT_PROMOTION_CONFIDENCE_LEVEL,
    random_seed: int = 0,
) -> dict[str, Any]:
    """Fail-closed manual-review gate for one predeclared challenger.

    Passing this evidence gate never edits the production model. The caller
    must explicitly confirm a predeclared untouched protocol, exact historical
    data vintages, and a separate review of any threshold-policy impact.
    """

    if min_samples < DEFAULT_PROMOTION_MIN_SAMPLES:
        raise ValueError(
            f"formal promotion requires min_samples>={DEFAULT_PROMOTION_MIN_SAMPLES}"
        )
    if min_issue_dates < DEFAULT_PROMOTION_MIN_ISSUE_DATES:
        raise ValueError(
            "formal promotion requires "
            f"min_issue_dates>={DEFAULT_PROMOTION_MIN_ISSUE_DATES}"
        )
    if min_class_samples < DEFAULT_PROMOTION_MIN_CLASS_SAMPLES:
        raise ValueError(
            "formal promotion requires "
            f"min_class_samples>={DEFAULT_PROMOTION_MIN_CLASS_SAMPLES}"
        )
    if (
        min_brier_improvement < 0
        or log_loss_noninferiority_margin < 0
        or max_roc_auc_degradation < 0
    ):
        raise ValueError("promotion margins cannot be negative")
    if log_loss_noninferiority_margin != 0.0:
        raise ValueError("formal promotion v1 fixes log-loss noninferiority margin at 0")
    if max_roc_auc_degradation > DEFAULT_MAX_ROC_AUC_DEGRADATION:
        raise ValueError(
            "formal promotion cannot loosen maximum ROC-AUC degradation above "
            f"{DEFAULT_MAX_ROC_AUC_DEGRADATION}"
        )
    if bootstrap_samples != DEFAULT_PROMOTION_BOOTSTRAP_SAMPLES:
        raise ValueError(
            "formal promotion fixes bootstrap_samples at "
            f"{DEFAULT_PROMOTION_BOOTSTRAP_SAMPLES}"
        )
    if confidence_level != DEFAULT_PROMOTION_CONFIDENCE_LEVEL:
        raise ValueError(
            "formal promotion fixes confidence_level at "
            f"{DEFAULT_PROMOTION_CONFIDENCE_LEVEL}"
        )
    if random_seed != 0:
        raise ValueError("formal promotion fixes random_seed at 0")
    supplied = list(records)
    formal_rows: list[Mapping[str, Any]] = []
    paired_rows_seen = 0
    group_keys: set[tuple[str, int]] = set()
    paired_forecast_ids: set[str] = set()
    paired_forecast_ids_complete = True
    paired_forecast_units: set[tuple[str, str, int, str]] = set()
    paired_forecast_units_unique = True
    for row in supplied:
        challengers = row.get("challengers")
        details = challengers.get(method) if isinstance(challengers, Mapping) else None
        if not isinstance(details, Mapping) or details.get("fit_status") != "calibrated":
            continue
        raw = _finite_probability(row.get("identity_probability_up"))
        candidate = _finite_probability(details.get("probability_up"))
        outcome = _outcome(row)
        if raw is None or candidate is None or outcome is None:
            continue
        paired_rows_seen += 1
        forecast_id = str(row.get("forecast_id") or "").strip()
        if not forecast_id or forecast_id in paired_forecast_ids:
            paired_forecast_ids_complete = False
        else:
            paired_forecast_ids.add(forecast_id)
        key = _group_key(row)
        normalized_issue_date = _day(row.get("issue_date") or row.get("as_of"))
        symbol = _explicit_symbol(row)
        if key is None or normalized_issue_date is None or symbol is None:
            continue
        forecast_unit = (
            key[0],
            symbol,
            key[1],
            normalized_issue_date,
        )
        if forecast_unit in paired_forecast_units:
            paired_forecast_units_unique = False
        else:
            paired_forecast_units.add(forecast_unit)
        formal_rows.append(row)
        group_keys.add(key)
    paired_input_complete = paired_rows_seen == len(formal_rows)
    required_block_size = max(
        7, 2 * max((key[1] for key in group_keys), default=1)
    )
    if block_size is not None and block_size != required_block_size:
        raise ValueError(
            "formal promotion fixes block_size at max(7, 2*horizon)="
            f"{required_block_size}"
        )
    resolved_block_size = block_size or required_block_size
    comparison = paired_method_comparison(formal_rows, method=method)
    brier_advantage, log_loss_advantage, bootstrap_dates = (
        _paired_loss_advantage_by_issue_date(formal_rows, method)
    )
    baseline_brier_advantage, _, baseline_bootstrap_dates = (
        _paired_loss_advantage_by_issue_date(
            formal_rows, method, reference="forecast_time_baseline"
        )
    )
    brier_ci = _deterministic_block_mean_ci(
        brier_advantage,
        block_size=resolved_block_size,
        n_resamples=bootstrap_samples,
        confidence_level=confidence_level,
        random_seed=random_seed,
    )
    log_loss_ci = _deterministic_block_mean_ci(
        log_loss_advantage,
        block_size=resolved_block_size,
        n_resamples=bootstrap_samples,
        confidence_level=confidence_level,
        random_seed=random_seed + 1,
    )
    baseline_brier_ci = _deterministic_block_mean_ci(
        baseline_brier_advantage,
        block_size=resolved_block_size,
        n_resamples=bootstrap_samples,
        confidence_level=confidence_level,
        random_seed=random_seed + 2,
    )
    evidence_checks = {
        "evaluation_protocol_confirmed": bool(evaluation_protocol_confirmed),
        "exact_vintage_confirmed": bool(exact_vintage_confirmed),
        "decision_policy_impact_confirmed": bool(decision_policy_impact_confirmed),
        "all_paired_rows_have_valid_scope_and_issue_date": paired_input_complete,
        "all_paired_rows_have_unique_forecast_id": paired_forecast_ids_complete,
        "all_paired_rows_are_unique_forecast_units": paired_forecast_units_unique,
        "single_model_horizon_group": paired_input_complete and len(group_keys) == 1,
        "minimum_samples": comparison["paired_observations"] >= min_samples,
        "minimum_issue_dates": comparison["paired_issue_dates"] >= min_issue_dates,
        "minimum_positive_outcomes": comparison["positive_outcomes"] >= min_class_samples,
        "minimum_negative_outcomes": comparison["negative_outcomes"] >= min_class_samples,
    }
    if comparison["identity"] is None or comparison["challenger"] is None:
        scoring_checks = {
            "brier_improves": False,
            "log_loss_noninferior": False,
            "brier_advantage_ci": False,
            "log_loss_noninferiority_ci": False,
            "positive_brier_skill_vs_forecast_time_baseline": False,
            "baseline_brier_advantage_ci": False,
            "roc_auc_noninferior": False,
        }
    else:
        difference = comparison["candidate_minus_identity"]
        scoring_checks = {
            "brier_improves": (
                -float(difference["brier_score"]) > min_brier_improvement
            ),
            "log_loss_noninferior": (
                float(difference["log_loss"]) <= log_loss_noninferiority_margin
            ),
            "brier_advantage_ci": (
                brier_ci is not None
                and float(brier_ci["lower"]) > min_brier_improvement
            ),
            "log_loss_noninferiority_ci": (
                log_loss_ci is not None
                and float(log_loss_ci["lower"])
                >= -log_loss_noninferiority_margin
            ),
            "positive_brier_skill_vs_forecast_time_baseline": (
                comparison["challenger_brier_skill_score"] is not None
                and float(comparison["challenger_brier_skill_score"]) > 0.0
            ),
            "baseline_brier_advantage_ci": (
                baseline_brier_ci is not None
                and float(baseline_brier_ci["lower"]) > 0.0
            ),
            "roc_auc_noninferior": (
                comparison["identity"].get("roc_auc") is not None
                and comparison["challenger"].get("roc_auc") is not None
                and float(comparison["challenger"]["roc_auc"])
                - float(comparison["identity"]["roc_auc"])
                >= -max_roc_auc_degradation
            ),
        }
    all_checks = {**evidence_checks, **scoring_checks}
    enough_evidence = all(
        value
        for key, value in evidence_checks.items()
        if key
        not in {
            "evaluation_protocol_confirmed",
            "exact_vintage_confirmed",
            "decision_policy_impact_confirmed",
        }
    )
    gate_passed = all(all_checks.values())
    if gate_passed:
        decision = "eligible_for_manual_review"
    elif not enough_evidence:
        decision = "insufficient_evidence"
    else:
        decision = "keep_identity"
    policy_payload = {
        "version": "calibration-promotion-v1",
        "method": method,
        "minimum_samples": min_samples,
        "minimum_issue_dates": min_issue_dates,
        "minimum_class_samples": min_class_samples,
        "minimum_brier_improvement": min_brier_improvement,
        "log_loss_noninferiority_margin": log_loss_noninferiority_margin,
        "maximum_roc_auc_degradation": max_roc_auc_degradation,
        "block_size": resolved_block_size,
        "bootstrap_samples": bootstrap_samples,
        "confidence_level": confidence_level,
        "random_seed": random_seed,
        "paired_loss_cluster": "normalized_issue_date",
    }
    policy_sha256 = sha256(
        json.dumps(
            policy_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).hexdigest()
    return {
        "method": method,
        "gate_policy": policy_payload,
        "gate_policy_sha256": policy_sha256,
        "decision": decision,
        "gate_passed": gate_passed,
        "checks": all_checks,
        "thresholds": {
            "minimum_samples": min_samples,
            "minimum_issue_dates": min_issue_dates,
            "minimum_class_samples": min_class_samples,
            "minimum_brier_improvement": min_brier_improvement,
            "log_loss_noninferiority_margin": log_loss_noninferiority_margin,
            "maximum_roc_auc_degradation": max_roc_auc_degradation,
            "block_size": resolved_block_size,
            "bootstrap_samples": bootstrap_samples,
            "confidence_level": confidence_level,
            "random_seed": random_seed,
        },
        "comparison": comparison,
        "issue_date_block_bootstrap": {
            "issue_dates": bootstrap_dates,
            "brier_advantage_identity_minus_challenger": brier_ci,
            "log_loss_advantage_identity_minus_challenger": log_loss_ci,
            "baseline_issue_dates": baseline_bootstrap_dates,
            "brier_advantage_forecast_time_baseline_minus_challenger": (
                baseline_brier_ci
            ),
        },
        "production_model_changed": False,
        "warning": (
            "Passing means eligible for human review only; this function never "
            "changes src.forecasting.MODEL_VERSION or production routing."
        ),
    }


def _load_replay_records(path: Path) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    source_metadata: dict[str, Any] = {}
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, Mapping):
        records = payload.get("replay_records")
        if records is None and isinstance(payload.get("records"), list):
            records = payload["records"]
        provenance = payload.get("provenance")
        if isinstance(provenance, Mapping):
            source_metadata["replay_provenance"] = dict(provenance)
        for key in ("symbols_requested", "horizons_days", "warnings"):
            if key in payload:
                source_metadata[key] = payload[key]
    else:
        records = None
    if not isinstance(records, list) or not all(isinstance(row, Mapping) for row in records):
        raise ValueError("input must be a record list or contain replay_records")
    return records, source_metadata


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=resolved.parent,
            prefix=f".{resolved.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, resolved)
    except Exception:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Leakage-safe walk-forward Platt and beta calibration challengers."
    )
    parser.add_argument("--input", required=True, type=Path, help="forecast replay JSON")
    parser.add_argument("--output", required=True, type=Path, help="atomic report JSON path")
    parser.add_argument("--min-samples", type=int, default=DEFAULT_MIN_CALIBRATION_SAMPLES)
    parser.add_argument(
        "--min-issue-dates", type=int, default=DEFAULT_MIN_CALIBRATION_ISSUE_DATES
    )
    parser.add_argument(
        "--min-class-samples", type=int, default=DEFAULT_MIN_CLASS_SAMPLES
    )
    parser.add_argument("--probability-clip", type=float, default=DEFAULT_PROBABILITY_CLIP)
    parser.add_argument("--l2", type=float, default=DEFAULT_L2)
    parser.add_argument("--reliability-bins", type=int, default=10)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        records, source_metadata = _load_replay_records(args.input)
        report = walk_forward_calibrate(
            records,
            min_samples=args.min_samples,
            min_issue_dates=args.min_issue_dates,
            min_class_samples=args.min_class_samples,
            probability_clip=args.probability_clip,
            l2=args.l2,
            reliability_bins=args.reliability_bins,
        )
        report["artifact_provenance"]["input_file"] = str(args.input.resolve())
        report["artifact_provenance"]["input_file_sha256"] = _file_sha256(args.input)
        report["artifact_provenance"]["source_replay"] = source_metadata
        _atomic_json_write(args.output, report)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(
        json.dumps(
            {
                "schema_version": report["schema_version"],
                "records_received": report["records_received"],
                "calibrated_records": report["calibrated_records"],
                "fallback_records": report["fallback_records"],
                "abstained_records": report["abstained_records"],
                "production_model_changed": False,
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through CLI tests.
    raise SystemExit(main())
