from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import random

import pytest

from src.forecast_calibration import (
    equal_mass_reliability,
    main,
    paired_promotion_gate,
    walk_forward_calibrate,
)


def _row(
    index: int,
    *,
    issue: date,
    probability: float,
    outcome: int,
    target_offset: int = 1,
    symbol: str = "BTCUSDT",
    model_version: str = "research-v1",
    horizon: int = 1,
    baseline_probability: float = 0.5,
) -> dict:
    return {
        "forecast_id": f"fc_{index}_{symbol}_{model_version}_h{horizon}",
        "symbol": symbol,
        "model_version": model_version,
        "horizon_days": horizon,
        "issue_date": issue.isoformat(),
        "target_date": (issue + timedelta(days=target_offset)).isoformat(),
        "probability_up": probability,
        "baseline_probability_up": baseline_probability,
        "outcome_up": outcome,
    }


def _alternating_rows(count: int, *, constant_probability: float | None = None) -> list[dict]:
    start = date(2025, 1, 1)
    return [
        _row(
            index,
            issue=start + timedelta(days=index),
            probability=(
                constant_probability
                if constant_probability is not None
                else (0.8 if index % 2 else 0.2)
            ),
            outcome=index % 2,
        )
        for index in range(count)
    ]


def _small_report(rows: list[dict]) -> dict:
    return walk_forward_calibrate(
        rows,
        min_samples=10,
        min_issue_dates=10,
        min_class_samples=2,
        l2=0.5,
    )


def test_walk_forward_warmup_falls_back_with_explicit_evidence():
    report = _small_report(_alternating_rows(20))
    before_warmup = report["records"][10]
    after_warmup = report["records"][11]

    assert before_warmup["calibration_status"] == "fallback_raw"
    assert "calibration_samples<10" in before_warmup["challengers"]["platt"]["fallback_reason"]
    assert before_warmup["platt_probability_up"] == before_warmup["identity_probability_up"]
    assert after_warmup["calibration_status"] == "calibrated"
    assert after_warmup["challengers"]["platt"]["calibration_samples"] == 10
    assert after_warmup["challengers"]["platt"]["calibration_issue_dates"] == 10
    assert after_warmup["challengers"]["platt"]["latest_mature_target_date"] < after_warmup["issue_date"]
    assert report["production_model_changed"] is False
    assert report["policy"]["automatic_winner_selection"] is False
    assert report["artifact_id"].startswith("cal_")
    assert len(report["artifact_provenance"]["configuration_sha256"]) == 64
    assert report["policy"]["predeclaration_verified_by_module"] is False


def test_future_label_mutation_cannot_change_an_earlier_calibration():
    rows = _alternating_rows(45)
    cutoff = date(2025, 1, 26).isoformat()
    original = _small_report(rows)
    mutated_rows = []
    for row in rows:
        changed = dict(row)
        if changed["target_date"] >= cutoff:
            changed["outcome_up"] = 1 - changed["outcome_up"]
        mutated_rows.append(changed)
    mutated = _small_report(mutated_rows)

    def protected(report: dict) -> list[tuple]:
        return [
            (
                row["forecast_id"],
                row["platt_probability_up"],
                row["beta_probability_up"],
                row["challengers"]["platt"].get("parameters"),
                row["challengers"]["beta"].get("parameters"),
            )
            for row in report["records"]
            if row["issue_date"] <= cutoff
        ]

    assert protected(original) == protected(mutated)


def test_same_issue_batch_does_not_consume_outcomes_resolving_that_day():
    rows = _alternating_rows(20)
    issue = date(2025, 1, 21)
    # These outcomes resolve exactly on the new batch's issue day.  Mutating
    # them must not alter any forecast emitted in that batch.
    for offset, probability in enumerate((0.1, 0.5, 0.9), start=100):
        rows.append(
            _row(
                offset,
                issue=issue,
                probability=probability,
                outcome=offset % 2,
                symbol=f"BATCH{offset}",
            )
        )
    first = _small_report(rows)
    mutated = [dict(row) for row in rows]
    for row in mutated:
        if row["target_date"] == issue.isoformat():
            row["outcome_up"] = 1 - row["outcome_up"]
    second = _small_report(mutated)

    def batch(report: dict) -> list[tuple[float, float]]:
        return sorted(
            (row["platt_probability_up"], row["beta_probability_up"])
            for row in report["records"]
            if row["issue_date"] == issue.isoformat()
        )

    assert batch(first) == batch(second)


