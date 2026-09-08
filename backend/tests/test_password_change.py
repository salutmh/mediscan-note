"""
비밀번호 정책과 변경.

**왜 필요한가**
- 최소 길이 정책이 없어 한 글자짜리 비밀번호로도 가입할 수 있었다.
- 비밀번호를 바꿀 방법이 없었다. 유출이 의심돼도 할 수 있는 게 없다는 뜻이다.

**핵심 동작**: 비밀번호를 바꾸면 **다른 기기의 로그인이 전부 끊긴다.**
비밀번호를 바꾸는 이유는 대개 "누가 내 계정을 쓰고 있는 것 같다"이므로,
다른 세션이 살아 있으면 바꾼 의미가 없다.
"""
import pytest

from app.schemas import MIN_PASSWORD_LENGTH
from tests.conftest import REQUIRED_CONSENTS

NEW_PASSWORD = "new-password-12345"


def _signup(client, email, password):
    return client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": password,
            "nickname": "테스트",
            "consents": dict(REQUIRED_CONSENTS),
        },
    )


# ------------------------------------------------------------------ 정책
@pytest.mark.parametrize("password", ["1", "short", "a" * (MIN_PASSWORD_LENGTH - 1)])
def test_signup_rejects_short_password(client, password):
    res = _signup(client, f"short{len(password)}@example.com", password)
    assert res.status_code == 422, "짧은 비밀번호로 가입이 됐다"


def test_signup_accepts_minimum_length(client):
    res = _signup(client, "minlen@example.com", "a" * MIN_PASSWORD_LENGTH)
    assert res.status_code == 200


def test_change_rejects_short_new_password(user_a):
    res = user_a.post(
        "/api/auth/password",
        json={"current_password": user_a.password, "new_password": "short"},
    )
    assert res.status_code == 422


# ------------------------------------------------------------------ 변경
def test_password_can_be_changed(client, user_a):
    res = user_a.post(
        "/api/auth/password",
        json={"current_password": user_a.password, "new_password": NEW_PASSWORD},
    )
    assert res.status_code == 200, res.text
    assert res.json()["password_changed"] is True

    # 새 비밀번호로 로그인된다
    assert client.post(
        "/api/auth/login", json={"email": user_a.email, "password": NEW_PASSWORD}
    ).status_code == 200
    # 옛 비밀번호는 더 이상 통하지 않는다
    assert client.post(
        "/api/auth/login", json={"email": user_a.email, "password": user_a.password}
    ).status_code == 401


