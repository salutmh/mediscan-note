"""
인증 엔드포인트 요청 수 제한.

**왜 필요한가**
지금은 /api/auth/login 을 초당 수백 번 호출해도 막는 것이 없다. 비밀번호 대입,
가입 스팸, SNS 토큰 추측이 전부 열려 있다. Closed Beta 는 URL 이 외부에 나가므로 최소선이 필요하다.

**왜 라이브러리를 안 쓰는가**
requirements 를 늘리지 않는다는 프로젝트 방침(팀원이 pip 추가 설치 없이 실행)을 지킨다.
필요한 것은 슬라이딩 윈도 카운터 하나뿐이라 표준 라이브러리로 충분하다.

**한계 (문서에 남긴다)**
- 프로세스 안 메모리에만 있다. 워커를 여러 개 띄우면 워커마다 따로 센다.
  Closed Beta 규모(단일 워커)에서는 문제가 없지만, 확장 시 Redis 같은 공유 저장소로 옮겨야 한다.
- 프록시 뒤에 있으면 X-Forwarded-For 의 첫 IP 를 쓴다. 신뢰할 수 있는 프록시가 앞에 있다는 전제다.

**production 에서 끄는 것에 대해**
개발·E2E 에서는 `MEDISCAN_RATE_LIMIT=0` 으로 끄고 돌린다(반복 실행하면 한도에 걸린다).
그 값이 배포에 따라가면 로그인 무차별 대입이 그대로 열리고, 서버는 겉보기에 정상이다.
그래서 production 에서는 `0` 을 거부한다. 앞단 프록시가 제한을 담당하는 정상 구성도
있으므로 그 경우에는 `MEDISCAN_RATE_LIMIT=external` 로 **의도를 명시**하게 했다.
"실수로 꺼짐"과 "다른 데서 하고 있음"은 구분되어야 한다.
"""
import logging
import os
import threading
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import ConfigError

logger = logging.getLogger(__name__)

ENABLED_ENV = "MEDISCAN_RATE_LIMIT"

# "METHOD 경로" -> (윈도 초, 최대 횟수). 인증·계정 관련 엔드포인트만 건다.
# 학습 흐름(제출/조회)은 정상 사용자가 빠르게 반복하는 것이 정상이라 걸지 않는다.
# 메서드까지 구분하는 이유: GET /api/auth/me 는 화면마다 호출되는 정상 트래픽이라
# 같은 경로의 DELETE 와 한도를 공유하면 안 된다.
RULES: dict[str, tuple[int, int]] = {
    "POST /api/auth/login": (60, 10),          # 비밀번호 대입 방지
    "POST /api/auth/signup": (3600, 10),       # 가입 스팸 방지
    "POST /api/auth/social-login": (60, 20),   # provider_token 추측 방지
    "DELETE /api/auth/me": (3600, 5),          # 탈퇴 반복 호출 방지
    "POST /api/auth/password": (3600, 10),     # 현재 비밀번호 대입 방지
    "POST /api/auth/password/reset": (3600, 10),  # 재설정 코드 대입 방지
}

# 테스트·개발에서 한도를 넉넉히 두고 싶을 때 배수로 조정한다.
MULTIPLIER_ENV = "MEDISCAN_RATE_LIMIT_MULTIPLIER"

# 앞단(프록시·WAF)에서 제한을 담당한다고 **명시**할 때 쓰는 값.
# production 에서 제한을 끄는 유일한 방법이다.
EXTERNAL = "external"

_OFF_VALUES = {"0", "false", "no", "off"}


def _raw_enabled() -> str:
    return os.getenv(ENABLED_ENV, "1").strip().lower()


def _enabled() -> bool:
    """기본 ON. 끄려면 MEDISCAN_RATE_LIMIT=0 (개발·테스트 편의).

    production 에서 `0` 은 config 가 막는다. 앞단에서 제한한다면 `external` 로 적는다.
    """
    raw = _raw_enabled()
    return raw not in _OFF_VALUES and raw != EXTERNAL


def _multiplier() -> int:
    try:
        return max(1, int(os.getenv(MULTIPLIER_ENV, "1")))
    except ValueError:
        return 1


