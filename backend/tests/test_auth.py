"""
인증 / 동의 테스트.

api-spec.md 1절(회원가입·로그인·동의)과 0절(401 규칙)이 실제로 지켜지는지 확인한다.
"""
import time

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Consent, User
from app.security import create_access_token
from tests.conftest import REQUIRED_CONSENTS

REQUIRED_KEYS = [
    "agree_terms",
    "agree_privacy",
    "agree_sensitive_data",
    "agree_ai_notice",
    "agree_age14",
]


def _signup_body(email="new@example.com", **overrides):
    body = {
        "email": email,
        "password": "pw12345678",
        "nickname": "온",
        "consents": dict(REQUIRED_CONSENTS),
    }
    body.update(overrides)
    return body


# ------------------------------------------------------------------ 회원가입
@pytest.mark.parametrize("missing_key", REQUIRED_KEYS)
def test_signup_rejects_missing_required_consent(client, missing_key):
    """필수 동의가 하나라도 false 면 계정이 생성되지 않는다 (api-spec 1-1)."""
    consents = dict(REQUIRED_CONSENTS)
    consents[missing_key] = False

    res = client.post("/api/auth/signup", json=_signup_body(consents=consents))

    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail["code"] == "CONSENT_REQUIRED"
    assert missing_key in detail["missing"]

    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.email == "new@example.com")) is None


def test_signup_allows_marketing_opt_out(client):
    """선택 동의(마케팅)는 false 여도 가입된다."""
    consents = dict(REQUIRED_CONSENTS)
    consents["agree_marketing"] = False
    res = client.post("/api/auth/signup", json=_signup_body(consents=consents))
    assert res.status_code == 200


def test_signup_returns_token_and_profile(client):
    res = client.post("/api/auth/signup", json=_signup_body())
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == "new@example.com"
    assert body["nickname"] == "온"
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user_id"].startswith("u_")


def test_signup_rejects_duplicate_email(client):
    assert client.post("/api/auth/signup", json=_signup_body()).status_code == 200
    res = client.post("/api/auth/signup", json=_signup_body())
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "EMAIL_ALREADY_EXISTS"


def test_password_is_not_stored_in_plaintext(client):
    client.post("/api/auth/signup", json=_signup_body(password="super-secret-pw"))
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "new@example.com"))
    assert user.password_hash != "super-secret-pw"
    assert "super-secret-pw" not in user.password_hash
    assert user.password_hash.startswith("scrypt$")


def test_consent_history_is_appended_with_version(client):
    """동의 이력은 항목별로 남고 약관 버전이 함께 저장된다 (api-spec 1절)."""
    res = client.post("/api/auth/signup", json=_signup_body())
    user_id = res.json()["user_id"]

    with SessionLocal() as db:
        rows = db.scalars(select(Consent).where(Consent.user_id == user_id)).all()

    stored = {r.key: r.agreed for r in rows}
    assert set(stored) == set(REQUIRED_CONSENTS)
    assert all(stored[k] for k in REQUIRED_KEYS)
    assert all(r.version for r in rows), "약관 버전이 비어 있으면 증빙이 되지 않는다"
    assert all(r.agreed_at for r in rows)


# --------------------------------------------------------------------- 로그인
def test_login_succeeds_with_correct_password(client, make_user):
    user = make_user()
    res = client.post("/api/auth/login", json={"email": user.email, "password": user.password})
    assert res.status_code == 200
    assert res.json()["user_id"] == user.user_id


def test_login_rejects_wrong_password(client, make_user):
    user = make_user()
    res = client.post("/api/auth/login", json={"email": user.email, "password": "wrong-password"})
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "INVALID_CREDENTIALS"


def test_login_rejects_unknown_email(client):
    res = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "pw12345678"})
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "INVALID_CREDENTIALS"


# ----------------------------------------------------------------------- 토큰
def test_me_returns_current_user(user_a):
    res = user_a.get("/api/auth/me")
    assert res.status_code == 200
    assert res.json() == {"user_id": user_a.user_id, "email": user_a.email, "nickname": "사용자A"}


