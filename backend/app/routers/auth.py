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
from sqlalchemy.exc import IntegrityError

from app import password_reset, social_auth, token_revocation
from app.account import delete_account
from app.deps import CurrentTokenPayload, CurrentUser, DbSession
from app.models import Consent, User, utcnow
from app.schemas import (
    ChangePasswordRequest,
    ResetPasswordRequest,
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
    try:
        db.commit()
    except IntegrityError:
        # 같은 이메일로 가입 요청이 동시에 들어온 경우(가입 버튼 더블클릭, 응답이 느려서 재시도).
        # 위의 중복 검사와 이 INSERT 사이에 **scrypt 해싱**이 끼어 있다. 일부러 느리게
        # 만든 연산이라 경쟁 구간이 마이크로초가 아니라 사람이 두 번 누를 수 있는 폭이다.
        # 예전에는 여기서 IntegrityError 가 그대로 500 이 됐다 — 사용자에게는 "서버 오류"로
        # 보이지만 사실은 "이미 가입됨" 이다.
        db.rollback()
        if db.scalar(select(User).where(User.email == payload.email)) is None:
            raise  # 이메일 중복이 아닌 다른 무결성 오류는 숨기지 않는다
        raise _error(409, "EMAIL_ALREADY_EXISTS", "이미 가입된 이메일입니다.") from None
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
    # production 에서 실검증이 설정되지 않은 제공자는 거부한다.
    # 검증이 없으면 토큰 값만 아는 사람이 그 계정으로 들어간다 (계정 탈취 경로).
    try:
        social_auth.assert_usable(payload.provider)
        # **토큰이 아니라 각 사가 알려준 식별자를 계정 키로 쓴다.**
        # 토큰을 키로 쓰면 갱신될 때마다 같은 사람이 새 계정이 되어 학습 이력이 갈린다.
        subject, verified = social_auth.resolve_subject(payload.provider, payload.provider_token)
    except social_auth.SocialAuthError as exc:
        status = social_auth.ERROR_STATUS.get(exc.reason, social_auth.DEFAULT_ERROR_STATUS)
        code = social_auth.ERROR_CODES.get(exc.reason, "SOCIAL_INVALID")
        raise _error(status, code, str(exc)) from exc

    user = db.scalar(
        select(User).where(
            User.provider == payload.provider,
            User.provider_subject == subject,
        )
    )
    if user:
        # 기존 사용자 재로그인 — consents 는 무시 (api-spec.md 1-3)
        response = _auth_response(user, is_new_user=False)
        if not verified:
            response["provider_verified"] = False
        return response

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
        provider_subject=subject,
    )
    db.add(user)
    _save_consents(db, user.user_id, payload.consents)
    try:
        db.commit()
    except IntegrityError:
        # 같은 SNS 계정으로 최초 가입이 동시에 들어온 경우.
        # (provider, provider_subject) 유니크 제약 덕분에 계정이 둘로 갈리지는 않지만,
        # 두 번째 요청이 500 을 받았다. 재시도의 올바른 결과는 **기존 계정으로 로그인**이다.
        db.rollback()
        existing = db.scalar(
            select(User).where(
                User.provider == payload.provider,
                User.provider_subject == subject,
            )
        )
        if existing is None:
            raise
        return _auth_response(existing, is_new_user=False)
    db.refresh(user)
    response = _auth_response(user, is_new_user=True)
    if not verified:
        # 예시 로그인이라는 사실을 응답에도 남긴다 (화면이 숨기지 않게)
        response["provider_verified"] = False
    return response


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


@router.post("/password")
def change_password(payload: ChangePasswordRequest, user: CurrentUser, db: DbSession):
    """비밀번호 변경 — **다른 기기의 로그인을 모두 끊고** 새 토큰을 발급한다.

    비밀번호를 바꾸는 이유는 대개 "누가 내 계정을 쓰고 있는 것 같다"이다.
    다른 기기 세션이 살아 있으면 바꾼 의미가 없으므로 전부 무효화한다.
    지금 쓰는 이 기기만 새 토큰으로 이어서 쓸 수 있다.

    SNS 계정은 비밀번호가 없으므로 이 경로를 쓸 수 없다.
    """
    if not user.password_hash:
        raise _error(
            400,
            "PASSWORD_NOT_SET",
            "간편 로그인 계정은 비밀번호가 없어 변경할 수 없습니다.",
        )
    if not verify_password(payload.current_password, user.password_hash):
        raise _error(403, "INVALID_CURRENT_PASSWORD", "현재 비밀번호가 올바르지 않습니다.")
    if payload.current_password == payload.new_password:
        raise _error(400, "PASSWORD_UNCHANGED", "기존과 다른 비밀번호를 입력해 주세요.")

    user.password_hash = hash_password(payload.new_password)
    # 이 시각 이전에 발급된 토큰은 전부 무효가 된다 (app/deps.py).
    #
    # **초 단위로 내림한다.** 토큰의 iat 는 int(time.time()) 이라 초 단위인데 여기에
    # 마이크로초가 붙어 있으면, 바로 아래에서 새로 발급하는 토큰(iat = 같은 초)이
    # 컷오프보다 이르다고 판정돼 즉시 거부된다.
    # 그 대가로 "같은 초에 발급된 토큰"은 살아남는다 — 1초 미만의 창이고,
    # 공격자가 하필 그 초에 로그인해 있어야 하므로 감수한다.
    user.sessions_valid_from = utcnow().replace(microsecond=0)
    db.commit()

    # 방금 무효화한 범위에 지금 토큰도 들어가므로 새로 발급해 돌려준다
    return {
        "password_changed": True,
        "other_sessions_signed_out": True,
        "access_token": create_access_token(user.user_id),
        "token_type": "bearer",
    }


@router.post("/password/reset")
def reset_password(payload: ResetPasswordRequest, db: DbSession):
    """운영자에게 받은 일회용 코드로 비밀번호를 재설정한다. **로그인 없이 호출한다.**

    비밀번호를 잊으면 계정과 학습 이력을 영구히 잃기 때문에 필요한 경로다.
    본인 확인은 운영자가 오프라인으로 한다 (app/password_reset.py 참고).

    성공하면 **모든 기기의 로그인을 끊는다** — 계정을 되찾는 상황이므로
    남의 세션이 살아 있으면 안 된다.
    """
    try:
        user = password_reset.consume(db, payload.email, payload.code)
    except password_reset.ResetError as exc:
        # 실패 사유를 구분해 알려주지 않는다 (가입 여부를 코드 대입으로 알아낼 수 없게)
        db.rollback()
        raise _error(400, "INVALID_RESET_CODE", str(exc)) from exc

    user.password_hash = hash_password(payload.new_password)
    user.sessions_valid_from = utcnow().replace(microsecond=0)
    db.commit()

    return {
        "password_reset": True,
        "all_sessions_signed_out": True,
        # 새 비밀번호로 바로 로그인하게 둔다 (여기서 토큰을 주지 않는다 —
        # 코드만 가진 사람이 곧장 세션을 얻는 것보다 로그인을 한 번 더 거치는 편이 낫다)
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
