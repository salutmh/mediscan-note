"""
마이그레이션 왕복 검증 도구 — **가드가 실제로 막는지** 확인한다.

==========================================================================
이 도구는 downgrade 로 테이블을 지운다. 가드가 새면 데이터가 사라진다.
==========================================================================
그래서 여기서 확인하는 것은 "왕복이 되는가"가 아니라
**"돌리면 안 되는 곳에서 돌지 않는가"** 다.

왕복 자체는 실제 Supabase 스테이징(PostgreSQL 17.6, 빈 상태)에서 한 번
성공 확인했다 — 테이블 8개와 리비전이 동일하게 복원됐다.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

from scripts import migration_roundtrip as mr

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def fresh_db(tmp_path):
    path = tmp_path / "roundtrip.db"
    url = "sqlite:///{}".format(path.as_posix())
    env = dict(os.environ, DATABASE_URL=url, PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", "from app.db import run_migrations; run_migrations()"],
        cwd=str(BACKEND_DIR), env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, result.stderr[-500:]
    return sa.create_engine(url)


def _add_user(engine, email="someone@example.com"):
    with engine.begin() as conn:
        conn.execute(sa.text(
            "insert into users (user_id, email, nickname, is_admin, created_at) "
            "values ('u_1', :email, '사용자', 0, '2026-01-01')"), {"email": email})


# ------------------------------------------------------------------ 가드
def test_a_database_with_rows_is_refused(fresh_db):
    """**행이 하나라도 있으면 거부한다.** downgrade 는 테이블을 지운다."""
    _add_user(fresh_db)
    with pytest.raises(SystemExit) as exc:
        mr._assert_empty(fresh_db)
    assert "데이터가 있는 DB" in str(exc.value)
    assert "users" in str(exc.value), "어느 테이블 때문인지 알려줘야 한다"


def test_a_staging_account_still_counts_as_data(fresh_db):
    """스테이징 계정이라고 지워도 되는 것은 아니다 — 다시 만들어야 한다."""
    _add_user(fresh_db, "staging-admin@staging.invalid")
    with pytest.raises(SystemExit):
        mr._assert_empty(fresh_db)


def test_production_is_refused_before_anything_else(fresh_db, monkeypatch):
    """**더 강한 가드를 먼저 본다.**

    순서를 반대로 뒀더니, 운영 DB 를 가리켰을 때 "데이터가 있다" 로만 막혀서
    production 가드가 실제로 도는지 확인할 수 없었다.
    """
    monkeypatch.setenv("MEDISCAN_ENV", "production")
    _add_user(fresh_db)
    with pytest.raises(SystemExit) as exc:
        mr._assert_empty(fresh_db)
    assert "production" in str(exc.value)


def test_an_empty_database_is_allowed(fresh_db):
    mr._assert_empty(fresh_db)  # 예외가 없으면 통과


def test_there_is_no_override_flag():
    """**우회 옵션을 일부러 만들지 않았다.**

    이 검사 하나 때문에 데이터를 잃는 것보다, 빈 DB 를 새로 만드는 편이 낫다.
    누가 `--force` 를 붙이면 그 순간 가드는 없는 것과 같다.
    """
    source = (BACKEND_DIR / "scripts" / "migration_roundtrip.py").read_text(encoding="utf-8")
    # **문서 문장이 아니라 실제 옵션 정의만 본다.** 처음엔 원문 전체를 뒤졌더니
    # "`--allow-rows` 같은 우회 옵션은 만들지 않았다" 라는 설명 문장에 걸려
    # 테스트가 실패했다 — 검사 대상을 좁히지 않으면 오탐이 난다.
    definitions = [line for line in source.splitlines() if "add_argument(" in line]
    for flag in ("--force", "--allow-rows", "--yes", "--skip-guard"):
        assert not any(flag in line for line in definitions), (
            "우회 옵션 {} 가 생겼다 — 가드를 끌 수 있으면 없는 것과 같다".format(flag))


# ------------------------------------------------------------ 스키마 비교
def test_snapshot_ignores_the_alembic_bookkeeping_table(fresh_db):
    assert "alembic_version" not in mr._schema_snapshot(fresh_db)


def test_snapshot_records_constraints_not_just_column_names(fresh_db):
    """컬럼 이름만 비교하면 **FK 가 사라진 것을 놓친다.**"""
    snapshot = mr._schema_snapshot(fresh_db)
    assert snapshot["consents"]["fk"], "FK 를 보고 있지 않다"
    assert snapshot["users"]["pk"] == ["user_id"]


def test_a_lost_foreign_key_is_reported():
    before = {"consents": {"columns": [], "pk": ["id"],
                           "fk": [(("user_id",), "users")], "indexes": []}}
    after = {"consents": {"columns": [], "pk": ["id"], "fk": [], "indexes": []}}
    problems = mr._diff(before, after)
    assert problems and "fk" in problems[0]


def test_a_lost_table_is_reported():
    problems = mr._diff({"users": {}}, {})
    assert problems == ["왕복 후 사라진 테이블: users"]


def test_an_identical_schema_reports_nothing(fresh_db):
    snapshot = mr._schema_snapshot(fresh_db)
    assert mr._diff(snapshot, snapshot) == []
