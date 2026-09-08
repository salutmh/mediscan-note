"""
전문가 해설 검토용 자료 생성.

지도교수·멘토가 케이스별로 "무엇이 등록돼 있는지" 보고 **소견을 직접 써 넣을 수 있는** 문서를 만든다.

**이 스크립트는 의학 내용을 한 글자도 만들어내지 않는다.**
채워 넣는 값은 전부 이미 검증된 사실뿐이다:
  - 병명 / 편측성        : DB 에 등록된 값 + export_meta 의 DICOM 방향 계산 결과
  - 대표 slice / 병변 범위 / GT 면적 : 전문가 GT(RTSTRUCT) 에서 센 값
  - 영상                 : **이미 만들어 둔 육안 검수 오버레이를 재사용**한다 (새로 만들지 않는다)
소견·의학용어·참고자료·검토자·검토일·승인 여부는 **빈칸**으로 둔다.

산출물 (기본 data/vs_seg_review_packet/)
    expert_review.md        사람이 읽고 채우는 문서 (요약표 + 케이스별 이미지 + 입력란)
    expert_review_form.csv  같은 항목의 표 형식 (엑셀/스프레드시트로 채우기 좋다)
    images/                 위 문서가 참조하는 PNG (검수 시트에서 복사)

사용법
------
    cd backend
    python -m scripts.build_review_packet

검토가 끝난 뒤에는 manifest 의 explanation 에 `case_findings` 블록(findings / reviewer /
reviewed_at)을 채우고 `python -m scripts.import_cases <manifest> --replace` 로 다시 등록한다.
import_cases 는 reviewer 와 reviewed_at 이 없으면 소견을 등록하지 않는다 —
**검토 출처 메타데이터를 필수화**하는 것이지, 필드가 있다고 검토를 보증하는 것은 아니다.
"""
import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db import SessionLocal  # noqa: E402
from app.models import Case, CaseSlice  # noqa: E402

LATERALITY_KO = {"right": "우측", "left": "좌측"}

CSV_COLUMNS = [
    "case_id",
    "병명",
    "편측성",
    "대표 slice",
    "병변 slice 범위",
    "대표 slice GT 면적(px)",
    "대표 slice 영상",
    "GT 오버레이",
    "주요 영상 소견(전문가 입력)",
    "의학용어(전문가 입력, 쉼표 구분)",
    "참고자료(전문가 입력)",
    "검토자",
    "검토일(YYYY-MM-DD)",
    "승인 여부(승인/보류/반려)",
]


def collect(case: Case, slices: list[CaseSlice], export_meta: dict | None) -> dict:
    """등록된 값과 export 기록을 맞춰 본다. 어긋나면 문서를 만들지 않고 알린다."""
    lesion = [s for s in slices if s.lesion_area_px > 0]
    if not lesion:
        raise RuntimeError("병변이 있는 slice 가 없습니다.")

    representative = case.representative_slice
    rep_slice = next((s for s in slices if s.slice_index == representative), None)
    if rep_slice is None:
        raise RuntimeError(f"대표 slice {representative} 가 case_slices 에 없습니다.")

    meta = export_meta or {}
    laterality_info = meta.get("laterality") or {}
    laterality = laterality_info.get("laterality")

    if meta:
        if meta.get("representative_slice") != representative:
            raise RuntimeError(
                f"대표 slice 불일치: DB={representative} / export={meta.get('representative_slice')}"
            )
        if meta.get("representative_area_px") != rep_slice.lesion_area_px:
            raise RuntimeError(
                f"대표 slice 면적 불일치: DB={rep_slice.lesion_area_px} / "
                f"export={meta.get('representative_area_px')}"
            )

    facts = (case.explanation or {}).get("case_facts") or {}
    findings = (case.explanation or {}).get("case_findings")
    return {
        "case_id": case.case_id,
        "disease_name": facts.get("disease_name") or case.disease,
        "laterality": laterality,
        "laterality_ko": LATERALITY_KO.get(laterality, "자동 판정 불가 (확인 필요)"),
        "laterality_basis": laterality_info.get("basis"),
        "representative": representative,
        "representative_area_px": rep_slice.lesion_area_px,
        "lesion_start": lesion[0].slice_index,
        "lesion_end": lesion[-1].slice_index,
        "lesion_count": len(lesion),
        "smallest_lesion_px": min(s.lesion_area_px for s in lesion),
        "registered_slices": len(slices),
        "total_slices": (case.image_meta or {}).get("total_slices"),
        "gt_voxels": meta.get("gt_voxels"),
        "chosen_roi": meta.get("chosen_roi"),
        "has_case_findings": findings is not None,
        "review_state": "검토 완료" if findings else "미검토",
        "image_url": case.image_url,
        "mask_url": case.reference_mask_url,
    }


