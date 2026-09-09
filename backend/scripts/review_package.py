"""
검수 결과 패키지 생성 — 사람이 기술 검수를 끝낸 뒤 다음 단계로 넘기는 도구.

만드는 것
--------
  review_summary.json   전체 후보 + 상태별 목록 (기계용)
  review_summary.csv    같은 내용 (표로 열어보기용)
  manifest_candidate.json  **TECH_PASS 된 케이스만** 담은 다음 단계 입력 후보

==========================================================================
**여기서 케이스를 등록하거나 활성화하지 않는다.**
==========================================================================
`manifest_candidate.json` 은 이름 그대로 **후보**다. 실제 등록(`import_cases.py`)의
입력으로 쓸 수 있는 형태지만, 이 스크립트가 직접 등록하지는 않는다.

신규 케이스는 다음 단계를 그대로 지킨다:

    candidate -> technical reviewed -> expert reviewed -> inactive ready -> active

**전문가 검수(`expert_review_status`)가 끝나지 않은 케이스는 어떤 경로로도
자동 활성화되지 않는다.** manifest 후보에도 그 사실을 필드로 박아둔다
(`expert_review_status`, `activation_blocked_reason`).

TECH_PASS 의 뜻
--------------
"export 파이프라인이 제대로 돌았다"뿐이다. 의학적 판단도, 서비스 활성화 승인도 아니다.
자세한 것은 `app/review_store.py` 와 `docs/CASE_REVIEW_CHECKLIST.md` 참고.

사용법
------
    cd backend
    python -m scripts.review_package --review-root data/expansion_review \
        --export-root data/expansion_export
    python -m scripts.review_package --review-root data/expansion_review \
        --export-root data/expansion_export --out data/expansion_review/package
"""
import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import review_candidates, review_store  # noqa: E402

CSV_COLUMNS = [
    "case_id",
    "technical_review_status",
    "expert_review_status",
    "activation_status",
    "laterality",
    "gt_voxels",
    "representative_slice",
    "representative_area_px",
    "lesion_slice_count",
    "size_bucket",
    "roi_name",
    "reviewer",
    "reviewed_at",
    "note",
]


def collect(export_root: Path, review_root: Path, screening: Path) -> list[dict]:
    stored = review_store.load(review_root)
    rows = []
    for case_id in review_candidates.list_case_ids(export_root):
        info = review_candidates.build(case_id, export_root, review_root, screening)
        if info is None:
            continue
        info["review"] = review_store.get_entry(stored, case_id)
        rows.append(info)
    return rows


def _flat(row: dict) -> dict:
    review = row["review"]
    return {
        "case_id": row["case_id"],
        "technical_review_status": review["technical_review_status"],
        "expert_review_status": review["expert_review_status"],
        "activation_status": review["activation_status"],
        "laterality": row.get("laterality"),
        "gt_voxels": row.get("gt_voxels"),
        "representative_slice": row.get("representative_slice"),
        "representative_area_px": row.get("representative_area_px"),
        "lesion_slice_count": row.get("lesion_slice_count"),
        "size_bucket": row.get("size_bucket"),
        "roi_name": (row.get("provenance") or {}).get("roi_name"),
        "reviewer": review.get("reviewer"),
        "reviewed_at": review.get("reviewed_at"),
        "note": review.get("note", ""),
    }


def build_summary(rows: list[dict]) -> dict:
    entries = [r["review"] for r in rows]
    by_status: dict[str, list[str]] = {s: [] for s in review_store.TECHNICAL_STATUSES}
    for r in rows:
        by_status[r["review"]["technical_review_status"]].append(r["case_id"])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": (
            "technical_review_status 는 export 파이프라인 확인 결과입니다. "
            "의학적 판단도, 서비스 활성화 승인도 아닙니다."
        ),
        "counts": review_store.counts(entries),
        "by_technical_status": by_status,
        "expert_review_pending": [
            r["case_id"] for r in rows if r["review"]["expert_review_status"] == review_store.EXPERT_PENDING
        ],
        "pipeline": ["candidate", "technical reviewed", "expert reviewed", "inactive ready", "active"],
        "cases": [_flat(r) for r in rows],
    }


