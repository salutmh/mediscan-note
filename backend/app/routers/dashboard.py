"""
학습 대시보드 — 사용자가 앱을 열었을 때 "지금 뭘 해야 하는가"에 답한다.

==========================================================================
**여기서 새로 만들어내는 값은 없다.**
==========================================================================
전부 `submissions` 에 이미 있는 것을 모아 보여줄 뿐이다.
지금까지는 데이터가 있어도 화면까지 오지 않아서, 홈이 그냥 케이스 격자였다.

지키는 것
---------
  * **의료적 난이도를 만들지 않는다.** 여기 나오는 숫자는 전부 사용자 자신의
    시도 기록이다. "이 케이스가 어렵다" 같은 판단을 하지 않는다.
  * **의학적 패턴을 추론하지 않는다.** "이런 병변을 자주 놓친다" 류의 일반화는
    우리가 할 수 있는 말이 아니다 (CONTENT_GUIDELINES).
  * **없는 값을 0 으로 채우지 않는다.** 한 번도 안 푼 것과 0점은 다르다.
  * 다음에 풀 케이스 추천은 **복습필요 우선 → 미시도 순**이라는 규칙일 뿐,
    난이도 판단이 아니다.
"""
from fastapi import APIRouter
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.grading import is_gradable
from app.models import Case
from app.repository import (
    case_progress_map,
    has_matched_case_ids,
    needs_review_case_ids,
    recent_submissions,
)
from app.static_files import absolute_url
from app.timefmt import to_kst_iso

router = APIRouter(prefix="/api/me", tags=["dashboard"])

RECENT_LIMIT = 8


def _iso(value):
    # **offset 이 반드시 붙어야 한다.** 없으면 브라우저가 로컬 시간으로 읽어
    # 방금 만든 기록이 "9시간 전"으로 보인다 (app/timefmt.py).
    return to_kst_iso(value)


def _case_brief(case: Case, reason: str) -> dict:
    return {
        "case_id": case.case_id,
        "body_part": case.body_part,
        "disease": case.disease,
        "thumbnail_url": absolute_url(case.thumbnail_url),
        # 왜 이걸 추천하는지 **화면에 그대로 쓸 수 있게** 내려보낸다.
        # 이유 없는 추천은 사용자가 신뢰하지 않는다.
        "reason": reason,
    }


@router.get("/dashboard")
def dashboard(user: CurrentUser, db: DbSession):
    cases = db.scalars(
        select(Case).where(Case.is_active.is_(True)).order_by(Case.case_id)
    ).all()
    by_id = {c.case_id: c for c in cases}

    matched = has_matched_case_ids(db, user.user_id)
    review = needs_review_case_ids(db, user.user_id)
    progress = case_progress_map(db, user.user_id)

    active_ids = set(by_id)
    # 비활성화된 케이스의 이력은 남아 있지만, 지금 풀 수 있는 것만 센다
    matched_active = matched & active_ids
    review_active = review & active_ids
    attempted_active = set(progress) & active_ids
    not_started = [c for c in cases if c.case_id not in attempted_active]

    # --- 다음에 풀 것 -------------------------------------------------
    # 복습필요를 먼저, 그다음 미시도. **난이도 판단이 아니라 순서 규칙이다.**
    next_up = None
    review_sorted = sorted(
        (by_id[cid] for cid in review_active),
        key=lambda c: progress.get(c.case_id, {}).get("last_attempt_at") or "",
    )
    if review_sorted:
        next_up = _case_brief(review_sorted[0], "needs_review")
    elif not_started:
        next_up = _case_brief(not_started[0], "not_started")
    elif cases:
        # 전부 학습완료 — 그래도 다시 풀 수 있다는 것을 알린다
        next_up = _case_brief(cases[0], "all_matched")

    # --- 최근 활동 -----------------------------------------------------
    recent = [
        {
            "case_id": s.case_id,
            "grade": s.grade,
            "dice": s.dice,
            "location_score": s.location_score,
            "submitted_at": _iso(s.submitted_at),
            "case_active": s.case_id in active_ids,
        }
        for s in recent_submissions(db, user.user_id, RECENT_LIMIT)
    ]

    # --- 최근 개선폭 ---------------------------------------------------
    # **같은 케이스의 마지막 두 시도**만 비교한다. 서로 다른 케이스의 점수를
    # 비교하면 "나아졌다"는 말이 성립하지 않는다 (케이스마다 병변이 다르다).
    improvement = _latest_improvement(db, user.user_id)

    dice_values = [
        entry["best_dice"] for entry in progress.values() if entry.get("best_dice") is not None
    ]

    return {
        "totals": {
            "total_cases": len(cases),
            "gradable_cases": sum(1 for c in cases if is_gradable(c)),
            "matched": len(matched_active),
            "needs_review": len(review_active),
            "attempted": len(attempted_active),
            "not_started": len(not_started),
            "total_attempts": sum(e.get("attempts", 0) for e in progress.values()),
        },
        "next_up": next_up,
        "recent_activity": recent,
        # 값이 없으면 null 이다 — 화면은 "아직 기록이 없습니다"를 보여준다
        "best_dice": max(dice_values) if dice_values else None,
        "latest_improvement": improvement,
        "has_any_activity": bool(progress),
    }


def _latest_improvement(db, user_id: str) -> dict | None:
    """가장 최근에 다시 푼 케이스에서 **직전 대비** 얼마나 달라졌는가.

    재도전이 이 서비스의 핵심 학습 루프인데, 지금까지 "다시 풀었다"는 사실만
    남고 **얼마나 나아졌는지**가 어디에도 보이지 않았다.
    """
    from app.models import Submission

    recent = db.scalars(
        select(Submission)
        .where(Submission.user_id == user_id)
        .order_by(Submission.submitted_at.desc(), Submission.id.desc())
        .limit(2 * RECENT_LIMIT)
    ).all()

    seen: dict[str, list] = {}
    for submission in recent:
        seen.setdefault(submission.case_id, []).append(submission)
        pair = seen[submission.case_id]
        if len(pair) == 2:
            latest, previous = pair
            if latest.dice is None or previous.dice is None:
                continue
            return {
                "case_id": latest.case_id,
                "previous_dice": previous.dice,
                "latest_dice": latest.dice,
                "delta": round(latest.dice - previous.dice, 4),
                "previous_grade": previous.grade,
                "latest_grade": latest.grade,
                "submitted_at": _iso(latest.submitted_at),
            }
    return None
