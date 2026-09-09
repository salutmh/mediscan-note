"""
DB 연결 방식 판별 — 특히 Supabase 의 세 모드.

==========================================================================
**포트 번호만으로 판별하면 틀린다.**
==========================================================================
Supabase 는 **세션 풀러도 5432 를 쓴다.** Direct 와 Session pooler 는 포트가 같고
**host 와 사용자명이 다르다.** 포트로만 가르면 세션 풀러를 Direct 로 착각한다.

| 방식 | host | port | 사용자명 |
|---|---|---|---|
| Direct | `db.<ref>.supabase.co` | 5432 | `postgres` |
| Session pooler | `<region>.pooler.supabase.com` | 5432 | `postgres.<ref>` |
| Transaction pooler | `<region>.pooler.supabase.com` | 6543 | `postgres.<ref>` |

이 구분이 중요한 이유: **마이그레이션과 백업은 Direct 를 써야 한다.**
트랜잭션 풀러는 prepared statement 가 세션에 남지 않아 깨질 수 있다.
"""
import pytest

from app import db_connection as conn

REF = "abcdefghijklmnop"
REGION = "aws-0-ap-northeast-2"

DIRECT_URL = f"postgresql+psycopg2://postgres:pw@db.{REF}.supabase.co:5432/postgres"
SESSION_URL = f"postgresql+psycopg2://postgres.{REF}:pw@{REGION}.pooler.supabase.com:5432/postgres"
TRANSACTION_URL = (
    f"postgresql+psycopg2://postgres.{REF}:pw@{REGION}.pooler.supabase.com:6543/postgres"
)


# ------------------------------------------------------------ 모드 판별
def test_direct_connection_is_detected():
    assert conn.parse(DIRECT_URL)["mode"] == conn.DIRECT


def test_session_pooler_is_not_mistaken_for_direct():
    """**둘 다 5432 다.** host 와 사용자명으로 갈라야 한다."""
    assert conn.parse(SESSION_URL)["mode"] == conn.SESSION_POOLER
    assert conn.parse(SESSION_URL)["port"] == 5432
    assert conn.parse(DIRECT_URL)["port"] == 5432


def test_transaction_pooler_is_detected():
    assert conn.parse(TRANSACTION_URL)["mode"] == conn.TRANSACTION_POOLER


def test_port_alone_does_not_decide():
    """5432 라고 Direct 가 아니고, 풀러 host 라고 트랜잭션 모드가 아니다."""
    assert conn.parse(SESSION_URL)["mode"] != conn.DIRECT
    assert conn.parse(SESSION_URL)["mode"] != conn.TRANSACTION_POOLER


def test_non_supabase_postgres_is_marked_as_such():
    info = conn.parse("postgresql+psycopg2://u:p@db.internal:5432/mediscan")
    assert info["mode"] == conn.OTHER_POSTGRES
    assert info["is_supabase"] is False


def test_sqlite_is_detected():
    assert conn.parse("sqlite:///./mediscan.db")["mode"] == conn.SQLITE


def test_empty_url_does_not_crash():
    assert conn.parse("")["mode"] == conn.UNKNOWN


@pytest.mark.parametrize(
    "url", [DIRECT_URL, SESSION_URL, TRANSACTION_URL, "postgresql://u:p@h:5432/d"]
)
def test_driver_suffix_does_not_confuse_parsing(url):
    """`postgresql+psycopg2://` 같은 접미사가 붙어도 파싱돼야 한다."""
    info = conn.parse(url)
    assert info["host"]
    assert info["port"] == int(url.rsplit(":", 1)[1].split("/")[0])


# ------------------------------------------------------- 비밀 노출 방지
def test_describe_does_not_leak_password_or_project_ref():
    """/health 에 실리는 값이라 비밀번호도, 프로젝트 식별자도 넣지 않는다."""
    described = conn.describe(DIRECT_URL)
    text = str(described)
    assert "pw" not in text.split("mode")[0] or "pw@" not in text
    assert REF not in text, "프로젝트 식별자가 노출됐다"
    assert described["host_suffix"] == "*.supabase.co"


def test_describe_reports_the_mode_in_words():
    assert "Direct" in conn.describe(DIRECT_URL)["label"]
    assert "Session pooler" in conn.describe(SESSION_URL)["label"]
    assert "Transaction pooler" in conn.describe(TRANSACTION_URL)["label"]


# ------------------------------------------------------------ 권고 사항
def test_transaction_pooler_is_warned_for_migrations():
    """**마이그레이션은 Direct 를 써야 한다.**"""
    notes = conn.advisories(TRANSACTION_URL, purpose="migration")
    assert any("Direct connection" in n for n in notes)
    assert any("prepared statement" in n for n in notes)


def test_transaction_pooler_is_warned_for_backup():
    notes = conn.advisories(TRANSACTION_URL, purpose="backup")
    assert any("Direct connection" in n for n in notes)


def test_transaction_pooler_is_warned_for_runtime():
    """이 서비스는 상시 실행 프로세스라 트랜잭션 풀러가 필요하지 않다."""
    notes = conn.advisories(TRANSACTION_URL, purpose="runtime")
    assert any("serverless" in n for n in notes)


def test_session_pooler_is_explained_not_blocked():
    """IPv4 만 되는 환경에서는 세션 풀러가 정답일 수 있다 — 막지 않는다."""
    notes = conn.advisories(SESSION_URL, purpose="runtime")
    assert any("Direct 처럼 동작" in n for n in notes)
    assert not any("쓸 수 없" in n for n in notes)


def test_direct_connection_mentions_ipv6():
    """Direct 는 기본이 IPv6 다 — IPv4 전용 네트워크에서 안 붙는다."""
    notes = conn.advisories(DIRECT_URL, purpose="runtime")
    assert any("IPv6" in n for n in notes)


def test_wrong_pooler_username_is_flagged():
    """풀러는 `postgres.<project_ref>` 형태를 쓴다. 그냥 `postgres` 면 연결되지 않는다."""
    bad = f"postgresql://postgres:pw@{REGION}.pooler.supabase.com:5432/postgres"
    notes = conn.advisories(bad, purpose="runtime")
    assert any("project_ref" in n for n in notes)


def test_missing_sslmode_is_mentioned_for_supabase():
    notes = conn.advisories(DIRECT_URL, purpose="runtime")
    assert any("sslmode" in n for n in notes)


def test_sslmode_present_is_not_mentioned():
    notes = conn.advisories(DIRECT_URL + "?sslmode=require", purpose="runtime")
    assert not any("sslmode" in n for n in notes)


def test_sqlite_runtime_advisory():
    notes = conn.advisories("sqlite:///./x.db", purpose="runtime")
    assert any("PostgreSQL" in n for n in notes)


# ------------------------------------------------------- 연결 풀 설정
def test_remote_postgres_gets_pre_ping():
    """**원격 DB 는 유휴 연결을 끊는다.**

    pool_pre_ping 이 없으면 죽은 연결을 꺼내주고 요청이 500 이 된다.
    로컬 컨테이너로는 이 문제가 보이지 않아서 오래 남아 있었다.
    """
    from app.db import _engine_options

    options = _engine_options("postgresql+psycopg2://u:p@host:5432/d")
    assert options["pool_pre_ping"] is True
    assert options["pool_recycle"] > 0


def test_sqlite_does_not_get_pool_options():
    """SQLite 는 파일이라 해당 없다."""
    from app.db import _engine_options

    assert _engine_options("sqlite:///./x.db") == {}
