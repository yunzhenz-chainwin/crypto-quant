from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import gc
import math
from pathlib import Path
import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.main import DIST, app
from backend.routers import forecast as forecast_router
from backend.services import app_db
from src.forecasting import (
    MIN_READY_CONFIDENCE, MODEL_VERSION,
    apply_freshness_guard,
    generate_forecast,
    model_metadata,
    resolve_forecast_outcome,
)


client = TestClient(app)


def _price_rows(count: int, start: datetime, *, future_spike: bool = False) -> list[dict]:
    rows = []
    for i in range(count):
        close = 100.0 + i * 0.08 + math.sin(i / 4.0) * 5.0
        if future_spike and i >= count - 3:
            close *= 20.0
        rows.append({"date": (start + timedelta(days=i)).date().isoformat(), "close": close})
    return rows


@pytest.fixture()
def isolated_forecast_db(monkeypatch):
    # The managed Windows runner can deny pytest's default system temp ACL.
    # A uniquely named workspace file is equally isolated and is removed here.
    db_path = Path(__file__).parent / f".forecast_test_{uuid4().hex}.db"
    monkeypatch.setattr(app_db, "DB_PATH", db_path)
    app_db.init_db()
    try:
        yield db_path
    finally:
        gc.collect()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{db_path}{suffix}").unlink(missing_ok=True)


def test_forecast_api_contract_uses_only_completed_daily_bars(isolated_forecast_db, monkeypatch):
    now = datetime.now(timezone.utc)
    yesterday = now.date() - timedelta(days=1)
    start = datetime.combine(yesterday - timedelta(days=299), datetime.min.time())
    rows = _price_rows(300, start)
    # A current UTC daily candle is still open and must never enter the snapshot.
    rows.append({"date": now.date().isoformat(), "close": 9_999_999.0})
    monkeypatch.setattr(forecast_router, "available_symbols", lambda interval="1d": ["TESTUSDT"])
    monkeypatch.setattr(forecast_router, "load_prices", lambda *args, **kwargs: rows)

    response = client.get("/api/forecast/testusdt?horizon=5")
    assert response.status_code == 200
    body = response.json()
    required = {
        "forecast_id", "symbol", "horizon_days", "status", "research", "as_of",
        "generated_at", "model_version", "probabilities", "return_quantiles_pct",
        "downside_risk", "regime", "confidence", "recommendation", "abstain_reason",
        "evidence", "data_quality", "input_hash", "data_version", "reference_close",
    }
    assert required <= body.keys()
    assert body["symbol"] == "TESTUSDT"
    assert body["horizon_days"] == 5
    assert body["research"] is True
    assert body["model_version"] == MODEL_VERSION
    assert body["as_of"] == yesterday.isoformat()
    assert body["data_quality"]["observations"] == 300
    assert body["probabilities"]["up"] is None or 0 <= body["probabilities"]["up"] <= 1
    assert body["downside_risk"]["threshold_pct"] == -7.0
    assert body["confidence"]["threshold"] == MIN_READY_CONFIDENCE
    evidence = body["evidence"]
    assert evidence["schema_version"] == 2
    assert evidence["items"] == [*evidence["supporting"], *evidence["opposing"]]
    assert evidence["for"] == [item["label"] for item in evidence["supporting"][:3]]
    assert evidence["against"] == [item["label"] for item in evidence["opposing"][:4]]
    for source_bucket in ("supporting", "opposing"):
        for item in evidence[source_bucket]:
            assert item["source_bucket"] == source_bucket
            assert item["code"]
            assert item["polarity"] in {"bullish", "bearish", "neutral"}
            assert item["category"] in {
                "directional", "risk", "release_gate", "observation", "notice", "evidence",
            }

    # Same model + same as_of returns the immutable snapshot, not a rewrite.
    assert client.get("/api/forecast/TESTUSDT?horizon=5").json()["generated_at"] == body["generated_at"]


def test_forecast_api_rejects_unknown_horizon(isolated_forecast_db, monkeypatch):
    monkeypatch.setattr(forecast_router, "available_symbols", lambda interval="1d": ["TESTUSDT"])
    response = client.get("/api/forecast/TESTUSDT?horizon=2")
    assert response.status_code == 422


