"""
케이스 후보 **기술 검수** API (운영자 전용, 로컬 도구 성격).

**왜 필요한가**
후보 24건을 폴더에서 PNG 를 하나씩 열어 보는 것은 운영 흐름이 아니다. 한 화면에서
메타데이터와 함께 보고 판단을 남길 수 있어야 한다.

==========================================================================
**여기서 하는 검수는 기술 검수뿐이다.**
==========================================================================
`TECH_PASS` 는 "export 파이프라인이 제대로 돌았다"는 뜻이고
**"의학적으로 옳다" 나 "서비스에 올려도 된다"를 뜻하지 않는다.**
상태를 셋으로 분리한 이유와 규칙은 `app/review_store.py` 참고.

**안전 장치**
- 운영자(admin) 인증 필수. 검수 시트는 실제 환자 영상에서 파생된 그림이다.
- 시트 경로는 review_root 안으로 제한한다 (경로 조작 차단).
- 후보 데이터가 없는 환경(배포 서버 등)에서는 빈 목록을 돌려주고 오류를 내지 않는다.
  `data/` 는 로컬 작업 폴더라 서버에 없는 것이 정상이다.
- 이 API 는 **케이스를 등록하거나 활성화하지 않는다.** 등록은 여전히 4단계 파이프라인을 거친다.
"""
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app import review_candidates, review_store
from app.deps import CurrentAdmin
from app.schemas import TechnicalReviewInput

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/review", tags=["admin-review"])

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent

# 로컬 작업 폴더. 배포 서버에는 없는 것이 정상이다.
EXPORT_ROOT_ENV = "MEDISCAN_REVIEW_EXPORT_ROOT"
REVIEW_ROOT_ENV = "MEDISCAN_REVIEW_ROOT"
SCREENING_ENV = "MEDISCAN_REVIEW_SCREENING"

DEFAULT_EXPORT_ROOT = BACKEND_DIR / "data" / "expansion_export"
DEFAULT_REVIEW_ROOT = BACKEND_DIR / "data" / "expansion_review"
DEFAULT_SCREENING = BACKEND_DIR / "data" / "vs_seg_screening.json"


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": True, "code": code, "message": message})


def export_root() -> Path:
    return Path(os.getenv(EXPORT_ROOT_ENV) or DEFAULT_EXPORT_ROOT)


def review_root() -> Path:
    return Path(os.getenv(REVIEW_ROOT_ENV) or DEFAULT_REVIEW_ROOT)


def screening_path() -> Path:
    return Path(os.getenv(SCREENING_ENV) or DEFAULT_SCREENING)


def _entries() -> tuple[list[dict], dict]:
    """후보 목록 + 저장된 검수 결과를 합쳐 돌려준다."""
    ids = review_candidates.list_case_ids(export_root())
    try:
        stored = review_store.load(review_root())
    except review_store.ReviewStoreError as exc:
        raise _error(500, "REVIEW_STORE_UNREADABLE", str(exc)) from exc

    rows = []
    for case_id in ids:
        info = review_candidates.build(case_id, export_root(), review_root(), screening_path())
        if info is None:
            continue
        info["review"] = review_store.get_entry(stored, case_id)
        rows.append(info)
    return rows, stored


# ------------------------------------------------------------------- 목록
@router.get("/candidates")
def list_candidates(admin: CurrentAdmin):
    """후보 전체 + 각각의 검수 상태.

    후보 폴더가 없으면 **빈 목록**이다 (오류가 아니다) — 배포 서버에는 없는 것이 정상이다.
    """
    rows, _ = _entries()
    return {
        "candidates": rows,
        "counts": review_store.counts([r["review"] for r in rows]),
        "roots": {
            "export": str(export_root()),
            "review": str(review_root()),
            "available": export_root().exists(),
        },
        # 화면이 문구를 지어내지 않도록 서버가 내려보낸다
        "notice": (
            "여기서 정하는 것은 **기술 검수**입니다. "
            "TECH_PASS 는 의학적으로 옳다거나 서비스에 올려도 된다는 뜻이 아닙니다."
        ),
        "status_meaning": review_store.TECHNICAL_MEANING,
    }


@router.get("/candidates/{case_id}")
def get_candidate(case_id: str, admin: CurrentAdmin):
    info = review_candidates.build(case_id, export_root(), review_root(), screening_path())
    if info is None:
        raise _error(404, "CANDIDATE_NOT_FOUND", f"후보를 찾을 수 없습니다: {case_id}")
    try:
        stored = review_store.load(review_root())
    except review_store.ReviewStoreError as exc:
        raise _error(500, "REVIEW_STORE_UNREADABLE", str(exc)) from exc
    info["review"] = review_store.get_entry(stored, case_id)
    return info


# ------------------------------------------------------------------- 시트
@router.get("/candidates/{case_id}/sheet")
def get_sheet(case_id: str, admin: CurrentAdmin):
    """검수 시트 PNG.

    실제 환자 영상에서 파생된 그림이므로 **운영자 인증이 필요하다**.
    경로는 review_root 안으로 제한된다.
    """
    path = review_candidates.sheet_path(case_id, review_root())
    if path is None:
        raise _error(404, "SHEET_NOT_FOUND", f"검수 시트를 찾을 수 없습니다: {case_id}")
    return FileResponse(
        path,
        media_type="image/png",
        # 브라우저가 캐시해도 되지만 공유 캐시에는 두지 않는다 (의료영상 파생물)
        headers={"Cache-Control": "private, max-age=300"},
    )


# ------------------------------------------------------------------- 기록
@router.put("/candidates/{case_id}")
def set_technical_review(case_id: str, payload: TechnicalReviewInput, admin: CurrentAdmin):
    """기술 검수 결과를 남긴다.

    **전문가 검수 상태와 활성화 상태는 바꾸지 않는다.** 이 엔드포인트로는
    케이스를 활성화할 수 없다.
    """
    info = review_candidates.build(case_id, export_root(), review_root(), screening_path())
    if info is None:
        raise _error(404, "CANDIDATE_NOT_FOUND", f"후보를 찾을 수 없습니다: {case_id}")

    try:
        entry = review_store.set_technical_status(
            review_root(),
            case_id,
            status=payload.technical_review_status,
            note=payload.note or "",
            reviewer=payload.reviewer or (admin.nickname or admin.user_id),
        )
    except review_store.ReviewStoreError as exc:
        raise _error(400, "INVALID_REVIEW_STATUS", str(exc)) from exc

    logger.info(
        "기술 검수 기록",
        extra={
            "event": "technical_review_recorded",
            "case_id": case_id,
            "status": entry["technical_review_status"],
        },
    )
    return entry


# ------------------------------------------------------------------- 현황
@router.get("/summary")
def summary(admin: CurrentAdmin):
    rows, _ = _entries()
    return {
        "counts": review_store.counts([r["review"] for r in rows]),
        "status_meaning": review_store.TECHNICAL_MEANING,
        "pipeline": [
            "candidate",
            "technical reviewed",
            "expert reviewed",
            "inactive ready",
            "active",
        ],
        "notice": (
            "기술 검수를 통과해도 전문가 검수가 끝나지 않으면 활성화되지 않습니다."
        ),
    }
