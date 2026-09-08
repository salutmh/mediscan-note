"""
케이스 후보 분석 — 콘텐츠를 늘리기 전에 "무엇이 있는지" 객관적으로 본다.

**왜 필요한가**
케이스를 6개에서 20~30개로 늘릴 때 아무거나 담으면 "전부 우측 대형 병변" 같은 편향된
세트가 된다. 그러면 학습자는 병변을 찾는 게 아니라 패턴을 외운다.
그래서 먼저 후보를 **계산 가능한 기준으로** 늘어놓고 사람이 고르게 한다.

==========================================================================
**여기서 계산하는 것은 전부 객관적 수치다. 의료적 난이도를 판정하지 않는다.**
==========================================================================
size_bucket 은 **이 분석 대상 안에서의 상대적 크기**(3분위)일 뿐,
"쉬움/어려움"이라는 교육적·의학적 판단이 아니다. `difficulty` 는 전문가 검토 대상이며
이 스크립트는 그 값을 만들지도, DB 에 쓰지도 않는다 (docs/CONTENT_GUIDELINES.md 6절).

**DB 를 바꾸지 않는다.** 읽기만 하고 표와 JSON 을 낸다. 등록은 기존 파이프라인으로만 한다.

사용법
------
    cd backend
    python -m scripts.analyze_case_candidates
    python -m scripts.analyze_case_candidates --export-root data/vs_seg_export
    python -m scripts.analyze_case_candidates --out data/case_candidates.json
"""
import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DEFAULT_EXPORT_ROOT = BACKEND_DIR / "data" / "vs_seg_export"
SERVICE_CASES_DIR = BACKEND_DIR / "app" / "static" / "cases"

SIZE_BUCKETS = ("small", "medium", "large")


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def overlap_from_dice(dice: float | None, gt_voxels: int, predicted_voxels: int) -> int | None:
    """Dice 와 두 면적에서 교집합 크기를 되돌린다.

    dice = 2I / (G + P)  ->  I = dice * (G + P) / 2

    마스크 npy(수십~수백 MB)를 다시 읽지 않고 FP/FN 을 구하기 위한 것이다.
    """
    if dice is None:
        return None
    return round(dice * (gt_voxels + predicted_voxels) / 2)


def collect_case(case_dir: Path) -> dict | None:
    """export_meta + 예측 sidecar 에서 **계산된 값만** 모은다."""
    meta = _read_json(case_dir / "export_meta.json")
    if meta is None:
        return None

    case_id = meta.get("case_id", case_dir.name)
    gt_voxels = int(meta.get("gt_voxels") or 0)
    prediction = _read_json(SERVICE_CASES_DIR / case_id / "prediction.json")

    row = {
        "case_id": case_id,
        # --- 데이터에서 계산된 사실 ---
        "laterality": (meta.get("laterality") or {}).get("laterality"),
        "gt_voxels": gt_voxels,
        "representative_slice": meta.get("representative_slice"),
        "representative_area_px": meta.get("representative_area_px"),
        "lesion_slice_count": meta.get("lesion_slice_count"),
        "lesion_slice_range": [meta.get("lesion_slice_min"), meta.get("lesion_slice_max")],
        "total_slices": (meta.get("shape") or [None, None, None])[2],
        "roi_name": meta.get("chosen_roi"),
        "roi_selected_by": meta.get("roi_selected_by"),
        # --- 모델 성능 (참고 정보. 채점과 무관하다) ---
        "model_version": None,
        "ai_detected": None,
        "ai_dice": None,
        "ai_predicted_voxels": None,
        "ai_representative_slice_dice": None,
        "false_negative_voxels": None,
        "false_positive_voxels": None,
        # --- 사람이 채워야 하는 것 ---
        "difficulty": None,  # 전문가 검토 대상. 이 스크립트는 절대 채우지 않는다.
    }

    if prediction:
        predicted = int(prediction.get("predicted_voxels") or 0)
        dice = prediction.get("dice_vs_reference")
        intersection = overlap_from_dice(dice, gt_voxels, predicted)
        row.update(
            {
                "model_version": prediction.get("model_version"),
                "ai_detected": prediction.get("detected"),
                "ai_dice": dice,
                "ai_predicted_voxels": predicted,
                "ai_representative_slice_dice": prediction.get("representative_slice_dice"),
                # GT 는 있는데 모델이 못 찾은 양 / 모델이 GT 밖에 그린 양
                "false_negative_voxels": (gt_voxels - intersection) if intersection is not None else None,
                "false_positive_voxels": (predicted - intersection) if intersection is not None else None,
            }
        )
    return row


