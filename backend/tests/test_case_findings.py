"""
case_findings 운영 구조 (Phase 4 / RELEASE_READINESS H2).

여기서 지키려는 것:
  - 소견이 비어 있는 **이유**를 응답이 말해준다 (빈칸만 보여주지 않는다)
  - 상태 필드가 실제 내용과 어긋나도 **응답은 거짓말하지 않는다**
  - 학습용 필드는 선택이며, 비어 있으면 비운 채로 나간다 (지어내서 채우지 않는다)
"""
import pytest

from app import explanations
from app.schemas import CaseFindings, Explanation


class _FakeCase:
    """explanations.build 는 ORM 객체의 속성만 읽으므로 가벼운 대역으로 충분하다."""

    def __init__(self, explanation=None, findings_status=None, disease="unknown-disease"):
        self.explanation = explanation
        self.disease = disease
        if findings_status is not None:
            self.findings_status = findings_status


FACTS = {"source": "dataset_verified", "disease_name": "테스트", "reference_region": "테스트 영역"}
FINDINGS = {
    "source": "expert_reviewed",
    "findings": "전문가가 작성한 소견",
    "reviewer": "검토자",
    "reviewed_at": "2026-09-08",
}


# ------------------------------------------------------------------ 상태 노출
def test_missing_findings_reports_needs_expert_review():
    case = _FakeCase({"case_facts": FACTS}, findings_status="needs_expert_review")
    built = explanations.build(case)

    assert built["case_findings"] is None
    assert built["case_findings_status"] == "needs_expert_review"
    # 없는 블록은 content_levels 에서도 빠진다
    assert "expert_reviewed" not in built["content_levels"]


def test_in_review_status_is_preserved():
    """'아직 아무도 안 봤다'와 '검토 중'은 운영자에게 다른 정보다."""
    case = _FakeCase({"case_facts": FACTS}, findings_status="in_review")
    assert explanations.build(case)["case_findings_status"] == "in_review"


def test_present_findings_are_reported_as_approved():
    case = _FakeCase(
        {"case_facts": FACTS, "case_findings": FINDINGS}, findings_status="needs_expert_review"
    )
    built = explanations.build(case)

    assert built["case_findings"]["findings"] == "전문가가 작성한 소견"
    # 내용이 이미 서비스되고 있으므로 저장된 상태보다 실제 내용을 따른다
    assert built["case_findings_status"] == "approved"
    assert "expert_reviewed" in built["content_levels"]


# ------------------------------------------- 상태가 내용과 어긋날 때 (거짓말 금지)
def test_approved_status_without_content_falls_back_to_needs_review():
    """상태만 approved 로 잘못 올라가 있어도 '검토된 소견이 있다'고 말하면 안 된다."""
    case = _FakeCase({"case_facts": FACTS}, findings_status="approved")
    built = explanations.build(case)

    assert built["case_findings"] is None
    assert built["case_findings_status"] == "needs_expert_review"


def test_unknown_status_falls_back_to_needs_review():
    case = _FakeCase({"case_facts": FACTS}, findings_status="완료함")
    assert explanations.build(case)["case_findings_status"] == "needs_expert_review"


def test_missing_status_column_defaults_to_needs_review():
    """컬럼이 아직 없는 객체(레거시)여도 안전한 쪽으로 떨어진다."""
    case = _FakeCase({"case_facts": FACTS})  # findings_status 속성 자체가 없음
    assert explanations.build(case)["case_findings_status"] == "needs_expert_review"


# ------------------------------------------------------------ 학습용 필드 구조
def test_learning_fields_are_optional_and_default_empty():
    """전문가가 안 쓴 항목은 비어 있어야 한다 — 등록·응답 어느 단계에서도 채우지 않는다."""
    model = CaseFindings(**FINDINGS)

    assert model.learning_points == []
    assert model.common_mistakes == []
    assert model.lesion_location is None
    assert model.reference_region_note is None
    assert model.content_version is None


def test_learning_fields_round_trip():
    model = CaseFindings(
        **FINDINGS,
        lesion_location="전문가가 쓴 위치 설명",
        reference_region_note="기준 영역 설명",
        learning_points=["확인 포인트 1", "확인 포인트 2"],
        common_mistakes=["자주 놓치는 부분"],
        content_version="vs-204-2026-09-08",
    )
    assert model.learning_points == ["확인 포인트 1", "확인 포인트 2"]
    assert model.common_mistakes == ["자주 놓치는 부분"]


def test_reviewer_metadata_is_required():
    """누가 언제 본 내용인지 없는 소견은 스키마 단계에서 막힌다."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CaseFindings(source="expert_reviewed", findings="검토자 없는 소견")


def test_explanation_schema_default_status_is_needs_review():
    """스키마 기본값도 안전한 쪽이어야 한다."""
    assert Explanation().case_findings_status == "needs_expert_review"


# ------------------------------------------------------ 등록 스크립트 (import)
def test_import_rejects_findings_without_reviewer():
    from scripts.import_cases import ImportError_, _validate_case_findings

    with pytest.raises(ImportError_):
        _validate_case_findings({"findings": "소견만 있고 검토자 없음"})


def test_import_keeps_optional_fields_empty_when_absent():
    from scripts.import_cases import _validate_case_findings

    result = _validate_case_findings(dict(FINDINGS))
    assert result["learning_points"] == []
    assert result["common_mistakes"] == []
    assert result["lesion_location"] is None


def test_import_accepts_learning_fields():
    from scripts.import_cases import _validate_case_findings

    result = _validate_case_findings(
        {**FINDINGS, "learning_points": ["포인트", "  "], "lesion_location": " 위치 "}
    )
    assert result["learning_points"] == ["포인트"]  # 빈 문자열은 버린다
    assert result["lesion_location"] == "위치"


def test_import_rejects_non_list_learning_points():
    from scripts.import_cases import ImportError_, _validate_case_findings

    with pytest.raises(ImportError_):
        _validate_case_findings({**FINDINGS, "learning_points": "문자열 하나"})


# --------------------------------------------------- 실제 등록 케이스 현황 확인
def test_registered_cases_expose_findings_status(user_a, roi_mismatch):
    """서비스 응답에 상태가 실제로 실려 나가는지 (mock 케이스 기준)."""
    body = user_a.submit(roi_mismatch).json()
    status = body["explanation"]["case_findings_status"]
    assert status in {"needs_expert_review", "in_review", "approved"}
    # 소견이 없으면 approved 일 수 없다
    if body["explanation"]["case_findings"] is None:
        assert status != "approved"
