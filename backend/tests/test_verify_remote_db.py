"""
원격 DB 검증 도구 — **결함을 실제로 잡는지** 확인한다.

==========================================================================
점검 도구는 "통과"를 말할 자격을 스스로 증명해야 한다.
==========================================================================
전부 OK 를 찍는 검사기는 두 가지일 수 있다: 정말 문제가 없거나,
**아무것도 보고 있지 않거나.** 그래서 여기서는 일부러 깨뜨려 놓고
검사기가 그것을 잡는지 본다 (fault injection).

이 프로젝트에서 실제로 두 번 당했다 — 접근성 점검과 오류계약 점검이
각각 "0건 지적"을 냈는데, 알고 보니 대상 파일을 못 읽고 있었다.

각 테스트는 **일회용 SQLite 파일**을 쓴다. 원격 DB 를 건드리지 않는다.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

from scripts import verify_remote_db as v

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def fresh_db(tmp_path):
    """마이그레이션까지 올린 빈 SQLite DB.

    **자식 프로세스로 만든다.** 같은 프로세스에서 alembic 을 돌리면
    앱 엔진의 전역 상태가 다른 테스트로 새어 나간다.
    """
    path = tmp_path / "verify.db"
    url = "sqlite:///{}".format(path.as_posix())
    # **환경을 통째로 물려준다.** 처음에 `env={"PATH": "", ...}` 로 최소 환경만
    # 넘겼더니 자식 프로세스가 못 떠서 13개가 전부 skip 됐다 —
    # 그리고 skip 은 초록색으로 보인다. 검사기를 검사하는 테스트가
    # 조용히 안 도는 것이 여기서 가장 위험한 실패다.
    env = dict(os.environ, DATABASE_URL=url, PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", "from app.db import run_migrations; run_migrations()"],
        cwd=str(BACKEND_DIR), env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, (
        "마이그레이션 준비 실패 — 이 fixture 가 skip 되면 아래 결함 주입 테스트가 "
        "전부 조용히 사라진다:\n{}".format(result.stderr[-500:])
    )
    return sa.create_engine(url)


@pytest.fixture(autouse=True)
def clean_results():
    v.results.clear()
    yield
    v.results.clear()


def _statuses(item_prefix: str) -> list[str]:
    return [status for status, item, _ in v.results if item.startswith(item_prefix)]


# ----------------------------------------------------------- 정상 상태
def test_a_healthy_database_passes_every_check(fresh_db):
    v.check_migration_head(fresh_db)
    v.check_tables(fresh_db)
    v.check_schema_drift(fresh_db)
    v.check_constraints(fresh_db)
    assert v.FAIL not in [status for status, _, _ in v.results]


def test_the_checks_actually_report_what_they_looked_at(fresh_db):
    """**"0건 지적"이 "제대로 봤는데 없음"인지 알 수 있어야 한다.**"""
    v.check_tables(fresh_db)
    detail = next(d for s, i, d in v.results if i == "테이블")
    assert "개" in detail, "몇 개를 봤는지 알려주지 않으면 통과를 믿을 수 없다"


# ------------------------------------------------- 결함 주입: 스키마 드리프트
def test_a_hand_added_column_is_detected(fresh_db):
    """**대시보드에서 손으로 컬럼을 추가한 상황.**

    마이그레이션과 실제 스키마가 갈라지면, 다음 autogenerate 가
    그 변경을 "되돌리는" 마이그레이션을 만들어 버린다.
    """
    with fresh_db.begin() as conn:
        conn.execute(sa.text("alter table users add column secret_note varchar(50)"))

    v.check_schema_drift(fresh_db)
    assert _statuses("스키마 드리프트") == [v.FAIL]
    assert "secret_note" in v.results[-1][2]


def test_drift_check_ignores_the_alembic_bookkeeping_table(fresh_db):
    """`alembic_version` 은 모델에 없다 — 항상 diff 에 나오지만 결함이 아니다."""
    v.check_schema_drift(fresh_db)
    assert _statuses("스키마 드리프트") == [v.OK]


# ------------------------------------------------ 결함 주입: 마이그레이션
def test_a_database_behind_head_is_detected(fresh_db):
    with fresh_db.begin() as conn:
        conn.execute(sa.text("update alembic_version set version_num='e93378ca7e48'"))

    v.check_migration_head(fresh_db)
    assert _statuses("마이그레이션") == [v.FAIL]
    assert "e93378ca7e48" in v.results[-1][2]


def test_a_database_that_never_ran_migrations_is_detected(fresh_db):
    with fresh_db.begin() as conn:
        conn.execute(sa.text("drop table alembic_version"))

    v.check_migration_head(fresh_db)
    assert _statuses("마이그레이션") == [v.FAIL]
    assert "적용된 적이 없다" in v.results[-1][2]


def test_migration_check_does_not_use_postgres_only_functions(fresh_db):
    """**처음에 `to_regclass()` 를 썼다가 SQLite 에서 검사 자체가 죽었다.**

    점검 도구가 환경 때문에 죽으면 "확인 못함"이 "이상 없음"으로 보인다.
    """
    v.check_migration_head(fresh_db)
    assert _statuses("마이그레이션") == [v.OK]


# -------------------------------------------------------- 결함 주입: 테이블
def test_a_missing_table_is_detected(fresh_db):
    with fresh_db.begin() as conn:
        conn.execute(sa.text("drop table learning_events"))

    v.check_tables(fresh_db)
    assert _statuses("테이블") == [v.FAIL]
    assert "learning_events" in v.results[-1][2]


def test_an_unexpected_table_is_a_warning_not_a_failure(fresh_db):
    """모델에 없는 테이블은 실패가 아니다 — 확장 기능일 수 있다."""
    with fresh_db.begin() as conn:
        conn.execute(sa.text("create table analytics_scratch (id integer)"))

    v.check_tables(fresh_db)
    assert v.WARN in _statuses("테이블")
    assert v.FAIL not in _statuses("테이블")


# ------------------------------------------------ 결함 주입: 스테이징 순수성
def test_a_real_looking_account_is_flagged(fresh_db):
    """**스테이징에 실제 사용자가 있으면** 그 순간부터 개인정보 처리 시스템이 된다."""
    with fresh_db.begin() as conn:
        conn.execute(sa.text(
            "insert into users (user_id, email, nickname, is_admin, created_at) "
            "values ('u_real', 'someone@example.com', '실제', 0, '2026-01-01')"))

    v.check_row_counts(fresh_db, expect_staging=True)
    assert v.FAIL in _statuses("스테이징 순수성")


def test_staging_accounts_pass_the_purity_check(fresh_db):
    with fresh_db.begin() as conn:
        conn.execute(sa.text(
            "insert into users (user_id, email, nickname, is_admin, created_at) "
            "values ('u_stg', 'staging-admin@staging.invalid', '스테이징', 1, '2026-01-01')"))

    v.check_row_counts(fresh_db, expect_staging=True)
    assert _statuses("스테이징 순수성") == [v.OK]


def test_purity_is_not_checked_unless_asked(fresh_db):
    """운영 DB 를 검증할 때는 이 검사가 의미 없다."""
    with fresh_db.begin() as conn:
        conn.execute(sa.text(
            "insert into users (user_id, email, nickname, is_admin, created_at) "
            "values ('u_real', 'someone@example.com', '실제', 0, '2026-01-01')"))

    v.check_row_counts(fresh_db, expect_staging=False)
    assert not _statuses("스테이징 순수성")


# ----------------------------------------------------- 환경 차이 처리
def test_postgres_only_server_check_is_skipped_not_failed(fresh_db):
    """**"확인 못함"을 실패로 찍지 않는다.** 실패 목록이 잡음으로 차면 진짜를 놓친다."""
    v.check_server(fresh_db)
    assert _statuses("서버") == [v.INFO]


def test_transaction_pooler_is_warned_about():
    url = "postgresql://postgres.abc:pw@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres"
    v.check_connection_mode(url)
    assert v.WARN in _statuses("연결 방식")


def test_session_pooler_is_not_warned_about():
    """IPv4 전용 환경에서는 세션 풀러가 정답이다 — 잡음을 내지 않는다."""
    url = "postgresql://postgres.abc:pw@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres"
    v.check_connection_mode(url)
    assert v.WARN not in _statuses("연결 방식")


# ------------------------------------------------------- 한 항목이 터져도
def test_one_broken_check_does_not_stop_the_rest():
    """**점검 도구는 첫 오류에서 멈추면 안 된다.**

    멈추면 "나머지는 괜찮은가"를 알 수 없다.
    """
    def boom(_):
        raise RuntimeError("의도적 실패")

    v._safe("깨진 검사")(boom)(None)
    assert _statuses("깨진 검사") == [v.FAIL]
    assert "RuntimeError" in v.results[-1][2]
