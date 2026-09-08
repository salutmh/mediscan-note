"""
비밀번호 재설정 (운영자 발급 코드).

**왜 이 방식인가**
메일 발송 수단이 없어 "비밀번호 찾기"를 만들 수 없다. 그렇다고 재설정을 아예 두지 않으면
비밀번호를 잊은 사용자가 **계정과 학습 이력을 영구히 잃는다** (새로 가입하면 기록이 갈린다).
운영자가 코드를 발급하고 본인 확인은 오프라인으로 한다.

여기서 지키려는 것:
  - 코드는 **해시로만 저장**된다 (DB 가 새도 그 값으로 비밀번호를 못 바꾼다)
  - **일회용·만료 있음**
  - 남의 코드로는 안 된다 (코드가 맞아도 이메일이 다르면 거부)
  - 실패 사유를 구분해 알려주지 않는다 (가입 여부를 캐낼 수 없게)
  - 재설정하면 **모든 기기 로그인이 끊긴다**
"""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app import password_reset
from app.db import SessionLocal
from app.models import PasswordResetCode, User, utcnow

NEW_PASSWORD = "recovered-password-1"


def _issue(admin, email):
    return admin.post("/api/admin/password-reset", json={"email": email})


def _reset(client, email, code, new_password=NEW_PASSWORD):
    return client.post(
        "/api/auth/password/reset",
        json={"email": email, "code": code, "new_password": new_password},
    )


# ------------------------------------------------------------------ 발급
def test_admin_can_issue_a_reset_code(admin_session, user_a):
    res = _issue(admin_session, user_a.email)
    assert res.status_code == 200, res.text

    body = res.json()
    assert body["user_id"] == user_a.user_id
    assert body["code"]
    assert body["expires_at"]


def test_code_is_stored_hashed_only(admin_session, user_a):
    """DB 가 새더라도 그 값으로 비밀번호를 바꿀 수 없어야 한다."""
    code = _issue(admin_session, user_a.email).json()["code"]

    with SessionLocal() as db:
        row = db.scalar(select(PasswordResetCode).where(PasswordResetCode.user_id == user_a.user_id))
    assert row is not None
    assert code not in row.code_hash
    assert len(row.code_hash) == 64  # sha256 hex


def test_issuing_a_new_code_invalidates_the_old_one(client, admin_session, user_a):
    """여러 개가 동시에 유효하면 회수가 어렵다."""
    first = _issue(admin_session, user_a.email).json()["code"]
    second = _issue(admin_session, user_a.email).json()["code"]

    assert _reset(client, user_a.email, first).status_code == 400
    assert _reset(client, user_a.email, second).status_code == 200


def test_issue_requires_admin(user_a):
    res = user_a.post("/api/admin/password-reset", json={"email": user_a.email})
    assert res.status_code == 403


def test_issue_requires_authentication(client, user_a):
    res = client.post("/api/admin/password-reset", json={"email": user_a.email})
    assert res.status_code == 401


def test_issue_for_unknown_email_returns_404(admin_session):
    assert _issue(admin_session, "nobody@example.com").status_code == 404


def test_social_account_cannot_get_a_reset_code(client, admin_session):
    from tests.conftest import REQUIRED_CONSENTS

    client.post(
        "/api/auth/social-login",
        json={
            "provider": "kakao",
            "provider_token": "reset-code-token",
            "consents": dict(REQUIRED_CONSENTS),
        },
    )
    # SNS 계정은 이메일이 없어 조회 자체가 안 된다
    assert _issue(admin_session, "").status_code == 404


# ------------------------------------------------------------------ 사용
def test_reset_changes_the_password(client, admin_session, user_a):
    code = _issue(admin_session, user_a.email).json()["code"]

    res = _reset(client, user_a.email, code)
    assert res.status_code == 200
    assert res.json()["password_reset"] is True

    assert client.post(
        "/api/auth/login", json={"email": user_a.email, "password": NEW_PASSWORD}
    ).status_code == 200
    assert client.post(
        "/api/auth/login", json={"email": user_a.email, "password": user_a.password}
    ).status_code == 401


def test_reset_needs_no_login(client, admin_session, user_a):
    """비밀번호를 잊은 사람은 로그인할 수 없다 — 이 경로는 인증 없이 열려야 한다."""
    code = _issue(admin_session, user_a.email).json()["code"]
    assert _reset(client, user_a.email, code).status_code == 200


