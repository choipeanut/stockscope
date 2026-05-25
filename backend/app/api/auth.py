"""Google OAuth + JWT 인증 엔드포인트."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from jose import jwt
from pydantic import BaseModel

from app.auth_dep import JWT_ALGORITHM, JWT_SECRET, get_current_user
from app.db import repo

router = APIRouter(prefix="/auth")

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
JWT_EXPIRE_DAYS = 30


def _verify_google_token(token: str) -> dict:
    """Google ID 토큰 검증 → payload 반환."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID not configured on server")
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        idinfo = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
        )
        return idinfo
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Google 토큰 검증 실패: {e}")


def _make_jwt(user_id: int, email: str, name: str, picture: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "name": name,
        "picture": picture,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


class GoogleTokenRequest(BaseModel):
    token: str  # Google ID token (credential from @react-oauth/google)


@router.post("/google")
def google_login(req: GoogleTokenRequest) -> dict:
    """Google ID 토큰으로 로그인 → JWT 반환."""
    idinfo = _verify_google_token(req.token)

    google_sub = idinfo["sub"]
    email = idinfo.get("email", "")
    name = idinfo.get("name", "")
    picture = idinfo.get("picture", "")

    user = repo.upsert_user(google_sub, email, name, picture)

    access_token = _make_jwt(user["id"], email, name, picture)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "email": email,
            "name": name,
            "picture": picture,
        },
    }


@router.get("/me")
def me(user: dict = Depends(get_current_user)) -> dict:
    """현재 로그인 유저 정보 반환."""
    return user
