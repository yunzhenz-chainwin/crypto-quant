"""Explicitly opt test processes into local fallback admin credentials.

Production/public startup ignores this override.  Keeping it here makes the
otherwise fail-closed application import deterministic during test collection.
"""
import os


os.environ.setdefault("CRYPTO_QUANT_MODE", "test")
os.environ.setdefault("CRYPTO_QUANT_BIND_HOST", "127.0.0.1")
os.environ.setdefault("ALLOW_INSECURE_ADMIN_DEFAULTS", "1")
