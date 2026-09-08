"""
채점 테스트 (API 계약 v0.4).

핵심 불변식:
  1. 채점 기준은 **전문가 검수 reference mask 하나뿐**이다. AI 예측은 채점에 관여하지 않는다.
  2. 기준 마스크가 없으면 **채점하지 않고** 422 를 주며 **제출 이력도 남기지 않는다**.
  3. 제출 마스크는 보정하지 않는다 (fill_holes 미적용).
"""
import base64
import io

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Case, Submission
from tests.conftest import CASE_ID, IMAGE_SIZE, LESION


def _mask(draw_fn) -> str:
    img = Image.new("RGBA", (IMAGE_SIZE, IMAGE_SIZE), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(img))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _roi(mask_base64: str, points=None) -> dict:
    return {
        "type": "brush_mask",
        "points": points or [[LESION["cx"], LESION["cy"]]],
        "mask_png_base64": mask_base64,
    }


def _circle(cx, cy, r, fill=True):
    def draw(d):
        box = [cx - r, cy - r, cx + r, cy + r]
        if fill:
            d.ellipse(box, fill=(255, 255, 255, 255))
        else:
            d.ellipse(box, outline=(255, 255, 255, 255), width=8)

    return draw


# ------------------------------------------------------------ 등급 판정
@pytest.mark.parametrize(
    "cx,cy,radius,expected_grade",
    [
        (LESION["cx"], LESION["cy"], LESION["r"], "match"),             # 정확히 덮음
        (LESION["cx"], LESION["cy"], LESION["r"] // 2, "partial_match"),  # 안쪽에 작게
        (LESION["cx"] + 40, LESION["cy"], LESION["r"], "partial_match"),  # 40px 어긋남
        (140, 160, 30, "mismatch"),                                       # 이미지 안의 딴 곳
    ],
)
def test_grade_reflects_overlap(user_a, cx, cy, radius, expected_grade):
    roi = _roi(_mask(_circle(cx, cy, radius)))
    body = user_a.submit(roi).json()
    assert body["grade"] == expected_grade, body


def test_perfect_overlap_scores_near_one(user_a):
    body = user_a.submit(_roi(_mask(_circle(LESION["cx"], LESION["cy"], LESION["r"])))).json()
    assert body["dice"] > 0.95
    assert body["iou"] > 0.9
    assert body["location_score"] == 100


def test_far_away_roi_scores_zero(user_a):
    body = user_a.submit(_roi(_mask(_circle(100, 120, 30)))).json()
    assert body["dice"] == 0.0
    assert body["iou"] == 0.0
    assert body["location_score"] == 0


# ------------------------------------------------- 응답 스키마 (계약 v0.4)
def test_response_uses_reference_mask_contract(user_a):
    body = user_a.submit(_roi(_mask(_circle(LESION["cx"], LESION["cy"], LESION["r"])))).json()

    assert body["case_id"] == CASE_ID
    assert body["reference_mask_url"].endswith("_mask.png")
    assert body["evaluation"] == {"method": "reference_mask", "is_provisional": False}
    assert body["ai_prediction"] is None  # 체크포인트가 없으므로 참고 정보도 없다
    assert "ai_mask_url" not in body, "v0.2 필드가 남아 있으면 안 된다"
    assert "model_version" not in body, "채점 응답의 최상위 model_version 은 v0.3 에서 제거됐다"
    # v0.4: 해설은 출처가 다른 3개 블록 + 파생 content_levels
    explanation = body["explanation"]
    assert set(explanation) == {"content_levels", "case_facts", "disease_info", "case_findings"}
    assert explanation["case_facts"]["source"] == "dataset_verified"
    assert {"disease_name", "reference_region"} <= set(explanation["case_facts"])
    assert "dataset_verified" in explanation["content_levels"]


# -------------------------------------------- ROI 보정 없음 (fill_holes 제거)
def test_outline_only_roi_is_not_auto_filled(user_a):
    """둘레만 그린 ROI 는 채운 것으로 간주되지 않는다 (v0.2 의 자동 보정 제거)."""
    outline = user_a.submit(_roi(_mask(_circle(LESION["cx"], LESION["cy"], LESION["r"], fill=False)))).json()
    filled = user_a.submit(_roi(_mask(_circle(LESION["cx"], LESION["cy"], LESION["r"])))).json()

    assert outline["dice"] < filled["dice"]
    assert filled["dice"] > 0.95
    # 윤곽선만으로는 match 가 나오지 않아야 한다 (과보정 방지)
    assert outline["grade"] != "match"


# ------------------------------------------------------------- ROI 검증
@pytest.mark.parametrize(
    "roi",
    [
        {"type": "brush_mask", "points": [[1, 1]]},                       # 마스크 없음
        {"type": "brush_mask", "points": [], "mask_png_base64": ""},      # 빈 문자열
        {"type": "brush_mask", "points": [], "mask_png_base64": "not-a-png"},  # 디코딩 실패
    ],
)
def test_invalid_roi_is_rejected(user_a, roi):
    res = user_a.post(f"/api/cases/{CASE_ID}/submit", json={"roi": roi})
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "INVALID_ROI"


def test_empty_mask_is_rejected(user_a):
    """완전히 투명한(빈) 마스크는 제출로 인정하지 않는다."""
    empty = _mask(lambda d: None)
    res = user_a.post(f"/api/cases/{CASE_ID}/submit", json={"roi": _roi(empty)})
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "INVALID_ROI"


def test_missing_roi_key_is_rejected(user_a):
    res = user_a.post(f"/api/cases/{CASE_ID}/submit", json={})
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "INVALID_ROI"


def test_invalid_roi_does_not_create_submission(user_a):
    user_a.post(f"/api/cases/{CASE_ID}/submit", json={"roi": {"type": "brush_mask", "points": []}})
    with SessionLocal() as db:
        assert db.scalars(select(Submission)).all() == []


# ------------------------------------- 기준 마스크 없음 -> 채점 거부 (422)
@pytest.fixture
def case_without_reference(client):
    """기준 마스크가 없는 케이스를 임시로 만든다."""
    case_id = "NO-REF-001"
    with SessionLocal() as db:
        db.add(
            Case(
                case_id=case_id,
                body_part="brain_mri",
                disease="test",
                reference_mask_url="/static/results/does-not-exist.png",
                reference_shape={"cx": 100, "cy": 100, "r": 20},
            )
        )
        db.commit()
    yield case_id
    with SessionLocal() as db:
        db.query(Submission).filter(Submission.case_id == case_id).delete()
        db.query(Case).filter(Case.case_id == case_id).delete()
        db.commit()


def test_case_without_reference_is_not_gradable(user_a, case_without_reference):
    detail = user_a.get(f"/api/cases/{case_without_reference}").json()
    assert detail["gradable"] is False

    listed = next(
        c for c in user_a.get("/api/cases").json()["cases"] if c["case_id"] == case_without_reference
    )
    assert listed["gradable"] is False


def test_submit_without_reference_returns_422(user_a, case_without_reference, roi_match):
    res = user_a.post(f"/api/cases/{case_without_reference}/submit", json={"roi": roi_match})
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "CASE_NOT_GRADABLE"


def test_not_gradable_submit_leaves_no_history(user_a, case_without_reference, roi_match):
    """채점할 수 없는 제출은 이력을 만들지 않는다 (리뷰 지적 반영)."""
    user_a.post(f"/api/cases/{case_without_reference}/submit", json={"roi": roi_match})

    with SessionLocal() as db:
        rows = db.scalars(select(Submission).where(Submission.case_id == case_without_reference)).all()
    assert rows == []

    # 복습노트에도 잡히지 않는다
    assert user_a.get("/api/wrong-notes").json()["items"] == []


def test_gradable_case_reports_true(user_a):
    assert user_a.get(f"/api/cases/{CASE_ID}").json()["gradable"] is True


# ----------------------------- AI 예측은 채점에 영향을 주지 않는다 (핵심)
def test_ai_model_never_overrides_reference_grading(user_a, monkeypatch, roi_match, tmp_path):
    """모델이 전혀 다른 마스크를 내놓아도 채점은 기준 마스크로만 이뤄진다."""
    from app import grading, inference

    # 가짜 모델의 출력은 pytest tmp_path 에만 쓴다.
    # (앱의 static 폴더에 쓰면 테스트가 실제 자산을 오염시킨다)
    predicted_mask = tmp_path / "fake_prediction.png"

    class FakeModule:
        MODEL_VERSION = "fake-model-v9"

        @staticmethod
        def predict(image_path, reference_mask_path=None):
            # 병변과 완전히 다른 위치를 예측하는 모델
            out = Image.new("RGBA", (IMAGE_SIZE, IMAGE_SIZE), (0, 0, 0, 0))
            ImageDraw.Draw(out).ellipse([10, 10, 60, 60], fill=(0, 200, 90, 190))
            out.save(predicted_mask)
            return {"mask_path": str(predicted_mask), "model_version": "fake-model-v9"}

    monkeypatch.setattr(inference, "is_available", lambda body_part: True)
    monkeypatch.setattr(inference, "get_module", lambda body_part: FakeModule)

    body = user_a.submit(roi_match).json()

    # 기준 마스크 기준으로 정상 채점되어야 한다
    assert body["grade"] == "match"
    assert body["dice"] > 0.95
    assert body["evaluation"]["method"] == "reference_mask"

    # 모델 결과는 참고 정보로만 붙는다
    assert body["ai_prediction"]["model_version"] == "fake-model-v9"
    assert body["ai_prediction"]["dice_vs_reference"] is not None
    assert body["ai_prediction"]["dice_vs_reference"] < 0.1  # 엉뚱한 예측이므로 낮다
    assert grading.METHOD_REFERENCE == "reference_mask"

    # 모델 출력은 tmp_path 에만 있고 앱 자산 폴더에는 없어야 한다
    assert predicted_mask.exists()


def test_broken_model_does_not_block_grading(user_a, monkeypatch, roi_match):
    """모델이 예외를 던져도 채점은 정상 동작한다 (참고 정보만 생략)."""
    from app import inference

    class ExplodingModule:
        MODEL_VERSION = "boom"

        @staticmethod
        def predict(image_path, reference_mask_path=None):
            raise RuntimeError("모델 폭발")

    monkeypatch.setattr(inference, "is_available", lambda body_part: True)
    monkeypatch.setattr(inference, "get_module", lambda body_part: ExplodingModule)

    body = user_a.submit(roi_match).json()
    assert body["grade"] == "match"
    assert body["ai_prediction"] is None


# ------------------------------------------ 개발용 근사 채점은 기본 비활성
def test_approx_grading_is_off_by_default(user_a, case_without_reference, roi_match):
    res = user_a.post(f"/api/cases/{case_without_reference}/submit", json={"roi": roi_match})
    assert res.status_code == 422, "환경변수 없이 근사 채점이 동작하면 안 된다"


def test_approx_grading_is_marked_provisional_when_enabled(
    user_a, case_without_reference, roi_match, monkeypatch
):
    monkeypatch.setenv("MEDISCAN_ALLOW_APPROX_GRADING", "1")
    res = user_a.post(f"/api/cases/{case_without_reference}/submit", json={"roi": roi_match})
    assert res.status_code == 200
    body = res.json()
    assert body["evaluation"] == {"method": "coordinate_approx", "is_provisional": True}
