import pytest

from studio.settings import validate_security_config


def test_local_development_may_use_loopback_only_mode():
    validate_security_config("", "development")
    validate_security_config("", "test")


def test_any_configured_shared_token_must_be_at_least_32_characters():
    with pytest.raises(RuntimeError, match="at least 32 characters"):
        validate_security_config("short-token", "development")


def test_production_requires_a_strong_service_token():
    with pytest.raises(RuntimeError, match="Production Studio requires"):
        validate_security_config("", "production")
    with pytest.raises(RuntimeError, match="Production Studio requires"):
        validate_security_config("short-token", "production")


def test_production_accepts_a_strong_service_token():
    validate_security_config("x" * 32, "production")
    validate_security_config("x" * 64, "prod")
