"""
기술 검수를 통과한 후보에 대해 **의료 판단이 필요 없는 검증**을 전부 돌린다.

전문가 검수를 기다리는 동안 손 놓고 있을 이유가 없다. 등록 직전에야 드러나는 문제를
지금 잡아두면, 전문가 승인이 나온 뒤 바로 넘어갈 수 있다.

여기서 확인하는 것 (전부 기계로 판정 가능)
-----------------------------------------
  export 무결성      volume/mask 파일이 있고 읽히는가, shape 이 서로 맞는가
  차원 일관성        메타데이터의 shape 과 실제 배열이 같은가
  대표 slice 범위    representative_slice 가 병변 범위 안에 있는가
  중복 등록          이미 DB 에 있는 case_id 인가 (덮어쓰면 제출 이력이 꼬인다)
  자산 준비 상태     PNG 자산이 생성됐는가 (아직이면 다음 단계가 남았다는 뜻)
  sidecar 상태       AI 예측이 있다면 현재 GT 와 어긋나지 않는가 (stale 판정)
  import dry-run     manifest 후보가 실제 등록 입력으로 형태가 맞는가

**여기서 하지 않는 것**
  - 케이스 등록·활성화 (하지 않는다)
  - GT 수정 (읽기만 한다)
  - 의학적 판정·난이도 (사람 몫)

사용법
------
    cd backend
    python -m scripts.preflight_candidates --review-root data/expansion_review \
        --export-root data/expansion_export
    # 자산까지 만든 뒤라면
    python -m scripts.preflight_candidates ... --assets-root data/expansion_cases

종료코드: 문제가 하나라도 있으면 1.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import model_predictions, review_candidates, review_store  # noqa: E402


def _fail(checks: list, name: str, detail: str) -> None:
    checks.append({"check": name, "ok": False, "detail": detail})


def _ok(checks: list, name: str, detail: str = "") -> None:
    checks.append({"check": name, "ok": True, "detail": detail})


def check_export_integrity(case_id: str, export_root: Path, checks: list) -> dict | None:
    """volume/mask 를 실제로 열어 shape 이 서로 맞는지 본다."""
    case_dir = export_root / case_id
    meta_path = case_dir / "export_meta.json"
    volume_path = case_dir / "t1_volume.npy"
    mask_path = case_dir / "ground_truth_mask.npy"

    for path in (meta_path, volume_path, mask_path):
        if not path.exists():
            _fail(checks, "export 파일 존재", f"없음: {path.name}")
            return None

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    try:
        # mmap 으로 연다 — 200MB 짜리를 24개 읽어들이지 않기 위해서다
        volume = np.load(volume_path, mmap_mode="r")
        mask = np.load(mask_path, mmap_mode="r")
    except Exception as exc:
        _fail(checks, "export 파일 읽기", f"{type(exc).__name__}: {exc}")
        return None
    _ok(checks, "export 파일 존재")

    if volume.shape != mask.shape:
        _fail(checks, "volume/mask 차원 일치", f"volume {volume.shape} != mask {mask.shape}")
    else:
        _ok(checks, "volume/mask 차원 일치", str(volume.shape))

    declared = tuple(meta.get("shape") or ())
    if declared and tuple(volume.shape) != declared:
        _fail(checks, "메타데이터 shape 일치", f"메타 {declared} != 실제 {volume.shape}")
    else:
        _ok(checks, "메타데이터 shape 일치")

    representative = meta.get("representative_slice")
    lo, hi = meta.get("lesion_slice_min"), meta.get("lesion_slice_max")
    if representative is None or lo is None or hi is None:
        _fail(checks, "대표 slice 범위", "메타데이터에 slice 정보가 없다")
    elif not (lo <= representative <= hi):
        _fail(checks, "대표 slice 범위", f"대표 {representative} 가 병변 범위 {lo}~{hi} 밖")
    else:
        _ok(checks, "대표 slice 범위", f"{representative} ∈ {lo}~{hi}")

    return meta


def check_not_already_registered(case_id: str, checks: list) -> None:
    """이미 DB 에 있는 case_id 를 다시 등록하면 제출 이력이 꼬인다."""
    try:
        from app.db import SessionLocal
        from app.models import Case

        with SessionLocal() as db:
            existing = db.get(Case, case_id)
    except Exception as exc:
        _fail(checks, "중복 등록 확인", f"DB 를 확인하지 못했다: {type(exc).__name__}")
        return

    if existing is None:
        _ok(checks, "중복 등록 확인", "새 케이스")
    else:
        _fail(
            checks,
            "중복 등록 확인",
            f"이미 등록돼 있다 (is_active={existing.is_active}). "
            "덮어쓰면 제출 이력이 꼬인다 — 다른 case_id 를 쓰거나 먼저 정리한다",
        )


def check_assets(case_id: str, assets_root: Path | None, checks: list) -> None:
    if assets_root is None:
        _ok(checks, "자산 준비", "아직 생성 전 (build_vs_seg_case_assets 가 남았다)")
        return
    manifest = assets_root / "manifest.json"
    if not manifest.exists():
        _fail(checks, "자산 준비", f"manifest 가 없다: {manifest}")
        return
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail(checks, "자산 manifest 읽기", str(exc))
        return

    entries = data if isinstance(data, list) else data.get("cases", [])
    entry = next((e for e in entries if e.get("case_id") == case_id), None)
    if entry is None:
        _fail(checks, "자산 준비", "manifest 에 이 케이스가 없다")
        return

    missing = []
    for key in ("image_path", "reference_mask_path", "thumbnail_path"):
        value = entry.get(key)
        if value and not (assets_root / value).exists() and not Path(value).exists():
            missing.append(key)
    if missing:
        _fail(checks, "자산 파일 존재", f"없음: {', '.join(missing)}")
    else:
        _ok(checks, "자산 파일 존재")


def check_sidecar(case_id: str, meta: dict | None, checks: list) -> None:
    """AI 예측 sidecar 가 현재 GT 와 어긋나지 않는지.

    **stale 한 예측을 그대로 두면** 화면에 옛 모델 결과가 참고 정보로 나간다.
    없는 것은 문제가 아니다 (`ai_prediction: null` 로 정직하게 나간다).
    """
    try:
        sidecar = model_predictions.load(case_id)
    except Exception as exc:
        _fail(checks, "예측 sidecar", f"읽지 못했다: {type(exc).__name__}")
        return

    if not sidecar:
        _ok(checks, "예측 sidecar", "없음 (ai_prediction: null 로 나간다)")
        return

    recorded = sidecar.get("gt_voxels")
    current = (meta or {}).get("gt_voxels")
    if recorded is not None and current is not None and recorded != current:
        _fail(
            checks,
            "예측 sidecar 최신성",
            f"sidecar 의 GT voxel {recorded} != 현재 {current} (stale)",
        )
    else:
        _ok(checks, "예측 sidecar", f"model_version={sidecar.get('model_version')}")


def check_manifest_candidate(review_root: Path, checks: list) -> None:
    """manifest 후보가 다음 단계 입력으로 형태가 맞는지 (import dry-run 성격)."""
    path = review_root / "package" / "manifest_candidate.json"
    if not path.exists():
        _ok(checks, "manifest 후보", "아직 생성 전 (review_package 를 먼저 돌린다)")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail(checks, "manifest 후보 읽기", str(exc))
        return

    if data.get("kind") != "manifest_candidate":
        _fail(checks, "manifest 후보 형식", f"kind={data.get('kind')}")
        return
    for entry in data.get("cases", []):
        if entry.get("intended_activation") == review_store.ACTIVATION_ACTIVE:
            _fail(
                checks,
                "manifest 후보 활성화 표시",
                f"{entry.get('case_id')} 가 active 로 표시돼 있다 — 자동 활성화는 금지다",
            )
            return
        if entry.get("difficulty") is not None or entry.get("case_findings") is not None:
            _fail(
                checks,
                "manifest 후보 의료 내용",
                f"{entry.get('case_id')} 에 난이도·소견이 채워져 있다 — 전문가 몫이다",
            )
            return
    _ok(checks, "manifest 후보", f"{len(data.get('cases', []))}건, 활성화 표시 없음")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="기술 통과 후보 사전 검증 (등록·활성화하지 않는다)"
    )
    parser.add_argument("--review-root", required=True)
    parser.add_argument("--export-root", required=True)
    parser.add_argument("--screening", default="data/vs_seg_screening.json")
    parser.add_argument("--assets-root", help="자산 생성을 마쳤다면 그 폴더")
    parser.add_argument(
        "--all", action="store_true", help="기술 통과 여부와 무관하게 전 후보를 검사한다"
    )
    args = parser.parse_args()

    export_root = Path(args.export_root)
    review_root = Path(args.review_root)
    assets_root = Path(args.assets_root) if args.assets_root else None

    if not export_root.exists():
        print(f"export 루트가 없습니다: {export_root}")
        return 1

    try:
        stored = review_store.load(review_root)
    except review_store.ReviewStoreError as exc:
        print(f"검수 결과를 읽을 수 없습니다: {exc}")
        return 1

    case_ids = review_candidates.list_case_ids(export_root)
    targets = []
    for case_id in case_ids:
        entry = review_store.get_entry(stored, case_id)
        if args.all or entry["technical_review_status"] == review_store.TECH_PASS:
            targets.append((case_id, entry))

    if not targets:
        print("기술 검수를 통과한 후보가 없습니다.")
        print("  운영자 화면(/admin/review)에서 검수하거나 --all 로 전체를 검사하세요.")
        return 0

    print(f"대상 {len(targets)}건 (전체 후보 {len(case_ids)}건)")
    print()

    problems = 0
    manifest_checks: list = []
    check_manifest_candidate(review_root, manifest_checks)

    for case_id, entry in targets:
        checks: list = []
        meta = check_export_integrity(case_id, export_root, checks)
        check_not_already_registered(case_id, checks)
        check_assets(case_id, assets_root, checks)
        check_sidecar(case_id, meta, checks)

        failed = [c for c in checks if not c["ok"]]
        problems += len(failed)
        mark = "지적" if failed else "통과"
        print(f"{mark}  {case_id:14} 기술={entry['technical_review_status']:12} "
              f"전문가={entry['expert_review_status']}")
        for c in checks:
            if not c["ok"]:
                print(f"        ✗ {c['check']}: {c['detail']}")
        if not failed:
            print(f"        {len(checks)}개 항목 전부 통과")

    print()
    for c in manifest_checks:
        print(f"{'통과' if c['ok'] else '지적'}  manifest 후보 — {c['check']}: {c['detail']}")
        if not c["ok"]:
            problems += 1

    print()
    print(f"지적 {problems}건")
    print()
    print("※ 이 스크립트는 케이스를 등록하거나 활성화하지 않습니다.")
    print("  전문가 검수가 끝나지 않은 케이스는 어떤 경로로도 자동 활성화되지 않습니다.")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
