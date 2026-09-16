"""
복습노트 / 학습 상태 테스트 (API 계약 v0.4).

핵심: has_matched(학습완료)와 needs_review(복습필요)는 **서로 배타적이지 않다.**
맞힌 뒤 다시 틀리면 둘 다 true 가 된다 — v0.2 의 `solved` 하나로 뭉쳐서 생기던
"화면 1은 해결인데 복습노트에도 있는" 모순을 이렇게 해소한다.
"""
from tests.conftest import CASE_ID


def _flags(user, case_id: str = CASE_ID) -> dict:
    row = next(c for c in user.get("/api/cases").json()["cases"] if c["case_id"] == case_id)
    return {"has_matched": row["has_matched"], "needs_review": row["needs_review"]}


def _wrong_note_ids(user) -> list[str]:
    return [i["case_id"] for i in user.get("/api/wrong-notes").json()["items"]]


# --------------------------------------------------- 상태 매트릭스 (핵심)
def test_untouched_case_has_no_state(user_a):
    assert _flags(user_a) == {"has_matched": False, "needs_review": False}
    assert _wrong_note_ids(user_a) == []


def test_match_only(user_a, roi_match):
    user_a.submit(roi_match)
    assert _flags(user_a) == {"has_matched": True, "needs_review": False}
    assert _wrong_note_ids(user_a) == []


def test_mismatch_only(user_a, roi_mismatch):
    user_a.submit(roi_mismatch)
    assert _flags(user_a) == {"has_matched": False, "needs_review": True}
    assert _wrong_note_ids(user_a) == [CASE_ID]


def test_match_then_mismatch_keeps_both_states(user_a, roi_match, roi_mismatch):
    """맞힌 뒤 다시 틀리면 학습완료는 유지되고 복습필요가 함께 켜진다."""
    user_a.submit(roi_match)
    user_a.submit(roi_mismatch)

    assert _flags(user_a) == {"has_matched": True, "needs_review": True}
    assert _wrong_note_ids(user_a) == [CASE_ID], "최근에 틀렸으므로 복습 대상이다"


def test_mismatch_then_match_clears_review(user_a, roi_mismatch, roi_match):
    """틀린 뒤 맞히면 복습노트에서 빠진다."""
    user_a.submit(roi_mismatch)
    assert _wrong_note_ids(user_a) == [CASE_ID]

    user_a.submit(roi_match)
    assert _flags(user_a) == {"has_matched": True, "needs_review": False}
    assert _wrong_note_ids(user_a) == []


def test_latest_submission_decides_review_state(user_a, roi_match, roi_mismatch):
    """복습 여부는 '최신' 제출로 정해진다 (누적이 아니다)."""
    for roi in (roi_mismatch, roi_match, roi_mismatch, roi_match):
        user_a.submit(roi)
    assert _flags(user_a) == {"has_matched": True, "needs_review": False}
    assert _wrong_note_ids(user_a) == []


# ------------------------------------------------------------- 재도전 경로
def test_retry_uses_same_grading_and_clears_review(user_a, roi_mismatch, roi_match):
    user_a.submit(roi_mismatch)

    res = user_a.post(f"/api/wrong-notes/{CASE_ID}/retry", json={"roi": roi_match})
    assert res.status_code == 200
    body = res.json()
    assert body["grade"] == "match"
    # 재도전 응답도 submit 과 같은 계약을 따른다
    assert body["evaluation"]["method"] == "reference_mask"
    assert body["reference_mask_url"].endswith("_mask.png")

    assert _wrong_note_ids(user_a) == []


def test_retry_on_unknown_case_returns_404(user_a, roi_match):
    res = user_a.post("/api/wrong-notes/NOPE-999/retry", json={"roi": roi_match})
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "CASE_NOT_FOUND"


def test_retry_with_invalid_roi_is_rejected(user_a):
    res = user_a.post(f"/api/wrong-notes/{CASE_ID}/retry", json={"roi": {"type": "brush_mask"}})
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "INVALID_ROI"


# ------------------------------------------------------------ 응답 형식
def test_wrong_note_item_shape(user_a, roi_mismatch):
    user_a.submit(roi_mismatch)
    item = user_a.get("/api/wrong-notes").json()["items"][0]

    assert item["case_id"] == CASE_ID
    assert item["body_part"] == "brain_mri"
    assert item["grade"] in {"partial_match", "mismatch"}
    # api-spec 0절: ISO 8601 + KST 오프셋
    assert item["attempted_at"].endswith("+09:00")


