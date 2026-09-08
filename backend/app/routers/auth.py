"""
회원가입 / 로그인 / SNS 간편가입 — DB 연동판.

이전 단계와 달라진 점:
- 사용자·동의 이력을 실제로 DB(users, consents)에 저장한다
- 비밀번호는 scrypt 로 해싱해 저장한다 (평문 저장 제거)
- 액세스 토큰은 HMAC 서명 + 만료가 있는 토큰이다 (security.py)
- /auth/me 가 토큰의 실제 사용자를 반환한다 (고정 데모유저 제거)

응답 스키마는 api-spec.md 1절 그대로 유지 — 프론트는 손댈 필요가 없다.

TODO(실서비스): SNS provider_token 을 각 사(카카오/구글/네이버) 서버에 검증 요청하는 로직.
지금은 provider_token 을 그대로 계정 식별자로 쓴다 (검증 없음).
"""
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app import token_revocation
from app.account import delete_account
from app.deps import CurrentTokenPayload, CurrentUser, DbSession
from app.models import Consent, User
from app.schemas import (
    Consents,
    DeleteAccountRequest,
    LoginRequest,
    SignupRequest,
    SocialLoginRequest,
)
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

MOCK_DIR = Path(__file__).resolve().parent.parent / "mock_data"


def _current_consent_version() -> str:
    """동의 이력에 함께 저장할 약관 버전 (consents_version.json 이 원본)."""
    path = MOCK_DIR / "consents_version.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")).get("version", "unknown")
    return "unknown"


def _new_user_id() -> str:
    return f"u_{uuid.uuid4().hex[:8]}"


def _error(status_code: int, code: str, message: str) -> HTTPException:
    # api-spec.md 0절 공통 에러 포맷
    return HTTPException(status_code=status_code, detail={"error": True, "code": code, "message": message})


def _save_consents(db: DbSession, user_id: str, consents: Consents) -> None:
    """동의 이력은 갱신하지 않고 append 로 쌓는다 (언제 몇 번 버전에 동의했는지 증빙)."""
    version = _current_consent_version()
    for key, agreed in consents.model_dump().items():
        db.add(Consent(user_id=user_id, key=key, agreed=bool(agreed), version=version))


def _auth_response(user: User, is_new_user: bool | None = None) -> dict:
    payload = {
        "user_id": user.user_id,
        "email": user.email,
        "nickname": user.nickname,
        "access_token": create_access_token(user.user_id),
        "token_type": "bearer",
    }
    if is_new_user is not None:
        payload["is_new_user"] = is_new_user
    return payload


@router.post("/signup")
def signup(payload: SignupRequest, db: DbSession):
    missing = payload.consents.missing_required()
    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "error": True,
                "code": "CONSENT_REQUIRED",
                "message": "필수 동의 항목에 모두 동의해야 가입할 수 있습니다.",
                "missing": missing,
            },
        )

    exists = db.scalar(select(User).where(User.email == payload.email))
    if exists:
        raise _error(409, "EMAIL_ALREADY_EXISTS", "이미 가입된 이메일입니다.")

    user = User(
        user_id=_new_user_id(),
        email=payload.email,
        password_hash=hash_password(payload.password),
        nickname=payload.nickname,
    )
    db.add(user)
    _save_consents(db, user.user_id, payload.consents)
    db.commit()
    db.refresh(user)
    return _auth_response(user)


@router.post("/login")
def login(payload: LoginRequest, db: DbSession):
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise _error(401, "INVALID_CREDENTIALS", "이메일 또는 비밀번호가 올바르지 않습니다.")
    return _auth_response(user)


@router.post("/social-login")
def social_login(payload: SocialLoginRequest, db: DbSession):
    user = db.scalar(
        select(User).where(
            User.provider == payload.provider,
            User.provider_subject == payload.provider_token,
        )
    )
    if user:
        # 기존 사용자 재로그인 — consents 는 무시 (api-spec.md 1-3)
        return _auth_response(user, is_new_user=False)

    # 신규 가입 — 동의 없이는 계정을 만들지 않는다
    missing = payload.consents.missing_required() if payload.consents else None
    if payload.consents is None or missing:
        raise HTTPException(
            status_code=400,
            detail={
                "error": True,
                "code": "CONSENT_REQUIRED",
                "message": "최초 가입 시 필수 동의 항목에 모두 동의해야 합니다.",
                "missing": missing if missing else ["consents"],
            },
        )

    user = User(
        user_id=_new_user_id(),
        nickname=f"{payload.provider}유저",
        provider=payload.provider,
        provider_subject=payload.provider_token,
    )
    db.add(user)
    _save_consents(db, user.user_id, payload.consents)
    db.commit()
    db.refresh(user)
    return _auth_response(user, is_new_user=True)


@router.get("/me")
def me(user: CurrentUser):
    return {"user_id": user.user_id, "email": user.email, "nickname": user.nickname}


@router.post("/logout")
def logout(payload: CurrentTokenPayload, db: DbSession):
    """로그아웃 — **이 토큰을 서버에서 폐기한다.**

    브라우저에서 토큰을 지우는 것만으로는 부족하다. 공용 PC 에서 로그아웃했는데
    그 토큰이 만료(기본 7일)까지 살아 있으면, 기록이나 로그에 남은 값으로 다시 들어올 수 있다.

    다른 기기의 로그인은 끊지 않는다 (토큰마다 jti 가 다르다).
    이미 폐기된 토큰으로 다시 불러도 성공으로 응답한다 — 로그아웃은 멱등해야 한다.
    """
    revoked = token_revocation.revoke(db, payload)
    return {
        "logged_out": True,
        # jti 가 없는 옛 토큰은 개별 폐기가 불가능하다. 사실대로 알린다.
        "token_revoked": revoked,
    }


@router.delete("/me")
def delete_me(
    user: CurrentUser,
    db: DbSession,
    token_payload: CurrentTokenPayload,
    payload: DeleteAccountRequest | None = None,
):
    """회원 탈퇴 — 계정·동의 이력·제출 이력을 모두 삭제한다. **되돌릴 수 없다.**

    이메일 계정은 비밀번호를 다시 받아 확인한다. 토큰만 있으면(예: 남의 기기에 남은 세션)
    계정이 통째로 지워지는 상황을 막기 위함이다.
    SNS 계정은 확인할 비밀번호가 없으므로 토큰만으로 진행한다.
    """
    if user.password_hash:
        password = payload.password if payload else None
        if not password or not verify_password(password, user.password_hash):
            raise _error(403, "PASSWORD_CONFIRMATION_REQUIRED", "탈퇴하려면 비밀번호를 다시 입력해야 합니다.")

    # 계정이 사라지면 그 토큰은 어차피 401 이지만, 폐기도 함께 남겨 방어선을 겹친다.
    token_revocation.revoke(db, token_payload)
    return delete_account(db, user)
