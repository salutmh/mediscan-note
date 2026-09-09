"""
실제 케이스 등록 스크립트.

의료영상 원본과 reference mask 는 **git 에 커밋하지 않는다.** 이 스크립트는 리포 밖(또는
gitignore 된 폴더)에 있는 실제 파일을 읽어 검증한 뒤, 서비스가 서빙하는 위치로 복사하고
DB(cases / case_slices 테이블)에 등록한다.

사용법
------
    cd backend
    python -m scripts.import_cases <manifest.json>            # 등록
    python -m scripts.import_cases <manifest.json> --dry-run  # 검증만
    python -m scripts.import_cases <manifest.json> --replace  # 기존 케이스 덮어쓰기

manifest 형식은 `backend/data/manifest.example.json` 참고.
경로는 manifest 파일 위치를 기준으로 한 상대경로도 된다.

단일 영상 케이스와 volume 케이스를 모두 받는다:
  - 단일 영상 : image / reference_mask 만 있으면 된다
  - volume    : 추가로 volume_id, representative_slice, slices[] 를 준다
                (slices[].slice_index 는 **원본 volume 인덱스를 그대로** 보존한다)

**운영 규칙**: 채점 기준이 곧 reference mask 이므로 팀에서 **검수를 마친 마스크만** 등록한다.
마스크가 없거나 열리지 않으면 케이스는 등록되되 `gradable: false` 가 되어 제출이 막힌다.

**해설 규칙 (API 계약 v0.4)**: 해설은 출처가 다른 3개 블록으로 나뉜다.

| 블록 | 출처 | manifest 로 넣나 |
|---|---|---|
| `case_facts`    | `dataset_verified`  | **필수.** GT/DICOM 에서 계산된 값만 (사람이 타이핑하지 않는다) |
| `disease_info`  | `literature_based`  | **넣을 수 없다.** app/content/diseases/<질환>.json 에서 온다 |
| `case_findings` | `expert_reviewed`   | 선택. 넣으려면 reviewer / reviewed_at 이 함께 있어야 한다 |

`disease_info` 를 manifest 로 막는 이유는, 케이스 등록자가 임의로 쓴 문장이 "문헌 기반"으로
표시되는 경로를 만들지 않기 위해서다. `case_findings` 의 reviewer/reviewed_at 은
**검토 출처 메타데이터를 필수화**하는 것이지, 필드가 있다고 검토를 보증하는 것은 아니다.
"""
import argparse
import json
import shutil
import uuid
import sys
from datetime import date
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db import SessionLocal, init_db  # noqa: E402
from app.explanations import SOURCE_DATASET, SOURCE_EXPERT  # noqa: E402
from app.models import Case, CaseSlice  # noqa: E402
from app.static_files import STATIC_DIR  # noqa: E402

# 실제 케이스 자산이 복사되는 위치. .gitignore 로 제외되어 있다.
CASES_DIR = STATIC_DIR / "cases"
CASES_URL_PREFIX = "/static/cases"

REQUIRED_FIELDS = ["case_id", "body_part", "disease", "image", "explanation"]
REQUIRED_CASE_FACTS = ["disease_name", "reference_region"]
REQUIRED_CASE_FINDINGS = ["findings", "reviewer", "reviewed_at"]
# v0.3 까지 쓰던 평평한 해설 키. 남아 있으면 조용히 무시하지 말고 실패시킨다.
LEGACY_EXPLANATION_KEYS = ["key_findings", "review_status", "medical_terms", "reference"]
THUMBNAIL_SIZE = (256, 256)


class ImportError_(Exception):
    """케이스 하나를 등록할 수 없을 때."""


