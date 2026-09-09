"""
문서 표류(documentation drift) 자동 점검.

**왜 필요한가**
이 프로젝트는 문서가 많고 서로를 참조한다. 코드를 고치면서 문서를 잊으면 다음 사람이
**없는 스크립트를 실행하고 없는 환경변수를 설정한다.** 실제로 겪은 것들:

  - `INVALID_CREDENTIALS` 가 에러 코드 표에서 빠져 있었다 (test_error_contract.py 가 잡는다)
  - CLAUDE.md 의 테스트 수가 417 인데 실제는 563 이었다
  - 시작 순서 7번이 `review_bundle.md` 를 가리켰는데 런북은 `docs/DEPLOYMENT.md` 였다
  - `scoring_config.thresholds()` 주석이 "/health 에 노출한다"고 했지만 실제로는 아니었다

여기서 잡는 것은 **기계로 확실히 알 수 있는 표류**뿐이다:
문서가 가리키는 파일·스크립트·환경변수가 실제로 있는가.

문장의 내용이 맞는지는 판단하지 않는다 — 그건 사람이 읽어야 한다.
"""
import re
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
DOCS_DIR = REPO_DIR / "docs"

DOC_FILES = sorted(
    [
        *DOCS_DIR.glob("*.md"),
        REPO_DIR / "CLAUDE.md",
        REPO_DIR / "README.md",
        BACKEND_DIR / "README.md",
        REPO_DIR / "frontend" / "README.md",
        REPO_DIR / "tools" / "browser-verify" / "README.md",
    ]
)

# 문서에 나오지만 저장소 파일이 아닌 것 (외부 도구·예시 경로 등)
IGNORED_PATHS = {
    "package.json",       # 여러 곳에 있어 특정할 수 없다
    "requirements.txt",   # backend/ 안에 있지만 문서에서는 상대경로로 쓴다
    "alembic.ini",
    "manifest.json",      # 사용자가 만드는 파일
    "review.png",         # 검수 산출물 (data/ = gitignore)
    "inference.py",       # models/<부위>/ 아래 여러 개
    ".env",
    ".env.example",
}


def _existing_docs():
    return [p for p in DOC_FILES if p.exists()]


def test_doc_files_exist():
    """점검 대상이 비어 있으면 이 파일 전체가 무의미해진다."""
    found = _existing_docs()
    assert len(found) >= 8, f"문서를 제대로 찾지 못했다: {[p.name for p in found]}"


# --------------------------------------------------- 스크립트 참조
def _referenced_scripts() -> dict[str, list[str]]:
    """문서가 `python -m scripts.<이름>` 으로 부르는 스크립트."""
    pattern = re.compile(r"python -m scripts\.([a-z_][a-z0-9_]*)")
    found: dict[str, list[str]] = {}
    for path in _existing_docs():
        for name in pattern.findall(path.read_text(encoding="utf-8")):
            found.setdefault(name, []).append(path.name)
    return found


def test_documents_reference_scripts():
    referenced = _referenced_scripts()
    assert len(referenced) >= 8, f"스크립트 참조를 제대로 수집하지 못했다: {referenced}"
    assert "verify_cases" in referenced


def test_every_referenced_script_exists():
    """**문서가 없는 스크립트를 실행하라고 하면 안 된다.**"""
    scripts_dir = BACKEND_DIR / "scripts"
    missing = {
        name: docs
        for name, docs in _referenced_scripts().items()
        if not (scripts_dir / f"{name}.py").exists()
    }
    assert not missing, (
        "문서가 가리키는데 없는 스크립트: "
        + ", ".join(f"scripts/{n}.py ({', '.join(d)})" for n, d in sorted(missing.items()))
    )


# --------------------------------------------------- 브라우저 검증 스크립트
def test_every_referenced_browser_script_exists():
    pattern = re.compile(r"tools/browser-verify/([a-z0-9-]+\.mjs)")
    tools_dir = REPO_DIR / "tools" / "browser-verify"
    missing = {}
    for path in _existing_docs():
        for name in pattern.findall(path.read_text(encoding="utf-8")):
            if not (tools_dir / name).exists():
                missing.setdefault(name, []).append(path.name)
    assert not missing, f"문서가 가리키는데 없는 브라우저 스크립트: {missing}"


# --------------------------------------------------- 환경변수 참조
def _documented_env_vars() -> dict[str, list[str]]:
    pattern = re.compile(r"\b(MEDISCAN_[A-Z0-9_]+)\b")
    found: dict[str, list[str]] = {}
    for path in _existing_docs():
        for name in pattern.findall(path.read_text(encoding="utf-8")):
            found.setdefault(name, []).append(path.name)
    return found


