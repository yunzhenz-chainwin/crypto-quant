"""Deployment safety checks and HTTP response hardening.

The development fallback credentials exist only to make an explicitly opted-in
loopback workflow possible.  A public/production process must never start with
either fallback value, even when the local-development override is present.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from typing import Any

from starlette.datastructures import MutableHeaders


DEFAULT_ADMIN_PASSWORD = "admin123"
DEFAULT_ADMIN_SECRET = "dev-secret-change-me"
LOCAL_INSECURE_OVERRIDE = "ALLOW_INSECURE_ADMIN_DEFAULTS"

_LOCAL_MODES = {"dev", "development", "local", "test", "testing"}
_EXTERNAL_MODES = {"prod", "production", "public", "external", "staging"}
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


class SecurityConfigurationError(RuntimeError):
    """Raised before application startup when credentials are unsafe."""


@dataclass(frozen=True)
class AdminSecurityConfig:
    username: str
    password: str
    secret: bytes
    deployment_mode: str
    external: bool
    insecure_local_override: bool
    weak_external_password: bool


def _enabled(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _deployment_mode(environ: Mapping[str, str]) -> str:
    return str(
        environ.get("CRYPTO_QUANT_MODE")
        or environ.get("APP_ENV")
        or environ.get("ENVIRONMENT")
        or "development"
    ).strip().lower()


def _bind_host(environ: Mapping[str, str]) -> str:
    return str(
        environ.get("CRYPTO_QUANT_BIND_HOST")
        or environ.get("UVICORN_HOST")
        or environ.get("HOST")
        or ""
    ).strip().lower().strip("[]")


def _is_external(environ: Mapping[str, str], mode: str) -> bool:
    if mode in _EXTERNAL_MODES or (mode and mode not in _LOCAL_MODES):
        return True
    if any(_enabled(environ.get(name)) for name in (
        "CRYPTO_QUANT_PUBLIC", "PUBLIC_MODE", "EXTERNAL_MODE",
    )):
        return True
    bind_host = _bind_host(environ)
    return bool(bind_host and bind_host not in _LOOPBACK_HOSTS)


def load_admin_security_config(
    environ: Mapping[str, str] | None = None,
) -> AdminSecurityConfig:
    """Load credentials and fail closed when fallback values are unsafe.

    Local development with fallback values requires both a local deployment
    mode and ``ALLOW_INSECURE_ADMIN_DEFAULTS=1``.  The override is deliberately
    ignored for public/production modes and non-loopback bind hosts.
    """
    values = os.environ if environ is None else environ
    password_was_explicit = bool(values.get("ADMIN_PASS"))
    username = str(values.get("ADMIN_USER") or "admin")
    password = str(values.get("ADMIN_PASS") or DEFAULT_ADMIN_PASSWORD)
    secret_text = str(values.get("ADMIN_SECRET") or DEFAULT_ADMIN_SECRET)
    mode = _deployment_mode(values)
    external = _is_external(values, mode)
    bind_host = _bind_host(values)
    override = _enabled(values.get(LOCAL_INSECURE_OVERRIDE))
    uses_default_password = password == DEFAULT_ADMIN_PASSWORD
    uses_default_secret = secret_text == DEFAULT_ADMIN_SECRET
    uses_fallback = uses_default_password or uses_default_secret

    if not password or not secret_text:
        raise SecurityConfigurationError(
            "ADMIN_PASS and ADMIN_SECRET must both be configured"
        )
    if uses_default_secret and external:
        raise SecurityConfigurationError(
            "public/production startup refused: the default admin signing secret is configured"
        )
    if external:
        if len(secret_text) < 32:
            raise SecurityConfigurationError(
                "public/production ADMIN_SECRET must contain at least 32 characters"
            )
        explicit_legacy_password = uses_default_password and password_was_explicit
        if len(password) < 12 and not explicit_legacy_password:
            raise SecurityConfigurationError(
                "public/production ADMIN_PASS must contain at least 12 characters"
            )
    elif uses_fallback:
        if bind_host not in _LOOPBACK_HOSTS:
            raise SecurityConfigurationError(
                "default admin credentials require an explicit loopback bind host"
            )
        if not override:
            raise SecurityConfigurationError(
                "default admin credentials require an explicit local-development override"
            )

    return AdminSecurityConfig(
        username=username,
        password=password,
        secret=secret_text.encode("utf-8"),
        deployment_mode=mode,
        external=external,
        insecure_local_override=not external and uses_fallback and override,
        weak_external_password=external and uses_default_password,
    )


CONTENT_SECURITY_POLICY = "; ".join((
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https:",
    "font-src 'self' data:",
    "connect-src 'self' wss://stream.binance.com:9443",
))


class SecurityHeadersMiddleware:
    """Add browser hardening headers without caching authenticated responses."""

    _BASE_HEADERS = {
        "Content-Security-Policy": CONTENT_SECURITY_POLICY,
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "X-Permitted-Cross-Domain-Policies": "none",
    }
    _SENSITIVE_GET_PREFIXES = (
        "/api/admin",
        "/api/forecast/scorecard",
    )
    _SENSITIVE_EXACT_PATHS = {
        "/api/sentiment/news/backfill",
    }

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "GET").upper()
        scheme = str(scope.get("scheme") or "http").lower()
        no_store = (
            method not in {"GET", "HEAD", "OPTIONS"}
            or path in self._SENSITIVE_EXACT_PATHS
            or any(path.startswith(prefix) for prefix in self._SENSITIVE_GET_PREFIXES)
        )

        async def send_hardened(message):
            if message.get("type") == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self._BASE_HEADERS.items():
                    if name not in headers:
                        headers[name] = value
                if scheme == "https" and "Strict-Transport-Security" not in headers:
                    headers["Strict-Transport-Security"] = "max-age=31536000"
                if no_store:
                    headers["Cache-Control"] = "no-store"
                    headers["Pragma"] = "no-cache"
            await send(message)

        await self.app(scope, receive, send_hardened)