def copy_images(info: dict, cases_root: Path, review_root: Path, images_dir: Path) -> dict:
    """**기존 육안 검수 자료를 재사용**해 문서 폴더로 복사한다 (새로 렌더링하지 않는다)."""
    case_id = info["case_id"]
    index = info["representative"]
    images_dir.mkdir(parents=True, exist_ok=True)

    sources = {
        # 대표 slice 원본(표시용) — 서비스에 등록된 것과 같은 파일
        "plain": cases_root / case_id / f"slice_{index:03d}.png",
        # 대표 slice GT 오버레이 — make_review_overlays.py 산출물
        "overlay": review_root / case_id / f"{case_id}_slice{index:03d}_repr.png",
        # 시작/대표/끝 3장 + 확대 시트
        "sheet": review_root / case_id / f"{case_id}_review.png",
    }

    result = {}
    for key, source in sources.items():
        if not source.exists():
            result[key] = None
            continue
        dest = images_dir / f"{case_id}_{key}.png"
        shutil.copy2(source, dest)
        result[key] = f"images/{dest.name}"
    return result


def render_markdown(rows: list[dict]) -> str:
    lines = [
        "# 전정신경초종 케이스 해설 — 전문가 검토 요청",
        "",
        "아래 6개 케이스는 서비스에 이미 등록돼 있고, **병명과 기준 영역(편측성·위치)까지만 채워져 있습니다.**",
        "주요 영상 소견·의학용어·참고자료는 저희가 임의로 작성하지 않고 비워 두었습니다.",
        "",
        "## 검토해 주실 내용",
        "",
        "1. **기준 마스크(전문가 GT)가 병변에 맞게 표시되어 있는지** — 아래 오버레이 이미지로 확인",
        "2. **편측성(좌/우)이 맞는지** — DICOM 방향 태그로 계산한 값입니다",
        "3. **주요 영상 소견 / 의학용어 / 참고자료** 작성",
        "4. 케이스별 **승인 여부**와 **검토자·검토일** 기입",
        "",
        "> 승인된 케이스만 `case_findings`(검토자·검토일 포함)로 등록되어 학습자에게 노출됩니다.",
        "> 그 전까지 화면 4 는 데이터셋 확인 정보와 문헌 기반 학습정보만 보여줍니다.",
        "",
        "> **채점 기준은 이 해설이 아니라 기준 마스크입니다.** 마스크 자체가 잘못됐다고 판단되시면",
        "> 승인 여부를 `반려`로 표시해 주세요 — 해당 케이스는 서비스에서 내립니다.",
        "",
        "표 형식으로 채우시려면 같은 폴더의 `expert_review_form.csv` 를 쓰셔도 됩니다.",
        "",
        "---",
        "",
        "## 요약",
        "",
        "| case_id | 병명 | 편측성 | 대표 slice | 병변 slice 범위 | 대표 slice GT 면적 | 케이스별 소견 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['case_id']} | {r['disease_name']} | {r['laterality_ko']} | "
            f"{r['representative']} | {r['lesion_start']}~{r['lesion_end']} ({r['lesion_count']}장) | "
            f"{r['representative_area_px']:,} px | {r['review_state']} |"
        )

    lines += ["", "---", ""]

    for r in rows:
        images = r["images"]
        lines += [
            f"## {r['case_id']}",
            "",
            "| 항목 | 값 |",
            "|---|---|",
            f"| 병명 | {r['disease_name']} |",
            f"| 편측성 | **{r['laterality_ko']}** · 근거: {r['laterality_basis']} |",
            f"| 대표 slice | **{r['representative']}** (원본 volume {r['total_slices']}장 중, 0부터) |",
            f"| 병변 slice 범위 | {r['lesion_start']} ~ {r['lesion_end']} ({r['lesion_count']}장) |",
            f"| 대표 slice GT 면적 | **{r['representative_area_px']:,} px** |",
            f"| 가장 작은 병변 slice | {r['smallest_lesion_px']:,} px |",
            f"| GT 전체 voxel | {r['gt_voxels']:,} |" if r["gt_voxels"] else "| GT 전체 voxel | (기록 없음) |",
            f"| RTSTRUCT ROI 이름 | {r['chosen_roi']} |",
            f"| 등록된 slice 수 | {r['registered_slices']}장 (병변 slice + 앞뒤 여유 3장) |",
            f"| 케이스별 영상 소견 | {r['review_state']} |",
            "",
        ]

        if images.get("plain") and images.get("overlay"):
            lines += [
                "| 대표 slice 영상 | GT 오버레이 |",
                "|:--:|:--:|",
                f"| ![{r['case_id']} 대표 slice]({images['plain']}) "
                f"| ![{r['case_id']} GT 오버레이]({images['overlay']}) |",
                "",
            ]
        if images.get("sheet"):
            lines += [
                "병변 시작 / 대표 / 끝 slice 검수 시트 (아랫줄은 병변 주변 확대):",
                "",
                f"![{r['case_id']} 검수 시트]({images['sheet']})",
                "",
            ]

        lines += [
            "### 전문가 입력란",
            "",
            "| 항목 | 작성 |",
            "|---|---|",
            "| 주요 영상 소견 | |",
            "| 의학용어 (쉼표로 구분) | |",
            "| 참고자료 (URL 또는 출처) | |",
            "| 검토자 | |",
            "| 검토일 (YYYY-MM-DD) | |",
            "| 승인 여부 (승인 / 보류 / 반려) | |",
            "",
            "---",
            "",
        ]

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="전문가 해설 검토용 자료 생성 (의학 내용 자동 작성 없음)")
    parser.add_argument("--export-root", type=Path, default=Path("data/vs_seg_export"))
    parser.add_argument("--review-root", type=Path, default=Path("data/vs_seg_review"))
    parser.add_argument("--cases-root", type=Path, default=Path("data/vs_seg_cases"))
    parser.add_argument("--out", type=Path, default=Path("data/vs_seg_review_packet"))
    parser.add_argument("--case-ids", nargs="*", help="생략 시 등록된 전체 케이스")
    args = parser.parse_args()

    rows = []
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
            slices = list(
                db.scalars(
                    select(CaseSlice)
                    .where(CaseSlice.case_id == case.case_id)
                    .order_by(CaseSlice.slice_index)
                ).all()
            )
            meta_path = args.export_root / case.case_id / "export_meta.json"
            export_meta = (
                json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None
            )
            try:
                info = collect(case, slices, export_meta)
            except RuntimeError as exc:
                print(f"  [건너뜀] {case.case_id}: {exc}")
                exit_code = 1
                continue

            info["images"] = copy_images(info, args.cases_root, args.review_root, args.out / "images")
            missing = [k for k, v in info["images"].items() if v is None]
            if missing:
                print(f"  [경고] {case.case_id}: 검수 이미지 없음 {missing}")
            rows.append(info)
            print(
                f"  [정리] {case.case_id}  {info['laterality_ko']}  대표 {info['representative']} "
                f"({info['representative_area_px']:,}px)  소견={info['review_state']}"
            )

    args.out.mkdir(parents=True, exist_ok=True)
    md_path = args.out / "expert_review.md"
    md_path.write_text(render_markdown(rows), encoding="utf-8")

    csv_path = args.out / "expert_review_form.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow(
                {
                    "case_id": r["case_id"],
                    "병명": r["disease_name"],
                    "편측성": r["laterality_ko"],
                    "대표 slice": r["representative"],
                    "병변 slice 범위": f"{r['lesion_start']}~{r['lesion_end']}",
                    "대표 slice GT 면적(px)": r["representative_area_px"],
                    "대표 slice 영상": r["images"].get("plain") or "",
                    "GT 오버레이": r["images"].get("overlay") or "",
                    # 아래는 전문가가 채운다 — 비워서 내보낸다
                    "주요 영상 소견(전문가 입력)": "",
                    "의학용어(전문가 입력, 쉼표 구분)": "",
                    "참고자료(전문가 입력)": "",
                    "검토자": "",
                    "검토일(YYYY-MM-DD)": "",
                    "승인 여부(승인/보류/반려)": "",
                }
            )

    print()
    print(f"문서: {md_path}")
    print(f"양식: {csv_path}")
    print(f"이미지: {args.out / 'images'}  ({len(rows)}케이스)")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
