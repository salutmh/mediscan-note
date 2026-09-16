"""
복습노트 (API 계약 v0.4). 경로/이름은 계약대로 wrong-notes 유지.

최신 제출이 match 가 아닌 케이스만 내려간다. 재도전해서 맞히면 목록에서 빠진다.
재도전 채점·저장은 submit(2-3)과 완전히 동일한 경로를 쓴다 (cases.grade_and_store).
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.models import Case, Submission
from app.repository import attempt_index, case_progress_map, review_reason, wrong_note_items
from app.routers.cases import grade_and_store
from app import explanations
from app.static_files import absolute_url
from app.timefmt import to_kst_iso

router = APIRouter(prefix="/api/wrong-notes", tags=["wrong-notes"])

# 이 처리는 원래 여기에만 있었다. 다른 라우터가 따라가지 않아 화면마다 시각
# 기준이 달랐다 — 그래서 app/timefmt.py 로 옮겼다.
_to_kst_iso = to_kst_iso


@router.get("")
def list_wrong_notes(user: CurrentUser, db: DbSession):
    """복습노트 = **지금 재도전할 수 있는** 케이스 목록.

    운영자가 숨긴 케이스(is_active=false)와 삭제된 케이스는 제외한다.
    재도전할 수 없는 항목을 목록에 남겨두면 눌렀을 때 404 밖에 안 나오고,
    케이스를 숨긴 이유가 "기준 마스크에 문제가 있다"라면 잘못된 기준으로 학습이 이어진다.

    제출 이력 자체는 지우지 않는다 — 케이스를 다시 노출하면 복습노트에도 돌아온다.
    """
    items = wrong_note_items(db, user.user_id)
    case_ids = [s.case_id for s in items]
    case_map = {
        c.case_id: c
        for c in db.scalars(
            select(Case).where(Case.case_id.in_(case_ids), Case.is_active.is_(True))
        ).all()
    } if case_ids else {}
    # **시도 요약을 함께 싣는다.** 예전에는 케이스 ID·등급·시각뿐이라,
    # 복습노트가 "틀린 것 목록"이지 "얼마나 나아지고 있는지"를 보여주지 못했다.
    # 재도전이 이 서비스의 핵심 학습 루프인데 그 경과가 어디에도 없었다.
    progress = case_progress_map(db, user.user_id)
    return {
        "items": [
            {
                "case_id": s.case_id,
                "body_part": case_map[s.case_id].body_part,
                "disease": case_map[s.case_id].disease,
                "thumbnail_url": absolute_url(case_map[s.case_id].thumbnail_url),
                "grade": s.grade,
                # **왜 여기 담겼는지**를 함께 보낸다. grade 가 match 인데 목록에 있는
                # 항목이 생겼으므로(over_marked), 이유를 말하지 않으면 화면이
                # "일치했는데 왜 복습이지?"를 설명할 수 없다.
                "review_reason": review_reason(s),
                "area_ratio": s.area_ratio,
                "attempted_at": _to_kst_iso(s.submitted_at),
                # 값이 없으면 넣지 않는다 — 0 으로 채우면 "0점을 받았다"로 읽힌다
                "latest_dice": s.dice,
                "best_dice": (progress.get(s.case_id) or {}).get("best_dice"),
                "attempts": (progress.get(s.case_id) or {}).get("attempts", 1),
            }
            for s in items
            # 숨겨졌거나 삭제된 케이스는 재도전이 불가능하므로 목록에서 뺀다
            if s.case_id in case_map
        ]
    }


@router.get("/{case_id}")
def wrong_note_detail(case_id: str, user: CurrentUser, db: DbSession):
    """오답 상세 — **다시 풀기 전에 무엇을 놓쳤는지 먼저 보는 화면.**

    지금까지 해설은 **제출 직후에만** 볼 수 있었다. 복습노트에서 케이스를 누르면
    바로 판독 화면으로 갔고, 해설을 다시 보려면 또 제출해야 했다 —
    틀린 것을 복습하러 와서 무엇을 틀렸는지 못 보고 다시 칠하는 구조였다.

    **여기가 GT 노출의 경계다.** 기준 마스크는 `이 사용자가 이 케이스를 제출한 적이
    있을 때만` 나간다. 제출 이력이 없으면 404 다 — 아직 풀지 않은 케이스의 정답을
    이 경로로 미리 볼 수 없어야 한다 (`tests/test_wrong_note_detail.py`).

    해설은 **제출 시점 스냅샷**(`submissions.explanation`)을 쓴다. 전문가가 나중에
    소견을 고쳐도, 이 학습자가 그때 본 것은 그때 것이다.
    """
    last = db.scalars(
        select(Submission)
        .where(Submission.user_id == user.user_id, Submission.case_id == case_id)
        .order_by(Submission.submitted_at.desc(), Submission.id.desc())
        .limit(1)
    ).first()
    if last is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": True,
                "code": "NO_SUBMISSION",
                "message": "아직 제출한 적이 없는 케이스입니다.",
            },
        )

    case = db.get(Case, case_id)
    if case is None or not case.is_active:
        raise HTTPException(
            status_code=404,
            detail={"error": True, "code": "CASE_NOT_FOUND", "message": f"해당 케이스를 찾을 수 없습니다: {case_id}"},
        )

    progress = (case_progress_map(db, user.user_id).get(case_id)) or {}

    # 해설: 제출 당시 케이스 블록 + 지금의 질환 문헌 정보.
    # 케이스별 사실·소견은 **그때 본 것**을 쓰고, 질환 일반론은 문헌 파일에서 새로 붙인다
    # (문헌은 케이스에 매인 값이 아니라 버전이 있는 콘텐츠다).
    snapshot = last.explanation or {}
    explanation = explanations.build(case)
    explanation["case_facts"] = snapshot.get("case_facts") or explanation.get("case_facts")
    explanation["case_findings"] = snapshot.get("case_findings") or explanation.get("case_findings")

    return {
        "case_id": case.case_id,
        "body_part": case.body_part,
        "disease": case.disease,
        "image_url": absolute_url(case.image_url),
        "image_meta": case.image_meta or {},
        # 제출한 적이 있으므로 기준 마스크를 보여줘도 된다 (제출 응답에서 이미 받았다)
        "reference_mask_url": absolute_url(last.reference_mask_url),
        "latest": {
            "grade": last.grade,
            "dice": last.dice,
            "iou": last.iou,
            "location_score": last.location_score,
            "attempt_number": attempt_index(db, user.user_id, case_id, last.id),
            "submitted_at": _to_kst_iso(last.submitted_at),
            "is_provisional": last.is_provisional,
        },
        "attempts": progress.get("attempts", 1),
        "best_dice": progress.get("best_dice"),
        "explanation": explanation,
        # **사용자가 칠한 마스크는 저장하지 않는다.** 화면에서 그렇게 밝힌다 —
        # 없는 것을 있는 것처럼 그리지 않기 위해서다.
        "user_mask_kept": False,
    }


@router.post("/{case_id}/retry")
def retry_case(case_id: str, payload: dict, user: CurrentUser, db: DbSession):
    case = db.get(Case, case_id)
    # 숨긴 케이스는 재도전으로도 들어올 수 없어야 한다.
    # submit(2-3)만 막고 여기를 열어두면, 운영자가 문제 있는 케이스를 내려도
    # 복습노트 경로로 계속 채점이 이뤄진다 (잘못된 기준으로 학습이 이어진다).
    if case is None or not case.is_active:
        raise HTTPException(
            status_code=404,
            detail={"error": True, "code": "CASE_NOT_FOUND", "message": f"해당 케이스를 찾을 수 없습니다: {case_id}"},
        )

    roi = payload.get("roi") if isinstance(payload, dict) else None
    if not isinstance(roi, dict):
        raise HTTPException(
            status_code=400,
            detail={"error": True, "code": "INVALID_ROI", "message": "roi 가 필요합니다."},
        )
    # 재도전도 같은 경로로 채점된다. 회차(attempt_number)는 grade_and_store 가 센다 —
    # 첫 시도와 재도전의 점수 변화를 보려면 이 값이 필요하다.
    duration = payload.get("duration_seconds") if isinstance(payload, dict) else None
    return grade_and_store(case, roi, user, db, duration_seconds=duration)
