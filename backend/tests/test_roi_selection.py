"""
VS-SEG export 의 종양 ROI 선택 규칙 (scripts/export_vs_seg_npy.py).

배경: 노트북은 키워드에 맞는 ROI 가 없으면 roi_names[0] 을 조용히 골랐다.
211/212 는 ROI 이름이 'AN'(acoustic neuroma)이라 키워드에 걸리지 않았고, 우연히
첫 번째였기 때문에 맞는 마스크가 나왔을 뿐이다. 여기서는 그 우연에 기대지 않는다:
  - AN / acoustic neuroma 를 종양 이름으로 인정한다
  - 그래도 못 찾으면 **중단**한다 (잘못된 ROI 를 채점 기준으로 만드는 것보다 낫다)

pydicom/rt_utils 는 이 함수들에 필요 없다 (지연 import) — 백엔드 venv 에서 그대로 돈다.
"""
import pytest

from scripts.export_vs_seg_npy import (
    RoiSelectionError,
    match_tumor_rois,
    normalize_roi_name,
    select_tumor_roi,
)


# 검수를 마치고 등록한 6케이스의 실제 RTSTRUCT ROI 목록 (export_meta.json 기록).
# 선택 규칙을 바꿔도 이 6개의 결과는 그대로여야 한다.
APPROVED_CASES = {
    "VS-SEG-202": (["TV", "Cochlea", "*Skull"], "TV"),
    "VS-SEG-203": (["TV", "*Skull"], "TV"),
    "VS-SEG-204": (["TV", "*Skull"], "TV"),
    "VS-SEG-207": (["TV", "Cochlea", "*Skull"], "TV"),
    "VS-SEG-211": (["AN", "cochlea", "*Skull"], "AN"),
    "VS-SEG-212": (["AN", "cochlea", "*Skull"], "AN"),
}


@pytest.mark.parametrize("case_id", sorted(APPROVED_CASES))
def test_approved_cases_keep_their_roi(case_id):
    """검수 완료된 6케이스가 규칙 변경 후에도 같은 ROI 를, 지정 없이 자동으로 고르는지."""
    roi_names, expected = APPROVED_CASES[case_id]
    chosen, matched = select_tumor_roi(roi_names)
    assert chosen == expected
    assert matched == [expected], "후보가 정확히 1개여야 자동 선택이 허용된다"


@pytest.mark.parametrize(
    "roi_names, expected",
    [
        # 표기 변형
        (["*Skull", "Tumour Volume"], "Tumour Volume"),
        (["Cochlea", "acoustic_neuroma"], "acoustic_neuroma"),
        (["Brainstem", "Schwannoma"], "Schwannoma"),
        (["Cochlea", "GTV"], "GTV"),
    ],
)
def test_selects_the_tumor_roi(roi_names, expected):
    chosen, _ = select_tumor_roi(roi_names)
    assert chosen == expected


def test_no_keyword_match_stops_instead_of_taking_the_first_roi():
    """옛 동작(roi_names[0] 자동 선택)이 되살아나면 여기서 실패한다."""
    with pytest.raises(RoiSelectionError) as exc:
        select_tumor_roi(["Cochlea", "*Skull", "Brainstem"])

    message = str(exc.value)
    assert "중단" in message
    assert "Cochlea" in message, "사람이 확인할 수 있게 ROI 목록을 보여줘야 한다"
    assert "--roi" in message, "다음에 뭘 하면 되는지 안내해야 한다"


def test_short_abbreviations_do_not_match_inside_other_words():
    """'an' 을 부분일치로 쓰면 Brainstem/Gland/Canal 이 종양으로 잡힌다."""
    assert match_tumor_rois(["Brainstem", "Gland", "Canal", "Cochlea"]) == []


def test_multiple_candidates_stop_instead_of_picking_one():
    """후보가 2개 이상이면 첫 번째를 고르지 않고 중단한다 — 사람이 --roi 로 명시해야 한다."""
    with pytest.raises(RoiSelectionError) as exc:
        select_tumor_roi(["TV", "Tumor_2", "*Skull"])

    message = str(exc.value)
    assert "중단" in message
    assert "TV" in message and "Tumor_2" in message, "후보 목록을 그대로 보여줘야 한다"
    assert "--roi" in message


def test_multiple_candidates_proceed_only_with_explicit_roi():
    chosen, matched = select_tumor_roi(["TV", "Tumor_2", "*Skull"], override="Tumor_2")
    assert (chosen, matched) == ("Tumor_2", ["Tumor_2"])


def test_override_must_exist_in_the_rtstruct():
    chosen, matched = select_tumor_roi(["Cochlea", "*Skull"], override="Cochlea")
    assert (chosen, matched) == ("Cochlea", ["Cochlea"])

    with pytest.raises(RoiSelectionError):
        select_tumor_roi(["Cochlea", "*Skull"], override="TV")


def test_normalize_strips_rtstruct_decorations():
    assert normalize_roi_name("*Skull") == "skull"
    assert normalize_roi_name(" AN_1 ") == "an 1"
    assert normalize_roi_name("Tumour-Volume") == "tumour volume"
