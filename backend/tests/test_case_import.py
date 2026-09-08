"""
실제 케이스 등록 파이프라인 테스트 (scripts/import_cases.py).

핵심:
  - 영상·마스크·병명·소견·의학용어·참고자료가 케이스에 연결된다
  - 마스크가 없거나 잘못된 케이스는 등록은 되되 gradable=false 가 된다
  - 필수 항목이 빠지면 등록되지 않는다
  - 등록된 실제 케이스로 채점(Dice/IoU)이 정상 동작한다
"""
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.db import SessionLocal
from app.grading import is_gradable
from app.models import Case, Submission
from scripts import import_cases

CASE_ID = "TEST-CXR-9001"
LESION = (200, 240, 30)  # cx, cy, r
SIZE = (512, 512)


def _write_image(path, size=SIZE):
    img = Image.new("RGB", size, (40, 40, 40))
    cx, cy, r = LESION
    ImageDraw.Draw(img).ellipse([cx - r, cy - r, cx + r, cy + r], fill=(200, 200, 200))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def _write_mask(path, size=SIZE):
    mask = Image.new("RGBA", size, (0, 0, 0, 0))
    cx, cy, r = LESION
    ImageDraw.Draw(mask).ellipse([cx - r, cy - r, cx + r, cy + r], fill=(0, 200, 90, 190))
    path.parent.mkdir(parents=True, exist_ok=True)
    mask.save(path)


def _entry(case_id=CASE_ID, **overrides) -> dict:
    entry = {
        "case_id": case_id,
        "body_part": "chest_xray",
        "disease": "pneumothorax",
        "image": "raw/image.png",
        "reference_mask": "raw/mask.png",
        "explanation": {
            "case_facts": {
                "disease_name": "기흉 (Pneumothorax)",
                "disease_code": "pneumothorax",
                "reference_region": "우측 폐첨부 흉막강",
                "dataset": "합성 테스트 픽스처",
            },
            "case_findings": {
                "findings": "장측 흉막선이 보이고 그 바깥으로 혈관 음영이 소실됨",
                "medical_terms": [{"term": "흉막선(pleural line)"}, {"term": "폐첨부(apex)"}],
                "references": [{"title": "예시", "url": "https://example.org/ref"}],
                "reviewer": "테스트 검토자",
                "reviewed_at": "2026-09-08",
            },
        },
    }
    entry.update(overrides)
    return entry


@pytest.fixture
def manifest_dir(tmp_path, monkeypatch):
    """manifest + 원본 파일이 있는 임시 폴더.

    복사 대상(CASES_DIR)과 URL 해석 기준(STATIC_DIR)을 **함께** tmp_path 로 돌린다.
    둘 중 하나만 바꾸면 저장 위치와 조회 위치가 어긋나 채점이 실패한다.
    앱의 실제 static 폴더는 이 테스트로 전혀 변하지 않는다.
    """
    import app.static_files as static_files

    _write_image(tmp_path / "raw" / "image.png")
    _write_mask(tmp_path / "raw" / "mask.png")

    served = tmp_path / "served"
    served.mkdir()
    monkeypatch.setattr(static_files, "STATIC_DIR", served)
    monkeypatch.setattr(import_cases, "CASES_DIR", served / "cases")
    return tmp_path


