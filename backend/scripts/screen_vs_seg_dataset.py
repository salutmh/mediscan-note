"""
VS-SEG 데이터셋 후보 스크리닝 — 어떤 케이스를 교육용으로 쓸지 **고르기 위한** 사전 조사.

**왜 필요한가**
지금 등록된 6케이스는 우측 5 / 좌측 1 이고 병변 크기도 한쪽으로 몰려 있다. 이대로 늘리면
학습자가 "병변을 찾는" 훈련이 아니라 "오른쪽을 칠하는" 훈련을 하게 된다.
그렇다고 242케이스를 전부 export 하면 케이스당 ~150MB 라 감당이 안 된다.

그래서 **볼륨을 만들지 않고** DICOM 태그와 RTSTRUCT 만 읽어 편측성·병변 크기를 먼저 재고,
그 결과로 균형 잡힌 후보를 고른 뒤 그것만 export 한다.

==========================================================================
**이 스크립트는 교육 콘텐츠를 등록하지 않는다.**
==========================================================================
읽기만 하고 표와 JSON 을 낸다. 실제 등록은 기존 4단계 파이프라인
(export -> **육안 검수** -> 자산 생성 -> import)을 그대로 거친다.
육안 검수 단계는 사람이 GT 를 눈으로 확인하는 자리이므로 건너뛰지 않는다.

의료적 난이도를 판정하지도 않는다. 편측성·voxel 수처럼 **계산되는 값만** 낸다.

실행 환경
--------
pydicom / rt_utils 가 필요하다. 학습 venv 로 실행한다:

    cd backend
    <학습리포>/.venv/Scripts/python -m scripts.screen_vs_seg_dataset \\
        --data-root "C:/Users/user/Downloads/vestibular_schwannoma_seg" \\
        --out data/vs_seg_screening.json

    # 일부만 빠르게 보려면
    ... --limit 30
"""
import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 이미 등록된 케이스는 다시 고를 필요가 없다
DEFAULT_EXPORT_ROOT = BACKEND_DIR / "data" / "vs_seg_export"


def _registered_cases() -> set[str]:
    if not DEFAULT_EXPORT_ROOT.exists():
        return set()
    return {d.name for d in DEFAULT_EXPORT_ROOT.iterdir() if d.is_dir()}


def screen_case(case_dir: Path) -> dict:
    """볼륨을 만들지 않고 필요한 값만 잰다.

    ROI 선택 규칙은 export 스크립트와 **같은 함수**를 쓴다 — 여기서 고른 케이스가
    export 단계에서 다른 ROI 로 잡히면 스크리닝이 의미가 없다.
    """
    import numpy as np

    from scripts.export_vs_seg_npy import (
        find_t1_series,
        infer_laterality,
        load_gt_mask,
        read_geometry,
        stack_volume,
    )

    result: dict = {"case_id": case_dir.name}

    t1_info, rtstruct_files = find_t1_series(case_dir)
    t1_files = t1_info["files"]
    t1_folder = t1_files[0].parent

    # ROI 선택은 export 와 **같은 함수**를 쓴다 — 여기서 고른 케이스가 export 에서
    # 다른 ROI 로 잡히면 스크리닝이 의미가 없다.
    mask, chosen_roi, roi_names, matched, _ = load_gt_mask(t1_folder, rtstruct_files)
    voxels = int(np.count_nonzero(mask))
    if voxels == 0:
        raise RuntimeError("GT 마스크가 비어 있습니다.")

    # 병변이 있는 slice 범위와 대표 slice (면적 최대)
    per_slice = mask.reshape(-1, mask.shape[2]).sum(axis=0)
    lesion_slices = np.nonzero(per_slice)[0]
    representative = int(np.argmax(per_slice))

    # 편측성은 export 와 동일하게 DICOM 방향 태그로 계산한다 (추측하지 않는다).
    # volume 이 필요해 여기서 한 번 읽지만 **파일로 쓰지는 않는다** — 스크리닝은 읽기 전용이다.
    geometry = read_geometry(t1_files)
    volume = stack_volume(t1_files)
    lat = infer_laterality(volume, mask, geometry)

    result.update(
        {
            "gt_voxels": voxels,
            "laterality": lat.get("laterality"),
            "laterality_basis": lat.get("basis"),
            "representative_slice": representative,
            "representative_area_px": int(per_slice[representative]),
            "lesion_slice_count": int(len(lesion_slices)),
            "lesion_slice_range": [int(lesion_slices[0]), int(lesion_slices[-1])],
            "total_slices": int(mask.shape[2]),
            "roi_name": chosen_roi,
            "roi_candidates": matched,
            "t1_description": t1_info.get("description"),
        }
    )
    return result


