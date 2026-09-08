"""
공간 피드백 (Phase 3 / RELEASE_READINESS H1).

여기서 지키려는 것 두 가지:

1. **학습적으로 구분이 되는가** — 같은 Dice 라도 "위치는 맞았는데 작게 칠했다"와
   "엉뚱한 곳을 칠했다"는 다른 조언이 나와야 한다.
2. **의료 내용을 지어내지 않는가** — geometry 로 확인되는 것만 말해야 한다.
   내이도·조영증강·종괴 같은 영상 소견 어휘가 자동 생성 문구에 들어가면 실패한다.
"""
import numpy as np
import pytest

from app import feedback, scoring_config
from app.config import ConfigError
from app.grading import _grade_from_dice


def _disk(size: int, cx: int, cy: int, r: int) -> np.ndarray:
    ys, xs = np.ogrid[:size, :size]
    return (xs - cx) ** 2 + (ys - cy) ** 2 <= r**2


SIZE = 200
REFERENCE = _disk(SIZE, 100, 100, 30)


def _codes(user: np.ndarray) -> set[str]:
    return {item["code"] for item in feedback.build(user, REFERENCE)["items"]}


# ------------------------------------------------------- 상황별로 다르게 말하는가
def test_perfect_match_is_reported_as_well_matched():
    result = feedback.build(REFERENCE.copy(), REFERENCE)
    assert "POSITION_ON_TARGET" in {i["code"] for i in result["items"]}
    assert "WELL_MATCHED" in {i["code"] for i in result["items"]}
    assert result["metrics"]["gt_coverage"] == 1.0
    assert result["metrics"]["user_precision"] == 1.0


def test_small_roi_at_right_place_says_position_ok_but_missed_area():
    """위치는 맞았지만 작게 칠한 경우 — 위치를 탓하면 안 된다."""
    codes = _codes(_disk(SIZE, 100, 100, 15))
    assert "POSITION_ON_TARGET" in codes
    assert {"UNDER_SEGMENTED", "SLIGHTLY_UNDER_SEGMENTED"} & codes
    assert "OVER_SEGMENTED" not in codes


def test_large_roi_at_right_place_says_over_segmented():
    codes = _codes(_disk(SIZE, 100, 100, 60))
    assert "POSITION_ON_TARGET" in codes
    assert {"OVER_SEGMENTED", "SLIGHTLY_OVER_SEGMENTED"} & codes


def test_completely_wrong_place_says_off_target():
    codes = _codes(_disk(SIZE, 30, 30, 30))
    assert "POSITION_OFF_TARGET" in codes
    # 겹치지도 않았는데 "일부를 놓쳤다"고 조언하면 오히려 헷갈린다
    assert "SLIGHTLY_UNDER_SEGMENTED" not in codes


def test_shift_within_lesion_radius_still_counts_as_on_target():
    """기준 반지름(30px) 안쪽으로 어긋난 것은 '중심을 맞췄다'로 본다.

    병변 안에서의 18px 이동을 "빗나갔다"고 말하면 학습자가 고칠 것이 없는데도 위치를 의심하게 된다.
    """
    codes = _codes(_disk(SIZE, 118, 100, 30))  # 18px 이동 = 반지름의 0.6배
    assert "POSITION_ON_TARGET" in codes


def test_shift_beyond_lesion_radius_says_near_not_far():
    """반지름의 1~2배 벗어나면 '조금 벗어남'이다 (아직 '크게 벗어남'은 아니다)."""
    codes = _codes(_disk(SIZE, 145, 100, 30))  # 45px 이동 = 반지름의 1.5배
    assert "POSITION_NEAR" in codes
    assert "POSITION_FAR" not in codes
    assert "POSITION_ON_TARGET" not in codes


