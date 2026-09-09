"""
액세스 토큰 폐기 (로그아웃).

**왜 필요한가**
지금까지 로그아웃은 브라우저에서 토큰을 지우는 것뿐이었다. 서버는 그 토큰을 여전히
유효하다고 본다. 이 서비스는 학내 실습실 같은 **공용 PC 배포**를 상정하므로,
로그아웃한 뒤에도 그 토큰이 최대 7일간 살아 있는 것은 실제 위험이다.

**방식: 폐기 목록(denylist)**
토큰마다 고유 `jti` 를 넣고(security.create_access_token), 로그아웃 시 그 jti 를 DB 에 적는다.
요청이 올 때마다 jti 가 목록에 있는지 본다.

  - 세션 하나만 정확히 끊는다 (다른 기기 로그인은 살아 있다)
  - DB 에 있으므로 **워커를 여러 개 띄워도 동작한다** (rate limit 과 달리 프로세스 메모리가 아니다)
  - 만료된 항목은 남겨둘 이유가 없으므로 정리한다 (토큰이 이미 죽었기 때문)

허용 목록(allowlist)이 아니라 폐기 목록인 이유: 로그인마다 세션 행을 쓰면 조회·정리 비용이
계속 들지만, 폐기는 로그아웃한 토큰만 남기면 되어 훨씬 작다.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import RevokedToken

logger = logging.getLogger(__name__)


def _expiry_from_payload(payload: dict) -> datetime:
    """토큰 만료 시각. 값이 이상하면 지금 시각으로 두어 곧 정리되게 한다."""
    try:
        return datetime.fromtimestamp(int(payload.get("exp", 0)), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc)


def revoke(db: Session, payload: dict) -> bool:
    """이 토큰을 폐기한다. 이미 폐기됐으면 조용히 넘어간다(멱등).

    payload 는 decode_access_token 이 돌려준 것이라 서명이 이미 검증된 상태다.
    """
    jti = payload.get("jti")
    if not jti:
        # jti 가 없는 토큰 = 이 기능 도입 이전에 발급된 것.
        # 개별 폐기가 불가능하므로 사실대로 False 를 돌려준다 (조용히 성공한 척하지 않는다).
        logger.info("jti 없는 토큰이라 개별 폐기 불가 (도입 이전 발급): user=%s", payload.get("sub"))
        return False

    if is_revoked(db, jti):
        return True

    db.add(
        RevokedToken(
            jti=jti,
            user_id=payload.get("sub"),
            expires_at=_expiry_from_payload(payload),
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # 같은 토큰으로 로그아웃이 동시에 두 번 들어온 경우(더블클릭, 느린 응답 재시도).
        # 위의 is_revoked 검사와 여기 사이에 다른 요청이 먼저 넣었다.
        # jti 가 기본키라 두 번째 INSERT 가 터진다 — 예전에는 이게 그대로 500 이 됐다.
        # 원하는 결과("이 토큰은 폐기됐다")는 이미 이뤄졌으므로 성공으로 본다.
        db.rollback()
        logger.info("동시 로그아웃 — 이미 폐기된 토큰: user=%s", payload.get("sub"))
        return True
    return True


def is_revoked(db: Session, jti: str | None) -> bool:
    if not jti:
        return False
    return db.scalar(select(RevokedToken.jti).where(RevokedToken.jti == jti)) is not None


def detach_user(db: Session, user_id: str) -> int:
    """계정이 삭제될 때 **폐기 효력은 남기고 사용자 연결만 끊는다.**

    폐기 기록을 통째로 지우면 안 된다 — 그 토큰이 만료 전이면 다시 유효해진다
    (계정이 없으니 어차피 401 이지만, 두 방어선을 겹쳐 두는 것이 이 테이블의 목적이다).

    반대로 `user_id` 를 그대로 두면, 계정을 지운 뒤에도 "이 사람이 언제
    로그아웃했는가"가 남는다. jti 만으로 폐기 판정은 그대로 되므로
    연결만 끊는 것이 삭제 범위와 보안을 둘 다 지키는 방법이다.

    반환값은 연결을 끊은 행 수.
    """
    rows = db.scalars(
        select(RevokedToken).where(RevokedToken.user_id == user_id)
    ).all()
    for row in rows:
        row.user_id = None
    return len(rows)


def purge_expired(db: Session, now: datetime | None = None) -> int:
    """이미 만료된 토큰의 폐기 기록을 지운다.

    만료된 토큰은 폐기 목록에 없어도 어차피 거부되므로 남겨 둘 이유가 없다.
    (목록이 무한히 자라면 로그인마다 조회 비용이 늘어난다.)
    """
    cutoff = now or datetime.now(timezone.utc)
    result = db.execute(delete(RevokedToken).where(RevokedToken.expires_at < cutoff))
    db.commit()
    return int(result.rowcount or 0)
