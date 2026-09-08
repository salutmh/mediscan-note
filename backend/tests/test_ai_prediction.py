"""
AI 예측 참고 정보 (`ai_prediction`) — 미리 계산된 sidecar 경로.

고정하려는 규칙:
  - **AI 예측은 채점에 관여하지 않는다.** sidecar 의 Dice 가 0 이어도 사용자 채점은 그대로다
  - volume 입력 모델은 slice PNG 로 요청 시 추론하지 않는다 (학습 때와 다른 입력이 된다)
  - sidecar 가 없거나 깨졌으면 조용히 null (참고 정보가 없다고 채점이 막히면 안 된다)
  - 미검출 케이스(detected=false)는 마스크 URL 없이 사실대로 내려간다
"""
import json

import pytest

from app import model_predictions
from tests.conftest import CASE_ID

SIDECAR = {
    "case_id": CASE_ID,
    "model_version": "vs-seg-unet2d5-att-hard-t1",
    "dice_vs_reference": 0.938430,
    "predicted_voxels": 12200,
    "reference_voxels": 12812,
    "detected": True,
    "representative_slice": 35,
    "representative_slice_dice": 0.910933,
    "mask_url": "/static/cases/VS-SEG-202/prediction.png",
    "generated_at": "2026-09-08T12:00:00+00:00",
}


@pytest.fixture
def sidecar_dir(tmp_path, monkeypatch):
    """예측 sidecar 위치를 임시 폴더로 돌린다. 앱의 실제 static 은 건드리지 않는다."""
    monkeypatch.setattr(model_predictions, "CASES_DIR", tmp_path)
    model_predictions.clear_cache()
    yield tmp_path
    model_predictions.clear_cache()


def write_sidecar(directory, case_id=CASE_ID, **overrides):
    payload = {**SIDECAR, **overrides}
    case_dir = directory / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "prediction.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    model_predictions.clear_cache()
    return payload


# ------------------------------------------------------------------ 로더
def test_missing_sidecar_returns_none(sidecar_dir):
    assert model_predictions.load(CASE_ID) is None


def test_sidecar_is_normalized(sidecar_dir):
    write_sidecar(sidecar_dir)
    prediction = model_predictions.load(CASE_ID)

    assert prediction["model_version"] == "vs-seg-unet2d5-att-hard-t1"
    assert prediction["dice_vs_reference"] == 0.9384  # 소수점 4자리로 정리
    assert prediction["detected"] is True
    assert prediction["mask_url"].endswith("/prediction.png")


def test_missed_case_has_no_mask_url(sidecar_dir):
    write_sidecar(sidecar_dir, detected=False, mask_url=None, dice_vs_reference=0.0)
    prediction = model_predictions.load(CASE_ID)

    assert prediction["detected"] is False
    assert prediction["mask_url"] is None
    assert prediction["dice_vs_reference"] == 0.0


def test_broken_sidecar_is_ignored(sidecar_dir):
    case_dir = sidecar_dir / CASE_ID
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "prediction.json").write_text("{ not json", encoding="utf-8")
    model_predictions.clear_cache()

    assert model_predictions.load(CASE_ID) is None


def test_sidecar_without_model_version_is_ignored(sidecar_dir):
    write_sidecar(sidecar_dir, model_version="")
    assert model_predictions.load(CASE_ID) is None


def test_recomputed_sidecar_is_picked_up_without_restart(sidecar_dir):
    assert model_predictions.load(CASE_ID) is None

    (sidecar_dir / CASE_ID).mkdir(parents=True, exist_ok=True)
    (sidecar_dir / CASE_ID / "prediction.json").write_text(
        json.dumps(SIDECAR, ensure_ascii=False), encoding="utf-8"
    )
    assert model_predictions.load(CASE_ID) is not None


def test_summary_counts_cases(sidecar_dir):
    write_sidecar(sidecar_dir)
    write_sidecar(sidecar_dir, case_id="VS-SEG-999")

    summary = model_predictions.summary()
    assert summary["cases_with_prediction"] == 2
    assert CASE_ID in summary["case_ids"]


# ---------------------------------------------------- 채점 응답에 실리는 방식
def test_submit_includes_precomputed_prediction(client, sidecar_dir, user_a, roi_match):
    write_sidecar(sidecar_dir)

    body = user_a.submit(roi_match).json()
    prediction = body["ai_prediction"]

    assert prediction["model_version"] == "vs-seg-unet2d5-att-hard-t1"
    assert prediction["detected"] is True
    # 상대 경로가 절대 URL 로 바뀌어 나간다
    assert prediction["mask_url"].startswith("http")


