"""
로그아웃 시 토큰 폐기 (RELEASE_READINESS H4).

**왜 중요한가**
이 서비스는 학내 실습실 같은 공용 PC 배포를 상정한다. 로그아웃했는데 그 토큰이
만료(기본 7일)까지 유효하면, 브라우저 기록이나 로그에 남은 값으로 남의 학습 계정에
다시 들어올 수 있다.

확인하는 것:
  - 로그아웃한 토큰으로는 더 이상 아무것도 못 한다
  - **다른 기기 세션은 끊기지 않는다** (토큰마다 jti 가 다르다)
  - 로그아웃은 멱등하다
  - 폐기 기록이 무한히 쌓이지 않는다 (만료분 정리)
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import security, token_revocation
from app.db import SessionLocal
from app.models import RevokedToken
from tests.conftest import REQUIRED_CONSENTS


def _logout(session):
    return session.post("/api/auth/logout")


def _login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


# ------------------------------------------------------------------ 토큰 구조
def test_tokens_carry_a_unique_id():
    """jti 가 있어야 '이 토큰 하나만' 폐기할 수 있다."""
    first = security.decode_access_token(security.create_access_token("u_1"))
    second = security.decode_access_token(security.create_access_token("u_1"))

    assert first["jti"] and second["jti"]
    assert first["jti"] != second["jti"], "같은 사용자의 두 토큰이 같은 jti 를 쓴다"


# ------------------------------------------------------------------ 기본 동작
def test_logout_invalidates_the_token(user_a):
    assert user_a.get("/api/auth/me").status_code == 200

    res = _logout(user_a)
    assert res.status_code == 200
    assert res.json() == {"logged_out": True, "token_revoked": True}

    after = user_a.get("/api/auth/me")
    assert after.status_code == 401
    assert after.json()["detail"]["code"] == "TOKEN_REVOKED"


def test_revoked_token_cannot_reach_any_protected_endpoint(user_a, roi_match):
    _logout(user_a)

    assert user_a.get("/api/cases").status_code == 401
    assert user_a.get("/api/wrong-notes").status_code == 401
    assert user_a.submit(roi_match).status_code == 401
    assert user_a.delete("/api/auth/me", json={"password": user_a.password}).status_code == 401


def test_logout_is_idempotent(user_a):
    """로그아웃을 두 번 눌러도 오류가 나면 안 된다.

    폐기된 토큰이 /logout 을 다시 통과하는 것은 의도된 동작이다 —
    이 엔드포인트는 토큰 외에 입력이 없고 폐기만 하므로 얻을 수 있는 것이 없다.
    데이터를 만지는 엔드포인트는 전부 폐기 목록을 확인한다 (아래 테스트).
    """
    assert _logout(user_a).status_code == 200
    assert _logout(user_a).status_code == 200

    with SessionLocal() as db:
        rows = db.scalars(select(RevokedToken).where(RevokedToken.user_id == user_a.user_id)).all()
    assert len(rows) == 1, "같은 토큰이 중복 기록됐다"

    # 그러면서도 데이터 접근은 여전히 막혀 있어야 한다
    assert user_a.get("/api/auth/me").status_code == 401


# ------------------------------------------ 다른 세션은 끊기지 않는다 (핵심)
def test_logout_does_not_kill_other_sessions(client, user_a):
    """다른 기기에서 로그인한 세션까지 끊으면 사용자가 놀란다."""
    other = _login(client, user_a.email, user_a.password)
    assert other.status_code == 200
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    _logout(user_a)

    assert user_a.get("/api/auth/me").status_code == 401          # 이 기기는 끊기고
    assert client.get("/api/auth/me", headers=other_headers).status_code == 200  # 저 기기는 살아 있다


def test_logout_does_not_affect_other_users(user_a, user_b):
    _logout(user_a)
    assert user_b.get("/api/auth/me").status_code == 200


def test_relogin_issues_a_working_token(client, user_a):
    _logout(user_a)
    again = _login(client, user_a.email, user_a.password)

    assert again.status_code == 200
    headers = {"Authorization": f"Bearer {again.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=headers).status_code == 200


# ---------------------------------------------------------------- 탈퇴와의 관계
def test_account_deletion_also_revokes_the_token(user_a):
    """계정이 사라지면 어차피 401 이지만, 폐기 기록도 남겨 방어선을 겹친다."""
    user_a.delete("/api/auth/me", json={"password": user_a.password})

    with SessionLocal() as db:
        rows = db.scalars(select(RevokedToken).where(RevokedToken.user_id == user_a.user_id)).all()
    assert len(rows) == 1
    # 사용자 행이 지워져도 폐기 기록은 남아야 한다 (외래키를 걸지 않은 이유)
    assert user_a.get("/api/auth/me").status_code == 401


# ------------------------------------------------------------ 기록 정리·경계
def test_expired_revocations_are_purged():
    """폐기 목록이 무한히 자라면 인증 조회 비용이 계속 늘어난다."""
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.add(RevokedToken(jti="old-one", user_id="u_x", expires_at=now - timedelta(days=1)))
        db.add(RevokedToken(jti="still-valid", user_id="u_x", expires_at=now + timedelta(days=1)))
        db.commit()

        removed = token_revocation.purge_expired(db, now=now)
        remaining = {r.jti for r in db.scalars(select(RevokedToken)).all()}

    assert removed == 1
    assert "old-one" not in remaining
    assert "still-valid" in remaining


def test_token_without_jti_is_reported_honestly():
    """도입 이전에 발급된 토큰은 개별 폐기가 불가능하다 — 성공한 척하지 않는다."""
    with SessionLocal() as db:
        assert token_revocation.revoke(db, {"sub": "u_legacy", "exp": 99999999999}) is False


def test_legacy_token_without_jti_still_authenticates(client, user_a):
    """폐기 도입이 기존 로그인 세션을 깨뜨리면 안 된다."""
    import json as jsonlib
    import time

    payload = {"sub": user_a.user_id, "iat": int(time.time()), "exp": int(time.time()) + 3600}
    body = security._b64e(jsonlib.dumps(payload, separators=(",", ":")).encode())
    import hashlib
    import hmac

    signature = security._b64e(
        hmac.new(security.SECRET_KEY.encode(), body.encode(), hashlib.sha256).digest()
    )
    legacy = f"{body}.{signature}"

    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {legacy}"})
    assert res.status_code == 200


def test_malformed_expiry_does_not_crash_revocation():
    with SessionLocal() as db:
        assert token_revocation.revoke(db, {"sub": "u_y", "jti": "weird", "exp": "곧"}) is True
        db.execute(select(RevokedToken))  # 세션이 살아 있다


def test_logout_requires_authentication(client):
    assert client.post("/api/auth/logout").status_code == 401


@pytest.fixture(autouse=True)
def _clean_revocations():
    yield
    with SessionLocal() as db:
        for row in db.scalars(select(RevokedToken)).all():
            db.delete(row)
        db.commit()


def test_social_account_can_log_out(client):
    signup = client.post(
        "/api/auth/social-login",
        json={
            "provider": "naver",
            "provider_token": "logout-test-token",
            "consents": dict(REQUIRED_CONSENTS),
        },
    )
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}

    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401
