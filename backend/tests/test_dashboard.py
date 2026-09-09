"""
학습 대시보드 — **있는 데이터를 보여줄 뿐, 만들어내지 않는다.**

==========================================================================
이 화면이 없어서 홈이 그냥 케이스 격자였다.
==========================================================================
시도 횟수·최고 점수·개선폭은 전부 `submissions` 에 있었는데 화면까지 오지 못했다.

여기서 지키는 것
----------------
  * **없는 값을 0 으로 채우지 않는다.** "아직 안 풀었음"과 "0점"은 다르다.
  * **의료적 난이도를 만들지 않는다.** 나오는 숫자는 전부 사용자 자신의 기록이다.
  * **개선폭은 같은 케이스 안에서만 비교한다.** 케이스마다 병변이 달라서,
    서로 다른 케이스의 Dice 를 비교하면 "나아졌다"는 말이 성립하지 않는다.
  * 비활성 케이스는 집계에서 빠지되 **이력은 지우지 않는다.**
"""
import base64
import io as _io

import pytest
from PIL import Image, ImageDraw

from tests.conftest import CASE_ID, IMAGE_SIZE, LESION

SECOND_CASE_ID = "VS-SEG-115"
SECOND_LESION = {"cx": 215, "cy": 282, "r": 26}


@pytest.fixture
def learner(client, make_user):
    return make_user()


def _dashboard(user):
    response = user.get("/api/me/dashboard")
    assert response.status_code == 200, response.text
    return response.json()


def _roi_on(lesion: dict) -> dict:
    """그 케이스의 기준 병변을 정확히 덮는 ROI."""
    img = Image.new("RGBA", (IMAGE_SIZE, IMAGE_SIZE), (0, 0, 0, 0))
    cx, cy, r = lesion["cx"], lesion["cy"], lesion["r"]
    ImageDraw.Draw(img).ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255))
    buf = _io.BytesIO()
    img.save(buf, "PNG")
    return {
        "type": "brush_mask",
        "points": [[cx, cy]],
        "mask_png_base64": base64.b64encode(buf.getvalue()).decode(),
    }


# ------------------------------------------------------------- 처음 상태
def test_a_new_user_sees_no_invented_numbers(client, learner):
    data = _dashboard(learner)
    assert data["has_any_activity"] is False
    assert data["best_dice"] is None, "**0 으로 채우면 '0점을 받았다'로 읽힌다**"
    assert data["latest_improvement"] is None
    assert data["recent_activity"] == []
    assert data["totals"]["total_attempts"] == 0


def test_a_new_user_is_told_where_to_start(client, learner):
    data = _dashboard(learner)
    assert data["next_up"] is not None, "홈이 '이제 뭘 하지'에 답해야 한다"
    assert data["next_up"]["reason"] == "not_started"
    assert data["next_up"]["case_id"]


def test_totals_count_only_active_cases(client, learner):
    data = _dashboard(learner)
    assert data["totals"]["total_cases"] >= 1
    assert data["totals"]["not_started"] == data["totals"]["total_cases"]
    assert data["totals"]["attempted"] == 0


# ------------------------------------------------------------- 시도 이후
def test_an_attempt_shows_up_in_recent_activity(client, learner, roi_mismatch):
    learner.submit(roi_mismatch)

    data = _dashboard(learner)
    assert data["has_any_activity"] is True
    assert len(data["recent_activity"]) == 1
    entry = data["recent_activity"][0]
    assert entry["case_id"] == CASE_ID
    assert entry["grade"] in ("match", "partial_match", "mismatch")
    assert entry["submitted_at"]


def test_a_wrong_attempt_makes_the_case_the_next_one_up(client, learner, roi_mismatch):
    """**복습필요를 먼저 추천한다.** 순서 규칙일 뿐 난이도 판단이 아니다."""
    learner.submit(roi_mismatch)

    data = _dashboard(learner)
    assert data["next_up"]["case_id"] == CASE_ID
    assert data["next_up"]["reason"] == "needs_review"


