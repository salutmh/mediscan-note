"""
복구 훈련 — 백업을 **실제로 되돌려서 서비스가 뜨는지** 확인한다.

**"읽힌다"와 "복구된다"는 다르다.**
`backup_db.py` 는 백업 파일을 열어 무결성과 행 수를 확인한다. 거기까지는 "파일이
멀쩡하다"는 뜻이고, **그 파일로 서비스가 실제로 동작하는지**는 다른 질문이다.
스키마가 현재 코드보다 옛 버전이면 되돌려도 앱이 뜨지 않는다.

해본 적 없는 백업은 백업이 아니다. 이 스크립트가 그 훈련을 자동화한다.

무엇을 하는가
------------
  1) 백업 파일을 **격리된 임시 위치**로 복원한다 (운영 DB 는 건드리지 않는다)
  2) 복원된 DB 로 **마이그레이션을 최신까지 올린다** (옛 백업도 살아나는지)
  3) 복원된 DB 로 **앱을 실제로 띄운다** (기동 실패는 여기서 잡힌다)
  4) 학습자 경로가 도는지 확인한다 (가입 -> 케이스 목록 -> 케이스 상세)
  5) 다시 만들 수 없는 데이터가 살아왔는지 센다 (계정·동의·제출·학습 이력)

==========================================================================
**운영 DB 를 절대 건드리지 않는다.**
==========================================================================
복원은 임시 폴더에서만 일어나고 끝나면 지운다. 이 스크립트에는 운영 DB 로 되돌리는
경로가 없다 — 실제 복구는 사람이 서버를 내리고 파일을 제자리에 두는 일이다.

사용법
------
    cd backend
    python -m scripts.restore_drill --backup ../backups/mediscan-20260909-013000.sqlite
    python -m scripts.restore_drill --backup <파일> --keep   # 임시 폴더를 남긴다

종료코드: 복구된 DB 로 서비스가 뜨지 않으면 1.
"""
import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 다시 만들 수 없는 데이터 (backup_db.py 와 같은 기준)
IRREPLACEABLE_TABLES = ["users", "consents", "submissions", "learning_events"]

CONSENTS = {
    "agree_terms": True,
    "agree_privacy": True,
    "agree_sensitive_data": True,
    "agree_ai_notice": True,
    "agree_age14": True,
    "agree_marketing": False,
}


def _step(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'통과' if ok else '실패'}  {label}{f' — {detail}' if detail else ''}")
    return ok


def restore_sqlite(backup: Path, workdir: Path) -> Path:
    """백업 파일을 임시 위치로 복사한다. **운영 DB 는 건드리지 않는다.**"""
    target = workdir / "restored.sqlite"
    shutil.copy2(backup, target)
    return target


def restore_postgres_dump(backup: Path, workdir: Path) -> Path:
    """plain SQL 덤프를 임시 SQLite 로는 되돌릴 수 없다 — 안내만 한다."""
    raise NotImplementedError(
        "PostgreSQL 덤프는 이 스크립트로 훈련할 수 없습니다. "
        "빈 DB 를 하나 만들고 `psql -d <임시DB> -f <덤프>` 로 되돌린 뒤, "
        "DATABASE_URL 을 그 DB 로 두고 앱을 띄워 확인하세요."
    )


