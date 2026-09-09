"""
API 로 나가는 시각에 **항상 offset 이 붙는지** 확인한다.

==========================================================================
offset 없는 ISO 문자열은 브라우저가 로컬 시간으로 읽는다.
==========================================================================
`2026-09-09T06:12:00` 은 어느 시간대인지 말하지 않는다. JavaScript 의
`new Date(...)` 는 이런 문자열을 로컬 시간으로 해석하므로, 한국(UTC+9)에서
**방금 만든 기록이 "9시간 전"으로 보였다.** 화면에서 실제로 그렇게 나왔다.

왜 오래 안 보였나
-----------------
`submitted_at` 컬럼은 `DateTime(timezone=True)` 지만 **SQLite 는 시간대를
저장하지 않는다.** PostgreSQL 에서는 tz 가 붙어 오고 SQLite 에서는 안 붙는다 —
즉 **개발 환경에서만 어긋났다.** 배포 DB 로는 재현되지 않는 종류의 버그다.

`wrong_notes.py` 는 원래 이 처리를 하고 있었는데 다른 라우터가 따라가지 않아,
같은 시각이 화면마다 다르게 보였다.
"""
import re
from datetime import datetime, timedelta, timezone

import pytest

from app.timefmt import KST, as_utc, to_kst_iso

# ISO 8601 끝의 `+09:00` / `Z` / `-05:00`
HAS_OFFSET = re.compile(r"(Z|[+-]\d{2}:\d{2})$")


# ------------------------------------------------------------------ 단위
def test_a_naive_datetime_is_treated_as_utc():
    """**DB 에 UTC 로 넣고 있다** (`models.utcnow`). 그 전제를 명시한다."""
    naive = datetime(2026, 9, 9, 6, 0, 0)
    assert as_utc(naive).tzinfo == timezone.utc


def test_an_aware_datetime_is_left_alone():
    aware = datetime(2026, 9, 9, 6, 0, 0, tzinfo=timezone.utc)
    assert as_utc(aware) is aware


def test_output_always_carries_an_offset():
    """이것 하나가 이 모듈의 존재 이유다."""
    assert HAS_OFFSET.search(to_kst_iso(datetime(2026, 9, 9, 6, 0, 0)))


def test_naive_utc_becomes_kst_nine_hours_later():
    """06:00 UTC = 15:00 KST. **같은 순간이지 다른 시각이 아니다.**"""
    assert to_kst_iso(datetime(2026, 9, 9, 6, 0, 0)).startswith("2026-09-09T15:00:00+09:00")


def test_an_aware_value_is_converted_not_relabelled():
    """tz 를 바꿔 붙이면 9시간이 통째로 어긋난다 — 변환해야 한다."""
    aware = datetime(2026, 9, 9, 6, 0, 0, tzinfo=timezone.utc)
    assert to_kst_iso(aware).startswith("2026-09-09T15:00:00+09:00")


def test_a_value_from_another_timezone_is_converted():
    other = datetime(2026, 9, 9, 1, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    assert to_kst_iso(other).startswith("2026-09-09T15:00:00+09:00")


def test_none_stays_none():
    assert to_kst_iso(None) is None
    assert as_utc(None) is None


def test_kst_is_utc_plus_nine():
    assert KST.utcoffset(None) == timedelta(hours=9)


# --------------------------------------------------- 실제 응답에서 확인
def _all_timestamps(payload) -> list[str]:
    """응답 안의 시각처럼 생긴 문자열을 전부 모은다."""
    found = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, str) and key.endswith(("_at", "_time")):
                found.append(value)
            else:
                found += _all_timestamps(value)
    elif isinstance(payload, list):
        for item in payload:
            found += _all_timestamps(item)
    return found


@pytest.fixture
def user_with_two_attempts(user_a, roi_match, roi_mismatch):
    """맞힌 뒤 다시 틀린 상태.

    **순서가 중요하다.** 마지막이 match 면 복습노트가 비어서, 그 응답의
    시각 검사가 조용히 아무것도 안 보게 된다 (실제로 그렇게 헛돌았다).
    """
    user_a.submit(roi_match)
    user_a.submit(roi_mismatch)
    return user_a


@pytest.mark.parametrize(
    "path", ["/api/me/dashboard", "/api/cases", "/api/wrong-notes"]
)
def test_every_timestamp_in_a_response_has_an_offset(user_with_two_attempts, path):
    """**한 화면이라도 빠지면 그 화면의 시각만 9시간 어긋난다.**"""
    payload = user_with_two_attempts.get(path).json()
    stamps = _all_timestamps(payload)
    assert stamps, f"{path} 에서 시각 필드를 하나도 못 찾았다 — 검사가 헛돌고 있다"
    for stamp in stamps:
        assert HAS_OFFSET.search(stamp), f"{path} 의 {stamp!r} 에 offset 이 없다"


def test_submit_response_previous_attempt_time_has_an_offset(user_a, roi_mismatch):
    """결과 화면의 "이전 시도" 시각도 같은 문제를 갖고 있었다."""
    user_a.submit(roi_mismatch)
    body = user_a.submit(roi_mismatch).json()

    previous = body["progress"]["previous"]
    assert previous is not None
    assert HAS_OFFSET.search(previous["submitted_at"])


def test_a_just_created_record_is_not_hours_in_the_past(user_a, roi_mismatch):
    """**증상 자체를 고정한다.** 방금 만든 기록이 몇 시간 전으로 보이면 안 된다."""
    user_a.submit(roi_mismatch)
    stamp = user_a.get("/api/me/dashboard").json()["recent_activity"][0]["submitted_at"]

    parsed = datetime.fromisoformat(stamp)
    drift = abs((datetime.now(timezone.utc) - parsed).total_seconds())
    assert drift < 300, f"방금 만든 기록이 {drift / 3600:.1f}시간 어긋나 있다"
