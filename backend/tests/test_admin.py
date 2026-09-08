"""
운영자 CMS (Phase 5 / RELEASE_READINESS H3).

가장 중요한 것은 **권한 격리**다. 콘텐츠를 바꿀 수 있는 API 가 일반 사용자에게 열리면
학습 기준(GT 기반 채점)의 신뢰가 통째로 무너진다. 그래서 모든 admin 엔드포인트에 대해
비로그인/일반 사용자 접근을 하나씩 확인한다.

그다음으로 확인하는 것:
  - 상태만 올려서 "검토된 것처럼" 보이게 하는 경로가 없는가
  - 전문가 GT(기준 마스크)를 화면에서 고치는 경로가 없는가
  - 비활성 케이스가 학습자에게서 실제로 숨겨지는가 (숨김이지 삭제가 아니다)
"""
import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Case, User
from tests.conftest import CASE_ID

FINDINGS_PAYLOAD = {
    "findings": "전문가가 작성한 소견 본문",
    "reviewer": "검토자A",
    "reviewed_at": "2026-09-08",
    "learning_points": ["확인 포인트", "  "],
    "lesion_location": " 위치 설명 ",
}


@pytest.fixture
def admin(make_user):
    """일반 사용자를 만든 뒤 DB 에서 운영자로 승격한다 (웹 경로로는 승격할 수 없다)."""
    session = make_user("운영자")
    with SessionLocal() as db:
        user = db.get(User, session.user_id)
        user.is_admin = True
        db.commit()
    return session


@pytest.fixture(autouse=True)
def _restore_case_state():
    """테스트가 케이스 운영 필드를 바꾸므로 원상복구한다 (케이스는 공용 시드 데이터)."""
    yield
    with SessionLocal() as db:
        for case in db.scalars(select(Case)).all():
            case.is_active = True
            case.difficulty = None
            case.findings_status = "needs_expert_review"
            explanation = dict(case.explanation or {})
            if explanation.get("case_findings") is not None:
                explanation["case_findings"] = None
                case.explanation = explanation
        db.commit()


ADMIN_ENDPOINTS = [
    ("GET", "/api/admin/cases", None),
    ("GET", f"/api/admin/cases/{CASE_ID}", None),
    ("PATCH", f"/api/admin/cases/{CASE_ID}", {"is_active": False}),
    ("PUT", f"/api/admin/cases/{CASE_ID}/findings", FINDINGS_PAYLOAD),
    ("DELETE", f"/api/admin/cases/{CASE_ID}/findings", None),
    ("GET", "/api/admin/learning-summary", None),
]


# --------------------------------------------------------------- 권한 격리 (핵심)
@pytest.mark.parametrize("method,path,body", ADMIN_ENDPOINTS)
def test_admin_endpoints_require_authentication(client, method, path, body):
    res = client.request(method, path, json=body)
    assert res.status_code == 401, f"{method} {path} 가 비로그인에 열려 있다"


@pytest.mark.parametrize("method,path,body", ADMIN_ENDPOINTS)
def test_admin_endpoints_reject_normal_users(user_a, method, path, body):
    """로그인은 했지만 권한이 없는 경우 — 401 이 아니라 403 이어야 한다."""
    res = user_a._client.request(method, path, json=body, headers=user_a.headers)
    assert res.status_code == 403, f"{method} {path} 가 일반 사용자에게 열려 있다"
    assert res.json()["detail"]["code"] == "ADMIN_REQUIRED"


def test_admin_flag_cannot_be_set_through_signup(client):
    """가입 요청에 is_admin 을 끼워 넣어도 승격되지 않아야 한다."""
    from tests.conftest import REQUIRED_CONSENTS

    res = client.post(
        "/api/auth/signup",
        json={
            "email": "sneaky@example.com",
            "password": "pw12345678",
            "nickname": "침입",
            "is_admin": True,
            "consents": dict(REQUIRED_CONSENTS),
        },
    )
    assert res.status_code == 200
    with SessionLocal() as db:
        assert db.get(User, res.json()["user_id"]).is_admin is False


def test_revoking_admin_takes_effect_immediately(admin):
    """권한을 회수하면 기존 토큰으로도 더는 들어올 수 없어야 한다.

    (관리자 여부를 토큰에 담았다면 만료까지 남아 있었을 것이다 — 그래서 DB 만 본다.)
    """
    assert admin.get("/api/admin/cases").status_code == 200

    with SessionLocal() as db:
        db.get(User, admin.user_id).is_admin = False
        db.commit()

    assert admin.get("/api/admin/cases").status_code == 403