def test_prediction_does_not_affect_grading(client, sidecar_dir, user_a, roi_match):
    """모델이 완전히 틀린(Dice 0) 케이스여도 사용자 채점은 기준 마스크 기준 그대로다."""
    without = user_a.submit(roi_match).json()

    write_sidecar(sidecar_dir, detected=False, mask_url=None, dice_vs_reference=0.0)
    with_prediction = user_a.submit(roi_match).json()

    assert with_prediction["grade"] == without["grade"]
    assert with_prediction["dice"] == without["dice"]
    assert with_prediction["iou"] == without["iou"]
    assert with_prediction["location_score"] == without["location_score"]
    assert with_prediction["ai_prediction"]["detected"] is False


def test_no_sidecar_yields_null_prediction(client, sidecar_dir, user_a, roi_match):
    body = user_a.submit(roi_match).json()
    assert body["ai_prediction"] is None


def test_ai_failure_case_shape_vs_seg_204(client, sidecar_dir, user_a):
    """VS-SEG-204 형태 — **AI 실패와 학습 채점의 독립성**을 보여주는 대표 케이스.

    실제 등록된 VS-SEG-204 는:
      - 전문가 GT 존재 (3,628 voxel, 대표 slice 37 / 702px)
      - 사용자가 기준 마스크대로 제출하면 Dice 1.0 / match
      - AI 는 병변을 전혀 찾지 못함 (dice_vs_reference 0.0, detected false, mask_url null)
    여기서는 같은 조건을 픽스처로 재현해 **AI 실패가 grade 에 전혀 영향을 주지 않음**을 고정한다.
    """
    import base64

    write_sidecar(
        sidecar_dir,
        detected=False,
        mask_url=None,
        dice_vs_reference=0.0,
        representative_slice_dice=0.0,
        predicted_voxels=0,
    )

    # 기준 마스크를 그대로 제출 -> 완전 일치
    from app.db import SessionLocal
    from app.models import Case
    from app.static_files import resolve_local_path

    with SessionLocal() as db:
        case = db.get(Case, CASE_ID)
        mask_path = resolve_local_path(case.reference_mask_url)

    payload = base64.b64encode(mask_path.read_bytes()).decode()
    body = user_a.post(
        f"/api/cases/{CASE_ID}/submit",
        json={"roi": {"type": "brush_mask", "mask_png_base64": payload}},
    ).json()

    # 학습자 채점: 전문가 GT 기준으로 완전 일치
    assert body["grade"] == "match"
    assert body["dice"] == 1.0
    assert body["evaluation"]["method"] == "reference_mask"

    # AI: 완전 실패
    assert body["ai_prediction"]["detected"] is False
    assert body["ai_prediction"]["dice_vs_reference"] == 0.0
    assert body["ai_prediction"]["mask_url"] is None


# -------------------------------------------------- volume 모델은 2D 호출 금지
def test_volume_model_is_not_called_with_a_slice_png():
    """slice PNG 로 부르면 학습 때와 다른 입력이라 조용히 틀린 마스크가 나온다."""
    import importlib.util
    from pathlib import Path

    from app.inference import MODELS_DIR

    path = MODELS_DIR / "brain_mri_vs" / "inference.py"
    spec = importlib.util.spec_from_file_location("brain_mri_vs_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.INPUT_KIND == "volume"
    with pytest.raises(module.VolumeModelError) as exc:
        module.predict(str(Path("does-not-matter.png")))
    assert "volume" in str(exc.value)


def test_grading_skips_live_inference_for_volume_models(client, sidecar_dir, monkeypatch, user_a, roi_match):
    """sidecar 가 없고 모델이 volume 입력이면, predict() 를 부르지 않고 그냥 null 이어야 한다."""
    from app import grading, inference

    class FakeVolumeModule:
        MODEL_VERSION = "fake-volume"
        INPUT_KIND = "volume"

        @staticmethod
        def predict(*args, **kwargs):
            raise AssertionError("volume 모델을 slice PNG 로 부르면 안 된다")

    monkeypatch.setattr(inference, "is_available", lambda body_part: True)
    monkeypatch.setattr(inference, "get_module", lambda body_part: FakeVolumeModule)

    case = type("C", (), {"case_id": CASE_ID, "body_part": "brain_mri", "image_url": None})()
    assert grading.ai_prediction(case) is None
