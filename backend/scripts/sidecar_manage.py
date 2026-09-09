"""
AI 예측 sidecar 운영 도구 — status / plan / validate / promote.

==========================================================================
**AI 예측은 채점 기준이 아니다.**
==========================================================================
sidecar 가 오래됐거나 없어도 학습자의 채점은 영향을 받지 않는다 (채점 기준은
전문가 GT reference mask 뿐이다). 문제는 **화면에 옛 정보가 "AI 예측"으로 나가는 것**이다.

수명주기
-------
    model/version -> stale 판정 -> 재계산 계획 -> 검증 -> 승격

**GPU·모델 없이도 status / plan / validate / promote 는 전부 돌아간다.**
실제 추론(`scripts/run_model_predictions.py`)만 학습 venv 가 필요하다.

사용법
------
    cd backend

    # 1) 지금 상태 — 무엇이 오래됐는가
    python -m scripts.sidecar_manage status
    python -m scripts.sidecar_manage status --export-root data/vs_seg_export \
        --weights <가중치.pth>

    # 2) 재계산 계획 (실행하지 않는다. 무엇을 왜 다시 계산할지 적는다)
    python -m scripts.sidecar_manage plan --json data/sidecar_plan.json

    # 3) 학습 venv 에서 추론 -> **스테이징 폴더**에 결과를 만든다
    #    (기존 sidecar 를 바로 덮지 않는다)

    # 4) 승격 전 검증 — 여기를 통과하지 못하면 덮어쓰지 않는다
    python -m scripts.sidecar_manage validate --staging data/sidecar_staging

    # 5) 승격 (기본은 dry-run. 실제로 옮기려면 --apply)
    python -m scripts.sidecar_manage promote --staging data/sidecar_staging
    python -m scripts.sidecar_manage promote --staging data/sidecar_staging --apply

절대 하지 않는 것
----------------
- 검증에 실패한 결과로 기존 예측을 덮어쓰지 않는다
- 승격 전 기존 sidecar 를 백업하지 않고 바꾸지 않는다
- 예측 지표를 만들어내지 않는다 (계산은 추론 스크립트 몫이다)
"""
import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import inference, sidecar_lifecycle as life  # noqa: E402
from app.static_files import STATIC_DIR  # noqa: E402

CASES_DIR = STATIC_DIR / "cases"


def _registered_cases() -> list[tuple[str, str | None, int | None]]:
    """(case_id, body_part, 등록된 GT voxel 합계)."""
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import Case, CaseSlice

    rows = []
    with SessionLocal() as db:
        for case in db.scalars(select(Case).order_by(Case.case_id)):
            voxels = db.scalar(
                select(func.sum(CaseSlice.lesion_area_px)).where(CaseSlice.case_id == case.case_id)
            )
            rows.append((case.case_id, case.body_part, int(voxels) if voxels else None))
    return rows


def _model_version(body_part: str | None) -> str | None:
    module = inference.get_module(body_part) if body_part else None
    return getattr(module, "MODEL_VERSION", None) if module else None


def _evaluate_all(args) -> list[dict]:
    export_root = Path(args.export_root) if args.export_root else None
    weights = Path(args.weights) if args.weights else None

    evaluations = []
    for case_id, body_part, voxels in _registered_cases():
        evaluations.append(
            life.evaluate(
                case_id,
                CASES_DIR / case_id,
                current_model_version=_model_version(body_part),
                weights_path=weights,
                export_dir=(export_root / case_id) if export_root else None,
                registered_gt_voxels=voxels,
            )
        )
    return evaluations


# ------------------------------------------------------------------ status
def cmd_status(args) -> int:
    evaluations = _evaluate_all(args)
    if not evaluations:
        print("등록된 케이스가 없습니다.")
        return 0

    print(f"등록 케이스 {len(evaluations)}건")
    print()
    for e in evaluations:
        if not e["present"]:
            print(f"없음  {e['case_id']:14} sidecar 없음 (ai_prediction: null 로 나간다)")
            continue
        mark = "재계산" if e["needs_recompute"] else "정상"
        print(f"{mark:6}{e['case_id']:14} {e['model_version']}")
        for reason in e["reasons"]:
            print(f"        - {life.REASON_TEXT.get(reason, reason)}")
        for key, value in e["details"].items():
            if isinstance(value, dict) and "sidecar" in value:
                print(f"          {key}: sidecar={str(value['sidecar'])[:16]}… / 실제={str(value.get('actual') or value.get('registered'))[:16]}…")
        if e["unchecked"]:
            # 확인하지 못한 것을 "이상 없음"으로 뭉개지 않는다
            print(f"        (확인 못 함: {', '.join(e['unchecked'])})")

    plan = life.build_plan(evaluations)
    print()
    c = plan["counts"]
    print(f"재계산 필요 {c['needs_recompute']}건 / 없음 {c['missing']}건 / 정상 {c['up_to_date']}건")
    print()
    print("※ AI 예측은 채점 기준이 아닙니다. 오래돼도 학습자의 채점은 영향을 받지 않고,")
    print("  화면에 옛 참고 정보가 나가는 것이 문제입니다.")
    return 1 if c["needs_recompute"] else 0


