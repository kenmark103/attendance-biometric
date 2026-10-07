import hashlib, secrets, time, uuid
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

from app.core import settings

ph = PasswordHasher()  # argon2id defaults
_DUMMY = ph.hash('timing-equalizer-not-a-real-password')

def hash_password(p: str) -> str:
    return ph.hash(p)

def verify_password(stored: str | None, supplied: str) -> bool:
    # Always runs a verify so unknown users cost the same as known ones.
    try:
        ph.verify(stored or _DUMMY, supplied)
        return stored is not None
    except (VerifyMismatchError, InvalidHashError):
        return False

def hash_refresh(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()

def new_refresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh(raw)

def create_access_token(user) -> tuple[str, int]:
    now = int(time.time())
    ttl = settings.ACCESS_TTL_SECONDS
    # `user` is a RealDictRow/dict (sync psycopg2 style used in this repo).
    claims = {
        'iss': 'attendance-api', 'aud': 'attendance-web',
        'sub': str(user['id']), 'email': user['email'], 'role': user['role'],
        'prov': user['auth_provider'], 'mcp': user['must_change_password'],
        'iat': now, 'exp': now + ttl, 'jti': uuid.uuid4().hex,
    }
    return jwt.encode(claims, settings.JWT_SECRET, algorithm='HS256'), ttl

def decode_access_token(token: str) -> dict:
    return jwt.decode(
        token, settings.JWT_SECRET, algorithms=['HS256'],
        audience='attendance-web', issuer='attendance-api',
        options={'require': ['exp', 'iat', 'sub']},
    )
