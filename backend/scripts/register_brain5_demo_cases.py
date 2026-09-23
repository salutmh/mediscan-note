"""
39. 5질환 통합모델 데모 케이스 → 메디스캔노트 학습 케이스 등록

목적
----
- service_inference_5disease의 실제 15개 데모 케이스를 읽는다.
- 같은 원본이 나온 통합 YOLO 데이터셋의 GT polygon 라벨을 reference mask PNG로 복원한다.
- 15개 전부 메인 학습 DB에 등록한다.
  - 양성 10개: GT polygon 을 그린 reference mask 로 기존 ROI 채점.
  - 음성 5개: GT 라벨이 비어 있다 — 같은 크기의 **완전히 빈** reference mask 를 만들고
    reference_is_empty=True 로 표시한다. 학습자는 "병변 없음" 답으로 풀 수 있다 (grading.py).
- AI 예측은 채점에 사용하지 않는다. ReadingView가 같은 case_id로 AI sidecar를 조회하도록 ID를 그대로 유지한다.

주의
----
이 스크립트가 만드는 reference mask는 통합 학습 데이터셋에 포함된 원본 GT polygon을
PNG로 다시 그린 것이다. AI 예측 mask를 정답으로 사용하지 않는다 (음성 케이스도 마찬가지 —
빈 마스크는 GT 라벨이 비어 있다는 사실에서 나온 것이지 AI 가 0건 검출해서가 아니다).
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw
from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import Case

try:
    from app.models import CaseSlice
except ImportError:
    CaseSlice = None

from app.static_files import STATIC_DIR


DISEASE_INFO = {
    "vestibular_schwannoma": {
        "ko": "전정신경초종",
        "dataset": "TCIA VESTIBULAR-SCHWANNOMA-SEG",
    },
    "glioma": {
        "ko": "교종",
        "dataset": "TCIA UTSW-Glioma",
    },
    "brain_metastasis": {
        "ko": "뇌전이",
        "dataset": "TCIA PRETREAT-METSTOBRAIN-MASKS",
    },
    "ischemic_stroke": {
        "ko": "허혈성 뇌졸중",
        "dataset": "ISLES 2022",
    },
    "multiple_sclerosis": {
        "ko": "다발성경화증",
        "dataset": "MS3SEG",
    },
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--medical-ai-root", type=Path, default=Path("/medical-ai"))
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def find_label_file(dataset_root: Path, source_image_name: str) -> Path:
    stem = Path(source_image_name).stem
    candidates = [
        dataset_root / "labels" / "val" / f"{stem}.txt",
        dataset_root / "labels" / "validation" / f"{stem}.txt",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"GT YOLO 라벨을 찾지 못했습니다: {source_image_name}\n"
        + "\n".join(str(x) for x in candidates)
    )


def polygon_label_to_mask(label_path: Path, width: int, height: int) -> Image.Image:
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)

    text = label_path.read_text(encoding="utf-8").strip()
    if not text:
        return mask

    for line_no, line in enumerate(text.splitlines(), start=1):
        parts = line.strip().split()
        if not parts:
            continue
        if len(parts) < 7 or (len(parts) - 1) % 2 != 0:
            raise ValueError(f"{label_path.name}:{line_no} polygon 형식 오류")

        coords = [float(v) for v in parts[1:]]
        xy = []
        for i in range(0, len(coords), 2):
            x = max(0.0, min(1.0, coords[i]))
            y = max(0.0, min(1.0, coords[i + 1]))
            px = int(round(x * (width - 1)))
            py = int(round(y * (height - 1)))
            xy.append((px, py))

        if len(xy) >= 3:
            draw.polygon(xy, fill=255)

    return mask


def set_if_column(obj, name, value):
    if name in obj.__table__.columns.keys():
        setattr(obj, name, value)


def clear_case_slices(db, case_id: str):
    if CaseSlice is None:
        return
    if "case_id" not in CaseSlice.__table__.columns.keys():
        return
    old = db.scalars(select(CaseSlice).where(CaseSlice.case_id == case_id)).all()
    for item in old:
        db.delete(item)


def build_explanation(disease: str, mask_pixels: int):
    meta = DISEASE_INFO[disease]
    # 음성 케이스는 "정상"이라고 쓰지 않는다 — 이 slice 의 기준 마스크에 표시된 병변이 없다는 것뿐이다
    reference_region = (
        "공개 데이터셋에서 제공된 병변 GT 마스크 영역"
        if mask_pixels > 0
        else "이 학습 케이스의 전문가 기준 마스크에는 표시된 병변 영역이 없습니다 (데이터셋 GT 라벨이 비어 있음)"
    )
    return {
        "case_facts": {
            "source": "dataset_verified",
            "disease_name": meta["ko"],
            "disease_code": disease,
            "reference_region": reference_region,
            "dataset": meta["dataset"],
            "representative_area_px": mask_pixels,
        },
        "case_findings": None,
    }


def main():
    args = parse_args()
    medical_ai_root = args.medical_ai_root.resolve()

    inference_root = medical_ai_root / "service_inference_5disease"
    dataset_root = medical_ai_root / "yolo_brain_5disease_integrated"

    index_path = inference_root / "index.json"
    if not index_path.exists():
        raise SystemExit(f"index.json 없음: {index_path}")
    if not dataset_root.exists():
        raise SystemExit(f"통합 데이터셋 없음: {dataset_root}")

    index = read_json(index_path)
    records = index.get("cases", [])
    if len(records) != 15:
        print(f"[경고] index.json 케이스 수가 15가 아닙니다: {len(records)}")

    prepared = []
    errors = []

    case_static_root = STATIC_DIR / "cases"
    case_static_root.mkdir(parents=True, exist_ok=True)

    # DB 스키마/마이그레이션을 기존 프로젝트 방식으로 준비
    init_db()

    with SessionLocal() as db:
        for rec in records:
            case_id = rec.get("case_id")
            disease = rec.get("source_disease")
            positive = bool(rec.get("is_positive_gt"))

            try:
                if disease not in DISEASE_INFO:
                    raise ValueError(f"지원하지 않는 disease: {disease}")

                sidecar_rel = rec["ai_prediction_json"]
                sidecar = read_json(inference_root / sidecar_rel)
                source_image_name = sidecar["source_image_name"]

                source_image = inference_root / rec["source_image"]
                if not source_image.exists():
                    raise FileNotFoundError(source_image)

                label_path = find_label_file(dataset_root, source_image_name)

                with Image.open(source_image) as im:
                    image = im.convert("L")
                    width, height = image.size

                ref_mask = polygon_label_to_mask(label_path, width, height)
                mask_pixels = sum(1 for v in ref_mask.getdata() if v > 0)

                # index의 GT 양성 여부와 실제 라벨을 서로 확인
                if positive and mask_pixels == 0:
                    raise ValueError("index는 GT 양성인데 복원한 reference mask가 비어 있습니다.")
                if (not positive) and mask_pixels > 0:
                    raise ValueError("index는 GT 음성인데 복원한 reference mask에 병변이 있습니다.")

                if not positive:
                    # 음성: 동일 크기의 완전히 빈 기준 마스크. AI 예측 마스크는 쓰지 않는다.
                    ref_mask = Image.new("L", (width, height), 0)

                if args.dry_run:
                    prepared.append(
                        {
                            "case_id": case_id,
                            "disease": disease,
                            "source_image_name": source_image_name,
                            "mask_pixels": mask_pixels,
                            "reference_is_empty": not positive,
                            "mode": "dry-run",
                        }
                    )
                    continue

                case_dir = case_static_root / case_id
                if case_dir.exists():
                    shutil.rmtree(case_dir)
                case_dir.mkdir(parents=True, exist_ok=True)

                image_dest = case_dir / "image.png"
                mask_dest = case_dir / "reference_mask.png"
                thumb_dest = case_dir / "thumbnail.png"

                image.save(image_dest)
                ref_mask.save(mask_dest)

                thumb = image.copy()
                thumb.thumbnail((320, 320))
                thumb.save(thumb_dest)

                image_url = f"/static/cases/{case_id}/image.png"
                mask_url = f"/static/cases/{case_id}/reference_mask.png"
                thumb_url = f"/static/cases/{case_id}/thumbnail.png"

                case = db.scalar(select(Case).where(Case.case_id == case_id))
                is_new = case is None

                if is_new:
                    # 최소 필드만 생성자에 전달해 프로젝트 버전 차이를 줄인다.
                    kwargs = {"case_id": case_id}
                    cols = Case.__table__.columns.keys()
                    if "body_part" in cols:
                        kwargs["body_part"] = "brain_mri"
                    if "disease" in cols:
                        kwargs["disease"] = disease
                    if "image_url" in cols:
                        kwargs["image_url"] = image_url
                    case = Case(**kwargs)
                    db.add(case)

                set_if_column(case, "body_part", "brain_mri")
                set_if_column(case, "disease", disease)
                set_if_column(case, "image_url", image_url)
                set_if_column(case, "thumbnail_url", thumb_url)
                set_if_column(case, "reference_mask_url", mask_url)
                # 빈 기준 마스크를 채점 기준으로 인정하려면 명시적으로 켜야 한다 (grading._load_reference)
                set_if_column(case, "reference_is_empty", not positive)
                set_if_column(case, "volume_id", None)
                set_if_column(case, "representative_slice", 0)
                set_if_column(
                    case,
                    "image_meta",
                    {
                        "width": width,
                        "height": height,
                        "slice_index": 0,
                        "total_slices": 1,
                        "source_image_name": source_image_name,
                        "source_split": sidecar.get("source_split", "val"),
                    },
                )
                set_if_column(case, "reference_shape", None)
                set_if_column(case, "explanation", build_explanation(disease, mask_pixels))
                set_if_column(case, "findings_status", "needs_expert_review")

                clear_case_slices(db, case_id)

                prepared.append(
                    {
                        "case_id": case_id,
                        "disease": disease,
                        "source_image_name": source_image_name,
                        "mask_pixels": mask_pixels,
                        "reference_is_empty": not positive,
                        "mode": "insert" if is_new else "update",
                    }
                )

            except Exception as e:
                errors.append({"case_id": case_id, "error": repr(e)})

        if args.dry_run:
            db.rollback()
        elif errors:
            db.rollback()
            print("\n오류가 있어 DB 변경을 전부 롤백했습니다.")
        else:
            db.commit()

    print("\n================ 39 등록 결과 ================")
    n_neg = sum(1 for r in prepared if r["reference_is_empty"])
    print(f"학습 등록 대상: {len(prepared)} (양성 {len(prepared) - n_neg} / 음성 {n_neg})")
    for row in prepared:
        kind = "NEG" if row["reference_is_empty"] else "POS"
        print(
            f"  OK  {kind} {row['case_id']:34s} "
            f"{row['disease']:24s} mask_px={row['mask_pixels']} [{row['mode']}]"
        )

    print("\n오류:", len(errors))
    for row in errors:
        print("  ERR ", row["case_id"], row["error"])

    report_dir = Path("/app/data")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "brain5_registration_report.json"
    report = {
        "registered_or_checked": prepared,
        "errors": errors,
        "dry_run": args.dry_run,
        "policy": {
            "scoring": "reference GT mask only",
            "ai_prediction": "supplemental only",
            "negative_cases": "empty reference mask + reference_is_empty=True; answered with explicit no_abnormality",
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n보고서:", report_path)

    if errors:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