def test_output_is_deterministic_and_independent_of_input_order():
    rows = _alternating_rows(40)
    shuffled = list(rows)
    random.Random(9182).shuffle(shuffled)

    assert _small_report(rows) == _small_report(shuffled)


def test_warm_start_matches_cold_start_probabilities():
    rows = _alternating_rows(55)
    warm = walk_forward_calibrate(
        rows,
        min_samples=10,
        min_issue_dates=10,
        min_class_samples=2,
        l2=0.5,
        warm_start=True,
    )
    cold = walk_forward_calibrate(
        rows,
        min_samples=10,
        min_issue_dates=10,
        min_class_samples=2,
        l2=0.5,
        warm_start=False,
    )

    assert [row["forecast_id"] for row in warm["records"]] == [
        row["forecast_id"] for row in cold["records"]
    ]
    for warm_row, cold_row in zip(warm["records"], cold["records"], strict=True):
        assert warm_row["platt_probability_up"] == pytest.approx(
            cold_row["platt_probability_up"], abs=1e-8
        )
        assert warm_row["beta_probability_up"] == pytest.approx(
            cold_row["beta_probability_up"], abs=1e-8
        )


def test_synthetic_overconfidence_is_improved_without_current_label_leakage():
    start = date(2024, 1, 1)
    rows = []
    for index in range(360):
        high = index % 2 == 0
        within_group = index // 2
        outcome = int(within_group % 4 != 0) if high else int(within_group % 4 == 0)
        rows.append(
            _row(
                index,
                issue=start + timedelta(days=index),
                probability=0.99 if high else 0.01,
                outcome=outcome,
            )
        )

    report = walk_forward_calibrate(
        rows,
        min_samples=80,
        min_issue_dates=60,
        min_class_samples=20,
        l2=0.5,
    )

    for method in ("platt", "beta"):
        comparison = report["comparisons"][method]
        assert comparison["paired_observations"] > 200
        assert comparison["candidate_minus_identity"]["brier_score"] < -0.03
        assert comparison["candidate_minus_identity"]["log_loss"] < -0.3
        assert comparison["winner_selected"] is False


def test_constant_probability_is_stable_and_single_label_fails_closed():
    constant = _small_report(_alternating_rows(40, constant_probability=0.5))
    final = constant["records"][-1]
    assert final["calibration_status"] == "calibrated"
    assert 0.0 < final["platt_probability_up"] < 1.0
    assert 0.0 < final["beta_probability_up"] < 1.0
    assert final["challengers"]["platt"]["parameters"]["slope"] >= 0.0
    assert final["challengers"]["beta"]["parameters"]["alpha"] >= 0.0
    assert final["challengers"]["beta"]["parameters"]["beta"] >= 0.0

    one_class = _alternating_rows(40)
    for row in one_class:
        row["outcome_up"] = 1
    fallback = _small_report(one_class)["records"][-1]
    assert fallback["calibration_status"] == "fallback_raw"
    assert "negative_outcomes<2" in fallback["challengers"]["beta"]["fallback_reason"]


def test_monotone_constraints_preserve_probability_ranking():
    rows = _alternating_rows(40)
    issue = date(2025, 2, 15)
    for offset, probability in enumerate((0.01, 0.2, 0.5, 0.8, 0.99), start=100):
        rows.append(
            _row(
                offset,
                issue=issue,
                probability=probability,
                outcome=offset % 2,
                symbol=f"RANK{offset}",
            )
        )
    report = _small_report(rows)
    batch = sorted(
        (row["identity_probability_up"], row)
        for row in report["records"]
        if row["issue_date"] == issue.isoformat()
    )

    for method in ("platt", "beta"):
        transformed = [row[f"{method}_probability_up"] for _, row in batch]
        assert transformed == sorted(transformed)
        assert all(row["challengers"][method]["monotone"] for _, row in batch)


