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
    return {
        "items": [
            {
                "case_id": s.case_id,
                "body_part": case_map[s.case_id].body_part,
                "grade": s.grade,
                "attempted_at": _to_kst_iso(s.submitted_at),
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
