"""
volume 케이스(뇌 MRI) 등록 테스트 — scripts/import_cases.py 의 slices 처리.

고정하려는 규칙:
  - **원본 slice_index 를 재번호 매기지 않는다** (2.5D 확장 시 인접 slice 조회 키)
  - **전문가 GT 를 임의로 걸러내지 않는다** — 1px 병변 slice 도 그대로 등록된다
  - 대표 slice 가 케이스의 image_url / reference_mask_url 이 된다
  - 다시 등록하면 예전 slice 가 남지 않는다
  - 해설은 case_facts / case_findings 블록으로 저장되고, disease_info 는 manifest 로 못 넣는다
"""
import base64
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select

from app.db import SessionLocal
from app.grading import is_gradable
from app.models import Case, CaseSlice, Submission
from scripts import import_cases

CASE_ID = "TEST-VS-9001"
SIZE = (128, 128)
# (slice_index, 병변 반지름). 0 이면 병변 없는 여유 slice.
SLICE_PLAN = [(27, 0), (28, 0), (29, 1), (30, 8), (31, 12), (32, 6), (33, 0)]
REPRESENTATIVE = 31


def _write_slice_image(path: Path) -> None:
    image = Image.new("L", SIZE, 30)
    ImageDraw.Draw(image).ellipse([20, 20, 108, 108], fill=90)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _write_slice_mask(path: Path, radius: int) -> int:
    """투명 배경 + 불투명 흰색 (build_vs_seg_case_assets 와 같은 형식). 칠한 픽셀 수를 돌려준다."""
    mask = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    cx = cy = 64
    ImageDraw.Draw(mask).ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius], fill=(255, 255, 255, 255)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    mask.save(path)
    return int((np.asarray(mask)[..., 3] > 16).sum())


@pytest.fixture
def volume_manifest(tmp_path, monkeypatch):
    """slice 파일 + manifest 를 만들고, 복사/조회 위치를 함께 tmp_path 로 돌린다."""
    import app.static_files as static_files

    served = tmp_path / "served"
    served.mkdir()
    monkeypatch.setattr(static_files, "STATIC_DIR", served)
    monkeypatch.setattr(import_cases, "CASES_DIR", served / "cases")

    areas: dict[int, int] = {}
    slices = []
    for index, radius in SLICE_PLAN:
        image_rel = f"raw/slice_{index:03d}.png"
        _write_slice_image(tmp_path / image_rel)

        mask_rel = None
        area = 0
        if radius:
            mask_rel = f"raw/mask_{index:03d}.png"
            area = _write_slice_mask(tmp_path / mask_rel, radius)
        areas[index] = area
        slices.append(
            {
                "slice_index": index,
                "image": image_rel,
                "mask": mask_rel,
                "lesion_area_px": area,
            }
        )

    def build(**overrides) -> Path:
        entry = {
            "case_id": CASE_ID,
            "body_part": "brain_mri",
            "disease": "vestibular_schwannoma",
            "volume_id": f"{CASE_ID}/T1",
            "representative_slice": REPRESENTATIVE,
            "slice_index": REPRESENTATIVE,
            "total_slices": 120,
            "image": f"raw/slice_{REPRESENTATIVE:03d}.png",
            "reference_mask": f"raw/mask_{REPRESENTATIVE:03d}.png",
            "slices": slices,
            "explanation": {
                "case_facts": {
                    "disease_name": "전정신경초종 (Vestibular Schwannoma)",
                    "disease_code": "vestibular_schwannoma",
                    "laterality": "right",
                    "reference_region": "우측 (DICOM 영상 방향으로 확인)",
                    "representative_slice": REPRESENTATIVE,
                    "total_slices": 120,
                    "lesion_slice_range": [29, 32],
                    "dataset": "합성 테스트 픽스처",
                },
                "case_findings": None,
            },
        }
        entry.update(overrides)
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps({"cases": [entry]}, ensure_ascii=False), encoding="utf-8")
        return path

    build.areas = areas  # 테스트에서 기대값으로 쓴다
    return build


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with SessionLocal() as db:
        db.query(Submission).filter(Submission.case_id.like("TEST-VS-%")).delete(
            synchronize_session=False
        )
        db.query(CaseSlice).filter(CaseSlice.case_id.like("TEST-VS-%")).delete(
            synchronize_session=False
        )
        db.query(Case).filter(Case.case_id.like("TEST-VS-%")).delete(synchronize_session=False)
        db.commit()


def _load_slices(db) -> list[CaseSlice]:
    return list(
        db.scalars(
            select(CaseSlice).where(CaseSlice.case_id == CASE_ID).order_by(CaseSlice.slice_index)
        ).all()
    )