def test_same_as_of_data_revision_creates_a_new_content_addressed_snapshot(
    isolated_forecast_db, monkeypatch,
):
    now = datetime.now(timezone.utc)
    yesterday = now.date() - timedelta(days=1)
    start = datetime.combine(yesterday - timedelta(days=299), datetime.min.time())
    state = {"rows": _price_rows(300, start)}
    monkeypatch.setattr(forecast_router, "available_symbols", lambda interval="1d": ["TESTUSDT"])
    monkeypatch.setattr(forecast_router, "load_prices", lambda *args, **kwargs: state["rows"])

    original = client.get("/api/forecast/TESTUSDT?horizon=5").json()
    revised_rows = deepcopy(state["rows"])
    revised_rows[80]["close"] += 0.125  # historical correction; same final date and close
    state["rows"] = revised_rows
    revised = client.get("/api/forecast/TESTUSDT?horizon=5").json()

    assert revised["as_of"] == original["as_of"]
    assert revised["reference_close"] == original["reference_close"]
    assert revised["input_hash"] != original["input_hash"]
    assert revised["data_version"] != original["data_version"]
    assert revised["forecast_id"] != original["forecast_id"]
    assert app_db.load_forecast_by_id(original["forecast_id"]) == original
    assert app_db.load_forecast_by_id(revised["forecast_id"]) == revised

    conn = sqlite3.connect(isolated_forecast_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM forecast_snapshot_v2").fetchone()[0] == 2
    finally:
        conn.close()


def test_point_in_time_forecast_ignores_future_rows():
    start = datetime(2024, 1, 1)
    rows = _price_rows(320, start)
    as_of = rows[299]["date"]
    fixed_now = datetime.fromisoformat(as_of).replace(tzinfo=timezone.utc) + timedelta(days=1)
    baseline = generate_forecast("BTCUSDT", 5, rows[:300], as_of=as_of, now=fixed_now)

    future = rows[:300] + [
        {"date": rows[300 + i]["date"], "close": 1_000_000.0 if i % 2 else 0.01}
        for i in range(20)
    ]
    with_future = generate_forecast("BTCUSDT", 5, future, as_of=as_of, now=fixed_now)
    assert with_future == baseline
    assert baseline["status"] != "ready" or baseline["confidence"]["score"] >= MIN_READY_CONFIDENCE


def test_forecast_abstains_for_insufficient_or_stale_data():
    start = datetime(2024, 1, 1)
    insufficient = _price_rows(40, start)
    short_result = generate_forecast(
        "BTCUSDT", 1, insufficient,
        now=datetime(2024, 2, 10, tzinfo=timezone.utc),
    )
    assert short_result["status"] == "abstain"
    assert "樣本不足" in short_result["abstain_reason"]
    assert short_result["probabilities"]["up"] is None
    assert short_result["evidence"]["opposing"][0]["code"] == "insufficient_observations"
    assert short_result["evidence"]["opposing"][0]["source_bucket"] == "opposing"

    enough = _price_rows(300, start)
    stale_result = generate_forecast(
        "BTCUSDT", 10, enough,
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert stale_result["status"] == "abstain"
    assert stale_result["data_quality"]["stale"] is True
    assert "資料已過期" in stale_result["abstain_reason"]
    assert "data_stale" in {
        item["code"] for item in stale_result["evidence"]["opposing"]
    }


def test_freshness_guard_upgrades_legacy_evidence_without_text_reclassification():
    snapshot = {
        "status": "ready",
        "recommendation": "research_watch_upside",
        "as_of": "2026-01-01",
        "data_quality": {"stale": False, "observations": 200},
        "evidence": {
            "for": ["legacy supporting text"],
            "against": ["legacy opposing text"],
        },
    }

    guarded = apply_freshness_guard(
        snapshot,
        now=datetime(2026, 1, 10, tzinfo=timezone.utc),
    )

    assert guarded["status"] == "abstain"
    assert guarded["evidence"]["schema_version"] == 2
    assert guarded["evidence"]["supporting"][0] == {
        "code": "legacy_supporting_0",
        "polarity": "neutral",
        "source_bucket": "supporting",
        "category": "evidence",
        "status": "info",
        "label": "legacy supporting text",
        "detail": "",
    }
    assert guarded["evidence"]["opposing"][0]["code"] == "data_stale"
    assert guarded["evidence"]["against"][0] == guarded["abstain_reason"]
    # The immutable source object is not rewritten by the delivery guard.
    assert snapshot["evidence"] == {
        "for": ["legacy supporting text"],
        "against": ["legacy opposing text"],
    }


def test_forecast_and_outcome_are_append_only(isolated_forecast_db):
    app_db.register_forecast_model(model_metadata())
    start = datetime(2025, 1, 1)
    rows = _price_rows(220, start)
    as_of = rows[199]["date"]
    now = datetime.fromisoformat(as_of).replace(tzinfo=timezone.utc) + timedelta(days=1)
    snapshot = generate_forecast("BTCUSDT", 5, rows[:200], as_of=as_of, now=now)
    app_db.save_forecast_snapshot(snapshot)
    assert app_db.save_forecast_snapshot(snapshot) == snapshot  # identical retry is safe

    changed = deepcopy(snapshot)
    changed["status"] = "ready" if snapshot["status"] != "ready" else "abstain"
    with pytest.raises(app_db.AppendOnlyConflict):
        app_db.save_forecast_snapshot(changed)

    outcome = resolve_forecast_outcome(snapshot, rows, now=now + timedelta(days=5))
    assert outcome is not None
    app_db.save_forecast_outcome(outcome)
    changed_outcome = {**outcome, "realized_return_pct": 123.456}
    with pytest.raises(app_db.AppendOnlyConflict):
        app_db.save_forecast_outcome(changed_outcome)
    assert app_db.load_forecast_by_id(snapshot["forecast_id"]) == snapshot
    assert app_db.load_forecast_outcome(snapshot["forecast_id"]) == outcome

    # A later correction of the as_of close cannot rewrite the forecast's
    # sealed base price or its realized outcome.
    revised_rows = deepcopy(rows)
    revised_rows[199]["close"] = snapshot["reference_close"] * 10
    revised_outcome = resolve_forecast_outcome(snapshot, revised_rows, now=now + timedelta(days=5))
    expected_return = (rows[204]["close"] / snapshot["reference_close"] - 1) * 100
    assert revised_outcome["reference_close"] == snapshot["reference_close"]
    assert revised_outcome["realized_return_pct"] == round(expected_return, 4)
    assert revised_outcome["realized_return_pct"] == outcome["realized_return_pct"]

    # The database itself rejects accidental UPDATE/DELETE, not only helpers.
    conn = sqlite3.connect(isolated_forecast_db)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE forecast_snapshot_v2 SET status='ready' WHERE forecast_id=?",
                (snapshot["forecast_id"],),
            )
    finally:
        conn.close()

def test_v2_migration_preserves_legacy_immutable_snapshot(isolated_forecast_db):
    app_db.register_forecast_model(model_metadata())
    legacy = {
        "forecast_id": "fc_legacy_immutable",
        "symbol": "BTCUSDT",
        "horizon_days": 5,
        "as_of": "2025-01-01",
        "generated_at": "2025-01-02T00:00:00Z",
        "model_version": MODEL_VERSION,
        "status": "abstain",
        "research": True,
    }
    encoded = app_db._canonical_json(legacy)
    conn = sqlite3.connect(isolated_forecast_db)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "INSERT INTO forecast_snapshot "
            "(forecast_id,symbol,horizon_days,as_of,generated_at,model_version,status,payload_json,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                legacy["forecast_id"], legacy["symbol"], legacy["horizon_days"], legacy["as_of"],
                legacy["generated_at"], legacy["model_version"], legacy["status"], encoded,
                "2025-01-02 00:00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    app_db.init_db()  # forward migration is safe to repeat
    assert app_db.load_forecast_by_id(legacy["forecast_id"]) == legacy
    conn = sqlite3.connect(isolated_forecast_db)
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"forecast_snapshot", "forecast_snapshot_v2"} <= tables
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE forecast_snapshot SET status='ready' WHERE forecast_id=?",
                (legacy["forecast_id"],),
            )
    finally:
        conn.close()


