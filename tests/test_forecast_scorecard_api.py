from __future__ import annotations

from datetime import datetime, timezone
import gc
import hashlib
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routers import admin as admin_router
from backend.services import app_db
from backend.services.forecast_scorecard import (
    build_replay_records,
    deduplicate_forecast_ledger,
)


client = TestClient(app)
MODEL = "scorecard-test-v1"


@pytest.fixture()
def isolated_scorecard_db(monkeypatch):
    db_path = Path(__file__).parent / f".scorecard_test_{uuid4().hex}.db"
    monkeypatch.setattr(app_db, "DB_PATH", db_path)
    app_db.init_db()
    app_db.register_forecast_model({
        "model_version": MODEL,
        "name": "Scorecard test model",
        "status": "research",
        "research": True,
        "methodology": {"test_only": True},
    })
    try:
        yield db_path
    finally:
        gc.collect()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{db_path}{suffix}").unlink(missing_ok=True)


@pytest.fixture()
def admin_headers():
    token = admin_router._make_token("scorecard-test")
    return {"Authorization": f"Bearer {token}"}


def _snapshot(
    forecast_id: str,
    *,
    issue_date: str,
    probability_up: float,
    horizon: int = 1,
    symbol: str = "BTCUSDT",
    generated_at: str | None = None,
    status: str = "ready",
) -> dict:
    digest = hashlib.sha256(forecast_id.encode("utf-8")).hexdigest()
    return {
        "forecast_id": forecast_id,
        "symbol": symbol,
        "horizon_days": horizon,
        "as_of": issue_date,
        "generated_at": generated_at or f"{issue_date}T01:00:00Z",
        "model_version": MODEL,
        "input_hash": digest,
        "data_version": f"{issue_date}:test:{digest[:12]}",
        "reference_close": 100.0,
        "status": status,
        "research": True,
        "probabilities": {"up": probability_up, "down": 1.0 - probability_up},
        "return_quantiles_pct": {"q10": -2.0, "q50": 0.25, "q90": 3.0},
    }


def _resolve(forecast_id: str, *, target: str, realized: float) -> None:
    app_db.save_forecast_outcome({
        "forecast_id": forecast_id,
        "target_as_of": target,
        "resolved_at": f"{target}T01:05:00Z",
        "realized_return_pct": realized,
        "actual_direction": "up" if realized > 0 else ("down" if realized < 0 else "flat"),
    })


def _ledger_counts(db_path: Path) -> tuple[int, int]:
    with sqlite3.connect(db_path) as conn:
        snapshots = conn.execute("SELECT COUNT(*) FROM forecast_snapshot_v2").fetchone()[0]
        outcomes = conn.execute("SELECT COUNT(*) FROM forecast_outcome_v2").fetchone()[0]
    return int(snapshots), int(outcomes)


