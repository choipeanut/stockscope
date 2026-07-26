"""Google OAuth + JWT 인증 엔드포인트."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from jose import jwt
from pydantic import BaseModel

from app.auth_dep import JWT_ALGORITHM, JWT_SECRET, get_current_user
from app.db import repo

router = APIRouter(prefix="/auth")
logger = logging.getLogger(__name__)

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
JWT_EXPIRE_DAYS = 30


def _verify_google_token(token: str) -> dict:
    """Google ID 토큰 검증 → payload 반환.

    cold start(Render 무료 플랜) 직후에는 Google 공개키 캐시가 비어 있어
    인증서를 네트워크로 새로 받아와야 한다. 이때 일시적인 네트워크 실패가
    나면 토큰이 멀쩡해도 검증이 터진다 — 그래서 재시도하고, 네트워크 문제와
    실제 잘못된 토큰을 구분해서 응답한다(503 vs 401).
    """
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID not configured on server")

    from google.auth.exceptions import GoogleAuthError, TransportError
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    last_transport_err: Exception | None = None
    for attempt in range(3):
        try:
            return id_token.verify_oauth2_token(
                token,
                google_requests.Request(),
                GOOGLE_CLIENT_ID,
                # 서버 시계가 살짝 어긋나도 "Token used too early"로 죽지 않게
                clock_skew_in_seconds=10,
            )
        except ValueError as e:
            # 토큰 자체가 잘못됨 (만료/audience 불일치/서명 오류) — 재시도 무의미
            raise HTTPException(status_code=401, detail=f"Google 토큰 검증 실패: {e}")
        except (TransportError, GoogleAuthError) as e:
            # Google 인증서 조회 실패 등 일시적 문제 — 재시도
            last_transport_err = e
            logger.warning("Google 인증서 조회 실패 (시도 %d/3): %s", attempt + 1, e)
            time.sleep(1.5 * (attempt + 1))

    raise HTTPException(
        status_code=503,
        detail=(
            "인증 서버 연결에 실패했습니다. 서버가 절전에서 깨어나는 중일 수 있습니다. "
            f"잠시 후 다시 시도해 주세요. ({last_transport_err})"
        ),
    )


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
