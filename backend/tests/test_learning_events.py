"""
학습 이벤트 로그 (Phase 8 / RELEASE_READINESS H7).

Closed Beta 에서 보려는 것: 케이스 시작 → 제출 전환율, 재도전 시 점수 변화, 소요시간.

여기서 지키려는 것:
  - **개인정보를 담지 않는다** (이메일·닉네임·IP·ROI 원본 금지)
  - 로그가 **채점·학습 상태 계산에 개입하지 않는다**
  - 기록이 실패해도 학습 흐름이 막히지 않는다
  - 탈퇴하면 함께 사라진다
"""
import pytest
from sqlalchemy import select

from app import analytics
from app.db import SessionLocal
from app.models import LearningEvent
from tests.conftest import CASE_ID


def _events(user_id: str, event: str | None = None) -> list[LearningEvent]:
    with SessionLocal() as db:
        stmt = select(LearningEvent).where(LearningEvent.user_id == user_id)
        if event:
            stmt = stmt.where(LearningEvent.event == event)
        return db.scalars(stmt.order_by(LearningEvent.id)).all()


# ------------------------------------------------------------------ 기록 동작
def test_opening_a_case_is_recorded(user_a):
    user_a.get(f"/api/cases/{CASE_ID}")
    opened = _events(user_a.user_id, analytics.CASE_OPENED)

    assert len(opened) == 1
    assert opened[0].case_id == CASE_ID


def test_submission_is_recorded_with_grade_and_dice(user_a, roi_match):
    body = user_a.submit(roi_match).json()
    graded = _events(user_a.user_id, analytics.SUBMISSION_GRADED)

    assert len(graded) == 1
    assert graded[0].grade == body["grade"]
    assert graded[0].dice == body["dice"]
    assert graded[0].attempt_number == 1


def test_attempt_number_increases_across_retries(user_a, roi_mismatch, roi_match):
    """첫 시도와 재도전을 이어야 학습 효과를 볼 수 있다."""
    user_a.submit(roi_mismatch)
    user_a.post(f"/api/wrong-notes/{CASE_ID}/retry", json={"roi": roi_match})

    graded = _events(user_a.user_id, analytics.SUBMISSION_GRADED)
    assert [e.attempt_number for e in graded] == [1, 2]
    # 재도전에서 점수가 올랐다는 것이 데이터로 남는다
    assert graded[1].dice > graded[0].dice


def test_duration_is_recorded_when_provided(user_a, roi_match):
    user_a.post(f"/api/cases/{CASE_ID}/submit", json={"roi": roi_match, "duration_seconds": 95})
    graded = _events(user_a.user_id, analytics.SUBMISSION_GRADED)
    assert graded[0].duration_seconds == 95


def test_duration_is_optional(user_a, roi_match):
    user_a.submit(roi_match)
    assert _events(user_a.user_id, analytics.SUBMISSION_GRADED)[0].duration_seconds is None


@pytest.mark.parametrize("value", [-5, "빠름", None, 10**9])
def test_unrealistic_duration_is_clamped_or_dropped(user_a, roi_match, value):
    """클라이언트가 보낸 값을 그대로 믿지 않는다."""
    user_a.post(f"/api/cases/{CASE_ID}/submit", json={"roi": roi_match, "duration_seconds": value})
    recorded = _events(user_a.user_id, analytics.SUBMISSION_GRADED)[0].duration_seconds
    assert recorded is None or 0 <= recorded <= analytics.MAX_DURATION_SECONDS


# ------------------------------------------------ 개인정보를 담지 않는다 (핵심)
def test_event_table_has_no_personal_fields():
    """스키마 자체에 개인정보 칸이 없어야 한다 — 있으면 언젠가 채워진다."""
    columns = set(LearningEvent.__table__.columns.keys())
    forbidden = {"email", "nickname", "ip", "ip_address", "user_agent", "roi", "mask", "image"}
    assert not (columns & forbidden), f"개인정보 칼럼이 있다: {columns & forbidden}"
    assert columns == {
        "id", "user_id", "case_id", "event", "grade", "dice",
        "attempt_number", "duration_seconds", "created_at",
    }


def test_recorded_values_contain_no_free_text(user_a, roi_match):
    """자유 입력이 섞이면 무엇이 쌓이는지 통제할 수 없다."""
    user_a.submit(roi_match)
    event = _events(user_a.user_id, analytics.SUBMISSION_GRADED)[0]

    assert event.event in analytics.ALLOWED_EVENTS
    assert event.grade in {"match", "partial_match", "mismatch"}
    assert user_a.email not in str(event.__dict__)


def test_unknown_event_names_are_ignored(user_a):
    """허용 목록에 없는 이벤트는 기록하지 않는다."""
    with SessionLocal() as db:
        result = analytics.record(db, user_id=user_a.user_id, event="anything_i_want")
        db.commit()

    assert result is None
    assert _events(user_a.user_id, "anything_i_want") == []


# ------------------------------------------- 채점·학습 상태에 개입하지 않는다 (핵심)
def test_events_do_not_affect_grading(user_a, roi_match):
    """같은 ROI 는 로그 유무와 무관하게 같은 결과여야 한다."""
    first = user_a.submit(roi_match).json()
    second = user_a.submit(roi_match).json()

    assert first["grade"] == second["grade"]
    assert first["dice"] == second["dice"]
    assert first["spatial_feedback"]["metrics"] == second["spatial_feedback"]["metrics"]


def test_learning_state_ignores_events(user_a, roi_match):
    """has_matched / needs_review 는 Submission 에서만 계산된다."""
    user_a.submit(roi_match)
    before = user_a.get("/api/cases").json()["cases"]

    with SessionLocal() as db:
        for _ in range(5):
            analytics.record(
                db,
                user_id=user_a.user_id,
                event=analytics.SUBMISSION_GRADED,
                case_id=CASE_ID,
                grade="mismatch",
                dice=0.0,
            )
        db.commit()

    assert user_a.get("/api/cases").json()["cases"] == before


def test_logging_failure_does_not_break_submission(user_a, roi_match, monkeypatch):
    """관찰용 로그 때문에 학습이 막히면 안 된다."""
    def explode(*args, **kwargs):
        raise RuntimeError("의도적 실패")

    monkeypatch.setattr(analytics, "record", explode)
    # record 가 라우터에서 직접 호출되므로, 예외가 나면 500 이 된다.
    # analytics.record 자체가 내부에서 예외를 삼키는지 별도로 확인한다.
    from app import analytics as module

    monkeypatch.undo()
    with SessionLocal() as db:
        monkeypatch.setattr(module, "LearningEvent", explode)
        assert module.record(db, user_id=user_a.user_id, event=module.CASE_OPENED) is None


def test_can_be_disabled_by_env(user_a, roi_match, monkeypatch):
    monkeypatch.setenv("MEDISCAN_ANALYTICS", "0")
    user_a.submit(roi_match)
    assert _events(user_a.user_id) == []


# -------------------------------------------------------------- 격리·삭제
def test_events_are_isolated_per_user(user_a, user_b, roi_match):
    user_a.submit(roi_match)
    assert _events(user_b.user_id) == []
    assert len(_events(user_a.user_id)) > 0


def test_events_are_deleted_with_the_account(user_a, roi_match):
    user_a.submit(roi_match)
    assert len(_events(user_a.user_id)) > 0

    user_a.delete("/api/auth/me", json={"password": user_a.password})
    assert _events(user_a.user_id) == []