def build_manifest_candidate(rows: list[dict], export_root: Path) -> dict:
    """TECH_PASS 된 케이스만 담은 **다음 단계 입력 후보**.

    실제 등록 manifest 가 아니다 — 자산(PNG)이 아직 없고, 무엇보다
    **전문가 검수가 끝나지 않았다.** 그 사실을 필드로 남긴다.
    """
    passed = [r for r in rows if r["review"]["technical_review_status"] == review_store.TECH_PASS]
    blocked = [
        r["case_id"]
        for r in passed
        if r["review"]["expert_review_status"] != review_store.EXPERT_APPROVED
    ]

    return {
        "kind": "manifest_candidate",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "warning": (
            "이것은 **후보 목록**이며 등록 manifest 가 아닙니다. "
            "자산 생성(build_vs_seg_case_assets)을 거쳐야 하고, "
            "전문가 검수가 끝나지 않은 케이스는 활성화하지 않습니다."
        ),
        "export_root": str(export_root),
        "next_steps": [
            "python -m scripts.build_vs_seg_case_assets --export-root <위 경로> --out <자산폴더>",
            "python -m scripts.import_cases <자산폴더>/manifest.json   # is_active=false 로 들어간다",
            "전문가 검수 완료 후에만 활성화 (운영자 화면 또는 PATCH /api/admin/cases/{id})",
        ],
        "activation_blocked_reason": (
            f"전문가 검수 미완료 {len(blocked)}건" if blocked else None
        ),
        "cases": [
            {
                "case_id": r["case_id"],
                "laterality": r.get("laterality"),
                "gt_voxels": r.get("gt_voxels"),
                "representative_slice": r.get("representative_slice"),
                "size_bucket": r.get("size_bucket"),
                "roi_name": (r.get("provenance") or {}).get("roi_name"),
                "technical_review_status": r["review"]["technical_review_status"],
                "expert_review_status": r["review"]["expert_review_status"],
                # 등록되더라도 처음에는 비활성이다
                "intended_activation": review_store.ACTIVATION_INACTIVE_READY,
                "difficulty": None,  # 자동 판단하지 않는다 (전문가 검토 대상)
                "case_findings": None,  # 전문가 검수 전에는 만들지 않는다
            }
            for r in passed
        ],
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(_flat(row))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="검수 결과 패키지 생성 (등록·활성화는 하지 않는다)"
    )
    parser.add_argument("--review-root", required=True)
    parser.add_argument("--export-root", required=True)
    parser.add_argument("--screening", default="data/vs_seg_screening.json")
    parser.add_argument("--out", help="출력 폴더 (기본: <review-root>/package)")
    args = parser.parse_args()

    export_root = Path(args.export_root)
    review_root = Path(args.review_root)
    if not export_root.exists():
        print(f"export 루트가 없습니다: {export_root}")
        return 1

    try:
        rows = collect(export_root, review_root, Path(args.screening))
    except review_store.ReviewStoreError as exc:
        print(f"검수 결과를 읽을 수 없습니다: {exc}")
        return 1

    if not rows:
        print("후보가 없습니다.")
        return 1

    out_dir = Path(args.out) if args.out else review_root / "package"
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = build_summary(rows)
    manifest = build_manifest_candidate(rows, export_root)

    (out_dir / "review_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_csv(out_dir / "review_summary.csv", rows)
    (out_dir / "manifest_candidate.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    counts = summary["counts"]
    print(f"후보 {counts['total']}건")
    for status in review_store.TECHNICAL_STATUSES:
        label = review_store.TECHNICAL_MEANING[status]
        print(f"  {status:12} {counts['technical'][status]:>3}건   ({label})")
    print()
    print(f"전문가 검수 대기: {counts['awaiting_expert_review']}건 (기술 통과 중)")
    print()
    print(f"저장: {out_dir}")
    for name in ("review_summary.json", "review_summary.csv", "manifest_candidate.json"):
        print(f"  - {name}")

    print()
    print("※ manifest_candidate.json 은 **후보 목록**이며 등록 manifest 가 아닙니다.")
    print("  자산 생성을 거쳐야 하고, 전문가 검수가 끝나지 않은 케이스는 활성화하지 않습니다.")
    if manifest["activation_blocked_reason"]:
        print(f"  현재 활성화 차단 사유: {manifest['activation_blocked_reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
