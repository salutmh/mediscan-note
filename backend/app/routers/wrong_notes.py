"""
복습노트 (API 계약 v0.4). 경로/이름은 계약대로 wrong-notes 유지.

최신 제출이 match 가 아닌 케이스만 내려간다. 재도전해서 맞히면 목록에서 빠진다.
재도전 채점·저장은 submit(2-3)과 완전히 동일한 경로를 쓴다 (cases.grade_and_store).
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.models import Case
from app.repository import case_progress_map, wrong_note_items
from app.routers.cases import grade_and_store
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