# ------------------------------------------------------------------ 목록·상세
def test_admin_list_shows_operational_metadata(admin):
    body = admin.get("/api/admin/cases").json()
    assert body["cases"], "케이스가 없다"

    case = body["cases"][0]
    for field in ("case_id", "is_active", "difficulty", "gradable",
                  "case_findings_status", "has_case_findings", "submission_count"):
        assert field in case, f"운영 필드 누락: {field}"


def test_admin_list_includes_inactive_by_default(admin):
    """숨긴 케이스를 다시 찾을 수 없으면 되돌릴 수 없다."""
    admin._client.request(
        "PATCH", f"/api/admin/cases/{CASE_ID}", json={"is_active": False}, headers=admin.headers
    )
    ids = [c["case_id"] for c in admin.get("/api/admin/cases").json()["cases"]]
    assert CASE_ID in ids

    visible = admin.get("/api/admin/cases?include_inactive=false").json()["cases"]
    assert CASE_ID not in [c["case_id"] for c in visible]


# ------------------------------------------------------- 비활성 = 숨김 (삭제 아님)
def test_inactive_case_is_hidden_from_learners(admin, user_a, roi_mismatch):
    user_a.submit(roi_mismatch)  # 이력을 먼저 만들어 둔다

    admin._client.request(
        "PATCH", f"/api/admin/cases/{CASE_ID}", json={"is_active": False}, headers=admin.headers
    )

    ids = [c["case_id"] for c in user_a.get("/api/cases").json()["cases"]]
    assert CASE_ID not in ids
    assert user_a.get(f"/api/cases/{CASE_ID}").status_code == 404
    assert user_a.submit(roi_mismatch).status_code == 404


def test_inactive_case_keeps_existing_submissions(admin, user_a, roi_mismatch):
    """숨김은 삭제가 아니다 — 이미 쌓인 학습 이력이 사라지면 안 된다."""
    user_a.submit(roi_mismatch)
    from app.models import Submission

    with SessionLocal() as db:
        before = len(db.scalars(select(Submission).where(Submission.user_id == user_a.user_id)).all())

    admin._client.request(
        "PATCH", f"/api/admin/cases/{CASE_ID}", json={"is_active": False}, headers=admin.headers
    )

    with SessionLocal() as db:
        after = len(db.scalars(select(Submission).where(Submission.user_id == user_a.user_id)).all())
    assert after == before > 0


# --------------------------------------------------------------- 메타데이터 수정
def test_difficulty_can_be_set_and_cleared(admin):
    res = admin._client.request(
        "PATCH", f"/api/admin/cases/{CASE_ID}", json={"difficulty": "hard"}, headers=admin.headers
    )
    assert res.status_code == 200
    assert res.json()["difficulty"] == "hard"

    res = admin._client.request(
        "PATCH", f"/api/admin/cases/{CASE_ID}", json={"difficulty": ""}, headers=admin.headers
    )
    assert res.json()["difficulty"] is None  # 미지정으로 되돌릴 수 있다


def test_difficulty_reaches_learners(admin, user_a):
    """반쪽 기능 방지: 운영자가 설정한 난이도가 학습자 화면까지 도달해야 한다.

    설정은 되는데 아무 데도 안 쓰이면 운영자가 헛일을 하게 된다.
    """
    admin._client.request(
        "PATCH", f"/api/admin/cases/{CASE_ID}", json={"difficulty": "hard"}, headers=admin.headers
    )

    listed = next(
        c for c in user_a.get("/api/cases").json()["cases"] if c["case_id"] == CASE_ID
    )
    assert listed["difficulty"] == "hard"
    assert user_a.get(f"/api/cases/{CASE_ID}").json()["difficulty"] == "hard"


def test_unset_difficulty_is_null_not_guessed(user_a):
    """지정하지 않은 난이도를 추측해서 채우지 않는다 (전문가 검토 대상)."""
    listed = next(
        c for c in user_a.get("/api/cases").json()["cases"] if c["case_id"] == CASE_ID
    )
    assert listed["difficulty"] is None


