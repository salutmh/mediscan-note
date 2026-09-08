"""
공통 의존성 — 토큰에서 현재 사용자를 꺼낸다.

api-spec.md 0절: /api/cases/*, /api/wrong-notes/*, /api/analyze 는 로그인 필요, 토큰 없으면 401.
지금까지는 라우터가 토큰을 아예 보지 않아 누구나 호출할 수 있었는데, 이 의존성으로 실제로 막는다.
"""
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import decode_access_token


def _unauthorized(code: str, message: str) -> HTTPException:
    # api-spec.md 0절 공통 에러 포맷
    return HTTPException(
        status_code=401,
        detail={"error": True, "code": code, "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized("UNAUTHORIZED", "로그인이 필요합니다.")

    token = authorization.split(" ", 1)[1].strip()
    payload = decode_access_token(token)
    if payload is None:
        raise _unauthorized("INVALID_TOKEN", "토큰이 유효하지 않거나 만료되었습니다.")

    user = db.get(User, payload["sub"])
    if user is None:
        raise _unauthorized("USER_NOT_FOUND", "사용자를 찾을 수 없습니다.")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
DbSession = Annotated[Session, Depends(get_db)]
