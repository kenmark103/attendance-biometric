"""Password, opaque-refresh-token, and application-JWT primitives."""
import hashlib
import secrets
import time
import uuid

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core import settings


ph = PasswordHasher()  # Argon2id with a per-password salt.
_DUMMY = ph.hash("timing-equalizer-not-a-real-password")


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(stored: str | None, supplied: str) -> bool:
    """Always verify a hash to avoid an account-existence timing oracle."""
    try:
        ph.verify(stored or _DUMMY, supplied)
        return stored is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_needs_rehash(stored: str | None) -> bool:
    return bool(stored and ph.check_needs_rehash(stored))


def hash_refresh(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    # token_urlsafe(48) contains substantially more than the 32-byte minimum.
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh(raw)


def create_access_token(user) -> tuple[str, int]:
    now = int(time.time())
    ttl = settings.ACCESS_TOKEN_TTL_MINUTES * 60
    claims = {
        "sub": str(user["id"]),
        "email": user["email"],
        "role": user["role"],
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": now,
        "exp": now + ttl,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM), ttl


def decode_access_token(token: str) -> dict:
    return jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        audience=settings.JWT_AUDIENCE,
        issuer=settings.JWT_ISSUER,
        options={"require": ["sub", "exp", "iat", "iss", "aud", "role"]},
    )
