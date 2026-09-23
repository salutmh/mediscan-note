"""
"병변 없음" 답 + 빈 기준 마스크 채점 (계약 v0.9).

핵심 불변식:
  1. 채점 기준은 전문가 기준 마스크뿐이다 — AI 예측은 어떤 분기에도 들어오지 않는다.
  2. ROI 를 그리지 않았다는 사실만으로 "병변 없음"이 되지 않는다 (명시적 type 필요).
  3. 빈 기준 마스크는 케이스에 reference_is_empty 가 켜져 있을 때만 채점 기준이 된다.
  4. 양성 케이스 + ROI 는 기존 채점 결과와 한 글자도 달라지지 않는다.
"""
import base64
import io

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import delete

from app import grading, masks
from app.db import SessionLocal
from app.models import Case, LearningEvent, Submission
from tests.conftest import CASE_ID, IMAGE_SIZE, LESION

NEG_ID = "NEG-TEST-001"
NO_ABNORMALITY = {"type": "no_abnormality"}


def _png(draw_fn=None) -> bytes:
    img = Image.new("RGBA", (IMAGE_SIZE, IMAGE_SIZE), (0, 0, 0, 0))
    if draw_fn:
        draw_fn(ImageDraw.Draw(img))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _disk(cx, cy, r):
    return lambda d: d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255))


def _brush(draw_fn) -> dict:
    return {
        "type": "brush_mask",
        "points": [[100, 100]],
        "mask_png_base64": base64.b64encode(_png(draw_fn)).decode(),
    }


@pytest.fixture
def negative_case(tmp_path, monkeypatch):
    """전문가 기준 마스크가 비어 있는 케이스. 마스크 파일은 tmp_path 에만 만든다."""
    empty_path = tmp_path / "reference_mask.png"
    # 등록 스크립트와 같은 형태: 검은 배경(L 모드) 완전 빈 PNG
    Image.new("L", (IMAGE_SIZE, IMAGE_SIZE), 0).save(empty_path)

    original = grading.reference_mask_path
    paths = {NEG_ID: empty_path}
    monkeypatch.setattr(
        grading, "reference_mask_path", lambda case: paths.get(case.case_id) or original(case)
    )

    with SessionLocal() as db:
        db.add(
            Case(
                case_id=NEG_ID,
                body_part="brain_mri",
                disease="glioma",
                image_url=None,
                image_meta={"width": IMAGE_SIZE, "height": IMAGE_SIZE},
                reference_mask_url=f"/static/cases/{NEG_ID}/reference_mask.png",
                reference_is_empty=True,
                explanation={"case_facts": {"source": "dataset_verified"}, "case_findings": None},
            )
        )
        db.commit()
    yield {"paths": paths, "tmp": tmp_path}
    with SessionLocal() as db:
        db.execute(delete(Submission).where(Submission.case_id == NEG_ID))
        db.execute(delete(LearningEvent).where(LearningEvent.case_id == NEG_ID))
        db.execute(delete(Case).where(Case.case_id == NEG_ID))
        db.commit()


def _breakdown(body):
    return body["spatial_feedback"]["metrics"]


# ------------------------------------------------------------ 요구된 4가지
def test_empty_reference_and_no_abnormality_is_match_100(user_a, negative_case):
    """1) GT 빔 + 병변 없음 -> 일치 / 100% / 놓친 0% / 과하게 0%."""
    res = user_a.submit(NO_ABNORMALITY, case_id=NEG_ID)
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["grade"] == "match"
    assert body["dice"] == 1.0
    assert body["iou"] == 1.0
    assert body["location_score"] == 100
    assert body["answer_type"] == "no_abnormality"
    assert body["evaluation"]["reference_empty"] is True
    m = _breakdown(body)
    assert m["under_segmentation_ratio"] == 0.0
    assert m["over_segmentation_ratio"] == 0.0
    assert m["user_area_px"] == 0 and m["reference_area_px"] == 0
    assert body["spatial_feedback"]["primary_message"] == "전문가 기준 정답에서도 표시된 병변이 없습니다."
    # 맞혔으니 복습 대상이 아니다
    assert body["review"]["needs_review"] is False


def test_empty_reference_and_roi_is_mismatch(user_a, negative_case):
    """2) GT 빔 + ROI 표시 -> 다름 / 과하게 표시한 부분 존재."""
    body = user_a.submit(_brush(_disk(200, 200, 20)), case_id=NEG_ID).json()

    assert body["grade"] == "mismatch"
    assert body["dice"] == 0.0
    assert body["answer_type"] == "roi"
    assert body["evaluation"]["reference_empty"] is True
    m = _breakdown(body)
    assert m["user_precision"] == 0.0  # 표시한 영역 전부가 기준 밖
    assert m["user_area_px"] > 0
    assert body["review"]["needs_review"] is True


