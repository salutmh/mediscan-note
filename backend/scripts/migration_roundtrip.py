"""
마이그레이션 왕복 검증 — head → base → head 가 되는가.

==========================================================================
**되돌릴 수 없는 마이그레이션은 배포 전에 알아야 한다.**
==========================================================================
배포 중 문제가 생겨 되돌려야 할 때, downgrade 가 깨져 있으면 그때 알게 된다.
그 시점에는 이미 운영 DB 가 중간 상태다.

이 스크립트는 **데이터가 하나도 없을 때만** 동작한다
------------------------------------------------------
downgrade 는 테이블을 지운다. 행이 하나라도 있으면 **거부한다.**
"막 만든 빈 스테이징"에서 한 번 돌려 보라고 만든 도구다.
데이터가 들어간 뒤에는 다시 돌리면 안 된다.

`--allow-rows` 같은 우회 옵션은 **일부러 만들지 않았다.** 이 검사 하나 때문에
데이터를 잃는 것보다, 빈 DB 를 새로 만들어 확인하는 편이 낫다.

사용법
------
    cd backend
    python -m scripts.staging_secret run --mode session_pooler -- \
        python -m scripts.migration_roundtrip
"""
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import sqlalchemy as sa  # noqa: E402


def _alembic_config():
    from alembic.config import Config

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config


def _table_counts(engine) -> dict[str, int]:
    from app import models  # noqa: F401
    from app.db import Base

    inspector = sa.inspect(engine)
    counts = {}
    with engine.connect() as conn:
        for name in sorted(Base.metadata.tables):
            if inspector.has_table(name):
                counts[name] = conn.execute(
                    sa.text("select count(*) from {}".format(name))).scalar()
    return counts


def _assert_empty(engine) -> None:
    # **더 강한 가드를 먼저 본다.** 순서를 반대로 뒀더니, 운영 DB 를 가리켰을 때
    # "데이터가 있다" 로만 막혀서 production 가드가 도는지 확인할 수 없었다.
    if os.getenv("MEDISCAN_ENV", "").lower() == "production":
        raise SystemExit("MEDISCAN_ENV=production 입니다. 운영 DB 에서는 돌리지 않습니다.")

    counts = _table_counts(engine)
    populated = {k: v for k, v in counts.items() if v}
    if populated:
        raise SystemExit(
            "중단합니다: 데이터가 있는 DB 입니다 — {}\n"
            "downgrade 는 테이블을 지웁니다. 빈 DB 에서만 돌리세요.".format(populated)
        )


def _current_revisions(engine) -> set[str]:
    if not sa.inspect(engine).has_table("alembic_version"):
        return set()
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(sa.text("select version_num from alembic_version"))}


def _schema_snapshot(engine) -> dict:
    """비교용 스키마 요약. **컬럼 순서까지는 보지 않는다** (의미 없는 차이다)."""
    inspector = sa.inspect(engine)
    snapshot = {}
    for table in sorted(inspector.get_table_names()):
        if table == "alembic_version":
            continue
        snapshot[table] = {
            "columns": sorted(
                (c["name"], str(c["type"]).upper(), bool(c["nullable"]))
                for c in inspector.get_columns(table)
            ),
            "pk": sorted(inspector.get_pk_constraint(table)["constrained_columns"]),
            "fk": sorted(
                (tuple(sorted(f["constrained_columns"])), f["referred_table"])
                for f in inspector.get_foreign_keys(table)
            ),
            "indexes": sorted(
                (tuple(sorted(i["column_names"])), bool(i.get("unique")))
                for i in inspector.get_indexes(table)
            ),
        }
    return snapshot


def _diff(before: dict, after: dict) -> list[str]:
    problems = []
    for table in sorted(set(before) | set(after)):
        if table not in after:
            problems.append("왕복 후 사라진 테이블: {}".format(table))
        elif table not in before:
            problems.append("왕복 후 생긴 테이블: {}".format(table))
        else:
            for key in ("columns", "pk", "fk", "indexes"):
                if before[table][key] != after[table][key]:
                    problems.append("{}.{} 가 달라졌다\n    이전: {}\n    이후: {}".format(
                        table, key, before[table][key], after[table][key]))
    return problems


def main(argv=None) -> int:
    from alembic import command

    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL 이 없습니다.")

    from app.db import _engine_options

    engine = sa.create_engine(url, **_engine_options(url))
    config = _alembic_config()

    print("마이그레이션 왕복 검증 (head -> base -> head)\n")
    _assert_empty(engine)
    print("  빈 DB 확인 — 진행합니다")

    before_revisions = _current_revisions(engine)
    print("  현재 리비전: {}".format(sorted(before_revisions) or "없음"))

    if not before_revisions:
        command.upgrade(config, "head")
        before_revisions = _current_revisions(engine)

    before = _schema_snapshot(engine)
    print("  스키마 스냅샷: 테이블 {}개".format(len(before)))

    print("\n  downgrade base ...")
    command.downgrade(config, "base")
    remaining = [t for t in sa.inspect(engine).get_table_names() if t != "alembic_version"]
    if remaining:
        print("  주의: downgrade 후에도 남은 테이블 — {}".format(remaining))

    print("  upgrade head ...")
    command.upgrade(config, "head")

    after = _schema_snapshot(engine)
    after_revisions = _current_revisions(engine)

    print("\n결과")
    problems = _diff(before, after)
    if before_revisions != after_revisions:
        problems.append("리비전이 다르다: {} -> {}".format(
            sorted(before_revisions), sorted(after_revisions)))

    if problems:
        print("  왕복 후 스키마가 달라졌습니다 ({}건):".format(len(problems)))
        for problem in problems:
            print("  - {}".format(problem))
        return 1

    print("  OK — 테이블 {}개, 리비전 {} 모두 동일하게 복원".format(
        len(after), sorted(after_revisions)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
