"""
인증 엔드포인트 요청 수 제한 (Phase 2 / RELEASE_READINESS C3).

막고 싶은 것: 비밀번호 대입, 가입 스팸, provider_token 추측.
막으면 안 되는 것: 학습 흐름(케이스 조회·ROI 제출)의 정상적인 반복.
"""
import pytest

from app import rate_limit
from tests.conftest import REQUIRED_CONSENTS


@pytest.fixture(autouse=True)
def _clean_limiter():
    rate_limit.reset()
    yield
    rate_limit.reset()


def _login(client, email="nobody@example.com", password="wrong-password"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


# ------------------------------------------------------------------ 기본 동작
def test_login_is_rate_limited_after_repeated_attempts(client):
    """실패한 로그인을 계속 던지면 429 로 막힌다 (비밀번호 대입 방지)."""
    window, limit = rate_limit.RULES["POST /api/auth/login"]

    for _ in range(limit):
        assert _login(client).status_code == 401  # 아직은 통과 (자격증명만 틀림)

    blocked = _login(client)
    assert blocked.status_code == 429
    body = blocked.json()
    assert body["code"] == "RATE_LIMITED"
    # 언제 다시 시도할 수 있는지 알려준다
    assert int(blocked.headers["Retry-After"]) > 0
    assert int(blocked.headers["Retry-After"]) <= window


def test_signup_is_rate_limited(client):
    _, limit = rate_limit.RULES["POST /api/auth/signup"]

    def signup(n):
        return client.post(
            "/api/auth/signup",
            json={
                "email": f"ratelimit{n}@example.com",
                "password": "pw12345678",
                "nickname": "테스트",
                "consents": dict(REQUIRED_CONSENTS),
            },
        )

    for n in range(limit):
        assert signup(n).status_code == 200
    assert signup(limit + 1).status_code == 429


def test_social_login_is_rate_limited(client):
    _, limit = rate_limit.RULES["POST /api/auth/social-login"]

    def attempt(n):
        return client.post(
            "/api/auth/social-login",
            json={"provider": "kakao", "provider_token": f"guess-{n}"},
        )

    for n in range(limit):
        # 동의 없이 신규 가입 시도라 400 — 여기서는 "차단되지 않았다"는 것만 본다
        assert attempt(n).status_code != 429
    assert attempt(limit + 1).status_code == 429


# ---------------------------------------------------- 학습 흐름은 막지 않는다
def test_learning_endpoints_are_not_rate_limited(user_a, roi_mismatch):
    """정상 학습자는 같은 케이스를 빠르게 여러 번 재도전할 수 있어야 한다."""
    for _ in range(30):
        res = user_a.submit(roi_mismatch)
        assert res.status_code == 200, res.text

    assert user_a.get("/api/cases").status_code == 200


def test_get_me_is_not_limited_by_delete_rule(user_a):
    """GET /api/auth/me 는 화면마다 불린다. 같은 경로의 DELETE 한도와 섞이면 안 된다."""
    _, delete_limit = rate_limit.RULES["DELETE /api/auth/me"]
    for _ in range(delete_limit * 3):
        assert user_a.get("/api/auth/me").status_code == 200


# ------------------------------------------------------------- 키 분리·해제
def test_limit_is_per_endpoint(client):
    """한 엔드포인트가 막혀도 다른 엔드포인트는 살아 있어야 한다."""
    _, login_limit = rate_limit.RULES["POST /api/auth/login"]
    for _ in range(login_limit + 1):
        _login(client)
    assert _login(client).status_code == 429

    # 같은 IP 라도 signup 은 아직 한도가 남아 있다
    res = client.post(
        "/api/auth/signup",
        json={
            "email": "separate@example.com",
            "password": "pw12345678",
            "nickname": "테스트",
            "consents": dict(REQUIRED_CONSENTS),
        },
    )
    assert res.status_code == 200


def test_can_be_disabled_by_env(client, monkeypatch):
    """개발·테스트에서 끌 수 있어야 한다 (기본은 ON)."""
    monkeypatch.setenv("MEDISCAN_RATE_LIMIT", "0")
    _, limit = rate_limit.RULES["POST /api/auth/login"]
    for _ in range(limit + 5):
        assert _login(client).status_code == 401  # 429 가 아니다


def test_window_expiry_allows_retry(monkeypatch):
    """윈도가 지나면 다시 허용된다 (영구 차단이 아니다)."""
    win = rate_limit._SlidingWindow()
    allowed_first, _ = win.check("k", window=60, limit=1, now=1000.0)
    blocked, retry_after = win.check("k", window=60, limit=1, now=1001.0)
    allowed_later, _ = win.check("k", window=60, limit=1, now=1061.0)

    assert allowed_first is True
    assert blocked is False and retry_after > 0
    assert allowed_later is True
