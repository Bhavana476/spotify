"""Password hashing, JWT issue/verify and role checks shared by the REST API and the WebSocket gateway."""
import hashlib
import hmac
import html
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from . import config
from .db import get_session
from .models import User

ROLE_RANK = {"listener": 0, "co_dj": 1, "host": 2, "admin": 3}
_PBKDF2_ROUNDS = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), _PBKDF2_ROUNDS)
    return hmac.compare_digest(digest.hex(), digest_hex)


def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    claims = {"sub": str(user.id), "role": user.role, "name": user.display_name, "typ": "access",
              "iat": now, "exp": now + timedelta(minutes=config.ACCESS_TOKEN_MINUTES)}
    return jwt.encode(claims, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def create_refresh_token(user: User) -> tuple[str, str, datetime]:
    now = datetime.now(timezone.utc)
    jti = uuid.uuid4().hex
    expires = now + timedelta(days=config.REFRESH_TOKEN_DAYS)
    token = jwt.encode({"sub": str(user.id), "typ": "refresh", "jti": jti, "iat": now, "exp": expires},
                       config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)
    return token, jti, expires


def decode_token(token: str, expected_type: str = "access") -> dict:
    try:
        claims = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc
    if claims.get("typ") != expected_type:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")
    return claims


_bearer = HTTPBearer(auto_error=False)


async def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
                       session: AsyncSession = Depends(get_session)) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    claims = decode_token(creds.credentials)
    user = await session.get(User, int(claims["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return user


def require_role(minimum: str):
    async def checker(user: User = Depends(current_user)) -> User:
        if ROLE_RANK[user.role] < ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role '{minimum}' or higher")
        return user
    return checker


_TAG_RE = re.compile(r"<[^>]*>")


def sanitize_text(text: str, max_len: int = 500) -> str:
    """Strip control chars and all markup so stored chat can never become stored XSS. Angle brackets are
    removed outright (the client also renders text, never HTML); quotes are kept so text reads naturally."""
    cleaned = "".join(ch for ch in text if ch.isprintable() or ch == " ")
    cleaned = _TAG_RE.sub("", html.unescape(cleaned)).replace("<", "").replace(">", "")
    return re.sub(r"\s+", " ", cleaned).strip()[:max_len]
