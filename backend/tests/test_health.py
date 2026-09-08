"""
/health 가 배포된 서버의 **실제 설정**을 보여주는지 (자율 루프 #23).

배포에서 가장 곤란한 상황은 "서버는 떠 있는데 내가 의도한 설정으로 도는지 모르겠다" 이다.
특히 아래 셋은 환경변수로 덮을 수 있으면서 잘못돼도 응답이 정상으로 보인다:

  채점 임계값    어떤 기준으로 채점 중인지 (grade 의 의미가 달라진다)
  요청 수 제한   켜져 있는지, 꺼졌다면 왜 (off 인지 external 인지)
  개발 전용 스위치  production 이라면 항상 비어 있어야 한다

접속정보·서명키는 싣지 않는다.
"""
import pytest

from app import rate_limit, scoring_config


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    rate_limit.reset()
    yield
    rate_limit.reset()


def _health(client):
    res = client.get("/health")
    assert res.status_code == 200
    return res.json()


def test_reports_applied_scoring_thresholds(client):
    scoring = _health(client)["scoring"]
    assert scoring["match_dice"] == scoring_config.DEFAULT_MATCH_DICE
    assert scoring["partial_dice"] == scoring_config.DEFAULT_PARTIAL_DICE
    # 값만 보여주면 "확정된 의학 기준"으로 읽힌다. 검증 상태를 함께 낸다.
    assert scoring["validation_status"] == "not_yet_educationally_validated"


def test_scoring_reflects_override_not_the_default(client, monkeypatch):
    # 기본값을 그냥 되읽어 보여주면 확인용으로 쓸모가 없다.
    monkeypatch.setenv("MEDISCAN_MATCH_DICE", "0.7")
    assert _health(client)["scoring"]["match_dice"] == 0.7


def test_reports_rate_limit_state(client):
    assert _health(client)["rate_limit"] == {"enabled": True, "mode": "app", "multiplier": 1}


def test_rate_limit_distinguishes_off_from_external(client, monkeypatch):
    # "실수로 꺼짐"과 "앞단에서 하고 있음"은 운영자에게 전혀 다른 의미다.
    monkeypatch.setenv(rate_limit.ENABLED_ENV, "0")
    off = _health(client)["rate_limit"]
    assert off["enabled"] is False and off["mode"] == "off"

    monkeypatch.setenv(rate_limit.ENABLED_ENV, rate_limit.EXTERNAL)
    external = _health(client)["rate_limit"]
    assert external["enabled"] is False and external["mode"] == rate_limit.EXTERNAL


def test_dev_only_flags_are_listed_when_on(client, monkeypatch):
    # 테스트 환경은 conftest 가 MEDISCAN_SEED_MOCK_CASES 를 켜둔다(합성 케이스가 필요하다).
    # 그래서 "비어 있다"가 아니라 **켠 것이 늘어나는지**를 본다.
    before = set(_health(client)["dev_only_flags"])
    assert "MEDISCAN_ANALYZE_DEMO" not in before

    monkeypatch.setenv("MEDISCAN_ANALYZE_DEMO", "1")
    after = set(_health(client)["dev_only_flags"])
    assert after == before | {"MEDISCAN_ANALYZE_DEMO"}


def test_health_never_leaks_secrets(client, monkeypatch):
    monkeypatch.setenv("MEDISCAN_SECRET_KEY", "super-secret-value-that-must-not-appear")
    body = _health(client)
    assert "super-secret-value" not in str(body)

    # DB 는 드라이버 이름만 — 사용자·비밀번호·호스트가 들어간 접속 문자열이 아니다.
    # (전체 응답에서 "://" 를 찾으면 개발용 CORS 정규식에 걸려 헛짚는다.)
    assert "://" not in body["db"]
    assert "@" not in body["db"]
