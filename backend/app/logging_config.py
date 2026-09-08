"""
애플리케이션 로깅 설정.

**왜 필요한가**
앱 곳곳에 `logger.info(...)` 를 써뒀는데 (계정 삭제, 폐기 기록 정리, 모델 실패 등)
**아무 데도 출력되지 않고 있었다.** 로깅을 설정하지 않으면 root 로거 기본 레벨이
WARNING 이라 INFO 가 조용히 버려진다. 로그를 남기는 코드를 써놓고 실제로는 남기지 않는
상태였고, Closed Beta 에서 "제출이 안 된다"는 문의를 받아도 볼 것이 없다.

**무엇을 남기지 않는가**
비밀번호·토큰·요청 본문·업로드 영상은 절대 로그에 넣지 않는다. 사용자 식별은 내부
`user_id` 로만 하고 이메일·닉네임은 남기지 않는다 (의료 서비스라 로그도 개인정보가 된다).
이 원칙은 코드 리뷰로 지킨다 — 포맷터가 걸러주지 않는다.

설정
----
    MEDISCAN_LOG_LEVEL   DEBUG | INFO(기본) | WARNING | ERROR
    MEDISCAN_LOG_FORMAT  text(기본) | json     json 은 로그 수집기에 넣기 좋다
"""
import json
import logging
import os
import sys

APP_LOGGER = "app"
LEVEL_ENV = "MEDISCAN_LOG_LEVEL"
FORMAT_ENV = "MEDISCAN_LOG_FORMAT"

DEFAULT_LEVEL = "INFO"

# 로그 레코드에 이미 들어 있는 표준 속성 — JSON 으로 낼 때 중복으로 넣지 않는다
_STANDARD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"asctime", "message"}


class JsonFormatter(logging.Formatter):
    """한 줄 = JSON 하나. 로그 수집기가 파싱하기 좋다."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # logger.info("...", extra={"case_id": ...}) 로 붙인 값을 그대로 싣는다
        for key, value in record.__dict__.items():
            if key not in _STANDARD and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def _level() -> int:
    raw = os.getenv(LEVEL_ENV, DEFAULT_LEVEL).strip().upper()
    return getattr(logging, raw, logging.INFO) if raw else logging.INFO


def _formatter() -> logging.Formatter:
    if os.getenv(FORMAT_ENV, "text").strip().lower() == "json":
        return JsonFormatter()
    return logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def configure() -> None:
    """앱 기동 시 한 번 호출한다 (main.py).

    `app` 네임스페이스만 설정한다 — uvicorn 자신의 로거는 건드리지 않는다.
    `propagate = False` 로 두어 root 로 올라가 중복 출력되는 것을 막는다.
    여러 번 불려도 핸들러가 쌓이지 않게 기존 핸들러를 정리한다.
    """
    logger = logging.getLogger(APP_LOGGER)
    logger.setLevel(_level())
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_formatter())
    logger.addHandler(handler)


def describe() -> dict:
    """/health 에 노출 — 로그가 어디로 얼마나 나가는지 확인용."""
    return {
        "level": logging.getLevelName(logging.getLogger(APP_LOGGER).level),
        "format": os.getenv(FORMAT_ENV, "text").strip().lower(),
    }
