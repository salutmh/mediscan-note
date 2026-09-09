"""
케이스 자산(의료영상·기준 마스크) 접근 제어 — 서명 URL.

==========================================================================
**왜 필요한가 — 실제로 열려 있었다.**
==========================================================================
케이스 영상과 기준 마스크는 `/static/cases/<case_id>/...` 로 서빙되는데,
StaticFiles 에는 인증이 없다. `case_id` 는 `VS-SEG-202` 처럼 예측 가능해서
**로그인하지 않고도 URL 을 만들어 실제 의료영상을 받아갈 수 있었다.**
Closed Beta 는 URL 이 외부에 나가므로 이건 실제 문제다.

**왜 Bearer 토큰으로 막지 않는가**
화면이 `<img src="...">` 로 영상을 불러온다. img 태그에는 Authorization 헤더를
붙일 수 없다. 그래서 **URL 자체에 유효기간이 있는 서명**을 넣는다.

어떻게 동작하나
--------------
API 가 자산 URL 을 만들 때 `?e=<만료>&s=<서명>` 을 붙인다.
서명은 `HMAC-SHA256(경로 + 만료)` 이고 키는 `MEDISCAN_SECRET_KEY` 다.
미들웨어가 `/static/cases/` 요청을 가로채 서명을 확인한다.

  - 서명이 없거나 틀리면 403
  - 만료됐으면 403 (사유를 구분해 알려준다 — 새로 고치면 되는 상황이라)
  - `/static/cases/` 밖(mock 이미지 등)은 검사하지 않는다

**사용자를 특정하지 않는다.** 이건 "이 URL 을 아는 사람은 이 파일을 볼 수 있다"는
capability URL 이고, 로그인한 사람만 URL 을 받는다는 점으로 접근을 제한한다.
사용자별로 묶으면 캐시가 안 먹고 공유 링크가 깨지는데, 그만한 이득이 없다.

유효기간
-------
기본 24시간. 학습자가 케이스를 열어두고 한참 뒤에 slice 를 넘겨도 끊기지 않아야 한다
(케이스 상세 응답을 받은 시점에 URL 이 만들어지므로 그 뒤로 계속 쓰인다).
`MEDISCAN_ASSET_URL_TTL` 로 조정한다. **"영원히 공개"보다는 무엇이든 낫다.**
"""
import hashlib
import hmac
import logging
import os
import time
from urllib.parse import urlencode

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# 이 경로 아래만 보호한다. mock 이미지·데모 결과는 실제 의료영상이 아니다.
PROTECTED_PREFIX = "/static/cases/"

TTL_ENV = "MEDISCAN_ASSET_URL_TTL"
DEFAULT_TTL_SECONDS = 60 * 60 * 24  # 24시간

EXPIRY_PARAM = "e"
SIGNATURE_PARAM = "s"


def ttl_seconds() -> int:
    raw = os.getenv(TTL_ENV, "").strip()
    if not raw:
        return DEFAULT_TTL_SECONDS
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s 를 숫자로 읽을 수 없어 기본값을 씁니다: %r", TTL_ENV, raw)
        return DEFAULT_TTL_SECONDS
    # 너무 짧으면 학습 도중 끊기고, 너무 길면 사실상 공개다
    return max(60, min(value, 60 * 60 * 24 * 30))


def _secret() -> bytes:
    from app.security import SECRET_KEY

    return SECRET_KEY.encode() if isinstance(SECRET_KEY, str) else SECRET_KEY


def sign(path: str, expires_at: int) -> str:
    """경로 + 만료시각에 대한 서명. 경로가 바뀌면 서명도 달라진다."""
    message = f"{path}|{expires_at}".encode()
    return hmac.new(_secret(), message, hashlib.sha256).hexdigest()[:32]


def needs_signature(path: str) -> bool:
    return path.startswith(PROTECTED_PREFIX)


def signed_query(path: str, *, now: int | None = None) -> str:
    """`e=...&s=...` 쿼리 문자열."""
    expires_at = int(now or time.time()) + ttl_seconds()
    return urlencode({EXPIRY_PARAM: expires_at, SIGNATURE_PARAM: sign(path, expires_at)})


def add_signature(url: str, *, now: int | None = None) -> str:
    """자산 URL 에 서명을 붙인다. 보호 대상이 아니면 그대로 돌려준다.

    절대 URL(`http://host/static/cases/...`)과 상대 경로 둘 다 받는다 —
    서명은 **경로 부분에만** 건다 (호스트가 바뀌어도 URL 이 살아 있어야 한다).
    """
    if not url:
        return url

    # 이미 서명이 붙어 있으면 두 번 붙이지 않는다
    if f"{SIGNATURE_PARAM}=" in url:
        return url

    path = url
    if "://" in url:
        after_scheme = url.split("://", 1)[1]
        slash = after_scheme.find("/")
        if slash == -1:
            return url
        path = after_scheme[slash:]

    path = path.split("?", 1)[0]
    if not needs_signature(path):
        return url

    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{signed_query(path, now=now)}"


def verify(path: str, expiry: str | None, signature: str | None, *, now: int | None = None):
    """(통과 여부, 사유코드). 사유를 구분하는 이유는 만료면 새로 고치면 되기 때문이다."""
    if not expiry or not signature:
        return False, "ASSET_URL_UNSIGNED"
    try:
        expires_at = int(expiry)
    except ValueError:
        return False, "ASSET_URL_INVALID"

    current = int(now or time.time())
    if expires_at < current:
        return False, "ASSET_URL_EXPIRED"
    if not hmac.compare_digest(sign(path, expires_at), signature):
        return False, "ASSET_URL_INVALID"
    return True, None


MESSAGES = {
    "ASSET_URL_UNSIGNED": "이 영상은 로그인한 사용자에게만 제공됩니다.",
    "ASSET_URL_INVALID": "영상 주소가 올바르지 않습니다.",
    "ASSET_URL_EXPIRED": "영상 주소의 유효기간이 지났습니다. 화면을 새로 고쳐 주세요.",
}


class SignedAssetMiddleware(BaseHTTPMiddleware):
    """`/static/cases/` 요청의 서명을 확인한다.

    **여기서 막지 못하면 인증 없이 실제 의료영상이 나간다.**
    """

    async def dispatch(self, request, call_next):
        path = request.url.path
        if not needs_signature(path):
            return await call_next(request)

        ok, reason = verify(
            path,
            request.query_params.get(EXPIRY_PARAM),
            request.query_params.get(SIGNATURE_PARAM),
        )
        if ok:
            return await call_next(request)

        return JSONResponse(
            status_code=403,
            content={
                "error": True,
                "code": reason,
                "message": MESSAGES.get(reason, "영상에 접근할 수 없습니다."),
            },
        )


def describe() -> dict:
    """/health 에 실을 상태."""
    return {
        "protected_prefix": PROTECTED_PREFIX,
        "ttl_seconds": ttl_seconds(),
        "note": "케이스 영상·기준 마스크는 서명된 URL 로만 받을 수 있습니다.",
    }
