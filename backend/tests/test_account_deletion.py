"""
회원 탈퇴 (Phase 2 / RELEASE_READINESS C4).

확인하는 것:
  - 인증 없이는 남의 계정을 지울 수 없다
  - 이메일 계정은 비밀번호 재확인이 필요하다 (토큰만 훔친 경우를 막는다)
  - 계정·동의 이력·제출 이력이 실제로 함께 사라진다
  - 다른 사용자의 데이터와 교육 콘텐츠(cases)는 건드리지 않는다

삭제 범위(전부 하드 삭제)는 법률 판단이 필요한 지점이라 app/account.py 한 곳에 모아뒀다.
→ docs/CLAUDE_HANDOFF.md BLOCKER-3
"""
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Case, Consent, LearningEvent, Submission, User


def _counts(user_id: str) -> dict:
    with SessionLocal() as db:
        return {
            "user": db.get(User, user_id) is not None,
            "consents": len(db.scalars(select(Consent).where(Consent.user_id == user_id)).all()),
            "submissions": len(
                db.scalars(select(Submission).where(Submission.user_id == user_id)).all()
            ),
            "learning_events": len(
                db.scalars(select(LearningEvent).where(LearningEvent.user_id == user_id)).all()
            ),
        }


# ------------------------------------------------------------------- 권한
def test_delete_requires_authentication(client):
    assert client.request("DELETE", "/api/auth/me").status_code == 401


def test_delete_requires_password_for_email_account(user_a):
    """토큰만 있으면 계정이 통째로 사라지는 상황을 막는다."""
    res = user_a.delete("/api/auth/me")
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "PASSWORD_CONFIRMATION_REQUIRED"
    assert _counts(user_a.user_id)["user"] is True  # 아직 살아 있다


def test_delete_rejects_wrong_password(user_a):
    res = user_a.delete("/api/auth/me", json={"password": "not-my-password"})
    assert res.status_code == 403
    assert _counts(user_a.user_id)["user"] is True


# ------------------------------------------------------------------- 삭제
def test_delete_removes_account_and_user_data(user_a, roi_mismatch):
    user_a.submit(roi_mismatch)
    before = _counts(user_a.user_id)
    assert before["user"] and before["consents"] > 0 and before["submissions"] > 0
    assert before["learning_events"] > 0, "제출 시 관찰 로그가 남아야 한다"

    res = user_a.delete("/api/auth/me", json={"password": user_a.password})
    assert res.status_code == 200, res.text

    body = res.json()
    assert body["deleted"] is True
    assert body["user_id"] == user_a.user_id
    assert body["deleted_counts"]["consents"] == before["consents"]
    assert body["deleted_counts"]["submissions"] == before["submissions"]
    # 학습 관찰 로그(Phase 8)도 함께 지운다 — 사용자 데이터이므로 남기지 않는다
    assert body["deleted_counts"]["learning_events"] == before["learning_events"]
    assert set(body["deleted_scopes"]) == {
        "account",
        "consents",
        "submissions",
        "learning_events",
    }

    after = _counts(user_a.user_id)
    assert after == {"user": False, "consents": 0, "submissions": 0, "learning_events": 0}


def test_token_stops_working_after_deletion(user_a):
    user_a.delete("/api/auth/me", json={"password": user_a.password})
    # 토큰 서명은 여전히 유효하지만 사용자가 없으므로 401 이어야 한다
    assert user_a.get("/api/auth/me").status_code == 401
    assert user_a.get("/api/cases").status_code == 401


def test_deleted_email_can_sign_up_again(client, user_a):
    """탈퇴한 이메일이 영구 점유되면 안 된다."""
    user_a.delete("/api/auth/me", json={"password": user_a.password})
    from tests.conftest import REQUIRED_CONSENTS

    res = client.post(
        "/api/auth/signup",
        json={
            "email": user_a.email,
            "password": "pw12345678",
            "nickname": "다시가입",
            "consents": dict(REQUIRED_CONSENTS),
        },
    )
    assert res.status_code == 200


# --------------------------------------------------------------- 격리·보존
def test_delete_does_not_touch_other_users(user_a, user_b, roi_mismatch):
    user_b.submit(roi_mismatch)
    before_b = _counts(user_b.user_id)

    user_a.delete("/api/auth/me", json={"password": user_a.password})

    assert _counts(user_b.user_id) == before_b
    assert user_b.get("/api/auth/me").status_code == 200


def test_delete_does_not_touch_cases(user_a, roi_mismatch):
    """교육 콘텐츠는 사용자 데이터가 아니다 — 함께 지워지면 안 된다."""
    user_a.submit(roi_mismatch)
    with SessionLocal() as db:
        before = len(db.scalars(select(Case)).all())

    user_a.delete("/api/auth/me", json={"password": user_a.password})

    with SessionLocal() as db:
        assert len(db.scalars(select(Case)).all()) == before


def test_social_account_can_delete_without_password(client):
    """SNS 계정은 확인할 비밀번호가 없다 — 토큰만으로 탈퇴할 수 있어야 한다."""
    from tests.conftest import REQUIRED_CONSENTS

    signup = client.post(
        "/api/auth/social-login",
        json={
            "provider": "kakao",
            "provider_token": "delete-me-token",
            "consents": dict(REQUIRED_CONSENTS),
        },
    )
    assert signup.status_code == 200
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}

    res = client.request("DELETE", "/api/auth/me", headers=headers)
    assert res.status_code == 200
    assert _counts(signup.json()["user_id"])["user"] is False
