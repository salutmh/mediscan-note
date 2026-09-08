"""
해설 3층 구조와 질환 문헌 콘텐츠 로더 (API 계약 v0.4).

고정하려는 규칙:
  - `content_levels` 는 저장값이 아니라 **블록 존재 여부에서 계산**된다
  - 콘텐츠 파일이 없거나 비어 있으면 `disease_info` 는 null 이고 레벨에서도 빠진다
  - `notice` 와 `source` 는 콘텐츠 파일이 아니라 **서버 상수**에서 온다
    (안내 문구를 콘텐츠 작성자가 빼거나 바꿀 수 없어야 한다)
"""
import json

import pytest

from app import disease_content, explanations


class FakeCase:
    """explanations.build 는 Case 의 disease / explanation 만 본다."""

    def __init__(self, disease="vestibular_schwannoma", explanation=None):
        self.disease = disease
        self.explanation = explanation


CASE_FACTS = {
    "source": "dataset_verified",
    "disease_name": "전정신경초종 (Vestibular Schwannoma)",
    "disease_code": "vestibular_schwannoma",
    "reference_region": "우측 (전문가 GT 위치)",
}
CASE_FINDINGS = {
    "source": "expert_reviewed",
    "findings": "소견",
    "reviewer": "홍길동",
    "reviewed_at": "2026-09-08",
}


@pytest.fixture
def content_dir(tmp_path, monkeypatch):
    """질환 콘텐츠 폴더를 임시 경로로 돌린다. 앱의 실제 content/ 는 건드리지 않는다."""
    monkeypatch.setattr(disease_content, "CONTENT_DIR", tmp_path)
    disease_content.clear_cache()
    yield tmp_path
    disease_content.clear_cache()