def test_expired_token_is_rejected(client, user_a):
    expired = create_access_token(user_a.user_id, ttl_seconds=-1)
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "INVALID_TOKEN"


def test_tampered_payload_is_rejected(client, user_a):
    """서명은 그대로 두고 payload 만 바꾼 토큰은 거부된다."""
    body, signature = user_a.token.split(".")
    tampered = f"{body[:-2]}XX.{signature}"
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tampered}"})
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "INVALID_TOKEN"


def test_token_for_deleted_user_is_rejected(client, user_a):
    with SessionLocal() as db:
        db.query(User).filter(User.user_id == user_a.user_id).delete()
        db.commit()
    res = user_a.get("/api/auth/me")
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "USER_NOT_FOUND"


@pytest.mark.parametrize(
    "header",
    ["", "Bearer", "Basic abc", "Bearer ", "token abc.def"],
)
def test_malformed_authorization_header_is_rejected(client, header):
    res = client.get("/api/auth/me", headers={"Authorization": header} if header else {})
    assert res.status_code == 401


# ------------------------------------------------------------- SNS 간편가입
def test_social_login_requires_consent_for_new_user(client):
    res = client.post(
        "/api/auth/social-login",
        json={"provider": "kakao", "provider_token": "kakao-token-1"},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "CONSENT_REQUIRED"


def test_social_login_creates_account_with_consent(client):
    res = client.post(
        "/api/auth/social-login",
        json={
            "provider": "kakao",
            "provider_token": "kakao-token-2",
            "consents": dict(REQUIRED_CONSENTS),
        },
    )
    assert res.status_code == 200
    assert res.json()["is_new_user"] is True


def test_social_login_returning_user_skips_consent(client):
    payload = {
        "provider": "naver",
        "provider_token": "naver-token-1",
        "consents": dict(REQUIRED_CONSENTS),
    }
    assert client.post("/api/auth/social-login", json=payload).json()["is_new_user"] is True

    again = client.post(
        "/api/auth/social-login",
        json={"provider": "naver", "provider_token": "naver-token-1"},
    )
    assert again.status_code == 200
    assert again.json()["is_new_user"] is False


def test_social_login_missing_required_consent_is_rejected(client):
    consents = dict(REQUIRED_CONSENTS)
    consents["agree_sensitive_data"] = False
    res = client.post(
        "/api/auth/social-login",
        json={"provider": "google", "provider_token": "google-token-1", "consents": consents},
    )
    assert res.status_code == 400
    assert "agree_sensitive_data" in res.json()["detail"]["missing"]


# ------------------------------------------- 민감정보 동의와 /api/analyze 연계
# (업로드 검증 자체는 tests/test_analyze_upload.py 에서 다룬다)
def _analyze_payload() -> dict:
    import base64
    import io as _io

    from PIL import Image as _Image

    img = _Image.new("RGB", (128, 128), (80, 80, 80))
    buf = _io.BytesIO()
    img.save(buf, "PNG")
    return {
        "image_base64": base64.b64encode(buf.getvalue()).decode(),
        "region": {"type": "brush_mask", "points": [[10, 10]]},
    }


def test_analyze_requires_sensitive_data_consent(user_a):
    """가입 시 동의했으므로 통과한다."""
    res = user_a.post("/api/analyze", json=_analyze_payload())
    assert res.status_code == 200


def test_analyze_blocked_after_consent_withdrawn(user_a):
    """가장 최근 동의 이력이 철회면 403 (동의 이력은 갱신이 아니라 append)."""
    with SessionLocal() as db:
        db.add(
            Consent(
                user_id=user_a.user_id,
                key="agree_sensitive_data",
                agreed=False,
                version="test",
            )
        )
        db.commit()

    res = user_a.post("/api/analyze", json=_analyze_payload())
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "CONSENT_REQUIRED"


def test_token_remains_valid_within_ttl(client, user_a):
    """짧은 시간 안에는 토큰이 계속 유효하다 (만료 로직 오작동 방지)."""
    time.sleep(1)
    assert user_a.get("/api/auth/me").status_code == 200
