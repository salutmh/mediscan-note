"""
API 에러 계약 — **코드가 낼 수 있는 에러 코드가 전부 문서에 있는가.**

**왜 자동으로 확인하나**
에러 코드는 프론트가 분기하는 계약이다. 새 코드를 추가하면서 `docs/api-spec.md` 를
잊으면, 프론트는 그 코드를 모르고 사용자는 정체불명의 메시지를 본다.
실제로 `INVALID_CREDENTIALS`(로그인 실패 — 사용자가 가장 흔히 만나는 에러)가
문서에 빠져 있었고, 사람이 표를 눈으로 대조하는 방식으로는 놓쳤다.

여기서 하는 것은 **문서 표류(documentation drift) 자동 점검**이다.
"""
import re
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
SPEC = BACKEND_DIR.parent / "docs" / "api-spec.md"

# 에러 코드를 만드는 곳은 라우터만이 아니다 — deps.py(인증), uploads.py(업로드 검증),
# rate_limit.py(429) 도 만든다. **app/ 전체를 본다.**
# 처음에 라우터만 봤다가 "문서에만 있고 코드에 없다"는 오판이 9건 나왔다 —
# 수집기가 좁으면 반대 방향 검사가 거짓 경보를 낸다.
SOURCE_FILES = sorted((BACKEND_DIR / "app").rglob("*.py"))

# 에러 코드가 **아닌** 대문자 상수. 여기 넣을 때는 왜 아닌지 이유가 있어야 한다.
NOT_ERROR_CODES = {
    # 운영자 전용 로컬 도구(케이스 후보 검수)의 코드. 학습자 화면에 나오지 않고
    # 프론트가 분기하지도 않는다 — 운영자에게 문구로만 보인다.
    "CANDIDATE_NOT_FOUND",
    "SHEET_NOT_FOUND",
    "INVALID_REVIEW_STATUS",
    "REVIEW_STORE_UNREADABLE",
}


def _spec_text() -> str:
    return SPEC.read_text(encoding="utf-8")


def _codes_in_source() -> set[str]:
    """소스에서 실제로 만들어내는 에러 코드를 모은다."""
    codes: set[str] = set()
    patterns = [
        # _error(404, "CASE_NOT_FOUND", ...) / UploadError(413, "IMAGE_TOO_LARGE", ...)
        re.compile(r'\(\s*\d{3}\s*,\s*"([A-Z][A-Z0-9_]{3,})"'),
        # _unauthorized("UNAUTHORIZED", "...")
        re.compile(r'_unauthorized\(\s*"([A-Z][A-Z0-9_]{3,})"'),
        # "code": "RATE_LIMITED"
        re.compile(r'"code"\s*:\s*"([A-Z][A-Z0-9_]{3,})"'),
    ]
    for path in SOURCE_FILES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            codes.update(pattern.findall(text))
    return codes - NOT_ERROR_CODES


def test_source_actually_yields_error_codes():
    """수집기가 놀고 있으면 이 파일 전체가 무의미해진다."""
    codes = _codes_in_source()
    assert len(codes) >= 20, f"에러 코드를 제대로 수집하지 못했다: {codes}"
    # 확실히 있어야 하는 것들
    for known in ("CASE_NOT_FOUND", "INVALID_ROI", "ADMIN_REQUIRED", "RATE_LIMITED"):
        assert known in codes, f"{known} 를 수집하지 못했다"


def test_every_error_code_is_documented():
    """**코드가 낼 수 있는 에러는 전부 api-spec.md 에 있어야 한다.**

    프론트가 분기하는 계약이라, 문서에 없으면 사용자는 정체불명의 메시지를 본다.
    """
    spec = _spec_text()
    missing = sorted(code for code in _codes_in_source() if f"`{code}`" not in spec)
    assert not missing, (
        f"docs/api-spec.md 의 에러 코드 표에 없는 코드: {', '.join(missing)}\n"
        "새 에러 코드를 만들었으면 표에도 넣으세요 (프론트가 분기하는 계약입니다)."
    )


def test_documented_codes_still_exist_in_source():
    """반대 방향 — 문서에만 있고 코드에 없는 것은 사라진 계약이다.

    프론트가 이미 없어진 코드로 분기하고 있을 수 있다.
    """
    spec = _spec_text()
    # 표에 있는 행만 본다 (본문 설명에 등장하는 코드는 제외)
    table_codes = set(re.findall(r"^\|\s*`([A-Z][A-Z0-9_]{3,})`", spec, re.M))
    # 한 행에 두 개가 적힌 경우 (`A` / `B`)
    table_codes |= set(re.findall(r"`([A-Z][A-Z0-9_]{3,})`\s*\|", spec))

    source = _codes_in_source()
    stale = sorted(code for code in table_codes if code not in source)
    assert not stale, (
        f"문서에는 있는데 코드가 더 이상 만들지 않는 에러 코드: {', '.join(stale)}\n"
        "사라진 계약입니다 — 표에서 지우거나, 왜 남겨두는지 적으세요."
    )


# ------------------------------------------------- 실제 응답이 계약대로인가
def test_login_failure_returns_documented_code(client):
    """가장 흔히 만나는 에러 — 실제 응답이 문서와 같은 코드인가."""
    res = client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "whatever-1234"}
    )
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "INVALID_CREDENTIALS"
    assert "`INVALID_CREDENTIALS`" in _spec_text()


def test_login_failure_does_not_reveal_whether_the_email_exists(client, user_a):
    """가입 여부를 알려주면 계정 목록을 캐낼 수 있다."""
    wrong_password = client.post(
        "/api/auth/login", json={"email": user_a.email, "password": "definitely-wrong-1"}
    )
    no_such_user = client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "definitely-wrong-1"}
    )

    assert wrong_password.status_code == no_such_user.status_code == 401
    assert (
        wrong_password.json()["detail"]["code"] == no_such_user.json()["detail"]["code"]
    ), "존재하는 계정과 없는 계정의 응답이 다르면 가입 여부가 새어 나간다"
    assert wrong_password.json()["detail"]["message"] == no_such_user.json()["detail"]["message"]


def test_unauthenticated_request_says_login_is_needed(client):
    """인증이 먼저 걸린다 — 없는 케이스여도 UNAUTHORIZED 가 맞다
    (없는 케이스인지 여부를 로그인 없이 알려줄 이유가 없다)."""
    res = client.get("/api/cases/NOPE-999")
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "UNAUTHORIZED"


def test_missing_case_returns_case_not_found_when_logged_in(user_a):
    res = user_a.get("/api/cases/NOPE-999")
    assert res.status_code == 404
    detail = res.json()["detail"]
    assert detail["error"] is True
    assert detail["code"] == "CASE_NOT_FOUND"
    assert detail["message"], "사람이 읽을 메시지가 있어야 한다"


def test_admin_endpoint_without_login_is_unauthorized(client):
    res = client.get("/api/admin/cases")
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "UNAUTHORIZED"


def test_error_messages_do_not_leak_internals(user_a):
    """사용자에게 내부 용어·경로가 새면 안 된다."""
    res = user_a.get("/api/cases/NOPE-999")
    message = res.json()["detail"]["message"]
    for leak in ("Traceback", "sqlalchemy", "app/", ".py", "SELECT "):
        assert leak not in message, f"내부 정보가 노출됐다: {leak}"