def test_partial_match_also_needs_review(user_a):
    """부분 일치도 복습 대상이다."""
    import base64
    import io

    from PIL import Image, ImageDraw

    from tests.conftest import IMAGE_SIZE, LESION

    img = Image.new("RGBA", (IMAGE_SIZE, IMAGE_SIZE), (0, 0, 0, 0))
    r = LESION["r"] // 2
    ImageDraw.Draw(img).ellipse(
        [LESION["cx"] - r, LESION["cy"] - r, LESION["cx"] + r, LESION["cy"] + r],
        fill=(255, 255, 255, 255),
    )
    buf = io.BytesIO()
    img.save(buf, "PNG")
    roi = {
        "type": "brush_mask",
        "points": [[LESION["cx"], LESION["cy"]]],
        "mask_png_base64": base64.b64encode(buf.getvalue()).decode(),
    }

    body = user_a.submit(roi).json()
    assert body["grade"] == "partial_match"
    assert _flags(user_a) == {"has_matched": False, "needs_review": True}
    assert _wrong_note_ids(user_a) == [CASE_ID]


# ------------------------------------------- 과대 표시 복습 (v0.6)
#
# 실제 사용자 walkthrough 에서 나온 문제다: 기준 1,539px 병변에 3,400px(2.2배)을 칠해
# 정상 조직으로 55% 가 넘친 제출이 Dice 0.62 로 `match` 를 받고 **학습완료로 끝났다.**
# 같은 응답의 spatial_feedback 은 그 순간 "경계를 조금 더 좁혀 보세요"라고 말하고 있었다 —
# 피드백과 등급이 다른 말을 하는데 학습 경로가 등급만 따랐다.
#
# 여기서 고정하려는 것: **grade 는 그대로 두고 복습 경로만 바뀐다.**
def test_over_marked_match_is_still_a_match(user_a, roi_over_marked):
    """넓게 칠했다고 **등급을 깎지 않는다.** 병변을 찾은 사실은 그대로다."""
    body = user_a.submit(roi_over_marked).json()

    assert body["grade"] == "match"
    assert body["review"]["reason"] == "over_marked"
    assert body["review"]["area_ratio"] >= body["review"]["review_area_ratio"]


def test_over_marked_match_goes_to_review(user_a, roi_over_marked):
    """일치했어도 지나치게 넓으면 **다시 그려볼 기회**를 준다."""
    user_a.submit(roi_over_marked)

    # 학습완료는 유지되고 복습필요가 함께 켜진다 (두 축은 배타적이지 않다)
    assert _flags(user_a) == {"has_matched": True, "needs_review": True}
    assert _wrong_note_ids(user_a) == [CASE_ID]


def test_review_list_says_why_a_match_is_there(user_a, roi_over_marked):
    """`grade: match` 인 항목이 목록에 있으므로 **이유가 함께 나가야** 한다."""
    user_a.submit(roi_over_marked)
    item = user_a.get("/api/wrong-notes").json()["items"][0]

    assert item["grade"] == "match"
    assert item["review_reason"] == "over_marked"
    assert item["area_ratio"] is not None


def test_tight_match_is_not_sent_to_review(user_a, roi_match):
    """경계를 잘 맞춘 제출은 그대로 끝난다 — 모든 match 를 복습으로 보내지 않는다."""
    body = user_a.submit(roi_match).json()

    assert body["grade"] == "match"
    assert body["review"]["needs_review"] is False
    assert body["review"]["reason"] is None
    assert _wrong_note_ids(user_a) == []


def test_redrawing_tighter_clears_review(user_a, roi_over_marked, roi_match):
    """넓게 칠해 복습에 담긴 뒤, 좁혀서 다시 그리면 빠진다."""
    user_a.submit(roi_over_marked)
    assert _wrong_note_ids(user_a) == [CASE_ID]

    user_a.submit(roi_match)
    assert _wrong_note_ids(user_a) == []
    assert _flags(user_a) == {"has_matched": True, "needs_review": False}


def test_submissions_without_area_ratio_are_not_flagged(user_a, roi_match):
    """area_ratio 를 기록하기 **전에 쌓인 제출**은 복습으로 끌어오지 않는다.

    모르는 값을 "과했다"로도 "괜찮았다"로도 단정하지 않는다. 마이그레이션 직후
    과거 이력이 통째로 복습노트에 쏟아지면, 그건 학습자에게 일어나지 않은 일이다.
    """
    from app.db import SessionLocal
    from app.models import Submission

    user_a.submit(roi_match)
    with SessionLocal() as db:
        row = db.query(Submission).filter(Submission.case_id == CASE_ID).one()
        row.area_ratio = None  # 옛 행을 흉내낸다
        db.commit()

    assert _wrong_note_ids(user_a) == []
    assert _flags(user_a) == {"has_matched": True, "needs_review": False}
