"""
의학용어 사전 API (`GET /api/glossary`) — 화면 2 우측 패널이 쓴다.

고정하려는 규칙:
  - **지어내지 않는다.** 콘텐츠 파일의 `medical_terms` 를 그대로 내보낸다
  - 콘텐츠가 없는 질환은 **에러가 아니라 빈 목록**이다 (아직 안 쓴 것뿐이다)
  - **제출 전에 열려도 기준 마스크가 새지 않는다** — 여기서 나가는 것은 질환 일반
    문헌이고, 이 케이스의 병변 위치·크기·편측성은 들어 있지 않다
  - 로그인 없이는 못 본다 (다른 학습 API 와 같은 취급)
"""
import json

import pytest

from app import disease_content


@pytest.fixture
def content_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(disease_content, "CONTENT_DIR", tmp_path)
    disease_content.clear_cache()
    yield tmp_path
    disease_content.clear_cache()


def write(content_dir, code, payload):
    (content_dir / f"{code}.json").write_text(json.dumps(payload), encoding="utf-8")
    disease_content.clear_cache()


# ------------------------------------------------------------------ 기본 동작
def test_terms_come_from_the_content_file_verbatim(user_a, content_dir):
    write(
        content_dir,
        "vestibular_schwannoma",
        {
            "content_version": "test-1",
            "medical_terms": [
                {"term": "소뇌교각 (CPA)", "description": "설명 (출처 2019)"},
                {"term": "내이도 (IAC)", "description": "설명2"},
            ],
        },
    )
    payload = user_a.get("/api/glossary?disease=vestibular_schwannoma").json()

    assert payload["source"] == "literature_based"
    assert payload["content_version"] == "test-1"
    assert [t["term"] for t in payload["terms"]] == ["소뇌교각 (CPA)", "내이도 (IAC)"]
    # 설명을 요약하거나 다듬지 않는다 — 출처 표기까지 그대로 나가야 한다
    assert payload["terms"][0]["description"] == "설명 (출처 2019)"


def test_a_disease_without_content_is_empty_not_an_error(user_a, content_dir):
    """**없는 것은 없다고 한다.** 빈 목록은 실패가 아니라 "아직 쓰지 않았다"는 뜻이다."""
    response = user_a.get("/api/glossary?disease=nothing_written_yet")
    assert response.status_code == 200
    assert response.json()["terms"] == []
    assert response.json()["content_version"] is None


def test_no_disease_given_is_also_empty(user_a, content_dir):
    response = user_a.get("/api/glossary")
    assert response.status_code == 200
    assert response.json()["terms"] == []


def test_login_is_required(client):
    assert client.get("/api/glossary?disease=vestibular_schwannoma").status_code == 401


# ------------------------------------------------------- 제출 전 GT 노출 금지
CASE_SPECIFIC_LEAKS = ["mask", "reference_region", "lesion", "slice", "laterality", "case_facts"]


def test_the_glossary_does_not_carry_case_specific_answers(user_a, content_dir):
    """
    사전은 **질환 일반 문헌**이다. 여기에 이 케이스의 답이 섞이면
    제출 전에 정답을 보여주는 통로가 된다 (`test_gt_not_leaked_before_submit` 과 같은 불변조건).
    """
    write(
        content_dir,
        "vestibular_schwannoma",
        {"medical_terms": [{"term": "소뇌교각", "description": "일반 설명"}]},
    )
    body = json.dumps(user_a.get("/api/glossary?disease=vestibular_schwannoma").json(), ensure_ascii=False)
    for field in CASE_SPECIFIC_LEAKS:
        assert field not in body, f"사전 응답에 케이스별 정보가 들어 있다: {field}"


def test_real_shipped_content_loads(user_a):
    """
    실제 커밋된 콘텐츠(전정신경초종)가 실제로 읽히는지.
    **여기 실패는 "화면에 사전이 비어 보인다"는 뜻이다** — 로더 경로가 깨진 것을 잡는다.
    """
    payload = user_a.get("/api/glossary?disease=vestibular_schwannoma").json()
    assert payload["terms"], "커밋된 문헌 콘텐츠가 있는데 사전이 비어 있다"
    assert all(t["term"] for t in payload["terms"])
    # 설명에는 출처가 함께 남아 있어야 한다 (CONTENT_GUIDELINES)
    assert any("(" in t["description"] for t in payload["terms"])
