"""
실행 환경 설정 — development / production 구분.

**왜 이 파일이 필요한가**
개발 편의를 위한 기본값(고정 서명 키, CORS 전체 허용)이 배포에 그대로 따라가면 사고가 된다.
그렇다고 개발에서까지 매번 환경변수를 채우게 하면 팀원이 실행을 못 한다.
그래서 `MEDISCAN_ENV` 하나로 갈라서, **production 에서는 위험한 기본값을 아예 금지**한다.

  MEDISCAN_ENV=development (기본)  개발 기본값 허용 + 경고
  MEDISCAN_ENV=production          필수 값이 없으면 **기동 실패** (조용히 뜨지 않는다)

기동 실패를 택한 이유: 잘못된 설정으로 뜬 서버는 겉보기에 정상이라 아무도 눈치채지 못한다.
"""
import os

DEVELOPMENT = "development"
PRODUCTION = "production"

ENV_VAR = "MEDISCAN_ENV"


class ConfigError(RuntimeError):
    """배포 설정이 안전하지 않을 때. 기동을 막는다."""


def env() -> str:
    """현재 실행 환경. 알 수 없는 값은 development 로 떨어뜨리지 않고 오류로 잡는다."""
    raw = os.getenv(ENV_VAR, DEVELOPMENT).strip().lower()
    if raw in {"prod", PRODUCTION}:
        return PRODUCTION
    if raw in {"dev", DEVELOPMENT, "local", "test", ""}:
        return DEVELOPMENT
    raise ConfigError(
        f"{ENV_VAR} 값을 알 수 없습니다: {raw!r} "
        f"(사용 가능: {DEVELOPMENT} | {PRODUCTION})"
    )


def is_production() -> bool:
    return env() == PRODUCTION
