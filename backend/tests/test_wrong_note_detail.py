"""
오답 상세 (`GET /api/wrong-notes/{case_id}`) — **다시 풀기 전에 무엇을 놓쳤는지 보는 화면.**

왜 만들었나
----------
해설은 **제출 직후에만** 볼 수 있었다. 복습노트에서 케이스를 누르면 바로 판독 화면으로
갔고, 해설을 다시 보려면 또 제출해야 했다 — 틀린 것을 복습하러 와서 무엇을 틀렸는지
못 보고 다시 칠하는 구조였다.

여기서 고정하는 것
----------------
  - **제출한 적이 있어야만** 기준 마스크가 나간다 (없으면 404).
    이 경로로 아직 풀지 않은 케이스의 정답을 미리 볼 수 없어야 한다
    (`test_gt_not_leaked_before_submit.py` 와 같은 불변조건이다)
  - 남의 제출로 남의 케이스 정답을 볼 수 없다
  - 해설은 **제출 시점 스냅샷**을 쓴다 — 전문가가 나중에 소견을 고쳐도
    그때 본 것은 그때 것이다
  - 사용자가 칠한 마스크는 **저장하지 않는다**. 응답이 그렇게 밝힌다
"""
CASE_ID = "VS-SEG-202"


def submit(user, case_id, roi):
    return user.post(f"/api/cases/{case_id}/submit", {"roi": roi, "duration_seconds": 30})


# --------------------------------------------------------- 노출 경계
def test_without_a_submission_there_is_no_detail(user_a):
    """**아직 풀지 않았으면 기준 마스크를 볼 수 없다.** 이게 이 화면의 보안 경계다."""
    response = user_a.get(f"/api/wrong-notes/{CASE_ID}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NO_SUBMISSION"
    assert "mask" not in response.text.lower()


def test_another_users_submission_does_not_open_the_answer(user_a, user_b, roi_mismatch):
    """user_a 가 풀었다고 해서 user_b 가 정답을 볼 수는 없다."""
    assert submit(user_a, CASE_ID, roi_mismatch).status_code == 200

    response = user_b.get(f"/api/wrong-notes/{CASE_ID}")
    assert response.status_code == 404


def test_after_submitting_the_reference_mask_is_available(user_a, roi_mismatch):
    """제출한 뒤에는 기준을 봐야 학습이 된다 (제출 응답에서 이미 받은 것과 같은 값)."""
    submit(user_a, CASE_ID, roi_mismatch)

    payload = user_a.get(f"/api/wrong-notes/{CASE_ID}").json()
    assert payload["reference_mask_url"], "제출 뒤에도 기준을 못 보면 복습이 안 된다"
    assert "mask" in payload["reference_mask_url"].lower()
    assert payload["image_url"]


# --------------------------------------------------------- 내용
def test_it_carries_the_latest_attempt_and_history(user_a, roi_mismatch, roi_match):
    submit(user_a, CASE_ID, roi_mismatch)
    submit(user_a, CASE_ID, roi_match)

    payload = user_a.get(f"/api/wrong-notes/{CASE_ID}").json()
    latest = payload["latest"]

    assert latest["grade"] == "match", "가장 최근 제출이 나와야 한다"
    assert latest["attempt_number"] == 2
    assert payload["attempts"] == 2
    # 최고 기록은 **자기 기록**이다 (케이스 난이도가 아니다)
    assert payload["best_dice"] is not None


def test_the_explanation_is_the_snapshot_from_submission_time(user_a, roi_mismatch):
    """
    전문가가 나중에 소견을 고쳐도 **이 학습자가 그때 본 것**이 남아야 한다.
    `submissions.explanation` 이 그래서 있는 컬럼이다.
    """
    submit(user_a, CASE_ID, roi_mismatch)
    payload = user_a.get(f"/api/wrong-notes/{CASE_ID}").json()

    assert payload["explanation"] is not None
    # 출처 구분은 그대로 유지된다 (문헌 일반론과 케이스 소견을 섞지 않는다)
    assert "content_levels" in payload["explanation"]


def test_it_says_the_user_mask_is_not_kept(user_a, roi_mismatch):
    """**없는 것을 있는 것처럼 그리지 않는다.** 사용자가 칠한 마스크는 저장하지 않는다."""
    submit(user_a, CASE_ID, roi_mismatch)
    assert user_a.get(f"/api/wrong-notes/{CASE_ID}").json()["user_mask_kept"] is False


def test_login_is_required(client):
    assert client.get(f"/api/wrong-notes/{CASE_ID}").status_code == 401
