"""
모델 평가 (Phase 7 / RELEASE_READINESS M4).

이 도구의 존재 이유는 **평균 Dice 하나로 판단하지 않기 위해서**다.
실제 모델은 5케이스가 0.94 부근이고 1케이스가 0.0 인데, 평균 0.79 만 보면
"전반적으로 조금 부정확한 모델"로 잘못 읽힌다.

그래서 확인하는 것:
  - 검출률과 미검출 목록이 따로 나오는가
  - 전체 Dice 와 '검출된 것만의 Dice' 가 구분되는가
  - 크기 구간별로 성능이 갈라져 보이는가
  - 버전 비교에서 **평균이 올라도 회귀를 잡아내는가**
  - 모델 평가가 채점에 개입하지 않는가
"""
import pytest

from scripts.evaluate_model import compare, evaluate


def _case(case_id, gt, dice, detected=True, bucket="medium", slice_dice=None):
    return {
        "case_id": case_id,
        "gt_voxels": gt,
        "size_bucket_relative": bucket,
        "model_version": "test-model-v1",
        "ai_detected": detected,
        "ai_dice": dice,
        "ai_representative_slice_dice": slice_dice,
        "false_negative_voxels": 0 if dice == 1.0 else gt // 10,
        "false_positive_voxels": 0,
    }


# 실제 VS-SEG 분포를 본뜬 세트 — 대부분 잘 맞히고 하나를 완전히 놓친다
REALISTIC = [
    _case("A", 3628, 0.0, detected=False, bucket="small"),
    _case("B", 5178, 0.9485, bucket="small"),
    _case("C", 8436, 0.9621, bucket="medium"),
    _case("D", 10890, 0.9509, bucket="medium"),
    _case("E", 12812, 0.9384, bucket="large"),
    _case("F", 15722, 0.9439, bucket="large"),
]


# ------------------------------------------------- 평균 하나로 요약하지 않는다
def test_detection_rate_is_reported_separately_from_dice():
    report = evaluate(REALISTIC)

    assert report["detection"]["detection_rate"] == pytest.approx(5 / 6, abs=1e-4)
    assert report["detection"]["missed"] == 1
    assert report["detection"]["missed_cases"][0]["case_id"] == "A"
    # 미검출 케이스의 크기를 함께 알려준다 (원인 추적의 출발점)
    assert report["detection"]["missed_cases"][0]["gt_voxels"] == 3628


def test_dice_is_split_into_all_and_detected_only():
    """이 구분이 없으면 '가끔 완전히 놓치는 모델'을 '전반적으로 부정확한 모델'로 오해한다."""
    report = evaluate(REALISTIC)

    assert report["dice_all_cases"]["mean"] < 0.85       # 미검출에 끌려 내려간 값
    assert report["dice_detected_only"]["mean"] > 0.93   # 찾았을 때의 실제 정확도
    assert report["dice_all_cases"]["min"] == 0.0
    assert report["dice_detected_only"]["min"] > 0.9


def test_median_reveals_distribution_shape():
    report = evaluate(REALISTIC)
    # 중앙값이 평균보다 훨씬 높다 = 소수의 실패가 평균을 끌어내린 형태
    assert report["dice_all_cases"]["median"] > report["dice_all_cases"]["mean"]


# ------------------------------------------------------------ 크기 구간별 분석
def test_size_stratified_performance_isolates_the_failure():
    """미검출이 특정 크기에 몰리는지 보여야 한다 (실제로 몰려 있다)."""
    report = evaluate(REALISTIC)
    by_size = report["by_lesion_size"]

    assert by_size["small"]["detection_rate"] == 0.5
    assert by_size["medium"]["detection_rate"] == 1.0
    assert by_size["large"]["detection_rate"] == 1.0
    assert by_size["small"]["gt_voxels_range"] == [3628, 5178]


def test_empty_size_bucket_is_omitted():
    report = evaluate([_case("A", 100, 0.9, bucket="medium")])
    assert "small" not in report["by_lesion_size"]
    assert "large" not in report["by_lesion_size"]


# -------------------------------------------------------------- 집계 규칙
def test_cases_without_prediction_are_excluded_not_zeroed():
    """예측이 없는 것을 0 으로 세면 모델이 실제보다 나빠 보인다."""
    rows = REALISTIC + [
        {
            "case_id": "NEW",
            "gt_voxels": 999,
            "size_bucket_relative": "small",
            "model_version": None,
            "ai_detected": None,
            "ai_dice": None,
            "ai_representative_slice_dice": None,
            "false_negative_voxels": None,
            "false_positive_voxels": None,
        }
    ]
    report = evaluate(rows)

    assert report["evaluated_cases"] == 6
    assert report["cases_without_prediction"] == ["NEW"]
    assert report["dice_all_cases"]["count"] == 6


def test_empty_input_does_not_crash():
    report = evaluate([])
    assert report["evaluated_cases"] == 0
    assert report["detection"]["detection_rate"] is None
    assert report["dice_all_cases"] is None


# --------------------------------------------- 버전 비교: 가짜 개선을 잡는다 (핵심)
def test_comparison_flags_regression_even_when_mean_improves(capsys):
    """평균 Dice 가 올라도 '검출하던 것을 놓친' 것은 개선이 아니다."""
    baseline = evaluate(REALISTIC)

    changed = [dict(c) for c in REALISTIC]
    for case in changed:
        if case["case_id"] == "A":       # 놓치던 것을 찾았고
            case["ai_detected"], case["ai_dice"] = True, 0.80
        if case["case_id"] == "E":       # 잘 찾던 것을 놓쳤다
            case["ai_detected"], case["ai_dice"] = False, 0.0
    current = evaluate(changed)

    # 평균은 오히려 떨어지지 않았는데도
    compare(current, baseline)
    output = capsys.readouterr().out

    assert "[회귀]" in output
    assert "E" in output


def test_comparison_reports_new_cases(capsys):
    baseline = evaluate(REALISTIC)
    current = evaluate(REALISTIC + [_case("G", 7000, 0.91)])

    compare(current, baseline)
    assert "신규" in capsys.readouterr().out


def test_comparison_without_regression_is_quiet_about_it(capsys):
    baseline = evaluate(REALISTIC)
    improved = [dict(c) for c in REALISTIC]
    for case in improved:
        if case["case_id"] == "A":
            case["ai_detected"], case["ai_dice"] = True, 0.85

    compare(evaluate(improved), baseline)
    output = capsys.readouterr().out
    assert "[회귀]" not in output


# --------------------------------------- 모델 평가는 채점에 개입하지 않는다 (핵심)
def test_evaluation_module_never_touches_grading_or_db():
    import scripts.evaluate_model as module

    with open(module.__file__, encoding="utf-8") as f:
        source = f.read()

    for forbidden in ("SessionLocal", "from app.models", "evaluate_submission", "db.commit"):
        assert forbidden not in source, f"모델 평가 도구가 채점/DB 에 손댄다: {forbidden}"


def test_report_states_grading_independence():
    """리포트를 읽는 사람이 '이 숫자가 채점 기준'이라고 오해하면 안 된다."""
    import scripts.evaluate_model as module

    with open(module.__file__, encoding="utf-8") as f:
        source = f.read()
    assert "채점" in source and "전문가 GT" in source
