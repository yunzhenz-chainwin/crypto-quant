import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse

from backend.services.security_hardening import (
    CONTENT_SECURITY_POLICY,
    SecurityConfigurationError,
    SecurityHeadersMiddleware,
    load_admin_security_config,
)


def _strong_config(**overrides):
    values = {
        "CRYPTO_QUANT_MODE": "external",
        "ADMIN_USER": "operator",
        "ADMIN_PASS": "non-default-password",
        "ADMIN_SECRET": "a-long-non-default-signing-secret-value",
    }
    values.update(overrides)
    return values


def test_external_mode_refuses_default_signing_secret_even_with_local_override():
    values = _strong_config(
        ADMIN_SECRET="dev-secret-change-me",
        ALLOW_INSECURE_ADMIN_DEFAULTS="1",
    )
    with pytest.raises(SecurityConfigurationError, match="startup refused"):
        load_admin_security_config(values)


def test_external_explicit_legacy_password_is_flagged_but_strong_secret_is_accepted():
    config = load_admin_security_config(_strong_config(ADMIN_PASS="admin123"))
    assert config.external is True
    assert config.weak_external_password is True


def test_external_implicit_or_other_short_password_is_refused():
    implicit = _strong_config()
    implicit.pop("ADMIN_PASS")
    with pytest.raises(SecurityConfigurationError, match="at least 12"):
        load_admin_security_config(implicit)

    with pytest.raises(SecurityConfigurationError, match="at least 12"):
        load_admin_security_config(_strong_config(ADMIN_PASS="too-short"))


def test_external_short_non_default_secret_is_refused():
    with pytest.raises(SecurityConfigurationError, match="at least 32"):
        load_admin_security_config(_strong_config(ADMIN_SECRET="short-secret"))


def test_non_loopback_bind_is_external_and_fails_closed():
    with pytest.raises(SecurityConfigurationError, match="startup refused"):
        load_admin_security_config({
            "CRYPTO_QUANT_MODE": "development",
            "CRYPTO_QUANT_BIND_HOST": "0.0.0.0",
            "ALLOW_INSECURE_ADMIN_DEFAULTS": "1",
        })


def test_local_fallback_requires_explicit_override():
    with pytest.raises(SecurityConfigurationError, match="explicit local-development"):
        load_admin_security_config({
            "CRYPTO_QUANT_MODE": "development",
            "CRYPTO_QUANT_BIND_HOST": "127.0.0.1",
        })

    config = load_admin_security_config({
        "CRYPTO_QUANT_MODE": "development",
        "CRYPTO_QUANT_BIND_HOST": "127.0.0.1",
        "ALLOW_INSECURE_ADMIN_DEFAULTS": "true",
    })
    assert config.external is False
    assert config.insecure_local_override is True


def test_local_fallback_requires_explicit_loopback_bind_host():
    with pytest.raises(SecurityConfigurationError, match="explicit loopback"):
        load_admin_security_config({
            "CRYPTO_QUANT_MODE": "development",
            "ALLOW_INSECURE_ADMIN_DEFAULTS": "1",
        })


def test_external_mode_accepts_non_default_credentials():
    config = load_admin_security_config(_strong_config())
    assert config.external is True
    assert config.insecure_local_override is False
    assert config.weak_external_password is False
    assert config.username == "operator"


def _header_app():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/public")
    def public():
        return JSONResponse({"ok": True}, headers={"Cache-Control": "public, max-age=60"})

    @app.post("/mutation")
    def mutation():
        return {"ok": True}

    return app


def test_security_headers_apply_without_overwriting_public_cache_policy():
    response = TestClient(_header_app()).get("/public")
    assert response.status_code == 200
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert "wss://stream.binance.com:9443" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert response.headers["cache-control"] == "public, max-age=60"
    assert "strict-transport-security" not in response.headers


def test_sensitive_and_mutating_responses_are_no_store():
    client = TestClient(_header_app())
    mutation = client.post("/mutation")
    assert mutation.headers["cache-control"] == "no-store"
    assert mutation.headers["pragma"] == "no-cache"

    # Even an authentication failure/404 under an admin path must not be cached.
    sensitive = client.get("/api/admin/health")
    assert sensitive.status_code == 404
    assert sensitive.headers["cache-control"] == "no-store"


def test_hsts_is_emitted_only_for_https_requests():
    client = TestClient(_header_app(), base_url="https://testserver")
    response = client.get("/public")
    assert response.headers["strict-transport-security"] == "max-age=31536000"


def test_assembled_application_installs_security_middleware():
    from backend.main import app

    response = TestClient(app).get("/api/symbols")
    assert response.status_code == 200
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert response.headers["x-content-type-options"] == "nosniff"
