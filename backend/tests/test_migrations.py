"""
Alembic 마이그레이션 테스트.

스키마의 기준은 create_all 이 아니라 마이그레이션이다. 아래를 고정한다:
  1. 빈 DB 에 upgrade head → 모델과 동일한 스키마가 만들어진다
  2. downgrade base → 전부 되돌아간다
  3. 모델과 마이그레이션 사이에 드리프트가 없다 (autogenerate 결과가 비어야 한다)
"""
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.db import BACKEND_DIR, Base

EXPECTED_TABLES = {"users", "consents", "cases", "submissions", "case_slices"}


def _config_for(db_path: Path) -> tuple[Config, str]:
    """개발 DB 와 완전히 분리된 임시 DB 를 대상으로 하는 Alembic 설정."""
    url = f"sqlite:///{db_path.as_posix()}"
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    # env.py 는 app.db.DATABASE_URL 을 읽으므로, 테스트에서는 URL 을 직접 주입한다.
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["test_url"] = url
    return config, url


@pytest.fixture
def migrated_db(tmp_path, monkeypatch):
    """임시 경로에 마이그레이션으로 만든 DB. 개발용 mediscan.db 는 건드리지 않는다."""
    db_path = tmp_path / "migration_test.db"
    config, url = _config_for(db_path)
    # env.py 안의 DATABASE_URL 참조까지 임시 DB 로 향하게 한다
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr("app.db.DATABASE_URL", url, raising=False)
    return config, url, db_path


def test_upgrade_creates_expected_schema(migrated_db):
    config, url, db_path = migrated_db
    command.upgrade(config, "head")

    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert EXPECTED_TABLES <= tables
        assert "alembic_version" in tables, "마이그레이션 버전 테이블이 있어야 한다"
    finally:
        engine.dispose()


def test_submissions_has_v03_columns(migrated_db):
    """v0.3 이후 계약 컬럼이 마이그레이션에 반영되어 있다."""
    config, url, _ = migrated_db
    command.upgrade(config, "head")

    engine = create_engine(url)
    try:
        columns = {c["name"] for c in inspect(engine).get_columns("submissions")}
    finally:
        engine.dispose()

    assert {"reference_mask_url", "evaluation_method", "is_provisional"} <= columns
    assert "ai_mask_url" not in columns, "v0.2 컬럼이 남아 있으면 안 된다"
    assert "model_version" not in columns


def test_volume_and_slice_schema(migrated_db):
    """뇌 MRI 는 volume 단위이므로 cases 에 volume 정보가, case_slices 에 slice 가 있어야 한다."""
    config, url, _ = migrated_db
    command.upgrade(config, "head")

    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        case_columns = {c["name"] for c in inspector.get_columns("cases")}
        slice_columns = {c["name"] for c in inspector.get_columns("case_slices")}
    finally:
        engine.dispose()

    assert {"volume_id", "representative_slice"} <= case_columns
    # slice_index 는 2.5D 확장 시 인접 slice 조회 키라 반드시 보존되어야 한다
    assert {"case_id", "slice_index", "image_url", "mask_url", "lesion_area_px"} <= slice_columns


def test_downgrade_removes_all_tables(migrated_db):
    config, url, _ = migrated_db
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert not (EXPECTED_TABLES & tables), f"되돌리지 못한 테이블: {EXPECTED_TABLES & tables}"


def test_upgrade_is_repeatable(migrated_db):
    """downgrade 후 다시 upgrade 해도 같은 스키마가 나온다."""
    config, url, _ = migrated_db
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_engine(url)
    try:
        assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_no_schema_drift_between_models_and_migrations(migrated_db):
    """모델을 바꾸고 마이그레이션을 만들지 않으면 여기서 실패한다."""
    config, url, _ = migrated_db
    command.upgrade(config, "head")

    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"compare_type": True, "render_as_batch": True}
            )
            diff = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    assert diff == [], f"모델과 마이그레이션이 어긋납니다. `alembic revision --autogenerate` 필요: {diff}"


def test_legacy_database_without_alembic_version_is_rejected(tmp_path, monkeypatch):
    """create_all 로 만들어진 옛 DB 는 명확한 안내와 함께 거부된다."""
    import app.db as db_module

    db_path = tmp_path / "legacy.db"
    url = f"sqlite:///{db_path.as_posix()}"
    legacy_engine = create_engine(url)
    Base.metadata.create_all(bind=legacy_engine)  # alembic_version 없이 테이블만 생성

    monkeypatch.setattr(db_module, "engine", legacy_engine)
    try:
        with pytest.raises(RuntimeError) as exc:
            db_module._assert_not_legacy_schema()
    finally:
        legacy_engine.dispose()

    assert "alembic" in str(exc.value).lower()