SIZE_STRATA = ("small", "medium", "large")


def _stratify(rows: list[dict]) -> dict:
    """GT voxel 3분위로 크기 계층을 나눈다 (이 데이터셋 안에서의 상대값)."""
    ordered = sorted(rows, key=lambda r: r["gt_voxels"])
    buckets: dict = {name: [] for name in SIZE_STRATA}
    n = len(ordered)
    for index, row in enumerate(ordered):
        buckets[SIZE_STRATA[min(index * 3 // max(n, 1), 2)]].append(row)
    return buckets


def recommend(rows: list[dict], registered: set[str], want: int) -> list[dict]:
    """편향을 줄이는 방향으로 후보를 고른다.

    **의료적 난이도가 아니라 분포**를 본다. 두 축을 함께 맞춘다:
      - 좌/우 균형 — 한쪽에 몰리면 위치를 외우는 훈련이 된다
      - **크기 계층 균형** — 작은 것만 고르면 첫 사용자가 좌절하고, 큰 것만 고르면 너무 쉽다

    처음에는 "작은 것부터"만 골랐더니 추천 24건이 전부 최소 크기(330~1,777)로 나왔다.
    데이터셋 중앙값이 6,012 인데 그 아래만 담은 셈이라 **반대 방향 편향**이 생겼다.
    그래서 크기 3분위에서 고르게 뽑는다.

    최종 선택은 사람이 한다 — 이건 제안이다.
    """
    fresh = [r for r in rows if r["case_id"] not in registered and r.get("gt_voxels")]
    if not fresh:
        return []

    buckets = _stratify(fresh)
    per_stratum = max(1, want // len(SIZE_STRATA))

    picked: list[dict] = []
    for name in SIZE_STRATA:
        group = buckets[name]
        left = [r for r in group if r["laterality"] == "left"]
        right = [r for r in group if r["laterality"] == "right"]
        # 각 계층 안에서 좌/우를 번갈아 담는다
        for index in range(max(len(left), len(right))):
            if len([p for p in picked if p.get("_stratum") == name]) >= per_stratum:
                break
            for pool in (left, right):
                if index < len(pool) and len(
                    [p for p in picked if p.get("_stratum") == name]
                ) < per_stratum:
                    row = dict(pool[index])
                    row["_stratum"] = name
                    picked.append(row)
    return picked[:want]


def summarize(rows: list[dict]) -> dict:
    ok = [r for r in rows if r.get("gt_voxels")]
    laterality: dict = {}
    for row in ok:
        key = str(row.get("laterality"))
        laterality[key] = laterality.get(key, 0) + 1
    voxels = sorted(r["gt_voxels"] for r in ok)
    return {
        "screened": len(rows),
        "usable": len(ok),
        "failed": [r["case_id"] for r in rows if not r.get("gt_voxels")],
        "laterality": laterality,
        "gt_voxels_min": voxels[0] if voxels else None,
        "gt_voxels_median": voxels[len(voxels) // 2] if voxels else None,
        "gt_voxels_max": voxels[-1] if voxels else None,
    }


def _print_result(summary: dict, picks: list[dict]) -> None:
    print()
    print(f"판독 가능 {summary['usable']} / {summary['screened']}")
    print(f"편측 분포: {summary['laterality']}")
    if summary["gt_voxels_min"]:
        print(
            f"GT voxel: 최소 {summary['gt_voxels_min']:,} / 중앙 {summary['gt_voxels_median']:,} "
            f"/ 최대 {summary['gt_voxels_max']:,}"
        )
    if summary["failed"]:
        print(f"읽지 못한 케이스 {len(summary['failed'])}건: {summary['failed'][:6]}")

    print()
    print(f"추천 후보 {len(picks)}건 (좌/우 + 크기 계층 균형)")
    print(f"  {'case_id':<14}{'편측':<6}{'크기':<8}{'GT voxel':>10}{'대표px':>9}{'병변slice':>10}")
    for row in picks:
        print(
            f"  {row['case_id']:<14}{(row['laterality'] or '-'):<6}"
            f"{row.get('_stratum', '-'):<8}"
            f"{row['gt_voxels']:>10,}{row['representative_area_px']:>9,}"
            f"{row['lesion_slice_count']:>10}"
        )
    picked_lat = {k: sum(1 for p in picks if p["laterality"] == k) for k in ("left", "right")}
    picked_size = {k: sum(1 for p in picks if p.get("_stratum") == k) for k in SIZE_STRATA}
    print(f"  -> 편측 {picked_lat} / 크기 {picked_size}")

    print()
    print("※ 이 스크립트는 케이스를 등록하지 않습니다.")
    print("  등록은 export -> 육안 검수 -> 자산 생성 -> import 4단계를 그대로 거칩니다.")
    print("  육안 검수는 사람이 GT 를 눈으로 확인하는 자리라 건너뛰지 않습니다.")
    print("※ 의료적 난이도는 판정하지 않습니다 (편측성·voxel 수 등 계산값만).")


def _save(out: Path, summary: dict, picks: list[dict], rows: list[dict]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "note": (
                    "후보 스크리닝 결과. 계산값만 담았고 난이도는 없다. "
                    "등록은 기존 4단계 파이프라인(육안 검수 포함)을 거친다."
                ),
                "summary": summary,
                "recommended": [r["case_id"] for r in picks],
                "recommended_detail": picks,
                "cases": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print()
    print(f"저장했습니다: {out}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="VS-SEG 후보 스크리닝 (읽기 전용, 등록하지 않음, 난이도 판정 없음)"
    )
    parser.add_argument("--data-root", type=Path, help="원본 DICOM 루트 (--from-json 이면 불필요)")
    parser.add_argument("--out", help="결과 JSON 저장 경로")
    parser.add_argument("--limit", type=int, help="앞에서 N개만 (빠른 확인용)")
    parser.add_argument("--want", type=int, default=24, help="추천 후보 개수")
    parser.add_argument(
        "--from-json",
        help="이미 만든 스크리닝 JSON 으로 추천만 다시 계산한다 (다시 스캔하지 않는다)",
    )
    args = parser.parse_args()

    if args.from_json:
        data = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        rows = data["cases"]
        summary = summarize(rows)
        picks = recommend(rows, _registered_cases(), args.want)
        _print_result(summary, picks)
        if args.out:
            _save(Path(args.out), summary, picks, rows)
        return 0

    if not args.data_root:
        parser.error("--data-root 또는 --from-json 이 필요합니다")
    root = Path(args.data_root)
    if not root.exists():
        print(f"데이터 루트가 없습니다: {root}")
        return 1

    case_dirs = sorted(d for d in root.iterdir() if d.is_dir())
    if args.limit:
        case_dirs = case_dirs[: args.limit]

    registered = _registered_cases()
    print(f"대상 {len(case_dirs)}케이스 / 이미 등록됨 {len(registered)}건")
    print()

    rows: list[dict] = []
    for index, case_dir in enumerate(case_dirs, 1):
        try:
            row = screen_case(case_dir)
        except Exception as exc:  # 한 케이스가 실패해도 나머지는 계속 본다
            row = {"case_id": case_dir.name, "error": str(exc)[:120]}
        rows.append(row)
        if index % 10 == 0 or index == len(case_dirs):
            print(f"  {index}/{len(case_dirs)} ...")

    summary = summarize(rows)
    picks = recommend(rows, registered, args.want)
    _print_result(summary, picks)

    if args.out:
        _save(Path(args.out), summary, picks, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
