"""
케이스 등록의 **멱등성과 부분 실패 대응**.

**왜 중요한가**
등록은 두 곳을 동시에 바꾼다: DB(cases/case_slices)와 파일(static/cases/).
둘이 어긋나면 조용히 깨진다:

  DB 에는 있는데 파일이 없다   -> 학습자가 빈 화면을 본다
  파일은 있는데 DB 에 없다     -> 디스크만 먹는 고아 파일 (다음 등록 때 헷갈린다)

24건을 한 번에 넣는 상황이라 **20번째에서 실패했을 때 앞 19건이 어떻게 되는지**가
실제로 중요해졌다.

**GT 를 고치는 테스트는 없다.** 등록은 GT 를 그대로 옮길 뿐이다.
"""
import json

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Case, CaseSlice
from scripts import import_cases

CASE_A = "IMP-TEST-A"
CASE_B = "IMP-TEST-B"


def _make_assets(base, case_id, *, slices=(33, 34, 35), representative=35):
    """실제 등록 흐름을 그대로 타도록 진짜 PNG 를 만든다."""
    case_dir = base / case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    for index in slices:
        img = np.zeros((64, 64), dtype=np.uint8)
        img[16:48, 16:48] = 180
        Image.fromarray(img, mode="L").save(case_dir / f"slice_{index:03d}.png")

        mask = np.zeros((64, 64), dtype=np.uint8)
        area = 0
        if index >= 34:  # 첫 slice 는 병변 없음
            mask[28:36, 28:36] = 255
            area = int((mask > 0).sum())
        Image.fromarray(mask, mode="L").save(case_dir / f"mask_{index:03d}.png")

        entries.append(
            {
                "slice_index": index,
                "image": f"{case_id}/slice_{index:03d}.png",
                "mask": f"{case_id}/mask_{index:03d}.png" if area else None,
                "lesion_area_px": area,
            }
        )

    return {
        "case_id": case_id,
        "body_part": "brain_mri",
        "disease": "vestibular_schwannoma",
        "volume_id": f"{case_id}/T1",
        "representative_slice": representative,
        "slice_index": representative,
        "total_slices": 120,
        "image": f"{case_id}/slice_{representative:03d}.png",
        "reference_mask": f"{case_id}/mask_{representative:03d}.png",
        "slices": entries,
        "explanation": {
            "case_facts": {
                "disease_name": "전정신경초종 (Vestibular Schwannoma)",
                "disease_code": "vestibular_schwannoma",
                "laterality": "right",
                "reference_region": "우측 소뇌교각 (데이터셋 전문가 GT 위치)",
            }
        },
    }


@pytest.fixture
def manifest_env(tmp_path, monkeypatch):
    """실제 static/ 을 건드리지 않도록 케이스 자산 폴더를 격리한다."""
    assets = tmp_path / "assets"
    assets.mkdir()
    cases = [_make_assets(assets, CASE_A), _make_assets(assets, CASE_B)]
    manifest = assets / "manifest.json"
    manifest.write_text(json.dumps({"cases": cases}, ensure_ascii=False), encoding="utf-8")

    served = tmp_path / "served" / "cases"
    monkeypatch.setattr(import_cases, "CASES_DIR", served)
    return {"manifest": manifest, "served": served}


@pytest.fixture(autouse=True)
def _clean_test_cases():
    """이 테스트가 만든 케이스만 정리한다 (다른 테스트의 케이스는 건드리지 않는다)."""
    yield
    with SessionLocal() as db:
        for case_id in (CASE_A, CASE_B):
            for slice_row in db.scalars(
                select(CaseSlice).where(CaseSlice.case_id == case_id)
            ).all():
                db.delete(slice_row)
            case = db.get(Case, case_id)
            if case is not None:
                db.delete(case)
        db.commit()


def _registered() -> set[str]:
    with SessionLocal() as db:
        return {
            c.case_id
            for c in db.scalars(select(Case).where(Case.case_id.in_([CASE_A, CASE_B])))
        }


def _served_dirs(served) -> set[str]:
    return {p.name for p in served.iterdir()} if served.exists() else set()


# ------------------------------------------------------------------ 기본 등록
def test_imports_both_cases(manifest_env):
    summary = import_cases.import_manifest(manifest_env["manifest"])
    assert summary["failed"] == [], summary["failed"]
    assert {c for c, _ in summary["registered"]} == {CASE_A, CASE_B}
    assert _registered() == {CASE_A, CASE_B}
    assert _served_dirs(manifest_env["served"]) == {CASE_A, CASE_B}


