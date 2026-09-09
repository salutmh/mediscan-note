"""
보안 응답 헤더.

**왜 필요한가**
의료영상(민감정보)을 다루는 서비스인데 응답에 보안 헤더가 하나도 없었다.
브라우저가 스스로 막아줄 수 있는 공격이 몇 가지 있고, 헤더 한 줄이면 된다.

여기서 붙이는 것
---------------
  X-Content-Type-Options: nosniff
      브라우저가 Content-Type 을 무시하고 내용을 추측하지 못하게 한다.
      업로드된 파일이 스크립트로 해석되는 경로를 막는다.

  X-Frame-Options: DENY
      다른 사이트가 우리 화면을 iframe 으로 감싸는 것을 막는다 (클릭재킹).
      학습자가 자기 화면을 조작당하면 엉뚱한 곳에 동의하거나 탈퇴할 수 있다.

  Referrer-Policy: strict-origin-when-cross-origin
      외부로 나가는 요청에 **케이스 ID 가 들어간 URL 전체**가 실려 나가지 않게 한다.

  Cross-Origin-Opener-Policy: same-origin
      우리 창을 다른 출처가 붙잡지 못하게 한다.

  Permissions-Policy
      쓰지 않는 브라우저 기능(카메라·마이크·위치)을 아예 꺼둔다.
      쓰지 않는 권한을 열어둘 이유가 없다.

==========================================================================
**Content-Security-Policy 는 기본으로 켜지 않는다.**
==========================================================================
CSP 는 잘못 걸면 **화면이 조용히 깨진다** — 스크립트가 막혀 버튼이 동작하지 않는데
콘솔을 보지 않으면 알 수 없다. 프론트가 Vite 로 빌드되고 폰트·이미지 출처가 배포마다
다르므로, 정책을 실제 배포 형태에 맞춰 정한 뒤 켜야 한다.

`MEDISCAN_CSP` 로 정책 문자열을 직접 주면 그대로 붙인다.
**정책을 우리가 추측해서 만들지 않는다** — 잘못된 CSP 는 없는 것보다 나쁘다
(깨진 화면 + 안전하다는 착각).

HSTS 도 붙이지 않는다. HTTPS 종단은 앞단(프록시·CDN)이 담당하고, 앱이 임의로
`Strict-Transport-Security` 를 내보내면 프록시 설정과 어긋날 수 있다.
"""
import os

from starlette.middleware.base import BaseHTTPMiddleware

CSP_ENV = "MEDISCAN_CSP"

# 값이 상황에 따라 달라지지 않는 것들. 항상 같은 값이라 미들웨어에서 한 번에 붙인다.
STATIC_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    # 이 서비스는 카메라·마이크·위치를 쓰지 않는다
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}


def csp_policy() -> str | None:
    """설정된 CSP 정책. 없으면 None (붙이지 않는다).

    **추측해서 만들지 않는다.** 잘못된 CSP 는 화면을 조용히 깨뜨리면서
    안전하다는 착각만 준다.
    """
    value = os.getenv(CSP_ENV, "").strip()
    return value or None


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """모든 응답에 보안 헤더를 붙인다.

    **이미 있는 값은 덮어쓰지 않는다** — 앞단 프록시가 붙인 정책이 있으면 그쪽을 존중한다.
    """

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for name, value in STATIC_HEADERS.items():
            response.headers.setdefault(name, value)

        policy = csp_policy()
        if policy:
            response.headers.setdefault("Content-Security-Policy", policy)
        return response


def describe() -> dict:
    """/health 에 실을 현재 상태. 무엇이 켜져 있는지 배포 후 확인할 수 있어야 한다."""
    return {
        "headers": sorted(STATIC_HEADERS),
        "csp": "설정됨" if csp_policy() else f"미설정 ({CSP_ENV} 로 지정)",
        "hsts": "앞단(프록시·CDN)이 담당한다 — 앱은 내보내지 않는다",
    }
