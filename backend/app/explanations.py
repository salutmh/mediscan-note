"""
화면 4(학습 해설) 응답 조립 — API 계약 v0.4.

해설을 **출처가 다른 3개 블록**으로 나눈다. 하나로 뭉쳐 두면 학습자가
"이 케이스에서 관찰된 것"과 "질환 일반론"을 구분할 수 없다.

| 블록 | source | 근거 | 지금 상태 |
|---|---|---|---|
| `case_facts`    | `dataset_verified`  | 전문가 GT(RTSTRUCT) + DICOM 태그에서 계산 | 6케이스 모두 있음 |
| `disease_info`  | `literature_based`  | 질환 단위 문헌 콘텐츠 파일 | 아직 없음 → null |
| `case_findings` | `expert_reviewed`   | 전문가가 이 케이스를 보고 쓴 소견 | 아직 없음 → null |

`content_levels` 는 **저장하지 않고 블록 존재 여부에서 계산한다.** 저장하면 실제 내용과
어긋날 수 있다. 세 값은 서로 배타적이지 않아서 스칼라 상태 필드로는 표현되지 않는다.
"""
from app import disease_content

SOURCE_DATASET = "dataset_verified"
SOURCE_LITERATURE = disease_content.SOURCE  # "literature_based"
SOURCE_EXPERT = "expert_reviewed"

# content_levels 는 근거가 강한 순서로 내려간다 (화면이 이 순서대로 섹션을 그린다)
LEVEL_ORDER = [SOURCE_DATASET, SOURCE_LITERATURE, SOURCE_EXPERT]


def stored_blocks(case) -> dict:
    """DB(cases.explanation)에 저장되는 케이스 단위 블록만. disease_info 는 여기 없다."""
    stored = case.explanation or {}
    return {
        "case_facts": stored.get("case_facts") or None,
        "case_findings": stored.get("case_findings") or None,
    }


def build(case) -> dict:
    """응답에 실리는 explanation 객체."""
    blocks = stored_blocks(case)
    case_facts = blocks["case_facts"]
    case_findings = blocks["case_findings"]
    info = disease_content.load(case.disease)

    present = {
        SOURCE_DATASET: case_facts is not None,
        SOURCE_LITERATURE: info is not None,
        SOURCE_EXPERT: case_findings is not None,
    }
    return {
        "content_levels": [level for level in LEVEL_ORDER if present[level]],
        "case_facts": case_facts,
        "disease_info": info,
        "case_findings": case_findings,
    }