def test_same_dice_can_produce_different_advice():
    """이 모듈의 존재 이유 — 같은 점수라도 조언이 갈려야 한다."""
    from app.masks import dice_iou

    small_centered = _disk(SIZE, 100, 100, 18)
    shifted_same_size = _disk(SIZE, 128, 100, 30)

    dice_small, _ = dice_iou(small_centered, REFERENCE)
    dice_shifted, _ = dice_iou(shifted_same_size, REFERENCE)
    assert abs(dice_small - dice_shifted) < 0.15  # 점수는 비슷한데

    assert _codes(small_centered) != _codes(shifted_same_size)  # 조언은 다르다


# ------------------------------------------------------------------ 지표 계산
def test_metrics_are_pure_geometry():
    user = _disk(SIZE, 100, 100, 15)
    m = feedback.compute_metrics(user, REFERENCE)

    assert 0.0 <= m["gt_coverage"] <= 1.0
    assert m["user_precision"] == pytest.approx(1.0, abs=0.02)  # 전부 기준 안쪽
    assert m["area_ratio"] < 1.0
    assert m["under_segmentation_ratio"] > 0
    assert m["over_segmentation_ratio"] == pytest.approx(0.0, abs=0.02)
    assert m["centroid_distance_px"] == pytest.approx(0.0, abs=1.0)
    assert m["reference_area_px"] == int(REFERENCE.sum())


def test_centroid_distance_is_normalized_by_lesion_size():
    """작은 병변에서 10px 어긋난 것과 큰 병변에서 10px 어긋난 것은 의미가 다르다."""
    small_ref = _disk(SIZE, 100, 100, 10)
    large_ref = _disk(SIZE, 100, 100, 50)
    shift = _disk(SIZE, 110, 100, 10)
    shift_large = _disk(SIZE, 110, 100, 50)

    small = feedback.compute_metrics(shift, small_ref)["centroid_distance_normalized"]
    large = feedback.compute_metrics(shift_large, large_ref)["centroid_distance_normalized"]
    assert small > large


def test_empty_reference_does_not_crash():
    empty = np.zeros((SIZE, SIZE), dtype=bool)
    result = feedback.build(_disk(SIZE, 100, 100, 10), empty)
    assert result["metrics"]["gt_coverage"] is None
    assert result["primary_message"]  # 빈 문자열이 아니라 뭔가 말은 해준다


def test_mask_of_different_size_is_aligned():
    """프론트 캔버스 크기가 기준 마스크와 달라도 계산돼야 한다."""
    user_small = _disk(100, 50, 50, 15)  # 절반 크기
    m = feedback.compute_metrics(user_small, REFERENCE)
    assert m["gt_coverage"] is not None and m["gt_coverage"] > 0


# ---------------------------------------------- 의료 내용을 지어내지 않는가 (핵심)
FORBIDDEN_MEDICAL_WORDS = [
    "내이도", "소뇌교각", "조영", "증강", "종괴", "종양", "낭성", "신경",
    "병변으로 보입니다", "진단", "의심", "소견상", "추정",
    "schwannoma", "tumor", "lesion is", "enhancement",
]


@pytest.mark.parametrize(
    "user",
    [
        REFERENCE.copy(),
        _disk(SIZE, 100, 100, 15),
        _disk(SIZE, 100, 100, 60),
        _disk(SIZE, 30, 30, 30),
        _disk(SIZE, 118, 100, 30),
        np.zeros((SIZE, SIZE), dtype=bool),
    ],
)
def test_messages_never_contain_medical_claims(user):
    """자동 생성 문구는 **geometry 만** 말한다.

    영상 소견·질환 추정은 전문가가 쓴 case_findings 자리다. 여기서 새어 나오면
    출처 없는 의료 내용이 서비스에 나가는 것이므로 반드시 실패해야 한다.
    """
    result = feedback.build(user, REFERENCE)
    texts = [result["primary_message"], *[i["message"] for i in result["items"]]]

    for text in texts:
        lowered = text.lower()
        for word in FORBIDDEN_MEDICAL_WORDS:
            assert word.lower() not in lowered, f"의료 내용이 자동 생성 문구에 들어갔다: {word!r} in {text!r}"


