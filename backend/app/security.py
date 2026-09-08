"""
비밀번호 해싱 + 액세스 토큰.

표준 라이브러리만 쓴다 (팀원이 pip 추가 설치 없이 바로 실행할 수 있도록):
  - 비밀번호: hashlib.scrypt (salt 포함, 검증된 KDF)
  - 토큰: HMAC-SHA256 로 서명한 payload.signature 형태 (JWT 와 같은 구조의 축소판)

실서비스로 갈 때 교체 지점:
  - SECRET_KEY 를 반드시 환경변수로 주입 (지금은 미설정 시 개발용 고정값 + 경고)
  - 토큰을 표준 JWT 로 바꾸려면 create_access_token / decode_access_token 두 함수만 갈아끼우면 된다
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import warnings

_DEV_SECRET = "dev-only-insecure-secret-change-me"
SECRET_KEY = os.getenv("MEDISCAN_SECRET_KEY", _DEV_SECRET)
TOKEN_TTL_SECONDS = int(os.getenv("MEDISCAN_TOKEN_TTL", str(60 * 60 * 24 * 7)))  # 기본 7일

if SECRET_KEY == _DEV_SECRET:
    warnings.warn(
        "MEDISCAN_SECRET_KEY 가 설정되지 않아 개발용 고정 키를 씁니다. 배포 전에 반드시 환경변수로 주입하세요.",
        stacklevel=2,
    )

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
    payload = {
        "sub": user_id,
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
