"""
운영자용 콘텐츠 관리 API (최소 CMS).

**왜 필요한가**
케이스가 6개일 때는 CLI(`scripts/import_cases.py`)로 버틸 수 있지만, 20~30개로 늘리면
개발자가 DB 와 CLI 를 직접 만지지 않고도 콘텐츠를 다룰 수 있어야 한다.

**의도적으로 하지 않는 것**
- 영상·마스크 업로드는 여기서 하지 않는다. 등록은 여전히 **4단계 파이프라인**
  (DICOM -> npy -> 육안 검수 -> PNG 자산 -> import_cases)을 거친다.
  중간에 사람이 확인하는 지점을 없애면 검수되지 않은 GT 가 서비스에 들어갈 수 있다.
- 케이스 삭제도 여기서 하지 않는다. 비활성(is_active=false)으로 숨길 수 있고,
  실제 삭제는 제출 이력까지 지우는 파괴적 작업이라 CLI(`scripts/remove_cases.py`)에 둔다.
- 채점 기준(reference_mask)은 수정 대상이 아니다. 전문가 GT 를 화면에서 고치는 경로를
  만들지 않는다 (CONTENT_GUIDELINES 2절).

여기서 다루는 것은 **운영 메타데이터와 전문가 소견**뿐이다.
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app import explanations, learning_stats
from app.deps import CurrentAdmin, DbSession
from app.grading import is_gradable
from app.models import Case, CaseSlice, LearningEvent, Submission
from app.schemas import AdminCaseUpdate, CaseFindingsInput
from app.static_files import absolute_url

router = APIRouter(prefix="/api/admin", tags=["admin"])

DIFFICULTIES = {"easy", "medium", "hard"}


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": True, "code": code, "message": message})


def _get_case(db, case_id: str) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise _error(404, "CASE_NOT_FOUND", f"해당 케이스를 찾을 수 없습니다: {case_id}")
    return case


def _summary(db, case: Case) -> dict:
    """운영자가 한눈에 볼 정보. 학습자용 응답(cases.py)과는 목적이 다르다."""
    explanation = explanations.build(case)
    slice_count = db.scalar(
        select(func.count()).select_from(CaseSlice).where(CaseSlice.case_id == case.case_id)
    )
    submission_count = db.scalar(
        select(func.count()).select_from(Submission).where(Submission.case_id == case.case_id)
    )
    return {
        "case_id": case.case_id,
        "body_part": case.body_part,
        "disease": case.disease,
        "is_active": case.is_active,
        "difficulty": case.difficulty,
        "gradable": is_gradable(case),
        "thumbnail_url": absolute_url(case.thumbnail_url),
        "image_url": absolute_url(case.image_url),
        "reference_mask_url": absolute_url(case.reference_mask_url),
        "volume_id": case.volume_id,
        "representative_slice": case.representative_slice,
        "slice_count": slice_count or 0,
        "submission_count": submission_count or 0,
        "content_levels": explanation["content_levels"],
        "case_findings_status": explanation["case_findings_status"],
        "has_case_findings": explanation["case_findings"] is not None,
    }


# ------------------------------------------------------------------ 목록·상세
@router.get("/cases")
def list_cases(admin: CurrentAdmin, db: DbSession, include_inactive: bool = True):
    """운영자 목록. 기본적으로 **비활성 케이스도 보여준다** (숨긴 것을 다시 찾을 수 있어야 한다)."""
    stmt = select(Case).order_by(Case.case_id)
    if not include_inactive:
        stmt = stmt.where(Case.is_active.is_(True))
    cases = db.scalars(stmt).all()
    return {"cases": [_summary(db, c) for c in cases]}


@router.get("/cases/{case_id}")
def get_case(case_id: str, admin: CurrentAdmin, db: DbSession):
    case = _get_case(db, case_id)
    return {**_summary(db, case), "explanation": explanations.build(case)}


# --------------------------------------------------------------- 메타데이터 수정
@router.patch("/cases/{case_id}")
def update_case(case_id: str, payload: AdminCaseUpdate, admin: CurrentAdmin, db: DbSession):
    """활성 여부 / 난이도 / 소견 검토 상태만 바꾼다.

    영상·마스크·해설 본문은 여기서 바꿀 수 없다 (위 docstring 참고).
    """
    case = _get_case(db, case_id)
    changed: dict = {}

    if payload.is_active is not None:
        case.is_active = payload.is_active
        changed["is_active"] = payload.is_active

    if payload.difficulty is not None:
        # 빈 문자열은 "미지정으로 되돌리기"로 받는다
        value = payload.difficulty.strip() or None
        if value is not None and value not in DIFFICULTIES:
            raise _error(
                422, "INVALID_DIFFICULTY", f"difficulty 는 {sorted(DIFFICULTIES)} 중 하나여야 합니다."
            )
        case.difficulty = value
        changed["difficulty"] = value

    if payload.findings_status is not None:
        status = payload.findings_status.strip()
        if status not in explanations.FINDINGS_STATUSES:
            raise _error(
                422,
                "INVALID_FINDINGS_STATUS",
                f"findings_status 는 {list(explanations.FINDINGS_STATUSES)} 중 하나여야 합니다.",
            )
        # 소견이 없는데 approved 로 올리는 것은 막는다.
        # 상태만 올려서 "검토된 것처럼" 보이게 하는 경로를 만들지 않는다.
        if status == explanations.STATUS_APPROVED and not (case.explanation or {}).get("case_findings"):
            raise _error(
                422,
                "FINDINGS_REQUIRED",
                "소견 내용이 없는 케이스를 approved 로 표시할 수 없습니다. 먼저 소견을 등록하세요.",
            )
        case.findings_status = status
        changed["findings_status"] = status

    if not changed:
        raise _error(400, "NO_CHANGES", "변경할 항목이 없습니다.")

    db.commit()
    db.refresh(case)
    return {"updated": changed, **_summary(db, case)}


# ------------------------------------------------------------------ 학습 지표
@router.get("/learning-summary")
def learning_summary(admin: CurrentAdmin, db: DbSession):
    """Closed Beta 에서 "학습이 실제로 일어나는가"를 본다.

    **집계만 돌려준다.** 누가 무엇을 틀렸는지는 나가지 않는다 — 운영자가 개인의 학습 내용을
    들여다보는 도구가 아니다. CLI(`scripts/learning_report.py`)와 **같은 함수**를 쓴다
    (두 곳에서 따로 계산하면 숫자가 갈라진다).

    이벤트 수집이 꺼져 있으면(`MEDISCAN_ANALYTICS=0`) 빈 집계가 나온다 —
    "데이터가 없다"와 "수집이 꺼져 있다"를 구분할 수 있게 상태도 함께 알려준다.
    """
    from app import analytics

    events = db.scalars(select(LearningEvent).order_by(LearningEvent.id)).all()
    return {
        "analytics_enabled": analytics.enabled(),
        **learning_stats.build_report(events),
    }


# ------------------------------------------------------------------ 전문가 소견
@router.put("/cases/{case_id}/findings")
def upsert_findings(case_id: str, payload: CaseFindingsInput, admin: CurrentAdmin, db: DbSession):
    """전문가 소견 등록/수정.

    `reviewer` / `reviewed_at` 은 스키마에서 필수다 — 누가 언제 본 내용인지 남지 않는 소견은
    등록하지 않는다. (필드가 있다는 것만으로 검토를 보증하지는 않는다.)
    """
    case = _get_case(db, case_id)

    findings = payload.to_block()
    explanation = dict(case.explanation or {})
    explanation["case_findings"] = findings
    # SQLAlchemy 가 JSON 변경을 감지하도록 새 dict 를 할당한다
    case.explanation = explanation
    case.findings_status = explanations.STATUS_APPROVED

    db.commit()
    db.refresh(case)
    return {"case_id": case.case_id, "explanation": explanations.build(case)}


@router.delete("/cases/{case_id}/findings")
def delete_findings(case_id: str, admin: CurrentAdmin, db: DbSession):
    """소견 회수 — 잘못 등록했을 때 되돌린다. 케이스 자체는 그대로 둔다."""
    case = _get_case(db, case_id)

    explanation = dict(case.explanation or {})
    if explanation.get("case_findings") is None:
        raise _error(404, "FINDINGS_NOT_FOUND", "등록된 소견이 없습니다.")

    explanation["case_findings"] = None
    case.explanation = explanation
    case.findings_status = explanations.STATUS_NEEDS_REVIEW

    db.commit()
    db.refresh(case)
    return {"case_id": case.case_id, "explanation": explanations.build(case)}