def _env_vars_in_code() -> set[str]:
    pattern = re.compile(r"\b(MEDISCAN_[A-Z0-9_]+)\b")
    names: set[str] = set()
    # backend 만 보면 부족하다 — models/<부위>/inference.py 도 환경변수를 읽는다.
    # (처음에 models/ 를 빼먹어 MEDISCAN_VS_SEG_ROOT 가 "문서에만 있다"고 오탐했다.
    #  수집기가 좁으면 드리프트 검사가 거짓 경보를 낸다.)
    sources = [
        *(BACKEND_DIR / "app").rglob("*.py"),
        *(BACKEND_DIR / "scripts").glob("*.py"),
        *(REPO_DIR / "models").rglob("*.py"),
    ]
    for path in sources:
        names.update(pattern.findall(path.read_text(encoding="utf-8")))
    # 프론트도 본다 (VITE_ 는 별개지만 MEDISCAN_ 이 섞일 수 있다)
    frontend_src = REPO_DIR / "frontend" / "src"
    if frontend_src.exists():
        for path in frontend_src.rglob("*.js"):
            names.update(pattern.findall(path.read_text(encoding="utf-8")))
    for path in (REPO_DIR / "tools" / "browser-verify").glob("*.mjs"):
        names.update(pattern.findall(path.read_text(encoding="utf-8")))
    return names


def test_env_var_collectors_are_not_empty():
    assert len(_documented_env_vars()) >= 8
    assert len(_env_vars_in_code()) >= 8


def test_documented_env_vars_exist_in_code():
    """**문서가 없는 환경변수를 설정하라고 하면 안 된다.**

    다음 사람이 그 값을 설정하고 "왜 안 되지" 하며 시간을 쓴다.
    """
    in_code = _env_vars_in_code()
    stale = {
        name: docs for name, docs in _documented_env_vars().items() if name not in in_code
    }
    assert not stale, (
        "문서에는 있는데 코드가 읽지 않는 환경변수: "
        + ", ".join(f"{n} ({', '.join(sorted(set(d)))})" for n, d in sorted(stale.items()))
    )


# --------------------------------------------------- 문서 간 상호 참조
def test_referenced_documents_exist():
    """문서가 가리키는 다른 문서가 실제로 있는가."""
    pattern = re.compile(r"`?(docs/[A-Za-z0-9_\-]+\.md)`?")
    missing = {}
    for path in _existing_docs():
        for target in pattern.findall(path.read_text(encoding="utf-8")):
            if not (REPO_DIR / target).exists():
                missing.setdefault(target, []).append(path.name)
    assert not missing, f"문서가 가리키는데 없는 문서: {missing}"


# --------------------------------------------------- 테스트 수치
def _stated_test_counts() -> dict[str, list[tuple[str, int]]]:
    """문서가 적어둔 '백엔드 N개' 같은 수치."""
    pattern = re.compile(r"(?:백엔드|backend)[^\n]{0,30}?\*\*(\d{3,4})(?:개| passed)")
    found: dict[str, list[tuple[str, int]]] = {}
    for path in _existing_docs():
        for value in pattern.findall(path.read_text(encoding="utf-8")):
            found.setdefault(path.name, []).append(("backend", int(value)))
    return found


# 전체 스위트를 돌 때만 실제 개수를 알 수 있다. 파일 하나만 돌리면
# 수집된 개수가 전체가 아니라 비교가 무의미하다.
FULL_SUITE_MIN = 200


def test_stated_backend_test_counts_are_close_to_reality(request):
    """문서의 테스트 수가 실제와 크게 어긋나지 않는가.

    **정확히 같기를 요구하지 않는다** — 테스트를 추가할 때마다 문서를 고치게 하면
    귀찮아서 아무도 안 지킨다. 크게 벌어졌을 때만 알린다 (10% 또는 30개).

    파일 하나만 돌린 경우에는 건너뛴다 — 그때 수집된 개수는 전체가 아니다.
    """
    actual = len(request.session.items)
    if actual < FULL_SUITE_MIN:
        pytest.skip(f"전체 스위트가 아니다 (수집 {actual}개) — 전체로 돌릴 때만 비교한다")

    stated = _stated_test_counts()
    if not stated:
        pytest.skip("문서에 테스트 수치가 없다")

    tolerance = max(30, int(actual * 0.10))
    drifted = [
        (doc, value)
        for doc, entries in stated.items()
        for _, value in entries
        if abs(value - actual) > tolerance
    ]
    assert not drifted, (
        f"문서의 테스트 수가 실제({actual})와 크게 다르다: "
        + ", ".join(f"{doc}={value}" for doc, value in drifted)
        + f"\n(허용 오차 {tolerance})"
    )
