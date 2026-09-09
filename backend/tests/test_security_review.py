"""
2차 보안 점검 — 회귀하면 조용히 위험해지는 것들.

1차(Phase 2)에서 production 가드·rate limit·토큰 폐기·탈퇴를 넣었다.
여기서 보는 것은 그 위에서 **다시 무너질 수 있는 것들**이다:

  응답에 비밀이 새는가        비밀번호 해시·토큰·서명키가 응답 본문에 들어가는가
  보안 헤더가 붙는가          클릭재킹·MIME 스니핑 방어
  정적 파일 경로 탈출         /static/ 으로 저장소 밖 파일을 읽을 수 있는가
  인증 경계                   보호되어야 할 엔드포인트가 실제로 막혀 있는가
  로그에 개인정보             이메일·닉네임·토큰이 로그에 남는가
  업로드 영상 미저장          분석 요청 영상이 디스크에 남는가

**의료 데이터 특유의 것**: 검수 시트·케이스 마스크는 실제 환자 영상 파생물이라
인증 뒤에 있어야 한다.
"""
import io as _io
import logging
import re
from pathlib import Path

import pytest

from app import security_headers
from app.static_files import STATIC_DIR

BACKEND_DIR = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------ 보안 헤더
@pytest.mark.parametrize(
    "header,expected",
    [
        ("x-content-type-options", "nosniff"),
        ("x-frame-options", "DENY"),
        ("referrer-policy", "strict-origin-when-cross-origin"),
        ("cross-origin-opener-policy", "same-origin"),
    ],
)
def test_security_headers_are_present(client, header, expected):
    """헤더 한 줄로 브라우저가 막아줄 수 있는 것들이다."""
    res = client.get("/health")
    assert res.headers.get(header) == expected


def test_security_headers_on_error_responses(client):
    """오류 응답에도 붙어야 한다 — 공격 경로는 정상 응답만이 아니다."""
    res = client.get("/api/cases/NOPE-999")
    assert res.status_code >= 400
    assert res.headers.get("x-frame-options") == "DENY"


def test_permissions_policy_disables_unused_features(client):
    """쓰지 않는 권한(카메라·마이크·위치)을 열어둘 이유가 없다."""
    policy = client.get("/health").headers.get("permissions-policy", "")
    for feature in ("camera", "microphone", "geolocation"):
        assert f"{feature}=()" in policy


def test_csp_is_not_guessed_by_default(client, monkeypatch):
    """**잘못된 CSP 는 없는 것보다 나쁘다** — 화면이 조용히 깨지면서 안전하다는 착각을 준다.

    정책은 배포 형태에 맞춰 사람이 정한 뒤 켠다.
    """
    monkeypatch.delenv(security_headers.CSP_ENV, raising=False)
    assert security_headers.csp_policy() is None
    assert client.get("/health").headers.get("content-security-policy") is None


def test_csp_is_used_when_explicitly_configured(client, monkeypatch):
    monkeypatch.setenv(security_headers.CSP_ENV, "default-src 'self'")
    res = client.get("/health")
    assert res.headers.get("content-security-policy") == "default-src 'self'"


def test_app_does_not_send_hsts(client):
    """HTTPS 종단은 앞단이 담당한다. 앱이 임의로 보내면 프록시 설정과 어긋난다."""
    assert client.get("/health").headers.get("strict-transport-security") is None


def test_health_reports_header_state(client):
    """배포 후 실제로 붙었는지 확인할 수 있어야 한다."""
    state = client.get("/health").json()["security_headers"]
    assert "X-Frame-Options" in state["headers"]
    assert "csp" in state


# ------------------------------------------------------ 응답에 비밀이 새는가
def _all_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _all_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _all_strings(v)


def test_auth_response_never_contains_password_hash(client, user_a):
    """scrypt 해시가 나가면 오프라인 대입이 가능해진다."""
    for res in (
        user_a.get("/api/auth/me"),
        client.post("/api/auth/login", json={"email": user_a.email, "password": user_a.password}),
    ):
        body = res.json()
        for text in _all_strings(body):
            assert "scrypt$" not in text, "비밀번호 해시가 응답에 들어 있다"
        assert "password_hash" not in str(body)


def test_case_response_never_leaks_the_answer_mask(user_a):
    """케이스 상세의 slice 목록에 마스크 URL 이 들어가면 답이 새어 나간다."""
    from tests.conftest import CASE_ID

    body = user_a.get(f"/api/cases/{CASE_ID}").json()
    for entry in body.get("slices", []):
        assert set(entry) <= {"slice_index", "image_url"}, f"slice 에 여분의 정보가 있다: {entry}"
        assert "mask" not in str(entry).lower()


