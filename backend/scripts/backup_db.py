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

    # 이미 만들어 둔 백업만 다시 검사 (복구 훈련용)
    python -m scripts.backup_db --verify-only ../backups/mediscan-20260909-013000.sqlite

    # 복구 (SQLite): 서버를 내리고 파일을 제자리에 되돌린다
    # 복구 (PostgreSQL): psql -d mediscan -f <덤프파일>

**백업을 만든 뒤 반드시 읽어본다**
"파일이 생겼다"와 "그 파일에 데이터가 들어 있다"는 다르다. 실제로 겪을 수 있는 조용한 실패:

  - `DATABASE_URL` 을 주지 않고 돌려서 **엉뚱한(비어 있는) 개발 DB** 를 백업한다.
    파일은 정상적으로 만들어지고 "백업 완료" 가 찍힌다. 사고가 나야 알게 된다.
  - 디스크가 중간에 차서 잘린 파일이 남는다. 크기만 보면 그럴듯하다.
  - pg_dump 가 일부 테이블만 덤프하고 0 으로 끝난다.

그래서 백업 직후 파일을 **열어서** 무결성과 행 수를 확인하고, 원본과 대조한다.
사용자가 다시 만들 수 없는 데이터(계정·동의·제출·학습 이력)가 0건이면 실패로 처리한다.
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


# 사용자가 다시 만들 수 없는 데이터. 케이스(교육 콘텐츠)는 파이프라인으로 다시 만들 수 있지만
# 누가 무엇을 언제 어떻게 틀렸는지는 복구할 방법이 없다. 백업의 존재 이유가 이 표다.
IRREPLACEABLE_TABLES = ["users", "consents", "submissions", "learning_events"]


def source_counts() -> dict[str, int]:
    """원본 DB 의 행 수. 대조 기준이 된다."""
    from sqlalchemy import create_engine, text

    engine = create_engine(DATABASE_URL)
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        for table in IRREPLACEABLE_TABLES:
            try:
                counts[table] = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            except Exception:
                counts[table] = -1  # 테이블 없음 (구버전 DB)
    engine.dispose()
    return counts


def verify_sqlite(target: Path) -> dict[str, int]:
    """백업 파일을 실제로 열어 무결성을 확인하고 행 수를 센다."""
    conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"백업 파일이 손상되었습니다: {integrity}")
        counts: dict[str, int] = {}
        for table in IRREPLACEABLE_TABLES:
            try:
                counts[table] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                counts[table] = -1
        return counts
    finally:
        conn.close()


COPY_END = r"\."  # pg_dump 는 COPY 블록을 이 두 글자로 닫는다


def verify_postgres_dump(target: Path) -> dict[str, int]:
    """plain SQL 덤프의 COPY 블록을 세어 테이블별 행 수를 얻는다.

    pg_dump 를 되돌려 넣어보는 것이 가장 확실하지만, 그러려면 빈 DB 가 하나 더 있어야 한다.
    운영 서버에서 백업할 때마다 그럴 수는 없으므로 덤프 내용을 직접 읽는다.
    적어도 "파일은 생겼는데 안이 비었다" 는 여기서 잡힌다.
    """
    counts = {table: -1 for table in IRREPLACEABLE_TABLES}
    current: str | None = None
    rows = 0
    with target.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if current is not None:
                if line.startswith(COPY_END):
                    counts[current] = rows
                    current, rows = None, 0
                else:
                    rows += 1
                continue
            if line.startswith("COPY "):
                name = line.split()[1].split(".")[-1].strip('"')
                if name in counts:
                    current, rows = name, 0
    if current is not None:
        raise RuntimeError(f"덤프가 중간에 끊겼습니다 ({current} 블록이 닫히지 않음)")
    return counts


def source_is_empty(source: dict[str, int]) -> bool:
    """원본에 사용자 데이터가 하나도 없는가.

    백업 자체의 실패는 아니다(원본을 그대로 옮겼으니 맞다). 다만 운영 DB 를 백업하려던
    것이었다면 DATABASE_URL 이 엉뚱한 곳을 가리키고 있다는 신호다. 그래서 "통과" 로
    뭉개지 않고 따로 말한다.
    """
    return all(source.get(table, 0) <= 0 for table in IRREPLACEABLE_TABLES)


