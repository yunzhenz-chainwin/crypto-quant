"""Honest model track records built from the immutable forecast ledger."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import math
from typing import Any, Iterable

from backend.services import app_db
from src.forecast_evaluation import evaluate_replay_records


MIN_EVALUATED_OBSERVATIONS = 1000
MIN_EVALUATED_ISSUE_DATES = 180


def _day(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _logical_key(row: dict) -> tuple:
    """One forecast opportunity, independent of same-day data corrections."""
    return (
        str(row.get("symbol") or "").upper(),
        int(row.get("horizon_days") or 0),
        str(row.get("as_of") or ""),
        str(row.get("model_version") or ""),
        int(row.get("schema_version") or 0),
    )


def _first_issue_rank(row: dict) -> tuple:
    # Database created_at is the actual append/publication order. generated_at
    # is only a deterministic tie-breaker because it is supplied by the model.
    return (
        str(row.get("snapshot_created_at") or "9999-12-31 23:59:59"),
        int(row.get("snapshot_rowid") or 2**63 - 1),
        str(row.get("generated_at") or "9999-12-31T23:59:59Z"),
        int(row.get("schema_version") or 99),
        str(row.get("forecast_id") or ""),
    )


def _row_identity(row: dict) -> str:
    return f"{int(row.get('schema_version') or 0)}:{row.get('forecast_id') or ''}"


def deduplicate_forecast_ledger(rows: Iterable[dict]) -> list[dict]:
    """Keep the first-issued snapshot for each logical forecast opportunity.

    Deduplication happens before unresolved rows are removed.  A later revised
    input therefore cannot temporarily replace the original forecast merely
    because its outcome happened to be resolved first.
    """
    first: dict[tuple, dict] = {}
    for row in rows:
        key = _logical_key(row)
        if not all(key):
            continue
        incumbent = first.get(key)
        if incumbent is None or _first_issue_rank(row) < _first_issue_rank(incumbent):
            first[key] = row
    return sorted(
        first.values(),
        key=lambda row: (
            str(row.get("as_of") or ""), str(row.get("symbol") or ""),
            int(row.get("horizon_days") or 0), str(row.get("model_version") or ""),
        ),
    )


def _resolved_value(row: dict) -> float | None:
    outcome = row.get("outcome") or {}
    return _number(outcome.get("realized_return_pct", row.get("realized_return_pct")))


def _target_day(row: dict) -> date | None:
    outcome = row.get("outcome") or {}
    return _day(outcome.get("target_as_of", row.get("target_as_of")))


def _forecast_time_baselines(rows: list[dict]) -> dict[str, float]:
    """Beta(1,1) expanding up-rate using only outcomes mature by issue time."""
    # Multiple model versions can predict the same market event. Count the
    # realized event once when forming the common, model-independent baseline.
    event_first: dict[tuple, dict] = {}
    for row in rows:
        realized = _resolved_value(row)
        target = _target_day(row)
        issue = _day(row.get("as_of"))
        if realized is None or target is None or issue is None:
            continue
        key = (
            str(row.get("symbol") or "").upper(),
            int(row.get("horizon_days") or 0),
            issue.isoformat(),
        )
        incumbent = event_first.get(key)
        if incumbent is None or _first_issue_rank(row) < _first_issue_rank(incumbent):
            event_first[key] = row

    events: dict[tuple[str, int], list[tuple[date, int]]] = defaultdict(list)
    for row in event_first.values():
        target = _target_day(row)
        realized = _resolved_value(row)
        if target is not None and realized is not None:
            group = (str(row["symbol"]).upper(), int(row["horizon_days"]))
            # Flat belongs to the non-up class because the forecast event is r > 0.
            events[group].append((target, 1 if realized > 0 else 0))
    for values in events.values():
        values.sort(key=lambda item: item[0])

    forecasts: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("outcome") is not None and _day(row.get("as_of")) is not None:
            group = (str(row["symbol"]).upper(), int(row["horizon_days"]))
            forecasts[group].append(row)

    baseline_by_id: dict[str, float] = {}
    for group, group_rows in forecasts.items():
        group_rows.sort(key=lambda row: (_day(row["as_of"]), _first_issue_rank(row)))
        matured = events.get(group, [])
        event_index = 0
        prior_up = 0
        prior_n = 0
        cursor = 0
        while cursor < len(group_rows):
            issue_day = _day(group_rows[cursor]["as_of"])
            assert issue_day is not None
            while event_index < len(matured) and matured[event_index][0] <= issue_day:
                prior_up += matured[event_index][1]
                prior_n += 1
                event_index += 1
            probability = (prior_up + 1.0) / (prior_n + 2.0)
            while cursor < len(group_rows) and _day(group_rows[cursor]["as_of"]) == issue_day:
                baseline_by_id[_row_identity(group_rows[cursor])] = probability
                cursor += 1
    return baseline_by_id


def _replay_record(row: dict, baseline: float | None) -> dict:
    snapshot = row.get("snapshot") or {}
    outcome = row.get("outcome") or {}
    probabilities = snapshot.get("probabilities") or {}
    quantiles = snapshot.get("return_quantiles_pct") or {}
    realized = _resolved_value(row)
    probability_up = _number(probabilities.get("up", snapshot.get("probability_up")))
    q10 = _number(quantiles.get("q10", snapshot.get("return_q10_pct")))
    q50 = _number(quantiles.get("q50", snapshot.get("return_q50_pct")))
    q90 = _number(quantiles.get("q90", snapshot.get("return_q90_pct")))
    if not (
        q10 is not None and q50 is not None and q90 is not None
        and q10 <= q50 <= q90
    ):
        q10 = q50 = q90 = None
    return {
        "forecast_id": str(row["forecast_id"]),
        "symbol": str(row["symbol"]).upper(),
        "horizon_days": int(row["horizon_days"]),
        "model_version": str(row["model_version"]),
        "ledger_schema_version": int(row.get("schema_version") or 0),
        "legacy": int(row.get("schema_version") or 0) == 1,
        "issue_date": str(row["as_of"])[:10],
        "as_of": str(row["as_of"])[:10],
        "target_as_of": str(outcome.get("target_as_of", row.get("target_as_of")) or "")[:10],
        "resolved_at": outcome.get("resolved_at", row.get("resolved_at")),
        "status": str(snapshot.get("status", row.get("status") or "unknown")),
        "probability_up": probability_up,
        "outcome_up": None if realized is None else (1 if realized > 0 else 0),
        "baseline_probability_up": baseline,
        "return_q10_pct": q10,
        "return_q50_pct": q50,
        "return_q90_pct": q90,
        "realized_return_pct": realized,
    }


def _build_replay_bundle(
    *,
    horizon: int | None = None,
    model_version: str | None = None,
    symbol: str | None = None,
    include_legacy: bool = False,
) -> dict:
    """Select canonical ledger rows and build point-in-time replay records."""
    # Do not prefilter model_version: the expanding market baseline is shared
    # across models and must use all prior unique mature market outcomes.
    ledger = app_db.load_forecast_ledger(
        horizon_days=horizon,
        symbol=symbol,
        include_legacy=include_legacy,
    )
    canonical = deduplicate_forecast_ledger(ledger)
    baselines = _forecast_time_baselines(canonical)
    selected_ledger = [
        row for row in ledger
        if model_version is None or row.get("model_version") == model_version
    ]
    selected_canonical = [
        row for row in canonical
        if model_version is None or row.get("model_version") == model_version
    ]
    records = []
    for row in selected_canonical:
        if row.get("outcome") is None:
            continue
        baseline = baselines.get(_row_identity(row))
        records.append(_replay_record(row, baseline))
    return {
        "records": records,
        "snapshots": len(selected_ledger),
        "canonical_snapshots": len(selected_canonical),
        "revisions_excluded": len(selected_ledger) - len(selected_canonical),
        "pending": sum(1 for row in selected_canonical if row.get("outcome") is None),
        "v2_snapshots": sum(
            1 for row in selected_ledger if int(row.get("schema_version") or 0) == 2
        ),
        "legacy_snapshots": sum(
            1 for row in selected_ledger if int(row.get("schema_version") or 0) == 1
        ),
    }


def build_replay_records(
    *,
    horizon: int | None = None,
    model_version: str | None = None,
    symbol: str | None = None,
    include_legacy: bool = False,
) -> list[dict]:
    """Build point-in-time replay records before applying any score window."""
    return _build_replay_bundle(
        horizon=horizon,
        model_version=model_version,
        symbol=symbol,
        include_legacy=include_legacy,
    )["records"]


def _scoreable(records: list[dict]) -> list[dict]:
    scored = []
    for row in records:
        probability = _number(row.get("probability_up"))
        baseline = _number(row.get("baseline_probability_up"))
        issue_day = _day(row.get("issue_date"))
        target_day = _day(row.get("target_as_of"))
        if (
            probability is not None and 0 <= probability <= 1
            and baseline is not None and 0 <= baseline <= 1
            and row.get("outcome_up") in (0, 1)
            and issue_day is not None and target_day is not None
            and target_day > issue_day
        ):
            scored.append(row)
    return scored


def _ci_bound(ci: Any, names: tuple[str, ...]) -> float | None:
    if not isinstance(ci, dict):
        return None
    for name in names:
        value = _number(ci.get(name))
        if value is not None:
            return value
    return None


def _promotion_gates(
    *,
    resolved_count: int,
    observations: int,
    issue_dates: int,
    evidence_status: str,
    metrics: dict | None,
    brier_ci: dict | None,
    include_legacy: bool,
) -> list[dict]:
    gates = [
        {
            "gate": "v2_only_provenance",
            "status": "failed" if include_legacy else "pass",
            "actual": not include_legacy,
            "required": True,
        },
        {
            "gate": "all_resolved_scorable",
            "status": "pass" if observations == resolved_count else "failed",
            "actual": observations,
            "required": resolved_count,
        },
        {
            "gate": "minimum_observations",
            "status": "pass" if observations >= MIN_EVALUATED_OBSERVATIONS else "failed",
            "actual": observations,
            "required": MIN_EVALUATED_OBSERVATIONS,
        },
        {
            "gate": "minimum_issue_dates",
            "status": "pass" if issue_dates >= MIN_EVALUATED_ISSUE_DATES else "failed",
            "actual": issue_dates,
            "required": MIN_EVALUATED_ISSUE_DATES,
        },
    ]
    if evidence_status != "evaluated" or not metrics:
        gates.extend([
            {"gate": "positive_brier_skill", "status": "not_testable", "actual": None, "required": "> 0"},
            {"gate": "brier_advantage_ci", "status": "not_testable", "actual": brier_ci, "required": "lower > 0"},
        ])
        return gates

    skill = _number(metrics.get("brier_skill_score"))
    gates.append({
        "gate": "positive_brier_skill",
        "status": "pass" if skill is not None and skill > 0 else "failed",
        "actual": skill,
        "required": "> 0",
    })
    lower = _ci_bound(brier_ci, ("lower", "low", "lower_bound", "ci_low"))
    gates.append({
        "gate": "brier_advantage_ci",
        "status": "not_testable" if lower is None else ("pass" if lower > 0 else "failed"),
        "actual": brier_ci,
        "required": "lower > 0",
    })
    return gates


def _group_score(
    records: list[dict],
    *,
    include_legacy: bool = False,
    promotion_scope: bool = True,
) -> dict:
    scored = _scoreable(records)
    issue_values = sorted({row["issue_date"] for row in scored if _day(row.get("issue_date"))})
    observations = len(scored)
    issue_dates = len(issue_values)
    if not records:
        status = "unverifiable"
    elif observations < MIN_EVALUATED_OBSERVATIONS or issue_dates < MIN_EVALUATED_ISSUE_DATES:
        status = "insufficient_evidence"
    else:
        status = "evaluated"

    horizons = [int(row["horizon_days"]) for row in scored]
    block_size = max(7, 2 * max(horizons)) if horizons else 7
    evaluation = (
        evaluate_replay_records(
            scored,
            block_size=block_size,
            bootstrap_samples=2000,
            random_seed=20260721,
        )
        if scored else {}
    )
    metrics = evaluation.get("overall") if evaluation else None
    intervals = evaluation.get("intervals") if evaluation else None
    brier_ci = evaluation.get("brier_advantage_ci") if evaluation else None
    ready_count = sum(1 for row in scored if str(row.get("status")).lower() == "ready")
    resolved_count = len(records)
    promotion_gates = (
        _promotion_gates(
            resolved_count=resolved_count,
            observations=observations,
            issue_dates=issue_dates,
            evidence_status=status,
            metrics=metrics,
            brier_ci=brier_ci,
            include_legacy=include_legacy,
        )
        if promotion_scope
        else [{
            "gate": "single_model_horizon_scope",
            "status": "not_applicable",
            "actual": "aggregate diagnostic view",
            "required": "one explicit model_version and one horizon",
        }]
    )
    return {
        "status": status,
        "resolved_count": resolved_count,
        "observations": observations,
        "unscorable_count": resolved_count - observations,
        "issue_dates": issue_dates,
        "date_range": {
            "start": issue_values[0] if issue_values else None,
            "end": issue_values[-1] if issue_values else None,
        },
        "ready_count": ready_count,
        "coverage": (ready_count / observations) if observations else None,
        "metrics": metrics,
        "intervals": intervals,
        "brier_advantage_ci": brier_ci,
        "promotion_gates": promotion_gates,
    }


def build_forecast_scorecard(
    *,
    horizon: int | None = None,
    model_version: str | None = None,
    symbol: str | None = None,
    window: int | None = None,
    include_legacy: bool = False,
    now: datetime | None = None,
) -> dict:
    """Return an on-demand scorecard; no result is persisted or invented."""
    if horizon is not None and int(horizon) not in (1, 5, 10):
        raise ValueError("forecast horizon must be 1, 5, or 10 days")
    if window is not None and int(window) < 1:
        raise ValueError("window must be a positive number of calendar days")

    normalized_symbol = str(symbol).upper() if symbol else None
    normalized_model = str(model_version) if model_version else None
    bundle = _build_replay_bundle(
        horizon=horizon,
        model_version=normalized_model,
        symbol=normalized_symbol,
        include_legacy=bool(include_legacy),
    )
    records = bundle["records"]
    target_days = [_day(row.get("target_as_of")) for row in records]
    target_days = [value for value in target_days if value is not None]
    data_as_of_day = max(target_days) if target_days else None
    if window is not None and data_as_of_day is not None:
        cutoff = data_as_of_day - timedelta(days=int(window) - 1)
        records = [
            row for row in records
            if _day(row.get("target_as_of")) is not None
            and cutoff <= _day(row["target_as_of"]) <= data_as_of_day
        ]

    overall = _group_score(
        records,
        include_legacy=bool(include_legacy),
        promotion_scope=normalized_model is not None and horizon is not None,
    )
    grouped: dict[int, list[dict]] = defaultdict(list)
    for row in records:
        grouped[int(row["horizon_days"])].append(row)
    horizon_values = [int(horizon)] if horizon is not None else sorted(grouped)
    by_horizon = [
        {
            "horizon_days": days,
            **_group_score(
                grouped.get(days, []),
                include_legacy=bool(include_legacy),
                promotion_scope=normalized_model is not None,
            ),
        }
        for days in horizon_values
    ]
    generated = now or datetime.now(timezone.utc)
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    generated_at = generated.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "status": overall["status"],
        "filters": {
            "horizon": int(horizon) if horizon is not None else None,
            "model_version": normalized_model,
            "symbol": normalized_symbol,
            "window": int(window) if window is not None else None,
            "include_legacy": bool(include_legacy),
        },
        "provenance": {
            "snapshot_tables": (
                ["forecast_snapshot_v2", "forecast_snapshot"]
                if include_legacy else ["forecast_snapshot_v2"]
            ),
            "outcome_tables": (
                ["forecast_outcome_v2", "forecast_outcome"]
                if include_legacy else ["forecast_outcome_v2"]
            ),
            "selection_rule": "first_issued_per_symbol_horizon_asof_model_and_schema",
            "baseline": "beta_1_1_expanding_prior_mature_symbol_horizon_outcomes",
            "include_legacy": bool(include_legacy),
            "release_eligible": not bool(include_legacy),
            "snapshots": bundle["snapshots"],
            "canonical_snapshots": bundle["canonical_snapshots"],
            "revisions_excluded": bundle["revisions_excluded"],
            "pending": bundle["pending"],
            "v2_snapshots": bundle["v2_snapshots"],
            "legacy_snapshots": bundle["legacy_snapshots"],
        },
        "overall": overall,
        "by_horizon": by_horizon,
        "generated_at": generated_at,
        "data_as_of": data_as_of_day.isoformat() if data_as_of_day else None,
        "warnings": (
            ["legacy ledger rows are research-only and fail the v2 release provenance gate"]
            if include_legacy else []
        ),
    }