def test_invalid_difficulty_is_rejected(admin):
    res = admin._client.request(
        "PATCH", f"/api/admin/cases/{CASE_ID}", json={"difficulty": "매우어려움"}, headers=admin.headers
    )
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "INVALID_DIFFICULTY"


def test_empty_patch_is_rejected(admin):
    res = admin._client.request("PATCH", f"/api/admin/cases/{CASE_ID}", json={}, headers=admin.headers)
    assert res.status_code == 400


def test_unknown_case_returns_404(admin):
    assert admin.get("/api/admin/cases/NOT-A-CASE").status_code == 404


# ------------------------------------- 상태만 올려 '검토된 것처럼' 만들 수 없다 (핵심)
def test_cannot_mark_approved_without_findings(admin):
    res = admin._client.request(
        "PATCH",
        f"/api/admin/cases/{CASE_ID}",
        json={"findings_status": "approved"},
        headers=admin.headers,
    )
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "FINDINGS_REQUIRED"


def test_in_review_status_is_allowed_without_findings(admin):
    """'검토 중'은 내용이 없어도 사실일 수 있다."""
    res = admin._client.request(
        "PATCH",
        f"/api/admin/cases/{CASE_ID}",
        json={"findings_status": "in_review"},
        headers=admin.headers,
    )
    assert res.status_code == 200
    assert res.json()["case_findings_status"] == "in_review"


def test_invalid_findings_status_is_rejected(admin):
    res = admin._client.request(
        "PATCH", f"/api/admin/cases/{CASE_ID}", json={"findings_status": "완료"}, headers=admin.headers
    )
    assert res.status_code == 422


# ------------------------------------------------------------------ 전문가 소견
def test_findings_can_be_registered_and_appear_to_learners(admin, user_a, roi_mismatch):
    res = admin._client.request(
        "PUT", f"/api/admin/cases/{CASE_ID}/findings", json=FINDINGS_PAYLOAD, headers=admin.headers
    )
    assert res.status_code == 200, res.text

    explanation = res.json()["explanation"]
    assert explanation["case_findings"]["findings"] == "전문가가 작성한 소견 본문"
    assert explanation["case_findings"]["reviewer"] == "검토자A"
    assert explanation["case_findings"]["learning_points"] == ["확인 포인트"]  # 빈 항목은 버린다
    assert explanation["case_findings"]["lesion_location"] == "위치 설명"
    assert explanation["case_findings_status"] == "approved"
    assert "expert_reviewed" in explanation["content_levels"]

    # 학습자 응답에도 실제로 반영된다
    learner = user_a.submit(roi_mismatch).json()["explanation"]
    assert learner["case_findings"]["findings"] == "전문가가 작성한 소견 본문"


def test_findings_require_reviewer_metadata(admin):
    """누가 언제 본 내용인지 없는 소견은 등록되지 않는다."""
    for missing in ("reviewer", "reviewed_at"):
        payload = {k: v for k, v in FINDINGS_PAYLOAD.items() if k != missing}
        res = admin._client.request(
            "PUT", f"/api/admin/cases/{CASE_ID}/findings", json=payload, headers=admin.headers
        )
        assert res.status_code == 422, f"{missing} 없이 등록됐다"


def test_findings_reject_blank_and_bad_date(admin):
    blank = admin._client.request(
        "PUT",
        f"/api/admin/cases/{CASE_ID}/findings",
        json={**FINDINGS_PAYLOAD, "findings": "   "},
        headers=admin.headers,
    )
    assert blank.status_code == 422

    bad_date = admin._client.request(
        "PUT",
        f"/api/admin/cases/{CASE_ID}/findings",
        json={**FINDINGS_PAYLOAD, "reviewed_at": "2026년 9월 8일"},
        headers=admin.headers,
    )
    assert bad_date.status_code == 422


def test_findings_source_is_server_controlled(admin):
    """입력으로 source 를 속일 수 없어야 한다."""
    res = admin._client.request(
        "PUT",
        f"/api/admin/cases/{CASE_ID}/findings",
        json={**FINDINGS_PAYLOAD, "source": "dataset_verified"},
        headers=admin.headers,
    )
    assert res.json()["explanation"]["case_findings"]["source"] == "expert_reviewed"


