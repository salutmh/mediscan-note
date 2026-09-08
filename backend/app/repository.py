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
