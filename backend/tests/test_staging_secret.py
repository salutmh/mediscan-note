"""
스테이징 DB 비밀번호 취급 — **값이 새어 나가지 않는지**를 본다.

==========================================================================
이 테스트가 지키는 것은 하나다: **비밀번호가 화면에 찍히지 않는다.**
==========================================================================
터미널 스크롤백, CI 로그, 스크린샷 — 한 번 찍히면 회수할 수 없다.
그래서 "출력에 비밀번호가 없다"를 모든 명령에 대해 확인한다.

두 번째로 지키는 것: **연결 문자열을 우리가 조립하지 않는다.**
Connect 화면이 준 문자열을 그대로 보관하고 자리표시자만 치환한다.
host 패턴을 코드로 만들면 Supabase 가 형식을 바꿨을 때 조용히 틀린다.
"""
import json

import pytest

from scripts import staging_secret as ss

REF = "abcdefghijklmnop"
REGION = "aws-0-ap-northeast-2"

DIRECT_TEMPLATE = f"postgresql://postgres:[YOUR-PASSWORD]@db.{REF}.supabase.co:5432/postgres"
SESSION_TEMPLATE = (
    f"postgresql://postgres.{REF}:[YOUR-PASSWORD]@{REGION}.pooler.supabase.com:5432/postgres"
)
TRANSACTION_TEMPLATE = (
    f"postgresql://postgres.{REF}:[YOUR-PASSWORD]@{REGION}.pooler.supabase.com:6543/postgres"
)


@pytest.fixture
def secret_file(tmp_path, monkeypatch):
    """**진짜 secret 파일을 건드리지 않는다.**"""
    path = tmp_path / ".supabase-secrets.json"
    monkeypatch.setattr(ss, "SECRET_PATH", path)
    monkeypatch.setattr(ss, "_is_gitignored", lambda p: True)
    return path


