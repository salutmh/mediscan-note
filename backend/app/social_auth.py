"""
SNS 로그인 토큰 실검증 (카카오 / 구글 / 네이버).

==========================================================================
**왜 필요한가 — 지금은 검증이 없어서 두 가지가 깨진다.**
==========================================================================
지금까지는 `provider_token` 을 **그대로 계정 식별자**로 썼다. 그래서:

  1) **남의 계정으로 들어갈 수 있다.** 토큰 값만 알면 그 계정으로 로그인된다.
     검증이 없으니 아무 문자열이나 넣어도 계정이 만들어지고, 같은 문자열을 넣으면
     그 계정이 열린다.
  2) **같은 사람이 새 계정이 된다.** SNS 액세스 토큰은 만료·갱신되는데, 토큰이
     식별자라서 갱신되면 다른 사람으로 보인다. 학습 이력이 갈린다.

토큰을 각 사 서버에 물어보면 **바뀌지 않는 사용자 식별자(subject)** 를 받는다.
그걸 저장해야 위 둘이 모두 해결된다.

각 사 확인 방법
--------------
  google  GET https://oauth2.googleapis.com/tokeninfo?id_token=<ID토큰>
          -> sub(식별자), aud(어느 앱에 발급됐는지). **aud 가 우리 client_id 인지 확인**한다.
             확인하지 않으면 다른 서비스용 토큰으로 우리 계정에 들어올 수 있다.
  kakao   GET https://kapi.kakao.com/v1/user/access_token_info  (Bearer)
          -> id(식별자), app_id(어느 앱 토큰인지). **app_id 를 확인**한다.
  naver   GET https://openapi.naver.com/v1/nid/me  (Bearer)
          -> response.id(식별자). 앱 확인 값이 응답에 없어 별도 대조는 하지 않는다.

설정
----
  MEDISCAN_OAUTH_GOOGLE_CLIENT_ID   구글 OAuth 클라이언트 ID (공개 값)
  MEDISCAN_OAUTH_KAKAO_APP_ID       카카오 앱 ID (숫자, 공개 값)
  MEDISCAN_OAUTH_NAVER_ENABLED      네이버 사용 여부 (1/true)

**셋 다 비밀이 아니다.** 실검증은 사용자가 가져온 토큰을 각 사에 되물어보는 방식이라
앱 시크릿이 필요 없다. 그래서 키 발급만 되면 바로 켤 수 있다.

설정되지 않았을 때
-----------------
  development  예전처럼 토큰을 그대로 식별자로 쓴다 (**검증 없는 예시 로그인**).
               기동 로그와 응답에 그렇게 표시된다.
  production   **거부한다.** 검증 없는 SNS 로그인은 계정 탈취 경로다.
               "아직 안 만들었다"와 "열려 있다"는 다르다.
"""
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

GOOGLE_CLIENT_ID_ENV = "MEDISCAN_OAUTH_GOOGLE_CLIENT_ID"
KAKAO_APP_ID_ENV = "MEDISCAN_OAUTH_KAKAO_APP_ID"
NAVER_ENABLED_ENV = "MEDISCAN_OAUTH_NAVER_ENABLED"

PROVIDERS = ("kakao", "google", "naver")

# 각 사 서버 응답을 기다리는 시간. 로그인 흐름이라 오래 붙잡고 있으면 안 된다.
TIMEOUT_SECONDS = 5

GOOGLE_TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"
KAKAO_TOKEN_INFO = "https://kapi.kakao.com/v1/user/access_token_info"
NAVER_ME = "https://openapi.naver.com/v1/nid/me"


# API 로 나가는 에러 코드. **동적으로 만들지 않는다** — f"SOCIAL_{reason.upper()}" 로
# 조립하면 코드를 grep 해도 안 나오고, 문서와 대조하는 검사도 볼 수 없다.
# 계약은 소스에 그대로 적혀 있어야 한다.
ERROR_CODES = {
    "invalid": "SOCIAL_INVALID",
    "wrong_audience": "SOCIAL_WRONG_AUDIENCE",
    "provider_unavailable": "SOCIAL_PROVIDER_UNAVAILABLE",
    "not_configured": "SOCIAL_NOT_CONFIGURED",
    "no_subject": "SOCIAL_NO_SUBJECT",
    "unsupported": "SOCIAL_UNSUPPORTED",
}

# 사유별 HTTP 상태. 제공자 장애와 토큰 문제는 사용자가 할 일이 다르다.
ERROR_STATUS = {
    "provider_unavailable": 503,
    "not_configured": 503,
}
DEFAULT_ERROR_STATUS = 401


class SocialAuthError(Exception):
    """토큰을 확인하지 못했을 때. 사유는 사용자에게 구분해 알려주지 않는다."""

    def __init__(self, message: str, *, reason: str = "invalid"):
        super().__init__(message)
        self.reason = reason


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_configured(provider: str) -> bool:
    """이 provider 의 실검증이 설정돼 있는가."""
    if provider == "google":
        return bool(os.getenv(GOOGLE_CLIENT_ID_ENV, "").strip())
    if provider == "kakao":
        return bool(os.getenv(KAKAO_APP_ID_ENV, "").strip())
    if provider == "naver":
        return _truthy(os.getenv(NAVER_ENABLED_ENV, ""))
    return False


def configured_providers() -> list[str]:
    return [p for p in PROVIDERS if is_configured(p)]


