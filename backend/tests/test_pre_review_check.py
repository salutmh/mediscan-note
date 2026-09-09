"""
육안 검수 전 기계 점검이 **실제로 문제를 잡는지**.

이 점검기의 위험은 "전부 통과"가 나왔을 때다. 제대로 봤는데 문제가 없는 것인지,
검사가 아무것도 안 하고 있는 것인지 구분되지 않으면 검수자가 잘못된 안심을 한다.
실제로 24건을 돌렸을 때 전부 "확인할 점 없음"이 나왔고, 그래서 일부러 깨뜨려 확인했다.
그 과정에서 **빈 마스크가 경고 없이 통과**하던 것을 찾았다.

이 점검기는 사람 검수를 대신하지 않는다 — 볼 순서를 정해줄 뿐이다.
"마스크가 의학적으로 옳은 범위인가"는 여기서 판단하지 않는다.
"""
import json

import numpy as np
import pytest

from scripts.pre_review_check import check_case

# 실제 export 산출물과 같은 모양 (작게)
SHAPE = (64, 64, 12)
LESION_Z = (4, 5, 6, 7)
REPRESENTATIVE = 6


def _write_case(tmp_path, *, mask=None, meta_overrides=None):
    """볼륨(머리 밝음 + 배경 어두움) + 마스크 + 메타를 만든다."""
    case_dir = tmp_path / "VS-SEG-TEST"
    case_dir.mkdir()

    # 가운데는 밝은 조직, 바깥은 어두운 배경
    volume = np.zeros(SHAPE, dtype=np.float32)
    volume[16:48, 16:48, :] = 500.0
    np.save(case_dir / "t1_volume.npy", volume)

    if mask is None:
        mask = np.zeros(SHAPE, dtype=np.uint8)
        for z in LESION_Z:
            size = 6 if z == REPRESENTATIVE else 4
            mask[28 : 28 + size, 28 : 28 + size, z] = 1
    np.save(case_dir / "ground_truth_mask.npy", mask)

    meta = {
        "case_id": "VS-SEG-TEST",
        "gt_voxels": int(mask.sum()),
        "representative_slice": REPRESENTATIVE,
        "representative_area_px": int(mask[:, :, REPRESENTATIVE].sum()),
        "lesion_slice_count": len(LESION_Z),
        "chosen_roi": "TV",
        "roi_selected_by": "keyword",
        "laterality": {"laterality": "left", "agree": True},
    }
    meta.update(meta_overrides or {})
    (case_dir / "export_meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return case_dir


def _warnings(case_dir) -> list[str]:
    return check_case(case_dir)["warnings"]


# ------------------------------------------------------ 정상은 통과해야 한다
def test_clean_case_has_no_warnings(tmp_path):
    """가드가 아무 케이스에나 경고를 붙이면 목록이 쓸모없어진다."""
    assert _warnings(_write_case(tmp_path)) == []


def test_clean_case_reports_what_it_measured(tmp_path):
    # "확인할 점 없음"이 제대로 본 결과인지 알 수 있어야 한다
    result = check_case(_write_case(tmp_path))
    assert result["components"] == 1
    assert result["on_background_ratio"] == 0.0
    assert result["gt_voxels"] > 0


# ------------------------------------------------------ 실제 결함을 잡는가
def test_empty_mask_is_flagged(tmp_path):
    """빈 마스크 = 채점 기준이 아예 없다는 뜻이다.

    처음 만들었을 때 이 경우가 빠져 있어 **경고 없이 통과**했다.
    등록하고 나서야 드러나면 이미 학습자가 열어본 뒤다.
    """
    case = _write_case(tmp_path, mask=np.zeros(SHAPE, dtype=np.uint8))
    assert any("비어 있음" in w for w in _warnings(case))


def test_scattered_mask_is_flagged(tmp_path):
    """서로 멀리 떨어진 조각. 자동으로 지우지 않고 사람에게 올린다
    (다발성 병변일 수도 있다)."""
    mask = np.zeros(SHAPE, dtype=np.uint8)
    for z in LESION_Z:
        mask[28:34, 28:34, z] = 1
    mask[4:7, 4:7, REPRESENTATIVE] = 1  # 멀리 떨어진 조각

    warnings = _warnings(_write_case(tmp_path, mask=mask))
    assert any("덩어리" in w for w in warnings)


def test_mask_sitting_on_background_is_flagged(tmp_path):
    """마스크가 조직이 아니라 어두운 배경 위에 있으면 좌표계가 어긋난 것이다."""
    mask = np.zeros(SHAPE, dtype=np.uint8)
    for z in LESION_Z:
        mask[2:8, 2:8, z] = 1  # 머리 밖 (volume 이 0 인 영역)

    warnings = _warnings(_write_case(tmp_path, mask=mask))
    assert any("배경 위" in w for w in warnings)


def test_wrong_representative_slice_is_flagged(tmp_path):
    case = _write_case(tmp_path, meta_overrides={"representative_slice": 0})
    assert any("대표 slice" in w for w in _warnings(case))


def test_non_tumor_roi_is_flagged(tmp_path):
    """Cochlea(달팽이관)를 채점 기준으로 쓰면 학습자는 종양이 아닌 곳을 칠하게 된다."""
    case = _write_case(tmp_path, meta_overrides={"chosen_roi": "Cochlea"})
    assert any("종양이 아님" in w for w in _warnings(case))


@pytest.mark.parametrize("roi", ["TV", "AN", "GTV", "tumour", "Tumor"])
def test_known_tumor_roi_names_pass(tmp_path, roi):
    # 실제 데이터셋에 이 이름들이 섞여 있다 (TV / AN / tumour 를 확인했다)
    case = _write_case(tmp_path, meta_overrides={"chosen_roi": roi})
    assert not any("ROI" in w for w in _warnings(case))


def test_disagreeing_laterality_is_flagged(tmp_path):
    """FOV 기준과 머리 기준이 다르면 계산이 확신하지 못한 것이다."""
    case = _write_case(
        tmp_path, meta_overrides={"laterality": {"laterality": "left", "agree": False}}
    )
    assert any("편측성" in w for w in _warnings(case))


def test_missing_laterality_is_flagged(tmp_path):
    case = _write_case(tmp_path, meta_overrides={"laterality": {"laterality": None, "agree": True}})
    assert any("편측성" in w for w in _warnings(case))


def test_single_slice_lesion_is_flagged(tmp_path):
    """한 장에만 있는 마스크는 잘못 그린 것일 수 있다. 반려가 아니라 '먼저 보라'는 표시다."""
    case = _write_case(tmp_path, meta_overrides={"lesion_slice_count": 1})
    assert any("slice 1장" in w for w in _warnings(case))


# ------------------------------------------------- 여러 문제를 함께 보여주는가
def test_multiple_problems_are_all_reported(tmp_path):
    """하나만 알려주면 고치고 다시 돌리기를 반복하게 된다."""
    case = _write_case(
        tmp_path,
        meta_overrides={
            "chosen_roi": "Cochlea",
            "lesion_slice_count": 1,
            "laterality": {"laterality": None, "agree": False},
        },
    )
    warnings = _warnings(case)
    assert len(warnings) >= 3
