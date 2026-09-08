"""
비밀번호 해싱 + 액세스 토큰.

표준 라이브러리만 쓴다 (팀원이 pip 추가 설치 없이 바로 실행할 수 있도록):
  - 비밀번호: hashlib.scrypt (salt 포함, 검증된 KDF)
  - 토큰: HMAC-SHA256 로 서명한 payload.signature 형태 (JWT 와 같은 구조의 축소판)

실서비스로 갈 때 교체 지점:
  - 토큰을 표준 JWT 로 바꾸려면 create_access_token / decode_access_token 두 함수만 갈아끼우면 된다

**서명 키 규칙 (MEDISCAN_ENV 로 갈린다 — config.py)**
  development : MEDISCAN_SECRET_KEY 미설정이면 개발용 고정값 + 경고 (팀원이 바로 실행 가능)
  production  : 미설정이거나 개발용 고정값이면 **기동 실패**

개발용 고정값은 공개 저장소에 들어 있어 사실상 공개된 값이다. 배포에서 이 값으로 뜨면
토큰을 누구나 위조할 수 있으므로, 경고가 아니라 기동 실패로 막는다.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
import warnings

from app.config import ConfigError, is_production

_DEV_SECRET = "dev-only-insecure-secret-change-me"
_MIN_SECRET_LENGTH = 32

SECRET_KEY_ENV = "MEDISCAN_SECRET_KEY"


def _resolve_secret_key() -> str:
    configured = os.getenv(SECRET_KEY_ENV, "").strip()

    if is_production():
        if not configured:
            raise ConfigError(
                f"{SECRET_KEY_ENV} 가 설정되지 않았습니다. production 에서는 필수입니다.\n"
                f'  생성 예: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        if configured == _DEV_SECRET:
            raise ConfigError(
                f"{SECRET_KEY_ENV} 가 개발용 고정값입니다. 이 값은 공개 저장소에 있어 "
                "토큰 위조가 가능하므로 production 에서 쓸 수 없습니다."
            )
        if len(configured) < _MIN_SECRET_LENGTH:
            raise ConfigError(
                f"{SECRET_KEY_ENV} 가 너무 짧습니다 ({len(configured)}자). "
                f"{_MIN_SECRET_LENGTH}자 이상을 쓰세요."
            )
        return configured

    if not configured:
        warnings.warn(
            f"{SECRET_KEY_ENV} 가 설정되지 않아 개발용 고정 키를 씁니다. "
            "배포(MEDISCAN_ENV=production)에서는 기동이 실패합니다.",
            stacklevel=3,
        )
        return _DEV_SECRET
    return configured


SECRET_KEY = _resolve_secret_key()
TOKEN_TTL_SECONDS = int(os.getenv("MEDISCAN_TOKEN_TTL", str(60 * 60 * 24 * 7)))  # 기본 7일

# scrypt 파라미터 (n=2**14 는 대화형 로그인에 적당한 수준)
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DKLEN = 32


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


# --------------------------------------------------------------------- 비밀번호
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_DKLEN
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64e(salt)}${_b64e(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = _b64d(digest_b64)
        actual = hashlib.scrypt(
            password.encode(),
            salt=_b64d(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    # 타이밍 공격 방지를 위해 상수 시간 비교
    return hmac.compare_digest(expected, actual)


# ------------------------------------------------------------------------ 토큰
def create_access_token(user_id: str, ttl_seconds: int | None = None) -> str:
    """토큰마다 고유한 jti 를 넣는다.

    jti 가 있어야 **이 토큰 하나만** 폐기할 수 있다 (app/token_revocation.py).
    없으면 로그아웃할 때 그 사용자의 다른 기기 세션까지 같이 끊거나,
    아니면 아무것도 못 끊거나 둘 중 하나가 된다.
    """
    payload = {
        "sub": user_id,
        "jti": uuid.uuid4().hex,
        "iat": int(time.time()),
        "exp": int(time.time()) + (ttl_seconds if ttl_seconds is not None else TOKEN_TTL_SECONDS),
    }
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    signature = _b64e(hmac.new(SECRET_KEY.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{signature}"


def decode_access_token(token: str) -> dict | None:
    """유효하면 payload, 아니면 None (서명 불일치·만료·형식 오류 모두 None)."""
    try:
        body, signature = token.split(".")
    except ValueError:
        return None

    expected = _b64e(hmac.new(SECRET_KEY.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, signature):
        return None

    try:
        payload = json.loads(_b64d(body))
    except (ValueError, TypeError):
        return None

    if not isinstance(payload, dict) or "sub" not in payload:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload
