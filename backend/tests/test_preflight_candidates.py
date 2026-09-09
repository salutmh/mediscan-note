"""
기술 통과 후보 사전 검증이 **실제로 문제를 잡는지**.

24건 전부 "통과"가 나왔을 때, 제대로 본 것인지 검사가 놀고 있는 것인지 구분되어야 한다.
(같은 이유로 `pre_review_check` 에서 빈 마스크가 통과하던 구멍을 찾은 적이 있다.)

여기서 확인하는 것은 전부 **의료 판단이 필요 없는** 기술 항목이다.
"""
import json

import numpy as np
import pytest

from scripts import preflight_candidates as pre

CASE = "VS-SEG-700"
SHAPE = (32, 32, 12)


def _write_export(root, *, shape=SHAPE, meta_overrides=None, drop=None):
    case_dir = root / CASE
    case_dir.mkdir(parents=True, exist_ok=True)

    if drop != "volume":
        np.save(case_dir / "t1_volume.npy", np.zeros(shape, dtype=np.float32))
    if drop != "mask":
        mask_shape = shape if drop != "mask_shape" else (shape[0], shape[1] // 2, shape[2])
        np.save(case_dir / "ground_truth_mask.npy", np.zeros(mask_shape, dtype=np.uint8))

    meta = {
        "case_id": CASE,
        "gt_voxels": 1000,
        "shape": list(shape),
        "representative_slice": 6,
        "lesion_slice_min": 4,
        "lesion_slice_max": 8,
        "chosen_roi": "TV",
    }
    meta.update(meta_overrides or {})
    if drop != "meta":
        (case_dir / "export_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
    return case_dir


def _run_export_checks(root):
    checks = []
    meta = pre.check_export_integrity(CASE, root, checks)
    return checks, meta


def _failed(checks):
    return [c["check"] for c in checks if not c["ok"]]


# ------------------------------------------------------ 정상은 통과
def test_healthy_export_passes(tmp_path):
    _write_export(tmp_path)
    checks, meta = _run_export_checks(tmp_path)
    assert _failed(checks) == []
    assert meta["case_id"] == CASE


# ------------------------------------------------------ 실제 결함을 잡는가
@pytest.mark.parametrize("missing", ["volume", "mask", "meta"])
def test_missing_file_is_caught(tmp_path, missing):
    _write_export(tmp_path, drop=missing)
    checks, meta = _run_export_checks(tmp_path)
    assert meta is None
    assert "export 파일 존재" in _failed(checks)


def test_volume_and_mask_shape_mismatch_is_caught(tmp_path):
    """차원이 어긋나면 채점이 엉뚱한 좌표로 이뤄진다."""
    _write_export(tmp_path, drop="mask_shape")
    checks, _ = _run_export_checks(tmp_path)
    assert "volume/mask 차원 일치" in _failed(checks)


def test_metadata_shape_mismatch_is_caught(tmp_path):
    """메타데이터가 실제 배열과 다르면 뒤 단계가 전부 어긋난다."""
    _write_export(tmp_path, meta_overrides={"shape": [64, 64, 12]})
    checks, _ = _run_export_checks(tmp_path)
    assert "메타데이터 shape 일치" in _failed(checks)


def test_representative_slice_outside_lesion_range_is_caught(tmp_path):
    """대표 slice 에 병변이 없으면 학습자가 빈 화면을 칠하게 된다."""
    _write_export(tmp_path, meta_overrides={"representative_slice": 11})
    checks, _ = _run_export_checks(tmp_path)
    assert "대표 slice 범위" in _failed(checks)


# ------------------------------------------------------ sidecar 최신성
def test_stale_sidecar_is_caught(monkeypatch):
    """옛 모델 결과가 참고 정보로 화면에 나가면 안 된다."""
    monkeypatch.setattr(
        pre.model_predictions, "load", lambda case_id: {"gt_voxels": 999, "model_version": "old"}
    )
    checks = []
    pre.check_sidecar(CASE, {"gt_voxels": 1000}, checks)
    assert "예측 sidecar 최신성" in _failed(checks)


def test_matching_sidecar_passes(monkeypatch):
    monkeypatch.setattr(
        pre.model_predictions, "load", lambda case_id: {"gt_voxels": 1000, "model_version": "v1"}
    )
    checks = []
    pre.check_sidecar(CASE, {"gt_voxels": 1000}, checks)
    assert _failed(checks) == []


def test_absent_sidecar_is_not_a_problem(monkeypatch):
    """없는 것은 문제가 아니다 — ai_prediction: null 로 정직하게 나간다."""
    monkeypatch.setattr(pre.model_predictions, "load", lambda case_id: None)
    checks = []
    pre.check_sidecar(CASE, {"gt_voxels": 1000}, checks)
    assert _failed(checks) == []


# ------------------------------------------- manifest 후보 안전성 (핵심)
def test_manifest_marked_active_is_caught(tmp_path):
    """**자동 활성화 표시는 반드시 잡혀야 한다.**"""
    package = tmp_path / "package"
    package.mkdir()
    (package / "manifest_candidate.json").write_text(
        json.dumps(
            {
                "kind": "manifest_candidate",
                "cases": [{"case_id": CASE, "intended_activation": "active"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    checks = []
    pre.check_manifest_candidate(tmp_path, checks)
    assert "manifest 후보 활성화 표시" in _failed(checks)


def test_manifest_with_medical_content_is_caught(tmp_path):
    """난이도·소견이 채워진 채로 넘어가면 전문가 검수를 건너뛴 것이다."""
    package = tmp_path / "package"
    package.mkdir()
    (package / "manifest_candidate.json").write_text(
        json.dumps(
            {
                "kind": "manifest_candidate",
                "cases": [
                    {
                        "case_id": CASE,
                        "intended_activation": "inactive_ready",
                        "difficulty": "easy",
                        "case_findings": None,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    checks = []
    pre.check_manifest_candidate(tmp_path, checks)
    assert "manifest 후보 의료 내용" in _failed(checks)


def test_safe_manifest_passes(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "manifest_candidate.json").write_text(
        json.dumps(
            {
                "kind": "manifest_candidate",
                "cases": [
                    {
                        "case_id": CASE,
                        "intended_activation": "inactive_ready",
                        "difficulty": None,
                        "case_findings": None,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    checks = []
    pre.check_manifest_candidate(tmp_path, checks)
    assert _failed(checks) == []


def test_missing_manifest_is_not_a_problem(tmp_path):
    """아직 안 만든 것은 문제가 아니다 (다음 단계가 남았다는 뜻)."""
    checks = []
    pre.check_manifest_candidate(tmp_path, checks)
    assert _failed(checks) == []