def assert_valid() -> None:
    """기동 시점 점검. production 에서 제한이 조용히 꺼져 있지 않은지 본다."""
    from app import config

    if not config.is_production():
        return

    raw = _raw_enabled()
    if raw in _OFF_VALUES:
        raise ConfigError(
            f"{ENABLED_ENV}={raw!r} — production 에서 요청 수 제한을 그냥 끌 수 없습니다. "
            "이 값은 개발·E2E 편의용이라 배포 환경에 따라오기 쉬운데, 꺼지면 로그인 "
            "무차별 대입이 그대로 열리고 서버는 겉보기에 정상입니다. "
            f"앞단 프록시·WAF 가 제한을 담당한다면 {ENABLED_ENV}={EXTERNAL} 로 명시하세요."
        )

    multiplier = _multiplier()
    if multiplier > 1:
        raise ConfigError(
            f"{MULTIPLIER_ENV}={multiplier} — production 에서는 쓸 수 없습니다. "
            "이 배수는 모든 한도를 한꺼번에 늘리므로 로그인 대입 한도까지 함께 풀립니다. "
            "특정 한도를 조정해야 한다면 app/rate_limit.py 의 RULES 를 고치세요."
        )


def describe_status() -> dict:
    """/health 에 실을 현재 제한 상태.

    한도 자체(RULES)는 싣지 않는다 — 어차피 11번 두드리면 알 수 있는 값이라 비밀은
    아니지만, 굳이 표로 정리해서 내줄 이유도 없다. 운영자가 알아야 하는 것은
    "지금 제한이 켜져 있는가"와 "왜 꺼져 있는가" 두 가지다.
    """
    raw = _raw_enabled()
    if raw == EXTERNAL:
        mode = EXTERNAL
    elif raw in _OFF_VALUES:
        mode = "off"
    else:
        mode = "app"
    return {"enabled": _enabled(), "mode": mode, "multiplier": _multiplier()}


def describe() -> str | None:
    """production 에서 제한을 끈 상태면 기동 로그에 남긴다."""
    if _raw_enabled() == EXTERNAL:
        return (
            f"요청 수 제한을 앱에서 하지 않습니다 ({ENABLED_ENV}={EXTERNAL}). "
            "앞단 프록시·WAF 가 /api/auth/* 를 제한하고 있는지 확인하세요."
        )
    return None


class _SlidingWindow:
    """키별 요청 시각을 윈도 길이만큼만 들고 있다가 개수를 센다."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, window: int, limit: int, now: float) -> tuple[bool, int]:
        """(허용 여부, 재시도까지 남은 초)."""
        with self._lock:
            hits = self._hits[key]
            cutoff = now - window
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = int(hits[0] + window - now) + 1
                return False, max(retry_after, 1)
            hits.append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_window = _SlidingWindow()


def reset() -> None:
    """테스트에서 상태를 비운다 (테스트 간 카운터가 새지 않도록)."""
    _window.reset()


def client_key(request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = request.client
    return client.host if client else "unknown"


def _rule_for(method: str, path: str) -> tuple[int, int] | None:
    rule = RULES.get(f"{method.upper()} {path.rstrip('/') or '/'}")
    if rule is None:
        return None
    window, limit = rule
    return window, limit * _multiplier()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """RULES 에 등록된 경로에만 적용한다."""

    async def dispatch(self, request, call_next):
        if not _enabled():
            return await call_next(request)

        if request.method == "OPTIONS":  # CORS preflight 는 세지 않는다
            return await call_next(request)

        rule = _rule_for(request.method, request.url.path)
        if rule is None:
            return await call_next(request)

        window, limit = rule
        key = f"{client_key(request)}|{request.method}|{request.url.path}"
        allowed, retry_after = _window.check(key, window, limit, time.monotonic())
        if allowed:
            return await call_next(request)

        # 어떤 값이 들어왔는지는 남기지 않는다 (자격증명이 로그에 새면 안 된다)
        logger.warning("rate limit 초과: path=%s window=%ss limit=%s", request.url.path, window, limit)
        return JSONResponse(
            status_code=429,
            content={
                "error": True,
                "code": "RATE_LIMITED",
                "message": "요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요.",
            },
            headers={"Retry-After": str(retry_after)},
        )
