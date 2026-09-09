"""
재도전 경과 (`progress`) — 자율 루프 #30.

**왜 필요한가**
회차(attempt_number)는 원래도 서버가 세고 있었다. 다만 운영자용 분석 로그로만 들어가서,
정작 케이스를 다시 푼 학습자는 자기가 나아졌는지 알 수 없었다. 재도전의 의미가 거기 있다.

**여기 있는 것은 전부 학습자 자신의 숫자다.** 같은 전문가 기준 마스크와의 일치도를
시점만 달리해 비교한 것이라 의학적 판단이 아니고, grade 에도 영향을 주지 않는다.
"""
import pytest


def test_first_attempt_has_nothing_to_compare(user_a, roi_mismatch):
    """비교 대상이 없는 것을 0 으로 채우면 "0에서 올랐다"로 읽힌다."""
    body = user_a.submit(roi_mismatch).json()

    progress = body["progress"]
    assert progress["attempt_number"] == 1
    assert progress["is_first_attempt"] is True
    assert progress["previous"] is None
    assert progress["improved"] is None
    # 첫 시도의 최고 기록은 이번 점수다
    assert progress["best_dice"] == body["dice"]


def test_second_attempt_reports_the_previous_score(user_a, roi_mismatch, roi_match):
    first = user_a.submit(roi_mismatch).json()
    second = user_a.submit(roi_match).json()

    progress = second["progress"]
    assert progress["attempt_number"] == 2
    assert progress["is_first_attempt"] is False
    assert progress["previous"]["dice"] == first["dice"]
    assert progress["previous"]["grade"] == first["grade"]
    assert progress["previous"]["submitted_at"]


def test_improvement_is_measured_against_the_previous_attempt(user_a, roi_mismatch, roi_match):
    user_a.submit(roi_mismatch)
    better = user_a.submit(roi_match).json()
    assert better["progress"]["improved"] is True

    worse = user_a.submit(roi_mismatch).json()
    assert worse["progress"]["improved"] is False


def test_best_score_survives_a_worse_attempt(user_a, roi_mismatch, roi_match):
    """직전보다 낮게 나와도 지금까지의 최고는 남는다 (뒤로 갔다고 느끼지 않게)."""
    user_a.submit(roi_mismatch)
    best = user_a.submit(roi_match).json()["dice"]
    worse = user_a.submit(roi_mismatch).json()

    assert worse["progress"]["improved"] is False
    assert worse["progress"]["best_dice"] == best


def test_progress_is_per_user(user_a, user_b, roi_match, roi_mismatch):
    """남의 시도가 내 회차에 섞이면 안 된다."""
    user_a.submit(roi_mismatch)
    user_a.submit(roi_match)

    body = user_b.submit(roi_match).json()
    assert body["progress"]["attempt_number"] == 1
    assert body["progress"]["previous"] is None


def test_retry_from_wrong_notes_also_reports_progress(user_a, roi_mismatch, roi_match):
    """복습노트 재도전이야말로 이 값이 필요한 자리다."""
    from tests.conftest import CASE_ID

    user_a.submit(roi_mismatch)
    body = user_a.post(f"/api/wrong-notes/{CASE_ID}/retry", json={"roi": roi_match}).json()

    assert body["progress"]["attempt_number"] == 2
    assert body["progress"]["previous"] is not None
    assert body["progress"]["improved"] is True


def test_progress_does_not_change_the_grade(user_a, roi_match):
    """경과 표시가 채점에 영향을 주면 안 된다 — 기준은 기준 마스크뿐이다."""
    first = user_a.submit(roi_match).json()
    second = user_a.submit(roi_match).json()

    assert second["grade"] == first["grade"]
    assert second["dice"] == first["dice"]
    assert second["progress"]["improved"] is False  # 같은 점수는 향상이 아니다


# ---------------------------------------------------------------------------
# 목록에 실리는 케이스별 시도 요약
# ---------------------------------------------------------------------------
# **데이터는 있는데 화면까지 오지 않던 것.** 목록이 has_matched/needs_review 두
# boolean 만 받아서, 카드에 "몇 번 풀었는지"조차 쓸 수 없었다.
def _card(user, case_id: str = "VS-SEG-202") -> dict:
    cases = user.get("/api/cases").json()["cases"]
    return next(c for c in cases if c["case_id"] == case_id)


def test_an_untouched_case_has_no_progress_object(user_a):
    """**null 이다. 0 이 아니다.** "아직 안 풀었음"과 "0점"은 다른 상태다."""
    assert _card(user_a)["progress"] is None


def test_progress_appears_after_the_first_attempt(user_a, roi_mismatch):
    user_a.submit(roi_mismatch)
    progress = _card(user_a)["progress"]
    assert progress["attempts"] == 1
    assert progress["latest_grade"] == "mismatch"
    assert progress["last_attempt_at"]


def test_attempts_accumulate(user_a, roi_mismatch):
    for _ in range(3):
        user_a.submit(roi_mismatch)
    assert _card(user_a)["progress"]["attempts"] == 3


def test_best_dice_survives_a_later_worse_attempt(user_a, roi_match, roi_mismatch):
    """최고 기록은 나중에 틀려도 남는다 — 그래야 재도전이 무섭지 않다."""
    best = user_a.submit(roi_match).json()["dice"]
    user_a.submit(roi_mismatch)

    progress = _card(user_a)["progress"]
    assert progress["best_dice"] == pytest.approx(best)
    assert progress["latest_dice"] < progress["best_dice"]
    assert progress["latest_grade"] == "mismatch"


def test_progress_is_per_user(user_a, user_b, roi_mismatch):
    user_a.submit(roi_mismatch)
    assert _card(user_b)["progress"] is None


def test_progress_does_not_leak_into_other_cases(user_a, roi_mismatch):
    user_a.submit(roi_mismatch)
    assert _card(user_a, "VS-SEG-115")["progress"] is None


def test_existing_list_fields_are_unchanged(user_a, roi_mismatch):
    """**추가일 뿐 변경이 아니다.** 기존 프론트가 깨지면 안 된다."""
    user_a.submit(roi_mismatch)
    card = _card(user_a)
    for key in ("case_id", "body_part", "disease", "thumbnail_url",
                "has_matched", "needs_review", "gradable", "difficulty"):
        assert key in card
