"""
AI 예측 sidecar 수명주기 — stale 판정 · 검증 · 승격.

**AI 예측은 채점 기준이 아니다.** sidecar 가 오래돼도 학습자의 채점은 영향을 받지 않는다.
문제는 **화면에 옛 정보가 "AI 예측"으로 나가는 것**이다.

이 테스트가 지키는 가장 중요한 것:
  **검증에 실패한 결과로 기존 예측을 덮어쓰지 않는다.**
  갈아끼워 버리면 되돌릴 근거도 함께 사라진다.
"""
import json
from pathlib import Path

import pytest

from app import sidecar_lifecycle as life

CASE = "VS-SEG-500"
MODEL = "vs-seg-v1"


def _sidecar(**overrides) -> dict:
    base = {
        "case_id": CASE,
        "model_version": MODEL,
        "dice_vs_reference": 0.9,
        "reference_voxels": 12000,
        "detected": True,
        "mask_url": f"/static/cases/{CASE}/prediction.png",
        "generated_at": "2026-09-09T00:00:00+00:00",
        "sidecar_version": life.CURRENT_SIDECAR_VERSION,
        "weights": {"sha256": "w" * 64},
        "source_gt": {"sha256": "g" * 64},
        "source_volume": {"sha256": "v" * 64},
    }
    base.update(overrides)
    return base


def _write_case(tmp_path, sidecar=None, *, with_mask=True) -> Path:
    case_dir = tmp_path / "cases" / CASE
    case_dir.mkdir(parents=True, exist_ok=True)
    if sidecar is not None:
        (case_dir / life.SIDECAR_NAME).write_text(
            json.dumps(sidecar, ensure_ascii=False), encoding="utf-8"
        )
    if with_mask:
        (case_dir / life.MASK_NAME).write_bytes(b"fake-png")
    return case_dir


def _reasons(result) -> list[str]:
    return result["reasons"]


# ------------------------------------------------------------ stale 판정
def test_healthy_sidecar_needs_nothing(tmp_path):
    case_dir = _write_case(tmp_path, _sidecar())
    result = life.evaluate(CASE, case_dir, current_model_version=MODEL)
    assert _reasons(result) == []
    assert result["needs_recompute"] is False


def test_missing_sidecar_is_not_a_failure(tmp_path):
    """없으면 `ai_prediction: null` 로 정직하게 나간다 — 틀린 것이 아니다."""
    result = life.evaluate(CASE, tmp_path / "nope")
    assert life.STALE_MISSING in _reasons(result)
    assert result["needs_recompute"] is False
    assert result["present"] is False


def test_unreadable_sidecar_needs_recompute(tmp_path):
    case_dir = _write_case(tmp_path)
    (case_dir / life.SIDECAR_NAME).write_text("{ not json", encoding="utf-8")
    result = life.evaluate(CASE, case_dir, current_model_version=MODEL)
    assert life.STALE_UNREADABLE in _reasons(result)
    assert result["needs_recompute"] is True


def test_model_version_change_is_detected(tmp_path):
    case_dir = _write_case(tmp_path, _sidecar())
    result = life.evaluate(CASE, case_dir, current_model_version="vs-seg-v2")
    assert life.STALE_MODEL_VERSION in _reasons(result)
    assert result["needs_recompute"] is True


def test_old_schema_is_detected(tmp_path):
    case_dir = _write_case(tmp_path, _sidecar(sidecar_version=1))
    result = life.evaluate(CASE, case_dir, current_model_version=MODEL)
    assert life.STALE_SCHEMA in _reasons(result)


def test_weights_change_is_detected(tmp_path):
    """가중치가 바뀌면 같은 model_version 이라도 결과가 달라진다."""
    case_dir = _write_case(tmp_path, _sidecar())
    weights = tmp_path / "model.pth"
    weights.write_bytes(b"new-weights")

    result = life.evaluate(CASE, case_dir, current_model_version=MODEL, weights_path=weights)
    assert life.STALE_WEIGHTS in _reasons(result)
    assert result["details"]["weights_sha256"]["sidecar"] == "w" * 64


def test_ground_truth_change_is_detected(tmp_path):
    """**GT 가 바뀌었는데 예측이 그대로면 옛 GT 기준 지표가 화면에 나간다.**"""
    case_dir = _write_case(tmp_path, _sidecar())
    export = tmp_path / "export"
    export.mkdir()
    (export / "ground_truth_mask.npy").write_bytes(b"new-gt")
    (export / "t1_volume.npy").write_bytes(b"new-volume")

    result = life.evaluate(CASE, case_dir, current_model_version=MODEL, export_dir=export)
    assert life.STALE_GT in _reasons(result)
    assert life.STALE_VOLUME in _reasons(result)