def report_verification(source: dict[str, int], backup: dict[str, int]) -> bool:
    """대조 결과를 출력하고 백업을 믿어도 되는지 반환한다."""
    ok = True
    print()
    print("백업 검증 (원본 대조)")
    for table in IRREPLACEABLE_TABLES:
        src, dst = source.get(table, -1), backup.get(table, -1)
        if src == -1 and dst == -1:
            print(f"  - {table}: 양쪽 모두 없음 (구버전 스키마)")
            continue
        if dst == -1:
            print(f"  ! {table}: 원본에는 {src}건인데 백업에 테이블이 없습니다")
            ok = False
            continue
        mark = "-" if dst == src else "!"
        note = "" if dst == src else f" (원본 {src}건)"
        print(f"  {mark} {table}: {dst}건{note}")
        # 백업 뒤에 새 행이 들어올 수 있으므로 dst < src 는 정상이다.
        # 하지만 원본에 있는데 백업이 0 이면 백업이 아니다.
        if src > 0 and dst == 0:
            ok = False
        if dst > src >= 0:
            print(f"    원본보다 많습니다 — 다른 DB 를 백업했는지 확인하세요")
            ok = False

    if source_is_empty(source):
        print()
        print("  ※ 원본에 사용자 데이터가 한 건도 없습니다.")
        print(f"    DATABASE_URL 이 의도한 DB 를 가리키는지 확인하세요 (현재: {DATABASE_URL.split('://', 1)[0]}).")
        print("    운영 DB 를 백업하려는 것이었다면 이 백업은 쓸모가 없습니다.")
    return ok


def verify_backup(target: Path, source: dict[str, int]) -> bool:
    if target.suffix == ".sqlite":
        backup = verify_sqlite(target)
    else:
        backup = verify_postgres_dump(target)
    return report_verification(source, backup)


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
    parser.add_argument("--out", help="백업 폴더 (--verify-only 일 때는 불필요)")
    parser.add_argument("--keep", type=int, default=7, help="보관할 백업 개수 (0이면 삭제 안 함)")
    parser.add_argument(
        "--verify-only",
        metavar="파일",
        help="새로 백업하지 않고 기존 백업 파일만 검사한다 (복구 훈련용)",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="백업 후 검증을 건너뛴다 (권장하지 않음)",
    )
    args = parser.parse_args()

    if args.verify_only:
        target = Path(args.verify_only)
        if not target.exists():
            print(f"백업 파일이 없습니다: {target}")
            return 1
        print(f"검사 대상: {target.name}")
        try:
            return 0 if verify_backup(target, source_counts()) else 1
        except Exception as exc:
            print(f"검증 실패: {exc}")
            return 1

    if not args.out:
        print("--out 또는 --verify-only 중 하나가 필요합니다.")
        return 1
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
    print(f"백업 파일 생성: {target.name} ({size_mb:.2f} MB)")

    # "파일이 생겼다"와 "그 파일에 데이터가 들어 있다"는 다르다. 열어서 확인한다.
    verified = True
    source = None
    if not args.skip_verify:
        try:
            source = source_counts()
            verified = verify_backup(target, source)
        except Exception as exc:
            print(f"검증 실패: {exc}")
            verified = False

    removed = prune(out_dir, args.keep)
    if removed:
        print(f"오래된 백업 {len(removed)}건 정리: {', '.join(p.name for p in removed)}")

    print()
    print("※ 이 파일에는 계정·동의 이력·학습 이력이 들어 있습니다.")
    print("  원본 DB 와 같은 수준으로 보호하세요 (git·공개 저장소·공유 폴더 금지).")

    if not verified:
        print()
        print("백업 파일은 만들어졌지만 **검증에 실패했습니다**. 이 백업을 믿지 마세요.")
        return 1
    print()
    if source is not None and source_is_empty(source):
        print("백업 완료 — 다만 위 경고대로 원본에 사용자 데이터가 없습니다.")
    else:
        print("백업 완료 (검증 통과).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
