"""
원격 DB(스테이징/운영) 검증 — **아무것도 바꾸지 않는다.**

==========================================================================
`verify_postgres.py` 와 무엇이 다른가
==========================================================================
`verify_postgres` 는 downgrade 로 스키마를 통째로 내렸다 올린다. 일회용 컨테이너
전용이고 **원격 DB 에 쓰면 안 된다.** 이 스크립트는 읽기만 한다 —
스테이징이든 운영이든 안전하게 돌릴 수 있다.

무엇을 보는가
------------
  1. 연결 방식        — Direct / Session pooler / Transaction pooler 중 무엇인가
  2. 서버             — PostgreSQL 버전, 현재 사용자, 시간대
  3. 마이그레이션      — alembic 리비전이 head 와 같은가
  4. 테이블           — 모델이 기대하는 테이블이 전부 있는가
  5. 스키마 드리프트   — autogenerate 가 빈 diff 를 내는가 (**손으로 고친 흔적**을 잡는다)
  6. 제약             — PK / FK / UNIQUE / 인덱스가 실제로 걸려 있는가
  7. 데이터           — 테이블별 행 수, **운영 데이터가 섞여 있지 않은가**
  8. 재연결           — 연결이 끊긴 뒤 다음 요청이 살아나는가 (pool_pre_ping)

`--expect-staging` 을 주면 스테이징이 아닌 사용자 계정이 하나라도 있을 때 실패한다.

사용법
------
    cd backend
    python -m scripts.staging_secret run --mode session_pooler -- \
        python -m scripts.verify_remote_db --expect-staging
"""
import argparse
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import sqlalchemy as sa  # noqa: E402

results: list[tuple[str, str, str]] = []  # (상태, 항목, 설명)

OK = "OK"
WARN = "주의"
FAIL = "실패"
INFO = "정보"


def record(status: str, item: str, detail: str = "") -> None:
    results.append((status, item, detail))
    print("  [{}] {}{}".format(status, item, "  — " + detail if detail else ""))