# ------------------------------------------------------------------ 정상 등록
def test_registers_volume_fields_and_slices(client, volume_manifest):
    summary = import_cases.import_manifest(volume_manifest())
    assert summary["failed"] == []

    with SessionLocal() as db:
        case = db.get(Case, CASE_ID)
        slices = _load_slices(db)

    assert case.volume_id == f"{CASE_ID}/T1"
    assert case.representative_slice == REPRESENTATIVE
    assert case.image_meta["slice_index"] == REPRESENTATIVE
    assert case.image_meta["total_slices"] == 120
    # 대표 slice 가 곧 케이스의 표시/채점 영상이다
    assert case.image_url.endswith(f"/slices/slice_{REPRESENTATIVE:03d}.png")
    assert case.reference_mask_url.endswith(f"/slices/mask_{REPRESENTATIVE:03d}.png")
    assert is_gradable(case)
    assert len(slices) == len(SLICE_PLAN)


def test_original_slice_indexes_are_preserved(client, volume_manifest):
    """0..n 으로 다시 번호를 매기면 2.5D 확장 때 인접 slice 를 못 찾는다."""
    import_cases.import_manifest(volume_manifest())

    with SessionLocal() as db:
        indexes = [s.slice_index for s in _load_slices(db)]

    assert indexes == [index for index, _ in SLICE_PLAN]
    assert indexes[0] == 27, "원본 인덱스가 그대로여야 한다"


def test_tiny_lesion_slices_are_kept_with_their_area(client, volume_manifest):
    """전문가 GT 를 최소 면적으로 걸러내지 않는다 — 작은 파편 slice 도 등록된다."""
    build = volume_manifest
    import_cases.import_manifest(build())

    with SessionLocal() as db:
        by_index = {s.slice_index: s for s in _load_slices(db)}

    smallest = by_index[29]
    assert smallest.mask_url is not None, "1px 짜리라도 마스크가 있으면 등록해야 한다"
    assert smallest.lesion_area_px == build.areas[29] > 0

    # 병변이 없는 여유 slice 는 마스크 없이 등록된다
    assert by_index[27].mask_url is None
    assert by_index[27].lesion_area_px == 0


def test_slice_files_are_copied_under_slices_dir(client, volume_manifest):
    import_cases.import_manifest(volume_manifest())

    slices_dir = import_cases.CASES_DIR / CASE_ID / "slices"
    assert (slices_dir / f"slice_{REPRESENTATIVE:03d}.png").exists()
    assert (slices_dir / f"mask_{REPRESENTATIVE:03d}.png").exists()
    assert (slices_dir / "slice_027.png").exists()
    assert not (slices_dir / "mask_027.png").exists(), "병변 없는 slice 에는 마스크가 없다"
    assert (import_cases.CASES_DIR / CASE_ID / "thumb.png").exists()


def test_reimport_replaces_slices_without_leftovers(client, volume_manifest):
    build = volume_manifest
    import_cases.import_manifest(build())

    fewer = [
        {"slice_index": 30, "image": "raw/slice_030.png", "mask": "raw/mask_030.png",
         "lesion_area_px": build.areas[30]},
        {"slice_index": 31, "image": "raw/slice_031.png", "mask": "raw/mask_031.png",
         "lesion_area_px": build.areas[31]},
    ]
    import_cases.import_manifest(build(slices=fewer), replace=True)

    with SessionLocal() as db:
        indexes = [s.slice_index for s in _load_slices(db)]

    assert indexes == [30, 31], "예전 slice 행이 남으면 안 된다"
    assert not (import_cases.CASES_DIR / CASE_ID / "slices" / "slice_027.png").exists()


# ------------------------------------------------------------------ 입력 검증
def test_representative_slice_must_be_in_slices(client, volume_manifest):
    summary = import_cases.import_manifest(volume_manifest(representative_slice=99))
    assert summary["failed"]
    assert "representative_slice" in summary["failed"][0][1]


def test_duplicate_slice_index_fails(client, volume_manifest):
    duplicated = [
        {"slice_index": 30, "image": "raw/slice_030.png", "mask": None, "lesion_area_px": 0},
        {"slice_index": 30, "image": "raw/slice_031.png", "mask": None, "lesion_area_px": 0},
    ]
    summary = import_cases.import_manifest(
        volume_manifest(slices=duplicated, representative_slice=30)
    )
    assert summary["failed"]
    assert "중복" in summary["failed"][0][1]


def test_slice_size_mismatch_fails(client, volume_manifest, tmp_path):
    Image.new("L", (64, 64), 10).save(tmp_path / "raw" / "odd.png")
    odd = [
        {"slice_index": 31, "image": f"raw/slice_{REPRESENTATIVE:03d}.png",
         "mask": f"raw/mask_{REPRESENTATIVE:03d}.png", "lesion_area_px": 1},
        {"slice_index": 32, "image": "raw/odd.png", "mask": None, "lesion_area_px": 0},
    ]
    summary = import_cases.import_manifest(volume_manifest(slices=odd))
    assert summary["failed"]
    assert "크기" in summary["failed"][0][1]


# ---------------------------------------------------- 해설 블록 규칙 (v0.4)
def test_case_facts_is_stored_with_dataset_source(client, volume_manifest):
    summary = import_cases.import_manifest(volume_manifest())
    assert summary["failed"] == []
    assert any("영상 소견 없음" in note for _, note in summary["warnings"])

    with SessionLocal() as db:
        explanation = db.get(Case, CASE_ID).explanation

    facts = explanation["case_facts"]
    assert facts["source"] == "dataset_verified", "source 는 manifest 값이 아니라 서버가 채운다"
    assert facts["laterality"] == "right"
    assert facts["representative_slice"] == REPRESENTATIVE
    assert explanation["case_findings"] is None