# -------------------------------------------------------------------- plan
def cmd_plan(args) -> int:
    evaluations = _evaluate_all(args)
    plan = life.build_plan(
        evaluations, export_root=Path(args.export_root) if args.export_root else None
    )

    c = plan["counts"]
    print(f"전체 {c['total']}건 — 재계산 {c['needs_recompute']} / 없음 {c['missing']} / 정상 {c['up_to_date']}")
    print()
    for item in plan["recompute"]:
        print(f"  {item['case_id']}")
        for text in item["reason_text"]:
            print(f"    - {text}")
    if plan["missing"]:
        print()
        print(f"  sidecar 없음 (재계산은 선택): {', '.join(plan['missing'])}")
    if plan["unchecked"]:
        print()
        print("  확인하지 못한 항목이 있는 케이스:")
        for case_id, items in plan["unchecked"].items():
            print(f"    {case_id}: {', '.join(items)}")

    print()
    print("다음 단계")
    for step in plan["steps"]:
        print(f"  {step}")
    print()
    print(f"※ {plan['safety']}")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n계획 저장: {args.json}")
    return 0


# ---------------------------------------------------------------- validate
def _staged_cases(staging: Path) -> list[str]:
    if not staging.exists():
        return []
    return sorted(d.name for d in staging.iterdir() if (d / life.SIDECAR_NAME).exists())


def _validate(staging: Path) -> list[dict]:
    body_parts = {case_id: bp for case_id, bp, _ in _registered_cases()}
    results = []
    for case_id in _staged_cases(staging):
        results.append(
            life.validate_staged(
                case_id,
                staging / case_id,
                current_model_version=_model_version(body_parts.get(case_id)),
                existing_dir=CASES_DIR / case_id,
            )
        )
    return results


def cmd_validate(args) -> int:
    staging = Path(args.staging)
    results = _validate(staging)
    if not results:
        print(f"스테이징 폴더에 sidecar 가 없습니다: {staging}")
        print("  학습 venv 에서 추론을 돌려 <스테이징>/<CASE_ID>/prediction.json 을 만드세요.")
        return 1

    failed = [r for r in results if not r["ok"]]
    for r in results:
        print(f"{'통과' if r['ok'] else '실패'}  {r['case_id']}")
        for p in r["problems"]:
            print(f"        ✗ {p}")
        for w in r["warnings"]:
            print(f"        ! {w}")

    print()
    print(f"통과 {len(results) - len(failed)}건 / 실패 {len(failed)}건")
    if failed:
        print()
        print("**실패한 결과는 승격되지 않습니다.** 기존 예측을 그대로 둡니다.")
    return 1 if failed else 0


# ----------------------------------------------------------------- promote
def cmd_promote(args) -> int:
    staging = Path(args.staging)
    results = _validate(staging)
    if not results:
        print(f"스테이징 폴더에 sidecar 가 없습니다: {staging}")
        return 1

    passed = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]

    if failed:
        print(f"검증 실패 {len(failed)}건 — 이 케이스는 승격하지 않습니다:")
        for r in failed:
            print(f"  {r['case_id']}: {'; '.join(r['problems'])}")
        print()

    if not passed:
        print("승격할 수 있는 케이스가 없습니다. 기존 예측을 그대로 둡니다.")
        return 1

    backup_root = Path(args.backup_root) if args.backup_root else CASES_DIR / life.BACKUP_DIRNAME

    if not args.apply:
        print(f"[dry-run] 승격 대상 {len(passed)}건 (실제로 옮기려면 --apply)")
        for r in passed:
            target = CASES_DIR / r["case_id"]
            print(f"  {r['case_id']}  ->  {target}")
            for w in r["warnings"]:
                print(f"        ! {w}")
        print()
        print(f"백업 위치: {backup_root}")
        return 0

    print(f"승격 {len(passed)}건")
    for r in passed:
        outcome = life.promote(
            r["case_id"], staging / r["case_id"], CASES_DIR / r["case_id"], backup_root=backup_root
        )
        print(f"  {r['case_id']}: {', '.join(outcome['promoted'])}")
        if outcome["backup"]:
            print(f"        백업: {outcome['backup']}")
        for w in r["warnings"]:
            print(f"        ! {w}")

    print()
    print("승격 후 확인:")
    print("  python -m scripts.verify_cases")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AI 예측 sidecar 운영 (채점 기준이 아니다 — 참고 정보 전용)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--export-root", help="export 루트 (GT/volume 해시 대조에 쓴다)")
        p.add_argument("--weights", help="현재 가중치 파일 (.pth) — 해시 대조에 쓴다")

    p_status = sub.add_parser("status", help="지금 무엇이 오래됐는가")
    common(p_status)
    p_status.set_defaults(func=cmd_status)

    p_plan = sub.add_parser("plan", help="재계산 계획 (실행하지 않는다)")
    common(p_plan)
    p_plan.add_argument("--json", help="계획 저장 경로")
    p_plan.set_defaults(func=cmd_plan)

    p_validate = sub.add_parser("validate", help="승격 전 검증")
    p_validate.add_argument("--staging", required=True)
    p_validate.set_defaults(func=cmd_validate)

    p_promote = sub.add_parser("promote", help="검증 통과분만 승격 (기본 dry-run)")
    p_promote.add_argument("--staging", required=True)
    p_promote.add_argument("--apply", action="store_true", help="실제로 옮긴다")
    p_promote.add_argument("--backup-root", help="백업 폴더 (기본: static/cases/_sidecar_backup)")
    p_promote.set_defaults(func=cmd_promote)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