def test_db_and_files_agree(manifest_env):
    """DB 가 가리키는 파일이 실제로 있어야 한다 — 없으면 학습자가 빈 화면을 본다."""
    import_cases.import_manifest(manifest_env["manifest"])
    served = manifest_env["served"]

    with SessionLocal() as db:
        case = db.get(Case, CASE_A)
        slices = db.scalars(select(CaseSlice).where(CaseSlice.case_id == CASE_A)).all()

    prefix = import_cases.CASES_URL_PREFIX
    for url in [case.image_url, case.thumbnail_url, case.reference_mask_url]:
        assert url and url.startswith(prefix)
        relative = url[len(prefix) :].lstrip("/")
        assert (served / relative).exists(), f"DB 가 가리키는 파일이 없다: {url}"

    for row in slices:
        relative = row.image_url[len(prefix) :].lstrip("/")
        assert (served / relative).exists()


# ------------------------------------------------------------------ 멱등성
def test_rerun_without_replace_skips(manifest_env):
    import_cases.import_manifest(manifest_env["manifest"])
    again = import_cases.import_manifest(manifest_env["manifest"])

    assert again["registered"] == []
    assert {c for c, _ in again["skipped"]} == {CASE_A, CASE_B}


def test_replace_is_idempotent(manifest_env):
    """같은 manifest 로 --replace 를 두 번 돌려도 결과가 같아야 한다."""
    import_cases.import_manifest(manifest_env["manifest"])
    import_cases.import_manifest(manifest_env["manifest"], replace=True)

    with SessionLocal() as db:
        first = db.scalars(select(CaseSlice).where(CaseSlice.case_id == CASE_A)).all()
        first_state = sorted((s.slice_index, s.lesion_area_px, s.image_url) for s in first)

    import_cases.import_manifest(manifest_env["manifest"], replace=True)

    with SessionLocal() as db:
        second = db.scalars(select(CaseSlice).where(CaseSlice.case_id == CASE_A)).all()
        second_state = sorted((s.slice_index, s.lesion_area_px, s.image_url) for s in second)

    assert first_state == second_state
    assert len(second) == 3


def test_replace_removes_slices_that_disappeared(manifest_env, tmp_path):
    """slice 가 줄어든 manifest 로 다시 등록하면 예전 slice 가 남으면 안 된다.

    남으면 학습자가 병변이 없는 slice 를 병변 있는 것으로 본다.
    """
    import_cases.import_manifest(manifest_env["manifest"])

    assets = tmp_path / "assets"
    shrunk = [_make_assets(assets, CASE_A, slices=(34, 35), representative=35)]
    manifest = assets / "shrunk.json"
    manifest.write_text(json.dumps({"cases": shrunk}, ensure_ascii=False), encoding="utf-8")

    import_cases.import_manifest(manifest, replace=True)

    with SessionLocal() as db:
        rows = db.scalars(select(CaseSlice).where(CaseSlice.case_id == CASE_A)).all()
    assert sorted(r.slice_index for r in rows) == [34, 35]


def test_dry_run_changes_nothing(manifest_env):
    summary = import_cases.import_manifest(manifest_env["manifest"], dry_run=True)
    assert {c for c, _ in summary["registered"]} == {CASE_A, CASE_B}
    assert _registered() == set()
    assert _served_dirs(manifest_env["served"]) == set()


# ------------------------------------------------------- 부분 실패 (핵심)
def test_partial_failure_leaves_no_orphan_assets(manifest_env, monkeypatch):
    """**앞 케이스는 등록되고 뒤 케이스가 실패했을 때 상태가 어긋나면 안 된다.**

    DB 는 롤백됐는데 static 에 파일이 남으면, 다음 등록 때 "이미 있는 파일"로 보여
    무엇이 진짜인지 알 수 없게 된다.
    """
    original = import_cases._copy_assets
    calls = []

    def failing(info):
        calls.append(info["case_id"])
        if len(calls) == 2:  # 두 번째 케이스에서 디스크 오류
            raise OSError("디스크 오류 흉내")
        return original(info)

    monkeypatch.setattr(import_cases, "_copy_assets", failing)

    # 한 케이스가 실패해도 전체가 멈추지 않는다 (24건 중 1건 때문에 되돌리면 곤란하다)
    summary = import_cases.import_manifest(manifest_env["manifest"])

    registered = _registered()
    served = _served_dirs(manifest_env["served"])

    # 앞 케이스는 남고, 실패한 케이스는 **DB 와 파일 양쪽에서** 흔적이 없어야 한다
    assert registered == served, f"DB={registered} / 파일={served} 이 어긋난다"
    assert len(registered) == 1, f"앞 케이스가 살아 있어야 한다: {registered}"
    assert len(summary["failed"]) == 1
    assert "등록 실패" in summary["failed"][0][1]


