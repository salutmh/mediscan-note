"""
케이스 후보 정보 모으기 — 검수 화면이 쓰는 읽기 전용 계층.

후보 하나에 대한 사실이 세 파일에 흩어져 있다:

  `<export_root>/<CASE>/export_meta.json`   실제 export 결과 (GT voxel·편측성·ROI·기하)
  `<review_root>/review_summary.json`       검수 시트 생성 결과 (시트 파일명·bbox·표시 윈도우)
  `data/vs_seg_screening.json`              후보로 고른 근거 (크기 계층·전체 분포)

검수자는 이걸 합쳐서 봐야 판단할 수 있다. **여기서는 계산된 값을 옮기기만 한다.**

==========================================================================
**여기서 만들지 않는 것**
==========================================================================
- 의료 소견·진단·난이도 — 어떤 것도 생성하지 않는다
- GT 수정 — 읽기만 한다
- AI 예측을 GT 처럼 다루는 것 — 예측이 있으면 **별도 블록**으로 분리해서 내보내고,
  화면에서도 색·레이어를 완전히 다르게 쓴다 (`ai_prediction` 키)

`provenance` 는 "이 숫자가 어디서 왔는가"를 검수자가 되짚을 수 있게 남기는 것이다.
출처를 모르는 값은 검수할 수 없다.
"""
import json
from pathlib import Path

from app import model_predictions

BACKEND_DIR = Path(__file__).resolve().parent.parent

# 크기 계층은 스크리닝이 GT voxel 3분위로 나눈 **계산값**이다.
# 의료적 난이도가 아니다 — 화면에도 그렇게 적는다.
SIZE_BUCKET_LABEL = {
    "small": "작음 (하위 1/3)",
    "medium": "중간 (중위 1/3)",
    "large": "큼 (상위 1/3)",
}


def _read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _screening_index(screening_path: Path) -> tuple[dict, dict]:
    """스크리닝 결과를 case_id 로 색인한다. (전체, 추천상세) 두 벌."""
    data = _read_json(screening_path)
    if not isinstance(data, dict):
        return {}, {}
    everything = {c["case_id"]: c for c in data.get("cases", []) if "case_id" in c}
    recommended = {
        c["case_id"]: c for c in data.get("recommended_detail", []) if "case_id" in c
    }
    return everything, recommended


def _sheet_index(review_root: Path) -> dict:
    rows = _read_json(review_root / "review_summary.json")
    if not isinstance(rows, list):
        return {}
    return {r["case_id"]: r for r in rows if "case_id" in r}


def _pre_check_index(review_root: Path) -> dict:
    rows = _read_json(review_root / "pre_review.json")
    if not isinstance(rows, list):
        return {}
    return {r["case_id"]: r for r in rows if "case_id" in r}


def _ai_prediction(case_id: str) -> dict | None:
    """미리 계산된 AI 예측이 있으면 **참고 정보로만** 붙인다.

    **채점 기준이 아니다.** VS-SEG-204 처럼 GT 는 정상인데 AI 가 병변을 전혀 못 찾는
    케이스가 실제로 있다. 검수자가 "AI 가 못 찾았으니 GT 가 틀렸다"고 읽으면 안 되므로
    응답에서 GT 값과 **다른 블록**으로 내보내고, 그 사실을 문구로도 함께 보낸다.
    """
    try:
        sidecar = model_predictions.load(case_id)
    except Exception:
        return None
    if not sidecar:
        return None
    return {
        "detected": sidecar.get("detected"),
        "dice_vs_reference": sidecar.get("dice_vs_reference"),
        "model_version": sidecar.get("model_version"),
        "notice": (
            "AI 예측은 참고 정보이며 채점 기준이 아닙니다. "
            "AI 가 찾지 못했다는 것이 GT 가 틀렸다는 뜻은 아닙니다."
        ),
    }


