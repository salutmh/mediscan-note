"""
해설 열람 기록 (자율 루프 #32).

**왜 재는가**
"틀린 뒤에 해설을 실제로 읽는가"는 콘텐츠에 사람 시간을 쓸 가치가 있는지를 가른다.
특히 전문가 소견(case_findings) 작성은 사람 시간이 많이 드는 일이라(BLOCKER-2),
아무도 안 읽는다면 우선순위가 달라진다.

EXPLANATION_VIEWED 상수는 예전부터 있었지만 **아무도 기록하지 않아서** 늘 0 이었다.
"수집되고 있다"고 착각하기 딱 좋은 상태였다.
"""
from sqlalchemy import select

from app import analytics
from app.db import SessionLocal
from app.learning_stats import build_report
from app.models import LearningEvent
from tests.conftest import CASE_ID


def _events(user_id: str) -> list[LearningEvent]:
    with SessionLocal() as db:
        return db.scalars(
            select(LearningEvent).where(
                LearningEvent.user_id == user_id,
                LearningEvent.event == analytics.EXPLANATION_VIEWED,
            )
        ).all()


def test_marks_the_explanation_as_viewed(user_a):
    res = user_a.post(f"/api/cases/{CASE_ID}/explanation-viewed")
    assert res.status_code == 200
    assert res.json()["recorded"] is True
    assert len(_events(user_a.user_id)) == 1


def test_same_user_and_case_is_recorded_only_once(user_a):
    """화면을 오갈 때마다 쌓이면 "몇 명이 봤는가"가 반복 조회에 묻힌다."""
    user_a.post(f"/api/cases/{CASE_ID}/explanation-viewed")
    second = user_a.post(f"/api/cases/{CASE_ID}/explanation-viewed")

    assert second.status_code == 200
    # 실패가 아니라 "이미 기록돼 있다" 이다
    assert second.json()["recorded"] is False
    assert len(_events(user_a.user_id)) == 1


def test_different_users_are_counted_separately(user_a, user_b):
    user_a.post(f"/api/cases/{CASE_ID}/explanation-viewed")
    user_b.post(f"/api/cases/{CASE_ID}/explanation-viewed")

    assert len(_events(user_a.user_id)) == 1
    assert len(_events(user_b.user_id)) == 1


def test_requires_login(client):
    assert client.post(f"/api/cases/{CASE_ID}/explanation-viewed").status_code == 401


def test_unknown_case_is_404(user_a):
    assert user_a.post("/api/cases/NOPE-999/explanation-viewed").status_code == 404


def test_hidden_case_is_404(user_a, admin_session):
    """숨긴 케이스에는 기록도 남기지 않는다 (존재를 알려줄 이유가 없다)."""
    admin_session.patch(f"/api/admin/cases/{CASE_ID}", json={"is_active": False})
    try:
        assert user_a.post(f"/api/cases/{CASE_ID}/explanation-viewed").status_code == 404
    finally:
        admin_session.patch(f"/api/admin/cases/{CASE_ID}", json={"is_active": True})


# ------------------------------------------------------------------ 집계
def test_report_counts_viewers_not_views(user_a, user_b, roi_match):
    """분모는 제출까지 간 (사용자, 케이스) 쌍이다 — 해설은 채점 뒤에 보인다."""
    user_a.submit(roi_match)
    user_b.submit(roi_match)
    user_a.post(f"/api/cases/{CASE_ID}/explanation-viewed")
    user_a.post(f"/api/cases/{CASE_ID}/explanation-viewed")  # 두 번 눌러도 1명

    with SessionLocal() as db:
        report = build_report(db.scalars(select(LearningEvent)).all())

    assert report["explanations_viewed"] == 1
    assert report["submit_to_explanation_rate"] == 0.5  # 제출 2쌍 중 1쌍이 열람


def test_report_handles_no_submissions_yet():
    with SessionLocal() as db:
        report = build_report(db.scalars(select(LearningEvent)).all())
    # 제출이 없으면 비율을 0 으로 꾸며내지 않는다 (0% 로 읽히면 안 된다)
    assert report["submit_to_explanation_rate"] is None
    assert report["explanations_viewed"] == 0


def test_disabled_analytics_records_nothing(user_a, monkeypatch):
    monkeypatch.setenv(analytics.ENABLED_ENV, "0")
    res = user_a.post(f"/api/cases/{CASE_ID}/explanation-viewed")

    assert res.status_code == 200  # 사용자 흐름을 막지 않는다
    assert res.json()["recorded"] is False
    assert _events(user_a.user_id) == []