def test_case_facts_source_cannot_be_forged(client, volume_manifest):
    """manifest 가 source 를 expert_reviewed 로 적어도 dataset_verified 로 저장된다."""
    facts = {
        "source": "expert_reviewed",
        "disease_name": "전정신경초종",
        "reference_region": "우측",
    }
    import_cases.import_manifest(volume_manifest(explanation={"case_facts": facts}))

    with SessionLocal() as db:
        assert db.get(Case, CASE_ID).explanation["case_facts"]["source"] == "dataset_verified"


def test_disease_info_cannot_come_from_manifest(client, volume_manifest):
    """문헌 정보는 질환 콘텐츠 파일에서만 온다 — 등록자가 쓴 문장이 '문헌 기반'이 되면 안 된다."""
    explanation = {
        "case_facts": {"disease_name": "전정신경초종", "reference_region": "우측"},
        "disease_info": {"imaging_features": ["임의로 넣은 문장"]},
    }
    summary = import_cases.import_manifest(volume_manifest(explanation=explanation))
    assert summary["failed"]
    assert "disease_info" in summary["failed"][0][1]


def test_case_findings_requires_reviewer_metadata(client, volume_manifest):
    """검토 출처 메타데이터(누가/언제)가 없으면 소견을 등록하지 않는다."""
    explanation = {
        "case_facts": {"disease_name": "전정신경초종", "reference_region": "우측"},
        "case_findings": {"findings": "검토자 없는 소견"},
    }
    summary = import_cases.import_manifest(volume_manifest(explanation=explanation))
    assert summary["failed"]
    assert "reviewer" in summary["failed"][0][1]


def test_case_findings_rejects_bad_review_date(client, volume_manifest):
    explanation = {
        "case_facts": {"disease_name": "전정신경초종", "reference_region": "우측"},
        "case_findings": {
            "findings": "소견",
            "reviewer": "홍길동",
            "reviewed_at": "2026년 9월 8일",
        },
    }
    summary = import_cases.import_manifest(volume_manifest(explanation=explanation))
    assert summary["failed"]
    assert "YYYY-MM-DD" in summary["failed"][0][1]


def test_case_findings_registers_with_full_metadata(client, volume_manifest):
    explanation = {
        "case_facts": {"disease_name": "전정신경초종", "reference_region": "우측"},
        "case_findings": {
            "findings": "전문가가 작성한 소견",
            "reviewer": "홍길동 (영상의학과)",
            "reviewed_at": "2026-09-08",
        },
    }
    summary = import_cases.import_manifest(volume_manifest(explanation=explanation))
    assert summary["failed"] == []

    with SessionLocal() as db:
        findings = db.get(Case, CASE_ID).explanation["case_findings"]
    assert findings["source"] == "expert_reviewed"
    assert findings["reviewer"] == "홍길동 (영상의학과)"


def test_legacy_review_status_is_rejected(client, volume_manifest):
    explanation = {
        "case_facts": {"disease_name": "전정신경초종", "reference_region": "우측"},
        "review_status": "expert_reviewed",
    }
    summary = import_cases.import_manifest(volume_manifest(explanation=explanation))
    assert summary["failed"]
    assert "review_status" in summary["failed"][0][1]


# --------------------------------------------------------- 등록 후 채점 동작
def test_reference_mask_submission_scores_dice_one(client, volume_manifest, user_a):
    """기준 마스크를 그대로 제출하면 Dice=1.0 (채점 경로 sanity check)."""
    import_cases.import_manifest(volume_manifest())

    mask_path = import_cases.CASES_DIR / CASE_ID / "slices" / f"mask_{REPRESENTATIVE:03d}.png"
    payload = base64.b64encode(mask_path.read_bytes()).decode()

    res = user_a.post(
        f"/api/cases/{CASE_ID}/submit",
        json={"roi": {"type": "brush_mask", "mask_png_base64": payload}},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dice"] == 1.0
    assert body["iou"] == 1.0
    assert body["grade"] == "match"
    assert body["location_score"] == 100
    assert body["evaluation"]["method"] == "reference_mask"
    # 사실 블록은 항상, 문헌 블록은 질환 콘텐츠가 있을 때만, 소견은 아직 없음
    levels = body["explanation"]["content_levels"]
    assert levels[0] == "dataset_verified"
    assert "expert_reviewed" not in levels
    assert body["explanation"]["case_findings"] is None


def test_case_detail_exposes_representative_slice(client, volume_manifest, user_a):
    import_cases.import_manifest(volume_manifest())

    res = user_a.get(f"/api/cases/{CASE_ID}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["image_meta"]["slice_index"] == REPRESENTATIVE
    assert body["gradable"] is True
    assert body["image_url"].endswith(f"/slices/slice_{REPRESENTATIVE:03d}.png")
