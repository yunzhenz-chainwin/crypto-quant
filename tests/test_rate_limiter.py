from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import admin, ai, backtest, forecast, sentiment
from backend.services.rate_limiter import FailedLoginLockout, SlidingWindowRateLimiter


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds: float):
        self.now += seconds


def test_sliding_window_and_retry_after():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(max_entries=8, clock=clock)

    assert limiter.check(scope="login", client="a", limit=2, window_seconds=60).allowed
    assert limiter.check(scope="login", client="a", limit=2, window_seconds=60).allowed
    denied = limiter.check(scope="login", client="a", limit=2, window_seconds=60)
    assert denied.allowed is False
    assert denied.retry_after == 60

    clock.advance(31)
    assert limiter.check(
        scope="login", client="a", limit=2, window_seconds=60,
    ).retry_after == 29
    clock.advance(29)
    assert limiter.check(scope="login", client="a", limit=2, window_seconds=60).allowed


def test_scopes_and_clients_are_isolated():
    limiter = SlidingWindowRateLimiter(max_entries=8, clock=FakeClock())
    assert limiter.check(scope="login", client="a", limit=1, window_seconds=60).allowed
    assert not limiter.check(scope="login", client="a", limit=1, window_seconds=60).allowed
    assert limiter.check(scope="backtest", client="a", limit=1, window_seconds=60).allowed
    assert limiter.check(scope="login", client="b", limit=1, window_seconds=60).allowed


def test_entry_bound_is_thread_safe_and_expired_entries_are_reclaimed():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(max_entries=16, clock=clock)

    def first_request(i):
        return limiter.check(
            scope="login", client=f"client-{i}", limit=1, window_seconds=60,
        ).allowed

    with ThreadPoolExecutor(max_workers=20) as pool:
        allowed = list(pool.map(first_request, range(100)))
    assert sum(allowed) == 16
    assert limiter.entry_count == 16

    saturated = limiter.check(scope="login", client="new", limit=1, window_seconds=60)
    assert saturated.allowed is False
    assert saturated.retry_after == 60

    clock.advance(60)
    assert limiter.check(scope="login", client="new", limit=1, window_seconds=60).allowed
    assert limiter.entry_count == 1


def test_failed_login_lockout_lasts_15_minutes_and_success_resets_failures():
    clock = FakeClock()
    guard = FailedLoginLockout(
        max_failures=5,
        lockout_seconds=900,
        failure_window_seconds=900,
        max_entries=8,
        clock=clock,
    )

    for expected_remaining in (4, 3, 2, 1):
        result = guard.record_failure("client-a")
        assert result.locked is False
        assert result.remaining_failures == expected_remaining
    guard.record_success("client-a")
    assert guard.status("client-a").remaining_failures == 5

    for _ in range(5):
        final = guard.record_failure("client-a")
    assert final.locked is True
    assert guard.status("client-a").retry_after == 900
    clock.advance(899)
    assert guard.status("client-a").locked is True
    clock.advance(1)
    assert guard.status("client-a").locked is False


@pytest.fixture()
def limited_api(monkeypatch):
    limiter = SlidingWindowRateLimiter(max_entries=32, clock=FakeClock())
    login_guard = FailedLoginLockout(max_entries=32, clock=FakeClock())
    monkeypatch.setattr(admin, "RATE_LIMITER", limiter)
    monkeypatch.setattr(admin, "LOGIN_FAILURE_GUARD", login_guard)
    monkeypatch.setattr(ai, "RATE_LIMITER", limiter)
    monkeypatch.setattr(backtest, "RATE_LIMITER", limiter)
    monkeypatch.setattr(forecast, "RATE_LIMITER", limiter)
    monkeypatch.setattr(sentiment, "RATE_LIMITER", limiter)
    monkeypatch.setattr(backtest, "available_symbols", lambda: ["BTCUSDT"])
    monkeypatch.setattr(
        backtest,
        "get_backtest",
        lambda symbol, **kwargs: {"symbol": symbol, "metrics": {}},
    )
    monkeypatch.setattr(backtest, "load_backtest_summary", lambda: [{"symbol": "BTCUSDT"}])
    monkeypatch.setattr(ai, "available_symbols", lambda: ["BTCUSDT"])
    monkeypatch.setattr(
        ai.ai_analyst,
        "analyze",
        lambda symbol, **kwargs: {"symbol": symbol, "source": "test"},
    )
    monkeypatch.setattr(
        sentiment,
        "_hn_fetch_range",
        lambda *args: (1, {"ok_requests": 1, "failed_requests": 0}),
    )
    monkeypatch.setattr(sentiment, "total_count", lambda: 1)
    monkeypatch.setattr(
        forecast,
        "build_forecast_scorecard",
        lambda **kwargs: {"status": "test", "filters": kwargs},
    )

    test_app = FastAPI()
    test_app.include_router(admin.router, prefix="/api")
    test_app.include_router(ai.router, prefix="/api")
    test_app.include_router(backtest.router, prefix="/api")
    test_app.include_router(forecast.router, prefix="/api")
    test_app.include_router(sentiment.router, prefix="/api")
    return TestClient(test_app)


