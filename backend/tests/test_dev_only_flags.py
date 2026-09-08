"""
개발 전용 스위치가 production 으로 새지 않는지 (자율 루프 #20).

이 세 스위치는 켜지면 서비스가 **사실과 다른 것**을 사용자에게 보여준다:

  MEDISCAN_ALLOW_APPROX_GRADING  전문가 검수 마스크가 아닌 원 근사로 grade 를 매긴다
  MEDISCAN_SEED_MOCK_CASES       합성 자리표시자가 학습 콘텐츠로 노출된다
  MEDISCAN_ANALYZE_DEMO          모델이 없는데 분석 결과가 있는 것처럼 보인다

셋 다 로컬 .env 복사나 데모 준비 후 원복 누락으로 배포에 남기 쉬운 값이고,
켜진 채로 떠도 서버는 겉보기에 멀쩡하다. 그래서 **기동을 막는다**.
이 테스트가 실패하면 가드가 사라진 것이다.
"""
import pytest

from app import config, grading, seed
from app.config import ConfigError
from app.routers import analyze


def _production(monkeypatch):
    monkeypatch.setenv("MEDISCAN_ENV", "production")


def _development(monkeypatch):
    monkeypatch.setenv("MEDISCAN_ENV", "development")


ALL_FLAGS = list(config.DEV_ONLY_FLAGS)


def _clear(monkeypatch):
    for name in ALL_FLAGS:
        monkeypatch.delenv(name, raising=False)


# ------------------------------------------------------- 레지스트리 자체
def test_every_flag_explains_what_it_breaks():
    # 이름만 보고는 위험도를 알 수 없다. 무엇이 깨지는지 함께 적혀 있어야
    # 다음 사람이 "이건 켜도 되겠지" 하고 넘기지 않는다.
    for name, why in config.DEV_ONLY_FLAGS.items():
        assert why.strip(), f"{name} 에 설명이 없다"
        assert len(why) > 20, f"{name} 설명이 너무 짧다: {why}"


def test_registry_covers_every_dev_switch_in_code():
    # 코드가 실제로 읽는 스위치와 레지스트리가 어긋나면 가드가 비어버린다.
    assert grading.APPROX_ENV in config.DEV_ONLY_FLAGS
    assert seed.MOCK_SEED_ENV in config.DEV_ONLY_FLAGS
    assert analyze.DEMO_ENV in config.DEV_ONLY_FLAGS


# --------------------------------------------------------- 기동 시점 점검
def test_startup_passes_when_no_flag_is_set(monkeypatch):
    _production(monkeypatch)
    _clear(monkeypatch)
    config.assert_dev_only_flags_off()  # 예외가 나지 않아야 한다


@pytest.mark.parametrize("name", ALL_FLAGS)
def test_production_startup_fails_for_each_flag(monkeypatch, name):
    _production(monkeypatch)
    _clear(monkeypatch)
    monkeypatch.setenv(name, "1")

    with pytest.raises(ConfigError) as exc:
        config.assert_dev_only_flags_off()
    message = str(exc.value)
    assert name in message
    # 무엇이 문제인지도 함께 알려준다 (이름만 던지면 원인을 다시 찾아야 한다)
    assert config.DEV_ONLY_FLAGS[name][:15] in message


def test_startup_error_lists_every_offender_at_once(monkeypatch):
    # 하나씩 고치고 다시 뜨기를 반복하지 않도록 전부 모아서 알려준다.
    _production(monkeypatch)
    _clear(monkeypatch)
    for name in ALL_FLAGS:
        monkeypatch.setenv(name, "1")

    with pytest.raises(ConfigError) as exc:
        config.assert_dev_only_flags_off()
    for name in ALL_FLAGS:
        assert name in str(exc.value)


@pytest.mark.parametrize("value", ["0", "false", "False", "no", "off", ""])
def test_explicitly_disabled_flag_is_allowed_in_production(monkeypatch, value):
    # 배포 템플릿에 `MEDISCAN_ANALYZE_DEMO=0` 처럼 꺼둔 채 남기는 것은 정상이다.
    _production(monkeypatch)
    _clear(monkeypatch)
    monkeypatch.setenv("MEDISCAN_ANALYZE_DEMO", value)
    config.assert_dev_only_flags_off()


def test_unknown_value_in_production_is_rejected(monkeypatch):
    # production 에 이 이름이 붙어 있다는 것 자체가 설정 실수다.
    # "maybe" 를 조용히 off 로 넘기면 오타(`MEDISCAN_ANALYZE_DEMO=ture`)를 못 잡는다.
    _production(monkeypatch)
    _clear(monkeypatch)
    monkeypatch.setenv("MEDISCAN_ANALYZE_DEMO", "ture")
    with pytest.raises(ConfigError):
        config.assert_dev_only_flags_off()


