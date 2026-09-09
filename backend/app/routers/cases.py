"""
케이스 조회 / ROI 제출 (API 계약 v0.4).

- 채점 기준은 전문가 검수 reference mask 뿐이다 (grading.py). AI 예측은 참고 정보로만 붙는다.
- 기준 마스크가 없는 케이스는 채점하지 않는다: 422 CASE_NOT_GRADABLE, **제출 이력도 만들지 않는다.**
- 학습 상태는 has_matched(학습완료) / needs_review(복습필요) 두 축으로 내려간다.
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app import analytics, explanations
from app.deps import CurrentUser, DbSession
from app.grading import InvalidRoi, NotGradable, evaluate_submission, is_gradable
from app.models import Case, CaseSlice, Submission
from app.repository import (
    best_dice,
    case_progress_map,
    has_matched_case_ids,
    needs_review_case_ids,
    previous_attempt,
)
from app.static_files import absolute_url
from app.timefmt import to_kst_iso

router = APIRouter(prefix="/api/cases", tags=["cases"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": True, "code": code, "message": message})


def _not_found(case_id: str) -> HTTPException:
    return _error(404, "CASE_NOT_FOUND", f"해당 케이스를 찾을 수 없습니다: {case_id}")


def _extract_roi(payload) -> dict:
    roi = payload.get("roi") if isinstance(payload, dict) else None
    if not isinstance(roi, dict):
        raise _error(400, "INVALID_ROI", "roi 가 필요합니다.")
    return roi


def _progress(attempt: int, previous, previous_best, current_dice) -> dict:
    """이번 제출을 직전·최고 기록과 견준 결과.

    첫 시도면 비교 대상이 없다 — 그때는 previous 를 None 으로 두고 **없는 것을
    있는 척하지 않는다**(0 으로 채우면 "0에서 올랐다"로 읽힌다).
    """
    prior_dice = previous.dice if previous is not None else None
    improved = None
    if prior_dice is not None and current_dice is not None:
        improved = current_dice > prior_dice

    return {
        "attempt_number": attempt,
        "is_first_attempt": previous is None,
        "previous": None
        if previous is None
        else {
            "dice": previous.dice,
            "grade": previous.grade,
            "submitted_at": to_kst_iso(previous.submitted_at),
        },
        # 직전보다 나빠도 지금까지의 최고는 남는다 (학습자가 뒤로 갔다고 느끼지 않게)
        "best_dice": previous_best if previous_best is not None else current_dice,
        "improved": improved,
    }


def grade_and_store(case: Case, roi: dict, user, db, duration_seconds=None) -> dict:
    """채점 -> 이력 저장 -> 응답 본문. submit 과 retry 가 함께 쓴다.

    채점 불가/ROI 오류일 때는 **저장하지 않고** 예외를 던진다.
    """
    # 회차와 직전 기록은 이번 제출을 저장하기 **전에** 읽는다 (1부터)
    attempt = analytics.attempt_number(db, user.user_id, case.case_id)
    previous = previous_attempt(db, user.user_id, case.case_id)
    previous_best = best_dice(db, user.user_id, case.case_id)
    try:
        result = evaluate_submission(case, roi)
    except NotGradable as exc:
        raise _error(422, "CASE_NOT_GRADABLE", str(exc)) from exc
    except InvalidRoi as exc:
        raise _error(400, "INVALID_ROI", str(exc)) from exc

    db.add(
        Submission(
            user_id=user.user_id,
            case_id=case.case_id,
            grade=result["grade"],
            dice=result["dice"],
            iou=result["iou"],
            location_score=result["location_score"],
            reference_mask_url=result["reference_mask_url"],
            evaluation_method=result["evaluation"]["method"],
            is_provisional=result["evaluation"]["is_provisional"],
            # 이력에는 **케이스 단위 블록만** 남긴다. disease_info 는 질환 콘텐츠 파일에서
            # 매번 새로 붙으므로(문헌이 갱신되면 같이 바뀐다) 제출 시점 스냅샷에 넣지 않는다.
            explanation=explanations.stored_blocks(case),
        )
    )
    # 관찰용 로그. 실패해도 채점 흐름을 막지 않는다 (app/analytics.py)
    analytics.record(
        db,
        user_id=user.user_id,
        event=analytics.SUBMISSION_GRADED,
        case_id=case.case_id,
        grade=result["grade"],
        dice=result["dice"],
        attempt_number=attempt,
        duration_seconds=duration_seconds,
    )
    db.commit()

    # 재도전한 학습자가 **지난번보다 나아졌는지** 알 수 있어야 한다.
    # 회차는 원래도 계산하고 있었지만 운영자용 분석 로그로만 들어가서, 정작 다시 푼
    # 사람은 자기 변화를 볼 수 없었다. 재도전의 의미가 여기 있으므로 응답에 싣는다.
    #
    # 여기 있는 것은 **학습자 자신의 숫자**뿐이다 — 같은 전문가 기준 마스크와의 일치도를
    # 시점만 달리해 비교한다. 의학적 판단이 아니고 grade 에도 영향을 주지 않는다.
    result["progress"] = _progress(attempt, previous, previous_best, result["dice"])

    result["reference_mask_url"] = absolute_url(result.get("reference_mask_url"))
    if result.get("ai_prediction") and result["ai_prediction"].get("mask_url"):
        result["ai_prediction"]["mask_url"] = absolute_url(result["ai_prediction"]["mask_url"])
    return {"case_id": case.case_id, **result}


@router.get("")
def list_cases(user: CurrentUser, db: DbSession, body_part: str | None = None):
    # 비활성 케이스는 학습자에게 보이지 않는다 (운영자가 숨긴 것).
    # 숨김일 뿐 삭제가 아니라서 이미 쌓인 제출 이력은 그대로 남는다.
    stmt = select(Case).where(Case.is_active.is_(True)).order_by(Case.case_id)
    if body_part:
        stmt = stmt.where(Case.body_part == body_part)
    cases = db.scalars(stmt).all()

    matched = has_matched_case_ids(db, user.user_id)
    review = needs_review_case_ids(db, user.user_id)
    # **시도 요약을 함께 내려보낸다.** 목록이 has_matched/needs_review 두 boolean 만
    # 받던 시절에는 "몇 번 풀었는지"를 화면에 보여줄 수 없었다 — 데이터는
    # submissions 에 다 있었는데 화면까지 가지 못했다. 사용자당 한 번에 모아 온다.
    progress = case_progress_map(db, user.user_id)
    return {
        "cases": [
            {
                "case_id": c.case_id,
                "body_part": c.body_part,
                "disease": c.disease,
                "thumbnail_url": absolute_url(c.thumbnail_url),
                "has_matched": c.case_id in matched,
                "needs_review": c.case_id in review,
                "gradable": is_gradable(c),
                # 전문가가 지정한 난이도. 미지정이면 null 이고 화면에서 아무것도 표시하지 않는다
                # (추측해서 채우지 않는다 — CONTENT_GUIDELINES 6절).
                "difficulty": c.difficulty,
                # 한 번도 풀지 않았으면 **null 이다.** 0 으로 채우지 않는다 —
                # "0점"과 "아직 안 풀었음"은 완전히 다른 상태다.
                "progress": _case_progress(progress.get(c.case_id)),
            }
            for c in cases
        ]
    }


def _case_progress(entry: dict | None) -> dict | None:
    """목록 카드가 쓸 시도 요약. 없는 값은 넣지 않는다."""
    if not entry:
        return None
    return {
        "attempts": entry.get("attempts", 0),
        "best_dice": entry.get("best_dice"),
        "latest_dice": entry.get("latest_dice"),
        "latest_grade": entry.get("latest_grade"),
        "first_dice": entry.get("first_dice"),
        "first_grade": entry.get("first_grade"),
        "best_location_score": entry.get("best_location_score"),
        "last_attempt_at": _iso(entry.get("last_attempt_at")),
        "first_attempt_at": _iso(entry.get("first_attempt_at")),
    }


def _iso(value):
    # offset 없는 문자열을 내보내면 브라우저가 로컬 시간으로 읽는다 (app/timefmt.py)
    return to_kst_iso(value)


@router.post("/{case_id}/explanation-viewed", status_code=200)
def mark_explanation_viewed(case_id: str, user: CurrentUser, db: DbSession):
    """이 사용자가 이 케이스의 해설을 열었다고 기록한다.

    **왜 필요한가**: "틀린 뒤에 해설을 실제로 읽는가"는 콘텐츠에 시간을 쓸 가치가
    있는지를 가르는 지표다. 특히 전문가 소견(case_findings) 작성은 사람 시간이
    많이 드는 일이라(BLOCKER-2), 아무도 안 읽는다면 우선순위가 달라진다.

    같은 (사용자, 케이스) 는 **한 번만** 쌓인다. 화면을 오갈 때마다 기록하면
    "몇 명이 봤는가"가 같은 사람의 반복 조회에 묻힌다.

    관찰용이라 실패해도 사용자 흐름을 막지 않는다 — 항상 200 이다.
    """
    case = db.get(Case, case_id)
    if case is None or not case.is_active:
        raise _not_found(case_id)

    recorded = analytics.record_once(
        db, user_id=user.user_id, event=analytics.EXPLANATION_VIEWED, case_id=case.case_id
    )
    db.commit()
    # recorded=false 는 실패가 아니라 "이미 기록돼 있다" 이다.
    return {"recorded": recorded is not None}


@router.get("/{case_id}")
def get_case(case_id: str, user: CurrentUser, db: DbSession):
    case = db.get(Case, case_id)
    # 숨긴 케이스는 직접 URL 로 들어와도 열리지 않아야 한다.
    # 존재를 알려줄 이유가 없으므로 404 로 통일한다.
    if case is None or not case.is_active:
        raise _not_found(case_id)

    # "몇 명이 열어서 몇 명이 제출까지 가는가"를 보려면 시작 지점이 필요하다
    analytics.record(
        db, user_id=user.user_id, event=analytics.CASE_OPENED, case_id=case.case_id
    )
    db.commit()

    return {
        "case_id": case.case_id,
        "body_part": case.body_part,
        "disease": case.disease,
        "image_url": absolute_url(case.image_url),
        "image_meta": case.image_meta or {},
        "gradable": is_gradable(case),
        "difficulty": case.difficulty,
        "representative_slice": case.representative_slice,
        "slices": _slice_list(db, case),
    }


def _slice_list(db, case: Case) -> list[dict]:
    """학습자에게 내려보내는 slice 목록.

    ==========================================================================
    **마스크 정보를 절대 포함하지 않는다.**
    ==========================================================================
    어느 slice 에 기준 마스크가 있는지는 곧 **정답 위치**다. `has_mask` 같은 불리언
    하나만 있어도 학습자는 병변이 몇 번 slice 에 있는지 바로 알게 되고, 그러면
    "찾는" 훈련이 아니라 "표시된 곳을 칠하는" 작업이 된다.

    그래서 여기서는 slice_index 와 image_url 만 준다. 기준 마스크는 채점 결과
    (화면 3 오버레이)에서만 공개된다.
    """
    rows = db.scalars(
        select(CaseSlice)
        .where(CaseSlice.case_id == case.case_id)
        .order_by(CaseSlice.slice_index)
    ).all()
    return [
        {"slice_index": row.slice_index, "image_url": absolute_url(row.image_url)}
        for row in rows
    ]


@router.post("/{case_id}/submit")
def submit_case(case_id: str, payload: dict, user: CurrentUser, db: DbSession):
    case = db.get(Case, case_id)
    if case is None or not case.is_active:
        raise _not_found(case_id)
    # duration_seconds 는 선택이다. 없으면 소요시간만 비고 나머지는 그대로 기록된다.
    duration = payload.get("duration_seconds") if isinstance(payload, dict) else None
    return grade_and_store(case, _extract_roi(payload), user, db, duration_seconds=duration)