def _resolve(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def _open_image(path: Path, label: str) -> Image.Image:
    if not path.exists():
        raise ImportError_(f"{label} 파일이 없습니다: {path}")
    try:
        image = Image.open(path)
        image.load()
    except UnidentifiedImageError as exc:
        raise ImportError_(f"{label} 을(를) 이미지로 열 수 없습니다: {path}") from exc
    except OSError as exc:
        raise ImportError_(f"{label} 이(가) 손상되었습니다: {path} ({exc})") from exc
    return image


def _optional_text(value) -> str | None:
    """빈 문자열은 None 으로. '있는 척'하는 빈 블록을 만들지 않는다."""
    text = str(value).strip() if value is not None else ""
    return text or None


def _string_list(value, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ImportError_(f"explanation.case_findings.{field} 는 문자열 배열이어야 합니다.")
    items = [str(v).strip() for v in value]
    return [item for item in items if item]


def _validate_case_findings(findings) -> dict:
    """전문가 소견 블록. 검토 출처 메타데이터(누가/언제)가 없으면 등록하지 않는다."""
    if not isinstance(findings, dict):
        raise ImportError_("explanation.case_findings 는 객체여야 합니다.")

    missing = [f for f in REQUIRED_CASE_FINDINGS if not str(findings.get(f, "")).strip()]
    if missing:
        raise ImportError_(
            f"explanation.case_findings 필수 항목 누락: {', '.join(missing)} "
            "(누가 언제 검토했는지 남지 않는 소견은 등록하지 않습니다)"
        )

    reviewed_at = str(findings["reviewed_at"]).strip()
    try:
        date.fromisoformat(reviewed_at)
    except ValueError as exc:
        raise ImportError_(
            f"explanation.case_findings.reviewed_at 은 YYYY-MM-DD 형식이어야 합니다: {reviewed_at}"
        ) from exc

    return {
        "source": SOURCE_EXPERT,
        "findings": str(findings["findings"]).strip(),
        # 아래 학습용 필드는 선택이다. **비어 있으면 비운 채로 둔다** —
        # 전문가가 쓰지 않은 내용을 등록 과정에서 만들어 넣지 않는다.
        "lesion_location": _optional_text(findings.get("lesion_location")),
        "reference_region_note": _optional_text(findings.get("reference_region_note")),
        "learning_points": _string_list(findings.get("learning_points"), "learning_points"),
        "common_mistakes": _string_list(findings.get("common_mistakes"), "common_mistakes"),
        "medical_terms": findings.get("medical_terms", []),
        "references": findings.get("references", []),
        "reviewer": str(findings["reviewer"]).strip(),
        "reviewed_at": reviewed_at,
        "content_version": _optional_text(findings.get("content_version")),
    }


def _validate_explanation(explanation, disease_code: str) -> dict:
    if not isinstance(explanation, dict):
        raise ImportError_("explanation 은 객체여야 합니다.")

    legacy = [k for k in LEGACY_EXPLANATION_KEYS if k in explanation]
    if legacy:
        raise ImportError_(
            f"explanation 에 v0.3 형식 키가 남아 있습니다: {', '.join(legacy)}. "
            "v0.4 는 case_facts / case_findings 블록을 씁니다 (data/manifest.example.json 참고)."
        )
    if "disease_info" in explanation:
        raise ImportError_(
            "explanation.disease_info 는 manifest 로 넣을 수 없습니다. "
            "질환 문헌 정보는 app/content/diseases/<질환코드>.json 에서 옵니다."
        )

    facts = explanation.get("case_facts")
    if not isinstance(facts, dict):
        raise ImportError_("explanation.case_facts 가 필요합니다 (객체).")
    missing = [f for f in REQUIRED_CASE_FACTS if not str(facts.get(f, "")).strip()]
    if missing:
        raise ImportError_(f"explanation.case_facts 필수 항목 누락: {', '.join(missing)}")

    laterality = facts.get("laterality")
    if laterality not in (None, "right", "left"):
        raise ImportError_(f"explanation.case_facts.laterality 값이 잘못됐습니다: {laterality}")

    case_facts = {
        # source 는 manifest 값을 믿지 않고 항상 여기서 채운다
        "source": SOURCE_DATASET,
        "disease_name": facts["disease_name"],
        "disease_code": facts.get("disease_code") or disease_code,
        "laterality": laterality,
        "laterality_basis": facts.get("laterality_basis"),
        "representative_slice": facts.get("representative_slice"),
        "total_slices": facts.get("total_slices"),
        "lesion_slice_range": facts.get("lesion_slice_range"),
        "representative_area_px": facts.get("representative_area_px"),
        "reference_region": facts["reference_region"],
        "dataset": facts.get("dataset"),
    }

    case_findings = explanation.get("case_findings")
    return {
        "case_facts": case_facts,
        "case_findings": _validate_case_findings(case_findings) if case_findings else None,
    }


def _validate_slices(entry: dict, base: Path, image_size: tuple[int, int]) -> list[dict]:
    """volume 케이스의 slice 목록 검증. 원본 slice_index 를 그대로 들고 간다."""
    raw = entry.get("slices")
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ImportError_("slices 는 배열이어야 합니다.")

    seen: set[int] = set()
    validated = []
    for item in raw:
        if not isinstance(item, dict) or "slice_index" not in item or not item.get("image"):
            raise ImportError_("slices 항목에는 slice_index 와 image 가 있어야 합니다.")
        index = int(item["slice_index"])
        if index in seen:
            raise ImportError_(f"slice_index 가 중복됐습니다: {index}")
        seen.add(index)

        slice_image = _resolve(base, item["image"])
        opened = _open_image(slice_image, f"slice {index} 영상")
        if opened.size != image_size:
            raise ImportError_(
                f"slice {index} 크기가 대표 영상과 다릅니다 "
                f"(대표 {image_size[0]}x{image_size[1]}, slice {opened.size[0]}x{opened.size[1]})"
            )

        mask_path = None
        if item.get("mask"):
            mask_path = _resolve(base, item["mask"])
            mask = _open_image(mask_path, f"slice {index} 마스크")
            if mask.size != image_size:
                raise ImportError_(f"slice {index} 마스크 크기가 영상과 다릅니다.")

        validated.append(
            {
                "slice_index": index,
                "image_path": slice_image,
                "mask_path": mask_path,
                # 전문가 GT 그대로. 작은 병변이라고 버리지 않는다.
                "lesion_area_px": int(item.get("lesion_area_px", 0)),
            }
        )

    validated.sort(key=lambda s: s["slice_index"])
    return validated


def validate_entry(entry: dict, base: Path) -> dict:
    """manifest 항목 하나를 검증하고 정규화된 정보를 돌려준다."""
    missing = [f for f in REQUIRED_FIELDS if not entry.get(f)]
    if missing:
        raise ImportError_(f"필수 항목 누락: {', '.join(missing)}")

    explanation = _validate_explanation(entry["explanation"], entry["disease"])

    image_path = _resolve(base, entry["image"])
    image = _open_image(image_path, "영상")

    mask_path = None
    mask_warning = None
    if entry.get("reference_mask"):
        candidate = _resolve(base, entry["reference_mask"])
        try:
            mask = _open_image(candidate, "기준 마스크")
        except ImportError_ as exc:
            # 마스크 문제는 케이스 등록을 막지 않는다 — gradable=false 로 등록된다
            mask_warning = str(exc)
        else:
            if mask.size != image.size:
                mask_warning = (
                    f"기준 마스크 크기가 영상과 다릅니다 "
                    f"(영상 {image.size[0]}x{image.size[1]}, 마스크 {mask.size[0]}x{mask.size[1]})"
                )
            else:
                mask_path = candidate
    else:
        mask_warning = "reference_mask 가 지정되지 않았습니다"

    slices = _validate_slices(entry, base, image.size)
    representative = entry.get("representative_slice")
    if slices and representative is not None:
        if int(representative) not in {s["slice_index"] for s in slices}:
            raise ImportError_(
                f"representative_slice({representative}) 가 slices 안에 없습니다."
            )

    return {
        "case_id": entry["case_id"],
        "body_part": entry["body_part"],
        "disease": entry["disease"],
        "image_path": image_path,
        "image_size": image.size,
        "mask_path": mask_path,
        "mask_warning": mask_warning,
        "explanation": explanation,
        "volume_id": entry.get("volume_id"),
        "representative_slice": int(representative) if representative is not None else None,
        "slices": slices,
        "slice_index": entry.get("slice_index", representative if representative is not None else 0),
        "total_slices": entry.get("total_slices", 1),
    }


def _slice_url(case_id: str, name: str) -> str:
    return f"{CASES_URL_PREFIX}/{case_id}/slices/{name}"


def _copy_assets(info: dict) -> dict:
    """영상·마스크를 서비스가 서빙하는 위치로 복사하고 썸네일을 만든다.

    volume 케이스는 slices/ 아래에 slice 별 파일을 두고, 케이스 대표 영상/마스크는
    **대표 slice 파일을 그대로 가리킨다** (같은 픽셀을 두 번 복사하지 않는다).
    """
    case_dir = CASES_DIR / info["case_id"]
    case_dir.mkdir(parents=True, exist_ok=True)

    slice_urls: dict[int, dict] = {}
    if info["slices"]:
        slices_dir = case_dir / "slices"
        # 다시 등록할 때 예전 slice 파일이 남지 않도록 통째로 비운다
        if slices_dir.exists():
            shutil.rmtree(slices_dir)
        slices_dir.mkdir(parents=True, exist_ok=True)

        for item in info["slices"]:
            index = item["slice_index"]
            image_name = f"slice_{index:03d}{item['image_path'].suffix.lower()}"
            shutil.copy2(item["image_path"], slices_dir / image_name)

            mask_url = None
            if item["mask_path"] is not None:
                mask_name = f"mask_{index:03d}{item['mask_path'].suffix.lower()}"
                shutil.copy2(item["mask_path"], slices_dir / mask_name)
                mask_url = _slice_url(info["case_id"], mask_name)

            slice_urls[index] = {
                "image_url": _slice_url(info["case_id"], image_name),
                "mask_url": mask_url,
            }

    representative = info["representative_slice"]
    if slice_urls and representative in slice_urls:
        image_url = slice_urls[representative]["image_url"]
        mask_url = slice_urls[representative]["mask_url"]
        thumb_source = CASES_DIR / info["case_id"] / "slices" / Path(image_url).name
    else:
        image_dest = case_dir / f"image{info['image_path'].suffix.lower()}"
        shutil.copy2(info["image_path"], image_dest)
        image_url = f"{CASES_URL_PREFIX}/{info['case_id']}/{image_dest.name}"

        mask_url = None
        if info["mask_path"] is not None:
            mask_dest = case_dir / f"mask{info['mask_path'].suffix.lower()}"
            shutil.copy2(info["mask_path"], mask_dest)
            mask_url = f"{CASES_URL_PREFIX}/{info['case_id']}/{mask_dest.name}"
        thumb_source = image_dest

    thumb_dest = case_dir / "thumb.png"
    with Image.open(thumb_source) as img:
        thumb = img.convert("RGB")
        thumb.thumbnail(THUMBNAIL_SIZE)
        thumb.save(thumb_dest, "PNG")

    return {
        "image_url": image_url,
        "thumbnail_url": f"{CASES_URL_PREFIX}/{info['case_id']}/{thumb_dest.name}",
        "reference_mask_url": mask_url,
        "slice_urls": slice_urls,
    }


def _stash_case_dir(case_id: str) -> Path | None:
    """이 케이스의 기존 자산을 옆으로 치운다. 없으면 None.

    등록이 중간에 실패했을 때 되돌리기 위해서다. 덮어쓰기(--replace) 도중 실패하면
    **잘 돌던 케이스의 자산이 반쯤 갈아엎힌 상태**로 남는데, 그게 가장 나쁘다.
    """
    case_dir = CASES_DIR / case_id
    if not case_dir.exists():
        return None
    stash = CASES_DIR / f".stash-{case_id}-{uuid.uuid4().hex[:8]}"
    shutil.move(str(case_dir), str(stash))
    return stash


def _restore_case_dir(case_id: str, stash: Path | None) -> None:
    """실패했을 때 원래 자산으로 되돌린다. 원래 없었으면 새로 만든 것을 지운다."""
    case_dir = CASES_DIR / case_id
    if case_dir.exists():
        shutil.rmtree(case_dir, ignore_errors=True)
    if stash is not None and stash.exists():
        shutil.move(str(stash), str(case_dir))


def _drop_stash(stash: Path | None) -> None:
    if stash is not None and stash.exists():
        shutil.rmtree(stash, ignore_errors=True)


def import_manifest(manifest_path: Path, replace: bool = False, dry_run: bool = False) -> dict:
    """manifest 를 읽어 케이스를 등록한다. 결과 요약을 돌려준다."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("cases", manifest if isinstance(manifest, list) else [])
    base = manifest_path.resolve().parent

    summary = {"registered": [], "skipped": [], "failed": [], "warnings": []}

    with SessionLocal() as db:
        existing = set(db.scalars(select(Case.case_id)).all())

        for entry in entries:
            case_id = entry.get("case_id", "(id 없음)")
            try:
                info = validate_entry(entry, base)
            except ImportError_ as exc:
                summary["failed"].append((case_id, str(exc)))
                continue

            if info["case_id"] in existing and not replace:
                summary["skipped"].append((info["case_id"], "이미 등록됨 (--replace 로 덮어쓰기)"))
                continue

            if info["mask_warning"]:
                summary["warnings"].append((info["case_id"], info["mask_warning"]))
            if info["explanation"]["case_findings"] is None:
                summary["warnings"].append(
                    (info["case_id"], "케이스별 영상 소견 없음 (사실/문헌 정보만 제공)")
                )

            if dry_run:
                summary["registered"].append((info["case_id"], "(dry-run)"))
                continue

            # **케이스 하나를 원자적으로 처리한다.**
            # 24건을 한 번에 넣다가 20번째에서 실패했을 때, 앞 19건은 남고 20번째는
            # 흔적 없이 사라져야 한다. DB 만 롤백하면 static 에 자산이 남아
            # "파일은 있는데 DB 에 없는" 상태가 되고, 다음 등록 때 무엇이 진짜인지 알 수 없다.
            stash = _stash_case_dir(info["case_id"])
            try:
                urls = _copy_assets(info)
                width, height = info["image_size"]
                case = db.get(Case, info["case_id"]) or Case(case_id=info["case_id"])
                case.body_part = info["body_part"]
                case.disease = info["disease"]
                case.image_url = urls["image_url"]
                case.thumbnail_url = urls["thumbnail_url"]
                case.reference_mask_url = urls["reference_mask_url"]
                case.volume_id = info["volume_id"]
                case.representative_slice = info["representative_slice"]
                case.image_meta = {
                    "width": width,
                    "height": height,
                    "slice_index": info["slice_index"],
                    "total_slices": info["total_slices"],
                }
                case.explanation = info["explanation"]
                # 소견이 실제로 들어왔을 때만 approved. 없으면 "아직 검토 전"이라고 사실대로 둔다.
                # (manifest 로 상태만 approved 로 올리는 경로를 만들지 않는다)
                case.findings_status = (
                    "approved"
                    if info["explanation"].get("case_findings")
                    else "needs_expert_review"
                )
                # 좌표 근사 채점은 개발 전용이라 실제 케이스에는 쓰지 않는다
                case.reference_shape = None
                db.add(case)
                db.flush()

                # slice 는 통째로 갈아끼운다 (부분 갱신은 예전 slice 가 남을 수 있다)
                for old_slice in db.scalars(
                    select(CaseSlice).where(CaseSlice.case_id == info["case_id"])
                ).all():
                    db.delete(old_slice)
                db.flush()

                for item in info["slices"]:
                    index = item["slice_index"]
                    db.add(
                        CaseSlice(
                            case_id=info["case_id"],
                            slice_index=index,
                            image_url=urls["slice_urls"][index]["image_url"],
                            mask_url=urls["slice_urls"][index]["mask_url"],
                            lesion_area_px=item["lesion_area_px"],
                        )
                    )

                # 이 케이스만 커밋한다. 앞 케이스는 이미 안전하게 들어가 있다.
                db.commit()
            except Exception as exc:
                # DB 와 파일을 **함께** 되돌린다. 한쪽만 되돌리면 상태가 어긋난다.
                db.rollback()
                _restore_case_dir(info["case_id"], stash)
                summary["failed"].append((info["case_id"], f"등록 실패: {exc}"))
                continue
            else:
                _drop_stash(stash)

            existing.add(info["case_id"])
            note = "gradable" if urls["reference_mask_url"] else "gradable=false"
            if info["slices"]:
                note += f", slice {len(info['slices'])}장 (대표 {info['representative_slice']})"
            summary["registered"].append((info["case_id"], note))

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="실제 케이스를 DB에 등록한다.")
    parser.add_argument("manifest", type=Path, help="케이스 manifest JSON 경로")
    parser.add_argument("--replace", action="store_true", help="이미 등록된 case_id 를 덮어쓴다")
    parser.add_argument("--dry-run", action="store_true", help="검증만 하고 저장하지 않는다")
    args = parser.parse_args()

    if not args.manifest.exists():
        print(f"manifest 를 찾을 수 없습니다: {args.manifest}")
        return 1

    init_db()  # 마이그레이션 적용 보장
    summary = import_manifest(args.manifest, replace=args.replace, dry_run=args.dry_run)

    for case_id, note in summary["registered"]:
        print(f"  [등록] {case_id}  {note}")
    for case_id, note in summary["skipped"]:
        print(f"  [건너뜀] {case_id}  {note}")
    for case_id, note in summary["warnings"]:
        print(f"  [경고] {case_id}  {note}")
    for case_id, note in summary["failed"]:
        print(f"  [실패] {case_id}  {note}")

    print()
    print(
        f"등록 {len(summary['registered'])} / 건너뜀 {len(summary['skipped'])} / "
        f"경고 {len(summary['warnings'])} / 실패 {len(summary['failed'])}"
    )
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