def test_login_is_limited_and_returns_retry_after(limited_api):
    for _ in range(5):
        response = limited_api.post(
            "/api/admin/login",
            json={"username": "invalid", "password": "invalid"},
        )
        assert response.status_code == 401

    blocked = limited_api.post(
        "/api/admin/login",
        json={"username": "invalid", "password": "invalid"},
    )
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "900"


def test_login_constant_time_comparison_accepts_unicode_credentials(limited_api, monkeypatch):
    monkeypatch.setattr(admin, "ADMIN_USER", "管理員")
    monkeypatch.setattr(admin, "ADMIN_PASS", "本機強密碼")
    response = limited_api.post(
        "/api/admin/login",
        json={"username": "管理員", "password": "本機強密碼"},
    )
    assert response.status_code == 200


def test_single_backtest_ignores_spoofed_forwarded_for_and_collection_is_unlimited(limited_api):
    for i in range(12):
        response = limited_api.get(
            "/api/backtest/BTCUSDT",
            headers={"X-Forwarded-For": f"203.0.113.{i}"},
        )
        assert response.status_code == 200

    blocked = limited_api.get(
        "/api/backtest/BTCUSDT",
        headers={"X-Forwarded-For": "198.51.100.250"},
    )
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "60"

    # The persisted collection summary is cheap and intentionally not limited.
    for _ in range(20):
        assert limited_api.get("/api/backtest").status_code == 200


def test_ai_ask_has_per_ip_minute_quota(limited_api):
    for i in range(10):
        response = limited_api.post(
            "/api/ai/ask",
            json={"question": ""},
            headers={"X-Forwarded-For": f"203.0.113.{i}"},
        )
        assert response.status_code == 400

    blocked = limited_api.post("/api/ai/ask", json={"question": ""})
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "60"


def test_forced_ai_analysis_has_stricter_per_ip_quota(limited_api):
    for _ in range(3):
        response = limited_api.get("/api/ai/analysis/BTCUSDT?force=1")
        assert response.status_code == 200

    blocked = limited_api.get("/api/ai/analysis/BTCUSDT?force=1")
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "60"


def test_authenticated_news_backfill_is_limited_per_ip(limited_api):
    token = admin._make_token(admin.ADMIN_USER)
    headers = {"Authorization": f"Bearer {token}"}
    path = "/api/sentiment/news/backfill?from_date=2026-01-01&to_date=2026-01-02"

    assert limited_api.post(path, headers=headers).status_code == 200
    assert limited_api.post(path, headers=headers).status_code == 200
    blocked = limited_api.post(path, headers=headers)
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "3600"


def test_forecast_snapshot_and_scorecard_have_separate_quotas(limited_api):
    for _ in range(30):
        assert limited_api.get("/api/forecast/UNKNOWN?horizon=2").status_code == 422
    snapshot_blocked = limited_api.get("/api/forecast/UNKNOWN?horizon=2")
    assert snapshot_blocked.status_code == 429

    token = admin._make_token(admin.ADMIN_USER)
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(12):
        assert limited_api.get("/api/forecast/scorecard", headers=headers).status_code == 200
    scorecard_blocked = limited_api.get("/api/forecast/scorecard", headers=headers)
    assert scorecard_blocked.status_code == 429
