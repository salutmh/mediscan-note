"""
DB 백업 — Closed Beta 학습 데이터를 잃지 않기 위한 최소 장치.

**왜 필요한가**
학습 이력은 사용자가 시간을 들여 쌓은 것이고 다시 만들 수 없다. 케이스(교육 콘텐츠)는
파이프라인으로 다시 만들 수 있지만, 누가 무엇을 언제 어떻게 틀렸는지는 복구할 방법이 없다.
백업 없이 Closed Beta 를 열면 사고 한 번에 그게 전부 사라진다.

무엇을 백업하는가
----------------
  SQLite      파일을 **온라인 백업 API** 로 복사한다. 단순 파일 복사는 쓰기 중이면
              깨진 스냅샷이 나올 수 있다.
  PostgreSQL  `pg_dump` 를 부른다 (설치되어 있어야 한다).

**백업에 들어가는 것**: 사용자 계정·동의 이력·제출 이력·학습 로그.
개인정보가 들어 있으므로 **백업 파일도 원본과 같은 수준으로 보호해야 한다**
(공유 폴더·git·클라우드 공개 버킷에 두지 말 것).

**백업하지 않는 것**: 케이스 영상·마스크(`app/static/cases/`)는 별도 자산이라
파이프라인으로 재생성하거나 따로 보관한다.

사용법
------
    cd backend
    python -m scripts.backup_db --out ../backups
    python -m scripts.backup_db --out /var/backups/mediscan --keep 14

    # 복구 (SQLite): 서버를 내리고 파일을 제자리에 되돌린다
    # 복구 (PostgreSQL): psql -d mediscan -f <덤프파일>
"""
import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db import DATABASE_URL  # noqa: E402

STAMP = "%Y%m%d-%H%M%S"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime(STAMP)


def backup_sqlite(url: str, out_dir: Path) -> Path:
    """온라인 백업 API 로 일관된 스냅샷을 뜬다.

    서버가 돌고 있는 중에도 안전하다 — 단순 `cp` 는 쓰기 도중이면 깨진 파일이 나온다.
    """
    path = Path(url.split("sqlite:///", 1)[-1])
    if not path.exists():
        raise FileNotFoundError(f"SQLite 파일이 없습니다: {path}")

    target = out_dir / f"mediscan-{_timestamp()}.sqlite"
    source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)  # 온라인 백업 API
        finally:
            dest.close()
    finally:
        source.close()
    return target


def backup_postgres(url: str, out_dir: Path) -> Path:
    """pg_dump 를 부른다. 비밀번호는 URL 에서 PGPASSWORD 로 옮겨 명령줄에 남지 않게 한다."""
    if shutil.which("pg_dump") is None:
        raise RuntimeError("pg_dump 를 찾을 수 없습니다. PostgreSQL 클라이언트를 설치하세요.")

    from urllib.parse import unquote, urlparse

    parsed = urlparse(url.replace("postgresql+psycopg2://", "postgresql://"))
    target = out_dir / f"mediscan-{_timestamp()}.sql"

    env = dict(os.environ)
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)

    cmd = [
        "pg_dump",
        "--host", parsed.hostname or "localhost",
        "--port", str(parsed.port or 5432),
        "--username", unquote(parsed.username or "postgres"),
        "--dbname", (parsed.path or "/").lstrip("/"),
        "--no-password",
        "--file", str(target),
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump 실패: {result.stderr.strip()[:300]}")
    return target


def prune(out_dir: Path, keep: int) -> list[Path]:
    """오래된 백업을 지운다. 디스크가 차서 백업이 멈추는 것을 막기 위함이다."""
    if keep <= 0:
        return []
    backups = sorted(
        [p for p in out_dir.glob("mediscan-*") if p.is_file()],
        key=lambda p: p.name,
        reverse=True,
    )
    removed = backups[keep:]
    for path in removed:
        path.unlink()
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="DB 백업 (개인정보 포함 — 보관 위치에 주의)")
    parser.add_argument("--out", required=True, help="백업 폴더")
    parser.add_argument("--keep", type=int, default=7, help="보관할 백업 개수 (0이면 삭제 안 함)")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    driver = DATABASE_URL.split("://", 1)[0]
    print(f"대상: {driver} / 출력: {out_dir}")

    try:
        if DATABASE_URL.startswith("sqlite"):
            target = backup_sqlite(DATABASE_URL, out_dir)
        elif DATABASE_URL.startswith("postgresql"):
            target = backup_postgres(DATABASE_URL, out_dir)
        else:
            print(f"지원하지 않는 드라이버입니다: {driver}")
            return 1
    except Exception as exc:
        print(f"백업 실패: {exc}")
        return 1

    size_mb = target.stat().st_size / 1024 / 1024
    print(f"백업 완료: {target.name} ({size_mb:.2f} MB)")

    removed = prune(out_dir, args.keep)
    if removed:
        print(f"오래된 백업 {len(removed)}건 정리: {', '.join(p.name for p in removed)}")

    print()
    print("※ 이 파일에는 계정·동의 이력·학습 이력이 들어 있습니다.")
    print("  원본 DB 와 같은 수준으로 보호하세요 (git·공개 저장소·공유 폴더 금지).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
