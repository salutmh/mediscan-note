"""
Alembic 환경 설정.

접속 정보와 모델 메타데이터를 **앱에서 그대로 가져온다** — alembic.ini 에 URL 을 따로
적어두면 앱과 어긋날 수 있기 때문이다. 따라서 `DATABASE_URL` 환경변수 하나만 바꾸면
앱과 마이그레이션이 같은 DB 를 본다 (app/db.py 참고).
"""
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# backend/ 를 import 경로에 넣어 `app` 패키지를 찾을 수 있게 한다
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db import DATABASE_URL, Base  # noqa: E402
from app import models  # noqa: E402,F401  (모델이 Base.metadata 에 등록되도록 import)

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _common_options() -> dict:
    return {
        "target_metadata": target_metadata,
        # SQLite 는 ALTER 지원이 제한적이라 배치 모드로 테이블을 재생성한다.
        # (PostgreSQL 에서는 영향 없음)
        "render_as_batch": DATABASE_URL.startswith("sqlite"),
        "compare_type": True,
    }


def run_migrations_offline() -> None:
    context.configure(url=DATABASE_URL, literal_binds=True, dialect_opts={"paramstyle": "named"}, **_common_options())
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, **_common_options())
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
