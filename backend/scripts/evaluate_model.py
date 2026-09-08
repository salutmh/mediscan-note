"""
모델 평가 — 평균 Dice 하나로 개선 여부를 판단하지 않기 위한 도구.

**왜 필요한가**
"평균 Dice 0.79" 는 이 모델을 잘못 요약한다. 실제로는 5케이스가 0.94 부근이고
1케이스가 0.0 이다. 평균만 보면 "전반적으로 조금 부정확한 모델"로 읽히지만,
사실은 **대부분 잘 맞히고 가끔 완전히 놓치는 모델**이다. 학습 서비스에서 이 둘은
전혀 다른 이야기다 — 후자는 "AI 도 놓칠 수 있다"는 교육 소재가 된다.

그래서 다음을 함께 본다:
  - 검출률 (detection rate) 과 미검출 케이스 목록
  - 검출된 케이스만의 Dice (평균/중앙값/최소)
  - 병변 크기 구간별 성능  <- 미검출이 특정 크기에 몰리는지
  - 케이스별 FN/FP voxel
  - **모델 버전 간 비교** (기준 파일과 대조)

**이 결과는 채점에 쓰이지 않는다.** 모델 평가는 모델 얘기고, 학습자 채점은 전문가 GT 로만 한다.
DB 도 건드리지 않는다.

사용법
------
    cd backend
    python -m scripts.evaluate_model
    python -m scripts.evaluate_model --save data/model_eval_v1.json
    python -m scripts.evaluate_model --compare data/model_eval_v1.json
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.analyze_case_candidates import (  # noqa: E402
    DEFAULT_EXPORT_ROOT,
    assign_size_buckets,
    collect_case,
)

# 크기 구간별 집계에 쓰는 라벨 (상대 3분위. 의학적 분류가 아니다)
SIZE_ORDER = ("small", "medium", "large")


def _stats(values: list[float]) -> dict | None:
    if not values:
        return None
    return {
        "count": len(values),
        "mean": round(statistics.fmean(values), 4),
        "median": round(statistics.median(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def evaluate(rows: list[dict]) -> dict:
    """평가 지표를 계산한다. 예측이 없는 케이스는 집계에서 빠진다(0 으로 세지 않는다)."""
    scored = [r for r in rows if r["ai_dice"] is not None]
    detected = [r for r in scored if r["ai_detected"]]
    missed = [r for r in scored if not r["ai_detected"]]

    by_size: dict = {}
    for bucket in SIZE_ORDER:
        group = [r for r in scored if r["size_bucket_relative"] == bucket]
        if not group:
            continue
        found = [r for r in group if r["ai_detected"]]
        by_size[bucket] = {
            "cases": len(group),
            "detected": len(found),
            "detection_rate": round(len(found) / len(group), 4),
            "dice_all": _stats([r["ai_dice"] for r in group]),
            "dice_detected_only": _stats([r["ai_dice"] for r in found]),
            "gt_voxels_range": [
                min(r["gt_voxels"] for r in group),
                max(r["gt_voxels"] for r in group),
            ],
        }

    versions = sorted({r["model_version"] for r in scored if r["model_version"]})

    return {
        "model_versions": versions,
        "evaluated_cases": len(scored),
        "cases_without_prediction": [r["case_id"] for r in rows if r["ai_dice"] is None],
        "detection": {
            "detected": len(detected),
            "missed": len(missed),
            # 검출률은 평균 Dice 보다 먼저 봐야 하는 값이다
            "detection_rate": round(len(detected) / len(scored), 4) if scored else None,
            "missed_cases": [
                {
                    "case_id": r["case_id"],
                    "gt_voxels": r["gt_voxels"],
                    "size_bucket_relative": r["size_bucket_relative"],
                }
                for r in missed
            ],
        },
        # 두 값을 나란히 둔다: 전체 평균은 미검출에 끌려 내려가고,
        # 검출된 것만의 평균은 "찾았을 때 얼마나 정확한가"를 말한다
        "dice_all_cases": _stats([r["ai_dice"] for r in scored]),
        "dice_detected_only": _stats([r["ai_dice"] for r in detected]),
        "representative_slice_dice": _stats(
            [r["ai_representative_slice_dice"] for r in scored if r["ai_representative_slice_dice"] is not None]
        ),
        "by_lesion_size": by_size,
        "per_case": [
            {
                "case_id": r["case_id"],
                "gt_voxels": r["gt_voxels"],
                "size_bucket_relative": r["size_bucket_relative"],
                "detected": r["ai_detected"],
                "dice": r["ai_dice"],
                "representative_slice_dice": r["ai_representative_slice_dice"],
                "false_negative_voxels": r["false_negative_voxels"],
                "false_positive_voxels": r["false_positive_voxels"],
            }
            for r in sorted(scored, key=lambda r: r["case_id"])
        ],
    }


def print_report(report: dict) -> None:
    print(f"모델 버전: {', '.join(report['model_versions']) or '(없음)'}")
    print(f"평가 케이스: {report['evaluated_cases']}건")
    if report["cases_without_prediction"]:
        print(f"예측 없음(집계 제외): {report['cases_without_prediction']}")
    print()

    detection = report["detection"]
    print(f"검출률: {detection['detection_rate']} ({detection['detected']}/{report['evaluated_cases']})")
    for case in detection["missed_cases"]:
        print(
            f"  미검출: {case['case_id']} "
            f"(GT {case['gt_voxels']:,} voxel, 상대크기 {case['size_bucket_relative']})"
        )
    print()

    all_stats = report["dice_all_cases"] or {}
    det_stats = report["dice_detected_only"] or {}
    print(f"Dice 전체:       평균 {all_stats.get('mean')} / 중앙값 {all_stats.get('median')} / 최소 {all_stats.get('min')}")
    print(f"Dice 검출건만:   평균 {det_stats.get('mean')} / 중앙값 {det_stats.get('median')} / 최소 {det_stats.get('min')}")
    print("  ^ 두 값의 차이가 크면 '전반적으로 부정확'이 아니라 '가끔 완전히 놓치는' 모델이다.")
    print()

    print("병변 크기 구간별 (상대 3분위 - 의학적 분류 아님)")
    header = f"  {'구간':<8}{'케이스':>6}{'검출률':>8}{'Dice(전체)':>12}{'Dice(검출건)':>13}{'GT voxel 범위':>20}"
    print(header)
    for bucket in SIZE_ORDER:
        row = report["by_lesion_size"].get(bucket)
        if not row:
            continue
        low, high = row["gt_voxels_range"]
        all_mean = (row["dice_all"] or {}).get("mean")
        det_mean = (row["dice_detected_only"] or {}).get("mean")
        print(
            f"  {bucket:<8}{row['cases']:>6}{row['detection_rate']:>8}"
            f"{str(all_mean):>12}{str(det_mean):>13}{f'{low:,} ~ {high:,}':>20}"
        )
    print()

    print("케이스별")
    print(f"  {'case_id':<14}{'검출':>6}{'Dice':>10}{'대표slice':>10}{'FN':>10}{'FP':>10}")
    for case in report["per_case"]:
        fn = case["false_negative_voxels"]
        fp = case["false_positive_voxels"]
        print(
            f"  {case['case_id']:<14}"
            f"{('O' if case['detected'] else 'X'):>6}"
            f"{str(case['dice']):>10}"
            f"{str(case['representative_slice_dice']):>10}"
            f"{('-' if fn is None else format(fn, ',')):>10}"
            f"{('-' if fp is None else format(fp, ',')):>10}"
        )


def compare(current: dict, baseline: dict) -> None:
    """버전 비교 - 평균만 보지 않고 케이스별로 어디가 좋아지고 나빠졌는지 본다."""
    print("\n=== 기준 대비 비교 ===")
    print(f"기준 모델: {', '.join(baseline.get('model_versions') or []) or '(없음)'}")
    print(f"현재 모델: {', '.join(current.get('model_versions') or []) or '(없음)'}")

    base_rate = (baseline.get("detection") or {}).get("detection_rate")
    cur_rate = (current.get("detection") or {}).get("detection_rate")
    if base_rate is not None and cur_rate is not None:
        print(f"검출률: {base_rate} -> {cur_rate} ({cur_rate - base_rate:+.4f})")

    base_mean = (baseline.get("dice_all_cases") or {}).get("mean")
    cur_mean = (current.get("dice_all_cases") or {}).get("mean")
    if base_mean is not None and cur_mean is not None:
        print(f"Dice 평균: {base_mean} -> {cur_mean} ({cur_mean - base_mean:+.4f})")

    base_cases = {c["case_id"]: c for c in baseline.get("per_case", [])}
    print("\n케이스별 변화")
    regressions = []
    for case in current.get("per_case", []):
        before = base_cases.get(case["case_id"])
        if before is None:
            print(f"  {case['case_id']}: 신규 (Dice {case['dice']})")
            continue
        delta = (case["dice"] or 0) - (before["dice"] or 0)
        mark = "→" if abs(delta) < 1e-6 else ("↑" if delta > 0 else "↓")
        print(f"  {case['case_id']}: {before['dice']} {mark} {case['dice']} ({delta:+.4f})")
        # 검출하던 것을 못 찾게 된 것은 평균이 올라도 회귀다
        if before.get("detected") and not case.get("detected"):
            regressions.append(case["case_id"])

    if regressions:
        print(f"\n[회귀] 이전에 검출하던 케이스를 놓쳤습니다: {regressions}")
        print("       평균 Dice 가 올라도 이건 개선이 아니다.")


def main() -> int:
    parser = argparse.ArgumentParser(description="모델 평가 (DB 변경 없음, 채점과 무관)")
    parser.add_argument("--export-root", default=str(DEFAULT_EXPORT_ROOT))
    parser.add_argument("--save", help="이번 결과를 JSON 으로 저장 (다음 버전 비교의 기준이 된다)")
    parser.add_argument("--compare", help="기준 JSON 과 비교")
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
    report = evaluate(rows)
    print_report(report)
    print("\n※ 이 결과는 모델 평가일 뿐 학습자 채점과 무관합니다 (채점 기준은 전문가 GT).")

    if args.compare:
        baseline_path = Path(args.compare)
        if not baseline_path.exists():
            print(f"\n기준 파일이 없습니다: {baseline_path}")
            return 1
        compare(report, json.loads(baseline_path.read_text(encoding="utf-8")))

    if args.save:
        out = Path(args.save)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n저장했습니다: {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