def test_change_requires_current_password(user_a):
    """남의 기기에 남은 세션으로 비밀번호가 바뀌면 계정을 통째로 빼앗긴다."""
    res = user_a.post(
        "/api/auth/password",
        json={"current_password": "wrong-password", "new_password": NEW_PASSWORD},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "INVALID_CURRENT_PASSWORD"


def test_change_requires_authentication(client):
    res = client.post(
        "/api/auth/password",
        json={"current_password": "x" * 10, "new_password": NEW_PASSWORD},
    )
    assert res.status_code == 401


def test_same_password_is_rejected(user_a):
    res = user_a.post(
        "/api/auth/password",
        json={"current_password": user_a.password, "new_password": user_a.password},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "PASSWORD_UNCHANGED"


def test_social_account_cannot_change_password(client):
    signup = client.post(
        "/api/auth/social-login",
        json={
            "provider": "google",
            "provider_token": "pw-change-token",
            "consents": dict(REQUIRED_CONSENTS),
        },
    )
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}

    res = client.post(
        "/api/auth/password",
        json={"current_password": "anything-here", "new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "PASSWORD_NOT_SET"


# ------------------------------------------- 다른 기기 로그아웃 (핵심)
def test_changing_password_records_the_signout_cutoff(client, user_a):
    """비밀번호를 바꾸면 '이 시각 이전 토큰은 전부 무효' 기준선이 기록된다."""
    from app.db import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        assert db.get(User, user_a.user_id).sessions_valid_from is None

    changed = user_a.post(
        "/api/auth/password",
        json={"current_password": user_a.password, "new_password": NEW_PASSWORD},
    )
    assert changed.json()["other_sessions_signed_out"] is True

    with SessionLocal() as db:
        cutoff = db.get(User, user_a.user_id).sessions_valid_from
    assert cutoff is not None
    # iat 가 초 단위라 컷오프도 초 단위여야 한다 (아래 단위 테스트 참고)
    assert cutoff.microsecond == 0


def test_token_issued_before_the_cutoff_is_rejected(client, user_a):
    """기준선보다 이르게 발급된 토큰은 다른 기기 것이라도 거부된다.

    실제 상황에서는 다른 기기가 몇 분~몇 시간 전에 로그인해 있다. 테스트는 1초 안에
    끝나므로 기준선을 명시적으로 앞당겨 **enforcement 경로**를 확인한다
    (타이밍 운에 기대지 않는다).
    """
    from datetime import timedelta

    from app.db import SessionLocal
    from app.models import User, utcnow

    other = client.post(
        "/api/auth/login", json={"email": user_a.email, "password": user_a.password}
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=other_headers).status_code == 200

    with SessionLocal() as db:
        db.get(User, user_a.user_id).sessions_valid_from = (
            utcnow() + timedelta(seconds=5)
        ).replace(microsecond=0)
        db.commit()

    stale = client.get("/api/auth/me", headers=other_headers)
    assert stale.status_code == 401
    assert stale.json()["detail"]["code"] == "SESSION_EXPIRED"


def test_session_cutoff_boundary():
    """경계 조건을 정확히 고정한다 — 같은 초는 살고, 이전 초는 죽는다."""
    from datetime import datetime, timedelta, timezone

    from app.deps import _issued_before_session_reset

    cutoff = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)

    class FakeUser:
        sessions_valid_from = cutoff

    def payload_at(dt):
        return {"iat": int(dt.timestamp())}

    assert _issued_before_session_reset(FakeUser(), payload_at(cutoff - timedelta(seconds=1)))
    assert not _issued_before_session_reset(FakeUser(), payload_at(cutoff))
    assert not _issued_before_session_reset(FakeUser(), payload_at(cutoff + timedelta(seconds=1)))

    # 기준선이 없으면 아무 토큰도 막지 않는다
    class NoCutoff:
        sessions_valid_from = None

    assert not _issued_before_session_reset(NoCutoff(), payload_at(cutoff))

    # iat 를 읽을 수 없는 토큰은 안전한 쪽으로 거부한다
    assert _issued_before_session_reset(FakeUser(), {"iat": "언젠가"})


def test_new_token_from_change_keeps_working(client, user_a):
    """바꾼 기기까지 끊기면 사용자가 곧바로 다시 로그인해야 한다 — 새 토큰을 돌려준다."""
    res = user_a.post(
        "/api/auth/password",
        json={"current_password": user_a.password, "new_password": NEW_PASSWORD},
    )
    fresh = {"Authorization": f"Bearer {res.json()['access_token']}"}

    assert client.get("/api/auth/me", headers=fresh).status_code == 200
    assert client.get("/api/cases", headers=fresh).status_code == 200


def test_other_users_are_not_affected(user_a, user_b):
    user_a.post(
        "/api/auth/password",
        json={"current_password": user_a.password, "new_password": NEW_PASSWORD},
    )
    assert user_b.get("/api/auth/me").status_code == 200


def test_learning_history_survives_password_change(user_a, roi_mismatch, client):
    """보안 조치가 학습 이력을 지우면 안 된다."""
    user_a.submit(roi_mismatch)
    before = user_a.get("/api/wrong-notes").json()["items"]
    assert before

    res = user_a.post(
        "/api/auth/password",
        json={"current_password": user_a.password, "new_password": NEW_PASSWORD},
    )
    fresh = {"Authorization": f"Bearer {res.json()['access_token']}"}

    after = client.get("/api/wrong-notes", headers=fresh).json()["items"]
    assert [i["case_id"] for i in after] == [i["case_id"] for i in before]
