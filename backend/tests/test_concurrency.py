"""
동시 요청에서 깨지던 것들 (자율 루프 #26, RELEASE_READINESS M6).

부하가 아니라 **정확성** 문제다. Closed Beta 규모에서도 아래 두 가지는 그냥 일어난다:

  로그아웃 버튼 더블클릭      같은 토큰으로 폐기 요청이 두 번 들어온다
  재설정 코드를 두 번 제출     같은 코드로 재설정이 두 번 들어온다

둘 다 실제로 재현했고(하나는 500, 하나는 코드가 두 번 먹혔다) 여기서 고정한다.

**왜 스레드를 쓰지 않는가**: 진짜 스레드로는 인터리빙이 재현될 때도 있고 아닐 때도 있어
회귀 테스트가 되지 못한다. 대신 "둘 다 검사를 통과한 상태"를 결정적으로 만들어 확인한다.
"""
import pytest
from sqlalchemy import select

from app import password_reset, security, token_revocation
from app.db import SessionLocal
from app.models import PasswordResetCode, RevokedToken, User


# ------------------------------------------------- 로그아웃 두 번 (토큰 폐기)
def test_concurrent_logout_of_same_token_is_idempotent(user_a, monkeypatch):
    """둘 다 '아직 폐기 안 됨'을 읽은 뒤 나란히 삽입하는 상황.

    jti 가 기본키라 두 번째 INSERT 에서 IntegrityError 가 났고 그대로 500 이 됐다.
    원하는 결과("이 토큰은 폐기됐다")는 이미 이뤄졌으므로 성공으로 처리해야 한다.
    """
    payload = security.decode_access_token(security.create_access_token(user_a.user_id))

    with SessionLocal() as db:
        assert token_revocation.revoke(db, payload) is True

    # 두 번째 요청은 첫 번째의 커밋을 아직 보지 못한 상태다
    monkeypatch.setattr(token_revocation, "is_revoked", lambda db, jti: False)
    with SessionLocal() as db:
        assert token_revocation.revoke(db, payload) is True
    monkeypatch.undo()

    with SessionLocal() as db:
        assert token_revocation.is_revoked(db, payload["jti"]) is True
        rows = db.scalars(select(RevokedToken).where(RevokedToken.jti == payload["jti"])).all()
    assert len(rows) == 1, "폐기 기록이 중복으로 쌓였다"


def test_double_logout_over_http_does_not_500(user_a, client):
    """실제 경로로도 확인한다 — 사용자가 버튼을 두 번 누르는 상황."""
    headers = {"Authorization": f"Bearer {user_a.token}"}
    first = client.post("/api/auth/logout", headers=headers)
    assert first.status_code == 200

    # 폐기된 토큰으로 다시 로그아웃 (더블클릭의 두 번째 요청)
    second = client.post("/api/auth/logout", headers=headers)
    assert second.status_code < 500, f"두 번째 로그아웃이 {second.status_code}: {second.text}"


# ------------------------------------------------ 재설정 코드는 정말 일회용인가
def _issue_code(user_id: str) -> str:
    with SessionLocal() as db:
        return password_reset.issue(db, db.get(User, user_id))["code"]


def test_reset_code_cannot_be_used_twice(user_a):
    """예전에는 두 번 통과했다.

    ORM 의 db.delete(row) 는 "내가 읽은 행을 지운다" 라서, 두 요청이 같은 행을 읽으면
    둘 다 통과하고 비밀번호가 두 번 바뀌었다. 조건부 DELETE 의 rowcount 로 소유권을
    주장하도록 바꿨다.
    """
    code = _issue_code(user_a.user_id)

    with SessionLocal() as db:
        user = password_reset.consume(db, user_a.email, code)
        user.password_hash = "changed-by-first"
        db.commit()

    with SessionLocal() as db:
        with pytest.raises(password_reset.ResetError):
            password_reset.consume(db, user_a.email, code)


def test_wrong_email_does_not_burn_someone_elses_code(user_a):
    """남의 코드를 태워 없앨 수 있으면 안 된다 — 그것만으로 계정 복구를 막을 수 있다."""
    code = _issue_code(user_a.user_id)

    with SessionLocal() as db:
        with pytest.raises(password_reset.ResetError):
            password_reset.consume(db, "attacker@example.com", code)
        db.rollback()

    # 본인은 여전히 쓸 수 있어야 한다
    with SessionLocal() as db:
        assert password_reset.consume(db, user_a.email, code).user_id == user_a.user_id
        db.commit()


def test_consumed_code_row_is_actually_gone(user_a):
    code = _issue_code(user_a.user_id)
    with SessionLocal() as db:
        password_reset.consume(db, user_a.email, code)
        db.commit()

    with SessionLocal() as db:
        remaining = db.scalars(
            select(PasswordResetCode).where(PasswordResetCode.user_id == user_a.user_id)
        ).all()
    assert remaining == []
