"""
등록된 케이스 점검 (등록 직후 sanity check).

무엇을 확인하는가
----------------
  1. 대표 영상 / 기준 마스크 파일이 실제로 있고 크기가 같은가 (gradable 여부)
  2. case_slices 가 원본 slice_index 를 보존하며 붙어 있는가, 대표 slice 가 그 안에 있는가
  3. **Dice=1.0 자가 점검** — 기준 마스크를 그대로 제출하면 채점이 완전 일치를 내는가.
     채점 경로(디코딩 -> 정렬 -> Dice/IoU)가 이 케이스의 마스크에 대해 실제로 도는지 보는 것이고,
     학습자의 실력과는 아무 상관이 없다.
  4. 해설 블록 구성 (case_facts / disease_info / case_findings 중 무엇이 있는지)
  5. AI 예측 sidecar 가 **오래된(stale) 결과**는 아닌지
     - model_version 이 현재 wrapper 와 같은가
     - 예측 계산에 쓴 GT voxel 수가 지금 등록된 마스크 총합과 같은가
       (volume 을 다시 export 했거나 마스크가 바뀌면 어긋난다)

사용법
------
    cd backend
    python -m scripts.verify_cases
    python -m scripts.verify_cases --case-ids VS-SEG-202
"""
import argparse
import base64
import sys
from pathlib import Path

from PIL import Image
from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import explanations, inference, model_predictions  # noqa: E402
from app.db import SessionLocal, run_migrations  # noqa: E402
from app.grading import evaluate_submission, is_gradable  # noqa: E402
from app.models import Case, CaseSlice  # noqa: E402
from app.static_files import resolve_local_path  # noqa: E402

TOLERANCE = 1e-9


def self_dice(case: Case) -> dict:
    """기준 마스크를 그대로 제출해 본다. 채점 경로가 살아 있으면 Dice=IoU=1.0 이어야 한다."""
    mask_path = resolve_local_path(case.reference_mask_url)
    if mask_path is None:
        return {"ok": False, "reason": "기준 마스크 파일 없음"}

    payload = base64.b64encode(mask_path.read_bytes()).decode()
    result = evaluate_submission(case, {"type": "brush_mask", "mask_png_base64": payload})
    ok = (
        abs(result["dice"] - 1.0) < TOLERANCE
        and abs(result["iou"] - 1.0) < TOLERANCE
        and result["grade"] == "match"
        and result["location_score"] == 100
    )
    return {"ok": ok, **result}


