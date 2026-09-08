"""
CORS 설정 — 개발 편의와 배포 안전을 분리한다.

  development : MEDISCAN_CORS_ORIGINS 를 안 주면 **localhost/127.0.0.1 의 아무 포트**를 허용한다.
                (프론트 5173, 미리보기 4173, 백엔드 포트를 바꿔도 그대로 동작)
  production  : MEDISCAN_CORS_ORIGINS 가 없으면 **기동 실패**. 와일드카드도 금지한다.

와일드카드를 production 에서 막는 이유: 이 API 는 Authorization 헤더로 인증한다.
아무 오리진에서나 호출되면 다른 사이트에 심어둔 스크립트가 사용자의 토큰으로 API 를 부를 수 있다.
"""
import os

from app.config import ConfigError, is_production

ORIGINS_ENV = "MEDISCAN_CORS_ORIGINS"

# 로컬 개발용 — 포트를 바꿔도 되도록 정규식으로 둔다.
DEV_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"


def _parse(raw: str) -> list[str]:
    return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]


def cors_kwargs() -> dict:
    """`app.add_middleware(CORSMiddleware, **cors_kwargs())` 에 그대로 넘긴다."""
    configured = _parse(os.getenv(ORIGINS_ENV, ""))

    if is_production():
        if not configured:
            raise ConfigError(
                f"{ORIGINS_ENV} 가 설정되지 않았습니다. production 에서는 필수입니다.\n"
                f"  예: {ORIGINS_ENV}=https://mediscan.example.com"
            )
        if "*" in configured:
            raise ConfigError(
                f"{ORIGINS_ENV} 에 와일드카드(*)는 쓸 수 없습니다. "
                "인증 토큰을 쓰는 API 라 실제 프론트 도메인만 허용해야 합니다."
            )
        return {
            "allow_origins": configured,
            "allow_credentials": True,
            "allow_methods": ["GET", "POST", "DELETE", "OPTIONS"],
            "allow_headers": ["Authorization", "Content-Type"],
        }

    # development
    if configured:
        return {
            "allow_origins": configured,
            "allow_credentials": True,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }
    return {
        "allow_origin_regex": DEV_ORIGIN_REGEX,
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }


def describe() -> str:
    """/health 에 노출할 한 줄 요약 (설정 실수를 빨리 알아채기 위함)."""
    configured = _parse(os.getenv(ORIGINS_ENV, ""))
    if configured:
        return ", ".join(configured)
    return f"regex:{DEV_ORIGIN_REGEX}"