def test_gt_voxel_mismatch_is_detected(tmp_path):
    case_dir = _write_case(tmp_path, _sidecar())
    result = life.evaluate(
        CASE, case_dir, current_model_version=MODEL, registered_gt_voxels=999
    )
    assert life.STALE_GT_VOXELS in _reasons(result)


def test_internal_inconsistency_is_detected(tmp_path):
    """미검출인데 마스크 URL 이 남으면 화면이 있지도 않은 예측을 그린다."""
    case_dir = _write_case(tmp_path, _sidecar(detected=False))
    result = life.evaluate(CASE, case_dir, current_model_version=MODEL)
    assert life.STALE_INCONSISTENT in _reasons(result)


def test_unchecked_items_are_reported_not_assumed_ok(tmp_path):
    """확인하지 못한 것을 '이상 없음'으로 뭉개면 안 된다."""
    case_dir = _write_case(tmp_path, _sidecar())
    result = life.evaluate(CASE, case_dir)  # 비교 대상을 아무것도 주지 않았다
    assert "model_version" in result["unchecked"]
    assert "weights" in result["unchecked"]
    assert "ground_truth" in result["unchecked"]


# ------------------------------------------------------------------ 계획
def test_plan_separates_recompute_missing_and_fine(tmp_path):
    evaluations = [
        {"case_id": "A", "needs_recompute": True, "reasons": [life.STALE_MODEL_VERSION], "details": {}, "unchecked": []},
        {"case_id": "B", "needs_recompute": False, "reasons": [life.STALE_MISSING], "details": {}, "unchecked": []},
        {"case_id": "C", "needs_recompute": False, "reasons": [], "details": {}, "unchecked": ["weights"]},
    ]
    plan = life.build_plan(evaluations)
    assert plan["counts"] == {"total": 3, "needs_recompute": 1, "missing": 1, "up_to_date": 1}
    assert plan["missing"] == ["B"]
    assert plan["up_to_date"] == ["C"]
    assert plan["unchecked"] == {"C": ["weights"]}


def test_plan_explains_reasons_in_words(tmp_path):
    evaluations = [
        {"case_id": "A", "needs_recompute": True, "reasons": [life.STALE_GT], "details": {}, "unchecked": []}
    ]
    plan = life.build_plan(evaluations)
    assert "전문가 GT 가 바뀌었다" in plan["recompute"][0]["reason_text"][0]


def test_plan_states_that_predictions_are_not_grading(tmp_path):
    plan = life.build_plan([])
    assert "채점 기준이 아닙니다" in plan["note"]
    assert "검증을 통과하지 못한 결과는 승격되지 않습니다" in plan["safety"]


# ------------------------------------------------------------------ 검증
def test_valid_staged_sidecar_passes(tmp_path):
    staging = tmp_path / "staging" / CASE
    staging.mkdir(parents=True)
    (staging / life.SIDECAR_NAME).write_text(json.dumps(_sidecar()), encoding="utf-8")
    (staging / life.MASK_NAME).write_bytes(b"png")

    result = life.validate_staged(CASE, staging, current_model_version=MODEL)
    assert result["ok"] is True
    assert result["problems"] == []


@pytest.mark.parametrize("field", ["model_version", "detected", "sidecar_version", "generated_at"])
def test_missing_required_field_fails(tmp_path, field):
    staging = tmp_path / "staging" / CASE
    staging.mkdir(parents=True)
    data = _sidecar()
    data[field] = None
    (staging / life.SIDECAR_NAME).write_text(json.dumps(data), encoding="utf-8")
    (staging / life.MASK_NAME).write_bytes(b"png")

    result = life.validate_staged(CASE, staging, current_model_version=MODEL)
    assert result["ok"] is False


def test_wrong_model_version_cannot_be_promoted(tmp_path):
    """다른 모델 결과를 현재 모델 결과인 척 올릴 수 없어야 한다."""
    staging = tmp_path / "staging" / CASE
    staging.mkdir(parents=True)
    (staging / life.SIDECAR_NAME).write_text(
        json.dumps(_sidecar(model_version="someone-elses")), encoding="utf-8"
    )
    (staging / life.MASK_NAME).write_bytes(b"png")

    result = life.validate_staged(CASE, staging, current_model_version=MODEL)
    assert result["ok"] is False
    assert any("model_version" in p for p in result["problems"])