def _report_prediction(case: Case, slices: list[CaseSlice], exit_code: int) -> int:
    """AI 예측 sidecar 상태 + stale 판별. 예측은 채점과 무관하므로 없어도 실패가 아니다."""
    raw = model_predictions.raw_sidecar(case.case_id)
    if raw is None:
        print("  AI 예측: 없음 (scripts/run_model_predictions.py 로 미리 계산)")
        return exit_code

    prediction = model_predictions.load(case.case_id)
    print(
        f"  AI 예측: {prediction['model_version']} "
        f"Dice(volume)={prediction['dice_vs_reference']} "
        f"대표 slice={prediction['representative_slice_dice']} "
        f"검출={prediction['detected']}  계산={prediction['computed_at']}"
    )

    module = inference.get_module(case.body_part)
    current_version = getattr(module, "MODEL_VERSION", None) if module else None
    if current_version and raw.get("model_version") != current_version:
        exit_code = 1
        print(
            f"  [실패] 예측이 오래됐습니다: sidecar={raw.get('model_version')} / "
            f"현재 모델={current_version} -> {raw.get('regenerate_with', '재계산 필요')}"
        )

    registered_voxels = sum(s.lesion_area_px for s in slices)
    recorded_voxels = raw.get("reference_voxels")
    if recorded_voxels is not None and registered_voxels and recorded_voxels != registered_voxels:
        exit_code = 1
        print(
            f"  [실패] 예측 계산 시점의 GT voxel({recorded_voxels:,})이 "
            f"등록된 마스크 총합({registered_voxels:,})과 다릅니다 -> 예측 재계산 필요"
        )

    if raw.get("detected") is False and raw.get("mask_url"):
        exit_code = 1
        print("  [실패] 미검출인데 예측 마스크 URL 이 남아 있습니다.")

    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="등록된 케이스 sanity check (DB 변경 없음)")
    parser.add_argument("--case-ids", nargs="*", help="생략 시 전체")
    args = parser.parse_args()

    # 스키마를 head 까지 올린 뒤 읽는다 (import_cases 와 동일한 보장).
    # 없으면 모델에 컬럼이 추가될 때마다 "no such column" 원시 에러로 죽는다.
    run_migrations()

    exit_code = 0
    with SessionLocal() as db:
        stmt = select(Case).order_by(Case.case_id)
        if args.case_ids:
            stmt = stmt.where(Case.case_id.in_(args.case_ids))
        cases = db.scalars(stmt).all()

        if not cases:
            print("등록된 케이스가 없습니다.")
            return 1

        for case in cases:
            print(f"=== {case.case_id} ===")
            slices = db.scalars(
                select(CaseSlice)
                .where(CaseSlice.case_id == case.case_id)
                .order_by(CaseSlice.slice_index)
            ).all()

            image_path = resolve_local_path(case.image_url)
            mask_path = resolve_local_path(case.reference_mask_url)
            size = None
            if image_path is not None:
                with Image.open(image_path) as img:
                    size = img.size

            print(f"  volume_id={case.volume_id}  대표 slice={case.representative_slice}")
            print(f"  image_url={case.image_url}")
            print(f"  reference_mask_url={case.reference_mask_url}")
            print(f"  gradable={is_gradable(case)}  크기={size}")

            if slices:
                indices = [s.slice_index for s in slices]
                with_mask = [s for s in slices if s.mask_url]
                areas = [s.lesion_area_px for s in with_mask]
                print(
                    f"  slice {len(slices)}장 (원본 index {indices[0]}~{indices[-1]}), "
                    f"마스크 {len(with_mask)}장, 병변 면적 {min(areas)}~{max(areas)}px"
                )
                if case.representative_slice not in indices:
                    print("  [실패] 대표 slice 가 case_slices 에 없습니다.")
                    exit_code = 1
            else:
                print("  slice 없음 (단일 영상 케이스)")

            if mask_path is not None and size is not None:
                with Image.open(mask_path) as m:
                    if m.size != size:
                        print(f"  [실패] 마스크 크기 불일치: {m.size} != {size}")
                        exit_code = 1

            check = self_dice(case)
            if check["ok"]:
                print(
                    f"  Dice 자가점검: dice={check['dice']} iou={check['iou']} "
                    f"grade={check['grade']} location={check['location_score']}  [통과]"
                )
            else:
                exit_code = 1
                print(f"  Dice 자가점검: [실패] {check}")

            exit_code = _report_prediction(case, slices, exit_code)

            explanation = explanations.build(case)
            levels = explanation["content_levels"]
            print(f"  해설 출처: {levels or '(없음)'}")
            facts = explanation["case_facts"] or {}
            print(f"  기준 영역: {facts.get('reference_region')}")
            if explanation["disease_info"] is None:
                print("  질환 문헌 정보: 없음 (app/content/diseases/ 미작성)")
            status = explanation["case_findings_status"]
            if explanation["case_findings"] is None:
                print(f"  케이스별 영상 소견: 없음 (검토 상태: {status})")
            else:
                findings = explanation["case_findings"]
                print(
                    f"  케이스별 영상 소견: 있음 (검토 상태: {status}, "
                    f"검토 {findings.get('reviewer')} · {findings.get('reviewed_at')})"
                )
            if not facts:
                print("  [실패] case_facts 가 없습니다.")
                exit_code = 1
            print()

    print("전체 통과" if exit_code == 0 else "실패 항목이 있습니다")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
