"""
육안 검수 **전** 기계 점검.

**사람 검수를 대신하지 않는다.** 검수자가 24장을 처음부터 똑같은 눈으로 볼 필요가 없게,
"기계가 확실히 셀 수 있는 것"을 미리 세어 **먼저 볼 케이스를 알려주는** 도구다.
`docs/CASE_REVIEW_CHECKLIST.md` 2절 중 계산 가능한 항목만 다룬다.

여기서 세는 것
--------------
  덩어리 수        마스크가 몇 조각으로 흩어져 있는가 (3D 연결 성분)
  배경 위 비율     마스크가 어두운 배경(=영상 밖·공기) 위에 얼마나 얹혀 있는가
  대표 slice 확인  가장 넓은 slice 가 정말 representative_slice 인가
  편측성 합치      FOV 기준과 머리 기준 계산이 서로 같은가
  ROI 이름         종양 ROI 인가 (Cochlea/Skull 등이 아닌가)
  얇은 병변        병변이 한 장에만 있는가

**여기서 하지 않는 것 (할 수 없는 것)**
  - 마스크가 **의학적으로 옳은 범위인가** — 영상의학 판단이다
  - 난이도 — 크기·모델 성능은 계산값일 뿐 난이도가 아니다
  - GT 수정 — 이상해 보여도 고치지 않는다. **표시할 뿐이다**

"주의" 로 표시된다고 반려가 아니고, "확인 없음"이라고 통과가 아니다.
**모든 케이스는 사람이 시트를 본다.** 이 표는 순서를 정해줄 뿐이다.

사용법
------
    cd backend
    python -m scripts.pre_review_check --export-root data/expansion_export
    python -m scripts.pre_review_check --export-root data/expansion_export --json out.json
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 종양 ROI 로 인정하는 이름 (export 단계와 같은 기준)
TUMOR_ROI_HINTS = ("tv", "an", "gtv", "tumor", "tumour", "schwannoma", "vs")
# 명백히 종양이 아닌 구조 — 이게 잡혔으면 확실한 반려 사유다
NON_TUMOR_ROI = ("cochlea", "skull", "brainstem", "modiolus", "canal")

# 배경 판정: volume 의 하위 percentile 을 어두운 값으로 본다.
# 절대값을 쓰지 않는 이유는 스캐너마다 intensity 범위가 다르기 때문이다.
BACKGROUND_PERCENTILE = 20.0
# 마스크의 이 비율 이상이 배경 위면 정렬을 의심한다
BACKGROUND_RATIO_WARN = 0.30


def _connected_components_3d(mask: np.ndarray) -> int:
    """3D 26-이웃 연결 성분 개수. scipy 없이 라벨 전파로 센다.

    (requirements 를 늘리지 않는다는 프로젝트 방침 — scipy.ndimage.label 을 쓰지 않는다.)
    """
    visited = np.zeros(mask.shape, dtype=bool)
    coords = np.argwhere(mask > 0)
    if coords.size == 0:
        return 0

    lookup = set(map(tuple, coords))
    neighbours = [
        (dz, dy, dx)
        for dz in (-1, 0, 1)
        for dy in (-1, 0, 1)
        for dx in (-1, 0, 1)
        if (dz, dy, dx) != (0, 0, 0)
    ]

    count = 0
    for start in map(tuple, coords):
        if visited[start]:
            continue
        count += 1
        stack = [start]
        visited[start] = True
        while stack:
            z, y, x = stack.pop()
            for dz, dy, dx in neighbours:
                nxt = (z + dz, y + dy, x + dx)
                if nxt in lookup and not visited[nxt]:
                    visited[nxt] = True
                    stack.append(nxt)
    return count


def check_case(case_dir: Path) -> dict:
    meta = json.loads((case_dir / "export_meta.json").read_text(encoding="utf-8"))
    volume = np.load(case_dir / "t1_volume.npy")
    mask = np.load(case_dir / "ground_truth_mask.npy")

    warnings: list[str] = []

    # --- 덩어리 수 -------------------------------------------------------
    components = _connected_components_3d(mask)
    if components == 0:
        # 빈 마스크는 채점 기준이 아예 없다는 뜻이다. 조용히 넘어가면 등록 후에야 드러난다.
        warnings.append("마스크가 비어 있음")
    elif components > 1:
        warnings.append(f"덩어리 {components}개")

    # --- 배경 위에 얹혀 있는가 (정렬 확인) --------------------------------
    background_level = float(np.percentile(volume, BACKGROUND_PERCENTILE))
    inside = volume[mask > 0]
    on_background = float((inside <= background_level).mean()) if inside.size else 0.0
    if on_background >= BACKGROUND_RATIO_WARN:
        warnings.append(f"배경 위 {on_background:.0%}")

    # --- 대표 slice 가 정말 가장 넓은가 -----------------------------------
    areas = mask.reshape(-1, mask.shape[2]).sum(axis=0) if mask.ndim == 3 else None
    widest = int(np.argmax(areas)) if areas is not None and areas.any() else None
    if widest is not None and widest != meta.get("representative_slice"):
        warnings.append(f"대표 slice 불일치(가장 넓은 곳={widest})")

    # --- 편측성 계산이 서로 합치하는가 ------------------------------------
    laterality = meta.get("laterality") or {}
    if not laterality.get("agree", True):
        warnings.append("편측성 계산 불일치")
    if not laterality.get("laterality"):
        warnings.append("편측성 미확정")

    # --- ROI 이름 ---------------------------------------------------------
    roi = str(meta.get("chosen_roi", "")).strip().lower().lstrip("*")
    if any(bad in roi for bad in NON_TUMOR_ROI):
        warnings.append(f"ROI 가 종양이 아님({meta.get('chosen_roi')})")
    elif not any(roi.startswith(hint) or hint in roi for hint in TUMOR_ROI_HINTS):
        warnings.append(f"ROI 이름 확인 필요({meta.get('chosen_roi')})")

    # --- 얇은 병변 ---------------------------------------------------------
    if meta.get("lesion_slice_count", 0) <= 1:
        warnings.append("병변 slice 1장")

    return {
        "case_id": meta["case_id"],
        "laterality": laterality.get("laterality"),
        "gt_voxels": meta.get("gt_voxels"),
        "representative_area_px": meta.get("representative_area_px"),
        "lesion_slice_count": meta.get("lesion_slice_count"),
        "chosen_roi": meta.get("chosen_roi"),
        "components": components,
        "on_background_ratio": round(on_background, 4),
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="육안 검수 전 기계 점검 (사람 검수를 대신하지 않는다)")
    parser.add_argument("--export-root", required=True, help="export_vs_seg_npy 출력 루트")
    parser.add_argument("--cases", nargs="*", help="생략 시 전부")
    parser.add_argument("--json", help="결과 JSON 저장 경로")
    args = parser.parse_args()

    root = Path(args.export_root)
    if not root.exists():
        print(f"export 루트가 없습니다: {root}")
        return 1

    dirs = sorted(d for d in root.iterdir() if (d / "export_meta.json").exists())
    if args.cases:
        wanted = set(args.cases)
        dirs = [d for d in dirs if d.name in wanted]
    if not dirs:
        print("점검할 케이스가 없습니다.")
        return 1

    print(f"대상 {len(dirs)}건 — {root}")
    print()
    header = f"{'case_id':14}{'편측':6}{'GT voxel':>10}{'대표px':>8}{'slice':>7}{'덩어리':>7}{'배경위':>8}  확인할 점"
    print(header)
    print("-" * (len(header) + 10))

    results = []
    for d in dirs:
        r = check_case(d)
        results.append(r)
        note = ", ".join(r["warnings"]) if r["warnings"] else ""
        print(
            f"{r['case_id']:14}{str(r['laterality']):6}{r['gt_voxels']:>10,}"
            f"{r['representative_area_px']:>8,}{r['lesion_slice_count']:>7}"
            f"{r['components']:>7}{r['on_background_ratio']:>8.0%}  {note}"
        )

    flagged = [r for r in results if r["warnings"]]
    print()
    print(f"확인할 점이 있는 케이스: {len(flagged)}건 / 전체 {len(results)}건")
    if flagged:
        print("  " + ", ".join(r["case_id"] for r in flagged))

    print()
    print("※ 이 표는 **볼 순서를 정해주는 것**이지 통과·반려 판정이 아닙니다.")
    print("  '확인할 점 없음'도 사람이 시트를 봐야 합니다 (docs/CASE_REVIEW_CHECKLIST.md).")
    print("  마스크가 의학적으로 옳은 범위인지는 여기서 판단하지 않습니다.")

    if args.json:
        Path(args.json).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n저장: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
