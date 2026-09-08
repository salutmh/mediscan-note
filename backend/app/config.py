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


# ---------------------------------------------------- 개발 전용 스위치
# 아래 환경변수들은 **개발·테스트 편의용**이며, 켜지면 서비스가 사실과 다른 것을
# 사용자에게 보여준다. 각각이 무엇을 깨뜨리는지 함께 적어둔다 — 이름만 봐서는
# 위험도를 알 수 없기 때문이다.
#
# production 에서는 값이 붙어 있기만 해도 **기동을 막는다**. 이 셋은 배포 환경에
# "실수로 남아 있을" 수 있는 종류의 값이고(로컬 .env 복사, 데모 준비 후 원복 누락),
# 켜진 채로 뜨면 겉보기에는 멀쩡하게 동작하기 때문이다.
DEV_ONLY_FLAGS: dict[str, str] = {
    "MEDISCAN_ALLOW_APPROX_GRADING": (
        "좌표 근사 채점을 켠다. 전문가가 검수한 기준 마스크가 아니라 원(circle) 근사로 "
        "grade 를 매기므로, 학습자가 검수되지 않은 기준으로 평가받는다."
    ),
    "MEDISCAN_SEED_MOCK_CASES": (
        "합성 mock 케이스를 DB 에 넣는다. 실제 의료영상이 아닌 자리표시자가 "
        "학습 콘텐츠로 노출된다."
    ),
    "MEDISCAN_ANALYZE_DEMO": (
        "업로드 분석에 예시 응답을 돌려준다. 모델이 없는데 분석 결과가 있는 것처럼 보인다."
    ),
}

_FALSY = {"", "0", "false", "no", "off"}
_TRUTHY = {"1", "true", "yes", "on"}


def _looks_off(raw: str) -> bool:
    return raw.strip().lower() in _FALSY


def dev_only_flag(name: str) -> bool:
    """개발 전용 스위치를 읽는다.

    - 꺼져 있거나 미설정이면 False
    - production 에서 꺼져 있지 않으면 ConfigError (조용히 무시하지 않는다)
    - development 에서 알 수 없는 값(`maybe` 등)은 **켠 것으로 보지 않는다**
      — 위험한 쪽으로 기울지 않기 위해서다
    """
    raw = os.getenv(name, "")
    if _looks_off(raw):
        return False
    if is_production():
        raise ConfigError(
            f"{name} 은(는) 개발 전용 설정이라 production 에서 쓸 수 없습니다. "
            f"({DEV_ONLY_FLAGS.get(name, '개발 전용')}) "
            f"이 환경변수를 제거하고 다시 기동하세요."
        )
    return raw.strip().lower() in _TRUTHY


def assert_dev_only_flags_off() -> None:
    """기동 시점 점검. production 에 개발 전용 스위치가 남아 있으면 기동을 막는다.

    요청이 들어올 때가 아니라 **뜰 때** 막는다. 요청 시점에 막으면 이미 배포가 끝난
    뒤라 사용자가 먼저 만나게 된다.
    """
    if not is_production():
        return
    offenders = [name for name in DEV_ONLY_FLAGS if not _looks_off(os.getenv(name, ""))]
    if not offenders:
        return
    detail = "\n".join(f"  - {name}: {DEV_ONLY_FLAGS[name]}" for name in offenders)
    raise ConfigError(
        "production 에 개발 전용 설정이 켜져 있어 기동하지 않습니다.\n"
        f"{detail}\n"
        "해당 환경변수를 제거한 뒤 다시 기동하세요."
    )


def describe_dev_only_flags() -> list[str]:
    """개발 환경에서 켜져 있는 스위치 목록. 기동 로그에 남겨 눈에 띄게 한다."""
    return [name for name in DEV_ONLY_FLAGS if not _looks_off(os.getenv(name, ""))]
