"""Password hashing, JWT handling and opaque token helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config.settings import settings
from app.core.errors import BadRequestError, UnauthorizedError

_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; normalise for safe comparison."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def validate_password_strength(password: str) -> None:
    """Deterministic password policy. Returns 422 with a helpful message on failure."""
    problems: list[str] = []
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        problems.append(f"must be at least {settings.PASSWORD_MIN_LENGTH} characters")
    if not any(c.islower() for c in password):
        problems.append("must contain a lowercase letter")
    if not any(c.isupper() for c in password):
        problems.append("must contain an uppercase letter")
    if not any(c.isdigit() for c in password):
        problems.append("must contain a digit")
    if password.lower() in {"password", "12345678", "letmein", "qwerty123"}:
        problems.append("is too common")
    if problems:
        raise BadRequestError("Password " + ", ".join(problems) + ".", code="weak_password")


def create_access_token(
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    role: str | None,
    is_superadmin: bool = False,
    expires_minutes: int | None = None,
) -> tuple[str, datetime]:
    issued_at = utcnow()
    expires_at = issued_at + timedelta(minutes=expires_minutes or settings.ACCESS_TOKEN_TTL_MINUTES)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org": str(organization_id) if organization_id else None,
        "role": role,
        "sa": is_superadmin,
        "type": "access",
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": int(issued_at.timestamp()),
        "nbf": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expires_at


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
            options={"require": ["exp", "iat", "sub", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Access token has expired.", code="token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Access token is invalid.", code="invalid_token") from exc
    if payload.get("type") != "access":
        raise UnauthorizedError("Token type is not valid for this endpoint.", code="invalid_token")
    return payload


def generate_opaque_token(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def new_id() -> uuid.UUID:
    return uuid.uuid4()
