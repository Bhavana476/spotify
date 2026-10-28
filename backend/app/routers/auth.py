from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import RefreshToken, User
from ..schemas import LoginIn, RefreshIn, RegisterIn
from ..security import (create_access_token, create_refresh_token, current_user, decode_token, hash_password,
                        sanitize_text, verify_password)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def user_json(u: User) -> dict:
    return {"userId": u.id, "email": u.email, "displayName": u.display_name, "role": u.role}


async def _issue(session: AsyncSession, user: User) -> dict:
    refresh, jti, expires = create_refresh_token(user)
    session.add(RefreshToken(jti=jti, user_id=user.id, expires_at=expires))
    await session.commit()
    return {"accessToken": create_access_token(user), "refreshToken": refresh, "tokenType": "bearer",
            "user": user_json(user)}


@router.post("/register", status_code=201)
async def register(body: RegisterIn, session: AsyncSession = Depends(get_session)):
    email = body.email.lower()
    if (await session.execute(select(User).where(User.email == email))).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=email, display_name=sanitize_text(body.displayName, 40),
                password_hash=hash_password(body.password), role="listener")
    session.add(user)
    await session.flush()
    return await _issue(session, user)


@router.post("/login")
async def login(body: LoginIn, session: AsyncSession = Depends(get_session)):
    user = (await session.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return await _issue(session, user)


@router.post("/refresh")
async def refresh(body: RefreshIn, session: AsyncSession = Depends(get_session)):
    """Rotating refresh tokens: each refresh token is single-use."""
    claims = decode_token(body.refreshToken, expected_type="refresh")
    record = await session.get(RefreshToken, claims["jti"])
    if record is None or record.revoked:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token revoked")
    record.revoked = True
    user = await session.get(User, int(claims["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return await _issue(session, user)


@router.post("/logout", status_code=204)
async def logout(body: RefreshIn, session: AsyncSession = Depends(get_session)):
    claims = decode_token(body.refreshToken, expected_type="refresh")
    record = await session.get(RefreshToken, claims["jti"])
    if record:
        record.revoked = True
        await session.commit()


@router.get("/me")
async def me(user: User = Depends(current_user)):
    return {**user_json(user), "serverTime": datetime.now(timezone.utc).isoformat()}
