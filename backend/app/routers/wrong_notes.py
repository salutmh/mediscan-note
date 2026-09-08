"""
복습노트 (API 계약 v0.4). 경로/이름은 계약대로 wrong-notes 유지.

최신 제출이 match 가 아닌 케이스만 내려간다. 재도전해서 맞히면 목록에서 빠진다.
재도전 채점·저장은 submit(2-3)과 완전히 동일한 경로를 쓴다 (cases.grade_and_store).
"""
from datetime import timedelta, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.models import Case
from app.repository import wrong_note_items
from app.routers.cases import grade_and_store

router = APIRouter(prefix="/api/wrong-notes", tags=["wrong-notes"])

KST = timezone(timedelta(hours=9))


def _to_kst_iso(value) -> str | None:
    """api-spec.md 0절: 날짜는 ISO 8601 (예: 2026-09-10T14:00:00+09:00)."""
    if value is None:
        return None
    if value.tzinfo is None:  # SQLite 는 tz 정보를 잃을 수 있다
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(KST).isoformat()


@router.get("")
def list_wrong_notes(user: CurrentUser, db: DbSession):
    items = wrong_note_items(db, user.user_id)
    case_ids = [s.case_id for s in items]
    case_map = {
        c.case_id: c
        for c in db.scalars(select(Case).where(Case.case_id.in_(case_ids))).all()
    } if case_ids else {}
    return {
        "items": [
            {
                "case_id": s.case_id,
                "body_part": case_map[s.case_id].body_part if s.case_id in case_map else None,
                "grade": s.grade,
                "attempted_at": _to_kst_iso(s.submitted_at),
            }
            for s in items
        ]
    }


@router.post("/{case_id}/retry")
def retry_case(case_id: str, payload: dict, user: CurrentUser, db: DbSession):
    case = db.get(Case, case_id)
    if case is None:
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
    return grade_and_store(case, roi, user, db)