def assign_size_buckets(rows: list[dict]) -> None:
    """**이 분석 대상 안에서의** 상대 크기를 3분위로 나눈다.

    절대 기준(예: 1000 voxel 이상은 large)을 만들지 않는 이유: 그런 값을 정할 근거가 없고,
    한번 문서에 적히면 의학적 기준처럼 굳는다. 여기서는 어디까지나 "이 세트 안에서 상대적으로"다.
    """
    sized = [r for r in rows if r["gt_voxels"] > 0]
    if not sized:
        return
    ordered = sorted(sized, key=lambda r: r["gt_voxels"])
    n = len(ordered)
    for index, row in enumerate(ordered):
        # 3분위. 케이스가 3개 미만이면 전부 medium 으로 두어 과한 의미부여를 피한다.
        if n < 3:
            row["size_bucket_relative"] = "medium"
            continue
        third = index * 3 // n
        row["size_bucket_relative"] = SIZE_BUCKETS[min(third, 2)]
    for row in rows:
        row.setdefault("size_bucket_relative", None)


def summarize(rows: list[dict]) -> dict:
    """세트 전체의 편향을 한눈에 본다 - 다양성이 부족하면 여기서 드러난다."""
    def count(key):
        result: dict = {}
        for row in rows:
            result[row.get(key)] = result.get(row.get(key), 0) + 1
        return {str(k): v for k, v in sorted(result.items(), key=lambda kv: str(kv[0]))}

    detected = [r for r in rows if r["ai_detected"] is True]
    missed = [r for r in rows if r["ai_detected"] is False]
    dices = [r["ai_dice"] for r in rows if r["ai_dice"] is not None]

    return {
        "case_count": len(rows),
        "laterality": count("laterality"),
        "size_bucket_relative": count("size_bucket_relative"),
        "difficulty_assigned": count("difficulty"),
        "ai_detected": len(detected),
        "ai_missed": len(missed),
        "ai_missed_cases": [r["case_id"] for r in missed],
        "ai_mean_dice": round(sum(dices) / len(dices), 4) if dices else None,
        "gt_voxels_min": min((r["gt_voxels"] for r in rows), default=None),
        "gt_voxels_max": max((r["gt_voxels"] for r in rows), default=None),
    }


def print_table(rows: list[dict]) -> None:
    header = f"{'case_id':<14}{'편측':<6}{'GT voxel':>10}{'상대크기':>9}{'대표px':>8}{'병변slice':>10}{'AI검출':>8}{'AI Dice':>9}{'FN':>8}{'FP':>8}"
    print(header)
    print("-" * len(header))
    for row in sorted(rows, key=lambda r: r["case_id"]):
        detected = row["ai_detected"]
        # f-string 안에서 같은 따옴표를 겹쳐 쓸 수 없어(파이썬 3.11) 미리 문자열로 만든다
        detected_mark = "O" if detected else ("X" if detected is False else "-")
        dice_text = "-" if row["ai_dice"] is None else str(row["ai_dice"])
        fn = row["false_negative_voxels"]
        fp = row["false_positive_voxels"]
        fn_text = "-" if fn is None else format(fn, ",")
        fp_text = "-" if fp is None else format(fp, ",")
        print(
            f"{row['case_id']:<14}"
            f"{(row['laterality'] or '-'):<6}"
            f"{row['gt_voxels']:>10,}"
            f"{(row['size_bucket_relative'] or '-'):>9}"
            f"{(row['representative_area_px'] or 0):>8,}"
            f"{(row['lesion_slice_count'] or 0):>10}"
            f"{detected_mark:>8}"
            f"{dice_text:>9}"
            f"{fn_text:>8}"
            f"{fp_text:>8}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="케이스 후보의 객관적 metadata 분석 (DB 변경 없음, 난이도 판정 없음)"
    )
    parser.add_argument("--export-root", default=str(DEFAULT_EXPORT_ROOT))
    parser.add_argument("--out", help="결과 JSON 저장 경로 (생략 시 표만 출력)")
    args = parser.parse_args()

    root = Path(args.export_root)
    if not root.exists():
        print(f"export 폴더가 없습니다: {root}")
        return 1

    rows = [r for r in (collect_case(d) for d in sorted(root.iterdir()) if d.is_dir()) if r]
    if not rows:
        print(f"분석할 케이스가 없습니다: {root}")
        return 1

    assign_size_buckets(rows)
    print_table(rows)

    summary = summarize(rows)
    print()
    print(f"케이스 {summary['case_count']}건 | 편측 {summary['laterality']}")
    print(f"상대 크기 {summary['size_bucket_relative']}")
    print(
        f"AI 검출 {summary['ai_detected']} / 미검출 {summary['ai_missed']}"
        f"{' ' + str(summary['ai_missed_cases']) if summary['ai_missed_cases'] else ''}"
        f" | 평균 Dice {summary['ai_mean_dice']}"
    )
    print()
    print("※ 상대 크기는 이 세트 안에서의 3분위일 뿐 의학적 분류가 아닙니다.")
    print("※ difficulty 는 전문가 검토 대상이라 이 스크립트가 채우지 않습니다.")
    print("※ DB 를 변경하지 않습니다. 등록은 scripts/import_cases.py 로만 합니다.")

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "note": (
                        "객관적 metadata 만 계산한 결과. size_bucket_relative 는 이 세트 안에서의 "
                        "상대 크기이고 의학적 분류가 아니다. difficulty 는 전문가 검토 대상이라 비어 있다."
                    ),
                    "summary": summary,
                    "cases": rows,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n저장했습니다: {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