def build(case_id: str, export_root: Path, review_root: Path, screening_path: Path) -> dict | None:
    """후보 하나의 표시용 정보. export 결과가 없으면 None."""
    meta = _read_json(Path(export_root) / case_id / "export_meta.json")
    if not isinstance(meta, dict):
        return None

    all_screened, recommended = _screening_index(Path(screening_path))
    sheets = _sheet_index(Path(review_root))
    pre_checks = _pre_check_index(Path(review_root))

    screening = recommended.get(case_id) or all_screened.get(case_id) or {}
    sheet = sheets.get(case_id) or {}
    pre_check = pre_checks.get(case_id) or {}
    laterality = meta.get("laterality") or {}
    bucket = screening.get("_stratum")

    return {
        "case_id": case_id,
        # ------------------------------------------------ 계산된 객관값
        "gt_voxels": meta.get("gt_voxels"),
        "representative_slice": meta.get("representative_slice"),
        "representative_area_px": meta.get("representative_area_px"),
        "lesion_slice_count": meta.get("lesion_slice_count"),
        "lesion_slice_range": [meta.get("lesion_slice_min"), meta.get("lesion_slice_max")],
        "total_slices": (meta.get("shape") or [None, None, None])[2],
        "lesion_bbox_rowcol": sheet.get("lesion_bbox_rowcol"),
        # ------------------------------------------------ 편측성 (추측 아님)
        "laterality": laterality.get("laterality"),
        "laterality_basis": laterality.get("basis"),
        "laterality_agree": laterality.get("agree"),
        "laterality_detail": {
            "by_fov_center": laterality.get("laterality_by_fov_center"),
            "by_head_center": laterality.get("laterality_by_head_center"),
            "lesion_col_center": laterality.get("lesion_col_center"),
        },
        # ------------------------------------------------ 크기 계층 (난이도 아님)
        "size_bucket": bucket,
        "size_bucket_label": SIZE_BUCKET_LABEL.get(bucket),
        "size_bucket_basis": (
            "GT voxel 수를 후보 전체의 3분위로 나눈 계산값입니다. "
            "**의료적 난이도가 아닙니다.**"
        ),
        # ------------------------------------------------ 후보 선정 근거
        "selection_reason": (
            f"편측 {laterality.get('laterality') or '?'} / 크기 {bucket or '?'} 균형을 맞추기 위해 선정"
            if bucket
            else "스크리닝 목록에서 선정"
        ),
        # ------------------------------------------------ 원본 출처
        "dataset": "VS-SEG",
        "source_case_id": case_id,
        "provenance": {
            "roi_name": meta.get("chosen_roi"),
            "roi_candidates": meta.get("roi_names"),
            "roi_selected_by": meta.get("roi_selected_by"),
            "rtstruct_file": meta.get("rtstruct"),
            "series_description": meta.get("t1_description"),
            "dicom_slice_files": meta.get("t1_slice_files"),
            "pixel_spacing": (meta.get("geometry") or {}).get("pixel_spacing"),
            "image_orientation_patient": (meta.get("geometry") or {}).get(
                "image_orientation_patient"
            ),
            "gt_source": "데이터셋 제공 RTSTRUCT (전문가 GT). 이 파이프라인에서 수정하지 않았습니다.",
        },
        # ------------------------------------------------ 기계 사전점검
        "pre_check": {
            "components": pre_check.get("components"),
            "on_background_ratio": pre_check.get("on_background_ratio"),
            "warnings": pre_check.get("warnings", []),
        },
        # ------------------------------------------------ AI 예측 (참고 전용)
        "ai_prediction": _ai_prediction(case_id),
        # ------------------------------------------------ 검수 시트
        "sheet_available": bool(sheet.get("sheet"))
        and (Path(review_root) / case_id / str(sheet.get("sheet"))).exists(),
        "display_window": sheet.get("display_window"),
    }


def list_case_ids(export_root: Path) -> list[str]:
    root = Path(export_root)
    if not root.exists():
        return []
    return sorted(d.name for d in root.iterdir() if (d / "export_meta.json").exists())


def sheet_path(case_id: str, review_root: Path) -> Path | None:
    """검수 시트 PNG 의 실제 경로. 경로 조작을 막기 위해 review_root 밖이면 None."""
    root = Path(review_root).resolve()
    sheets = _sheet_index(root)
    filename = (sheets.get(case_id) or {}).get("sheet")
    if not filename:
        return None
    candidate = (root / case_id / filename).resolve()
    if not candidate.is_file():
        return None
    if root not in candidate.parents:
        return None  # review_root 밖을 가리키면 거부한다
    return candidate
