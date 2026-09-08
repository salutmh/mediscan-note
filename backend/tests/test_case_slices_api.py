"""
케이스 상세의 slice 목록 (화면 2 slice 탐색).

**가장 중요한 것: 정답을 흘리지 않는가.**
어느 slice 에 기준 마스크가 있는지는 곧 병변 위치다. `has_mask` 같은 불리언 하나만 있어도
학습자는 병변이 몇 번 slice 에 있는지 즉시 알게 되고, "찾는" 훈련이 아니라
"표시된 곳을 칠하는" 작업이 된다. 그래서 채점 전에는 마스크와 관련된 어떤 정보도 나가면 안 된다.
"""
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Case, CaseSlice
from tests.conftest import CASE_ID


def _detail(user):
    res = user.get(f"/api/cases/{CASE_ID}")
    assert res.status_code == 200, res.text
    return res.json()


# ------------------------------------------------- 정답 누출 방지 (핵심)
def test_slice_list_never_exposes_mask_information(user_a):
    detail = _detail(user_a)

    for item in detail["slices"]:
        assert set(item.keys()) == {"slice_index", "image_url"}, (
            f"slice 응답에 예상 밖 필드가 있다: {sorted(item.keys())} — "
            "마스크 관련 정보는 정답 위치를 알려주는 것과 같다"
        )


def test_slice_list_has_no_lesion_hints_anywhere_in_payload(user_a):
    """필드명이 달라도 마스크/병변 정보가 새면 안 된다."""
    import json

    payload = json.dumps(_detail(user_a)["slices"]).lower()
    for leaked in ("mask", "lesion", "area_px", "has_", "gt"):
        assert leaked not in payload, f"slice 목록에 '{leaked}' 정보가 들어 있다"


def test_representative_slice_is_not_marked_inside_slice_items(user_a):
    """대표 slice 는 최상위 필드로만 알려준다.

    항목마다 표시하면 '여기가 병변이 가장 큰 곳'을 목록에서 바로 읽을 수 있다.
    (최상위 representative_slice 는 ROI 를 어디에 그려야 하는지 알려주기 위해 필요하다 —
    이건 정답 위치가 아니라 '입력 위치'다.)
    """
    detail = _detail(user_a)
    for item in detail["slices"]:
        assert "representative" not in json_keys(item)


def json_keys(item) -> str:
    return " ".join(item.keys())


# ------------------------------------------------------------- 내용 정확성
def test_slices_match_registered_case_slices(user_a):
    detail = _detail(user_a)

    with SessionLocal() as db:
        rows = db.scalars(
            select(CaseSlice).where(CaseSlice.case_id == CASE_ID).order_by(CaseSlice.slice_index)
        ).all()
        expected = [r.slice_index for r in rows]

    assert [s["slice_index"] for s in detail["slices"]] == expected


def test_slices_preserve_original_volume_indices(user_a):
    """0부터 다시 매기지 않는다 — 해설의 slice 번호와 같아야 한다."""
    detail = _detail(user_a)
    indices = [s["slice_index"] for s in detail["slices"]]
    if not indices:
        return
    assert indices == sorted(indices)
    assert indices[0] >= 0
    # 등록 범위는 볼륨 전체가 아니라 병변 주변이다
    assert len(indices) <= (detail["image_meta"].get("total_slices") or len(indices))


def test_representative_slice_is_inside_the_slice_list(user_a):
    """ROI 를 그릴 slice 가 목록에 없으면 화면이 아무 데도 갈 수 없다."""
    detail = _detail(user_a)
    if not detail["slices"]:
        return
    indices = [s["slice_index"] for s in detail["slices"]]
    assert detail["representative_slice"] in indices


def test_slice_image_urls_are_absolute(user_a):
    detail = _detail(user_a)
    for item in detail["slices"]:
        assert item["image_url"].startswith("http"), "프론트가 다른 포트에서 부르므로 절대 URL 이어야 한다"


# ------------------------------------------------------------- 경계 상황
def test_case_without_slices_returns_empty_list(user_a):
    """단일 영상 케이스(흉부 X-ray 등)도 화면이 깨지지 않아야 한다."""
    with SessionLocal() as db:
        case = db.scalars(select(Case).where(Case.case_id != CASE_ID)).first()
        if case is None:
            return
        target = case.case_id
        has_slices = db.scalar(
            select(CaseSlice.id).where(CaseSlice.case_id == target)
        )

    res = user_a.get(f"/api/cases/{target}")
    if res.status_code != 200:
        return
    body = res.json()
    assert isinstance(body["slices"], list)
    if not has_slices:
        assert body["slices"] == []


def test_slice_list_requires_authentication(client):
    assert client.get(f"/api/cases/{CASE_ID}").status_code == 401