def test_findings_can_be_withdrawn(admin):
    admin._client.request(
        "PUT", f"/api/admin/cases/{CASE_ID}/findings", json=FINDINGS_PAYLOAD, headers=admin.headers
    )
    res = admin._client.request(
        "DELETE", f"/api/admin/cases/{CASE_ID}/findings", headers=admin.headers
    )
    assert res.status_code == 200

    explanation = res.json()["explanation"]
    assert explanation["case_findings"] is None
    assert explanation["case_findings_status"] == "needs_expert_review"
    assert "expert_reviewed" not in explanation["content_levels"]


def test_withdrawing_absent_findings_returns_404(admin):
    res = admin._client.request(
        "DELETE", f"/api/admin/cases/{CASE_ID}/findings", headers=admin.headers
    )
    assert res.status_code == 404


def test_findings_do_not_touch_case_facts(admin):
    """소견을 등록해도 데이터에서 계산된 사실(case_facts)은 그대로여야 한다."""
    before = admin.get(f"/api/admin/cases/{CASE_ID}").json()["explanation"]["case_facts"]
    admin._client.request(
        "PUT", f"/api/admin/cases/{CASE_ID}/findings", json=FINDINGS_PAYLOAD, headers=admin.headers
    )
    after = admin.get(f"/api/admin/cases/{CASE_ID}").json()["explanation"]["case_facts"]
    assert after == before


# ------------------------------------------------------------------ 학습 지표
def test_learning_summary_is_aggregate_only(admin, user_a, roi_mismatch):
    """운영자가 **개인의 학습 내용을 들여다보는 도구가 아니다.**

    집계만 나가야 한다 — user_id·이메일이 응답에 섞이면 목적이 달라진다.
    """
    import json

    user_a.get(f"/api/cases/{CASE_ID}")
    user_a.submit(roi_mismatch)

    body = admin.get("/api/admin/learning-summary").json()
    payload = json.dumps(body, ensure_ascii=False)

    assert user_a.user_id not in payload, "응답에 개인 식별자가 들어 있다"
    assert user_a.email not in payload
    # 집계는 제대로 나온다
    assert body["users_seen"] >= 1
    assert body["submissions"] >= 1


def test_learning_summary_matches_cli_report(admin, user_a, roi_mismatch):
    """CLI 와 API 가 같은 함수를 쓴다 — 두 곳에서 따로 계산하면 숫자가 갈라진다."""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.learning_stats import build_report
    from app.models import LearningEvent

    user_a.submit(roi_mismatch)

    api = admin.get("/api/admin/learning-summary").json()
    with SessionLocal() as db:
        events = db.scalars(select(LearningEvent).order_by(LearningEvent.id)).all()
        cli = build_report(events)

    assert api["submissions"] == cli["submissions"]
    assert api["users_seen"] == cli["users_seen"]


def test_learning_summary_reports_collection_state(admin, monkeypatch):
    """'데이터가 없다'와 '수집이 꺼져 있다'는 다른 이야기다."""
    monkeypatch.setenv("MEDISCAN_ANALYTICS", "0")
    assert admin.get("/api/admin/learning-summary").json()["analytics_enabled"] is False


def test_learning_summary_without_events_does_not_crash(admin):
    body = admin.get("/api/admin/learning-summary").json()
    assert body["events"] == 0
    assert body["start_to_submit_rate"] is None


# ------------------------------------------- GT 를 화면에서 고치는 경로가 없다 (핵심)
def test_admin_cannot_change_reference_mask(admin):
    """전문가 GT 는 채점 기준이다. API 로 바꿀 수 있으면 안 된다."""
    before = admin.get(f"/api/admin/cases/{CASE_ID}").json()["reference_mask_url"]

    res = admin._client.request(
        "PATCH",
        f"/api/admin/cases/{CASE_ID}",
        json={"reference_mask_url": "/static/results/hacked.png", "is_active": True},
        headers=admin.headers,
    )
    assert res.status_code == 200  # 알 수 없는 필드는 무시된다

    after = admin.get(f"/api/admin/cases/{CASE_ID}").json()["reference_mask_url"]
    assert after == before


def test_admin_cannot_overwrite_case_facts_via_findings(admin):
    res = admin._client.request(
        "PUT",
        f"/api/admin/cases/{CASE_ID}/findings",
        json={**FINDINGS_PAYLOAD, "case_facts": {"disease_name": "조작"}},
        headers=admin.headers,
    )
    assert res.status_code == 200
    facts = res.json()["explanation"]["case_facts"]
    assert facts is None or facts.get("disease_name") != "조작"