def test_failure_during_replace_restores_previous_assets(manifest_env, monkeypatch):
    """**잘 돌던 케이스를 덮어쓰다 실패하면 원래대로 되돌아가야 한다.**

    반쯤 갈아엎힌 상태로 남으면 학습자가 깨진 케이스를 만난다.
    """
    import_cases.import_manifest(manifest_env["manifest"])
    served = manifest_env["served"]
    before = sorted(p.name for p in (served / CASE_A).rglob("*") if p.is_file())
    assert before, "첫 등록이 되어 있어야 한다"

    original = import_cases._copy_assets

    def failing(info):
        if info["case_id"] == CASE_A:
            # 자산을 일부 써놓고 터진다
            (import_cases.CASES_DIR / info["case_id"]).mkdir(parents=True, exist_ok=True)
            (import_cases.CASES_DIR / info["case_id"] / "half-written.png").write_bytes(b"x")
            raise OSError("덮어쓰기 도중 디스크 오류")
        return original(info)

    monkeypatch.setattr(import_cases, "_copy_assets", failing)
    summary = import_cases.import_manifest(manifest_env["manifest"], replace=True)

    after = sorted(p.name for p in (served / CASE_A).rglob("*") if p.is_file())
    assert after == before, "실패했는데 원래 자산이 바뀌었다"
    assert not (served / CASE_A / "half-written.png").exists()
    assert CASE_A in [c for c, _ in summary["failed"]]
    # 케이스는 여전히 등록돼 있고 정상이어야 한다
    assert CASE_A in _registered()


def test_no_stash_folders_are_left_behind(manifest_env):
    """되돌리기용 임시 폴더가 남으면 다음 등록 때 헷갈린다."""
    import_cases.import_manifest(manifest_env["manifest"])
    import_cases.import_manifest(manifest_env["manifest"], replace=True)

    leftovers = [p.name for p in manifest_env["served"].iterdir() if p.name.startswith(".stash-")]
    assert leftovers == [], f"임시 폴더가 남았다: {leftovers}"


def test_validation_failure_does_not_abort_other_cases(manifest_env, tmp_path):
    """한 케이스가 형식 오류여도 나머지는 들어가야 한다 (24건 중 1건 때문에 멈추면 곤란하다)."""
    assets = tmp_path / "assets"
    good = _make_assets(assets, CASE_A)
    broken = _make_assets(assets, CASE_B)
    del broken["explanation"]  # 필수 항목 누락

    manifest = assets / "mixed.json"
    manifest.write_text(json.dumps({"cases": [broken, good]}, ensure_ascii=False), encoding="utf-8")

    summary = import_cases.import_manifest(manifest)

    assert {c for c, _ in summary["registered"]} == {CASE_A}
    assert [c for c, _ in summary["failed"]] == [CASE_B]
    assert _registered() == {CASE_A}


def test_missing_asset_file_is_reported_not_crashed(manifest_env, tmp_path):
    assets = tmp_path / "assets"
    entry = _make_assets(assets, CASE_A)
    (assets / CASE_A / "slice_035.png").unlink()

    manifest = assets / "missing.json"
    manifest.write_text(json.dumps({"cases": [entry]}, ensure_ascii=False), encoding="utf-8")

    summary = import_cases.import_manifest(manifest)
    assert [c for c, _ in summary["failed"]] == [CASE_A]
    assert _registered() == set()


# --------------------------------------------------- 의료 내용 안전장치
def test_findings_status_is_not_approved_without_findings(manifest_env):
    """manifest 로 검토 상태만 approved 로 올리는 경로를 만들지 않는다."""
    import_cases.import_manifest(manifest_env["manifest"])
    with SessionLocal() as db:
        case = db.get(Case, CASE_A)
    assert case.findings_status == "needs_expert_review"
    assert (case.explanation or {}).get("case_findings") is None
