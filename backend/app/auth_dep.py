"""JWT Bearer auth dependency — shared across all protected routers."""
from __future__ import annotations

import os

from fastapi import HTTPException, Header
from jose import JWTError, jwt

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-in-prod")
JWT_ALGORITHM = "HS256"


def get_current_user(authorization: str = Header(...)) -> dict:
    """Authorization: Bearer <token> 헤더에서 user 정보 추출."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization[7:]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return {
            "user_id": int(payload["sub"]),
            "email": payload.get("email", ""),
            "name": payload.get("name", ""),
            "picture": payload.get("picture", ""),
        }
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
