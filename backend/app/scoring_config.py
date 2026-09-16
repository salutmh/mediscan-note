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
- 2026-09-16: `review_area_ratio`(기본 2.0) 추가. **Dice 임계값은 그대로 두었고
  grade 도 바꾸지 않았다** — 과대 표시 제출을 복습 목록에 담는 **경로**만 조정한다.
  계기: 기준 1,539px 에 3,400px(2.2배)을 칠해 정상 조직으로 55% 넘긴 제출이
  Dice 0.62 로 match 를 받고 학습완료 처리돼 복습에서 빠졌다. 같은 화면이
  "경계를 조금 더 좁혀 보세요"라고 말하는 중이었다.
  E3(임계값 0.60 자체의 타당성)는 **여전히 열려 있다** — 이 변경이 대신하지 않는다.
"""
import os

from app.config import ConfigError

# Dice 기준 판정 임계값
DEFAULT_MATCH_DICE = 0.60
DEFAULT_PARTIAL_DICE = 0.15

# 복습 대상으로 담는 **과대 표시** 배수 (기준 면적 대비).
#
# 왜 필요한가: Dice 0.60 만으로 판정하면 **기준을 통째로 덮되 훨씬 넓게 칠한** 제출이
# `match` 가 된다. 실제로 기준 1,539px 짜리 병변에 3,400px(2.2배)을 칠하고 정상 조직으로
# 55% 가 넘친 제출이 Dice 0.62 로 `match` 를 받았고, 그대로 학습완료 처리돼 복습 목록에서
# 빠졌다. 화면은 같은 순간에 "경계를 조금 더 좁혀 보세요"라고 말하고 있었다 —
# **피드백과 등급이 서로 다른 말을 하는데 학습 경로는 등급만 따르고 있었다.**
#
# 여기서 하는 일은 **경로 조정뿐이다. grade 는 건드리지 않는다.**
# "이 정도면 맞게 그린 것인가"(= 임계값 0.60 이 타당한가)는 전문가가 판단할 문제이고
# 아직 열려 있다(E3). 그 판단과 무관하게 "한 번 더 그려볼 가치가 있다"는 말은 할 수 있다.
#
# 값 2.0 역시 **검증된 값이 아니다** — Dice 임계값과 같은 지위다.
DEFAULT_REVIEW_AREA_RATIO = 2.0

# 검증 상태 — 응답·문서에 그대로 노출해 "확정된 기준"으로 오해되지 않게 한다.
VALIDATION_STATUS = "not_yet_educationally_validated"


MATCH_ENV = "MEDISCAN_MATCH_DICE"
PARTIAL_ENV = "MEDISCAN_PARTIAL_DICE"
REVIEW_AREA_ENV = "MEDISCAN_REVIEW_AREA_RATIO"


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


def review_area_ratio() -> float:
    """과대 표시 복습 기준. Dice 임계값과 달리 **1.0 이상의 배수**다.

    `_float_env` 를 쓰지 않는 이유가 여기 있다 — 그 함수는 0.0~1.0 을 강제하므로
    2.0 을 넣으면 "범위를 벗어났다"고 막는다. 단위가 다른 값이라 검사도 따로 한다.
    """
    raw = os.getenv(REVIEW_AREA_ENV, "").strip()
    if not raw:
        return DEFAULT_REVIEW_AREA_RATIO
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(
            f"{REVIEW_AREA_ENV} 를 숫자로 읽을 수 없습니다: {raw!r}. "
            f"기준 면적 대비 **배수**입니다 (예: {DEFAULT_REVIEW_AREA_RATIO} = 2배)."
        ) from None
    if value < 1.0:
        # 1.0 미만이면 기준보다 **작게** 칠한 것까지 과대 표시로 담게 된다.
        # 조용히 되돌리지 않고 막는다 (이 파일의 다른 값들과 같은 원칙).
        raise ConfigError(
            f"{REVIEW_AREA_ENV} 가 1.0 보다 작습니다: {value}. "
            "기준 면적 대비 배수이므로 1.0 이상이어야 합니다 "
            "(1.0 = 기준과 같은 넓이, 2.0 = 기준의 두 배)."
        )
    return value


def over_marked(area_ratio: float | None) -> bool:
    """이 제출이 **과대 표시로 복습 대상**인가.

    `area_ratio` 가 None 이면 False 다 — 기록하기 전에 쌓인 제출들이 여기 해당한다.
    모르는 것을 "괜찮았다"로도 "과했다"로도 단정하지 않는다.
    """
    if area_ratio is None:
        return False
    return area_ratio >= review_area_ratio()


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
        # grade 를 정하는 값이 아니라 **복습 경로**를 정하는 값이다. 같이 실어야
        # 배포된 서버가 무엇을 기준으로 복습을 권하는지 확인할 수 있다.
        "review_area_ratio": review_area_ratio(),
        "validation_status": VALIDATION_STATUS,
    }
