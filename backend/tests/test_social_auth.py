"""
SNS 로그인 토큰 실검증.

==========================================================================
**검증이 없으면 두 가지가 깨진다 — 둘 다 실제로 재현했다.**
==========================================================================
  1) 토큰 값만 알면 **남의 계정으로 들어간다.** 검증이 없으니 아무 문자열이나
     넣으면 계정이 만들어지고, 같은 문자열을 넣으면 그 계정이 열린다.
  2) SNS 액세스 토큰은 갱신되는데 토큰이 식별자라서, 갱신되면 **같은 사람이
     새 계정**이 된다. 학습 이력이 갈린다.

각 사에 토큰을 되물어보면 **바뀌지 않는 식별자**를 받는다. 그걸 저장해야 둘 다 풀린다.

`aud`/`app_id` 확인이 특히 중요하다 — 토큰 자체는 진짜지만 **다른 서비스용**으로
발급된 것일 수 있고, 그러면 그 토큰으로 우리 계정에 들어올 수 있다.
"""
from unittest.mock import patch

import pytest

from app import social_auth
from app.social_auth import SocialAuthError
from tests.conftest import REQUIRED_CONSENTS

KAKAO_SUBJECT = 987654321
GOOGLE_SUBJECT = "google-sub-abc"
CLIENT_ID = "our-client-id.apps.googleusercontent.com"
APP_ID = "123456"


