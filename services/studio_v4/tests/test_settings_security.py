import pytest

from studio.settings import validate_security_config


HEX_256 = "0123456789abcdef" * 4
URLSAFE_256 = "A1_b2-C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1V"


def test_local_development_may_use_loopback_only_mode():
    validate_security_config("", "development")
    validate_security_config("", "test")


@pytest.mark.parametrize("token", ["short-token", "x" * 64, "a" * 64, "x" * 43])
def test_configured_shared_token_must_have_256_bit_encoding(token):
    with pytest.raises(RuntimeError, match="256-bit"):
        validate_security_config(token, "development")


def test_production_requires_a_256_bit_service_token():
    with pytest.raises(RuntimeError, match="256-bit"):
        validate_security_config("", "production")


def test_production_accepts_256_bit_hex_or_urlsafe_token():
    validate_security_config(HEX_256, "production")
    validate_security_config(URLSAFE_256, "prod")
