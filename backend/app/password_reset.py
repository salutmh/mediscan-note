"""
비밀번호 재설정 — 운영자가 일회용 코드를 발급한다.

**왜 이 방식인가**
메일 발송 수단이 없으면 "비밀번호 찾기"를 만들 수 없다. 그렇다고 재설정을 아예 두지 않으면
비밀번호를 잊은 사용자는 계정과 **학습 이력을 영구히 잃는다** (새로 가입하면 기록이 갈린다).

그래서 운영자가 코드를 발급하고 **본인 확인은 오프라인으로** 한다. 학내 Closed Beta 라
조교·담당자가 얼굴을 아는 상황을 전제한 것이고, 메일 발송 수단이 생기면 이 모듈의
발급 경로만 바꾸면 된다 (검증·소비 로직은 그대로 쓴다).

지키는 것
--------
  - 코드는 **해시로만 저장한다.** DB 가 새더라도 그 값으로 비밀번호를 바꿀 수 없다.
    코드 원문은 발급 응답에 한 번만 나가고 서버에 남지 않는다.
  - **일회용.** 성공하면 즉시 지운다.
  - **만료 있음** (기본 24시간).
  - 새 코드를 발급하면 그 사용자의 기존 코드는 무효가 된다 (여러 개가 떠다니지 않게).
  - 재설정에 성공하면 **모든 기기의 로그인을 끊는다** — 계정을 되찾는 상황이므로
    남의 세션이 살아 있으면 안 된다.

코드에 느린 KDF(scrypt)를 쓰지 않는 이유: 비밀번호와 달리 **높은 엔트로피로 서버가
직접 생성**하기 때문이다. 무차별 대입이 통하지 않으므로 SHA-256 으로 충분하다.
"""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import PasswordResetCode, User, utcnow

logger = logging.getLogger(__name__)

CODE_TTL_HOURS = 24
# 사람이 받아 적을 수 있으면서 추측은 불가능한 길이 (base32 8자 = 40비트)
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 헷갈리는 0/O/1/I 제외
CODE_LENGTH = 10


class ResetError(Exception):
    """재설정 코드가 없거나 만료됐거나 이미 쓰였다."""


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def generate_code() -> str:
    """읽어서 옮겨 적을 수 있는 형태로 만든다 (오프라인 전달을 전제)."""
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    return f"{raw[:5]}-{raw[5:]}"


def issue(db: Session, user: User, issued_by: str | None = None) -> dict:
    """코드를 발급한다. **원문은 이 반환값에만 존재한다.**

    기존 코드는 무효화한다 — 여러 개가 동시에 유효하면 회수가 어렵다.
    """
    db.execute(delete(PasswordResetCode).where(PasswordResetCode.user_id == user.user_id))

    code = generate_code()
    expires_at = utcnow() + timedelta(hours=CODE_TTL_HOURS)
    db.add(
        PasswordResetCode(
            user_id=user.user_id,
            code_hash=_hash(code),
            expires_at=expires_at,
            issued_by=issued_by,
        )
    )
    db.commit()

    # 코드는 로그에 남기지 않는다 (남기면 로그를 본 사람이 계정을 가져갈 수 있다)
    logger.info(
        "비밀번호 재설정 코드 발급: user_id=%s issued_by=%s",
        user.user_id,
        issued_by,
        extra={"event": "password_reset_issued", "user_id": user.user_id, "issued_by": issued_by},
    )
    return {"code": code, "expires_at": expires_at.isoformat(), "user_id": user.user_id}


def _is_expired(row: PasswordResetCode, now: datetime) -> bool:
    expires_at = row.expires_at
    if expires_at.tzinfo is None:  # SQLite 는 tz 정보를 잃을 수 있다
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at < now


def consume(db: Session, email: str, code: str) -> User:
    """코드를 검증하고 소비한다. 성공하면 해당 사용자를 돌려준다.

    실패 사유를 구분해서 알려주지 않는다 — "이 이메일이 가입돼 있는가"를
    코드 대입으로 알아낼 수 있으면 안 된다.
    """
    row = db.scalar(select(PasswordResetCode).where(PasswordResetCode.code_hash == _hash(code)))
    if row is None:
        raise ResetError("재설정 코드가 올바르지 않거나 만료되었습니다.")

    if _is_expired(row, datetime.now(timezone.utc)):
        db.delete(row)
        db.commit()
        raise ResetError("재설정 코드가 올바르지 않거나 만료되었습니다.")

    user = db.get(User, row.user_id)
    if user is None or (user.email or "").strip().lower() != (email or "").strip().lower():
        # 코드는 맞지만 이메일이 다르다 = 남의 코드를 들고 온 경우.
        # 이때는 코드를 소비하지 않는다 (남의 코드를 태워 없앨 수 있으면 안 된다).
        raise ResetError("재설정 코드가 올바르지 않거나 만료되었습니다.")

    # **일회용을 여기서 실제로 보장한다.**
    # 위의 SELECT 와 이 지점 사이에 다른 요청이 같은 코드를 쓸 수 있다. ORM 의
    # db.delete(row) 는 "내가 읽은 행을 지운다" 라서 두 요청이 나란히 통과했고,
    # 코드 하나로 비밀번호가 두 번 바뀌었다. 조건부 DELETE 의 rowcount 로 소유권을
    # 주장한다 — 행 잠금 덕분에 두 번째 요청은 첫 번째가 커밋된 뒤 0건을 보게 된다.
    claimed = db.execute(
        delete(PasswordResetCode).where(PasswordResetCode.code_hash == row.code_hash)
    ).rowcount
    if not claimed:
        raise ResetError("재설정 코드가 올바르지 않거나 만료되었습니다.")
    return user


def purge_expired(db: Session, now: datetime | None = None) -> int:
    """만료된 코드를 정리한다 (앱 기동 시)."""
    cutoff = now or datetime.now(timezone.utc)
    result = db.execute(delete(PasswordResetCode).where(PasswordResetCode.expires_at < cutoff))
    db.commit()
    return int(result.rowcount or 0)
