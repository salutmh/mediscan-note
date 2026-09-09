"""
Supabase 스테이징 프로젝트 준비 상태를 점검한다.

==========================================================================
**access token 을 출력하지 않는다.**
==========================================================================
CLI 는 로그인 토큰을 `~/.supabase` 아래에 보관한다. 이 스크립트는 토큰이
있는지 없는지만 보고, 값은 읽지도 찍지도 않는다. organization id 와
project ref 는 비밀이 아니지만(연결 문자열에 그대로 들어간다), 그래도
필요한 만큼만 보여준다.

무엇을 확인하나
---------------
  1. CLI 를 실행할 수 있는가 (전역 설치 / npx)
  2. 로그인돼 있는가          — **안 돼 있으면 여기서 멈춘다. 대신 로그인할 수 없다.**
  3. organization 목록
  4. `mediscan-note-staging` 프로젝트가 이미 있는가 — **있으면 새로 만들지 않는다**
  5. 로컬 secret 준비 상태 (DB 비밀번호, 연결 문자열)

사용법
------
    cd backend
    python -m scripts.supabase_staging preflight
    python -m scripts.supabase_staging create --org-id <id>   # 로그인 후에만
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts import staging_secret  # noqa: E402

PROJECT_NAME = "mediscan-note-staging"
REGION = "ap-northeast-2"  # 서울
CLI_PACKAGE = "supabase@latest"

# CLI 가 "로그인 안 됨" 을 알리는 방식. 문구가 바뀔 수 있어 여러 신호를 함께 본다.
NOT_LOGGED_IN_SIGNS = (
    "AuthRequiredError",
    "Access token not provided",
    "supabase login",
)

LOGIN_INSTRUCTIONS = """
────────────────────────────────────────────────────────────────────────
로그인이 필요합니다. **이 부분만 직접 해 주세요.**

    npx supabase@latest login

  브라우저가 열리고 Supabase 계정으로 인증합니다.
  (계정이 없으면 먼저 supabase.com 에서 가입해야 합니다.)

  터미널로 돌아온 뒤 다시 실행하세요:

    cd backend
    python -m scripts.supabase_staging preflight

