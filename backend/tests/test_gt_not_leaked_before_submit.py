"""
**제출 전에 정답(전문가 GT)이 새지 않는가.**

==========================================================================
이게 새면 학습이 성립하지 않는다.
==========================================================================
학습자가 판독하기 전에 기준 마스크를 볼 수 있으면, 이 서비스는 훈련 도구가
아니라 따라 그리기가 된다. 점수도 학습 이력도 의미를 잃는다.

새어 나갈 수 있는 경로는 셋이다:
  1. **케이스 상세 응답** — 마스크 URL·병변 위치·소견이 섞여 들어가는 경우
  2. **자산 URL 추측** — `slice_035.png` 옆에 `mask_035.png` 가 있다
  3. **slice 목록** — 마스크 파일이 slice 목록에 섞여 들어가는 경우

기능을 추가하다 보면 1번이 가장 쉽게 깨진다. 해설을 케이스 상세에 붙이거나,
"편측성을 미리 알려주자" 같은 편의 기능이 곧 정답 노출이다.
"""
import json

import pytest

CASE_ID = "VS-SEG-202"

# 케이스 상세에 **있으면 안 되는** 것들. 값이 아니라 필드 이름으로 본다 —
# 값은 케이스마다 다르지만 이름은 계약이다.
FORBIDDEN_FIELDS = [
    ("reference_mask_url", "기준 마스크 주소"),
    ("mask_url", "마스크 주소"),
    ("ground_truth", "전문가 GT"),
    ("gt_voxels", "GT 크기"),
    ("lesion_slice_range", "병변이 있는 slice 범위"),
    ("lesion_slice_min", "병변 시작 slice"),
    ("lesion_slice_max", "병변 끝 slice"),
    ("representative_area_px", "병변 면적"),
    ("laterality", "좌/우 편측성"),
    ("reference_region", "기준 영역 설명"),
    ("case_facts", "데이터셋 확인 사실 (해설 블록)"),
    ("case_findings", "전문가 소견"),
    ("explanation", "해설 전체"),
    ("spatial_feedback", "공간 피드백"),
]


@pytest.fixture
def detail(user_a):
    response = user_a.get(f"/api/cases/{CASE_ID}")
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------- 1. 케이스 상세 응답
@pytest.mark.parametrize("field,what", FORBIDDEN_FIELDS)
def test_case_detail_does_not_carry(detail, field, what):
    """**편의 기능이 곧 정답 노출이 되는 자리다.**

    "편측성을 미리 알려주면 친절하지 않을까" 같은 생각이 이 검사에 걸린다.
    """
    assert field not in json.dumps(detail, ensure_ascii=False), (
        f"케이스 상세에 {field}({what}) 가 들어 있다 — 제출 전에는 보여주면 안 된다"
    )


def test_case_detail_still_has_what_the_screen_needs(detail):
    """**너무 막아도 안 된다.** 판독 화면이 그릴 수 없으면 그것도 고장이다."""
    assert detail["image_url"], "영상이 없으면 판독할 수 없다"
    assert detail["image_meta"]["width"] > 0, "캔버스 크기를 알아야 좌표가 맞는다"
    # `representative_slice` 는 volume 케이스에만 있다 (단일 영상 케이스는 null).
    # 있다면 slice 목록 안의 값이어야 한다.
    if detail.get("representative_slice") is not None:
        indexes = [s["slice_index"] for s in detail["slices"]]
        assert detail["representative_slice"] in indexes


def test_slice_list_only_carries_slice_images(detail):
    """slice 목록에 마스크가 섞이면 그대로 정답이 보인다."""
    for entry in detail["slices"]:
        assert set(entry) == {"slice_index", "image_url"}, f"예상 밖의 필드: {sorted(entry)}"
        assert "mask" not in entry["image_url"].lower(), (
            f"slice 목록에 마스크가 있다: {entry['image_url']}"
        )


