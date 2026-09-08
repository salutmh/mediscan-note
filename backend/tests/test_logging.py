"""
로깅 설정 (RELEASE_READINESS M1).

**왜 필요했나**
앱 곳곳에 `logger.info(...)` 를 써뒀는데 **아무 데도 출력되지 않고 있었다.**
로깅을 설정하지 않으면 root 로거 기본 레벨이 WARNING 이라 INFO 가 조용히 버려진다.
로그를 남기는 코드를 써놓고 실제로는 남기지 않는 상태였다.

여기서 확인하는 것:
  - INFO 가 실제로 나가는가 (이게 원래 문제였다)
  - JSON 포맷이 파싱 가능한가 (로그 수집기에 넣으려면)
  - **민감정보가 로그에 섞이지 않는가**
"""
import json
import logging

import pytest

from app import logging_config


@pytest.fixture(autouse=True)
def _restore_logging():
    """테스트가 로거 설정을 바꾸므로 원래대로 되돌린다."""
    logger = logging.getLogger(logging_config.APP_LOGGER)
    before = (logger.level, list(logger.handlers), logger.propagate)
    yield
    logger.setLevel(before[0])
    logger.handlers = before[1]
    logger.propagate = before[2]


def _capture(monkeypatch, capsys, level="INFO", fmt="text"):
    monkeypatch.setenv(logging_config.LEVEL_ENV, level)
    monkeypatch.setenv(logging_config.FORMAT_ENV, fmt)
    logging_config.configure()
    return capsys


# ------------------------------------------------------------------ 기본 동작
def test_info_logs_actually_appear(monkeypatch, capsys):
    """원래 문제: INFO 가 조용히 버려지고 있었다."""
    _capture(monkeypatch, capsys)
    logging.getLogger("app.sample").info("계정 삭제: user_id=u_123")

    out = capsys.readouterr().out
    assert "계정 삭제: user_id=u_123" in out
    assert "INFO" in out


def test_level_can_be_raised(monkeypatch, capsys):
    _capture(monkeypatch, capsys, level="WARNING")
    logging.getLogger("app.sample").info("보이면 안 되는 정보성 로그")
    logging.getLogger("app.sample").warning("보여야 하는 경고")

    out = capsys.readouterr().out
    assert "보이면 안 되는" not in out
    assert "보여야 하는 경고" in out


def test_unknown_level_falls_back_to_info(monkeypatch, capsys):
    """오타 때문에 로그가 통째로 사라지면 안 된다."""
    _capture(monkeypatch, capsys, level="VERBOSE")
    logging.getLogger("app.sample").info("기본 레벨로 떨어져야 한다")
    assert "기본 레벨로 떨어져야 한다" in capsys.readouterr().out


# ------------------------------------------------------------------ JSON
def test_json_format_is_parseable(monkeypatch, capsys):
    _capture(monkeypatch, capsys, fmt="json")
    logging.getLogger("app.sample").info("케이스 등록 완료", extra={"case_id": "VS-SEG-202"})

    line = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(line)  # 파싱되지 않으면 수집기에 넣을 수 없다

    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.sample"
    assert payload["message"] == "케이스 등록 완료"
    assert payload["case_id"] == "VS-SEG-202"


def test_json_includes_exception_details(monkeypatch, capsys):
    _capture(monkeypatch, capsys, fmt="json")
    try:
        raise ValueError("의도적 오류")
    except ValueError:
        logging.getLogger("app.sample").exception("모델 추론 실패")

    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert "의도적 오류" in payload["exception"]


# -------------------------------------------------- 민감정보가 새지 않는가 (핵심)
def test_no_secrets_are_logged_by_the_app():
    """로그에 비밀번호·토큰·요청 본문을 넣는 코드가 없는지 소스에서 확인한다.

    포맷터가 걸러주지 않으므로 이건 코드 리뷰로 지켜야 한다.
    이 테스트는 그 리뷰를 자동화한 것이다.
    """
    from pathlib import Path

    app_dir = Path(__file__).resolve().parent.parent / "app"
    forbidden = ("password", "access_token", "provider_token", "mask_png_base64", "image_base64")

    offenders = []
    for path in app_dir.rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith(("logger.", "logging.getLogger")):
                continue
            lowered = stripped.lower()
            for word in forbidden:
                if word in lowered:
                    offenders.append(f"{path.name}:{number} {stripped[:80]}")

    assert not offenders, "로그에 민감정보가 들어갈 수 있다:\n" + "\n".join(offenders)


def test_health_reports_logging_settings(client):
    """배포에서 로그가 어디로 얼마나 나가는지 확인할 수 있어야 한다."""
    body = client.get("/health").json()
    assert set(body["logging"]) == {"level", "format"}


# -------------------------------------------------------------- 중복 설정
def test_configure_is_idempotent(monkeypatch):
    """여러 번 호출해도 핸들러가 쌓이면 안 된다 (쌓이면 같은 줄이 여러 번 찍힌다)."""
    monkeypatch.setenv(logging_config.LEVEL_ENV, "INFO")
    for _ in range(3):
        logging_config.configure()

    handlers = logging.getLogger(logging_config.APP_LOGGER).handlers
    assert len(handlers) == 1, f"핸들러가 {len(handlers)}개로 늘었다 — 로그가 중복 출력된다"


def test_app_logs_do_not_propagate_to_root(monkeypatch, capsys):
    """root 로 올라가면 uvicorn 핸들러와 겹쳐 같은 줄이 두 번 나온다."""
    _capture(monkeypatch, capsys)
    assert logging.getLogger(logging_config.APP_LOGGER).propagate is False
