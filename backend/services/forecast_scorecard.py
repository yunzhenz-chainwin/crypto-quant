"""Honest model track records built from the immutable forecast ledger."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import math
from typing import Any, Iterable

from backend.services import app_db
from src.forecast_evaluation import evaluate_replay_records
from src.forecasting import (
    MIN_OBSERVATIONS as MODEL_MIN_OBSERVATIONS,
    MIN_OUTCOMES as MODEL_MIN_OUTCOMES,
    MIN_READY_CONFIDENCE,
    MODEL_VERSION as HISTORICAL_BASELINE_MODEL_VERSION,
)


MIN_EVALUATED_OBSERVATIONS = 1000
MIN_EVALUATED_ISSUE_DATES = 180
CLASSIFICATION_THRESHOLD = 0.5
CALIBRATION_REVIEW_ECE = 0.05
REGIME_MA_DAYS = 60
REGIME_RETURN_DAYS = 20


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
    promotion_scope_reason: str = "aggregate diagnostic view",
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
            "actual": promotion_scope_reason,
            "required": (
                "one explicit model_version and one horizon over the full "
                "unfiltered symbol universe and full history"
            ),
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


def _progress(actual: int, required: int) -> float:
    return round(min(max(actual / required, 0.0), 1.0), 4)


def _assessment_reason(
    code: str,
    title: str,
    detail: str,
    severity: str,
    evidence: dict | None = None,
) -> dict:
    return {
        "code": code,
        "title": title,
        "detail": detail,
        "severity": severity,
        "evidence": evidence or {},
    }


def _assessment_action(
    *,
    priority: int,
    parameter: str,
    current: Any,
    suggested: Any,
    action: str,
    rationale: str,
    evidence: dict | None = None,
    status: str = "diagnostic_only",
) -> dict:
    priority_level = (
        "high"
        if status in {"required", "required_for_formal_evaluation"}
        else "medium"
        if status in {"research_candidate", "investigate_only"}
        else "low"
    )
    return {
        "priority": priority_level,
        "priority_level": priority_level,
        "order": priority,
        "parameter": parameter,
        "current": current,
        "suggested": suggested,
        "action": action,
        "rationale": rationale,
        "evidence": evidence or {},
        "status": status,
        "requires_validation": True,
        "automatic_change": False,
    }


def _build_performance_assessment(
    *,
    overall: dict,
    by_horizon: list[dict],
    filters: dict,
    provenance: dict,
) -> dict:
    """Explain what the observed scorecard can and cannot support.

    This is intentionally a deterministic interpretation of the queried
    ledger.  It never tunes a model, selects a winner, or turns a descriptive
    metric into a production claim.
    """
    observations = int(overall.get("observations") or 0)
    issue_dates = int(overall.get("issue_dates") or 0)
    resolved_count = int(overall.get("resolved_count") or 0)
    unscorable_count = int(overall.get("unscorable_count") or 0)
    pending = int(provenance.get("pending") or 0)
    observation_progress = _progress(
        observations, MIN_EVALUATED_OBSERVATIONS,
    )
    issue_date_progress = _progress(issue_dates, MIN_EVALUATED_ISSUE_DATES)
    progress_ratio = min(observation_progress, issue_date_progress)

    if observations == 0:
        maturity_level = "none"
        maturity_note = "尚無成熟且可評分的預測結果，所有準確度結論都不可判定。"
    elif overall.get("status") != "evaluated":
        maturity_level = "accumulating"
        maturity_note = "資料仍在累積；目前指標只能描述樣本，不能作正式上線結論。"
    else:
        maturity_level = "sufficient_for_scorecard_gate"
        maturity_note = "已達成績單最低資料量，仍須同時通過基準、區間與來源門檻。"

    formal_scope = (
        filters.get("model_version") is not None
        and filters.get("horizon") is not None
        and filters.get("symbol") is None
        and filters.get("window") is None
    )
    gates = {
        str(gate.get("gate")): gate
        for gate in overall.get("promotion_gates") or []
        if isinstance(gate, dict)
    }
    all_gates_pass = bool(gates) and all(
        gate.get("status") == "pass" for gate in gates.values()
    )
    release_review_eligible = bool(
        overall.get("status") == "evaluated"
        and formal_scope
        and all_gates_pass
    )

    metrics = overall.get("metrics") if isinstance(overall.get("metrics"), dict) else {}
    skill = _number(metrics.get("brier_skill_score"))
    auc = _number(metrics.get("roc_auc"))
    recall = _number(metrics.get("recall"))
    specificity = _number(metrics.get("specificity"))
    ece = _number(metrics.get("expected_calibration_error"))
    threshold = _number(metrics.get("classification_threshold"))
    threshold = CLASSIFICATION_THRESHOLD if threshold is None else threshold
    is_historical_baseline = (
        filters.get("model_version") == HISTORICAL_BASELINE_MODEL_VERSION
    )
    calibration_current = (
        "raw" if is_historical_baseline else "not_declared_in_scorecard"
    )
    regime_current = (
        {"ma_days": REGIME_MA_DAYS, "return_days": REGIME_RETURN_DAYS}
        if is_historical_baseline
        else {
            "status": "not_declared_in_scorecard",
            "historical_baseline_reference": {
                "model_version": HISTORICAL_BASELINE_MODEL_VERSION,
                "ma_days": REGIME_MA_DAYS,
                "return_days": REGIME_RETURN_DAYS,
            },
        }
    )
    brier_lower = _ci_bound(
        overall.get("brier_advantage_ci"),
        ("lower", "low", "lower_bound", "ci_low"),
    )
    supports_probability_skill_claim = bool(
        release_review_eligible
        and skill is not None
        and skill > 0
        and brier_lower is not None
        and brier_lower > 0
    )

    if not metrics or skill is None:
        performance_level = "unverifiable"
    elif skill < 0:
        performance_level = "below_baseline"
    elif skill == 0:
        performance_level = "indistinguishable_from_baseline"
    elif supports_probability_skill_claim:
        performance_level = "probability_skill_supported"
    else:
        performance_level = "descriptive_positive"

    scorable_ratio = observations / resolved_count if resolved_count else 0.0
    trust_score = progress_ratio * scorable_ratio
    trust_score *= 1.0 if formal_scope else 0.75
    trust_score *= 1.0 if provenance.get("release_eligible") else 0.75
    if overall.get("status") == "evaluated" and brier_lower is None:
        trust_score *= 0.85
    trust_score = round(min(max(trust_score, 0.0), 1.0), 3)
    if observations == 0:
        trust_level = "unverifiable"
    elif trust_score < 0.5:
        trust_level = "low"
    elif trust_score < 0.9:
        trust_level = "medium"
    else:
        trust_level = "high"

    if observations == 0:
        verdict = "unverifiable"
        headline = "目前沒有成熟證據，不能判斷模型是否準確或可信。"
    elif overall.get("status") != "evaluated":
        verdict = "insufficient_evidence"
        headline = "已有觀測結果，但樣本量或跨日期覆蓋仍不足。"
    elif not formal_scope:
        verdict = "diagnostic_only"
        headline = "這是篩選後的診斷切片，不能取代完整正式評估。"
    elif skill is None or skill <= 0:
        verdict = "not_better_than_baseline"
        headline = "目前沒有證據顯示機率預測優於預測當下可得的基準。"
    elif not supports_probability_skill_claim:
        verdict = "promising_not_confirmed"
        headline = "點估計較佳，但統計區間或其他正式門檻尚未完整通過。"
    else:
        verdict = "release_review_eligible"
        headline = "正式證據門檻已通過，可進入人工發布審查；不代表保證未來準確。"

    reasons: list[dict] = []
    if observations == 0:
        reasons.append(_assessment_reason(
            "no_matured_outcomes",
            "沒有成熟預測結果",
            "沒有可同時取得預測機率、基準機率與真實結果的紀錄。",
            "blocker",
            {"observations": observations, "pending": pending},
        ))
    if observations < MIN_EVALUATED_OBSERVATIONS:
        reasons.append(_assessment_reason(
            "insufficient_observations",
            "成熟觀測數不足",
            "先累積成熟 outcome；不應為了較快通過而降低正式證據門檻。",
            "blocker",
            {
                "actual": observations,
                "required": MIN_EVALUATED_OBSERVATIONS,
                "gap": MIN_EVALUATED_OBSERVATIONS - observations,
            },
        ))
    if issue_dates < MIN_EVALUATED_ISSUE_DATES:
        reasons.append(_assessment_reason(
            "insufficient_issue_dates",
            "獨立發行日期不足",
            "跨日期覆蓋不足時，單一市場階段可能主導結果。",
            "blocker",
            {
                "actual": issue_dates,
                "required": MIN_EVALUATED_ISSUE_DATES,
                "gap": MIN_EVALUATED_ISSUE_DATES - issue_dates,
            },
        ))
    if not formal_scope:
        reasons.append(_assessment_reason(
            "diagnostic_scope",
            "目前查詢只適合診斷",
            "horizon 與 window 是評估篩選條件，不是會自動提高準確率的調參旋鈕。",
            "warning",
            {"filters": filters},
        ))
    if not provenance.get("release_eligible"):
        reasons.append(_assessment_reason(
            "legacy_provenance",
            "包含研究用舊版來源",
            "舊版 ledger 可供相容性研究，但不符合正式發布來源門檻。",
            "blocker",
            {"include_legacy": provenance.get("include_legacy")},
        ))
    if unscorable_count:
        reasons.append(_assessment_reason(
            "unscorable_resolved_records",
            "部分已解決紀錄無法評分",
            "必須先修復缺失或無效欄位，不能只排除不利紀錄。",
            "blocker",
            {
                "unscorable_count": unscorable_count,
                "resolved_count": resolved_count,
            },
        ))
    if metrics and skill is not None:
        if skill < 0:
            reasons.append(_assessment_reason(
                "brier_skill_below_baseline",
                "機率品質低於時點基準",
                "Brier skill score 為負，代表此樣本中的機率誤差大於預測當下可得基準。",
                "blocker",
                {"brier_skill_score": skill},
            ))
        elif skill == 0:
            reasons.append(_assessment_reason(
                "brier_skill_not_improved",
                "機率品質未優於基準",
                "Brier skill score 為零，尚未顯示增量價值。",
                "blocker",
                {"brier_skill_score": skill},
            ))
        elif brier_lower is None or brier_lower <= 0:
            reasons.append(_assessment_reason(
                "brier_advantage_not_confirmed",
                "較佳點估計尚未被區間確認",
                "Brier skill 點估計為正，但優勢區間下界尚未大於零。",
                "warning",
                {
                    "brier_skill_score": skill,
                    "brier_advantage_ci_lower": brier_lower,
                },
            ))
        elif supports_probability_skill_claim:
            reasons.append(_assessment_reason(
                "probability_skill_supported",
                "機率預測優勢通過正式證據門檻",
                "Brier skill 與其區間門檻均通過；仍需人工發布審查與持續監控。",
                "info",
                {
                    "brier_skill_score": skill,
                    "brier_advantage_ci_lower": brier_lower,
                },
            ))
    if metrics and auc is None:
        reasons.append(_assessment_reason(
            "ranking_metric_not_estimable",
            "ROC-AUC 目前不可估計",
            "樣本可能只有單一結果類別；null 必須維持不可判定，不能補成 0 或 0.5。",
            "warning",
            {"roc_auc": None},
        ))
    elif auc is not None and auc <= 0.52:
        reasons.append(_assessment_reason(
            "weak_observed_ranking",
            "排序辨識力偏弱",
            "目前 ROC-AUC 接近或低於隨機排序；這是觀測警訊，不是未來保證。",
            "warning",
            {"roc_auc": auc},
        ))
    threshold_imbalanced = bool(
        recall is not None
        and specificity is not None
        and abs(recall - specificity) >= 0.15
    )
    if threshold_imbalanced:
        reasons.append(_assessment_reason(
            "classification_threshold_tradeoff",
            "固定分類門檻存在取捨",
            "recall 與 specificity 差距較大；任何門檻變更都必須在訓練／驗證期決定，再用未碰過資料確認。",
            "warning",
            {
                "classification_threshold": threshold,
                "recall": recall,
                "specificity": specificity,
            },
        ))
    if observations and overall.get("coverage") == 0:
        reasons.append(_assessment_reason(
            "no_ready_forecasts",
            "成熟樣本中沒有 ready 預測",
            "應先檢查 abstain 原因與資料充分性，不可只為提高 coverage 而放寬信心門檻。",
            "warning",
            {
                "ready_count": overall.get("ready_count"),
                "coverage": overall.get("coverage"),
            },
        ))

    actions: list[dict] = []
    priority = 1
    if (
        observations < MIN_EVALUATED_OBSERVATIONS
        or issue_dates < MIN_EVALUATED_ISSUE_DATES
    ):
        actions.append(_assessment_action(
            priority=priority,
            parameter="minimum_evidence",
            current={"observations": observations, "issue_dates": issue_dates},
            suggested={
                "minimum_observations": MIN_EVALUATED_OBSERVATIONS,
                "minimum_issue_dates": MIN_EVALUATED_ISSUE_DATES,
                "policy": "collect_before_parameter_tuning",
            },
            action="collect_matured_outcomes",
            rationale="這是目前最優先工作；先補足跨日期成熟結果，再判斷是否值得調模型。",
            evidence={
                "observation_gap": max(
                    MIN_EVALUATED_OBSERVATIONS - observations, 0,
                ),
                "issue_date_gap": max(
                    MIN_EVALUATED_ISSUE_DATES - issue_dates, 0,
                ),
                "pending": pending,
            },
            status="required",
        ))
        priority += 1
    if filters.get("model_version") is None:
        actions.append(_assessment_action(
            priority=priority,
            parameter="model_version",
            current=None,
            suggested="one_explicit_registered_model_version",
            action="fix_formal_model_scope",
            rationale="混合模型版本只能做總覽；正式判斷必須鎖定單一不可變版本。",
            status="required_for_formal_evaluation",
        ))
        priority += 1
    if filters.get("horizon") is None:
        horizon_evidence = [
            {
                "horizon_days": row.get("horizon_days"),
                "observations": row.get("observations"),
                "brier_skill_score": (
                    (row.get("metrics") or {}).get("brier_skill_score")
                    if isinstance(row.get("metrics"), dict) else None
                ),
                "roc_auc": (
                    (row.get("metrics") or {}).get("roc_auc")
                    if isinstance(row.get("metrics"), dict) else None
                ),
            }
            for row in by_horizon
        ]
        actions.append(_assessment_action(
            priority=priority,
            parameter="horizon",
            current=None,
            suggested={
                "formal_evaluation": [1, 5, 10],
                "one_horizon_per_scorecard": True,
            },
            action="evaluate_horizons_separately",
            rationale="1、5、10 日是不同預測目標；不得用同一評估集挑出看起來最好的 horizon 後宣稱提升準確率。",
            evidence={"observed_by_horizon": horizon_evidence},
            status="required_for_formal_evaluation",
        ))
        priority += 1
    if filters.get("symbol") is not None:
        actions.append(_assessment_action(
            priority=priority,
            parameter="symbol",
            current=filters.get("symbol"),
            suggested=None,
            action="remove_symbol_filter_for_formal_gate",
            rationale="單一幣種切片可找問題，但不能取代完整適用範圍的正式證據。",
            status="required_for_formal_evaluation",
        ))
        priority += 1
    if filters.get("window") is not None:
        actions.append(_assessment_action(
            priority=priority,
            parameter="window",
            current=filters.get("window"),
            suggested=None,
            action="use_full_history_for_formal_gate",
            rationale="window 只用於漂移診斷；正式門檻使用全歷史，避免挑選有利期間。",
            status="required_for_formal_evaluation",
        ))
        priority += 1
    calibration_review = bool(
        metrics
        and (
            (skill is not None and skill <= 0)
            or (ece is not None and ece > CALIBRATION_REVIEW_ECE)
        )
    )
    if calibration_review:
        actions.append(_assessment_action(
            priority=priority,
            parameter="calibration",
            current=calibration_current,
            suggested={
                "challengers": ["platt", "beta"],
                "validation": "walk_forward_out_of_sample",
                "promotion": "lower_brier_and_log_loss_with_auc_noninferiority",
            },
            action="run_calibration_challengers",
            rationale="校準器只能改善機率可信度，不能修復排序能力；需以新版本、走勢外資料驗證後才可替換。",
            evidence={
                "brier_skill_score": skill,
                "expected_calibration_error": ece,
                "log_loss": metrics.get("log_loss"),
                "baseline_log_loss": metrics.get("baseline_log_loss"),
            },
            status="research_candidate",
        ))
        priority += 1
    if threshold_imbalanced:
        direction = "lower_to_test" if recall < specificity else "raise_to_test"
        actions.append(_assessment_action(
            priority=priority,
            parameter="classification_threshold",
            current=threshold,
            suggested={
                "direction": direction,
                "method": "predeclared_walk_forward_search",
                "production_probability_unchanged": True,
            },
            action="validate_decision_threshold_offline",
            rationale="0.5 是分類評估政策，不是機率模型本身；調整會交換 recall 與 specificity，不能用目前測試集直接定值。",
            evidence={"recall": recall, "specificity": specificity},
            status="research_candidate",
        ))
        priority += 1
    if metrics and (
        (auc is not None and auc <= 0.52)
        or (skill is not None and skill <= 0)
    ):
        actions.append(_assessment_action(
            priority=priority,
            parameter="regime_definition",
            current=regime_current,
            suggested={
                "action": "register_predeclared_challenger_versions",
                "validation": "walk_forward_out_of_sample",
            },
            action="test_regime_or_feature_challengers",
            rationale="排序偏弱時應研究新訊號或 regime 定義；任何 MA／報酬視窗改動都必須成為新模型版本，不能就地覆寫。",
            evidence={"roc_auc": auc, "brier_skill_score": skill},
            status="research_candidate",
        ))
        priority += 1
    if observations and overall.get("coverage") == 0:
        actions.append(_assessment_action(
            priority=priority,
            parameter="forecast_readiness_policy",
            current={
                "minimum_price_observations": MODEL_MIN_OBSERVATIONS,
                "minimum_regime_outcomes": MODEL_MIN_OUTCOMES,
                "minimum_ready_confidence": MIN_READY_CONFIDENCE,
            },
            suggested="keep_current_until_abstention_root_cause_is_validated",
            action="audit_abstention_causes",
            rationale="先判斷是資料不足、罕見 regime 或信心不足；不可只為增加 ready 數量而降低門檻。",
            evidence={
                "ready_count": overall.get("ready_count"),
                "coverage": overall.get("coverage"),
            },
            status="investigate_only",
        ))
        priority += 1
    if not actions:
        actions.append(_assessment_action(
            priority=priority,
            parameter="monitoring_window",
            current=None,
            suggested="predeclared_rolling_drift_reviews",
            action="continue_shadow_monitoring",
            rationale="保留完整歷史作正式門檻，另以事先約定的 rolling window 監測漂移。",
            status="monitor",
        ))

    metric_names = (
        "accuracy", "precision", "recall", "f1_score", "roc_auc",
        "average_precision", "brier_score", "brier_skill_score",
        "expected_calibration_error",
    )
    return {
        "schema_version": "forecast-scorecard-assessment-v1",
        "verdict": verdict,
        "trust_level": trust_level,
        "trust_score": trust_score,
        "trust_score_basis": "evidence_completeness_not_probability",
        "performance_level": performance_level,
        "headline": headline,
        "supports_probability_skill_claim": supports_probability_skill_claim,
        "release_review_eligible": release_review_eligible,
        "data_maturity": {
            "level": maturity_level,
            "matured_observations": observations,
            "issue_dates": issue_dates,
            "unresolved": pending,
            "minimum_observations": MIN_EVALUATED_OBSERVATIONS,
            "minimum_issue_dates": MIN_EVALUATED_ISSUE_DATES,
            "observation_progress": observation_progress,
            "issue_date_progress": issue_date_progress,
            "progress_ratio": progress_ratio,
            "note": maturity_note,
        },
        "observed_metrics": {
            name: metrics.get(name) for name in metric_names
        },
        "explainability": {
            "method": "historical_evidence",
            "shap": (
                "not_applicable" if is_historical_baseline else "not_available"
            ),
            "reason": (
                "歷史經驗分布與 regime 條件基準沒有可供 SHAP 分解的已訓練"
                "特徵模型；不得捏造 SHAP 數值。"
                if is_historical_baseline
                else "scorecard ledger 未保存此模型的特徵矩陣或 attribution；"
                "因此無法從本查詢產生 SHAP，且不得捏造數值。"
            ),
        },
        "parameter_context": {
            "model_readiness": {
                "applies_to_model_version": HISTORICAL_BASELINE_MODEL_VERSION,
                "minimum_price_observations": MODEL_MIN_OBSERVATIONS,
                "minimum_regime_outcomes": MODEL_MIN_OUTCOMES,
                "minimum_ready_confidence": MIN_READY_CONFIDENCE,
            },
            "scorecard_evidence_policy": {
                "minimum_observations": MIN_EVALUATED_OBSERVATIONS,
                "minimum_issue_dates": MIN_EVALUATED_ISSUE_DATES,
            },
            "classification_policy": {
                "threshold": threshold,
                "role": "evaluation_only",
            },
            "regime_definition": {
                "current": regime_current,
                "change_control": "new_model_version_and_walk_forward_validation",
            },
            "calibration": {
                "current": calibration_current,
                "challengers": ["platt", "beta"],
                "ece_review_trigger": CALIBRATION_REVIEW_ECE,
                "ece_trigger_role": "diagnostic_not_release_gate",
            },
            "evaluation_filters": {
                "horizon": filters.get("horizon"),
                "window": filters.get("window"),
                "role": "diagnostic_scope_not_accuracy_controls",
            },
        },
        "reasons": reasons,
        "recommended_actions": actions,
        "disclaimer": (
            "此評估只解讀查詢當下已成熟 ledger 證據；不會自動調參、訓練、部署，"
            "也不保證未來市場表現。"
        ),
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

    overall_scope_issues = []
    if normalized_model is None:
        overall_scope_issues.append("model_version is not explicit")
    if horizon is None:
        overall_scope_issues.append("horizon is not explicit")
    if normalized_symbol is not None:
        overall_scope_issues.append("symbol-filtered diagnostic slice")
    if window is not None:
        overall_scope_issues.append("window-filtered diagnostic slice")
    overall = _group_score(
        records,
        include_legacy=bool(include_legacy),
        promotion_scope=not overall_scope_issues,
        promotion_scope_reason="; ".join(overall_scope_issues),
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
                promotion_scope=(
                    normalized_model is not None
                    and normalized_symbol is None
                    and window is None
                ),
                promotion_scope_reason="; ".join(
                    reason for reason in (
                        "model_version is not explicit" if normalized_model is None else "",
                        "symbol-filtered diagnostic slice" if normalized_symbol is not None else "",
                        "window-filtered diagnostic slice" if window is not None else "",
                    )
                    if reason
                ),
            ),
        }
        for days in horizon_values
    ]
    generated = now or datetime.now(timezone.utc)
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    generated_at = generated.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    filters_payload = {
        "horizon": int(horizon) if horizon is not None else None,
        "model_version": normalized_model,
        "symbol": normalized_symbol,
        "window": int(window) if window is not None else None,
        "include_legacy": bool(include_legacy),
    }
    provenance_payload = {
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
    }
    assessment = _build_performance_assessment(
        overall=overall,
        by_horizon=by_horizon,
        filters=filters_payload,
        provenance=provenance_payload,
    )
    return {
        "status": overall["status"],
        "filters": filters_payload,
        "provenance": provenance_payload,
        "overall": overall,
        "by_horizon": by_horizon,
        "assessment": assessment,
        "generated_at": generated_at,
        "data_as_of": data_as_of_day.isoformat() if data_as_of_day else None,
        "warnings": (
            ["legacy ledger rows are research-only and fail the v2 release provenance gate"]
            if include_legacy else []
        ),
    }