def test_promotion_gate_rejects_a_challenger_that_worsens_paired_scores():
    start = date(2026, 1, 1)
    records = []
    for index in range(1000):
        outcome = index % 2
        raw = 0.9 if outcome else 0.1
        bad = 1.0 - raw
        records.append(
            {
                "forecast_id": str(index),
                "symbol": "BTCUSDT",
                "model_version": "research-v1",
                "horizon_days": 1,
                "issue_date": (start + timedelta(days=index)).isoformat(),
                "outcome_up": outcome,
                "identity_probability_up": raw,
                "baseline_probability_up": 0.5,
                "challengers": {
                    "platt": {
                        "fit_status": "calibrated",
                        "probability_up": bad,
                    }
                },
            }
        )

    gate = paired_promotion_gate(
        records,
        method="platt",
        evaluation_protocol_confirmed=True,
        exact_vintage_confirmed=True,
        decision_policy_impact_confirmed=True,
    )

    assert gate["decision"] == "keep_identity"
    assert gate["gate_passed"] is False
    assert gate["checks"]["brier_improves"] is False
    assert gate["checks"]["log_loss_noninferior"] is False
    assert gate["production_model_changed"] is False


def test_promotion_gate_requires_predeclared_untouched_protocol():
    report = _small_report(_alternating_rows(80))
    gate = paired_promotion_gate(
        report["records"],
        method="platt",
        evaluation_protocol_confirmed=False,
    )

    assert gate["checks"]["evaluation_protocol_confirmed"] is False
    assert gate["checks"]["exact_vintage_confirmed"] is False
    assert gate["checks"]["decision_policy_impact_confirmed"] is False
    assert gate["gate_passed"] is False
    assert gate["production_model_changed"] is False
    assert len(gate["gate_policy_sha256"]) == 64


def test_promotion_gate_blocks_brier_gain_that_collapses_global_auc():
    start = date(2025, 1, 1)
    records = []
    for index in range(1000):
        outcome = index % 2
        records.append(
            {
                "forecast_id": str(index),
                "symbol": "BTCUSDT",
                "model_version": "research-v1",
                "horizon_days": 1,
                "issue_date": (start + timedelta(days=index)).isoformat(),
                "outcome_up": outcome,
                "identity_probability_up": 0.9 if outcome else 0.8,
                "baseline_probability_up": 0.6,
                "challengers": {
                    "platt": {
                        "fit_status": "calibrated",
                        "probability_up": 0.5,
                    }
                },
            }
        )

    gate = paired_promotion_gate(
        records,
        method="platt",
        evaluation_protocol_confirmed=True,
        exact_vintage_confirmed=True,
        decision_policy_impact_confirmed=True,
    )

    assert gate["checks"]["brier_improves"] is True
    assert gate["checks"]["positive_brier_skill_vs_forecast_time_baseline"] is True
    assert gate["checks"]["baseline_brier_advantage_ci"] is True
    assert gate["checks"]["roc_auc_noninferior"] is False
    assert gate["gate_passed"] is False
    assert gate["decision"] == "keep_identity"


def test_equal_mass_reliability_reports_all_observations():
    bins = equal_mass_reliability(
        [0.1, 0.2, 0.3, 0.7, 0.8, 0.9],
        [0, 0, 1, 0, 1, 1],
        bins=3,
    )

    assert len(bins) == 3
    assert sum(item["count"] for item in bins) == 6
    assert bins[0]["mean_probability"] == pytest.approx(0.15)
    assert bins[-1]["observed_rate"] == 1.0


def test_equal_mass_reliability_never_splits_probability_ties():
    first = equal_mass_reliability(
        [0.1, 0.1, 0.1, 0.9, 0.9],
        [1, 0, 0, 1, 0],
        bins=3,
    )
    reordered_within_ties = equal_mass_reliability(
        [0.1, 0.1, 0.1, 0.9, 0.9],
        [0, 1, 0, 0, 1],
        bins=3,
    )

    assert first == reordered_within_ties
    assert [item["count"] for item in first] == [3, 2]


def test_empty_input_and_equal_identity_challenger_fail_closed():
    empty = walk_forward_calibrate([])
    assert empty["records_emitted"] == 0
    assert empty["comparisons"]["platt"]["status"] == "unverifiable"
    assert empty["artifact_provenance"]["latest_training_cutoff"] is None

    start = date(2026, 3, 1)
    records = []
    for index in range(20):
        probability = 0.8 if index % 2 else 0.2
        records.append(
            {
                "forecast_id": str(index),
                "symbol": "BTCUSDT",
                "issue_date": (start + timedelta(days=index)).isoformat(),
                "model_version": "research-v1",
                "horizon_days": 1,
                "outcome_up": index % 2,
                "identity_probability_up": probability,
                "baseline_probability_up": 0.5,
                "challengers": {
                    "platt": {
                        "fit_status": "calibrated",
                        "probability_up": probability,
                    }
                },
            }
        )
    gate = paired_promotion_gate(
        records,
        method="platt",
        evaluation_protocol_confirmed=True,
    )
    assert gate["gate_passed"] is False
    assert gate["checks"]["brier_improves"] is False
    assert gate["issue_date_block_bootstrap"][
        "brier_advantage_identity_minus_challenger"
    ]["estimate"] == 0.0


