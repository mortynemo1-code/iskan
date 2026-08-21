import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type


password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65_536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


class TokenError(ValueError):
    pass


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Пароль должен содержать не менее 12 символов")
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except Exception as error:
        raise TokenError("Некорректный токен") from error


def encode_token(
    claims: dict[str, Any],
    secret: str,
    issuer: str,
    lifetime: timedelta,
    token_type: str,
    now: datetime | None = None,
) -> str:
    issued_at = now or datetime.now(UTC)
    payload = {
        **claims,
        "iss": issuer,
        "iat": int(issued_at.timestamp()),
        "nbf": int(issued_at.timestamp()),
        "exp": int((issued_at + lifetime).timestamp()),
        "typ": token_type,
    }
    header = {"alg": "HS256", "typ": "JWT"}
    parts = [
        _b64url_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode()),
        _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()),
    ]
    signing_input = ".".join(parts)
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def decode_token(
    token: str,
    secret: str,
    issuer: str,
    expected_type: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    try:
        header_encoded, payload_encoded, signature_encoded = token.split(".")
        header = json.loads(_b64url_decode(header_encoded))
        payload = json.loads(_b64url_decode(payload_encoded))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise TokenError("Некорректный токен") from error
    if header != {"alg": "HS256", "typ": "JWT"}:
        raise TokenError("Неподдерживаемый формат токена")
    signing_input = f"{header_encoded}.{payload_encoded}"
    expected_signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64url_encode(expected_signature), signature_encoded):
        raise TokenError("Некорректная подпись токена")
    timestamp = int((now or datetime.now(UTC)).timestamp())
    if payload.get("iss") != issuer or payload.get("typ") != expected_type:
        raise TokenError("Токен выпущен для другого контекста")
    if not isinstance(payload.get("exp"), int) or timestamp >= payload["exp"]:
        raise TokenError("Срок действия токена истёк")
    if not isinstance(payload.get("nbf"), int) or timestamp < payload["nbf"]:
        raise TokenError("Токен ещё не действует")
    return payload


def hash_refresh_token(token: str, secret: str) -> str:
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp_code(secret: str, at: int | None = None, step: int = 30, digits: int = 6) -> str:
    timestamp = int(time.time()) if at is None else at
    counter = timestamp // step
    padding = "=" * (-len(secret) % 8)
    try:
        key = base64.b32decode(secret.upper() + padding)
    except Exception as error:
        raise ValueError("Некорректный TOTP-секрет") from error
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return str(number).zfill(digits)


def verify_totp(secret: str, code: str, at: int | None = None, window: int = 1) -> bool:
    if len(code) != 6 or not code.isdigit():
        return False
    timestamp = int(time.time()) if at is None else at
    return any(
        hmac.compare_digest(totp_code(secret, timestamp + offset * 30), code)
        for offset in range(-window, window + 1)
    )


def totp_uri(secret: str, login: str, issuer: str) -> str:
    label = quote(f"{issuer}:{login}")
    return f"otpauth://totp/{label}?secret={quote(secret)}&issuer={quote(issuer)}&digits=6&period=30"