def _safe(item: str):
    """**한 항목이 터져도 나머지를 계속한다.**

    점검 도구가 첫 오류에서 멈추면 "나머지는 괜찮은가"를 알 수 없다.
    """
    def wrap(fn):
        def run(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 — 점검 도구는 계속 돌아야 한다
                record(FAIL, item, "{}: {}".format(type(exc).__name__, str(exc)[:160]))
                return None
        return run
    return wrap


# ------------------------------------------------------------------ 검사들
def check_connection_mode(url: str) -> None:
    from app import db_connection

    described = db_connection.describe(url)
    record(INFO, "연결 방식", "{}  (port {}, sslmode {})".format(
        described["label"], described["port"], described["sslmode"] or "없음"))
    if described["mode"] == db_connection.TRANSACTION_POOLER:
        record(WARN, "연결 방식",
               "Transaction pooler 다 — 마이그레이션·백업에는 Direct 를 쓰세요")
    if described["mode"] == db_connection.SQLITE:
        record(WARN, "연결 방식", "SQLite 다 — 이 스크립트는 원격 DB 용이다")


def check_server(engine) -> None:
    if engine.dialect.name != "postgresql":
        # 이 검사는 PostgreSQL 전용이다. **"확인 못함"을 실패로 찍지 않는다** —
        # 실패 목록이 잡음으로 차면 진짜 실패를 놓친다.
        record(INFO, "서버", "{} — PostgreSQL 전용 검사는 건너뛴다".format(engine.dialect.name))
        return
    with engine.connect() as conn:
        version = conn.execute(sa.text("select version()")).scalar()
        user = conn.execute(sa.text("select current_user")).scalar()
        tz = conn.execute(sa.text("show timezone")).scalar()
        # **타임존이 UTC 가 아니면** 만료 시각 비교가 어긋날 수 있다
    record(INFO, "서버", version.split(" on ")[0])
    record(INFO, "접속 사용자", user)
    record(OK if tz.upper() == "UTC" else WARN, "서버 타임존", tz)


def check_migration_head(engine) -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    heads = set(ScriptDirectory.from_config(config).get_heads())

    # **엔진에 종속된 함수를 쓰지 않는다.** 처음에 `to_regclass()` 를 썼는데
    # PostgreSQL 전용이라, 같은 스크립트를 SQLite 로 돌리면 검사 자체가 죽었다.
    # 점검 도구가 환경 때문에 죽으면 "확인 못함"이 "이상 없음"으로 보인다.
    if not sa.inspect(engine).has_table("alembic_version"):
        record(FAIL, "마이그레이션", "alembic_version 테이블이 없다 — 적용된 적이 없다")
        return
    with engine.connect() as conn:
        current = {
            row[0] for row in conn.execute(sa.text("select version_num from alembic_version"))
        }

    if current == heads:
        record(OK, "마이그레이션", "head 와 일치 ({})".format(", ".join(sorted(heads))))
    else:
        record(FAIL, "마이그레이션",
               "DB={} / head={}".format(sorted(current) or "없음", sorted(heads)))


def check_tables(engine) -> set[str]:
    from app import models  # noqa: F401 — Base.metadata 채우기
    from app.db import Base

    expected = set(Base.metadata.tables)
    actual = set(sa.inspect(engine).get_table_names())

    missing = expected - actual
    if missing:
        record(FAIL, "테이블", "없는 테이블: {}".format(sorted(missing)))
    else:
        record(OK, "테이블", "{}개 모두 존재".format(len(expected)))

    # 모델에 없는 테이블은 실패가 아니다 (alembic_version 등)
    extra = actual - expected - {"alembic_version"}
    if extra:
        record(WARN, "테이블", "모델에 없는 테이블: {}".format(sorted(extra)))
    return actual


def check_schema_drift(engine) -> None:
    """**손으로 고친 흔적을 잡는다.**

    누군가 대시보드에서 컬럼을 추가하면 마이그레이션과 실제 스키마가 갈라진다.
    다음 autogenerate 가 그 변경을 "되돌리는" 마이그레이션을 만들어 버린다.
    """
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app import models  # noqa: F401
    from app.db import Base

    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        diff = compare_metadata(context, Base.metadata)

    # alembic_version 은 모델에 없으므로 항상 diff 에 나온다 — 제외한다
    meaningful = [d for d in diff if "alembic_version" not in str(d)]
    if not meaningful:
        record(OK, "스키마 드리프트", "모델과 일치 (diff 없음)")
    else:
        record(FAIL, "스키마 드리프트", "{}건: {}".format(
            len(meaningful), str(meaningful)[:300]))


def check_constraints(engine) -> None:
    """PK / FK / UNIQUE / 인덱스가 **실제로** 걸려 있는가.

    SQLite 는 외래키를 기본적으로 강제하지 않아서, 로컬에서는 FK 없이도
    전부 통과한다. 원격 PostgreSQL 에서 처음 터지는 종류의 문제다.
    """
    from app import models  # noqa: F401
    from app.db import Base

    inspector = sa.inspect(engine)
    missing_pk, missing_fk, missing_unique = [], [], []

    for name, table in Base.metadata.tables.items():
        if name not in inspector.get_table_names():
            continue
        if table.primary_key.columns and not inspector.get_pk_constraint(name)["constrained_columns"]:
            missing_pk.append(name)

        expected_fk = {
            (fk.parent.name, fk.column.table.name) for fk in table.foreign_keys
        }
        actual_fk = {
            (col, ref["referred_table"])
            for ref in inspector.get_foreign_keys(name)
            for col in ref["constrained_columns"]
        }
        for item in expected_fk - actual_fk:
            missing_fk.append("{}.{} -> {}".format(name, item[0], item[1]))

        expected_unique = {
            col.name for col in table.columns if col.unique
        }
        actual_unique = {
            col
            for uc in inspector.get_unique_constraints(name)
            for col in uc["column_names"]
        } | {
            col
            for idx in inspector.get_indexes(name) if idx.get("unique")
            for col in idx["column_names"]
        }
        # PK 컬럼은 UNIQUE 로 따로 잡히지 않는다
        pk_cols = set(inspector.get_pk_constraint(name)["constrained_columns"])
        missing_unique += [
            "{}.{}".format(name, col)
            for col in expected_unique - actual_unique - pk_cols
        ]

    for label, items in (("PK", missing_pk), ("FK", missing_fk), ("UNIQUE", missing_unique)):
        if items:
            record(FAIL, "제약 ({})".format(label), "누락: {}".format(items))
        else:
            record(OK, "제약 ({})".format(label), "모두 존재")


def check_row_counts(engine, expect_staging: bool) -> None:
    from app import models  # noqa: F401
    from app.db import Base

    inspector = sa.inspect(engine)
    counts = {}
    with engine.connect() as conn:
        for name in sorted(Base.metadata.tables):
            if name not in inspector.get_table_names():
                continue
            counts[name] = conn.execute(
                sa.text("select count(*) from {}".format(name))).scalar()
    record(INFO, "행 수", ", ".join(
        "{}={}".format(k, v) for k, v in counts.items() if v) or "전부 비어 있음")

    if not expect_staging:
        return

    # **운영 데이터가 섞여 있지 않은가.** 스테이징에 실제 사용자가 있으면
    # 그 순간부터 개인정보 처리 시스템이 된다.
    with engine.connect() as conn:
        rows = conn.execute(sa.text(
            "select email, provider from users "
            "where email is null or email not like '%@staging.invalid'")).all()
    if rows:
        record(FAIL, "스테이징 순수성",
               "스테이징이 아닌 계정 {}개 — 운영 데이터일 수 있다".format(len(rows)))
    else:
        record(OK, "스테이징 순수성", "모든 계정이 @staging.invalid")


def check_reconnect(engine) -> None:
    """**원격 DB 는 유휴 연결을 끊는다.**

    끊긴 연결을 풀에서 그대로 꺼내 쓰면 다음 요청이 500 이 된다.
    여기서는 서버측에서 연결을 강제로 끊고, 그다음 쿼리가 사는지 본다.
    """
    with engine.connect() as conn:
        pid = conn.execute(sa.text("select pg_backend_pid()")).scalar()

    # 같은 풀의 다른 연결로 방금 그 연결을 죽인다
    with engine.connect() as killer:
        try:
            killer.execute(sa.text("select pg_terminate_backend(:pid)"), {"pid": pid})
        except Exception as exc:  # 풀러 환경에서는 권한이 없을 수 있다
            record(WARN, "재연결", "연결을 강제 종료할 수 없어 확인 못함: {}".format(
                type(exc).__name__))
            return

    try:
        with engine.connect() as conn:
            conn.execute(sa.text("select 1"))
        record(OK, "재연결", "끊긴 연결 뒤에도 정상 (pool_pre_ping 동작)")
    except Exception as exc:  # noqa: BLE001
        record(FAIL, "재연결", "{}: {}".format(type(exc).__name__, str(exc)[:120]))


# --------------------------------------------------------------------- main
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="원격 DB 를 읽기만 하며 검증한다")
    parser.add_argument("--expect-staging", action="store_true",
                        help="스테이징이 아닌 계정이 있으면 실패로 본다")
    parser.add_argument("--skip-reconnect", action="store_true",
                        help="연결 강제 종료 검사를 건너뛴다")
    args = parser.parse_args(argv)

    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL 이 없습니다. staging_secret run --mode ... 로 실행하세요.")

    from app.db import _engine_options

    print("원격 DB 검증 (읽기 전용)\n")
    _safe("연결 방식")(check_connection_mode)(url)

    engine = sa.create_engine(url, **_engine_options(url))
    _safe("서버")(check_server)(engine)
    _safe("마이그레이션")(check_migration_head)(engine)
    _safe("테이블")(check_tables)(engine)
    _safe("스키마 드리프트")(check_schema_drift)(engine)
    _safe("제약")(check_constraints)(engine)
    _safe("행 수")(check_row_counts)(engine, args.expect_staging)
    if not args.skip_reconnect:
        _safe("재연결")(check_reconnect)(engine)

    failures = [r for r in results if r[0] == FAIL]
    warnings = [r for r in results if r[0] == WARN]
    print("\n{}건 검사 — 실패 {} / 주의 {}".format(len(results), len(failures), len(warnings)))
    for status, item, detail in failures:
        print("  실패: {} — {}".format(item, detail))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
