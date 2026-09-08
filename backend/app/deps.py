"""
공통 의존성 — 토큰에서 현재 사용자를 꺼낸다.

api-spec.md 0절: /api/cases/*, /api/wrong-notes/*, /api/analyze 는 로그인 필요, 토큰 없으면 401.
지금까지는 라우터가 토큰을 아예 보지 않아 누구나 호출할 수 있었는데, 이 의존성으로 실제로 막는다.
"""
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app import token_revocation
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

    # 로그아웃된 토큰은 서명이 멀쩡해도 거부한다 (app/token_revocation.py).
    # 공용 PC 에서 로그아웃한 뒤에도 토큰이 살아 있으면 안 된다.
    if token_revocation.is_revoked(db, payload.get("jti")):
        raise _unauthorized("TOKEN_REVOKED", "로그아웃된 토큰입니다. 다시 로그인해 주세요.")

    user = db.get(User, payload["sub"])
    if user is None:
        raise _unauthorized("USER_NOT_FOUND", "사용자를 찾을 수 없습니다.")
    return user


def current_token_payload(
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """현재 요청의 토큰 payload. 로그아웃처럼 **토큰 자체**를 다뤄야 할 때 쓴다.

    current_user 와 달리 사용자 객체가 아니라 payload(jti 포함)를 돌려준다.

    **의도적으로 폐기 목록을 보지 않는다.** 이미 로그아웃한 토큰으로 로그아웃을 또 불러도
    성공해야 하기 때문이다(멱등). 로그아웃은 토큰 외에 입력이 없고 폐기만 하므로,
    폐기된 토큰이 이 경로를 지나가도 얻을 수 있는 것이 없다.
    데이터를 만지는 엔드포인트는 전부 current_user 를 쓰고, 그쪽은 폐기 목록을 확인한다.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized("UNAUTHORIZED", "로그인이 필요합니다.")
    payload = decode_access_token(authorization.split(" ", 1)[1].strip())
    if payload is None:
        raise _unauthorized("INVALID_TOKEN", "토큰이 유효하지 않거나 만료되었습니다.")
    return payload


def current_admin(user: Annotated[User, Depends(current_user)]) -> User:
    """운영자 전용 엔드포인트 가드.

    권한이 없으면 **403** 이다(401 아님) — 로그인은 되어 있으나 권한이 없는 상태이므로.
    관리자 여부는 DB 의 users.is_admin 만 본다. 토큰에 담지 않는 이유는,
    담으면 권한을 회수해도 기존 토큰이 만료될 때까지 관리자로 남기 때문이다.
    """
    if not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail={"error": True, "code": "ADMIN_REQUIRED", "message": "운영자 권한이 필요합니다."},
        )
    return user


CurrentUser = Annotated[User, Depends(current_user)]
CurrentTokenPayload = Annotated[dict, Depends(current_token_payload)]
CurrentAdmin = Annotated[User, Depends(current_admin)]
DbSession = Annotated[Session, Depends(get_db)]
