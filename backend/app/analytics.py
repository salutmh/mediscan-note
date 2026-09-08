"""
학습 이벤트 기록 — Closed Beta 에서 "학습이 실제로 일어나는가"를 보기 위한 최소 로그.

**무엇을 알고 싶은가**
  - 케이스를 시작한 사람 중 몇 %가 제출까지 가는가
  - 첫 시도와 재도전 사이에 점수가 오르는가 (= 학습 효과의 최소 신호)
  - 해설을 여는가
  - 케이스 하나에 얼마나 걸리는가

==========================================================================
**개인정보를 과도하게 수집하지 않는다.**
==========================================================================
기록하는 것: user_id(내부 식별자), case_id, 이벤트 종류, 시각, 소요시간(초),
             제출이면 grade/dice, 시도 회차.
**기록하지 않는 것**: 이메일·닉네임·IP·User-Agent·ROI 마스크 원본·업로드 영상.
민감정보(의료영상)를 다루는 서비스라 "나중에 쓸지도 모르니 일단 다 남긴다"를 하지 않는다.

user_id 를 남기는 이유: 같은 사람의 첫 시도와 재도전을 이어야 학습 효과를 볼 수 있기 때문이다.
계정을 지우면 이벤트도 함께 지워진다 (users.user_id 외래키 + cascade).

**이 로그는 채점·학습 상태 계산에 쓰이지 않는다.** 순수 관찰용이다.
기록에 실패해도 학습 흐름을 막지 않는다.
"""
import logging
import os

from sqlalchemy.orm import Session

from app.models import LearningEvent

logger = logging.getLogger(__name__)

ENABLED_ENV = "MEDISCAN_ANALYTICS"

# 허용된 이벤트만 기록한다. 임의 문자열을 받으면 무엇이 쌓이는지 알 수 없게 된다.
CASE_OPENED = "case_opened"
SUBMISSION_GRADED = "submission_graded"
EXPLANATION_VIEWED = "explanation_viewed"

ALLOWED_EVENTS = (CASE_OPENED, SUBMISSION_GRADED, EXPLANATION_VIEWED)

# 클라이언트가 보낸 소요시간을 그대로 믿지 않는다 (조작·버그로 비현실적 값이 올 수 있다)
MAX_DURATION_SECONDS = 60 * 60 * 4


def enabled() -> bool:
    """기본 ON. 끄려면 MEDISCAN_ANALYTICS=0."""
    return os.getenv(ENABLED_ENV, "1").strip() not in {"0", "false", "False"}


def _clamp_duration(value) -> int | None:
    if value is None:
        return None
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return min(seconds, MAX_DURATION_SECONDS)


def record(
    db: Session,
    *,
    user_id: str,
    event: str,
    case_id: str | None = None,
    grade: str | None = None,
    dice: float | None = None,
    attempt_number: int | None = None,
    duration_seconds=None,
) -> LearningEvent | None:
    """이벤트 1건 기록. 실패해도 예외를 밖으로 내보내지 않는다.

    학습 흐름(제출·채점)이 관찰용 로그 때문에 막히면 안 된다.
    """
    if not enabled() or event not in ALLOWED_EVENTS:
        return None

    try:
        entry = LearningEvent(
            user_id=user_id,
            case_id=case_id,
            event=event,
            grade=grade,
            dice=dice,
            attempt_number=attempt_number,
            duration_seconds=_clamp_duration(duration_seconds),
        )
        db.add(entry)
        db.flush()  # commit 은 호출한 쪽 트랜잭션에 맡긴다
        return entry
    except Exception:
        logger.exception("학습 이벤트 기록 실패 (학습 흐름은 계속): event=%s case=%s", event, case_id)
        return None


def attempt_number(db: Session, user_id: str, case_id: str) -> int:
    """이번이 이 케이스의 몇 번째 제출인지 (1부터).

    첫 시도와 재도전의 점수를 비교하려면 회차가 필요하다.
    """
    from sqlalchemy import func, select

    from app.models import Submission

    previous = db.scalar(
        select(func.count())
        .select_from(Submission)
        .where(Submission.user_id == user_id, Submission.case_id == case_id)
    )
    return int(previous or 0) + 1
