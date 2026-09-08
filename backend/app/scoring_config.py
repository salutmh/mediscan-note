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

변경 이력
- 2026-09-08: 최초 분리. 값은 기존과 동일(0.60 / 0.15) — 이번 작업에서 의미를 바꾸지 않았다.
"""
import os

# Dice 기준 판정 임계값
DEFAULT_MATCH_DICE = 0.60
DEFAULT_PARTIAL_DICE = 0.15

# 검증 상태 — 응답·문서에 그대로 노출해 "확정된 기준"으로 오해되지 않게 한다.
VALIDATION_STATUS = "not_yet_educationally_validated"


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if 0.0 <= value <= 1.0 else default


def match_dice() -> float:
    return _float_env("MEDISCAN_MATCH_DICE", DEFAULT_MATCH_DICE)


def partial_dice() -> float:
    return _float_env("MEDISCAN_PARTIAL_DICE", DEFAULT_PARTIAL_DICE)


def thresholds() -> dict:
    """현재 적용 중인 임계값 (응답·/health 에 노출해 무엇이 적용됐는지 보이게 한다)."""
    return {
        "match_dice": match_dice(),
        "partial_dice": partial_dice(),
        "validation_status": VALIDATION_STATUS,
    }