def test_development_startup_never_blocks(monkeypatch):
    _development(monkeypatch)
    for name in ALL_FLAGS:
        monkeypatch.setenv(name, "1")
    config.assert_dev_only_flags_off()


# ------------------------------------------------------- 읽는 시점 방어
# 기동 점검을 어떻게든 지나쳤더라도(직접 임포트한 스크립트 등) 값을 읽는 순간 막는다.
@pytest.mark.parametrize("name", ALL_FLAGS)
def test_reading_a_flag_in_production_raises(monkeypatch, name):
    _production(monkeypatch)
    _clear(monkeypatch)
    monkeypatch.setenv(name, "1")
    with pytest.raises(ConfigError):
        config.dev_only_flag(name)


@pytest.mark.parametrize("name", ALL_FLAGS)
def test_unset_flag_is_off_in_production(monkeypatch, name):
    _production(monkeypatch)
    _clear(monkeypatch)
    assert config.dev_only_flag(name) is False


def test_development_unknown_value_is_not_treated_as_on(monkeypatch):
    # 애매한 값을 켠 것으로 보면 위험한 쪽으로 기운다.
    _development(monkeypatch)
    monkeypatch.setenv("MEDISCAN_ANALYZE_DEMO", "maybe")
    assert config.dev_only_flag("MEDISCAN_ANALYZE_DEMO") is False


@pytest.mark.parametrize("value", ["1", "true", "True", "yes", "on"])
def test_development_accepts_common_on_values(monkeypatch, value):
    _development(monkeypatch)
    monkeypatch.setenv("MEDISCAN_ANALYZE_DEMO", value)
    assert config.dev_only_flag("MEDISCAN_ANALYZE_DEMO") is True


# ----------------------------------------------- 실제 사용처가 가드를 거치는가
def test_approx_grading_is_blocked_in_production(monkeypatch):
    # 검수되지 않은 기준으로 학습자를 평가하느니 채점을 못 하는 편이 낫다.
    _production(monkeypatch)
    _clear(monkeypatch)
    monkeypatch.setenv(grading.APPROX_ENV, "1")
    with pytest.raises(ConfigError):
        grading._approx_allowed()


def test_mock_seeding_is_blocked_in_production(monkeypatch):
    _production(monkeypatch)
    _clear(monkeypatch)
    monkeypatch.setenv(seed.MOCK_SEED_ENV, "1")
    with pytest.raises(ConfigError):
        seed.mock_seeding_enabled()


def test_analyze_demo_is_blocked_in_production(monkeypatch):
    _production(monkeypatch)
    _clear(monkeypatch)
    monkeypatch.setenv(analyze.DEMO_ENV, "1")
    with pytest.raises(ConfigError):
        analyze._demo_enabled()


# ------------------------------------------------- 실제 기동이 막히는가
# 위 테스트들은 함수 단위다. 여기서는 앱을 실제로 띄워 **DB 를 건드리기 전에**
# 막히는지 확인한다 (시드 스위치가 켜져 있으면 init_db 가 합성 케이스를 넣어버린다).
#
# 파일 경로로 확인하지 않는 이유: DATABASE_URL 은 app.db 임포트 시점에 이미 엔진으로
# 굳으므로, 나중에 환경변수를 바꿔도 DB 위치가 따라오지 않는다. 그래서 파일 유무는
# 항상 통과하는 가짜 검증이 된다. 대신 **init_db 가 불렸는지**를 직접 본다.
def _production_env(monkeypatch):
    monkeypatch.setenv("MEDISCAN_ENV", "production")
    monkeypatch.setenv("MEDISCAN_SECRET_KEY", "x" * 48)
    monkeypatch.setenv("MEDISCAN_CORS_ORIGINS", "https://example.com")
    _clear(monkeypatch)


def _spy_init_db(monkeypatch):
    from app import main

    calls = []
    monkeypatch.setattr(main, "init_db", lambda: calls.append(1))
    return calls


@pytest.mark.parametrize("name", ALL_FLAGS)
def test_app_refuses_to_boot_before_touching_db(monkeypatch, name):
    from fastapi.testclient import TestClient

    from app.main import app

    _production_env(monkeypatch)
    calls = _spy_init_db(monkeypatch)
    monkeypatch.setenv(name, "1")

    with pytest.raises(ConfigError):
        with TestClient(app):
            pass
    assert calls == [], "기동이 막히기 전에 init_db 가 실행됐다"


def test_clean_production_still_boots(monkeypatch):
    # 가드가 정상 배포까지 막으면 안 된다.
    from fastapi.testclient import TestClient

    from app.main import app

    _production_env(monkeypatch)
    calls = _spy_init_db(monkeypatch)

    with TestClient(app):
        pass
    assert calls == [1], "정상 설정인데 기동이 끝까지 가지 않았다"
