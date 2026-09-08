"""
VS-SEG DICOM -> npy 배치 export.

**이 스크립트는 새 전처리를 만들지 않는다.** `02_run_pretrained_model.ipynb` 의
cell 3(T1 시리즈 선택) / cell 4(RTSTRUCT ROI -> GT mask) / cell 5(volume 스택) 로직을
그대로 옮긴 것이고, 모델 추론과 z-score 정규화(cell 6)는 포함하지 않는다
(여기서 만드는 것은 **표시·채점용 원본 volume 과 전문가 GT** 뿐이다).

노트북과 다른 점은 **ROI 선택 안전장치 하나뿐**이다 (아래 "ROI 선택" 참고).
노트북은 키워드에 맞는 ROI 가 없으면 roi_names[0] 을 조용히 골랐지만, 여기서는
사람이 확인하도록 중단한다. 배열 산출물 자체는 노트북과 동일해야 하며
`--verify-against` 로 그것을 강제한다.

노트북과 동일한 산출물을 같은 이름으로 저장한다:
    <출력>/<CASE_ID>/t1_volume.npy          (H, W, S) float32  — raw intensity
    <출력>/<CASE_ID>/ground_truth_mask.npy  (H, W, S) uint8    — 전문가 RTSTRUCT 변환
    <출력>/<CASE_ID>/export_meta.json       shape/병변 slice/대표 slice/편측성 등 요약

의존성: pydicom, rt_utils, numpy
    노트북 환경에 이미 설치돼 있다. 백엔드 서비스에는 필요 없으므로 requirements.txt 에 넣지 않는다.
    실행 예 (학습 리포의 venv 사용 — 경로는 각자 환경에 맞게):
        <VS_SEG_ROOT>/.venv/Scripts/python.exe -m scripts.export_vs_seg_npy
            --data-root <VS-SEG DICOM 루트> --out data/vs_seg_export --cases VS-SEG-202
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

# ------------------------------------------------------------------ ROI 선택
# 종양 ROI 이름 규칙.
#   EXACT     : 두 글자 약어라 부분일치를 쓰면 다른 ROI 를 잘못 잡는다
#               (예: "an" 은 "Brainstem", "Gland", "Canal" 안에도 들어 있다).
#   SUBSTRING : 충분히 긴 단어라 부분일치가 안전하다.
TUMOR_ROI_EXACT = frozenset({"tv", "an", "vs", "gtv", "ctv", "target"})
TUMOR_ROI_SUBSTRING = (
    "tumor",
    "tumour",
    "schwannoma",
    "acoustic neuroma",
    "acousticneuroma",
    "neuroma",
)


class RoiSelectionError(RuntimeError):
    """종양 ROI 를 이름으로 확정할 수 없음 — 사람이 확인해야 한다."""


def normalize_roi_name(name: str) -> str:
    """비교용 정규화. ROI 이름에는 '*Skull', 'AN_1', 'Tumor-Volume' 같은 표기가 섞여 있다."""
    return re.sub(r"[\s_\-*.]+", " ", str(name).strip().lower()).strip()


def match_tumor_rois(roi_names: list[str]) -> list[str]:
    """종양으로 인정되는 ROI 이름만 원래 순서대로 추린다."""
    matched = []
    for name in roi_names:
        normalized = normalize_roi_name(name)
        if normalized in TUMOR_ROI_EXACT or any(k in normalized for k in TUMOR_ROI_SUBSTRING):
            matched.append(name)
    return matched


def select_tumor_roi(roi_names: list[str], override: str | None = None) -> tuple[str, list[str]]:
    """종양 ROI 를 고른다. (선택된 이름, 키워드에 걸린 후보 목록)

    **자동 선택은 후보가 정확히 1개일 때만 한다.** 0개면 물론이고, 2개 이상이어도 중단한다 —
    후보 중 아무거나(첫 번째든 뭐든) 고르면 잘못된 마스크가 조용히 채점 기준이 될 수 있다.
    애매하면 사람이 영상으로 확인한 뒤 `--roi CASE_ID=ROI이름` 으로 명시해야 진행된다.
    """
    if override:
        if override not in roi_names:
            raise RoiSelectionError(
                f"--roi 로 지정한 '{override}' 가 RTSTRUCT 에 없습니다. ROI 목록: {roi_names}"
            )
        return override, [override]

    matched = match_tumor_rois(roi_names)
    if len(matched) == 1:
        return matched[0], matched

    if not matched:
        reason = "종양 ROI 를 이름으로 찾지 못했습니다."
    else:
        reason = f"종양 후보 ROI 가 {len(matched)}개라 어느 것이 종양인지 확정할 수 없습니다: {matched}"

    raise RoiSelectionError(
        f"{reason} export 를 중단합니다 (임의로 하나를 고르지 않습니다).\n"
        f"    RTSTRUCT ROI 목록: {roi_names}\n"
        f"    인정 이름(완전일치): {sorted(TUMOR_ROI_EXACT)}\n"
        f"    인정 이름(부분일치): {list(TUMOR_ROI_SUBSTRING)}\n"
        "    사람이 영상으로 확인한 뒤 --roi <CASE_ID>=<ROI 이름> 으로 지정하세요."
    )


# ---------------------------------------------------------------- 노트북 cell 3
def find_t1_series(patient_dir: Path):
    """MR 시리즈 중 SeriesDescription 에 't1' 이 들어간 것을 고른다 (노트북 cell 3 그대로)."""
    import pydicom

    series: dict[str, dict] = {}
    rtstruct_files: list[Path] = []

    for f in patient_dir.rglob("*.dcm"):
        try:
            ds = pydicom.dcmread(f, stop_before_pixels=True, force=True)
            modality = str(getattr(ds, "Modality", ""))
            if modality == "MR":
                uid = str(getattr(ds, "SeriesInstanceUID", ""))
                desc = str(getattr(ds, "SeriesDescription", ""))
                series.setdefault(uid, {"description": desc, "files": []})["files"].append(f)
            elif modality == "RTSTRUCT":
                rtstruct_files.append(f)
        except Exception:
            pass

    t1_uid = next((uid for uid, info in series.items() if "t1" in info["description"].lower()), None)
    if t1_uid is None:
        raise RuntimeError("T1 시리즈를 찾지 못했습니다.")

    return series[t1_uid], rtstruct_files


# ---------------------------------------------------------------- 노트북 cell 4
def load_gt_mask(t1_folder: Path, rtstruct_files: list[Path], roi_override: str | None = None):
    """T1 과 연결되는 RTSTRUCT 에서 종양 ROI 마스크를 얻는다.

    RTSTRUCT 탐색과 마스크 변환은 노트북 cell 4 그대로이고, ROI 이름 선택만
    select_tumor_roi() 로 바꿨다 (자동 첫 번째 선택 제거).
    """
    from rt_utils import RTStructBuilder

    rt = None
    chosen_rtstruct = None
    for f in rtstruct_files:
        try:
            candidate = RTStructBuilder.create_from(
                dicom_series_path=str(t1_folder), rt_struct_path=str(f)
            )
            names = candidate.get_roi_names()
            if names:
                rt = candidate
                chosen_rtstruct = f
                break
        except Exception:
            continue

    if rt is None:
        raise RuntimeError("T1과 연결되는 RTSTRUCT를 찾지 못했습니다.")

    roi_names = rt.get_roi_names()
    chosen_roi, matched = select_tumor_roi(roi_names, roi_override)
    gt_mask = rt.get_roi_mask_by_name(chosen_roi).astype(bool)
    return gt_mask, chosen_roi, roi_names, matched, chosen_rtstruct


# ---------------------------------------------------------------- 노트북 cell 5
def stack_volume(t1_files: list[Path]):
    """T1 DICOM 을 3D volume 으로 쌓는다 (노트북 cell 5 그대로)."""
    import pydicom

    slices = []
    for f in t1_files:
        ds = pydicom.dcmread(f, force=True)
        if hasattr(ds, "ImagePositionPatient"):
            order = float(ds.ImagePositionPatient[2])
        else:
            order = float(getattr(ds, "InstanceNumber", 0))
        slices.append((order, ds))

    slices.sort(key=lambda x: x[0])
    return np.stack([ds.pixel_array.astype(np.float32) for _, ds in slices], axis=-1)


# -------------------------------------------------------------- 기하 / 편측성
def read_geometry(t1_files: list[Path]) -> dict:
    """정렬된 첫 slice 의 DICOM 기하 태그. 편측성 판정용이며 배열 산출물에는 영향이 없다."""
    import pydicom

    entries = []
    for f in t1_files:
        ds = pydicom.dcmread(f, stop_before_pixels=True, force=True)
        if hasattr(ds, "ImagePositionPatient"):
            order = float(ds.ImagePositionPatient[2])
        else:
            order = float(getattr(ds, "InstanceNumber", 0))
        entries.append((order, ds))
    entries.sort(key=lambda x: x[0])
    first = entries[0][1]

    def floats(tag: str):
        value = getattr(first, tag, None)
        return [float(v) for v in value] if value is not None else None

    return {
        "image_orientation_patient": floats("ImageOrientationPatient"),
        "image_position_patient_first": floats("ImagePositionPatient"),
        "pixel_spacing": floats("PixelSpacing"),
        "rows": int(getattr(first, "Rows", 0)),
        "columns": int(getattr(first, "Columns", 0)),
    }


def infer_laterality(volume: np.ndarray, gt_mask: np.ndarray, geometry: dict) -> dict:
    """DICOM 방향 태그로 병변의 좌/우를 판정한다. **해설에 추정 문구를 쓰지 않기 위한 근거 계산이다.**

    DICOM 환자좌표계에서 +x 는 환자의 **왼쪽**이다. ImageOrientationPatient 의 앞 3개가
    행 방향(= 열 인덱스가 커지는 방향)이므로, 그 x 성분 부호로 "열 인덱스 증가 = 좌/우" 가 정해진다.

    중앙선은 두 가지로 잡아 서로 대조한다:
      - FOV 중심 (columns-1)/2
      - 머리 전경(배경보다 밝은 픽셀)의 열 중심
    둘이 어긋나면 laterality 를 None 으로 두고 사람이 확인하게 한다.
    """
    iop = geometry.get("image_orientation_patient")
    result: dict = {"laterality": None, "basis": None}
    if not iop or len(iop) < 6:
        result["basis"] = "ImageOrientationPatient 없음 — 판정 불가"
        return result

    row_dir_x = float(iop[0])
    if abs(row_dir_x) < 0.9:
        result["basis"] = f"사입(oblique) 방향이라 자동 판정 불가 (row_dir={iop[:3]})"
        return result

    lesion_cols = np.nonzero(gt_mask)[1]
    if lesion_cols.size == 0:
        result["basis"] = "GT 마스크가 비어 있음"
        return result

    lesion_center = float(lesion_cols.mean())
    fov_center = (volume.shape[1] - 1) / 2.0

    # 머리 전경 = 배경보다 충분히 밝은 픽셀 (판정 보조용이라 임계값은 느슨해도 된다)
    threshold = float(np.percentile(volume, 99)) * 0.15
    foreground_cols = np.nonzero(np.any(volume > threshold, axis=(0, 2)))[0]
    head_center = float(foreground_cols.mean()) if foreground_cols.size else fov_center

    def side(center: float) -> str:
        toward_left = (lesion_center - center) * (1.0 if row_dir_x > 0 else -1.0)
        return "left" if toward_left > 0 else "right"

    by_fov = side(fov_center)
    by_head = side(head_center)

    result.update(
        {
            "laterality": by_fov if by_fov == by_head else None,
            "laterality_by_fov_center": by_fov,
            "laterality_by_head_center": by_head,
            "agree": by_fov == by_head,
            "lesion_col_center": round(lesion_center, 1),
            "fov_col_center": round(fov_center, 1),
            "head_col_center": round(head_center, 1),
            "row_direction": [round(v, 4) for v in iop[:3]],
            "basis": (
                "DICOM ImageOrientationPatient + GT 마스크 열 중심"
                if by_fov == by_head
                else "FOV 중심 기준과 머리 중심 기준이 어긋남 — 사람이 확인 필요"
            ),
        }
    )
    return result


# ------------------------------------------------------------------------ 요약
def summarize(volume: np.ndarray, gt_mask: np.ndarray) -> dict:
    """슬라이스 축은 axis 2 (노트북 cell 10 의 gt_mask.sum(axis=(0,1)) 과 동일)."""
    areas = gt_mask.sum(axis=(0, 1))
    lesion_slices = np.nonzero(areas)[0]
    return {
        "shape": list(volume.shape),
        "volume_dtype": str(volume.dtype),
        "mask_dtype": str(gt_mask.astype(np.uint8).dtype),
        "intensity_min": float(volume.min()),
        "intensity_max": float(volume.max()),
        "gt_voxels": int(gt_mask.sum()),
        "lesion_slice_min": int(lesion_slices.min()) if lesion_slices.size else None,
        "lesion_slice_max": int(lesion_slices.max()) if lesion_slices.size else None,
        "lesion_slice_count": int(lesion_slices.size),
        "representative_slice": int(np.argmax(areas)) if lesion_slices.size else None,
        "representative_area_px": int(areas.max()) if lesion_slices.size else 0,
    }


def load_case(patient_dir: Path, roi_override: str | None = None):
    """(meta, volume, gt_mask). 저장 경로와 대조 경로가 갈라지지 않도록 한 군데로 모았다."""
    t1_info, rtstruct_files = find_t1_series(patient_dir)
    t1_files = t1_info["files"]

    gt_mask, chosen_roi, roi_names, matched, rtstruct = load_gt_mask(
        t1_files[0].parent, rtstruct_files, roi_override
    )
    volume = stack_volume(t1_files)
    if volume.shape != gt_mask.shape:
        raise RuntimeError(f"영상 {volume.shape} / mask {gt_mask.shape} 크기가 다릅니다.")

    geometry = read_geometry(t1_files)
    meta = summarize(volume, gt_mask)
    meta.update(
        {
            "case_id": patient_dir.name,
            "t1_description": t1_info["description"],
            "t1_slice_files": len(t1_files),
            "roi_names": roi_names,
            "roi_keyword_matches": matched,
            "chosen_roi": chosen_roi,
            "roi_selected_by": "override" if roi_override else "keyword",
            "rtstruct": rtstruct.name if rtstruct else None,
            "geometry": geometry,
            "laterality": infer_laterality(volume, gt_mask, geometry),
        }
    )
    return meta, volume, gt_mask


def save_case(out_dir: Path, meta: dict, volume: np.ndarray, gt_mask: np.ndarray) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / "t1_volume.npy", volume.astype(np.float32))
    np.save(out_dir / "ground_truth_mask.npy", gt_mask.astype(np.uint8))
    (out_dir / "export_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ------------------------------------------------------------------------ 대조
VERIFY_KEYS = [
    "shape",
    "volume_dtype",
    "mask_dtype",
    "intensity_min",
    "intensity_max",
    "gt_voxels",
    "lesion_slice_min",
    "lesion_slice_max",
    "lesion_slice_count",
    "representative_slice",
    "representative_area_px",
]


def verify_against(reference_dir: Path, meta: dict, volume=None, gt_mask=None) -> list[str]:
    """기존 노트북 산출물과 항목별로 대조한다. 불일치 목록을 돌려준다."""
    problems = []
    ref_volume = np.load(reference_dir / "t1_volume.npy", mmap_mode="r")
    ref_mask = np.load(reference_dir / "ground_truth_mask.npy", mmap_mode="r")
    ref_meta = summarize(np.asarray(ref_volume), np.asarray(ref_mask))

    for key in VERIFY_KEYS:
        if meta[key] != ref_meta[key]:
            problems.append(f"{key}: 기존={ref_meta[key]} / 재현={meta[key]}")

    # 값 자체가 동일한지도 확인 (요약이 같아도 내용이 다를 수 있다)
    if volume is not None and not np.array_equal(np.asarray(ref_volume), volume):
        problems.append("volume 픽셀 값이 기존 산출물과 다릅니다")
    if gt_mask is not None and not np.array_equal(np.asarray(ref_mask).astype(bool), gt_mask):
        problems.append("GT mask 값이 기존 산출물과 다릅니다")

    return problems


def _parse_roi_overrides(values: list[str] | None) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for item in values or []:
        if "=" not in item:
            raise SystemExit(f"--roi 형식은 CASE_ID=ROI이름 입니다: {item}")
        case_id, roi = item.split("=", 1)
        overrides[case_id.strip()] = roi.strip()
    return overrides


def main() -> int:
    parser = argparse.ArgumentParser(description="VS-SEG DICOM -> npy export (노트북 로직 그대로)")
    parser.add_argument("--data-root", type=Path, required=True, help="원본 DICOM 루트")
    parser.add_argument("--out", type=Path, help="출력 루트 (생략 시 저장하지 않음)")
    parser.add_argument("--cases", nargs="+", required=True, help="예: VS-SEG-202 VS-SEG-203")
    parser.add_argument(
        "--roi",
        nargs="*",
        help="자동 선택이 중단됐을 때 사람이 확인한 ROI 를 지정: CASE_ID=ROI이름",
    )
    parser.add_argument(
        "--verify-against", type=Path, help="기존 노트북 산출물 루트 (예: .../outputs) 와 대조"
    )
    args = parser.parse_args()
    overrides = _parse_roi_overrides(args.roi)

    exit_code = 0
    for case_id in args.cases:
        patient_dir = args.data_root / case_id
        print(f"=== {case_id} ===")
        if not patient_dir.exists():
            print(f"  [실패] 폴더 없음: {patient_dir}")
            exit_code = 1
            continue

        try:
            meta, volume, gt_mask = load_case(patient_dir, overrides.get(case_id))
        except RoiSelectionError as exc:
            print(f"  [중단] {exc}")
            exit_code = 1
            continue
        except Exception as exc:
            print(f"  [실패] {exc}")
            exit_code = 1
            continue

        print(f"  T1: {meta['t1_description']} ({meta['t1_slice_files']}장)")
        print(f"  ROI 목록: {meta['roi_names']}")
        print(
            f"  ROI 선택: {meta['chosen_roi']}  "
            f"(키워드 후보 {meta['roi_keyword_matches']}, 근거={meta['roi_selected_by']})"
        )
        print(f"  shape={meta['shape']} dtype={meta['volume_dtype']}/{meta['mask_dtype']}")
        print(f"  intensity {meta['intensity_min']}~{meta['intensity_max']}")
        print(f"  GT voxel={meta['gt_voxels']:,}")
        print(
            f"  병변 slice {meta['lesion_slice_min']}~{meta['lesion_slice_max']} "
            f"({meta['lesion_slice_count']}장), 대표={meta['representative_slice']} "
            f"({meta['representative_area_px']}px)"
        )
        lat = meta["laterality"]
        print(
            f"  편측성={lat.get('laterality')} "
            f"(병변 열중심 {lat.get('lesion_col_center')} / FOV {lat.get('fov_col_center')} / "
            f"머리 {lat.get('head_col_center')}, row_dir={lat.get('row_direction')})"
        )

        if args.verify_against:
            ref_dir = args.verify_against / case_id
            if not ref_dir.exists():
                print(f"  [대조 건너뜀] 기존 산출물 없음: {ref_dir}")
            else:
                problems = verify_against(ref_dir, meta, volume=volume, gt_mask=gt_mask)
                if problems:
                    exit_code = 1
                    print("  [대조 실패]")
                    for p in problems:
                        print(f"    - {p}")
                else:
                    print("  [대조 성공] 기존 노트북 산출물과 완전히 일치")

        if args.out:
            save_case(args.out / case_id, meta, volume, gt_mask)
            print(f"  저장: {args.out / case_id}")
        print()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
