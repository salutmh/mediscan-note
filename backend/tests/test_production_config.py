"""
production 배포 설정 가드 (Phase 2 / RELEASE_READINESS C1·C2).

개발 기본값(공개된 dev 서명 키, CORS 전체 허용)이 배포로 따라가면 사고가 된다.
그래서 production 에서는 **경고가 아니라 기동 실패**로 막는다. 이 테스트는 그 가드가
실제로 동작하는지 확인한다 — 가드가 사라지면 여기서 실패해야 한다.
"""
import pytest

from app import cors, security
from app.config import ConfigError, is_production

GOOD_SECRET = "x" * 48


def _production(monkeypatch):
    monkeypatch.setenv("MEDISCAN_ENV", "production")


# ------------------------------------------------------------------ 환경 판별
def test_default_env_is_development(monkeypatch):
    monkeypatch.delenv("MEDISCAN_ENV", raising=False)
    assert is_production() is False


def test_production_env_is_detected(monkeypatch):
    _production(monkeypatch)
    assert is_production() is True


def test_unknown_env_is_rejected(monkeypatch):
    """오타를 조용히 development 로 떨어뜨리면 배포에서 가드가 통째로 풀린다."""
    monkeypatch.setenv("MEDISCAN_ENV", "prodution")  # 오타
    with pytest.raises(ConfigError):
        is_production()


# --------------------------------------------------------------- SECRET_KEY
def test_production_requires_secret_key(monkeypatch):
    _production(monkeypatch)
    monkeypatch.delenv("MEDISCAN_SECRET_KEY", raising=False)
    with pytest.raises(ConfigError) as exc:
        security._resolve_secret_key()
    assert "MEDISCAN_SECRET_KEY" in str(exc.value)


def test_production_rejects_dev_secret(monkeypatch):
    """dev 키는 공개 저장소에 있는 값이라 production 에서 쓰면 토큰 위조가 가능하다."""
    _production(monkeypatch)
    monkeypatch.setenv("MEDISCAN_SECRET_KEY", security._DEV_SECRET)
    with pytest.raises(ConfigError):
        security._resolve_secret_key()


def test_production_rejects_short_secret(monkeypatch):
    _production(monkeypatch)
    monkeypatch.setenv("MEDISCAN_SECRET_KEY", "short")
    with pytest.raises(ConfigError):
        security._resolve_secret_key()


def test_production_accepts_strong_secret(monkeypatch):
    _production(monkeypatch)
    monkeypatch.setenv("MEDISCAN_SECRET_KEY", GOOD_SECRET)
    assert security._resolve_secret_key() == GOOD_SECRET


def test_development_falls_back_with_warning(monkeypatch):
    """개발에서는 팀원이 환경변수 없이도 실행할 수 있어야 한다 — 단 경고는 나온다."""
    monkeypatch.setenv("MEDISCAN_ENV", "development")
    monkeypatch.delenv("MEDISCAN_SECRET_KEY", raising=False)
    with pytest.warns(UserWarning):
        assert security._resolve_secret_key() == security._DEV_SECRET


# --------------------------------------------------------------------- CORS
def test_production_requires_cors_origins(monkeypatch):
    _production(monkeypatch)
    monkeypatch.delenv("MEDISCAN_CORS_ORIGINS", raising=False)
    with pytest.raises(ConfigError) as exc:
        cors.cors_kwargs()
    assert "MEDISCAN_CORS_ORIGINS" in str(exc.value)


def test_production_rejects_wildcard_origin(monkeypatch):
    _production(monkeypatch)
    monkeypatch.setenv("MEDISCAN_CORS_ORIGINS", "*")
    with pytest.raises(ConfigError):
        cors.cors_kwargs()


def test_production_uses_explicit_origins(monkeypatch):
    _production(monkeypatch)
    monkeypatch.setenv(
        "MEDISCAN_CORS_ORIGINS", "https://mediscan.example.com, https://www.example.com/"
    )
    kwargs = cors.cors_kwargs()
    assert kwargs["allow_origins"] == [
        "https://mediscan.example.com",
        "https://www.example.com",
    ]
    # 인증 토큰을 쓰는 API 라 메서드·헤더도 좁힌다
    assert "*" not in kwargs["allow_methods"]
    assert "*" not in kwargs["allow_headers"]


def test_development_allows_any_localhost_port(monkeypatch):
    """포트를 바꿔도 프론트가 붙어야 한다 (5173 / 4173 / 그 외)."""
    import re

    monkeypatch.setenv("MEDISCAN_ENV", "development")
    monkeypatch.delenv("MEDISCAN_CORS_ORIGINS", raising=False)
    kwargs = cors.cors_kwargs()
    pattern = re.compile(kwargs["allow_origin_regex"])
    assert pattern.match("http://localhost:5173")
    assert pattern.match("http://127.0.0.1:4173")
    assert not pattern.match("https://evil.example.com")