def test_scorecard_requires_admin_and_empty_ledger_is_unverifiable(
    isolated_scorecard_db,
    admin_headers,
):
    before = _ledger_counts(isolated_scorecard_db)
    assert client.get("/api/forecast/scorecard").status_code == 401
    assert client.get(
        "/api/forecast/scorecard",
        headers={"Authorization": "Bearer invalid"},
    ).status_code == 401
    assert client.get(
        "/api/forecast/scorecard?horizon=2", headers=admin_headers,
    ).status_code == 422

    response = client.get("/api/forecast/scorecard", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unverifiable"
    assert body["data_as_of"] is None
    assert body["overall"]["resolved_count"] == 0
    assert body["overall"]["observations"] == 0
    assert body["overall"]["metrics"] is None
    assert body["provenance"]["snapshot_tables"] == ["forecast_snapshot_v2"]
    assert body["provenance"]["revisions_excluded"] == 0
    assert _ledger_counts(isolated_scorecard_db) == before


def test_scorecard_deduplicates_revisions_before_outcome_filtering(
    isolated_scorecard_db,
    admin_headers,
):
    original = _snapshot(
        "fc_original",
        issue_date="2025-01-01",
        probability_up=0.8,
        generated_at="2025-01-01T01:00:00Z",
    )
    revision = _snapshot(
        "fc_revision",
        issue_date="2025-01-01",
        probability_up=0.1,
        generated_at="2025-01-01T02:00:00Z",
    )
    app_db.save_forecast_snapshot(original)
    app_db.save_forecast_snapshot(revision)
    _resolve(revision["forecast_id"], target="2025-01-02", realized=2.0)

    params = {"horizon": 1, "model_version": MODEL, "symbol": "btcusdt"}
    unresolved_original = client.get(
        "/api/forecast/scorecard",
        params=params,
        headers=admin_headers,
    ).json()
    assert unresolved_original["status"] == "unverifiable"
    assert unresolved_original["overall"]["resolved_count"] == 0
    assert unresolved_original["provenance"]["pending"] == 1
    assert unresolved_original["provenance"]["revisions_excluded"] == 1

    _resolve(original["forecast_id"], target="2025-01-02", realized=2.0)
    response = client.get(
        "/api/forecast/scorecard", params=params, headers=admin_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert body["filters"] == {
        "horizon": 1,
        "model_version": MODEL,
        "symbol": "BTCUSDT",
        "window": None,
        "include_legacy": False,
    }
    assert body["provenance"]["snapshots"] == 2
    assert body["provenance"]["canonical_snapshots"] == 1
    assert body["provenance"]["revisions_excluded"] == 1
    assert body["overall"]["resolved_count"] == 1
    assert body["overall"]["observations"] == 1
    assert body["overall"]["metrics"]["brier_score"] == pytest.approx(0.04)
    assert body["overall"]["metrics"]["f1_score"] == 1.0
    assert body["overall"]["metrics"]["roc_auc"] is None
    assert "average_precision" in body["overall"]["metrics"]
    assert body["overall"]["promotion_gates"][0]["gate"] == (
        "single_model_horizon_scope"
    )
    assert body["overall"]["promotion_gates"][0]["status"] == "not_applicable"

    formal = client.get(
        "/api/forecast/scorecard",
        params={"horizon": 1, "model_version": MODEL},
        headers=admin_headers,
    ).json()
    assert {gate["status"] for gate in formal["overall"]["promotion_gates"]} <= {
        "pass", "failed", "not_testable",
    }
    assert all(
        gate["gate"] != "single_model_horizon_scope"
        for gate in formal["overall"]["promotion_gates"]
    )

    aggregate = client.get(
        "/api/forecast/scorecard", headers=admin_headers,
    ).json()
    assert aggregate["overall"]["promotion_gates"] == [{
        "gate": "single_model_horizon_scope",
        "status": "not_applicable",
        "actual": "model_version is not explicit; horizon is not explicit",
        "required": (
            "one explicit model_version and one horizon over the full "
            "unfiltered symbol universe and full history"
        ),
    }]


def test_same_second_revisions_keep_actual_sqlite_insert_order(
    isolated_scorecard_db,
    monkeypatch,
):
    monkeypatch.setattr(app_db, "_now", lambda: "2025-01-01 01:00:00")
    original = _snapshot(
        "zz_first_inserted",
        issue_date="2025-01-01",
        probability_up=0.8,
        generated_at="2025-01-01T02:00:00Z",
    )
    revision = _snapshot(
        "aa_second_inserted",
        issue_date="2025-01-01",
        probability_up=0.1,
        generated_at="2025-01-01T01:00:00Z",
    )
    app_db.save_forecast_snapshot(original)
    app_db.save_forecast_snapshot(revision)

    ledger = app_db.load_forecast_ledger(
        horizon_days=1,
        model_version=MODEL,
        symbol="BTCUSDT",
    )
    rowids = {row["forecast_id"]: row["snapshot_rowid"] for row in ledger}
    assert rowids["zz_first_inserted"] < rowids["aa_second_inserted"]
    assert deduplicate_forecast_ledger(ledger)[0]["forecast_id"] == "zz_first_inserted"


def test_prequential_baseline_is_built_before_window_and_flat_is_non_up(
    isolated_scorecard_db,
    admin_headers,
):
    first = _snapshot("fc_first", issue_date="2025-01-01", probability_up=0.7)
    second = _snapshot(
        "fc_second",
        issue_date="2025-01-02",
        probability_up=0.4,
        status="abstain",
    )
    app_db.save_forecast_snapshot(first)
    app_db.save_forecast_snapshot(second)
    _resolve(first["forecast_id"], target="2025-01-02", realized=1.0)
    _resolve(second["forecast_id"], target="2025-01-03", realized=0.0)

    replay = build_replay_records(model_version=MODEL, horizon=1, symbol="BTCUSDT")
    assert [row["baseline_probability_up"] for row in replay] == pytest.approx([0.5, 2 / 3])
    assert replay[1]["outcome_up"] == 0

    response = client.get(
        "/api/forecast/scorecard",
        params={
            "horizon": 1,
            "model_version": MODEL,
            "symbol": "BTCUSDT",
            "window": 1,
        },
        headers=admin_headers,
    )
    body = response.json()
    assert response.status_code == 200
    assert body["data_as_of"] == "2025-01-03"
    assert body["overall"]["resolved_count"] == 1
    assert body["overall"]["date_range"] == {
        "start": "2025-01-02",
        "end": "2025-01-02",
    }
    assert body["overall"]["metrics"]["baseline_brier_score"] == pytest.approx((2 / 3) ** 2)
    assert body["overall"]["ready_count"] == 0
    assert body["overall"]["coverage"] == 0.0
    scope_gate = body["overall"]["promotion_gates"][0]
    assert scope_gate["gate"] == "single_model_horizon_scope"
    assert scope_gate["status"] == "not_applicable"
    assert "symbol-filtered" in scope_gate["actual"]
    assert "window-filtered" in scope_gate["actual"]


def test_legacy_rows_are_opt_in_and_fail_the_release_provenance_gate(
    isolated_scorecard_db,
    admin_headers,
):
    legacy = {
        "forecast_id": "fc_legacy_scorecard",
        "symbol": "ETHUSDT",
        "horizon_days": 5,
        "as_of": "2025-02-01",
        "generated_at": "2025-02-01T01:00:00Z",
        "model_version": MODEL,
        "status": "ready",
        "research": True,
        "probabilities": {"up": 0.6, "down": 0.4},
        "return_quantiles_pct": {"q10": -3.0, "q50": 0.1, "q90": 4.0},
    }
    with sqlite3.connect(isolated_scorecard_db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "INSERT INTO forecast_snapshot "
            "(forecast_id,symbol,horizon_days,as_of,generated_at,model_version,status,payload_json,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                legacy["forecast_id"], legacy["symbol"], legacy["horizon_days"],
                legacy["as_of"], legacy["generated_at"], legacy["model_version"],
                legacy["status"], app_db._canonical_json(legacy), "2025-02-01 01:00:00",
            ),
        )
    _resolve(legacy["forecast_id"], target="2025-02-06", realized=-1.0)

    params = {"horizon": 5, "model_version": MODEL}
    default_body = client.get(
        "/api/forecast/scorecard", params=params, headers=admin_headers,
    ).json()
    assert default_body["status"] == "unverifiable"
    assert default_body["provenance"]["legacy_snapshots"] == 0

    research_body = client.get(
        "/api/forecast/scorecard",
        params={**params, "include_legacy": True},
        headers=admin_headers,
    ).json()
    assert research_body["status"] == "insufficient_evidence"
    assert research_body["provenance"]["legacy_snapshots"] == 1
    assert research_body["provenance"]["release_eligible"] is False
    assert research_body["warnings"]
    provenance_gate = next(
        gate for gate in research_body["overall"]["promotion_gates"]
        if gate["gate"] == "v2_only_provenance"
    )
    assert provenance_gate["status"] == "failed"