def test_admin_summary_has_no_personal_data(admin_session):
    """학습 지표는 집계만 — 이메일·닉네임이 섞이면 안 된다."""
    body = admin_session.get("/api/admin/learning-summary").json()
    text = str(body)
    assert "@" not in text, "이메일로 보이는 값이 지표에 들어 있다"


# ------------------------------------------------------ 정적 파일 경로 탈출
@pytest.mark.parametrize(
    "path",
    [
        "/static/../alembic.ini",
        "/static/..%2Falembic.ini",
        "/static/cases/../../../requirements.txt",
    ],
)
def test_static_serving_cannot_escape_the_static_root(client, path):
    """저장소 파일을 정적 경로로 읽을 수 있으면 안 된다."""
    res = client.get(path)
    assert res.status_code in (400, 403, 404), f"{path} 가 {res.status_code} 로 응답했다"
    assert "sqlalchemy" not in res.text
    assert "alembic" not in res.text.lower() or res.status_code >= 400


def test_static_root_is_inside_the_app(client):
    """서빙 루트가 app/static 밖으로 나가 있지 않은지."""
    assert STATIC_DIR.resolve().is_relative_to((BACKEND_DIR / "app").resolve())


# ------------------------------------------------------------ 인증 경계
@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/cases"),
        ("GET", "/api/cases/VS-SEG-202"),
        ("GET", "/api/wrong-notes"),
        ("POST", "/api/analyze"),
        ("GET", "/api/analyze/availability"),
        ("GET", "/api/auth/me"),
        ("POST", "/api/auth/password"),
        ("DELETE", "/api/auth/me"),
    ],
)
def test_protected_endpoints_require_login(client, method, path):
    res = client.request(method, path, json={})
    assert res.status_code == 401, f"{method} {path} 가 비로그인에 열려 있다"


def test_normal_user_cannot_read_review_sheets(user_a):
    """검수 시트는 **실제 환자 영상에서 파생된 그림**이다."""
    res = user_a.get("/api/admin/review/candidates/VS-SEG-202/sheet")
    assert res.status_code == 403


# ------------------------------------------------------ 로그에 개인정보
def test_logs_do_not_contain_email_or_token(client, user_a, caplog):
    """계정 정보가 로그에 남으면 로그를 본 사람이 계정을 특정할 수 있다."""
    with caplog.at_level(logging.INFO, logger="app"):
        client.post("/api/auth/login", json={"email": user_a.email, "password": user_a.password})
        user_a.get("/api/auth/me")
        user_a.post("/api/auth/logout")

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert user_a.email not in text, "이메일이 로그에 남았다"
    assert user_a.token not in text, "토큰이 로그에 남았다"


def test_account_deletion_log_has_no_identifying_data(client, make_user, caplog):
    session = make_user("삭제될사용자")
    with caplog.at_level(logging.INFO, logger="app"):
        res = session.delete("/api/auth/me", json={"password": session.password})
    assert res.status_code == 200

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert session.email not in text
    assert "삭제될사용자" not in text


# ------------------------------------------------- 업로드 영상 미저장
def test_uploaded_image_is_not_written_to_disk(user_a):
    """분석 요청 영상은 저장하지 않는다 (민감정보를 남기지 않는다)."""
    import base64

    from PIL import Image

    buf = _io.BytesIO()
    Image.new("RGB", (64, 64), (123, 45, 67)).save(buf, "PNG")
    encoded = base64.b64encode(buf.getvalue()).decode()

    before = {p for p in STATIC_DIR.rglob("*") if p.is_file()}
    user_a.post(
        "/api/analyze",
        json={"image_base64": encoded, "region": {"type": "brush_mask", "points": [[10, 10]]}},
    )
    after = {p for p in STATIC_DIR.rglob("*") if p.is_file()}

    assert after == before, f"업로드 후 새 파일이 생겼다: {after - before}"


# ------------------------------------------------- 시크릿이 저장소에 없는가
def test_no_real_secret_in_env_example():
    """`.env.example` 은 커밋되는 파일이라 실제 값이 들어가면 안 된다."""
    example = BACKEND_DIR / ".env.example"
    if not example.exists():
        pytest.skip(".env.example 이 없다")

    text = example.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("MEDISCAN_SECRET_KEY"):
            value = line.split("=", 1)[1].strip() if "=" in line else ""
            assert not value or value.startswith("<"), f"실제 값처럼 보인다: {line}"


def test_no_hardcoded_secret_key_outside_the_dev_default(monkeypatch):
    """개발용 기본값 말고 다른 하드코딩 키가 없는지."""
    pattern = re.compile(r'SECRET_KEY\s*=\s*"(?!.*dev-only)[A-Za-z0-9_\-]{20,}"')
    offenders = []
    for path in (BACKEND_DIR / "app").rglob("*.py"):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.name}: {match.group(0)[:40]}")
    assert not offenders, f"하드코딩된 서명 키로 보이는 값: {offenders}"