토큰 값은 저에게 보여주지 마세요 — CLI 가 알아서 보관합니다.
────────────────────────────────────────────────────────────────────────
"""


# ------------------------------------------------------------------- CLI 찾기
def cli_command() -> list[str] | None:
    """CLI 를 실행할 argv 앞부분. 없으면 None.

    Supabase 는 전역 npm 설치를 지원하지 않는다 — `npx` 로 부르는 게 공식 경로다.
    """
    found = shutil.which("supabase")
    if found:
        return [found]
    # **`shutil.which` 가 준 경로를 그대로 쓴다.** Windows 에서 `npx` 는 실제로
    # `npx.cmd` 라서, 이름만 넘기면 subprocess 가 "파일을 찾을 수 없습니다" 로 죽는다.
    npx = shutil.which("npx")
    if npx:
        return [npx, "--yes", CLI_PACKAGE]
    return None


def _run(argv: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout,
    )


def _looks_logged_out(proc: subprocess.CompletedProcess) -> bool:
    blob = (proc.stdout or "") + (proc.stderr or "")
    return any(sign in blob for sign in NOT_LOGGED_IN_SIGNS)


# --------------------------------------------------------------------- 점검
def preflight(args) -> int:
    cli = cli_command()
    print("1. Supabase CLI")
    if not cli:
        print("   [없음] supabase 도 npx 도 찾을 수 없습니다.")
        print("   Node.js 를 설치하면 npx 로 쓸 수 있습니다: https://nodejs.org")
        return 2
    version = _run(cli + ["--version"])
    print("   [있음] {}  (버전 {})".format(
        " ".join(cli), (version.stdout or version.stderr).strip() or "?"))

    print("\n2. 로그인 상태")
    if os.getenv("SUPABASE_ACCESS_TOKEN"):
        # 값은 읽지 않는다 — 있다는 사실만 본다
        print("   SUPABASE_ACCESS_TOKEN 이 설정돼 있습니다 (값은 확인하지 않습니다)")
    projects = _run(cli + ["projects", "list", "--output", "json"])
    if _looks_logged_out(projects):
        print("   [로그인 안 됨]")
        print(LOGIN_INSTRUCTIONS)
        _report_local_secret()
        return 1
    if projects.returncode != 0:
        print("   [확인 실패] CLI 가 오류를 냈습니다:")
        print("   " + (projects.stderr or projects.stdout).strip().splitlines()[0][:200])
        return 2
    print("   [로그인됨]")

    print("\n3. Organization")
    orgs = _run(cli + ["orgs", "list", "--output", "json"])
    org_ids = []
    if orgs.returncode == 0:
        for org in _parse_json_list(orgs.stdout):
            org_id = org.get("id") or org.get("slug") or "?"
            org_ids.append(org_id)
            print("   - {}  (id: {})".format(org.get("name", "?"), org_id))
    if not org_ids:
        print("   organization 을 찾지 못했습니다. Supabase 대시보드에서 확인하세요.")

    print("\n4. `{}` 프로젝트".format(PROJECT_NAME))
    existing = _find_project(_parse_json_list(projects.stdout))
    if existing:
        # **있으면 새로 만들지 않는다.** 같은 이름의 프로젝트를 둘 만들면
        # 어느 쪽에 마이그레이션을 돌렸는지 헷갈린다.
        print("   [이미 있음] ref={}  region={}  status={}".format(
            existing.get("id", "?"), existing.get("region", "?"),
            existing.get("status", "?")))
        print("   새로 만들지 않습니다. 이 프로젝트를 씁니다.")
    else:
        print("   [없음] 만들어야 합니다.")
        print("   python -m scripts.supabase_staging create --org-id <위 목록의 id>")

    print()
    _report_local_secret()
    return 0


def _parse_json_list(text: str) -> list[dict]:
    try:
        data = json.loads(text or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _find_project(projects: list[dict]) -> dict | None:
    for project in projects:
        if project.get("name") == PROJECT_NAME:
            return project
    return None


def _report_local_secret() -> None:
    print("5. 로컬 secret")
    path = staging_secret.SECRET_PATH
    if not path.exists():
        print("   [없음] python -m scripts.staging_secret init 으로 만드세요.")
        return
    data = staging_secret._load()
    safe = staging_secret._is_gitignored(path)
    print("   DB 비밀번호: 있음 (지문 {})".format(data.get("fingerprint", "?")))
    print("   gitignore:   {}".format("걸림 (안전)" if safe else "!! 안 걸림"))
    urls = data.get("connection_urls") or {}
    print("   연결 문자열: {}".format(", ".join(urls) if urls else "아직 없음"))


# --------------------------------------------------------------------- 생성
def create(args) -> int:
    """프로젝트를 만든다. **비밀번호는 secret 파일에서 꺼내 넘긴다.**"""
    cli = cli_command()
    if not cli:
        raise SystemExit("Supabase CLI 를 찾을 수 없습니다.")
    if not staging_secret.SECRET_PATH.exists():
        raise SystemExit("먼저 `python -m scripts.staging_secret init` 을 실행하세요.")

    projects = _run(cli + ["projects", "list", "--output", "json"])
    if _looks_logged_out(projects):
        print(LOGIN_INSTRUCTIONS)
        return 1
    existing = _find_project(_parse_json_list(projects.stdout))
    if existing:
        print("`{}` 가 이미 있습니다 (ref={}). 새로 만들지 않습니다.".format(
            PROJECT_NAME, existing.get("id", "?")))
        return 0

    argv = cli + [
        "projects", "create", PROJECT_NAME,
        "--org-id", args.org_id,
        "--region", args.region,
        "--db-password", staging_secret.SECRET_TOKEN,  # run 이 바꿔 넣는다
    ]
    if args.size:
        argv += ["--size", args.size]
    # staging_secret.run 을 거쳐야 비밀번호가 화면에 찍히지 않는다
    return staging_secret.main(["run", "--"] + argv)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Supabase 스테이징 준비 점검")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("preflight", help="CLI·로그인·조직·프로젝트·secret 상태").set_defaults(
        func=preflight)

    p_create = sub.add_parser("create", help="스테이징 프로젝트를 만든다")
    p_create.add_argument("--org-id", required=True)
    p_create.add_argument("--region", default=REGION, help="기본 {} (서울)".format(REGION))
    p_create.add_argument("--size", help="인스턴스 크기 (유료 조직에서만 의미 있음)")
    p_create.set_defaults(func=create)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
