"""
검수 결과 패키지 생성.

**가장 중요한 것: 이 스크립트는 케이스를 등록하거나 활성화하지 않는다.**

`manifest_candidate.json` 은 이름 그대로 후보다. 전문가 검수가 끝나지 않은 케이스가
여기 들어 있다고 해서 활성화되면, 검수되지 않은 GT 가 학습자의 채점 기준이 된다.
그래서 파일 안에 차단 사유를 박아두고, 이 테스트가 그것을 고정한다.
"""
import json

import pytest

from app import review_store
from app.review_store import EXPERT_APPROVED, EXPERT_PENDING, TECH_HOLD, TECH_PASS, TECH_REJECT
from scripts import review_package

CASE_A = "VS-SEG-800"
CASE_B = "VS-SEG-801"
CASE_C = "VS-SEG-802"


@pytest.fixture
def package_env(tmp_path):
    """export 3건 + 검수 시트 메타 (실제 의료영상 없이)."""
    export_root = tmp_path / "export"
    review_root = tmp_path / "review"
    review_root.mkdir()
    screening = tmp_path / "screening.json"

    for case_id, voxels, lat, bucket in [
        (CASE_A, 4000, "left", "medium"),
        (CASE_B, 900, "right", "small"),
        (CASE_C, 12000, "left", "large"),
    ]:
        case_dir = export_root / case_id
        case_dir.mkdir(parents=True)
        (case_dir / "export_meta.json").write_text(
            json.dumps(
                {
                    "case_id": case_id,
                    "gt_voxels": voxels,
                    "shape": [512, 512, 120],
                    "representative_slice": 40,
                    "representative_area_px": 700,
                    "lesion_slice_count": 8,
                    "lesion_slice_min": 36,
                    "lesion_slice_max": 43,
                    "chosen_roi": "TV",
                    "roi_names": ["TV"],
                    "roi_selected_by": "keyword",
                    "geometry": {},
                    "laterality": {"laterality": lat, "agree": True, "basis": "DICOM"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        del bucket

    screening.write_text(
        json.dumps(
            {
                "cases": [{"case_id": CASE_A}, {"case_id": CASE_B}, {"case_id": CASE_C}],
                "recommended_detail": [
                    {"case_id": CASE_A, "_stratum": "medium"},
                    {"case_id": CASE_B, "_stratum": "small"},
                    {"case_id": CASE_C, "_stratum": "large"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {"export": export_root, "review": review_root, "screening": screening}


def _collect(env):
    return review_package.collect(env["export"], env["review"], env["screening"])


def _decide(env, case_id, status, note=""):
    review_store.set_technical_status(
        env["review"], case_id, status=status, note=note, reviewer="tester"
    )


# ------------------------------------------------------------------ 요약
def test_summary_counts_each_status(package_env):
    _decide(package_env, CASE_A, TECH_PASS)
    _decide(package_env, CASE_B, TECH_HOLD, "이미지 대비가 낮아 확인 어려움")
    _decide(package_env, CASE_C, TECH_REJECT)

    summary = review_package.build_summary(_collect(package_env))
    assert summary["counts"]["total"] == 3
    assert summary["by_technical_status"][TECH_PASS] == [CASE_A]
    assert summary["by_technical_status"][TECH_HOLD] == [CASE_B]
    assert summary["by_technical_status"][TECH_REJECT] == [CASE_C]


def test_summary_lists_expert_pending_separately(package_env):
    _decide(package_env, CASE_A, TECH_PASS)
    summary = review_package.build_summary(_collect(package_env))
    # 기술 통과와 무관하게 셋 다 전문가 검수 대기다
    assert set(summary["expert_review_pending"]) == {CASE_A, CASE_B, CASE_C}


def test_summary_states_what_technical_status_means(package_env):
    summary = review_package.build_summary(_collect(package_env))
    assert "의학적 판단도, 서비스 활성화 승인도 아닙니다" in summary["note"]
    assert summary["pipeline"][0] == "candidate"
    assert summary["pipeline"][-1] == "active"


def test_summary_keeps_the_technical_note(package_env):
    _decide(package_env, CASE_B, TECH_HOLD, "overlay 위치 재확인")
    summary = review_package.build_summary(_collect(package_env))
    row = next(c for c in summary["cases"] if c["case_id"] == CASE_B)
    assert row["note"] == "overlay 위치 재확인"
    assert row["reviewer"] == "tester"
    assert row["reviewed_at"]


# ------------------------------------------------- manifest 후보 (핵심)
def test_manifest_contains_only_tech_passed_cases(package_env):
    _decide(package_env, CASE_A, TECH_PASS)
    _decide(package_env, CASE_B, TECH_HOLD)
    _decide(package_env, CASE_C, TECH_REJECT)

    manifest = review_package.build_manifest_candidate(_collect(package_env), package_env["export"])
    assert [c["case_id"] for c in manifest["cases"]] == [CASE_A]


def test_manifest_never_marks_a_case_active(package_env):
    """**이 테스트가 무너지면 검수되지 않은 GT 가 서비스에 들어갈 수 있다.**"""
    _decide(package_env, CASE_A, TECH_PASS)
    manifest = review_package.build_manifest_candidate(_collect(package_env), package_env["export"])

    entry = manifest["cases"][0]
    assert entry["intended_activation"] == review_store.ACTIVATION_INACTIVE_READY
    assert entry["expert_review_status"] == EXPERT_PENDING
    assert manifest["activation_blocked_reason"] is not None
    assert "전문가 검수 미완료" in manifest["activation_blocked_reason"]


def test_manifest_does_not_invent_difficulty_or_findings(package_env):
    """난이도와 소견은 전문가 몫이다. 비워 둔다."""
    _decide(package_env, CASE_A, TECH_PASS)
    manifest = review_package.build_manifest_candidate(_collect(package_env), package_env["export"])

    entry = manifest["cases"][0]
    assert entry["difficulty"] is None
    assert entry["case_findings"] is None


def test_manifest_says_it_is_not_a_registration_manifest(package_env):
    _decide(package_env, CASE_A, TECH_PASS)
    manifest = review_package.build_manifest_candidate(_collect(package_env), package_env["export"])
    assert manifest["kind"] == "manifest_candidate"
    assert "등록 manifest 가 아닙니다" in manifest["warning"]
    assert any("build_vs_seg_case_assets" in step for step in manifest["next_steps"])


def test_blocked_reason_clears_only_when_expert_approves(package_env):
    """전문가 승인이 나야 차단 사유가 사라진다."""
    _decide(package_env, CASE_A, TECH_PASS)

    # 전문가 승인을 직접 기록한다 (이 화면·API 로는 바꿀 수 없는 값이다)
    data = review_store.load(package_env["review"])
    data["cases"][CASE_A]["expert_review_status"] = EXPERT_APPROVED
    review_store.save(package_env["review"], data)

    manifest = review_package.build_manifest_candidate(_collect(package_env), package_env["export"])
    assert manifest["activation_blocked_reason"] is None
    # 그래도 등록은 비활성으로 들어간다
    assert manifest["cases"][0]["intended_activation"] == review_store.ACTIVATION_INACTIVE_READY


def test_empty_manifest_when_nothing_passed(package_env):
    manifest = review_package.build_manifest_candidate(_collect(package_env), package_env["export"])
    assert manifest["cases"] == []
    assert manifest["activation_blocked_reason"] is None


# ------------------------------------------------------------------ 파일 출력
def test_writes_all_three_files(package_env, tmp_path, monkeypatch):
    _decide(package_env, CASE_A, TECH_PASS)
    out = tmp_path / "package"

    monkeypatch.setattr(
        "sys.argv",
        [
            "review_package",
            "--review-root", str(package_env["review"]),
            "--export-root", str(package_env["export"]),
            "--screening", str(package_env["screening"]),
            "--out", str(out),
        ],
    )
    assert review_package.main() == 0

    assert (out / "review_summary.json").exists()
    assert (out / "review_summary.csv").exists()
    assert (out / "manifest_candidate.json").exists()

    csv_text = (out / "review_summary.csv").read_text(encoding="utf-8-sig")
    assert "technical_review_status" in csv_text
    assert "expert_review_status" in csv_text
    assert CASE_A in csv_text
