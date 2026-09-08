"""
VS-SEG export(npy) -> 서비스 등록용 PNG 자산 + manifest 생성.

**여기서도 DB 는 건드리지 않는다.** 만들어진 manifest 를 scripts/import_cases.py 에 넘겨야
비로소 케이스가 등록된다 (검수 -> 자산 생성 -> 등록 순서를 분리해 두기 위함).

무엇을 만드는가
--------------
    <출력>/<CASE_ID>/slice_<원본index>.png   표시용 8bit 그레이스케일
    <출력>/<CASE_ID>/mask_<원본index>.png    전문가 GT (투명 배경 + 불투명 흰색)
    <출력>/manifest.json                      import_cases.py 입력

규칙
----
1. **표시용 정규화는 volume 별 percentile 1~99% 클리핑 후 8bit.**
   육안 검수 시트(make_review_overlays.py)와 **같은 함수**를 쓴다 — 사람이 승인한 그림과
   서비스에 올라가는 그림이 달라지면 안 되기 때문이다.
   이는 화면 표시 전용이며 **모델 입력 전처리(z-score)와 절대 공유하지 않는다.**
2. **전문가 GT 를 수정하지 않는다.** 최소 면적 필터, 구멍 메우기, 스무딩 전부 없다.
   GT 가 1px 이라도 있는 slice 는 그대로 마스크를 만든다.
3. slice 범위 = 병변이 있는 slice 전체 + 앞뒤 margin (기본 3장), volume 경계에서 잘린다.
4. **파일 이름의 인덱스는 원본 volume 인덱스**다. case_slices.slice_index 에 그대로 들어가고,
   2.5D 확장 시 인접 slice 를 원본과 같은 좌표로 찾기 위해 재번호를 매기지 않는다.
5. 대표 slice = 병변 면적이 가장 큰 slice (export_meta 의 representative_slice 와 동일).

해설(explanation) 정책 — API 계약 v0.4
-------------------------------------
여기서 만드는 것은 **case_facts 블록(source=dataset_verified) 하나뿐**이다.
전부 GT/DICOM 에서 계산된 값이라 사람이 타이핑하는 문장이 없다.

  - disease_info  : 질환 단위 문헌 콘텐츠라 manifest 가 아니라
                    app/content/diseases/<질환코드>.json 에서 온다 (여기서 만들지 않는다)
  - case_findings : 전문가가 이 케이스를 보고 쓴 소견. **null 로 둔다.**
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 육안 검수 시트와 동일한 표시 규칙을 쓴다 (import 로 강제)
from app.explanations import SOURCE_DATASET  # noqa: E402
from scripts.make_review_overlays import display_window, slice_to_8bit  # noqa: E402

DEFAULT_MARGIN = 3
MASK_RGBA = (255, 255, 255, 255)  # 투명 배경 + 불투명 흰색 (masks.py / ResultCompare.vue 판정 규칙)

BODY_PART = "brain_mri"
DISEASE = "vestibular_schwannoma"
DISEASE_NAME = "전정신경초종 (Vestibular Schwannoma)"
LATERALITY_KO = {"right": "우측", "left": "좌측"}


def slice_range(areas: np.ndarray, margin: int) -> tuple[int, int, int, int]:
    """(범위 시작, 범위 끝, 병변 시작, 병변 끝). 끝 인덱스는 모두 포함(inclusive)."""
    lesion = np.nonzero(areas)[0]
    if lesion.size == 0:
        raise RuntimeError("GT 마스크에 병변이 없습니다.")
    start, end = int(lesion.min()), int(lesion.max())
    return max(0, start - margin), min(len(areas) - 1, end + margin), start, end


def write_slice_png(volume: np.ndarray, index: int, lo: float, hi: float, path: Path) -> None:
    Image.fromarray(slice_to_8bit(volume[:, :, index], lo, hi), mode="L").save(path)


def write_mask_png(gt: np.ndarray, index: int, path: Path) -> None:
    """전문가 GT 를 그대로 PNG 로. 어떤 보정도 하지 않는다."""
    mask = gt[:, :, index].astype(bool)
    rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
    rgba[mask] = MASK_RGBA
    Image.fromarray(rgba, mode="RGBA").save(path)


def build_case_facts(meta: dict, representative: int, area_px: int,
                     lesion_start: int, lesion_end: int) -> dict:
    """이 케이스에서 직접 확인된 사실만 담는다 (source=dataset_verified)."""
    laterality_info = meta.get("laterality") or {}
    laterality = laterality_info.get("laterality")
    side = LATERALITY_KO.get(laterality)
    total = meta["shape"][2]

    # 한글 콘솔(cp949)에서도 깨지지 않도록 em dash 같은 문자는 쓰지 않는다
    if side:
        region = (
            f"{side} (DICOM 영상 방향 ImageOrientationPatient 으로 확인한 전문가 GT 마스크 위치). "
            f"대표 slice {representative} / 원본 {total}장, 병변 slice {lesion_start}~{lesion_end}."
        )
    else:
        # 좌우를 자동 판정하지 못했으면 추측하지 않는다
        region = (
            "전문가 GT 마스크 위치 (좌우 편측성 자동 판정 불가, 검토 필요). "
            f"대표 slice {representative} / 원본 {total}장, 병변 slice {lesion_start}~{lesion_end}."
        )

    return {
        "source": SOURCE_DATASET,
        "disease_name": DISEASE_NAME,
        "disease_code": DISEASE,
        "laterality": laterality,
        "laterality_basis": laterality_info.get("basis"),
        "representative_slice": representative,
        "total_slices": int(total),
        "lesion_slice_range": [lesion_start, lesion_end],
        "representative_area_px": int(area_px),
        "reference_region": region,
        "dataset": "VS-SEG (RTSTRUCT 전문가 GT)",
    }


def build_case(case_id: str, export_dir: Path, out_dir: Path, margin: int) -> dict:
    volume = np.load(export_dir / "t1_volume.npy")
    gt = np.load(export_dir / "ground_truth_mask.npy").astype(bool)
    meta = json.loads((export_dir / "export_meta.json").read_text(encoding="utf-8"))

    if volume.shape != gt.shape:
        raise RuntimeError(f"영상 {volume.shape} / mask {gt.shape} 크기가 다릅니다.")

    areas = gt.sum(axis=(0, 1))
    first, last, lesion_start, lesion_end = slice_range(areas, margin)
    representative = int(np.argmax(areas))
    if representative != meta.get("representative_slice"):
        raise RuntimeError(
            f"대표 slice 불일치: export_meta={meta.get('representative_slice')} / 재계산={representative}"
        )

    lo, hi = display_window(volume)
    out_dir.mkdir(parents=True, exist_ok=True)

    slices = []
    for index in range(first, last + 1):
        image_name = f"slice_{index:03d}.png"
        write_slice_png(volume, index, lo, hi, out_dir / image_name)

        area = int(areas[index])
        mask_name = None
        if area > 0:
            mask_name = f"mask_{index:03d}.png"
            write_mask_png(gt, index, out_dir / mask_name)

        slices.append(
            {
                "slice_index": index,          # 원본 volume 인덱스를 그대로 보존
                "image": f"{case_id}/{image_name}",
                "mask": f"{case_id}/{mask_name}" if mask_name else None,
                "lesion_area_px": area,        # GT 그대로. 1px 도 버리지 않는다
            }
        )

    representative_slice_entry = next(s for s in slices if s["slice_index"] == representative)
    height, width = volume.shape[0], volume.shape[1]

    entry = {
        "case_id": case_id,
        "body_part": BODY_PART,
        "disease": DISEASE,
        "volume_id": f"{case_id}/T1",
        "representative_slice": representative,
        "slice_index": representative,
        "total_slices": int(volume.shape[2]),
        "image": representative_slice_entry["image"],
        "reference_mask": representative_slice_entry["mask"],
        "slices": slices,
        "explanation": {
            "case_facts": build_case_facts(
                meta, representative, areas[representative], lesion_start, lesion_end
            ),
            # 전문가가 이 케이스를 보고 쓴 소견은 아직 없다
            "case_findings": None,
        },
        "source": {
            "t1_description": meta.get("t1_description"),
            "chosen_roi": meta.get("chosen_roi"),
            "roi_names": meta.get("roi_names"),
            "gt_voxels": meta.get("gt_voxels"),
            "laterality": (meta.get("laterality") or {}).get("laterality"),
            "display_window": [round(lo, 2), round(hi, 2)],
            "image_size": [width, height],
            "lesion_slice_range": [lesion_start, lesion_end],
            "exported_slice_range": [first, last],
            "margin": margin,
        },
    }
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description="VS-SEG npy -> 서비스 PNG 자산 + manifest (DB 등록 없음)")
    parser.add_argument("--export-root", type=Path, required=True, help="export_vs_seg_npy 출력 루트")
    parser.add_argument("--out", type=Path, required=True, help="PNG/manifest 출력 루트")
    parser.add_argument("--cases", nargs="*", help="생략 시 export-root 안의 모든 케이스")
    parser.add_argument("--margin", type=int, default=DEFAULT_MARGIN, help="병변 앞뒤 여유 slice 수")
    args = parser.parse_args()

    cases = args.cases or sorted(p.name for p in args.export_root.iterdir() if p.is_dir())
    entries = []
    exit_code = 0

    for case_id in cases:
        print(f"=== {case_id} ===")
        try:
            entry = build_case(case_id, args.export_root / case_id, args.out / case_id, args.margin)
        except Exception as exc:
            print(f"  [실패] {exc}")
            exit_code = 1
            continue

        source = entry["source"]
        with_mask = sum(1 for s in entry["slices"] if s["mask"])
        print(f"  ROI={source['chosen_roi']}  편측성={source['laterality']}")
        print(
            f"  slice {source['exported_slice_range'][0]}~{source['exported_slice_range'][1]} "
            f"({len(entry['slices'])}장, 병변 {source['lesion_slice_range'][0]}~"
            f"{source['lesion_slice_range'][1]} / 마스크 {with_mask}장)"
        )
        print(f"  대표 slice={entry['representative_slice']}  표시윈도우={source['display_window']}")
        print(f"  최소 병변 면적={min((s['lesion_area_px'] for s in entry['slices'] if s['lesion_area_px']), default=0)}px")
        entries.append(entry)

    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "_comment": [
                    "VS-SEG 실데이터 케이스. 영상 PNG 는 표시용(percentile 1~99% 클리핑)이고,",
                    "mask 는 RTSTRUCT 에서 나온 전문가 GT 를 보정 없이 그대로 옮긴 것이다.",
                    "explanation 은 case_facts(dataset_verified) 블록만 담는다.",
                    "질환 문헌 정보(disease_info)는 app/content/diseases/ 에서, 케이스별 소견",
                    "(case_findings)은 전문가 검토 후에 붙는다.",
                ],
                "cases": entries,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nmanifest: {manifest_path}  ({len(entries)}건)")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
