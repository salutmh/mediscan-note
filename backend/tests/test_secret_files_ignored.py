"""
비밀값이 담기는 파일이 실수로 커밋되지 않는지 확인한다.

==========================================================================
**한 번 push 하면 되돌릴 수 없다.**
==========================================================================
이 저장소는 Public 이다. Supabase DB 비밀번호를 `backend/.env.staging` 에 적었는데
그 파일이 무시 목록에 없으면 `git add -A` 한 번에 그대로 올라간다.
`git rm --cached` 로 지워도 이력에는 남는다 — 비밀번호를 새로 발급받는 수밖에 없다.

실제로 이 저장소는 그 상태였다. `.gitignore` 에 `.env` 만 있었고,
`.env.staging` / `.env.production` / `.env.supabase` 는 전부 커밋 가능했다.

또 한 가지 함정: `!.env.production` 처럼 **경로 없이 되살리면**
`frontend/.env.production`(공개 설정) 뿐 아니라 `backend/.env.production`(비밀값)
까지 함께 되살아난다. 그래서 되살릴 때는 반드시 `/frontend/` 를 붙인다.

여기서는 파일을 만들지 않고 `git check-ignore` 로 규칙만 묻는다.
"""
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# 비밀값이 들어갈 수 있는 경로 — **반드시 무시돼야 한다**
MUST_BE_IGNORED = [
    "backend/.env",
    "backend/.env.local",
    "backend/.env.staging",
    "backend/.env.production",
    "backend/.env.supabase",
    "backend/.env.staging.local",
    ".env",
    ".env.production",
    ".supabase-secrets",
    ".supabase-secrets.json",
    "supabase/.temp/project-ref",
    "supabase/.branches/x",
    "server.key",
    "client.pem",
    "gcp-service-account.json",
    "my-credentials.json",
]

# 공개 설정·예시 — **커밋돼야 한다** (막아 버리면 새 팀원이 설정을 못 받는다)
MUST_BE_COMMITTABLE = [
    "backend/.env.example",
    "frontend/.env.example",
    "frontend/.env.development",
    "frontend/.env.production",
]


def _is_ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", path],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if result.returncode not in (0, 1):
        pytest.skip(f"git check-ignore 를 쓸 수 없다: {result.returncode}")
    return result.returncode == 0


@pytest.mark.parametrize("path", MUST_BE_IGNORED)
def test_secret_paths_are_ignored(path):
    assert _is_ignored(path), (
        f"{path} 가 무시되지 않는다 — 여기에 비밀번호를 적으면 커밋된다. "
        ".gitignore 를 확인하라."
    )


@pytest.mark.parametrize("path", MUST_BE_COMMITTABLE)
def test_public_config_stays_committable(path):
    assert not _is_ignored(path), (
        f"{path} 는 비밀값이 아니라 공개 설정이다. 무시하면 안 된다."
    )


def test_no_env_file_with_secrets_is_currently_tracked():
    """이미 추적 중인 파일은 `.gitignore` 로 막을 수 없다 — 지금 상태를 확인한다."""
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True
    )
    if tracked.returncode != 0:
        pytest.skip("git ls-files 를 쓸 수 없다")

    env_files = [
        line for line in tracked.stdout.splitlines() if "/.env" in line or line.startswith(".env")
    ]
    allowed = set(MUST_BE_COMMITTABLE)
    unexpected = [f for f in env_files if f not in allowed]
    assert not unexpected, (
        f"비밀값이 들어갈 수 있는 파일이 이미 추적되고 있다: {unexpected}. "
        ".gitignore 만으로는 막히지 않는다."
    )
