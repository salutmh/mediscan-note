"""
제출 이력에서 파생되는 조회들 (solved / 복습노트).

api-spec.md v0.4 기준. 3절이 WrongNote 를 "Submission 에서 grade≠match 인 것을 뷰로 뽑아도 됨"으로
열어놨으므로 별도 테이블 없이 여기서 계산한다. 기준은 **케이스별 최신 제출**이다
(예전에 틀렸다가 나중에 맞혔으면 복습노트에서 빠져야 한다).
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Submission


def _latest_submission_subquery(user_id: str):
    """사용자의 케이스별 최신 제출 시각."""
    return (
        select(
            Submission.case_id.label("case_id"),
            func.max(Submission.submitted_at).label("latest_at"),
        )
        .where(Submission.user_id == user_id)
        .group_by(Submission.case_id)
        .subquery()
    )


def latest_submissions(db: Session, user_id: str) -> list[Submission]:
    """케이스별 최신 제출 목록 (최근 시도 순)."""
    latest = _latest_submission_subquery(user_id)
    stmt = (
        select(Submission)
        .join(
            latest,
            (Submission.case_id == latest.c.case_id) & (Submission.submitted_at == latest.c.latest_at),
        )
        .where(Submission.user_id == user_id)
        .order_by(Submission.submitted_at.desc())
    )
    # 같은 시각에 두 건이 들어간 극단적 경우 중복이 생길 수 있어 케이스별로 하나만 남긴다
    seen: set[str] = set()
    result: list[Submission] = []
    for submission in db.scalars(stmt).all():
        if submission.case_id in seen:
            continue
        seen.add(submission.case_id)
        result.append(submission)
    return result


def has_matched_case_ids(db: Session, user_id: str) -> set[str]:
    """한 번이라도 'match' 를 받은 케이스 (화면 표기: 학습완료).

    한 번 달성하면 취소되지 않는 성취다. 나중에 다시 틀려도 이 집합에는 남는다 —
    그 경우 needs_review 가 함께 true 가 되어 두 상태가 동시에 표시된다 (api-spec v0.4).
    """
    stmt = select(Submission.case_id).where(
        Submission.user_id == user_id,
        Submission.grade == "match",
    )
    return set(db.scalars(stmt).all())


def wrong_note_items(db: Session, user_id: str) -> list[Submission]:
    """최신 제출이 match 가 아닌 케이스들 = 복습노트 (화면 표기: 복습필요)."""
    return [s for s in latest_submissions(db, user_id) if s.grade != "match"]


def needs_review_case_ids(db: Session, user_id: str) -> set[str]:
    """가장 최근 제출이 match 가 아닌 케이스."""
    return {s.case_id for s in wrong_note_items(db, user_id)}


def previous_attempt(db: Session, user_id: str, case_id: str) -> Submission | None:
    """이 케이스에 대한 **직전** 제출. 없으면 None (첫 시도).

    이번 제출을 저장하기 **전에** 불러야 한다.
    """
    return db.scalar(
        select(Submission)
        .where(Submission.user_id == user_id, Submission.case_id == case_id)
        .order_by(Submission.submitted_at.desc(), Submission.id.desc())
        .limit(1)
    )


def best_dice(db: Session, user_id: str, case_id: str) -> float | None:
    """지금까지 이 케이스에서 낸 최고 일치도. 없으면 None."""
    return db.scalar(
        select(func.max(Submission.dice)).where(
            Submission.user_id == user_id, Submission.case_id == case_id
        )
    )


# ---------------------------------------------------------------------------
# 케이스별 학습 상태 요약
# ---------------------------------------------------------------------------
# **화면이 쓸 수 있는 형태로 한 번에 모은다.**
# 지금까지 목록 화면은 has_matched / needs_review 두 boolean 만 받아서,
# "몇 번 풀었는지" "지난번보다 나아졌는지" 를 보여줄 수 없었다.
# 데이터는 submissions 에 다 있었는데 화면까지 가지 못했다.
#
# 케이스마다 질의를 따로 하면 N+1 이 된다 — 사용자당 한 번에 모아 온다.
def case_progress_map(db: Session, user_id: str) -> dict[str, dict]:
    """케이스별 시도 요약. `{case_id: {...}}`.

    한 번도 풀지 않은 케이스는 **키가 없다** (0 으로 채우지 않는다 —
    "0점"과 "아직 안 풀었음"은 다르다).
    """
    rows = db.execute(
        select(
            Submission.case_id,
            func.count(Submission.id),
            func.max(Submission.dice),
            func.max(Submission.location_score),
            func.max(Submission.submitted_at),
            func.min(Submission.submitted_at),
        )
        .where(Submission.user_id == user_id)
        .group_by(Submission.case_id)
    ).all()

    summary = {
        case_id: {
            "attempts": attempts,
            "best_dice": best,
            "best_location_score": best_location,
            "last_attempt_at": last_at,
            "first_attempt_at": first_at,
        }
        for case_id, attempts, best, best_location, last_at, first_at in rows
    }

    # 최신 제출의 등급·점수는 집계로 얻을 수 없다 (max(dice) 가 최신이 아니다)
    for submission in latest_submissions(db, user_id):
        entry = summary.setdefault(submission.case_id, {"attempts": 1})
        entry["latest_grade"] = submission.grade
        entry["latest_dice"] = submission.dice
        entry["latest_location_score"] = submission.location_score
    return summary


def recent_submissions(db: Session, user_id: str, limit: int = 8) -> list[Submission]:
    """최근 제출 (케이스 중복 허용). 학습 활동 타임라인용."""
    return list(
        db.scalars(
            select(Submission)
            .where(Submission.user_id == user_id)
            .order_by(Submission.submitted_at.desc(), Submission.id.desc())
            .limit(limit)
        ).all()
    )


def attempt_index(db: Session, user_id: str, case_id: str, submission_id: int) -> int:
    """이 제출이 그 케이스의 **몇 번째 시도**인가 (1부터).

    `attempt_number` 컬럼을 두지 않는 이유: 제출 행이 곧 시도이므로
    세면 된다. 컬럼을 두면 두 값이 어긋날 여지가 생긴다.
    """
    earlier = db.scalar(
        select(func.count(Submission.id)).where(
            Submission.user_id == user_id,
            Submission.case_id == case_id,
            Submission.id <= submission_id,
        )
    )
    return int(earlier or 1)
