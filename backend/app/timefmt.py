"""
시각을 API 로 내보내는 한 가지 방법.

==========================================================================
**offset 없는 ISO 문자열을 내보내면 브라우저가 로컬 시간으로 읽는다.**
==========================================================================
`2026-09-09T06:12:00` 은 어느 시간대인지 말하지 않는다. JavaScript 의
`new Date(...)` 는 이런 문자열을 **로컬 시간**으로 해석하므로, 한국(UTC+9)에서는
방금 만든 기록이 "9시간 전"으로 보인다. 실제로 그렇게 보였다.

왜 생겼나
---------
`submitted_at` 컬럼은 `DateTime(timezone=True)` 이지만 **SQLite 는 시간대를
저장하지 않는다.** PostgreSQL 에서 읽으면 tz 가 붙어 오고 SQLite 에서는 안 붙는다.
그래서 개발(SQLite)에서만 시각이 어긋나고, 그 사실을 알아채기 어려웠다.

`.isoformat()` 을 직접 부르지 말고 여기를 쓴다.
`app/routers/wrong_notes.py` 는 원래 이 처리를 하고 있었는데, 다른 라우터가
따라가지 않아 화면마다 시각 기준이 달랐다.
"""
from datetime import datetime, timedelta, timezone

# 화면 표기는 한국 기준이다 (api-spec.md 0절 예시: 2026-09-10T14:00:00+09:00).
KST = timezone(timedelta(hours=9))


def as_utc(value: datetime | None) -> datetime | None:
    """tz 가 없는 값을 UTC 로 본다. **DB 에 UTC 로 넣고 있기 때문이다**
    (`models.utcnow` 가 `datetime.now(timezone.utc)`)."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def to_kst_iso(value: datetime | None) -> str | None:
    """API 로 내보낼 ISO 8601 문자열. **항상 offset 이 붙는다.**"""
    aware = as_utc(value)
    return aware.astimezone(KST).isoformat() if aware else None
