"""
케이스 조회 / ROI 제출 (API 계약 v0.4).

- 채점 기준은 전문가 검수 reference mask 뿐이다 (grading.py). AI 예측은 참고 정보로만 붙는다.
- 기준 마스크가 없는 케이스는 채점하지 않는다: 422 CASE_NOT_GRADABLE, **제출 이력도 만들지 않는다.**
- 학습 상태는 has_matched(학습완료) / needs_review(복습필요) 두 축으로 내려간다.
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app import explanations
from app.deps import CurrentUser, DbSession
from app.grading import InvalidRoi, NotGradable, evaluate_submission, is_gradable
from app.models import Case, Submission
from app.repository import has_matched_case_ids, needs_review_case_ids
from app.static_files import absolute_url

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


def grade_and_store(case: Case, roi: dict, user, db) -> dict:
    """채점 -> 이력 저장 -> 응답 본문. submit 과 retry 가 함께 쓴다.

    채점 불가/ROI 오류일 때는 **저장하지 않고** 예외를 던진다.
    """
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
    db.commit()

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
            }
            for c in cases
        ]
    }


@router.get("/{case_id}")
def get_case(case_id: str, user: CurrentUser, db: DbSession):
    case = db.get(Case, case_id)
    # 숨긴 케이스는 직접 URL 로 들어와도 열리지 않아야 한다.
    # 존재를 알려줄 이유가 없으므로 404 로 통일한다.
    if case is None or not case.is_active:
        raise _not_found(case_id)
    return {
        "case_id": case.case_id,
        "body_part": case.body_part,
        "disease": case.disease,
        "image_url": absolute_url(case.image_url),
        "image_meta": case.image_meta or {},
        "gradable": is_gradable(case),
    }


@router.post("/{case_id}/submit")
def submit_case(case_id: str, payload: dict, user: CurrentUser, db: DbSession):
    case = db.get(Case, case_id)
    if case is None or not case.is_active:
        raise _not_found(case_id)
    return grade_and_store(case, _extract_roi(payload), user, db)