def test_code_is_single_use(client, admin_session, user_a):
    code = _issue(admin_session, user_a.email).json()["code"]

    assert _reset(client, user_a.email, code).status_code == 200
    assert _reset(client, user_a.email, code, "another-password-2").status_code == 400


def test_expired_code_is_rejected(client, admin_session, user_a):
    code = _issue(admin_session, user_a.email).json()["code"]

    with SessionLocal() as db:
        row = db.scalar(select(PasswordResetCode).where(PasswordResetCode.user_id == user_a.user_id))
        row.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()

    assert _reset(client, user_a.email, code).status_code == 400


def test_code_of_another_user_is_rejected(client, admin_session, user_a, user_b):
    """코드가 맞아도 이메일이 다르면 안 된다."""
    code = _issue(admin_session, user_a.email).json()["code"]

    assert _reset(client, user_b.email, code).status_code == 400
    # user_b 의 비밀번호는 그대로다
    assert client.post(
        "/api/auth/login", json={"email": user_b.email, "password": user_b.password}
    ).status_code == 200


def test_wrong_code_is_rejected(client, user_a):
    assert _reset(client, user_a.email, "AAAAA-BBBBB").status_code == 400


def test_failure_message_does_not_reveal_account_existence(client, user_a, admin_session):
    """가입 여부를 코드 대입으로 알아낼 수 있으면 안 된다."""
    unknown = _reset(client, "nobody@example.com", "AAAAA-BBBBB")
    known = _reset(client, user_a.email, "AAAAA-BBBBB")

    assert unknown.status_code == known.status_code == 400
    assert unknown.json()["detail"]["message"] == known.json()["detail"]["message"]


def test_reset_rejects_short_password(client, admin_session, user_a):
    code = _issue(admin_session, user_a.email).json()["code"]
    assert _reset(client, user_a.email, code, "short").status_code == 422


# ------------------------------------------------------- 세션·이력
def test_reset_signs_out_all_sessions(client, admin_session, user_a):
    """계정을 되찾는 상황이므로 남의 세션이 살아 있으면 안 된다."""
    code = _issue(admin_session, user_a.email).json()["code"]
    _reset(client, user_a.email, code)

    with SessionLocal() as db:
        assert db.get(User, user_a.user_id).sessions_valid_from is not None


def test_learning_history_survives_reset(client, admin_session, user_a, roi_mismatch):
    user_a.submit(roi_mismatch)
    code = _issue(admin_session, user_a.email).json()["code"]
    _reset(client, user_a.email, code)

    login = client.post(
        "/api/auth/login", json={"email": user_a.email, "password": NEW_PASSWORD}
    ).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    items = client.get("/api/wrong-notes", headers=headers).json()["items"]
    assert items, "계정을 되찾았는데 학습 이력이 사라졌다"


# ------------------------------------------------------------------ 정리
def test_expired_codes_are_purged():
    with SessionLocal() as db:
        db.add(
            PasswordResetCode(
                user_id="u_ghost", code_hash="a" * 64, expires_at=utcnow() - timedelta(days=1)
            )
        )
        db.add(
            PasswordResetCode(
                user_id="u_ghost2", code_hash="b" * 64, expires_at=utcnow() + timedelta(days=1)
            )
        )
        db.commit()

        removed = password_reset.purge_expired(db)
        remaining = {r.code_hash for r in db.scalars(select(PasswordResetCode)).all()}
        db.execute(select(PasswordResetCode))

    assert removed >= 1
    assert "a" * 64 not in remaining
    assert "b" * 64 in remaining


@pytest.fixture(autouse=True)
def _clean_codes():
    yield
    with SessionLocal() as db:
        for row in db.scalars(select(PasswordResetCode)).all():
            db.delete(row)
        db.commit()


def test_generated_codes_are_unique_and_readable():
    codes = {password_reset.generate_code() for _ in range(200)}
    assert len(codes) == 200, "코드가 겹친다"
    for code in list(codes)[:5]:
        # 사람이 받아 적는 코드라 헷갈리는 글자를 쓰지 않는다
        assert not set(code) & set("O0I1")