def test_matching_moves_the_case_out_of_needs_review(client, learner, roi_match):
    learner.submit(roi_match)

    data = _dashboard(learner)
    assert data["totals"]["matched"] == 1
    assert data["totals"]["needs_review"] == 0
    assert data["next_up"]["reason"] != "needs_review"


def test_best_dice_is_the_best_not_the_latest(client, learner, roi_match, roi_mismatch):
    """맞힌 뒤 다시 틀려도 **최고 기록은 남는다.**

    (기준 마스크와 브러시 래스터화가 완전히 같지는 않아 Dice 가 1.0 이 아니다 —
    그래서 상수와 비교하지 않고 실제 제출 결과와 비교한다.)
    """
    matched_dice = learner.submit(roi_match).json()["dice"]
    learner.submit(roi_mismatch)

    data = _dashboard(learner)
    assert data["best_dice"] == pytest.approx(matched_dice)


def test_total_attempts_counts_every_submission(client, learner, roi_mismatch):
    for _ in range(3):
        learner.submit(roi_mismatch)

    data = _dashboard(learner)
    assert data["totals"]["total_attempts"] == 3
    assert data["totals"]["attempted"] == 1, "같은 케이스를 세 번 푼 것은 케이스 1개다"


# ------------------------------------------------------------- 개선폭
def test_improvement_compares_the_last_two_attempts_of_one_case(
    client, learner, roi_mismatch, roi_match
):
    """**재도전이 핵심 학습 루프인데** 얼마나 나아졌는지가 어디에도 없었다."""
    learner.submit(roi_mismatch)
    learner.submit(roi_match)

    improvement = _dashboard(learner)["latest_improvement"]
    assert improvement is not None
    assert improvement["case_id"] == CASE_ID
    assert improvement["latest_dice"] > improvement["previous_dice"]
    assert improvement["delta"] > 0
    assert improvement["latest_grade"] == "match"


def test_improvement_is_none_after_a_single_attempt(client, learner, roi_mismatch):
    """한 번만 풀었으면 비교 대상이 없다 — **0 이 아니라 없음이다.**"""
    learner.submit(roi_mismatch)
    assert _dashboard(learner)["latest_improvement"] is None


def test_improvement_never_compares_across_cases(client, learner, roi_mismatch):
    """**케이스마다 병변이 다르다.** 서로 다른 케이스의 Dice 비교는 의미가 없다."""
    learner.submit(roi_mismatch)
    learner.submit(_roi_on(SECOND_LESION), case_id=SECOND_CASE_ID)

    assert _dashboard(learner)["latest_improvement"] is None, (
        "케이스가 서로 다르면 개선폭을 계산하면 안 된다"
    )


# --------------------------------------------------- 다른 사용자와 격리
def test_one_users_attempts_do_not_appear_for_another(
    client, learner, make_user, roi_mismatch
):
    learner.submit(roi_mismatch)

    other = make_user()
    data = _dashboard(other)
    assert data["has_any_activity"] is False
    assert data["recent_activity"] == []


def test_dashboard_requires_authentication(client):
    assert client.get("/api/me/dashboard").status_code == 401


# ------------------------------------------------- 의료 내용을 만들지 않는다
def test_dashboard_does_not_invent_difficulty_or_findings(client, learner, roi_mismatch):
    """**의료적 난이도·소견을 자동으로 만들지 않는다.**

    "이 케이스가 어렵다" "이런 병변을 자주 놓친다" 는 우리가 할 수 있는 말이 아니다.
    """
    learner.submit(roi_mismatch)

    text = str(_dashboard(learner))
    for forbidden in ("difficulty", "finding", "진단", "소견", "어려운", "자주 놓"):
        assert forbidden not in text, f"대시보드가 {forbidden!r} 을 만들어냈다"
