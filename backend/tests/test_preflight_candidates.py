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


# ---------------------------------------------------------------------------
# 후보끼리의 중복 — **한 사람을 두 번 등록하지 않는다**
# ---------------------------------------------------------------------------
# 242건을 기계로 선별했으므로, 서로 다른 case_id 인데 같은 환자·같은 촬영일 수 있다.
# 그대로 등록하면 학습자가 사실상 같은 영상을 두 번 풀고 통계가 부풀려진다.
def _meta(case_id, *, position=(0.0, 0.0, 0.0), gt_voxels=1000, area=500):
    return {
        "case_id": case_id,
        "shape": [512, 512, 120],
        "gt_voxels": gt_voxels,
        "representative_slice": 32,
        "representative_area_px": area,
        "geometry": {
            "image_position_patient_first": list(position),
            "pixel_spacing": [0.41, 0.41],
        },
    }


def test_two_candidates_from_the_same_scan_are_flagged():
    checks = []
    pre.check_no_duplicate_candidates(
        {"VS-SEG-100": _meta("VS-SEG-100"), "VS-SEG-200": _meta("VS-SEG-200")}, checks
    )
    assert _failed(checks) == ["후보 간 중복"]
    assert "VS-SEG-100" in checks[0]["detail"] and "VS-SEG-200" in checks[0]["detail"]


def test_the_duplicate_check_asks_a_human_and_does_not_delete():
    """**자동으로 지우지 않는다.** 같은 환자의 다른 시점일 수도 있다."""
    checks = []
    pre.check_no_duplicate_candidates(
        {"A": _meta("A"), "B": _meta("B")}, checks
    )
    assert "사람이 확인" in checks[0]["detail"]


def test_different_scans_pass():
    checks = []
    pre.check_no_duplicate_candidates(
        {
            "A": _meta("A", position=(0.0, 0.0, 0.0), gt_voxels=1000),
            "B": _meta("B", position=(-107.0, -135.0, -90.0), gt_voxels=2200),
        },
        checks,
    )
    assert not _failed(checks)


def test_the_same_position_but_different_lesion_is_not_a_duplicate():
    """촬영 위치가 같아도 병변이 다르면 다른 케이스다 (지문을 여러 값으로 만드는 이유)."""
    checks = []
    pre.check_no_duplicate_candidates(
        {"A": _meta("A", gt_voxels=1000, area=500), "B": _meta("B", gt_voxels=8800, area=1900)},
        checks,
    )
    assert not _failed(checks)


def test_one_candidate_cannot_be_compared():
    """**"확인 못함"을 "이상 없음"으로 뭉개지 않는다.**"""
    checks = []
    pre.check_no_duplicate_candidates({"A": _meta("A")}, checks)
    assert not _failed(checks)
    assert "판정 불가" in checks[0]["detail"]


def test_unreadable_metadata_is_skipped_not_counted_as_unique():
    checks = []
    pre.check_no_duplicate_candidates({"A": _meta("A"), "B": None}, checks)
    assert "1건" in checks[0]["detail"], "읽을 수 없는 후보를 비교 대상에 넣으면 안 된다"


# ---------------------------------------------------------------------------
# 출처 정보 — **어디서 온 케이스인지 되짚을 수 있어야 한다**
# ---------------------------------------------------------------------------
# 나중에 데이터셋 이용 조건(BLOCKER-1)이나 GT 출처를 확인해야 할 때,
# 이 값들이 없으면 근거가 사라진다.
FULL_PROVENANCE = {
    "case_id": "VS-SEG-003",
    "rtstruct": "0d712c68.dcm",
    "chosen_roi": "AN",
    "roi_selected_by": "keyword",
    "t1_description": "t1_fl3d_tra_gk_v1",
    "shape": [512, 512, 120],
}


def test_complete_provenance_passes():
    checks = []
    pre.check_provenance("VS-SEG-003", dict(FULL_PROVENANCE), checks)
    assert not _failed(checks)


@pytest.mark.parametrize("field", sorted(FULL_PROVENANCE))
def test_each_missing_provenance_field_is_caught(field):
    """**하나씩 다 확인한다.** 한 항목만 검사하면 나머지는 조용히 빠진다."""
    meta = dict(FULL_PROVENANCE)
    meta.pop(field)
    checks = []
    pre.check_provenance("VS-SEG-003", meta, checks)
    assert _failed(checks) == ["출처 정보"]
    assert field in checks[0]["detail"]


def test_missing_metadata_is_reported_as_unchecked():
    checks = []
    pre.check_provenance("VS-SEG-003", None, checks)
    assert _failed(checks) == ["출처 정보"]
    assert "확인 못함" in checks[0]["detail"]


def test_provenance_does_not_require_medical_content():
    """**소견·난이도를 출처로 요구하지 않는다.** 그건 전문가 몫이고 여기 없어야 정상이다."""
    for field in ("case_findings", "difficulty", "diagnosis"):
        assert field not in pre.REQUIRED_PROVENANCE
