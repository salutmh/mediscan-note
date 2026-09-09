"""
문서(docs/api-spec.md) ↔ 실제 응답 불일치 감지.

`docs/api-spec.md` 는 프론트와의 **유일한 접점**이다 (CLAUDE.md 개발원칙 2).
응답에 필드를 추가/삭제하면서 문서를 잊는 일이 반복돼서, 여기서 기계적으로 잡는다.

검사 방향 두 가지:
  1. 실제 응답에 있는 필드가 문서에 적혀 있는가  (문서 누락 감지)
  2. schemas.py 모델의 필드가 문서에 적혀 있는가  (계약 모델 누락 감지)

값이 아니라 **필드 이름의 존재**만 본다 — 문서 문장까지 강제하면 관리가 어렵다.
"""
from pathlib import Path

import pytest

from app import schemas

API_SPEC = Path(__file__).resolve().parent.parent.parent / "docs" / "api-spec.md"


@pytest.fixture(scope="module")
def spec_text() -> str:
    assert API_SPEC.exists(), f"API 명세를 찾을 수 없습니다: {API_SPEC}"
    return API_SPEC.read_text(encoding="utf-8")


def _keys(payload, prefix="") -> set[str]:
    """응답에 실제로 나온 필드 이름을 모은다 (중첩 객체 포함)."""
    found = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            found.add(key)
            found |= _keys(value)
    elif isinstance(payload, list):
        # **항목을 전부 본다.** 예전에는 첫 항목만 보고 "형태는 같다"고 뒀는데,
        # 조건부로 채워지는 필드가 있으면 그렇지 않다 —
        # 케이스 목록에서 첫 케이스가 미시도(progress=null)면 그 안의
        # 필드가 통째로 검사에서 빠져, 문서에 없는 필드가 조용히 새어 나갔다.
        for item in payload:
            found |= _keys(item)
    return found


# 문서에 굳이 필드명으로 적지 않는 것들 (설명 문장으로 다루거나 내부 표기)
NOT_REQUIRED_IN_SPEC = {
    "error", "code", "message", "detail",
    "db", "models", "folder", "module_loaded", "available", "input_kind",
    "unavailable_reason", "model_version",  # /health 전용 표기
    "precomputed_predictions", "cases_with_prediction", "case_ids",
    "token_type", "is_new_user",
    "source", "notice", "term", "description", "title", "publisher", "url", "accessed",
    "name", "probability",
}


def _assert_documented(keys: set[str], spec: str, where: str):
    missing = sorted(k for k in keys if k not in NOT_REQUIRED_IN_SPEC and k not in spec)
    assert not missing, f"{where} 응답 필드가 api-spec.md 에 없습니다: {missing}"


def test_case_list_fields_are_documented(client, user_a, roi_mismatch, spec_text):
    """**먼저 한 번 풀고 나서 본다.**

    풀지 않은 상태에서는 `progress` 가 null 이라 그 안의 필드가 응답에
    아예 나타나지 않는다. 그대로 검사하면 새로 늘어난 하위 필드가
    문서에 없어도 조용히 통과한다 — 실제로 그렇게 새어 나갔다.
    """
    user_a.submit(roi_mismatch)
    body = user_a.get("/api/cases").json()
    assert any(c.get("progress") for c in body["cases"]), "progress 가 채워진 상태를 봐야 한다"
    _assert_documented(_keys(body), spec_text, "GET /api/cases")


def test_case_detail_fields_are_documented(client, user_a, spec_text):
    from tests.conftest import CASE_ID

    body = user_a.get(f"/api/cases/{CASE_ID}").json()
    _assert_documented(_keys(body), spec_text, "GET /api/cases/{id}")


def test_submit_fields_are_documented(client, user_a, roi_match, spec_text):
    body = user_a.submit(roi_match).json()
    _assert_documented(_keys(body), spec_text, "POST /api/cases/{id}/submit")


def test_wrong_notes_fields_are_documented(client, user_a, roi_mismatch, spec_text):
    user_a.submit(roi_mismatch)
    body = user_a.get("/api/wrong-notes").json()
    _assert_documented(_keys(body), spec_text, "GET /api/wrong-notes")


def test_dashboard_fields_are_documented(client, user_a, roi_mismatch, spec_text):
    """홈 화면이 쓰는 필드도 계약이다 — 문서 없이 늘어나면 프론트가 추측하게 된다."""
    user_a.submit(roi_mismatch)
    body = user_a.get("/api/me/dashboard").json()
    _assert_documented(_keys(body), spec_text, "GET /api/me/dashboard")


def test_analyze_fields_are_documented(client, user_a, spec_text):
    import base64
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (128, 128), (80, 80, 80)).save(buf, "PNG")
    body = user_a.post(
        "/api/analyze",
        json={
            "image_base64": base64.b64encode(buf.getvalue()).decode(),
            "region": {"type": "brush_mask", "points": [[10, 10]]},
        },
    ).json()
    _assert_documented(_keys(body), spec_text, "POST /api/analyze")


# ------------------------------------------------------- schemas.py ↔ 문서
CONTRACT_MODELS = [
    schemas.CaseSummary,
    schemas.CaseDetail,
    schemas.Explanation,
    schemas.CaseFacts,
    schemas.DiseaseInfo,
    schemas.CaseFindings,
    schemas.Evaluation,
    schemas.AiPrediction,
    schemas.EvaluationResult,
    schemas.WrongNoteItem,
    schemas.AnalyzeResult,
]


@pytest.mark.parametrize("model", CONTRACT_MODELS, ids=lambda m: m.__name__)
def test_schema_fields_are_documented(model, spec_text):
    missing = sorted(
        name for name in model.model_fields
        if name not in NOT_REQUIRED_IN_SPEC and name not in spec_text
    )
    assert not missing, f"{model.__name__} 필드가 api-spec.md 에 없습니다: {missing}"


def test_removed_v03_fields_are_gone_from_responses(client, user_a, roi_match):
    """v0.3 에서 제거한 평평한 해설 필드가 응답에 되살아나지 않았는지."""
    body = user_a.submit(roi_match).json()
    explanation = body["explanation"]

    for removed in ("key_findings", "review_status", "medical_terms", "reference"):
        assert removed not in explanation, f"제거된 v0.3 필드가 남아 있습니다: {removed}"
    assert "ai_mask_url" not in body, "v0.2 필드가 남아 있습니다"


def test_contract_version_is_current(spec_text):
    """문서 상단의 계약 버전이 현재 구조(3층 해설)와 맞는지."""
    assert "계약 버전: v0.4" in spec_text
    assert "content_levels" in spec_text
