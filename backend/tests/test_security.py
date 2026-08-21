from datetime import UTC, datetime, timedelta

import pytest

from app.security import (
    TokenError,
    decode_token,
    encode_token,
    hash_password,
    totp_code,
    verify_password,
    verify_totp,
)


def test_argon2id_password_roundtrip() -> None:
    password_hash = hash_password("long-test-password")
    assert password_hash.startswith("$argon2id$")
    assert verify_password(password_hash, "long-test-password")
    assert not verify_password(password_hash, "wrong-password")


def test_short_password_is_rejected() -> None:
    with pytest.raises(ValueError):
        hash_password("short")


def test_access_token_roundtrip_and_type_check() -> None:
    now = datetime(2026, 8, 20, tzinfo=UTC)
    token = encode_token({"sub": "user-1"}, "secret", "issuer", timedelta(minutes=15), "access", now)
    assert decode_token(token, "secret", "issuer", "access", now)["sub"] == "user-1"
    with pytest.raises(TokenError):
        decode_token(token, "secret", "issuer", "refresh", now)


def test_expired_token_is_rejected() -> None:
    issued = datetime(2026, 8, 20, tzinfo=UTC)
    token = encode_token({}, "secret", "issuer", timedelta(seconds=1), "access", issued)
    with pytest.raises(TokenError, match="истёк"):
        decode_token(token, "secret", "issuer", "access", issued + timedelta(seconds=1))


def test_tampered_token_is_rejected() -> None:
    token = encode_token({}, "secret", "issuer", timedelta(minutes=1), "access")
    with pytest.raises(TokenError):
        decode_token(token[:-1] + ("A" if token[-1] != "A" else "B"), "secret", "issuer", "access")


def test_totp_rfc_vector_and_window() -> None:
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert totp_code(secret, at=59, digits=8) == "94287082"
    current = totp_code(secret, at=90)
    assert verify_totp(secret, current, at=90)
    assert verify_totp(secret, current, at=119)
    assert not verify_totp(secret, "000000", at=90)