def count_rows(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        counts = {}
        for table in IRREPLACEABLE_TABLES:
            try:
                counts[table] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                counts[table] = -1
        return counts
    finally:
        conn.close()


def run_drill(restored: Path, *, verbose: bool = False) -> tuple[bool, dict]:
    """복원된 DB 로 앱을 **별도 프로세스에서** 띄우고 학습자 경로를 돌려본다.

    별도 프로세스인 이유: DATABASE_URL 은 app.db 임포트 시점에 엔진으로 굳는다.
    이미 임포트된 프로세스 안에서 환경변수만 바꿔도 복원된 DB 를 쓰지 않는다.
    (이 함정은 이전에 백업 검증 테스트에서 한 번 겪었다.)
    """
    script = f'''
import json, sys, time
sys.path.insert(0, {str(BACKEND_DIR)!r})
from fastapi.testclient import TestClient
from app.main import app
from app.db import DATABASE_URL

result = {{"database_url_driver": DATABASE_URL.split("://", 1)[0]}}
with TestClient(app) as client:
    email = f"drill{{int(time.time()*1000)}}@example.com"
    signup = client.post("/api/auth/signup", json={{
        "email": email, "password": "pw12345678", "nickname": "복구훈련",
        "consents": {CONSENTS!r},
    }})
    result["signup_status"] = signup.status_code
    token = signup.json().get("access_token") if signup.status_code == 200 else None
    headers = {{"Authorization": f"Bearer {{token}}"}} if token else {{}}

    cases = client.get("/api/cases", headers=headers)
    result["cases_status"] = cases.status_code
    items = cases.json().get("cases", []) if cases.status_code == 200 else []
    result["case_count"] = len(items)

    if items:
        first = items[0]["case_id"]
        detail = client.get(f"/api/cases/{{first}}", headers=headers)
        result["case_detail_status"] = detail.status_code
        result["case_detail_gradable"] = detail.json().get("gradable") if detail.status_code == 200 else None
    else:
        result["case_detail_status"] = None

    health = client.get("/health")
    result["health_status"] = health.status_code
print("DRILL_RESULT " + json.dumps(result))
'''
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{restored.as_posix()}"
    env["PYTHONIOENCODING"] = "utf-8"
    # 복구 훈련은 개발 환경으로 돌린다 (운영 가드가 임시 DB 를 막지 않도록)
    env.pop("MEDISCAN_ENV", None)

    proc = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        # Windows 기본 인코딩(cp949)으로 읽으면 한국어 로그에서 디코딩이 터진다.
        # 자식 프로세스는 PYTHONIOENCODING=utf-8 로 쓰고 있으므로 여기서도 utf-8 로 읽는다.
        encoding="utf-8",
        errors="replace",
        cwd=str(BACKEND_DIR),
        timeout=300,
    )
    if verbose or proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-15:]
        for line in tail:
            print(f"        {line}")

    if proc.returncode != 0:
        return False, {"error": "앱이 뜨지 않았습니다 (위 로그 참고)"}

    for line in (proc.stdout or "").splitlines():
        if line.startswith("DRILL_RESULT "):
            import json

            return True, json.loads(line[len("DRILL_RESULT ") :])
    return False, {"error": "훈련 결과를 읽지 못했습니다"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="백업을 실제로 되돌려 서비스가 뜨는지 확인한다 (운영 DB 는 건드리지 않는다)"
    )
    parser.add_argument("--backup", required=True, help="백업 파일 (.sqlite 또는 .sql)")
    parser.add_argument("--keep", action="store_true", help="임시 폴더를 지우지 않는다")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    backup = Path(args.backup)
    if not backup.exists():
        print(f"백업 파일이 없습니다: {backup}")
        return 1

    if backup.suffix != ".sqlite":
        try:
            restore_postgres_dump(backup, Path("."))
        except NotImplementedError as exc:
            print(str(exc))
            return 1

    workdir = Path(tempfile.mkdtemp(prefix=f"restore-drill-{uuid.uuid4().hex[:6]}-"))
    print(f"복구 훈련: {backup.name}")
    print(f"작업 폴더: {workdir}  (운영 DB 는 건드리지 않습니다)")
    print()

    ok = True
    try:
        # 1) 복원
        restored = restore_sqlite(backup, workdir)
        ok &= _step("백업을 임시 위치로 복원", restored.exists(), f"{restored.stat().st_size / 1024 / 1024:.2f} MB")

        # 2) 행 수 (복원 직후)
        before = count_rows(restored)
        missing_tables = [t for t, n in before.items() if n == -1]
        ok &= _step(
            "다시 만들 수 없는 데이터가 들어 있다",
            not missing_tables,
            ", ".join(f"{t}={n}" for t, n in before.items()),
        )

        # 3) 앱 기동 + 마이그레이션 (init_db 가 upgrade 를 돌린다)
        booted, result = run_drill(restored, verbose=args.verbose)
        ok &= _step("복원된 DB 로 앱이 뜬다 (마이그레이션 포함)", booted, result.get("error", ""))

        if booted:
            ok &= _step("가입이 된다", result.get("signup_status") == 200, str(result.get("signup_status")))
            ok &= _step("케이스 목록이 나온다", result.get("cases_status") == 200,
                        f"{result.get('case_count')}건")
            if result.get("case_detail_status") is not None:
                ok &= _step("케이스 상세가 나온다", result.get("case_detail_status") == 200,
                            f"gradable={result.get('case_detail_gradable')}")
            else:
                print("  건너뜀  케이스 상세 (백업에 케이스가 없다)")
            ok &= _step("/health 가 응답한다", result.get("health_status") == 200)

        # 4) 훈련 중 새로 만든 계정 때문에 행 수가 늘어난다 — 줄지 않았는지 본다
        after = count_rows(restored)
        shrunk = [t for t in IRREPLACEABLE_TABLES if after.get(t, 0) < before.get(t, 0)]
        ok &= _step("훈련 중 기존 데이터가 사라지지 않았다", not shrunk, ", ".join(shrunk))

    finally:
        if args.keep:
            print(f"\n임시 폴더를 남깁니다: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)

    print()
    if ok:
        print("복구 훈련 통과 — 이 백업으로 서비스를 되돌릴 수 있습니다.")
        print()
        print("※ 실제 복구는 사람이 합니다: 서버를 내리고 파일을 제자리에 되돌립니다.")
        print("  이 스크립트에는 운영 DB 로 되돌리는 경로가 없습니다.")
    else:
        print("복구 훈련 실패 — **이 백업으로는 서비스를 되돌리지 못합니다.**")
        print("  백업 파일이나 마이그레이션 상태를 확인하세요.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
