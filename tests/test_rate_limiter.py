from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import admin, backtest
from backend.services.rate_limiter import SlidingWindowRateLimiter


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


@pytest.fixture()
def limited_api(monkeypatch):
    limiter = SlidingWindowRateLimiter(max_entries=32, clock=FakeClock())
    monkeypatch.setattr(admin, "RATE_LIMITER", limiter)
    monkeypatch.setattr(backtest, "RATE_LIMITER", limiter)
    monkeypatch.setattr(backtest, "available_symbols", lambda: ["BTCUSDT"])
    monkeypatch.setattr(
        backtest,
        "get_backtest",
        lambda symbol, **kwargs: {"symbol": symbol, "metrics": {}},
    )
    monkeypatch.setattr(backtest, "load_backtest_summary", lambda: [{"symbol": "BTCUSDT"}])

    test_app = FastAPI()
    test_app.include_router(admin.router, prefix="/api")
    test_app.include_router(backtest.router, prefix="/api")
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
    assert blocked.headers["Retry-After"] == "60"


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
