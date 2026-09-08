"""
채점 임계값 설정.

⚠️ **이 값들은 교육적으로 검증되지 않았다 (not yet educationally validated).**

0.60 / 0.15 는 개발 중 "그럴듯해 보이는" 값으로 정한 것이고, 학습자가 어느 정도 그렸을 때
"학습완료"로 볼 수 있는지에 대한 근거는 아직 없다. 그래서 상수로 코드에 박아두지 않고
여기로 분리했다. 사용자 테스트 결과가 쌓이면 이 파일만 고쳐서 조정한다.

**임의로 바꾸지 않는다.** 바꾸면 과거 제출 이력의 grade 와 의미가 달라진다
(이미 저장된 Submission.grade 는 바뀌지 않으므로 통계가 섞인다).
조정 시에는 근거와 날짜를 아래 "변경 이력"에 남긴다.

  → docs/RELEASE_READINESS.md E3 (NEEDS_EXPERT_REVIEW)

환경변수로도 덮을 수 있게 해 둔 이유: 사용자 테스트에서 여러 값을 시험해 보기 위함이다.
운영 기본값을 바꾸려면 환경변수가 아니라 이 파일의 기본값을 고친다.

**잘못된 값은 조용히 무시하지 않고 오류로 막는다.** 예전에는 범위를 벗어나거나 읽을 수 없는
값을 기본값으로 되돌렸는데, 그러면 `MEDISCAN_MATCH_DICE=75`(75%를 의도) 같은 입력이
조용히 0.60 으로 채점되고 운영자는 0.75 인 줄 안다. 채점 기준이 의도와 다른데 서버는
겉보기에 정상인 상태가 가장 나쁘다.

변경 이력
- 2026-09-08: 최초 분리. 값은 기존과 동일(0.60 / 0.15) — 이번 작업에서 의미를 바꾸지 않았다.
- 2026-09-09: 잘못된 환경변수를 조용히 무시하던 것을 오류로 바꿨다. partial > match 순서
  뒤집힘도 막는다 (뒤집히면 partial_match 판정이 통째로 도달 불가능해진다).
  **기본값은 그대로 0.60 / 0.15** — 판정 의미는 바꾸지 않았다.
"""
import os

from app.config import ConfigError

# Dice 기준 판정 임계값
DEFAULT_MATCH_DICE = 0.60
DEFAULT_PARTIAL_DICE = 0.15

# 검증 상태 — 응답·문서에 그대로 노출해 "확정된 기준"으로 오해되지 않게 한다.
VALIDATION_STATUS = "not_yet_educationally_validated"


MATCH_ENV = "MEDISCAN_MATCH_DICE"
PARTIAL_ENV = "MEDISCAN_PARTIAL_DICE"


def _float_env(name: str, default: float) -> float:
    """Dice 임계값을 읽는다. 값이 이상하면 기본값으로 되돌리지 않고 **막는다**."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(
            f"{name} 를 숫자로 읽을 수 없습니다: {raw!r}. "
            f"Dice 임계값은 0.0~1.0 사이의 소수입니다 (예: {default})."
        ) from None
    if not 0.0 <= value <= 1.0:
        raise ConfigError(
            f"{name} 가 범위를 벗어났습니다: {value}. "
            f"Dice 임계값은 0.0~1.0 입니다 — 백분율이 아니라 비율로 적습니다 "
            f"(75% 는 75 가 아니라 0.75)."
        )
    return value


def match_dice() -> float:
    return _float_env(MATCH_ENV, DEFAULT_MATCH_DICE)


def partial_dice() -> float:
    return _float_env(PARTIAL_ENV, DEFAULT_PARTIAL_DICE)


def assert_valid() -> None:
    """기동 시점 점검. 채점이 처음 일어나는 순간이 아니라 뜰 때 막는다.

    순서가 뒤집히면(partial > match) `partial_match` 판정이 도달 불가능해지고,
    부분적으로 맞게 그린 학습자가 전부 `mismatch` 를 받는다. 등급 하나가 통째로
    사라져도 응답 형태는 정상이라 눈치채기 어렵다.
    """
    match, partial = match_dice(), partial_dice()
    if partial > match:
        raise ConfigError(
            f"{PARTIAL_ENV}({partial}) 가 {MATCH_ENV}({match}) 보다 큽니다. "
            "이 상태에서는 partial_match 판정이 나올 수 없어 부분 일치가 전부 "
            "mismatch 로 채점됩니다. partial <= match 여야 합니다."
        )


def thresholds() -> dict:
    """현재 적용 중인 임계값.

    채점 응답의 `evaluation.thresholds` 와 `/health` 의 `scoring` 양쪽에 실린다 —
    환경변수로 덮을 수 있는 값이라, 배포된 서버가 **실제로 어떤 기준으로 채점 중인지**
    눈으로 확인할 수 있어야 한다. validation_status 를 항상 함께 내보내
    "확정된 의학 기준"으로 읽히지 않게 한다.
    """
    return {
        "match_dice": match_dice(),
        "partial_dice": partial_dice(),
        "validation_status": VALIDATION_STATUS,
    }