def test_detected_without_mask_file_fails(tmp_path):
    staging = tmp_path / "staging" / CASE
    staging.mkdir(parents=True)
    (staging / life.SIDECAR_NAME).write_text(json.dumps(_sidecar()), encoding="utf-8")
    # 마스크 파일을 만들지 않는다

    result = life.validate_staged(CASE, staging, current_model_version=MODEL)
    assert result["ok"] is False
    assert any(life.MASK_NAME in p for p in result["problems"])


def test_big_dice_drop_is_a_warning_not_a_block(tmp_path):
    """모델이 나빠진 것일 수도, 정상적인 변화일 수도 있다 — 사람이 본다."""
    existing = _write_case(tmp_path, _sidecar(dice_vs_reference=0.9))
    staging = tmp_path / "staging" / CASE
    staging.mkdir(parents=True)
    (staging / life.SIDECAR_NAME).write_text(
        json.dumps(_sidecar(dice_vs_reference=0.3)), encoding="utf-8"
    )
    (staging / life.MASK_NAME).write_bytes(b"png")

    result = life.validate_staged(
        CASE, staging, current_model_version=MODEL, existing_dir=existing
    )
    assert result["ok"] is True  # 막지는 않는다
    assert any("Dice 가 크게 떨어졌다" in w for w in result["warnings"])


def test_detection_regression_is_warned(tmp_path):
    existing = _write_case(tmp_path, _sidecar(detected=True))
    staging = tmp_path / "staging" / CASE
    staging.mkdir(parents=True)
    (staging / life.SIDECAR_NAME).write_text(
        json.dumps(_sidecar(detected=False, mask_url=None)), encoding="utf-8"
    )

    result = life.validate_staged(
        CASE, staging, current_model_version=MODEL, existing_dir=existing
    )
    assert any("검출했는데 이번에는 미검출" in w for w in result["warnings"])


# ------------------------------------------------------------------ 승격
def test_promote_backs_up_the_previous_sidecar(tmp_path):
    """**되돌릴 수 있어야 한다.**"""
    target = _write_case(tmp_path, _sidecar(dice_vs_reference=0.9))
    staging = tmp_path / "staging" / CASE
    staging.mkdir(parents=True)
    (staging / life.SIDECAR_NAME).write_text(
        json.dumps(_sidecar(dice_vs_reference=0.95)), encoding="utf-8"
    )
    (staging / life.MASK_NAME).write_bytes(b"new-png")

    outcome = life.promote(CASE, staging, target, backup_root=tmp_path / "backup")

    promoted = json.loads((target / life.SIDECAR_NAME).read_text(encoding="utf-8"))
    assert promoted["dice_vs_reference"] == 0.95

    backup_dir = Path(outcome["backup"])
    backup = json.loads((backup_dir / life.SIDECAR_NAME).read_text(encoding="utf-8"))
    assert backup["dice_vs_reference"] == 0.9
    assert life.SIDECAR_NAME in outcome["backed_up"]


def test_promote_removes_stale_mask_when_not_detected(tmp_path):
    """미검출로 바뀌었는데 옛 마스크가 남으면 화면이 없는 예측을 그린다."""
    target = _write_case(tmp_path, _sidecar(detected=True))
    assert (target / life.MASK_NAME).exists()

    staging = tmp_path / "staging" / CASE
    staging.mkdir(parents=True)
    (staging / life.SIDECAR_NAME).write_text(
        json.dumps(_sidecar(detected=False, mask_url=None)), encoding="utf-8"
    )
    # 스테이징에는 마스크가 없다

    life.promote(CASE, staging, target, backup_root=tmp_path / "backup")
    assert not (target / life.MASK_NAME).exists()


def test_promote_leaves_no_temp_files(tmp_path):
    target = _write_case(tmp_path, _sidecar())
    staging = tmp_path / "staging" / CASE
    staging.mkdir(parents=True)
    (staging / life.SIDECAR_NAME).write_text(json.dumps(_sidecar()), encoding="utf-8")
    (staging / life.MASK_NAME).write_bytes(b"png")

    life.promote(CASE, staging, target, backup_root=tmp_path / "backup")
    leftovers = [p.name for p in target.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_promote_refuses_when_sidecar_absent(tmp_path):
    target = _write_case(tmp_path, _sidecar())
    empty = tmp_path / "staging" / CASE
    empty.mkdir(parents=True)

    with pytest.raises(life.SidecarError):
        life.promote(CASE, empty, target, backup_root=tmp_path / "backup")