def test_walk_forward_abstains_without_explicit_model_version():
    row = _row(
        1,
        issue=date(2026, 1, 1),
        probability=0.5,
        outcome=1,
    )
    row.pop("model_version")

    emitted = walk_forward_calibrate([row])["records"][0]

    assert emitted["calibration_status"] == "abstain"
    assert "explicit_model_version" in emitted["calibration_abstain_reason"]

    missing_symbol = _row(
        2,
        issue=date(2026, 1, 2),
        probability=0.5,
        outcome=0,
    )
    missing_symbol.pop("symbol")
    symbol_result = walk_forward_calibrate([missing_symbol])["records"][0]
    assert symbol_result["calibration_status"] == "abstain"
    assert "explicit_symbol" in symbol_result["calibration_abstain_reason"]


def test_walk_forward_rejects_duplicate_forecast_ids_and_units():
    first = _row(
        1,
        issue=date(2026, 1, 1),
        probability=0.5,
        outcome=1,
    )
    with pytest.raises(ValueError, match="duplicate forecast identity"):
        walk_forward_calibrate([first, dict(first)])

    revision = dict(first, forecast_id="different-revision-id")
    with pytest.raises(ValueError, match="duplicate forecast identity"):
        walk_forward_calibrate([first, revision])


@pytest.mark.parametrize(
    "override",
    [
        {"min_samples": 999},
        {"min_issue_dates": 179},
        {"min_class_samples": 99},
        {"bootstrap_samples": 999},
        {"bootstrap_samples": 1001},
        {"confidence_level": 0.90},
        {"confidence_level": 0.99},
        {"random_seed": 1},
        {"block_size": 8},
        {"log_loss_noninferiority_margin": 0.001},
        {"max_roc_auc_degradation": 0.003},
    ],
)
def test_formal_promotion_thresholds_cannot_be_weakened(override):
    with pytest.raises(ValueError, match="formal promotion"):
        paired_promotion_gate([], method="platt", **override)


def test_promotion_gate_rejects_missing_or_mixed_scope_even_when_scores_pass():
    start = date(2020, 1, 1)
    records = []
    for index in range(1000):
        outcome = index % 2
        records.append(
            {
                "forecast_id": str(index),
                "symbol": "BTCUSDT",
                "issue_date": (start + timedelta(days=index)).isoformat(),
                "outcome_up": outcome,
                "identity_probability_up": 0.9 if outcome else 0.8,
                "baseline_probability_up": 0.6,
                "challengers": {
                    "platt": {
                        "fit_status": "calibrated",
                        "probability_up": 0.55 if outcome else 0.45,
                    }
                },
            }
        )

    missing = paired_promotion_gate(
        records,
        method="platt",
        evaluation_protocol_confirmed=True,
        exact_vintage_confirmed=True,
        decision_policy_impact_confirmed=True,
    )
    assert missing["checks"]["all_paired_rows_have_valid_scope_and_issue_date"] is False
    assert missing["checks"]["single_model_horizon_group"] is False
    assert missing["gate_passed"] is False

    mixed = [dict(row, model_version="research-v1", horizon_days=1) for row in records]
    mixed[-1].pop("model_version")
    mixed_result = paired_promotion_gate(
        mixed,
        method="platt",
        evaluation_protocol_confirmed=True,
        exact_vintage_confirmed=True,
        decision_policy_impact_confirmed=True,
    )
    assert mixed_result["checks"][
        "all_paired_rows_have_valid_scope_and_issue_date"
    ] is False
    assert mixed_result["checks"]["single_model_horizon_group"] is False
    assert mixed_result["gate_passed"] is False

    duplicated_id = [
        dict(row, model_version="research-v1", horizon_days=1) for row in records
    ]
    duplicated_id[-1]["forecast_id"] = duplicated_id[0]["forecast_id"]
    duplicate_id_result = paired_promotion_gate(
        duplicated_id,
        method="platt",
        evaluation_protocol_confirmed=True,
        exact_vintage_confirmed=True,
        decision_policy_impact_confirmed=True,
    )
    assert duplicate_id_result["checks"][
        "all_paired_rows_have_unique_forecast_id"
    ] is False
    assert duplicate_id_result["gate_passed"] is False

    duplicated_unit = [dict(row) for row in duplicated_id]
    duplicated_unit[-1]["forecast_id"] = "unique-revision-id"
    duplicated_unit[-1]["issue_date"] = duplicated_unit[0]["issue_date"]
    duplicate_unit_result = paired_promotion_gate(
        duplicated_unit,
        method="platt",
        evaluation_protocol_confirmed=True,
        exact_vintage_confirmed=True,
        decision_policy_impact_confirmed=True,
    )
    assert duplicate_unit_result["checks"][
        "all_paired_rows_are_unique_forecast_units"
    ] is False
    assert duplicate_unit_result["gate_passed"] is False


