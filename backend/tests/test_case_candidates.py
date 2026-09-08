"""
케이스 후보 분석 (Phase 6 / RELEASE_READINESS M3).

이 도구의 목적은 "콘텐츠를 늘리기 전에 편향을 드러내는 것"이다.
그래서 확인하는 것:
  - 계산이 맞는가 (FN/FP 를 마스크 재로딩 없이 Dice 에서 복원한다)
  - **의료적 난이도를 자동으로 채우지 않는가** (difficulty 는 항상 None)
  - 상대 크기가 '이 세트 안에서의 상대값'으로만 쓰이는가
  - DB 를 건드리지 않는가
"""
import json

import pytest

from scripts.analyze_case_candidates import (
    SIZE_BUCKETS,
    assign_size_buckets,
    collect_case,
    overlap_from_dice,
    summarize,
)


def _row(case_id: str, gt: int, **kw) -> dict:
    row = {
        "case_id": case_id,
        "gt_voxels": gt,
        "laterality": kw.get("laterality", "right"),
        "ai_detected": kw.get("ai_detected"),
        "ai_dice": kw.get("ai_dice"),
        "difficulty": None,
    }
    return row


# --------------------------------------------------------------- 교집합 복원
def test_overlap_is_recovered_from_dice():
    """dice = 2I/(G+P) 에서 I 를 되돌린다 — 수백 MB npy 를 다시 읽지 않기 위함이다."""
    gt, pred, intersection = 1000, 800, 700
    dice = 2 * intersection / (gt + pred)
    assert overlap_from_dice(dice, gt, pred) == intersection


def test_overlap_handles_total_miss():
    assert overlap_from_dice(0.0, 3628, 0) == 0


def test_overlap_returns_none_without_dice():
    assert overlap_from_dice(None, 100, 100) is None


# ------------------------------------------------------------- 상대 크기 분류
def test_size_buckets_are_relative_to_the_set():
    rows = [_row(f"C{i}", gt) for i, gt in enumerate([100, 200, 300, 400, 500, 600])]
    assign_size_buckets(rows)

    by_id = {r["case_id"]: r["size_bucket_relative"] for r in rows}
    assert by_id["C0"] == "small"
    assert by_id["C5"] == "large"
    assert set(by_id.values()) <= set(SIZE_BUCKETS)


def test_same_sizes_in_a_different_set_get_different_buckets():
    """같은 병변이라도 세트가 바뀌면 상대 위치가 달라진다 — 절대 기준이 아니라는 증거."""
    small_set = [_row("A", 500), _row("B", 5000), _row("C", 50000)]
    assign_size_buckets(small_set)
    a_alone = {r["case_id"]: r["size_bucket_relative"] for r in small_set}["A"]

    with_smaller = [_row("A", 500), _row("X", 10), _row("Y", 20), _row("Z", 30)]
    assign_size_buckets(with_smaller)
    a_with_smaller = {r["case_id"]: r["size_bucket_relative"] for r in with_smaller}["A"]

    assert a_alone == "small"
    assert a_with_smaller == "large"


def test_tiny_set_avoids_overinterpretation():
    """케이스가 3개 미만이면 3분위에 의미가 없다."""
    rows = [_row("A", 100), _row("B", 900)]
    assign_size_buckets(rows)
    assert all(r["size_bucket_relative"] == "medium" for r in rows)


def test_zero_gt_case_is_not_bucketed():
    rows = [_row("A", 0), _row("B", 100), _row("C", 200), _row("D", 300)]
    assign_size_buckets(rows)
    assert {r["case_id"]: r["size_bucket_relative"] for r in rows}["A"] is None


# ---------------------------------------------- 난이도를 자동 판정하지 않는다 (핵심)
def test_difficulty_is_never_filled_automatically(tmp_path):
    """의료적 난이도는 전문가 검토 대상이다. 계산으로 확정하면 안 된다."""
    case_dir = tmp_path / "TEST-001"
    case_dir.mkdir()
    (case_dir / "export_meta.json").write_text(
        json.dumps(
            {
                "case_id": "TEST-001",
                "gt_voxels": 1234,
                "representative_slice": 30,
                "representative_area_px": 300,
                "lesion_slice_count": 5,
                "lesion_slice_min": 28,
                "lesion_slice_max": 32,
                "shape": [512, 512, 120],
                "laterality": {"laterality": "left"},
                "chosen_roi": "TV",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    row = collect_case(case_dir)
    assert row["difficulty"] is None
    assert row["laterality"] == "left"
    assert row["gt_voxels"] == 1234

    rows = [row, _row("B", 10), _row("C", 99999)]
    assign_size_buckets(rows)
    assert all(r["difficulty"] is None for r in rows), "난이도가 자동으로 채워졌다"


def test_collect_case_returns_none_without_meta(tmp_path):
    empty = tmp_path / "EMPTY"
    empty.mkdir()
    assert collect_case(empty) is None


# ------------------------------------------------------------------- 요약 통계
def test_summary_surfaces_laterality_bias():
    """편향을 드러내는 것이 이 도구의 존재 이유다."""
    rows = [_row(f"C{i}", 100 * (i + 1), laterality="right") for i in range(5)]
    rows.append(_row("C5", 600, laterality="left"))
    assign_size_buckets(rows)

    summary = summarize(rows)
    assert summary["laterality"] == {"left": 1, "right": 5}
    assert summary["case_count"] == 6


def test_summary_reports_missed_cases():
    rows = [
        _row("A", 100, ai_detected=True, ai_dice=0.9),
        _row("B", 200, ai_detected=False, ai_dice=0.0),
    ]
    summary = summarize(rows)

    assert summary["ai_detected"] == 1
    assert summary["ai_missed"] == 1
    assert summary["ai_missed_cases"] == ["B"]
    assert summary["ai_mean_dice"] == pytest.approx(0.45)


def test_summary_without_predictions_does_not_crash():
    rows = [_row("A", 100), _row("B", 200)]
    summary = summarize(rows)
    assert summary["ai_mean_dice"] is None
    assert summary["ai_missed_cases"] == []


# ---------------------------------------------------------------- DB 미변경
def test_analysis_module_does_not_touch_db():
    """읽기 전용 도구다 — DB 세션이나 모델을 끌어오지 않는다."""
    import scripts.analyze_case_candidates as module

    source = module.__file__
    with open(source, encoding="utf-8") as f:
        text = f.read()
    for forbidden in ("SessionLocal", "db.commit", "from app.models"):
        assert forbidden not in text, f"분석 도구가 DB 를 건드린다: {forbidden}"
