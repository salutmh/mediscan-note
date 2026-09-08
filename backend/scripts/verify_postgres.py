"""
PostgreSQL 이식성 검증 — 배포 DB 에서 정말 도는지 확인한다.

**왜 필요한가**
개발은 SQLite, 배포는 PostgreSQL 이다. 테스트가 SQLite 에서만 돌면 이식성 문제를
**배포에서 처음 만난다.** 실제로 이 검증을 처음 돌렸을 때 테스트 1건이 깨졌다 —
SQLite 는 외래키를 기본적으로 강제하지 않아서, ORM cascade 를 우회하는 대량 삭제가
조용히 통과하고 있었다 (PostgreSQL 에서는 FK 위반).

무엇을 보는가
------------
  1. 마이그레이션이 head 까지 올라가는가
  2. downgrade 로 되돌아가는가 (되돌릴 수 없는 마이그레이션을 배포하면 곤란하다)
  3. 스키마가 모델과 일치하는가 (autogenerate 가 빈 diff 를 내는가)
  4. 전체 테스트 스위트가 PostgreSQL 에서도 통과하는가

사용법
------
    # 일회용 컨테이너를 띄운 뒤
    docker run -d --name mediscan-pg-test -e POSTGRES_PASSWORD=testpw \
      -e POSTGRES_DB=mediscan_test -p 55432:5432 postgres:16-alpine

    cd backend
    python -m scripts.verify_postgres \
      --url postgresql+psycopg2://postgres:testpw@localhost:55432/mediscan_test

    # 테스트까지 함께 (느리다)
    python -m scripts.verify_postgres --url ... --with-tests

**운영 DB 를 가리키지 말 것.** downgrade 로 스키마를 통째로 내렸다 올린다.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 검증용 임시 키 (실제 secret 이 아니다 — production 가드를 통과시키기 위한 값)
VERIFY_SECRET = "postgres-verify-only-not-a-real-secret-key"

results: list[tuple[bool, str, str]] = []


def record(ok: bool, label: str, detail: str = "") -> None:
    results.append((ok, label, detail))
    print(f"  {'통과' if ok else '실패'}  {label}{f' - {detail}' if detail else ''}")


def _env(url: str) -> dict:
    env = dict(os.environ)
    env["DATABASE_URL"] = url
    env.setdefault("MEDISCAN_SECRET_KEY", VERIFY_SECRET)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run(args: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def check_guard(url: str) -> bool:
    if url.startswith("sqlite"):
        print("SQLite URL 입니다. 이 스크립트는 PostgreSQL 검증용입니다.")
        return False
    if not url.startswith("postgresql"):
        print(f"PostgreSQL URL 이 아닙니다: {url.split('://')[0]}")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="PostgreSQL 이식성 검증 (일회용 DB 에만 쓸 것)")
    parser.add_argument("--url", required=True, help="postgresql+psycopg2://user:pw@host:port/db")
    parser.add_argument("--with-tests", action="store_true", help="전체 pytest 를 PostgreSQL 로 실행")
    args = parser.parse_args()

    if not check_guard(args.url):
        return 1

    env = _env(args.url)
    print(f"대상: {args.url.split('@')[-1]}")
    print()

    # 1) 연결
    probe = _run(["-c", "from app.db import engine; engine.connect().close(); print('ok')"], env)
    record(probe.returncode == 0, "연결", probe.stderr.strip().splitlines()[-1] if probe.returncode else "")
    if probe.returncode != 0:
        return 1

    # 2) upgrade head
    up = _run(["-m", "alembic", "upgrade", "head"], env)
    applied = (up.stdout + up.stderr).count("Running upgrade")
    record(up.returncode == 0, "마이그레이션 upgrade head", f"{applied}단계 적용")

    # 3) 모델 <-> 스키마 드리프트 (autogenerate 가 빈 diff 여야 한다)
    drift = _run(
        [
            "-c",
            "from alembic.config import Config;"
            "from alembic import command;"
            "from alembic.autogenerate import compare_metadata;"
            "from alembic.migration import MigrationContext;"
            "from app.db import Base, engine;"
            "import app.models;"
            "ctx=MigrationContext.configure(engine.connect());"
            "diff=compare_metadata(ctx, Base.metadata);"
            "print('DIFF', diff)",
        ],
        env,
    )
    has_diff = "DIFF []" not in drift.stdout
    record(
        not has_diff,
        "모델과 스키마 일치 (autogenerate 빈 diff)",
        "" if not has_diff else drift.stdout.strip()[-200:],
    )

    # 4) downgrade -> upgrade (되돌릴 수 있는가)
    down = _run(["-m", "alembic", "downgrade", "base"], env)
    reverted = (down.stdout + down.stderr).count("Running downgrade")
    record(down.returncode == 0, "마이그레이션 downgrade base", f"{reverted}단계 되돌림")

    reup = _run(["-m", "alembic", "upgrade", "head"], env)
    record(reup.returncode == 0, "downgrade 후 다시 upgrade", f"{(reup.stdout + reup.stderr).count('Running upgrade')}단계")

    # 5) 전체 테스트
    if args.with_tests:
        test_env = dict(env)
        test_env["MEDISCAN_TEST_DATABASE_URL"] = args.url
        print("\n  전체 테스트 실행 중 (수 분 걸립니다)...")
        tests = _run(["-m", "pytest", "-q"], test_env)
        summary = [ln for ln in (tests.stdout or "").splitlines() if "passed" in ln or "failed" in ln]
        record(tests.returncode == 0, "pytest (PostgreSQL)", summary[-1] if summary else "")

    print()
    failed = [label for ok, label, _ in results if not ok]
    if failed:
        print(f"실패 {len(failed)}건: {', '.join(failed)}")
        return 1
    print("전체 통과 - PostgreSQL 에서 스키마와 앱이 정상 동작합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
