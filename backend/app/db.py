"""
DB 연결/세션.

DATABASE_URL 환경변수 하나로 로컬(SQLite)과 배포(PostgreSQL)를 모두 커버한다.
  - 미설정: backend/mediscan.db 라는 SQLite 파일을 쓴다 (팀원이 아무 설치 없이 바로 실행 가능)
  - PostgreSQL: DATABASE_URL=postgresql+psycopg2://user:pw@host:5432/mediscan

models.py 는 두 DB 모두에서 동작하는 타입만 쓴다(JSON 포함). 그래서 나중에 AWS RDS 로 옮길 때
URL 만 바꾸면 되고 모델·라우터는 손대지 않는다.

스키마는 **Alembic 마이그레이션이 유일한 기준**이다 (backend/alembic/).
`create_all` 은 더 이상 기동 경로에서 쓰지 않는다 — 모델을 바꾸면 반드시 마이그레이션을 만든다.
"""
import logging
import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import ConfigError, is_production

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE_PATH = BACKEND_DIR / "mediscan.db"


def _resolve_database_url() -> str:
    """DB 주소. **production 에서는 반드시 명시해야 한다.**

    개발에서는 미설정 시 로컬 SQLite 파일로 떨어진다 (팀원이 아무 설치 없이 실행 가능).
    production 에서 같은 폴백이 일어나면 **데이터 손실 사고**가 된다 —
    컨테이너 안 로컬 파일에 학습 이력이 쌓이고, 재배포하면 통째로 사라진다.
    그것도 겉보기에는 정상 동작하므로 아무도 눈치채지 못한다. 그래서 기동을 막는다.

    SQLite 자체를 금지하지는 않는다. 볼륨을 붙인 SQLite 로 소규모 운영을 할 수도 있다 —
    다만 그 선택을 **명시적으로** 하게 만든다.
    """
    configured = os.getenv("DATABASE_URL", "").strip()
    if configured:
        return configured

    if is_production():
        raise ConfigError(
            "DATABASE_URL 이 설정되지 않았습니다. production 에서는 필수입니다.\n"
            "  미설정 시 컨테이너 안 로컬 SQLite 파일로 떨어지고, 재배포하면 학습 데이터가 사라집니다.\n"
            "  예: DATABASE_URL=postgresql+psycopg2://user:pw@host:5432/mediscan\n"
            "  (의도적으로 SQLite 를 쓰려면 볼륨 경로를 직접 지정하세요: sqlite:////data/mediscan.db)"
        )
    return f"sqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"


DATABASE_URL = _resolve_database_url()

# SQLite 는 기본적으로 커넥션을 만든 스레드에서만 쓸 수 있다.
# FastAPI 는 요청을 스레드풀에서 처리하므로 이 옵션이 필요하다 (PostgreSQL 에는 불필요).
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI 의존성. 요청 하나당 세션 하나."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _assert_not_legacy_schema() -> None:
    """Alembic 도입 이전(create_all)에 만들어진 DB 를 감지해 명확히 안내한다.

    그런 DB 에는 테이블은 있는데 alembic_version 이 없어서 `upgrade head` 가
    "table already exists" 로 실패한다. 원인을 모른 채 헤매지 않도록 먼저 잡아준다.
    """
    from sqlalchemy import inspect

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if not tables or "alembic_version" in tables:
        return
    if tables & {"users", "cases", "submissions", "consents"}:
        raise RuntimeError(
            "Alembic 도입 이전에 만들어진 DB 입니다 (alembic_version 테이블 없음).\n"
            "  - 개발용이라 버려도 되면: DB 파일/스키마를 삭제한 뒤 다시 실행하세요.\n"
            "  - 데이터를 유지해야 하면: cd backend && alembic stamp head\n"
            f"  현재 DATABASE_URL={DATABASE_URL.split('://', 1)[0]}://..."
        )


def run_migrations() -> None:
    """Alembic 을 프로그램 안에서 실행해 스키마를 head 까지 올린다.

    앱 기동·테스트 모두 이 경로를 쓴다. 덕분에 마이그레이션이 매번 실제로 검증된다.
    (CLI 로 하려면: cd backend && alembic upgrade head)
    """
    from alembic import command
    from alembic.config import Config

    _assert_not_legacy_schema()

    ini_path = BACKEND_DIR / "alembic.ini"
    config = Config(str(ini_path))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    # env.py 가 app.db.DATABASE_URL 을 읽으므로 여기서 URL 을 따로 넘기지 않는다.
    command.upgrade(config, "head")


def init_db() -> None:
    """앱 시작 시 호출 — 마이그레이션 적용 후 케이스 시드."""
    from app import models  # noqa: F401  — 모델이 Base.metadata 에 등록되도록 import
    from app import token_revocation
    from app.seed import seed_cases

    run_migrations()
    with SessionLocal() as db:
        seed_cases(db)
        # 이미 만료된 토큰의 폐기 기록은 남겨 둘 이유가 없다(어차피 거부된다).
        # 목록이 무한히 자라면 요청마다 도는 조회가 계속 무거워진다.
        purged = token_revocation.purge_expired(db)
        if purged:
            logger.info("만료된 토큰 폐기 기록 %s건 정리", purged)