def write_content(directory, disease_code, payload):
    (directory / f"{disease_code}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    disease_content.clear_cache()


# ------------------------------------------------- 콘텐츠 파일이 없을 때 (현재 상태)
def test_missing_content_file_yields_null_disease_info(content_dir):
    result = explanations.build(FakeCase(explanation={"case_facts": CASE_FACTS}))

    assert result["disease_info"] is None
    assert result["content_levels"] == ["dataset_verified"]
    assert result["case_findings"] is None


def test_empty_content_file_yields_null_disease_info(content_dir):
    """빈 카드가 화면에 뜨는 것보다 블록이 없는 편이 정확하다."""
    write_content(content_dir, "vestibular_schwannoma", {"content_version": "v0"})

    result = explanations.build(FakeCase(explanation={"case_facts": CASE_FACTS}))
    assert result["disease_info"] is None
    assert result["content_levels"] == ["dataset_verified"]


def test_broken_content_file_does_not_break_the_response(content_dir):
    (content_dir / "vestibular_schwannoma.json").write_text("{ not json", encoding="utf-8")
    disease_content.clear_cache()

    result = explanations.build(FakeCase(explanation={"case_facts": CASE_FACTS}))
    assert result["disease_info"] is None
    assert result["content_levels"] == ["dataset_verified"]


# ------------------------------------------------------------ 콘텐츠가 있을 때
def test_content_file_adds_literature_level(content_dir):
    write_content(
        content_dir,
        "vestibular_schwannoma",
        {
            "content_version": "vs-test",
            "imaging_features": ["일반적 특징 1"],
            "medical_terms": [{"term": "소뇌교각(CPA)", "description": "설명"}],
            "references": [{"title": "출처", "url": "https://example.org"}],
        },
    )

    result = explanations.build(FakeCase(explanation={"case_facts": CASE_FACTS}))
    assert result["content_levels"] == ["dataset_verified", "literature_based"]
    assert result["disease_info"]["imaging_features"] == ["일반적 특징 1"]
    assert result["disease_info"]["content_version"] == "vs-test"


def test_notice_and_source_come_from_the_server_not_the_file(content_dir):
    """콘텐츠 작성자가 안내 문구를 지우거나 출처를 바꿀 수 없어야 한다."""
    write_content(
        content_dir,
        "vestibular_schwannoma",
        {
            "source": "expert_reviewed",
            "notice": "",
            "imaging_features": ["특징"],
        },
    )

    info = explanations.build(FakeCase(explanation={"case_facts": CASE_FACTS}))["disease_info"]
    assert info["source"] == "literature_based"
    assert info["notice"] == disease_content.NOTICE
    assert "개별 영상 소견을 확정하는 설명은 아닙니다" in info["notice"]


def test_plain_string_medical_terms_are_normalized(content_dir):
    write_content(content_dir, "vestibular_schwannoma", {"medical_terms": ["내이도(IAC)"]})

    info = explanations.build(FakeCase(explanation={"case_facts": CASE_FACTS}))["disease_info"]
    assert info["medical_terms"] == [{"term": "내이도(IAC)", "description": ""}]


def test_content_is_shared_by_disease_not_case(content_dir):
    write_content(content_dir, "vestibular_schwannoma", {"imaging_features": ["공용"]})

    a = explanations.build(FakeCase(explanation={"case_facts": CASE_FACTS}))
    b = explanations.build(FakeCase(explanation={"case_facts": dict(CASE_FACTS)}))
    assert a["disease_info"] == b["disease_info"]

    other = explanations.build(FakeCase(disease="pneumothorax", explanation={"case_facts": CASE_FACTS}))
    assert other["disease_info"] is None, "다른 질환은 자기 콘텐츠 파일만 본다"


# ----------------------------------------------------------- content_levels
def test_all_three_levels(content_dir):
    write_content(content_dir, "vestibular_schwannoma", {"imaging_features": ["특징"]})

    result = explanations.build(
        FakeCase(explanation={"case_facts": CASE_FACTS, "case_findings": CASE_FINDINGS})
    )
    assert result["content_levels"] == [
        "dataset_verified",
        "literature_based",
        "expert_reviewed",
    ]


def test_levels_are_derived_not_stored(content_dir):
    """저장된 content_levels 를 그대로 믿으면 실제 내용과 어긋날 수 있다."""
    stored = {"case_facts": CASE_FACTS, "content_levels": ["expert_reviewed"]}

    result = explanations.build(FakeCase(explanation=stored))
    assert result["content_levels"] == ["dataset_verified"]


def test_case_without_explanation_has_no_levels(content_dir):
    result = explanations.build(FakeCase(explanation=None))
    assert result["content_levels"] == []
    assert result["case_facts"] is None


def test_stored_blocks_excludes_disease_info(content_dir):
    """제출 이력에는 케이스 단위 블록만 남는다 (문헌은 갱신되면 같이 바뀌어야 한다)."""
    write_content(content_dir, "vestibular_schwannoma", {"imaging_features": ["특징"]})

    stored = explanations.stored_blocks(FakeCase(explanation={"case_facts": CASE_FACTS}))
    assert set(stored) == {"case_facts", "case_findings"}


# --------------------------------------------------------------- 캐시 갱신
def test_added_content_file_is_picked_up_without_restart(content_dir):
    """서버를 다시 띄우지 않아도 파일을 추가하면 반영돼야 한다 (mtime 으로 재검사)."""
    case = FakeCase(explanation={"case_facts": CASE_FACTS})
    assert explanations.build(case)["disease_info"] is None  # 캐시에 '없음' 이 들어간다

    (content_dir / "vestibular_schwannoma.json").write_text(
        json.dumps({"imaging_features": ["새로 추가한 문장"]}, ensure_ascii=False), encoding="utf-8"
    )
    info = explanations.build(case)["disease_info"]
    assert info is not None, "추가된 콘텐츠 파일이 반영되지 않았습니다"
    assert info["imaging_features"] == ["새로 추가한 문장"]


def test_removed_content_file_is_picked_up_without_restart(content_dir):
    write_content(content_dir, "vestibular_schwannoma", {"imaging_features": ["삭제될 문장"]})
    case = FakeCase(explanation={"case_facts": CASE_FACTS})
    assert explanations.build(case)["disease_info"] is not None

    (content_dir / "vestibular_schwannoma.json").unlink()
    assert explanations.build(case)["disease_info"] is None


def test_edited_content_file_is_reread(content_dir):
    import os

    path = content_dir / "vestibular_schwannoma.json"
    write_content(content_dir, "vestibular_schwannoma", {"imaging_features": ["처음"]})
    case = FakeCase(explanation={"case_facts": CASE_FACTS})
    assert explanations.build(case)["disease_info"]["imaging_features"] == ["처음"]

    path.write_text(
        json.dumps({"imaging_features": ["고친 뒤"]}, ensure_ascii=False), encoding="utf-8"
    )
    # 같은 초에 쓰면 mtime 이 같을 수 있어 명시적으로 뒤로 민다 (내용 길이도 같은 경우 대비)
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert explanations.build(case)["disease_info"]["imaging_features"] == ["고친 뒤"]


# --------------------------------------- 실제 서비스에 올라간 문헌 콘텐츠
def test_vestibular_schwannoma_content_is_loadable():
    """실제 콘텐츠 파일이 규격대로 읽히는지 (임시 폴더가 아니라 앱의 진짜 경로)."""
    disease_content.clear_cache()
    info = disease_content.load("vestibular_schwannoma")

    assert info is not None, "전정신경초종 문헌 콘텐츠를 읽지 못했습니다"
    assert info["source"] == "literature_based"
    assert info["notice"] == disease_content.NOTICE
    assert info["imaging_features"], "일반적 영상 특징이 비어 있습니다"
    assert info["medical_terms"]
    assert info["references"], "출처 없는 문헌 정보는 두지 않는다"


def test_every_reference_has_a_resolvable_source():
    """출처 없는(또는 URL 없는) 참고문헌은 '문헌 기반' 이라는 라벨을 지키지 못한다."""
    disease_content.clear_cache()
    info = disease_content.load("vestibular_schwannoma")

    for reference in info["references"]:
        assert reference["title"].strip()
        assert reference["url"], f"URL 없는 참고문헌: {reference['title']}"
        assert reference["accessed"], f"확인일 없는 참고문헌: {reference['title']}"


def test_literature_content_does_not_claim_case_specific_findings():
    """질환 일반론이어야 한다 — 특정 케이스를 단정하는 표현이 섞이면 안 된다."""
    disease_content.clear_cache()
    info = disease_content.load("vestibular_schwannoma")

    banned = ["이 케이스", "이 환자", "본 증례", "VS-SEG-2"]
    for feature in info["imaging_features"]:
        for word in banned:
            assert word not in feature, f"케이스 단정 표현이 있습니다: {feature}"


def test_literature_content_has_no_epidemiology_statistics():
    """판독 훈련에 필요 없는 역학 수치(유병 비율 등)는 넣지 않기로 했다.

    핵심 일반 학습정보(위치 / 신호 특성 / 조영증강 / IAC·CPA)만 간결하게 유지한다.
    """
    import re

    disease_content.clear_cache()
    info = disease_content.load("vestibular_schwannoma")

    texts = list(info["imaging_features"]) + [t["description"] for t in info["medical_terms"]]
    for text in texts:
        assert "%" not in text, f"역학 수치로 보이는 표현이 있습니다: {text}"
        assert not re.search(r"약\s*\d", text), f"역학 수치로 보이는 표현이 있습니다: {text}"


def test_literature_content_covers_the_core_teaching_points():
    """IAC / CPA / 조영증강 T1 / T2 는 판독 훈련의 핵심이라 빠지면 안 된다."""
    disease_content.clear_cache()
    info = disease_content.load("vestibular_schwannoma")
    blob = " ".join(info["imaging_features"]) + " ".join(t["term"] for t in info["medical_terms"])

    for keyword in ["내이도", "소뇌교각", "조영증강", "T2"]:
        assert keyword in blob, f"핵심 학습 요소 누락: {keyword}"


def test_all_registered_disease_content_files_are_valid():
    """폴더에 있는 모든 질환 콘텐츠가 로더를 통과해야 한다 (깨진 파일 조기 발견)."""
    disease_content.clear_cache()
    for path in disease_content.CONTENT_DIR.glob("*.json"):
        assert disease_content.load(path.stem) is not None, f"읽히지 않는 콘텐츠: {path.name}"