def test_outcome_pipeline_adopts_concurrent_append_winner(isolated_forecast_db, monkeypatch):
    app_db.register_forecast_model(model_metadata())
    start = datetime(2025, 1, 1)
    rows = _price_rows(220, start)
    as_of = rows[199]["date"]
    forecast_now = datetime.fromisoformat(as_of).replace(tzinfo=timezone.utc) + timedelta(days=1)
    resolve_now = forecast_now + timedelta(days=5)
    snapshot = generate_forecast("BTCUSDT", 5, rows[:200], as_of=as_of, now=forecast_now)
    app_db.save_forecast_snapshot(snapshot)

    real_save = app_db.save_forecast_outcome
    winner: dict = {}

    def lose_simulated_cross_process_race(payload):
        winner.update({**payload, "resolved_at": "2025-12-31T23:59:59Z"})
        real_save(winner)
        raise app_db.AppendOnlyConflict("simulated concurrent winner")

    monkeypatch.setattr(app_db, "save_forecast_outcome", lose_simulated_cross_process_race)
    resolved = app_db.resolve_mature_forecast_outcomes(
        lambda symbol: rows,
        limit=1,
        now=resolve_now,
    )

    assert resolved == [winner]
    assert app_db.load_forecast_outcome(snapshot["forecast_id"]) == winner


def test_spa_fallback_cannot_escape_dist_directory():
    response = client.get("/%2e%2e/%2e%2e/README.md", follow_redirects=False)
    assert response.status_code == 404
    assert "Crypto Quant" not in response.text

    # A legitimate file inside dist remains available when a production build
    # is present (dist is intentionally absent in some clean test checkouts).
    if (DIST / "favicon.svg").exists():
        assert client.get("/favicon.svg").status_code == 200