@pytest.fixture(autouse=True)
def _clear_oauth_env(monkeypatch):
    for name in (
        social_auth.GOOGLE_CLIENT_ID_ENV,
        social_auth.KAKAO_APP_ID_ENV,
        social_auth.NAVER_ENABLED_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("MEDISCAN_ENV", raising=False)


def _social(client, token, *, provider="kakao", with_consents=True):
    body = {"provider": provider, "provider_token": token}
    if with_consents:
        body["consents"] = dict(REQUIRED_CONSENTS)
    return client.post("/api/auth/social-login", json=body)


# ------------------------------------------------------------ 설정 감지
def test_no_provider_is_configured_by_default():
    assert social_auth.configured_providers() == []


@pytest.mark.parametrize(
    "env,provider",
    [
        (social_auth.GOOGLE_CLIENT_ID_ENV, "google"),
        (social_auth.KAKAO_APP_ID_ENV, "kakao"),
    ],
)
def test_setting_the_env_configures_the_provider(monkeypatch, env, provider):
    monkeypatch.setenv(env, "x")
    assert social_auth.is_configured(provider) is True


def test_naver_uses_a_boolean_switch(monkeypatch):
    monkeypatch.setenv(social_auth.NAVER_ENABLED_ENV, "1")
    assert social_auth.is_configured("naver") is True
    monkeypatch.setenv(social_auth.NAVER_ENABLED_ENV, "0")
    assert social_auth.is_configured("naver") is False


# ---------------------------------------------- production 에서 막히는가
def test_production_refuses_unverified_social_login(client, monkeypatch):
    """**"아직 안 만들었다"와 "열려 있다"는 다르다.**

    검증 없는 SNS 로그인은 계정 탈취 경로다 — 열어둔 채로 배포할 수 없다.
    """
    monkeypatch.setenv("MEDISCAN_ENV", "production")
    res = _social(client, "아무-토큰")

    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "SOCIAL_NOT_CONFIGURED"
    assert "다른 방법으로 로그인" in res.json()["detail"]["message"]


def test_production_allows_configured_provider(client, monkeypatch):
    monkeypatch.setenv("MEDISCAN_ENV", "production")
    monkeypatch.setenv(social_auth.KAKAO_APP_ID_ENV, APP_ID)

    with patch.object(
        social_auth, "_get_json", lambda url, headers=None: {"id": KAKAO_SUBJECT, "app_id": APP_ID}
    ):
        res = _social(client, "진짜-토큰")
    assert res.status_code == 200


def test_development_still_allows_the_demo_path(client):
    """개발에서는 각 사 키 없이도 화면을 확인할 수 있어야 한다."""
    res = _social(client, "demo-token")
    assert res.status_code == 200
    # 예시 로그인이라는 사실을 숨기지 않는다
    assert res.json()["provider_verified"] is False


def test_verified_login_does_not_claim_to_be_a_demo(client, monkeypatch):
    monkeypatch.setenv(social_auth.KAKAO_APP_ID_ENV, APP_ID)
    with patch.object(
        social_auth, "_get_json", lambda url, headers=None: {"id": KAKAO_SUBJECT, "app_id": APP_ID}
    ):
        res = _social(client, "진짜-토큰")
    assert "provider_verified" not in res.json()


# ------------------------------------ 토큰이 갱신돼도 같은 계정인가 (핵심)
def test_refreshed_token_maps_to_the_same_account(client, monkeypatch):
    """**이 테스트가 무너지면 같은 사람의 학습 이력이 갈린다.**

    SNS 액세스 토큰은 만료·갱신된다. 각 사가 알려주는 식별자는 그대로다.
    """
    monkeypatch.setenv(social_auth.KAKAO_APP_ID_ENV, APP_ID)
    fake = lambda url, headers=None: {"id": KAKAO_SUBJECT, "app_id": APP_ID}  # noqa: E731

    with patch.object(social_auth, "_get_json", fake):
        first = _social(client, "access-token-처음")
        second = _social(client, "access-token-갱신됨")

    assert first.json()["user_id"] == second.json()["user_id"]
    assert first.json()["is_new_user"] is True
    assert second.json()["is_new_user"] is False


def test_the_stored_identifier_is_the_provider_subject_not_the_token(client, monkeypatch):
    """토큰을 저장하면 그것만으로 로그인되는 값이 DB 에 남는다."""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import User

    monkeypatch.setenv(social_auth.KAKAO_APP_ID_ENV, APP_ID)
    with patch.object(
        social_auth, "_get_json", lambda url, headers=None: {"id": KAKAO_SUBJECT, "app_id": APP_ID}
    ):
        res = _social(client, "비밀스러운-액세스-토큰")

    with SessionLocal() as db:
        user = db.get(User, res.json()["user_id"])
        assert user.provider_subject == str(KAKAO_SUBJECT)
        assert user.provider_subject != "비밀스러운-액세스-토큰"


# ------------------------------------ 다른 앱 토큰을 막는가 (핵심)
def test_kakao_token_from_another_app_is_rejected(client, monkeypatch):
    """토큰 자체는 진짜지만 **다른 서비스용**이다. 막지 않으면 그걸로 들어온다."""
    monkeypatch.setenv(social_auth.KAKAO_APP_ID_ENV, APP_ID)
    with patch.object(
        social_auth, "_get_json", lambda url, headers=None: {"id": 111, "app_id": "999999"}
    ):
        res = _social(client, "다른앱-토큰")

    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "SOCIAL_WRONG_AUDIENCE"


def test_google_token_for_another_audience_is_rejected(monkeypatch):
    monkeypatch.setenv(social_auth.GOOGLE_CLIENT_ID_ENV, CLIENT_ID)
    with patch.object(
        social_auth,
        "_get_json",
        lambda url, headers=None: {"sub": GOOGLE_SUBJECT, "aud": "someone-else.apps.googleusercontent.com"},
    ):
        with pytest.raises(SocialAuthError) as exc:
            social_auth.verify("google", "token")
    assert exc.value.reason == "wrong_audience"


def test_google_token_for_our_audience_is_accepted(monkeypatch):
    monkeypatch.setenv(social_auth.GOOGLE_CLIENT_ID_ENV, CLIENT_ID)
    with patch.object(
        social_auth,
        "_get_json",
        lambda url, headers=None: {"sub": GOOGLE_SUBJECT, "aud": CLIENT_ID},
    ):
        assert social_auth.verify("google", "token") == GOOGLE_SUBJECT


# ------------------------------------------------------------ 실패 처리
def test_provider_outage_is_distinguished_from_a_bad_token(client, monkeypatch):
    """제공자 장애면 사용자는 잠시 뒤 다시 시도하면 된다 — 토큰 문제와 다르다."""
    monkeypatch.setenv(social_auth.KAKAO_APP_ID_ENV, APP_ID)

    def unavailable(url, headers=None):
        raise SocialAuthError("연결 실패", reason="provider_unavailable")

    with patch.object(social_auth, "_get_json", unavailable):
        res = _social(client, "토큰")
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "SOCIAL_PROVIDER_UNAVAILABLE"


def test_invalid_token_is_unauthorized(client, monkeypatch):
    monkeypatch.setenv(social_auth.KAKAO_APP_ID_ENV, APP_ID)

    def invalid(url, headers=None):
        raise SocialAuthError("토큰이 유효하지 않습니다.", reason="invalid")

    with patch.object(social_auth, "_get_json", invalid):
        res = _social(client, "썩은-토큰")
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "SOCIAL_INVALID"


def test_empty_token_is_rejected_without_calling_the_provider(monkeypatch):
    monkeypatch.setenv(social_auth.KAKAO_APP_ID_ENV, APP_ID)
    called = []

    with patch.object(social_auth, "_get_json", lambda *a, **k: called.append(1) or {}):
        with pytest.raises(SocialAuthError):
            social_auth.verify("kakao", "   ")
    assert called == [], "빈 토큰으로 제공자를 부르지 않는다"


def test_response_without_subject_is_rejected(monkeypatch):
    """식별자가 없으면 계정을 만들 수 없다 — 빈 값으로 만들면 안 된다."""
    monkeypatch.setenv(social_auth.KAKAO_APP_ID_ENV, APP_ID)
    with patch.object(social_auth, "_get_json", lambda url, headers=None: {"app_id": APP_ID}):
        with pytest.raises(SocialAuthError) as exc:
            social_auth.verify("kakao", "token")
    assert exc.value.reason == "no_subject"


def test_unsupported_provider_is_rejected():
    with pytest.raises(SocialAuthError) as exc:
        social_auth.verify("facebook", "token")
    assert exc.value.reason == "unsupported"


# ------------------------------------------------------------------ 상태 노출
def test_health_reports_which_providers_are_verified(client):
    state = client.get("/health").json()["social_login"]
    assert state["verified"] == []
    assert set(state["unverified"]) == set(social_auth.PROVIDERS)
    assert "계정 탈취" in state["note"]


def test_describe_says_all_verified_when_configured(monkeypatch):
    monkeypatch.setenv(social_auth.GOOGLE_CLIENT_ID_ENV, CLIENT_ID)
    monkeypatch.setenv(social_auth.KAKAO_APP_ID_ENV, APP_ID)
    monkeypatch.setenv(social_auth.NAVER_ENABLED_ENV, "1")

    state = social_auth.describe()
    assert state["unverified"] == []
    assert "모든 제공자가 실검증" in state["note"]