# ------------------------------------------------------ 2. 자산 접근 통제
# 서명 검사는 `/static/cases/` 에만 걸린다 (app/asset_urls.PROTECTED_PREFIX).
# **테스트 DB 의 케이스는 합성 fixture 라 그 밖(`/static/images/`)에 있다** —
# 그래서 여기서는 케이스 응답의 주소가 아니라 **미들웨어 자체**를 확인한다.
# "실제 케이스가 보호 경로 안에 있는가"는 배포 점검이 본다
# (`deploy_preflight.check_content` 의 "자산 접근 보호").
PROTECTED_SAMPLE = "/static/cases/VS-SEG-999/slices/mask_001.png"


def test_a_protected_path_is_refused_without_a_signature(client):
    """**파일이 있든 없든 서명이 먼저다.** 없으면 존재 여부조차 알려주지 않는다."""
    response = client.get(PROTECTED_SAMPLE)
    assert response.status_code == 403, "서명 없이 케이스 자산을 가져갈 수 있다"


def test_a_forged_signature_is_refused(client):
    response = client.get(f"{PROTECTED_SAMPLE}?e=9999999999&s={'de' * 16}")
    assert response.status_code == 403, "아무 서명이나 통과한다"


def test_an_expired_signature_is_refused(client):
    from app import asset_urls

    # 아주 오래전 시점으로 서명하면 만료 시각도 그만큼 과거가 된다
    signed = asset_urls.add_signature(PROTECTED_SAMPLE, now=1)  # 1970년
    assert client.get(signed).status_code == 403, "만료된 서명이 통과한다"


def test_a_valid_signature_gets_past_the_middleware(client):
    """**막기만 하면 안 된다.** 정당한 서명은 통과해야 결과 화면이 뜬다.

    파일은 없으므로 404 가 정상이다 — 중요한 것은 **403 이 아니라는 것**이다.
    """
    from app import asset_urls

    signed = asset_urls.add_signature(PROTECTED_SAMPLE)
    assert client.get(signed).status_code != 403


def test_the_fixture_assets_live_outside_the_protected_prefix(detail):
    """**이 사실을 기록해 둔다.** 위 테스트들이 왜 케이스 주소를 안 쓰는지의 이유다.

    합성 fixture 는 실제 의료영상이 아니라 보호 대상이 아니다.
    실제 케이스가 이 경로로 등록되면 배포 점검이 차단한다.
    """
    from app.asset_urls import PROTECTED_PREFIX

    url = detail["image_url"]
    assert "/static/" in url
    if PROTECTED_PREFIX in url:
        pytest.skip("이 환경에서는 실제 케이스가 등록돼 있다 (보호 경로 안)")
    assert "/static/images/" in url or "/static/results/" in url


# --------------------------------------------- 3. 제출 뒤에는 나와야 한다
def test_after_submitting_the_reference_mask_is_returned(user_a, roi_mismatch):
    """**제출한 뒤에는 보여줘야 한다.** 비교 없이는 배울 수 없다."""
    response = user_a.submit(roi_mismatch)
    assert response.status_code == 200
    payload = response.json()

    assert payload["reference_mask_url"], "제출 뒤에도 기준을 못 보면 학습이 안 된다"
    assert "mask" in payload["reference_mask_url"].lower()
    assert payload["explanation"], "해설도 제출 뒤에 나온다"


def test_the_returned_mask_url_actually_works(client, user_a, roi_mismatch):
    """서명된 주소는 열려야 한다 — 막기만 하고 못 열면 결과 화면이 빈다."""
    url = user_a.submit(roi_mismatch).json()["reference_mask_url"]
    path = url[url.index("/static/"):]  # 질의 문자열(서명)을 그대로 둔다

    response = client.get(path)
    assert response.status_code == 200, "제출 뒤 받은 서명 주소가 열리지 않는다"
    assert response.headers["content-type"].startswith("image/")