def _stored(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _password(path):
    return _stored(path)["db_password"]


# --------------------------------------------------------------- 생성
def test_init_creates_a_strong_password(secret_file):
    assert ss.main(["init"]) == 0
    password = _password(secret_file)
    assert len(password) == ss.PASSWORD_LENGTH
    assert len(set(password)) > 10, "같은 문자만 반복되면 강하지 않다"


def test_init_does_not_print_the_password(secret_file, capsys):
    ss.main(["init"])
    output = capsys.readouterr().out
    assert _password(secret_file) not in output
    assert "지문" in output, "값 대신 지문으로 확인할 수 있어야 한다"


def test_password_has_no_url_breaking_characters(secret_file):
    """`@` `:` `/` 가 섞이면 연결 문자열이 엉뚱하게 파싱된다.

    그러면 "비밀번호가 틀렸다"가 아니라 "host 를 못 찾겠다" 같은
    **엉뚱한 오류**가 나서 원인을 한참 헤맨다.
    """
    ss.main(["init"])
    password = _password(secret_file)
    for bad in "@:/#?&=[] ":
        assert bad not in password


def test_init_refuses_to_overwrite_without_force(secret_file, capsys):
    ss.main(["init"])
    first = _password(secret_file)
    assert ss.main(["init"]) == 1
    assert _password(secret_file) == first, "말없이 새 비밀번호로 바꾸면 기존 DB 에 못 붙는다"


def test_init_with_force_replaces(secret_file):
    ss.main(["init"])
    first = _password(secret_file)
    ss.main(["init", "--force"])
    assert _password(secret_file) != first


def test_init_refuses_when_the_file_would_be_committed(tmp_path, monkeypatch):
    """**커밋될 수 있는 자리에는 비밀번호를 만들지 않는다.**

    Public 저장소다. 한 번 push 되면 이력에 남아 회수할 수 없다.
    """
    monkeypatch.setattr(ss, "SECRET_PATH", tmp_path / ".supabase-secrets.json")
    monkeypatch.setattr(ss, "_is_gitignored", lambda p: False)
    with pytest.raises(SystemExit) as exc:
        ss.main(["init"])
    assert ".gitignore" in str(exc.value)
    assert not (tmp_path / ".supabase-secrets.json").exists()


def test_fingerprint_is_stable_and_hides_the_value():
    assert ss.fingerprint("hunter2") == ss.fingerprint("hunter2")
    assert ss.fingerprint("hunter2") != ss.fingerprint("hunter3")
    assert "hunter2" not in ss.fingerprint("hunter2")


# --------------------------------------------------------------- 상태
def test_status_never_prints_the_password(secret_file, capsys):
    ss.main(["init"])
    capsys.readouterr()
    ss.main(["status"])
    assert _password(secret_file) not in capsys.readouterr().out


def test_status_warns_when_not_gitignored(secret_file, monkeypatch, capsys):
    ss.main(["init"])
    monkeypatch.setattr(ss, "_is_gitignored", lambda p: False)
    assert ss.main(["status"]) == 1, "안전하지 않으면 0 을 돌려주면 안 된다"
    assert "커밋될 수 있습니다" in capsys.readouterr().out


# --------------------------------------------------- 연결 문자열 보관
def test_set_url_keeps_the_placeholder_not_the_password(secret_file):
    ss.main(["init"])
    ss.main(["set-url", "--mode", "direct", "--url", DIRECT_TEMPLATE])
    stored = _stored(secret_file)["connection_urls"]["direct"]
    assert "[YOUR-PASSWORD]" in stored
    assert _password(secret_file) not in stored


def test_set_url_rewrites_a_url_that_already_has_the_password(secret_file):
    """비밀번호를 끼워 넣은 문자열을 붙여도 자리표시자로 되돌려 보관한다."""
    ss.main(["init"])
    password = _password(secret_file)
    filled = DIRECT_TEMPLATE.replace("[YOUR-PASSWORD]", password)
    ss.main(["set-url", "--mode", "direct", "--url", filled])
    assert password not in _stored(secret_file)["connection_urls"]["direct"]


def test_set_url_rejects_a_string_without_a_placeholder(secret_file):
    """자리표시자가 없으면 Connect 에서 복사한 값이 아니다 — 조용히 받지 않는다."""
    ss.main(["init"])
    with pytest.raises(SystemExit) as exc:
        ss.main(["set-url", "--mode", "direct", "--url",
                 f"postgresql://postgres:mypw@db.{REF}.supabase.co:5432/postgres"])
    assert "자리표시자" in str(exc.value)


def test_set_url_flags_a_mode_mismatch(secret_file, capsys):
    """세션 풀러 문자열을 direct 로 저장하면 알려준다.

    **둘 다 5432 라서** 눈으로는 잘 구분되지 않는다. 모르고 저장하면
    "왜 마이그레이션이 이상하지" 를 한참 헤맨다.
    """
    ss.main(["init"])
    capsys.readouterr()
    ss.main(["set-url", "--mode", "direct", "--url", SESSION_TEMPLATE])
    assert "session_pooler" in capsys.readouterr().out


def test_set_url_accepts_a_matching_mode_quietly(secret_file, capsys):
    ss.main(["init"])
    capsys.readouterr()
    ss.main(["set-url", "--mode", "transaction_pooler", "--url", TRANSACTION_TEMPLATE])
    assert "주의" not in capsys.readouterr().out


# ------------------------------------------------------- URL 조립 (내부)
def test_database_url_substitutes_and_adds_the_driver(secret_file):
    ss.main(["init"])
    ss.main(["set-url", "--mode", "direct", "--url", DIRECT_TEMPLATE])
    data = _stored(secret_file)
    url = ss._database_url(data, "direct")
    assert url.startswith("postgresql+psycopg2://"), "SQLAlchemy 는 드라이버 접미사를 원한다"
    assert data["db_password"] in url
    assert "[YOUR-PASSWORD]" not in url


def test_database_url_reports_a_missing_mode_clearly(secret_file):
    ss.main(["init"])
    with pytest.raises(SystemExit) as exc:
        ss._database_url(_stored(secret_file), "session_pooler")
    assert "set-url" in str(exc.value)


# ------------------------------------------------------------- 실행/가림
def test_run_substitutes_the_secret_token_without_echoing_it(secret_file, capsys):
    ss.main(["init"])
    password = _password(secret_file)
    code = ss.main(["run", "--", "python", "-c",
                    "import sys; print('got', len(sys.argv[1]))", "@SECRET"])
    assert code == 0
    output = capsys.readouterr().out
    assert f"got {ss.PASSWORD_LENGTH}" in output, "자식이 실제 비밀번호를 받아야 한다"
    assert password not in output, "**명령 표시 줄에 비밀번호가 찍히면 안 된다**"
    assert "***" in output


def test_run_redacts_the_password_from_child_output(secret_file, capsys):
    """도구들은 오류 메시지에 연결 문자열을 통째로 넣는 일이 많다."""
    ss.main(["init"])
    password = _password(secret_file)
    ss.main(["run", "--", "python", "-c", "import sys; print('연결 실패:', sys.argv[1])", "@SECRET"])
    captured = capsys.readouterr()
    assert password not in captured.out
    assert "***" in captured.out


def test_run_passes_database_url_through_the_environment(secret_file, capsys):
    """환경변수로 넘기면 프로세스 목록에 보이지 않는다."""
    ss.main(["init"])
    ss.main(["set-url", "--mode", "direct", "--url", DIRECT_TEMPLATE])
    capsys.readouterr()
    ss.main(["run", "--mode", "direct", "--", "python", "-c",
             "import os; print('MODE_OK' if 'supabase.co' in os.environ['DATABASE_URL'] else 'NO')"])
    captured = capsys.readouterr()
    assert "MODE_OK" in captured.out
    assert _password(secret_file) not in captured.out


def test_run_propagates_the_exit_code(secret_file):
    """실패를 성공으로 삼키면 안 된다."""
    ss.main(["init"])
    assert ss.main(["run", "--", "python", "-c", "raise SystemExit(3)"]) == 3


def test_redact_also_catches_the_url_encoded_form():
    password = "a~b.c-d_e"
    text = f"error at postgresql://postgres:{password}@host/db"
    assert password not in ss._redact(text, password)


# ------------------------------------------------------------------ check
def test_check_warns_that_migrations_need_direct(secret_file, capsys):
    ss.main(["init"])
    ss.main(["set-url", "--mode", "transaction_pooler", "--url", TRANSACTION_TEMPLATE])
    capsys.readouterr()
    ss.main(["check"])
    output = capsys.readouterr().out
    assert "Direct connection" in output
    assert "migration" in output


def test_check_does_not_need_or_print_the_real_password(secret_file, capsys):
    ss.main(["init"])
    ss.main(["set-url", "--mode", "direct", "--url", DIRECT_TEMPLATE])
    capsys.readouterr()
    ss.main(["check"])
    assert _password(secret_file) not in capsys.readouterr().out


def test_check_does_not_leak_the_project_ref(secret_file, capsys):
    """host 에는 프로젝트 식별자가 들어 있다 — 요약에는 넣지 않는다."""
    ss.main(["init"])
    ss.main(["set-url", "--mode", "direct", "--url", DIRECT_TEMPLATE, "--ref", REF])
    capsys.readouterr()
    ss.main(["check"])
    assert REF not in capsys.readouterr().out


def test_check_reports_nothing_stored(secret_file, capsys):
    ss.main(["init"])
    capsys.readouterr()
    assert ss.main(["check"]) == 1
    assert "없습니다" in capsys.readouterr().out


# ------------------------------------------------------------ 깨진 파일
def test_corrupt_secret_file_is_not_silently_overwritten(secret_file):
    """깨진 파일 안에 **유일한** 비밀번호가 있을 수 있다."""
    secret_file.write_text("{ 깨짐", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        ss.main(["status"])
    assert "직접 열어 확인" in str(exc.value)
    assert secret_file.read_text(encoding="utf-8") == "{ 깨짐"
