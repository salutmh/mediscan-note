"""
케이스 후보 기술 검수 워크플로.

**이 테스트가 지키는 가장 중요한 것: 세 검수 상태가 서로 섞이지 않는다.**

  technical_review_status   export 파이프라인이 제대로 돌았는가
  expert_review_status      의학적으로 옳은가 (전문가만)
  activation_status         학습자에게 보이는가

기술 검수를 통과시켰다고 전문가 검수가 진행되거나 케이스가 활성화되면,
검수되지 않은 GT 가 학습자의 채점 기준이 된다. 되돌릴 방법은 케이스를 내리는 것뿐이고
그때까지 쌓인 제출 이력은 의미가 없어진다.
"""
import json

import pytest

from app import review_candidates, review_store
from app.review_store import (
    ACTIVATION_CANDIDATE,
    EXPERT_PENDING,
    TECH_HOLD,
    TECH_PASS,
    TECH_REJECT,
    TECH_UNREVIEWED,
)

CASE_A = "VS-SEG-900"
CASE_B = "VS-SEG-901"


# ------------------------------------------------------------------ 픽스처
@pytest.fixture
def review_env(tmp_path, monkeypatch):
    """export/review 폴더를 흉내 낸다 (실제 의료영상 없이)."""
    from PIL import Image

    export_root = tmp_path / "export"
    review_root = tmp_path / "review"
    screening = tmp_path / "screening.json"

    sheets = []
    for case_id, voxels, lat, bucket in [
        (CASE_A, 4200, "left", "medium"),
        (CASE_B, 11000, "right", "large"),
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
                    "representative_area_px": 800,
                    "lesion_slice_count": 9,
                    "lesion_slice_min": 36,
                    "lesion_slice_max": 44,
                    "chosen_roi": "TV",
                    "roi_names": ["TV", "Cochlea"],
                    "roi_selected_by": "keyword",
                    "rtstruct": "abc.dcm",
                    "t1_description": "t1_test",
                    "t1_slice_files": 120,
                    "geometry": {"pixel_spacing": [0.4, 0.4], "image_orientation_patient": [1, 0, 0, 0, 1, 0]},
                    "laterality": {
                        "laterality": lat,
                        "basis": "DICOM ImageOrientationPatient + GT 마스크 열 중심",
                        "agree": True,
                        "laterality_by_fov_center": lat,
                        "laterality_by_head_center": lat,
                        "lesion_col_center": 300.0,
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        sheet_dir = review_root / case_id
        sheet_dir.mkdir(parents=True)
        Image.new("RGB", (40, 20), (20, 20, 20)).save(sheet_dir / f"{case_id}_review.png")
        sheets.append(
            {
                "case_id": case_id,
                "sheet": f"{case_id}_review.png",
                "display_window": [0.0, 1000.0],
                "lesion_bbox_rowcol": [200, 250, 240, 290],
            }
        )

        screening_cases = {"case_id": case_id, "_stratum": bucket}
        del screening_cases

    (review_root / "review_summary.json").write_text(
        json.dumps(sheets, ensure_ascii=False), encoding="utf-8"
    )
    screening.write_text(
        json.dumps(
            {
                "cases": [{"case_id": CASE_A}, {"case_id": CASE_B}],
                "recommended_detail": [
                    {"case_id": CASE_A, "_stratum": "medium"},
                    {"case_id": CASE_B, "_stratum": "large"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("MEDISCAN_REVIEW_EXPORT_ROOT", str(export_root))
    monkeypatch.setenv("MEDISCAN_REVIEW_ROOT", str(review_root))
    monkeypatch.setenv("MEDISCAN_REVIEW_SCREENING", str(screening))
    return {"export": export_root, "review": review_root}


# ------------------------------------------------------------------ 권한
def test_requires_admin(client, user_a, review_env):
    """검수 시트는 실제 환자 영상에서 파생된 그림이다."""
    assert client.get("/api/admin/review/candidates").status_code == 401
    assert user_a.get("/api/admin/review/candidates").status_code == 403
    assert user_a.get(f"/api/admin/review/candidates/{CASE_A}/sheet").status_code == 403
    assert (
        user_a.post(f"/api/admin/review/candidates/{CASE_A}", json={"technical_review_status": "tech_pass"}).status_code
        != 200
    )


def test_sheet_requires_admin_too(client, review_env):
    assert client.get(f"/api/admin/review/candidates/{CASE_A}/sheet").status_code == 401


# ------------------------------------------------------------------ 목록
def test_lists_candidates_with_objective_values(admin_session, review_env):
    body = admin_session.get("/api/admin/review/candidates").json()
    ids = [c["case_id"] for c in body["candidates"]]
    assert ids == [CASE_A, CASE_B]

    first = body["candidates"][0]
    assert first["gt_voxels"] == 4200
    assert first["laterality"] == "left"
    assert first["lesion_slice_count"] == 9
    assert first["size_bucket"] == "medium"
    # 크기 계층이 난이도로 읽히지 않게 근거를 함께 내려보낸다
    assert "난이도가 아닙니다" in first["size_bucket_basis"]
    assert first["provenance"]["roi_name"] == "TV"
    assert first["dataset"] == "VS-SEG"


def test_response_states_that_this_is_not_medical_review(admin_session, review_env):
    """화면이 문구를 지어내지 않도록 서버가 내려보낸다."""
    body = admin_session.get("/api/admin/review/candidates").json()
    assert "기술 검수" in body["notice"]
    assert "의학적으로 옳다거나" in body["notice"]


def test_missing_export_folder_is_not_an_error(admin_session, monkeypatch, tmp_path):
    """배포 서버에는 data/ 작업 폴더가 없는 것이 정상이다."""
    monkeypatch.setenv("MEDISCAN_REVIEW_EXPORT_ROOT", str(tmp_path / "nope"))
    monkeypatch.setenv("MEDISCAN_REVIEW_ROOT", str(tmp_path / "nope2"))

    res = admin_session.get("/api/admin/review/candidates")
    assert res.status_code == 200
    body = res.json()
    assert body["candidates"] == []
    assert body["roots"]["available"] is False


# ------------------------------------------------------------------ 시트
def test_serves_the_review_sheet(admin_session, review_env):
    res = admin_session.get(f"/api/admin/review/candidates/{CASE_A}/sheet")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    # 공유 캐시에 남기지 않는다 (의료영상 파생물)
    assert "private" in res.headers.get("cache-control", "")


def test_unknown_case_sheet_is_404(admin_session, review_env):
    assert admin_session.get("/api/admin/review/candidates/NOPE/sheet").status_code == 404


def test_sheet_path_cannot_escape_review_root(review_env, tmp_path):
    """경로 조작으로 review_root 밖 파일을 읽을 수 없어야 한다."""
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"x")

    # review_summary.json 이 바깥을 가리키도록 조작한다
    summary = review_env["review"] / "review_summary.json"
    summary.write_text(
        json.dumps([{"case_id": CASE_A, "sheet": "../../secret.png"}], ensure_ascii=False),
        encoding="utf-8",
    )
    assert review_candidates.sheet_path(CASE_A, review_env["review"]) is None


# ------------------------------------------------- 상태 분리 (가장 중요)
def test_new_candidate_starts_unreviewed_and_pending(admin_session, review_env):
    body = admin_session.get("/api/admin/review/candidates").json()
    review = body["candidates"][0]["review"]
    assert review["technical_review_status"] == TECH_UNREVIEWED
    assert review["expert_review_status"] == EXPERT_PENDING
    assert review["activation_status"] == ACTIVATION_CANDIDATE


def test_tech_pass_does_not_touch_expert_or_activation(admin_session, review_env):
    """**이 테스트가 무너지면 검수되지 않은 GT 가 서비스에 들어갈 수 있다.**"""
    res = admin_session.put(
        f"/api/admin/review/candidates/{CASE_A}",
        json={"technical_review_status": TECH_PASS, "note": "export 문제 없어 보임"},
    )
    assert res.status_code == 200
    entry = res.json()

    assert entry["technical_review_status"] == TECH_PASS
    # 기술 통과가 의학적 검수나 활성화로 번지지 않는다
    assert entry["expert_review_status"] == EXPERT_PENDING
    assert entry["activation_status"] == ACTIVATION_CANDIDATE


def test_cannot_set_expert_or_activation_through_this_api(admin_session, review_env):
    """기술 검수 화면에서 실수로 바꿀 수 있으면 안 된다."""
    admin_session.put(
        f"/api/admin/review/candidates/{CASE_A}",
        json={
            "technical_review_status": TECH_PASS,
            "expert_review_status": "approved",   # 무시되어야 한다
            "activation_status": "active",        # 무시되어야 한다
        },
    )
    entry = admin_session.get(f"/api/admin/review/candidates/{CASE_A}").json()["review"]
    assert entry["expert_review_status"] == EXPERT_PENDING
    assert entry["activation_status"] == ACTIVATION_CANDIDATE


@pytest.mark.parametrize("status", [TECH_PASS, TECH_HOLD, TECH_REJECT, TECH_UNREVIEWED])
def test_all_technical_statuses_are_accepted(admin_session, review_env, status):
    res = admin_session.put(
        f"/api/admin/review/candidates/{CASE_A}", json={"technical_review_status": status}
    )
    assert res.status_code == 200
    assert res.json()["technical_review_status"] == status


def test_unknown_status_is_rejected(admin_session, review_env):
    res = admin_session.put(
        f"/api/admin/review/candidates/{CASE_A}", json={"technical_review_status": "approved"}
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "INVALID_REVIEW_STATUS"


# ------------------------------------------------------------------ 지속성
def test_review_survives_reload(admin_session, review_env):
    """사용자가 화면을 새로 열어도 이전 판단이 유지되어야 한다."""
    admin_session.put(
        f"/api/admin/review/candidates/{CASE_B}",
        json={"technical_review_status": TECH_HOLD, "note": "이미지 대비가 낮아 확인 어려움"},
    )

    body = admin_session.get("/api/admin/review/candidates").json()
    entry = next(c["review"] for c in body["candidates"] if c["case_id"] == CASE_B)
    assert entry["technical_review_status"] == TECH_HOLD
    assert entry["note"] == "이미지 대비가 낮아 확인 어려움"
    assert entry["reviewed_at"]
    assert entry["reviewer"]


def test_results_file_is_written_where_documented(admin_session, review_env):
    admin_session.put(
        f"/api/admin/review/candidates/{CASE_A}", json={"technical_review_status": TECH_PASS}
    )
    path = review_env["review"] / "review_results.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["cases"][CASE_A]["technical_review_status"] == TECH_PASS


def test_broken_results_file_is_not_silently_overwritten(admin_session, review_env):
    """깨진 파일을 빈 값으로 덮으면 그때까지의 검수가 사라진다."""
    (review_env["review"] / "review_results.json").write_text("{ not json", encoding="utf-8")

    res = admin_session.get("/api/admin/review/candidates")
    assert res.status_code == 500
    assert res.json()["detail"]["code"] == "REVIEW_STORE_UNREADABLE"
    # 파일은 그대로 남아 있어야 한다
    assert (review_env["review"] / "review_results.json").read_text(encoding="utf-8").startswith("{ not")


# ------------------------------------------------------------------ 현황
def test_summary_counts_technical_and_expert_separately(admin_session, review_env):
    admin_session.put(
        f"/api/admin/review/candidates/{CASE_A}", json={"technical_review_status": TECH_PASS}
    )

    counts = admin_session.get("/api/admin/review/summary").json()["counts"]
    assert counts["total"] == 2
    assert counts["technical"][TECH_PASS] == 1
    assert counts["technical"][TECH_UNREVIEWED] == 1
    # 기술 통과했지만 전문가 검수가 남은 수 — 이 값이 0 이 아니면 활성화하면 안 된다
    assert counts["awaiting_expert_review"] == 1
    assert counts["expert"][EXPERT_PENDING] == 2


def test_summary_states_the_pipeline_order(admin_session, review_env):
    body = admin_session.get("/api/admin/review/summary").json()
    assert body["pipeline"] == [
        "candidate",
        "technical reviewed",
        "expert reviewed",
        "inactive ready",
        "active",
    ]
    assert "전문가 검수가 끝나지 않으면 활성화되지 않습니다" in body["notice"]


# ------------------------------------------------------------------ 저장 안전성
def test_save_is_atomic_and_leaves_no_temp_files(review_env):
    review_store.set_technical_status(
        review_env["review"], CASE_A, status=TECH_PASS, note="ok", reviewer="tester"
    )
    leftovers = list(review_env["review"].glob(".review_*.tmp"))
    assert leftovers == [], f"임시 파일이 남았다: {leftovers}"