def _write_manifest(base: Path, entries: list[dict]) -> Path:
    path = base / "manifest.json"
    path.write_text(json.dumps({"cases": entries}, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _cleanup_imported_cases():
    yield
    with SessionLocal() as db:
        db.query(Submission).filter(Submission.case_id.like("TEST-CXR-%")).delete(
            synchronize_session=False
        )
        db.query(Case).filter(Case.case_id.like("TEST-CXR-%")).delete(synchronize_session=False)
        db.commit()


# ------------------------------------------------------------------ 정상 등록
def test_imports_case_with_all_metadata(client, manifest_dir):
    manifest = _write_manifest(manifest_dir, [_entry()])
    summary = import_cases.import_manifest(manifest)

    assert [c for c, _ in summary["registered"]] == [CASE_ID]
    assert summary["failed"] == []

    with SessionLocal() as db:
        case = db.get(Case, CASE_ID)

    assert case.body_part == "chest_xray"
    assert case.disease == "pneumothorax"
    assert case.image_url.endswith("/image.png")
    assert case.reference_mask_url.endswith("/mask.png")
    assert case.image_meta["width"] == SIZE[0]
    # 사실 블록과 전문가 소견 블록이 각각 저장된다 (v0.4)
    facts = case.explanation["case_facts"]
    assert facts["source"] == "dataset_verified"
    assert facts["disease_name"] == "기흉 (Pneumothorax)"
    assert facts["reference_region"] == "우측 폐첨부 흉막강"

    findings = case.explanation["case_findings"]
    assert findings["source"] == "expert_reviewed"
    assert findings["findings"]
    assert findings["reviewer"] == "테스트 검토자"
    assert findings["reviewed_at"] == "2026-09-08"


def test_copies_assets_and_builds_thumbnail(client, manifest_dir):
    manifest = _write_manifest(manifest_dir, [_entry()])
    import_cases.import_manifest(manifest)

    case_dir = import_cases.CASES_DIR / CASE_ID
    assert (case_dir / "image.png").exists()
    assert (case_dir / "mask.png").exists()
    assert (case_dir / "thumb.png").exists(), "목록 화면용 썸네일이 생성되어야 한다"


def test_dry_run_does_not_write(client, manifest_dir):
    manifest = _write_manifest(manifest_dir, [_entry()])
    import_cases.import_manifest(manifest, dry_run=True)

    with SessionLocal() as db:
        assert db.get(Case, CASE_ID) is None
    assert not (import_cases.CASES_DIR / CASE_ID).exists()


def test_existing_case_is_skipped_unless_replace(client, manifest_dir):
    manifest = _write_manifest(manifest_dir, [_entry()])
    import_cases.import_manifest(manifest)

    again = import_cases.import_manifest(manifest)
    assert [c for c, _ in again["skipped"]] == [CASE_ID]

    replaced = import_cases.import_manifest(
        _write_manifest(manifest_dir, [_entry(disease="nodule")]), replace=True
    )
    assert [c for c, _ in replaced["registered"]] == [CASE_ID]
    with SessionLocal() as db:
        assert db.get(Case, CASE_ID).disease == "nodule"


# ------------------------------------------- 마스크 문제 -> gradable=false
def test_case_without_mask_is_registered_but_not_gradable(client, manifest_dir):
    entry = _entry()
    entry.pop("reference_mask")
    manifest = _write_manifest(manifest_dir, [entry])

    summary = import_cases.import_manifest(manifest)
    assert [c for c, _ in summary["warnings"]] == [CASE_ID]

    with SessionLocal() as db:
        case = db.get(Case, CASE_ID)
    assert case is not None, "마스크가 없어도 케이스 자체는 등록된다"
    assert case.reference_mask_url is None
    assert is_gradable(case) is False


def test_broken_mask_file_is_registered_but_not_gradable(client, manifest_dir):
    (manifest_dir / "raw" / "broken.png").write_bytes(b"not really a png")
    manifest = _write_manifest(manifest_dir, [_entry(reference_mask="raw/broken.png")])

    summary = import_cases.import_manifest(manifest)
    assert summary["warnings"], "손상된 마스크는 경고로 알려야 한다"

    with SessionLocal() as db:
        case = db.get(Case, CASE_ID)
    assert is_gradable(case) is False


def test_mask_size_mismatch_is_rejected_as_reference(client, manifest_dir):
    _write_mask(manifest_dir / "raw" / "small_mask.png", size=(256, 256))
    manifest = _write_manifest(manifest_dir, [_entry(reference_mask="raw/small_mask.png")])

    summary = import_cases.import_manifest(manifest)
    assert any("크기" in note for _, note in summary["warnings"])

    with SessionLocal() as db:
        assert is_gradable(db.get(Case, CASE_ID)) is False


# ------------------------------------------------------------- 입력 검증
@pytest.mark.parametrize("missing", ["case_id", "body_part", "disease", "image", "explanation"])
def test_missing_required_field_fails(client, manifest_dir, missing):
    entry = _entry()
    entry.pop(missing)
    summary = import_cases.import_manifest(_write_manifest(manifest_dir, [entry]))

    assert summary["failed"], f"{missing} 누락이 통과되면 안 된다"
    assert summary["registered"] == []


def test_missing_case_facts_field_fails(client, manifest_dir):
    entry = _entry()
    entry["explanation"]["case_facts"].pop("reference_region")
    summary = import_cases.import_manifest(_write_manifest(manifest_dir, [entry]))
    assert summary["failed"]
    assert "case_facts" in summary["failed"][0][1]


def test_legacy_v03_explanation_keys_fail_loudly(client, manifest_dir):
    """조용히 무시하면 옛 해설이 사라진 줄 모른 채 등록된다."""
    entry = _entry()
    entry["explanation"]["key_findings"] = "v0.3 형식"
    summary = import_cases.import_manifest(_write_manifest(manifest_dir, [entry]))
    assert summary["failed"]
    assert "key_findings" in summary["failed"][0][1]


def test_missing_image_file_fails(client, manifest_dir):
    summary = import_cases.import_manifest(
        _write_manifest(manifest_dir, [_entry(image="raw/does-not-exist.png")])
    )
    assert summary["failed"]
    assert "없습니다" in summary["failed"][0][1]


# ------------------------------------- 등록된 실제 케이스로 채점이 동작하는지
def test_imported_case_is_gradable_end_to_end(client, manifest_dir, user_a):
    """등록된 케이스에 ROI 를 제출하면 실제 Dice/IoU 가 계산된다."""
    import base64
    import io as _io

    import_cases.import_manifest(_write_manifest(manifest_dir, [_entry()]))

    # 기준 마스크와 정확히 같은 영역을 칠한다
    cx, cy, r = LESION
    roi_img = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    ImageDraw.Draw(roi_img).ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255))
    buf = _io.BytesIO()
    roi_img.save(buf, "PNG")

    res = user_a.post(
        f"/api/cases/{CASE_ID}/submit",
        json={
            "roi": {
                "type": "brush_mask",
                "points": [[cx, cy]],
                "mask_png_base64": base64.b64encode(buf.getvalue()).decode(),
            }
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["grade"] == "match"
    assert body["dice"] > 0.99, "기준 마스크와 동일한 ROI 는 Dice 가 1 에 가까워야 한다"
    assert body["iou"] > 0.99
    assert body["evaluation"]["method"] == "reference_mask"
    assert body["explanation"]["case_facts"]["disease_name"] == "기흉 (Pneumothorax)"


def test_imported_case_without_mask_returns_422(client, manifest_dir, user_a, roi_match):
    entry = _entry()
    entry.pop("reference_mask")
    import_cases.import_manifest(_write_manifest(manifest_dir, [entry]))

    res = user_a.post(f"/api/cases/{CASE_ID}/submit", json={"roi": roi_match})
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "CASE_NOT_GRADABLE"
