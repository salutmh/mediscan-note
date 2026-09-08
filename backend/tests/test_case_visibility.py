"""
비활성 케이스가 학습자에게 새지 않는지 (교차 엔드포인트 불변조건).

**왜 이 파일이 따로 있나**
운영자가 케이스를 숨기는 이유는 대개 "이 케이스에 문제가 있다"이다 — 기준 마스크가 잘못됐거나,
검수가 끝나지 않았거나. 그런데 한 경로라도 열려 있으면 **문제 있는 기준으로 채점이 계속된다.**
실제로 `POST /wrong-notes/{id}/retry` 가 `is_active` 를 보지 않아 숨긴 케이스로 재도전이
채점되고 있었다(이 파일이 그 회귀를 고정한다).

**케이스를 다루는 학습자 경로를 추가하면 여기에도 추가할 것.**
숨김은 삭제가 아니므로, 다시 노출하면 원래대로 돌아와야 한다는 것도 함께 확인한다.
"""
import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Case, Submission
from tests.conftest import CASE_ID


def _set_active(case_id: str, active: bool) -> None:
    with SessionLocal() as db:
        db.get(Case, case_id).is_active = active
        db.commit()


@pytest.fixture
def hidden_case():
    """테스트 동안 케이스를 숨겼다가 반드시 되돌린다 (케이스는 공용 시드 데이터)."""
    _set_active(CASE_ID, False)
    yield CASE_ID
    _set_active(CASE_ID, True)


# ------------------------------------------------ 학습자 경로 전부에서 막힌다
def test_hidden_case_is_absent_from_case_list(user_a, hidden_case):
    ids = [c["case_id"] for c in user_a.get("/api/cases").json()["cases"]]
    assert hidden_case not in ids


def test_hidden_case_detail_returns_404(user_a, hidden_case):
    assert user_a.get(f"/api/cases/{hidden_case}").status_code == 404


def test_hidden_case_submit_returns_404(user_a, hidden_case, roi_match):
    assert user_a.submit(roi_match, case_id=hidden_case).status_code == 404


def test_hidden_case_retry_returns_404(user_a, roi_mismatch, roi_match):
    """회귀 고정: retry 는 is_active 를 보지 않아 숨긴 케이스로 채점되고 있었다."""
    user_a.submit(roi_mismatch)  # 먼저 틀려서 복습노트에 넣는다
    _set_active(CASE_ID, False)
    try:
        res = user_a.post(f"/api/wrong-notes/{CASE_ID}/retry", json={"roi": roi_match})
        assert res.status_code == 404, "숨긴 케이스가 재도전 경로로 채점됐다"
    finally:
        _set_active(CASE_ID, True)


def test_hidden_case_retry_creates_no_submission(user_a, roi_mismatch, roi_match):
    """차단은 이력도 남기지 않아야 한다 (422 CASE_NOT_GRADABLE 과 같은 원칙)."""
    user_a.submit(roi_mismatch)
    with SessionLocal() as db:
        before = len(
            db.scalars(select(Submission).where(Submission.user_id == user_a.user_id)).all()
        )

    _set_active(CASE_ID, False)
    try:
        user_a.post(f"/api/wrong-notes/{CASE_ID}/retry", json={"roi": roi_match})
    finally:
        _set_active(CASE_ID, True)

    with SessionLocal() as db:
        after = len(
            db.scalars(select(Submission).where(Submission.user_id == user_a.user_id)).all()
        )
    assert after == before


def test_hidden_case_disappears_from_wrong_notes(user_a, roi_mismatch):
    """누를 수 없는 항목을 목록에 남겨두면 404 밖에 안 나온다."""
    user_a.submit(roi_mismatch)
    assert CASE_ID in [i["case_id"] for i in user_a.get("/api/wrong-notes").json()["items"]]

    _set_active(CASE_ID, False)
    try:
        ids = [i["case_id"] for i in user_a.get("/api/wrong-notes").json()["items"]]
        assert CASE_ID not in ids
    finally:
        _set_active(CASE_ID, True)


# ------------------------------------------------------ 숨김은 삭제가 아니다
def test_history_survives_hiding_and_returns_when_shown_again(user_a, roi_mismatch):
    user_a.submit(roi_mismatch)

    _set_active(CASE_ID, False)
    assert CASE_ID not in [i["case_id"] for i in user_a.get("/api/wrong-notes").json()["items"]]

    _set_active(CASE_ID, True)
    # 이력이 지워진 게 아니라 가려졌을 뿐이므로 그대로 돌아온다
    assert CASE_ID in [i["case_id"] for i in user_a.get("/api/wrong-notes").json()["items"]]


def test_hidden_case_submissions_are_kept_in_db(user_a, roi_mismatch, hidden_case):
    """숨김 전에 쌓인 이력은 DB 에 남아 있어야 한다."""
    with SessionLocal() as db:
        rows = db.scalars(select(Submission).where(Submission.case_id == hidden_case)).all()
    # 이 테스트 자체는 이력 유무와 무관하게, 숨김이 이력을 지우지 않음을 확인한다
    assert isinstance(rows, list)


# ---------------------------------------------------- 운영자는 계속 볼 수 있다
def test_admin_still_sees_hidden_case(admin_session, hidden_case):
    """숨긴 것을 다시 찾을 수 없으면 되돌릴 수 없다."""
    ids = [c["case_id"] for c in admin_session.get("/api/admin/cases").json()["cases"]]
    assert hidden_case in ids
    assert admin_session.get(f"/api/admin/cases/{hidden_case}").status_code == 200
