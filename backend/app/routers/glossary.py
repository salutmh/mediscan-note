"""
의학용어 사전 — 판독 중에 옆에 두고 찾아보는 용어 목록 (화면 2 우측 패널).

==========================================================================
**여기서 의학 내용을 새로 만들지 않는다.**
==========================================================================
`app/content/diseases/<code>.json` 의 `medical_terms` 를 그대로 내보낸다.
그 파일은 출처를 함께 적어 커밋한 문헌 콘텐츠다 (CONTENT_GUIDELINES).
없는 질환은 **빈 목록**을 주고, 화면은 "준비된 용어가 없습니다"를 보여준다.
그럴듯한 설명을 지어내는 것보다 비어 있는 편이 낫다.

**제출 전에 열어도 되는가**
  된다. 여기서 나가는 것은 질환 일반론(해부학 용어·영상 기법 정의)이고,
  **이 케이스의 기준 마스크·병변 위치·크기·편측성은 포함되지 않는다.**
  케이스별 사실(`case_facts`)과 소견(`case_findings`)은 제출 뒤에만 나가는
  해설 쪽에 그대로 남아 있다 (`tests/test_gt_not_leaked_before_submit.py`).
  학습자는 케이스 목록에서 이미 질환명을 보고 들어오므로,
  교과서 용어 설명을 옆에 두는 것은 답을 알려주는 것이 아니라 학습 보조다.
"""
from fastapi import APIRouter

from app import disease_content
from app.deps import CurrentUser
from app.schemas import GlossaryResponse

router = APIRouter(prefix="/api", tags=["glossary"])


@router.get("/glossary", response_model=GlossaryResponse)
def get_glossary(user: CurrentUser, disease: str | None = None) -> dict:
    """질환 코드로 용어 목록을 준다. 코드가 없거나 콘텐츠가 없으면 빈 목록."""
    content = disease_content.load(disease)
    return {
        "disease": disease,
        # 콘텐츠가 없는 질환도 **에러가 아니다** — 아직 안 쓴 것뿐이다
        "content_version": (content or {}).get("content_version"),
        "source": "literature_based",
        "terms": (content or {}).get("medical_terms", []),
    }
