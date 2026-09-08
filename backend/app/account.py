"""
계정 삭제 (회원 탈퇴).

**삭제 정책을 여기 한 곳에 모아둔 이유**
"동의 이력을 지울 것인가"는 법률 판단이 필요한 지점이다. 개인정보 파기 의무와
"누가 언제 무엇에 동의했는지" 증빙 보존이 서로 당긴다.
지금은 **전부 삭제(하드 삭제)** 로 간다. Closed Beta 규모에서 사용자에게 가장 안전하고
설명하기 쉬운 선택이기 때문이다. 판단이 서면 이 함수 하나만 바꾸면 된다.

  → docs/CLAUDE_HANDOFF.md BLOCKER-3 (NEEDS_REGULATORY_REVIEW)

지워지는 것 (User 의 cascade="all, delete-orphan" 으로 함께 사라진다):
  - users            계정 (이메일 / 비밀번호 해시 / 닉네임 / SNS 식별자)
  - consents         동의 이력 전부
  - submissions      제출·채점 이력 전부 (복습노트·진행현황도 함께 사라진다)
  - learning_events  학습 관찰 로그 전부

지워지지 않는 것:
  - cases / case_slices  교육 콘텐츠. 사용자 데이터가 아니다.
"""
import logging

from sqlalchemy.orm import Session

from app.models import User

logger = logging.getLogger(__name__)

# 응답으로 무엇이 지워졌는지 알려준다 (사용자가 확인할 수 있어야 한다).
DELETED_SCOPES = ["account", "consents", "submissions", "learning_events"]


def delete_account(db: Session, user: User) -> dict:
    """계정과 딸린 사용자 데이터를 지운다. 되돌릴 수 없다.

    반환값은 지워진 건수 — "정말 지워졌는지" 확인할 수 있게 남긴다.
    """
    counts = {
        "consents": len(user.consents),
        "submissions": len(user.submissions),
        "learning_events": len(user.learning_events),
    }
    user_id = user.user_id

    db.delete(user)
    db.commit()

    # 개인 식별 정보는 로그에 남기지 않는다 (이메일·닉네임 금지, 내부 ID 만).
    logger.info(
        "계정 삭제: user_id=%s consents=%s submissions=%s events=%s",
        user_id, counts["consents"], counts["submissions"], counts["learning_events"],
    )
    return {
        "deleted": True,
        "user_id": user_id,
        "deleted_counts": counts,
        "deleted_scopes": DELETED_SCOPES,
    }
