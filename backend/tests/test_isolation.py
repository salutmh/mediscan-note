"""
사용자간 데이터 격리 — 최우선 테스트.

한 사용자의 판독 이력이 다른 사용자에게 절대 새어나가면 안 된다.
의료 학습 서비스에서 "남의 학습 상태가 보인다"는 것은 기능 버그를 넘어 신뢰 문제다.

학습 상태는 API 계약 v0.4 기준으로 has_matched(학습완료) / needs_review(복습필요) 두 축이다.
"""
import pytest

from tests.conftest import CASE_ID

# 로그인이 필요한 모든 엔드포인트 (api-spec.md 0절)
PROTECTED = [
    ("GET", "/api/auth/me", None),
    ("GET", "/api/cases", None),
    ("GET", f"/api/cases/{CASE_ID}", None),
    ("POST", f"/api/cases/{CASE_ID}/submit", {"roi": {"type": "brush_mask", "points": [[1, 1]]}}),
    ("GET", "/api/wrong-notes", None),
    ("POST", f"/api/wrong-notes/{CASE_ID}/retry", {"roi": {"type": "brush_mask", "points": [[1, 1]]}}),
    ("POST", "/api/analyze", {"image_base64": "iVBORw0KGgo="}),
]


def _case_row(payload: dict, case_id: str = CASE_ID) -> dict:
    return next(c for c in payload["cases"] if c["case_id"] == case_id)


# ---------------------------------------------------------------- 토큰 요구
@pytest.mark.parametrize("method,path,body", PROTECTED)
def test_protected_endpoints_require_token(client, method, path, body):
    res = client.request(method, path, json=body)
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize("method,path,body", PROTECTED)
def test_protected_endpoints_reject_forged_token(client, method, path, body):
    res = client.request(method, path, json=body, headers={"Authorization": "Bearer forged.signature"})
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "INVALID_TOKEN"


# ------------------------------------------------------- 케이스 목록 격리
def test_solved_state_is_per_user(user_a, user_b, roi_match):
    """A 가 맞혀도 B 의 케이스 목록은 영향을 받지 않는다."""
    assert user_a.submit(roi_match).json()["grade"] == "match"

    a_row = _case_row(user_a.get("/api/cases").json())
    b_row = _case_row(user_b.get("/api/cases").json())

    assert a_row["has_matched"] is True
    assert a_row["needs_review"] is False
    assert b_row["has_matched"] is False
    assert b_row["needs_review"] is False


def test_fresh_user_sees_nothing_solved(user_a, user_b, roi_match):
    """A 가 모든 케이스를 풀어도 신규 사용자 B 는 전부 미해결이어야 한다."""
    for case in user_a.get("/api/cases").json()["cases"]:
        user_a.submit(roi_match, case_id=case["case_id"])

    b_cases = user_b.get("/api/cases").json()["cases"]
    assert b_cases, "케이스 시드가 비어 있으면 이 테스트는 의미가 없다"
    assert all(c["has_matched"] is False for c in b_cases)
    assert all(c["needs_review"] is False for c in b_cases)


# ---------------------------------------------------------- 복습노트 격리
def test_wrong_notes_are_per_user(user_a, user_b, roi_mismatch):
    """A 가 틀려서 생긴 복습노트가 B 에게 보이면 안 된다."""
    assert user_a.submit(roi_mismatch).json()["grade"] == "mismatch"

    a_items = user_a.get("/api/wrong-notes").json()["items"]
    b_items = user_b.get("/api/wrong-notes").json()["items"]

    assert [i["case_id"] for i in a_items] == [CASE_ID]
    assert b_items == []


def test_retry_result_is_attributed_to_submitter(user_a, user_b, roi_mismatch, roi_match):
    """B 가 재도전해 맞혀도 A 의 복습노트는 그대로 남는다."""
    user_a.submit(roi_mismatch)
    user_b.submit(roi_mismatch)

    res = user_b.post(f"/api/wrong-notes/{CASE_ID}/retry", json={"roi": roi_match})
    assert res.status_code == 200
    assert res.json()["grade"] == "match"

    assert user_b.get("/api/wrong-notes").json()["items"] == []
    assert [i["case_id"] for i in user_a.get("/api/wrong-notes").json()["items"]] == [CASE_ID]


# ------------------------------------------------------------ 저장소 수준
def test_submission_rows_belong_to_submitter(user_a, user_b, roi_match, roi_mismatch):
    """DB 에 저장된 제출 이력의 user_id 가 실제 제출자와 일치한다."""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Submission

    user_a.submit(roi_match)
    user_b.submit(roi_mismatch)

    with SessionLocal() as db:
        rows = db.scalars(select(Submission)).all()
        by_user = {r.user_id: r.grade for r in rows}

    assert by_user == {user_a.user_id: "match", user_b.user_id: "mismatch"}


def test_progress_source_data_is_per_user(user_a, user_b, roi_match):
    """화면 7(진행현황)이 집계에 쓰는 두 응답이 사용자별로 분리되어 있다."""
    user_a.submit(roi_match)

    a_cases = user_a.get("/api/cases").json()["cases"]
    b_cases = user_b.get("/api/cases").json()["cases"]

    assert sum(1 for c in a_cases if c["has_matched"]) == 1
    assert sum(1 for c in b_cases if c["has_matched"]) == 0
    assert user_b.get("/api/wrong-notes").json()["items"] == []


def test_me_returns_only_own_identity(user_a, user_b):
    assert user_a.get("/api/auth/me").json()["user_id"] == user_a.user_id
    assert user_b.get("/api/auth/me").json()["user_id"] == user_b.user_id
    assert user_a.user_id != user_b.user_id


def test_token_of_one_user_never_returns_another_users_data(user_a, user_b, roi_match):
    """A 의 토큰으로는 어떤 경로로도 B 의 이력이 나오지 않는다."""
    user_b.submit(roi_match)

    assert user_a.get("/api/wrong-notes").json()["items"] == []
    assert all(c["has_matched"] is False for c in user_a.get("/api/cases").json()["cases"])
    assert user_a.get("/api/auth/me").json()["email"] == user_a.email
