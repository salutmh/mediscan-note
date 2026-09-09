"""
스테이징 DB 비밀번호를 **로컬 secret** 으로 다룬다.

==========================================================================
**비밀번호를 화면에 찍지 않는다.**
==========================================================================
터미널 출력은 스크롤백에 남고, CI 로그에 남고, 스크린샷에 남는다.
그래서 이 도구는 비밀번호를 만들고 보관하고 **자식 프로세스에 넘겨줄 뿐**,
사람이 읽을 수 있는 형태로 출력하지 않는다.

확인이 필요할 때는 값 대신 **지문(fingerprint)** 을 쓴다 —
sha256 앞 12자만 보여주므로, 두 곳의 비밀번호가 같은지는 알 수 있어도
비밀번호 자체는 알 수 없다.

연결 문자열을 우리가 조립하지 않는다
------------------------------------
`db.<ref>.supabase.co` 같은 host 를 코드로 만들어내면, Supabase 가 형식을
바꿨을 때 **조용히 틀린 곳에 붙는다.** 대신 Dashboard 의 Connect 나 CLI 가 준
문자열을 **그대로** 저장한다. 그 문자열에는 보통 `[YOUR-PASSWORD]` 자리표시자가
들어 있고, 우리는 그 자리에만 비밀번호를 끼워 넣는다.

쓰는 법
-------
    python -m scripts.staging_secret init          # 비밀번호 생성 (한 번만)
    python -m scripts.staging_secret status        # 지문·상태 확인 (값은 안 나온다)
    python -m scripts.staging_secret set-url --mode direct --url "<Connect 에서 복사한 URI>"
    python -m scripts.staging_secret run --mode direct -- alembic upgrade head
    python -m scripts.staging_secret run -- npx supabase projects create ... --db-password @SECRET

`run` 이 하는 일:
  * `DATABASE_URL` 을 자식 프로세스 **환경변수로만** 넣는다 (`--mode` 를 준 경우)
  * argv 의 `@SECRET` 토큰을 비밀번호로 바꾼다
  * 자식 프로세스의 출력에 비밀번호가 섞여 나오면 `***` 로 가린다

한계 (알고 쓰자)
----------------
  * `@SECRET` 로 넘긴 값은 잠깐이지만 **프로세스 목록에 보인다.** 같은 PC 를
    쓰는 다른 사용자가 있으면 피하는 게 좋다. 환경변수 방식(`--mode`)에는 해당 없다.
  * 파일 권한은 POSIX 기준으로만 조인다. Windows 에서는 NTFS ACL 이 따로다.
"""
import argparse
import hashlib
import json
import os
import secrets
import shutil
import string
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[2]
SECRET_PATH = REPO_ROOT / ".supabase-secrets.json"

# URL 에서 인코딩이 필요 없는 문자만 쓴다.
# @ : / # ? 가 섞이면 연결 문자열이 엉뚱하게 파싱된다 —
# 그러면 "비밀번호가 틀렸다" 가 아니라 "host 를 못 찾겠다" 같은 엉뚱한 오류가 난다.
ALPHABET = string.ascii_letters + string.digits + "-._~"
PASSWORD_LENGTH = 40

# Connect 화면이 주는 자리표시자들
PLACEHOLDERS = ("[YOUR-PASSWORD]", "[YOUR_PASSWORD]", "{password}", "YOUR-PASSWORD")

SECRET_TOKEN = "@SECRET"
MODES = ("direct", "session_pooler", "transaction_pooler")


# ------------------------------------------------------------------ 저장소
def _load() -> dict:
    if not SECRET_PATH.exists():
        return {}
    try:
        return json.loads(SECRET_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        # **덮어쓰지 않는다.** 깨진 파일 안에 유일한 비밀번호가 있을 수 있다.
        raise SystemExit(
            "{} 을 읽을 수 없습니다 ({}). "
            "직접 열어 확인하세요 — 자동으로 덮어쓰지 않습니다.".format(SECRET_PATH.name, exc)
        )


def _save(data: dict) -> None:
    SECRET_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    try:
        os.chmod(SECRET_PATH, 0o600)
    except OSError:
        pass  # Windows 에서는 의미가 제한적이다


def fingerprint(password: str) -> str:
    return "sha256:" + hashlib.sha256(password.encode("utf-8")).hexdigest()[:12]


def _is_gitignored(path: Path) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(path)], cwd=str(REPO_ROOT), capture_output=True
    )
    return result.returncode == 0


