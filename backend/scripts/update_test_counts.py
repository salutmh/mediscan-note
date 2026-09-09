"""
문서에 적힌 테스트 수를 **실제로 세어** 갱신한다.

==========================================================================
사람이 매번 손으로 고치면 결국 어긋난다.
==========================================================================
실제로 그랬다 — 백엔드 수치가 문서 네 곳에 흩어져 있었고, 한 곳을 고치면
나머지가 남아 `test_documentation_drift` 가 매번 걸렸다.

**세는 것과 고치는 것을 둘 다 여기서 한다.**
개수는 문서에서 읽지 않고 `pytest --collect-only` / `vitest --run` 으로 직접 센다.
"헤아린 값"과 "적어둔 값"이 갈라질 여지를 만들지 않기 위해서다.

사용법
------
    cd backend
    python -m scripts.update_test_counts            # 세어서 보여주기만
    python -m scripts.update_test_counts --write    # 문서까지 고치기

종료코드: `--write` 없이 돌렸을 때 어긋난 곳이 있으면 1.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = REPO_ROOT / "frontend"

# 수치를 적어 두는 문서들. **여기 없는 문서에는 숫자를 적지 않는다.**
DOCS = [
    REPO_ROOT / "CLAUDE.md",
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "CLAUDE_HANDOFF.md",
    REPO_ROOT / "docs" / "RELEASE_READINESS.md",
]

# `**830개**` / `**830 passed**` 앞에 "백엔드"·"backend" 가 오는 형태
BACKEND_PATTERN = re.compile(r"((?:백엔드|backend)[^\n]{0,30}?\*\*)(\d{3,5})((?:개| passed))")
ANSI = re.compile("\x1b\[[0-9;]*m")

FRONTEND_PATTERN = re.compile(r"((?:프론트|frontend)[^\n]{0,30}?\*\*)(\d{2,5})((?:개| passed))")


def count_backend() -> int:
    """pytest 가 실제로 수집하는 개수."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=str(BACKEND_DIR), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    match = re.search(r"(\d+) tests? collected", result.stdout)
    if not match:
        raise SystemExit("백엔드 테스트 수를 셀 수 없습니다:\n" + result.stdout[-500:])
    return int(match.group(1))


def count_frontend() -> int | None:
    """vitest 가 실제로 도는 개수. 실행할 수 없으면 None (**추측하지 않는다**)."""
    npx = "npx.cmd" if sys.platform == "win32" else "npx"
    result = subprocess.run(
        [npx, "vitest", "run"],
        cwd=str(FRONTEND_DIR), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    # **ANSI 색 코드를 먼저 떼어낸다.** vitest 출력은 "Tests" 와 숫자 사이에
    # 이스케이프 시퀀스가 끼어 있어, 그냥 정규식으로 찾으면 항상 못 찾는다
    # (그러면 "셀 수 없음"으로 조용히 넘어가 프론트 수치가 영영 안 고쳐진다).
    blob = ANSI.sub("", result.stdout + result.stderr)
    match = re.search(r"Tests\s+(\d+) passed", blob)
    if match:
        return int(match.group(1))
    match = re.search(r'"numTotalTests":(\d+)', blob)
    return int(match.group(1)) if match else None


def apply(text: str, backend: int, frontend: int | None) -> tuple[str, int]:
    changed = 0

    def replace_backend(m):
        nonlocal changed
        if int(m.group(2)) != backend:
            changed += 1
        return f"{m.group(1)}{backend}{m.group(3)}"

    text = BACKEND_PATTERN.sub(replace_backend, text)

    if frontend is not None:
        def replace_frontend(m):
            nonlocal changed
            if int(m.group(2)) != frontend:
                changed += 1
            return f"{m.group(1)}{frontend}{m.group(3)}"

        text = FRONTEND_PATTERN.sub(replace_frontend, text)
    return text, changed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="문서의 테스트 수를 실제와 맞춘다")
    parser.add_argument("--write", action="store_true", help="문서를 실제로 고친다")
    args = parser.parse_args(argv)

    backend = count_backend()
    frontend = count_frontend()
    print(f"실제 개수 — 백엔드 {backend} / 프론트 {frontend if frontend is not None else '셀 수 없음'}")
    if frontend is None:
        print("  (프론트는 건드리지 않는다 — 셀 수 없는 값을 적어 두면 그게 곧 드리프트다)")
    print()

    stale = 0
    for path in DOCS:
        if not path.exists():
            continue
        original = path.read_text(encoding="utf-8")
        updated, changed = apply(original, backend, frontend)
        if not changed:
            print(f"  맞음   {path.relative_to(REPO_ROOT)}")
            continue
        stale += changed
        if args.write:
            path.write_text(updated, encoding="utf-8", newline="\n")
            print(f"  고침   {path.relative_to(REPO_ROOT)} ({changed}곳)")
        else:
            print(f"  어긋남 {path.relative_to(REPO_ROOT)} ({changed}곳)")

    print()
    if not stale:
        print("문서와 실제가 일치합니다.")
        return 0
    if args.write:
        print(f"{stale}곳을 고쳤습니다.")
        return 0
    print(f"{stale}곳이 어긋났습니다. --write 로 고치세요.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