def test_positive_reference_and_no_abnormality_is_mismatch_missed_100(user_a):
    """3) GT 양성 + 병변 없음 -> 다름 / 놓친 부분 100%."""
    body = user_a.submit(NO_ABNORMALITY).json()

    assert body["grade"] == "mismatch"
    assert body["dice"] == 0.0
    assert body["iou"] == 0.0
    assert body["location_score"] == 0
    assert body["answer_type"] == "no_abnormality"
    assert body["evaluation"]["reference_empty"] is False
    m = _breakdown(body)
    assert m["gt_coverage"] == 0.0
    assert m["under_segmentation_ratio"] == 1.0
    assert m["over_segmentation_ratio"] == 0.0
    assert "전문가 기준 영역을 놓쳤습니다" in body["spatial_feedback"]["primary_message"]
    assert body["review"]["needs_review"] is True


def test_positive_reference_and_roi_is_unchanged(user_a):
    """4) GT 양성 + ROI -> 기존 Dice/IoU/위치 채점 그대로 (회귀 없음)."""
    roi = _brush(_disk(LESION["cx"], LESION["cy"], LESION["r"]))
    body = user_a.submit(roi).json()

    with SessionLocal() as db:
        case = db.get(Case, CASE_ID)
    reference = masks.from_path(grading.reference_mask_path(case))
    user_mask = masks.from_base64(roi["mask_png_base64"])
    dice, iou = masks.dice_iou(user_mask, reference)

    assert body["answer_type"] == "roi"
    assert body["evaluation"]["reference_empty"] is False
    assert body["dice"] == round(dice, 4)
    assert body["iou"] == round(iou, 4)
    assert body["location_score"] == masks.location_score(user_mask, reference)
    assert body["grade"] == "match"
    # 기존 geometry 피드백 경로를 그대로 탄다
    assert body["spatial_feedback"]["items"][0]["code"] == "POSITION_ON_TARGET"


# ------------------------------------------------------------ 경계 조건
def test_blank_canvas_is_not_treated_as_no_abnormality(user_a, negative_case):
    """칠하지 않은 캔버스를 그대로 보내면 '병변 없음'으로 간주하지 않는다."""
    res = user_a.submit(_brush(None), case_id=NEG_ID)
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "INVALID_ROI"


def test_no_abnormality_with_painted_mask_is_rejected(user_a, negative_case):
    roi = {**_brush(_disk(200, 200, 20)), "type": "no_abnormality"}
    res = user_a.submit(roi, case_id=NEG_ID)
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "INVALID_ROI"


def test_empty_mask_without_flag_is_not_gradable(user_a, negative_case):
    """reference_is_empty 가 꺼진 채 빈 마스크면 export 오류일 수 있다 -> 채점하지 않는다."""
    with SessionLocal() as db:
        db.get(Case, NEG_ID).reference_is_empty = False
        db.commit()
    res = user_a.submit(NO_ABNORMALITY, case_id=NEG_ID)
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "CASE_NOT_GRADABLE"


def test_flag_with_nonempty_mask_is_not_gradable(user_a, negative_case):
    lesion_path = negative_case["tmp"] / "lesion.png"
    lesion_path.write_bytes(_png(_disk(200, 200, 20)))
    negative_case["paths"][NEG_ID] = lesion_path
    res = user_a.submit(NO_ABNORMALITY, case_id=NEG_ID)
    assert res.status_code == 422


def test_case_detail_does_not_leak_reference_empty(user_a, negative_case):
    """빈 기준 마스크 여부는 곧 정답이다 — 제출 전 응답에 나가면 안 된다."""
    detail = user_a.get(f"/api/cases/{NEG_ID}").json()
    listed = next(c for c in user_a.get("/api/cases").json()["cases"] if c["case_id"] == NEG_ID)
    for payload in (detail, listed):
        assert "reference_is_empty" not in payload
        assert "reference_empty" not in payload


def test_ai_prediction_is_not_consulted_for_grading(user_a, negative_case, monkeypatch):
    """AI 예측이 '병변 있음'이라고 해도 빈 기준 마스크 채점은 그대로다."""
    monkeypatch.setattr(
        grading,
        "ai_prediction",
        lambda case, reference=None: {"model_version": "fake", "mask_url": None,
                                      "dice_vs_reference": 0.0, "detected": True},
    )
    body = user_a.submit(NO_ABNORMALITY, case_id=NEG_ID).json()
    assert body["grade"] == "match" and body["dice"] == 1.0
    assert body["ai_prediction"]["model_version"] == "fake"


def test_no_abnormality_submission_is_stored(user_a, negative_case):
    user_a.submit(NO_ABNORMALITY, case_id=NEG_ID)
    with SessionLocal() as db:
        rows = db.query(Submission).filter(Submission.case_id == NEG_ID).all()
    assert len(rows) == 1
    assert rows[0].grade == "match" and rows[0].dice == 1.0