def _require_gitignored() -> None:
    """**비밀번호를 만들기 전에** 커밋될 수 없는 자리인지 확인한다."""
    if not _is_gitignored(SECRET_PATH):
        raise SystemExit(
            "중단합니다: {} 이 .gitignore 에 걸리지 않습니다.\n"
            "이대로 비밀번호를 만들면 `git add -A` 한 번에 공개 저장소로 올라갑니다.\n"
            ".gitignore 에 `.supabase-secrets*` 를 넣고 다시 실행하세요.".format(SECRET_PATH.name)
        )


def _db_connection_module():
    """백엔드 패키지를 import 할 수 있게 경로를 맞춘다."""
    backend = str(REPO_ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from app import db_connection

    return db_connection


# ------------------------------------------------------------------ 명령들
def cmd_init(args) -> int:
    _require_gitignored()
    data = _load()
    if data.get("db_password") and not args.force:
        print("이미 비밀번호가 있습니다. 새로 만들려면 --force (기존 것은 못 되살립니다).")
        print("  지문: {}".format(data.get("fingerprint")))
        return 1

    password = "".join(secrets.choice(ALPHABET) for _ in range(PASSWORD_LENGTH))
    data.update(
        {
            "version": 1,
            "db_password": password,
            "fingerprint": fingerprint(password),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "note": "이 파일을 커밋하지 마세요. 비밀번호는 여기에만 있습니다.",
        }
    )
    data.setdefault("connection_urls", {})
    _save(data)

    print("비밀번호를 만들었습니다 ({}자). **값은 출력하지 않습니다.**".format(PASSWORD_LENGTH))
    print("  파일: {}".format(SECRET_PATH))
    print("  지문: {}".format(data["fingerprint"]))
    print("  Supabase 에 넘길 때는 `staging_secret run ... @SECRET` 을 쓰세요.")
    return 0


def cmd_status(args) -> int:
    ignored = _is_gitignored(SECRET_PATH)
    print("파일:        {}".format(SECRET_PATH))
    print("존재:        {}".format("예" if SECRET_PATH.exists() else "아니오"))
    print("gitignore:   {}".format(
        "걸림 (안전)" if ignored else "!! 안 걸림 — 커밋될 수 있습니다"))
    if not SECRET_PATH.exists():
        print("\n아직 없습니다. `python -m scripts.staging_secret init` 으로 만드세요.")
        return 0 if ignored else 1

    data = _load()
    print("생성:        {}".format(data.get("created_at", "?")))
    print("지문:        {}".format(data.get("fingerprint", "?")))
    print("길이:        {}자".format(len(data.get("db_password", ""))))
    print("project_ref: {}".format("저장됨" if data.get("project_ref") else "아직 없음"))
    urls = data.get("connection_urls") or {}
    print("연결 문자열:")
    for mode in MODES:
        print("  {:<20} {}".format(mode, "저장됨" if urls.get(mode) else "-"))
    if not urls:
        print("    (Supabase 의 Connect 에서 받아 `set-url` 로 넣으세요)")
    return 0 if ignored else 1


def cmd_set_url(args) -> int:
    _require_gitignored()
    data = _load()
    if not data.get("db_password"):
        raise SystemExit("먼저 `init` 으로 비밀번호를 만드세요.")

    url = args.url.strip()
    if data["db_password"] in url:
        # 이미 비밀번호를 끼워 넣은 문자열을 붙였다 — 자리표시자로 되돌려 저장한다
        url = url.replace(data["db_password"], PLACEHOLDERS[0])
        print("문자열에 비밀번호가 들어 있어 자리표시자로 바꿔 저장합니다.")
    if not any(p in url for p in PLACEHOLDERS):
        raise SystemExit(
            "자리표시자가 없습니다. Connect 에서 복사한 문자열에는 "
            "보통 {} 가 들어 있습니다. 그대로 붙여 넣으세요.".format(PLACEHOLDERS[0])
        )

    data.setdefault("connection_urls", {})[args.mode] = url
    if args.ref:
        data["project_ref"] = args.ref
    _save(data)
    print("{} 연결 문자열을 저장했습니다 (비밀번호는 자리표시자로 보관).".format(args.mode))

    # 저장한 문자열이 정말 그 모드인지 확인한다 — 모드를 착각한 채로 저장하면
    # "왜 마이그레이션이 깨지지" 를 한참 헤맨다
    resolved = _db_connection_module().parse(_substitute(url, "x" * 8))["mode"]
    if resolved != args.mode:
        print("  주의: 이 문자열은 `{}` 로 인식됩니다 (`{}` 로 저장하셨습니다).".format(
            resolved, args.mode))
        print("  host / 사용자명 / 포트를 Connect 화면의 값과 다시 대조하세요.")
    return 0


def _substitute(url: str, password: str) -> str:
    for placeholder in PLACEHOLDERS:
        url = url.replace(placeholder, password)
    return url


def _database_url(data: dict, mode: str) -> str:
    urls = data.get("connection_urls") or {}
    if mode not in urls:
        raise SystemExit(
            "`{mode}` 연결 문자열이 없습니다. "
            "`set-url --mode {mode} --url \"...\"` 으로 먼저 넣으세요.".format(mode=mode)
        )
    url = _substitute(urls[mode], data["db_password"])
    # SQLAlchemy 는 드라이버 접미사를 원한다. Connect 화면은 `postgresql://` 로 준다.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def cmd_run(args) -> int:
    data = _load()
    password = data.get("db_password")
    if not password:
        raise SystemExit("비밀번호가 없습니다. 먼저 `init` 을 실행하세요.")

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("실행할 명령이 없습니다. `run -- <명령>` 형태로 쓰세요.")

    env = os.environ.copy()
    if args.mode:
        env["DATABASE_URL"] = _database_url(data, args.mode)
        print("[staging_secret] DATABASE_URL 을 {} 로 설정했습니다 (값은 감춥니다)".format(args.mode))

    substituted = [password if part == SECRET_TOKEN else part for part in command]
    # Windows 에서 `npx` 는 `npx.cmd` 다 — 이름만 넘기면 subprocess 가 찾지 못한다.
    resolved = shutil.which(substituted[0])
    if resolved:
        substituted[0] = resolved
    if any(part == SECRET_TOKEN for part in command):
        print("[staging_secret] 명령의 @SECRET 을 비밀번호로 바꿉니다 "
              "(프로세스 목록에는 잠깐 보입니다)")

    print("[staging_secret] 실행: {}".format(
        " ".join("***" if p == password else p for p in substituted)))

    proc = subprocess.run(
        substituted, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    # 자식이 비밀번호를 되뱉을 수 있다 (오류 메시지에 연결 문자열을 통째로 넣는 도구가 많다)
    sys.stdout.write(_redact(proc.stdout, password))
    sys.stderr.write(_redact(proc.stderr, password))
    return proc.returncode


def _redact(text: str, password: str) -> str:
    if not text:
        return ""
    return text.replace(password, "***").replace(quote(password, safe=""), "***")


def cmd_check(args) -> int:
    """저장된 연결 문자열이 어떤 모드로 인식되는지, 용도에 맞는지 본다."""
    data = _load()
    urls = data.get("connection_urls") or {}
    if not urls:
        print("저장된 연결 문자열이 없습니다.")
        return 1

    db_connection = _db_connection_module()
    fake = "x" * 8  # 판별에는 실제 비밀번호가 필요 없다
    exit_code = 0
    for mode, template in urls.items():
        url = _substitute(template, fake)
        described = db_connection.describe(url)
        print("\n[{}]".format(mode))
        print("  인식: {}".format(described["label"]))
        print("  host: {}  port: {}  sslmode: {}".format(
            described["host_suffix"], described["port"], described["sslmode"] or "없음"))
        for purpose in ("migration", "backup", "runtime"):
            for note in db_connection.advisories(url, purpose=purpose):
                print("  - ({}) {}".format(purpose, note))
        if described["mode"] == db_connection.UNKNOWN:
            exit_code = 1
    return exit_code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="스테이징 DB 비밀번호를 로컬 secret 으로 다룬다")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="강한 DB 비밀번호를 만든다 (출력하지 않음)")
    p_init.add_argument("--force", action="store_true", help="기존 비밀번호를 버리고 새로 만든다")
    p_init.set_defaults(func=cmd_init)

    sub.add_parser("status", help="지문과 상태만 본다").set_defaults(func=cmd_status)

    p_url = sub.add_parser("set-url", help="Connect 에서 받은 연결 문자열을 저장한다")
    p_url.add_argument("--mode", required=True, choices=MODES)
    p_url.add_argument("--url", required=True)
    p_url.add_argument("--ref", help="project ref (선택)")
    p_url.set_defaults(func=cmd_set_url)

    p_run = sub.add_parser("run", help="비밀번호를 노출하지 않고 명령을 실행한다")
    p_run.add_argument("--mode", choices=MODES, help="DATABASE_URL 을 이 모드로 넣는다")
    p_run.add_argument("command", nargs=argparse.REMAINDER)
    p_run.set_defaults(func=cmd_run)

    sub.add_parser("check", help="저장된 연결 문자열의 모드와 권고사항").set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