def _get_json(url: str, *, headers: dict | None = None) -> dict:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        # 4xx 는 토큰 문제, 5xx 는 제공자 장애 — 사용자에게 할 말이 다르다
        if 400 <= exc.code < 500:
            raise SocialAuthError("토큰이 유효하지 않습니다.", reason="invalid") from exc
        raise SocialAuthError(
            "로그인 제공자에 연결하지 못했습니다.", reason="provider_unavailable"
        ) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SocialAuthError(
            "로그인 제공자에 연결하지 못했습니다.", reason="provider_unavailable"
        ) from exc


def _verify_google(token: str) -> str:
    """구글 ID 토큰 -> sub.

    **aud 를 반드시 확인한다.** 확인하지 않으면 다른 서비스용으로 발급된 토큰으로
    우리 계정에 들어올 수 있다 (토큰 자체는 진짜라 서명 검증만으로는 못 막는다).
    """
    client_id = os.getenv(GOOGLE_CLIENT_ID_ENV, "").strip()
    data = _get_json(f"{GOOGLE_TOKENINFO}?id_token={urllib.parse.quote(token)}")

    audience = str(data.get("aud", ""))
    if audience != client_id:
        logger.warning(
            "구글 토큰의 aud 가 우리 앱이 아닙니다",
            extra={"event": "social_auth_wrong_audience", "provider": "google"},
        )
        raise SocialAuthError("다른 앱에서 발급된 토큰입니다.", reason="wrong_audience")

    subject = str(data.get("sub", "")).strip()
    if not subject:
        raise SocialAuthError("사용자 식별자를 받지 못했습니다.", reason="no_subject")
    return subject


def _verify_kakao(token: str) -> str:
    """카카오 액세스 토큰 -> id. app_id 로 우리 앱 토큰인지 확인한다."""
    app_id = os.getenv(KAKAO_APP_ID_ENV, "").strip()
    data = _get_json(KAKAO_TOKEN_INFO, headers={"Authorization": f"Bearer {token}"})

    if str(data.get("app_id", "")) != app_id:
        logger.warning(
            "카카오 토큰의 app_id 가 우리 앱이 아닙니다",
            extra={"event": "social_auth_wrong_audience", "provider": "kakao"},
        )
        raise SocialAuthError("다른 앱에서 발급된 토큰입니다.", reason="wrong_audience")

    subject = str(data.get("id", "")).strip()
    if not subject:
        raise SocialAuthError("사용자 식별자를 받지 못했습니다.", reason="no_subject")
    return subject


def _verify_naver(token: str) -> str:
    """네이버 액세스 토큰 -> response.id."""
    data = _get_json(NAVER_ME, headers={"Authorization": f"Bearer {token}"})

    if str(data.get("resultcode", "00")) != "00":
        raise SocialAuthError("토큰이 유효하지 않습니다.", reason="invalid")

    subject = str((data.get("response") or {}).get("id", "")).strip()
    if not subject:
        raise SocialAuthError("사용자 식별자를 받지 못했습니다.", reason="no_subject")
    return subject


VERIFIERS = {"google": _verify_google, "kakao": _verify_kakao, "naver": _verify_naver}


def verify(provider: str, token: str) -> str:
    """토큰을 각 사 서버에 물어보고 **바뀌지 않는 사용자 식별자**를 돌려준다."""
    verifier = VERIFIERS.get(provider)
    if verifier is None:
        raise SocialAuthError(f"지원하지 않는 제공자입니다: {provider}", reason="unsupported")
    if not token or not token.strip():
        raise SocialAuthError("토큰이 없습니다.", reason="invalid")
    return verifier(token.strip())


def resolve_subject(provider: str, token: str) -> tuple[str, bool]:
    """(계정 식별자, 실검증 여부).

    설정돼 있으면 각 사에 확인하고, 아니면 개발용 예시 경로를 탄다.
    **production 에서 설정되지 않은 경우는 여기 오기 전에 막힌다** (assert_usable).
    """
    if is_configured(provider):
        return verify(provider, token), True

    # 개발용 예시 경로 — 토큰을 그대로 식별자로 쓴다. 검증이 없다.
    logger.warning(
        "SNS 실검증이 설정되지 않아 예시 로그인으로 처리합니다 (개발 전용)",
        extra={"event": "social_auth_unverified", "provider": provider},
    )
    return token.strip(), False


def assert_usable(provider: str) -> None:
    """production 에서 검증 없는 SNS 로그인을 막는다.

    **"아직 안 만들었다"와 "열려 있다"는 다르다.** 검증이 없으면 토큰 값만 아는
    사람이 그 계정으로 들어간다 — 계정 탈취 경로를 열어둔 채로 배포할 수 없다.
    """
    from app import config

    if is_configured(provider) or not config.is_production():
        return
    raise SocialAuthError(
        f"{provider} 로그인이 아직 설정되지 않았습니다. 다른 방법으로 로그인해 주세요.",
        reason="not_configured",
    )


def describe() -> dict:
    """/health 와 배포 점검에 실을 상태."""
    verified = configured_providers()
    unverified = [p for p in PROVIDERS if p not in verified]
    return {
        "verified": verified,
        "unverified": unverified,
        "note": (
            "실검증되지 않은 제공자는 production 에서 거부됩니다 "
            "(검증 없는 SNS 로그인은 계정 탈취 경로입니다)."
            if unverified
            else "모든 제공자가 실검증됩니다."
        ),
    }