def test_feedback_declares_geometry_source():
    """응답을 받는 쪽이 전문가 소견과 구분할 수 있어야 한다."""
    assert feedback.build(REFERENCE.copy(), REFERENCE)["source"] == "geometry"


# ------------------------------------------------------- 채점에 관여하지 않는다
def test_feedback_does_not_change_grade():
    """spatial_feedback 은 설명일 뿐 판정 기준이 아니다."""
    user = _disk(SIZE, 100, 100, 15)
    from app.masks import dice_iou

    dice, _ = dice_iou(user, REFERENCE)
    grade_before = _grade_from_dice(dice)
    feedback.build(user, REFERENCE)  # 피드백을 만들어도
    assert _grade_from_dice(dice) == grade_before  # 판정은 그대로다


# --------------------------------------------------------- 임계값 config 분리
def test_thresholds_come_from_config():
    assert scoring_config.match_dice() == scoring_config.DEFAULT_MATCH_DICE
    assert scoring_config.partial_dice() == scoring_config.DEFAULT_PARTIAL_DICE
    assert scoring_config.thresholds()["validation_status"] == "not_yet_educationally_validated"


def test_thresholds_can_be_overridden_for_user_testing(monkeypatch):
    """사용자 테스트에서 값을 바꿔 볼 수 있어야 한다."""
    monkeypatch.setenv("MEDISCAN_MATCH_DICE", "0.75")
    assert scoring_config.match_dice() == 0.75
    assert _grade_from_dice(0.70) == "partial_match"  # 기본값(0.60)이면 match 였을 값
    assert _grade_from_dice(0.80) == "match"


def test_invalid_threshold_env_is_rejected_not_silently_ignored(monkeypatch):
    """오타가 조용히 채점 기준을 무너뜨리면 안 된다.

    예전에는 기본값으로 되돌렸는데, 그게 바로 "조용히" 다.
    `MEDISCAN_MATCH_DICE=75`(75%를 의도) 를 넣으면 범위 밖이라 0.60 으로 채점되고
    운영자는 0.75 인 줄 안다. 되돌리지 말고 막는다.
    """
    monkeypatch.setenv("MEDISCAN_MATCH_DICE", "매치")
    with pytest.raises(ConfigError):
        scoring_config.match_dice()

    monkeypatch.setenv("MEDISCAN_MATCH_DICE", "75")  # 0.75 를 의도한 백분율 오입력
    with pytest.raises(ConfigError) as exc:
        scoring_config.match_dice()
    assert "0.75" in str(exc.value), "무엇을 적어야 하는지 알려줘야 한다"


def test_reversed_thresholds_are_rejected(monkeypatch):
    """partial > match 면 partial_match 판정이 통째로 도달 불가능해진다.

    응답 형태는 멀쩡해서 등급 하나가 사라진 것을 알아채기 어렵다.
    부분적으로 맞게 그린 학습자가 전부 mismatch 를 받게 된다.
    """
    monkeypatch.setenv("MEDISCAN_MATCH_DICE", "0.60")
    monkeypatch.setenv("MEDISCAN_PARTIAL_DICE", "0.80")

    # 실제로 등급이 사라지는지 먼저 확인한다 (가드가 막는 것이 진짜 문제인지)
    grades = {_grade_from_dice(d) for d in (0.05, 0.3, 0.5, 0.7, 0.95)}
    assert "partial_match" not in grades

    with pytest.raises(ConfigError):
        scoring_config.assert_valid()


def test_equal_thresholds_are_allowed(monkeypatch):
    # partial == match 는 "부분 일치를 쓰지 않는다"는 뜻이라 모순이 아니다.
    monkeypatch.setenv("MEDISCAN_MATCH_DICE", "0.60")
    monkeypatch.setenv("MEDISCAN_PARTIAL_DICE", "0.60")
    scoring_config.assert_valid()


def test_default_thresholds_are_self_consistent():
    # 기본값이 스스로 모순이면 아무도 기동하지 못한다.
    scoring_config.assert_valid()