def test_promotion_gate_counts_normalized_issue_days_not_timestamp_strings():
    records = []
    for index in range(1000):
        outcome = index % 2
        day = 1 + (index % 10)
        records.append(
            {
                "forecast_id": str(index),
                "symbol": "BTCUSDT",
                "model_version": "research-v1",
                "horizon_days": 1,
                "issue_date": f"2025-01-{day:02d}T{index // 10:02d}:00:00Z",
                "outcome_up": outcome,
                "identity_probability_up": 0.9 if outcome else 0.8,
                "baseline_probability_up": 0.6,
                "challengers": {
                    "platt": {
                        "fit_status": "calibrated",
                        "probability_up": 0.55 if outcome else 0.45,
                    }
                },
            }
        )

    gate = paired_promotion_gate(
        records,
        method="platt",
        evaluation_protocol_confirmed=True,
        exact_vintage_confirmed=True,
        decision_policy_impact_confirmed=True,
    )

    assert gate["comparison"]["paired_issue_dates"] == 10
    assert gate["checks"]["minimum_issue_dates"] is False
    assert gate["gate_passed"] is False


def test_model_version_and_horizon_are_isolated_while_symbols_pool():
    start = date(2025, 1, 1)
    rows = []
    for index in range(20):
        issue = start + timedelta(days=index)
        rows.append(
            _row(index, issue=issue, probability=0.8, outcome=index % 2, symbol="BTC")
        )
        rows.append(
            _row(index, issue=issue, probability=0.2, outcome=index % 2, symbol="ETH")
        )
        rows.append(
            _row(
                index,
                issue=issue,
                probability=0.7,
                outcome=index % 2,
                model_version="research-v2",
            )
        )
        rows.append(
            _row(
                index,
                issue=issue,
                probability=0.6,
                outcome=index % 2,
                horizon=5,
                target_offset=5,
            )
        )
    report = walk_forward_calibrate(
        rows, min_samples=10, min_issue_dates=5, min_class_samples=2
    )
    current = [
        row
        for row in report["records"]
        if row["issue_date"] == (start + timedelta(days=19)).isoformat()
        and row["model_version"] == "research-v1"
        and row["horizon_days"] == 1
    ]
    assert len(current) == 2
    assert {
        row["challengers"]["platt"]["calibration_samples"] for row in current
    } == {36}
    assert len(report["comparisons_by_group"]) == 3


def test_target_as_of_alias_is_admitted_to_mature_training():
    rows = _alternating_rows(20)
    for row in rows:
        row["target_as_of"] = row.pop("target_date")
    report = _small_report(rows)
    assert report["records"][-1]["calibration_status"] == "calibrated"
    assert report["records"][-1]["challengers"]["beta"]["calibration_samples"] == 18


def test_cli_reads_replay_json_and_writes_report_atomically(capsys):
    directory = Path(__file__).resolve().parent
    source = directory / ".forecast_calibration_input_test.json"
    output = directory / ".forecast_calibration_output_test.json"
    try:
        source.write_text(
            json.dumps({"replay_records": _alternating_rows(20)}), encoding="utf-8"
        )

        result = main(
            [
                "--input",
                str(source),
                "--output",
                str(output),
                "--min-samples",
                "10",
                "--min-issue-dates",
                "10",
                "--min-class-samples",
                "2",
            ]
        )

        assert result == 0
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["schema_version"] == "forecast-calibration-research-v1"
        assert payload["production_model_changed"] is False
        assert '"calibrated_records"' in capsys.readouterr().out
        assert not list(directory.glob(f".{output.name}.*.tmp"))
    finally:
        source.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
