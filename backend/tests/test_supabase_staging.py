"""
Supabase 스테이징 준비 점검 — **네트워크 없이** 판단 로직만 본다.

==========================================================================
여기서 지키는 것
==========================================================================
1. **access token 을 출력하지 않는다.** 로그인 여부만 본다.
2. **같은 이름의 프로젝트를 둘 만들지 않는다.** 이미 있으면 그걸 쓴다.
   둘 만들면 어느 쪽에 마이그레이션을 돌렸는지 헷갈리고, 빈 쪽을 보며
   "왜 테이블이 없지" 를 한참 헤맨다.
3. **로그인 안 됨을 오류로 뭉개지 않는다.** 사용자가 직접 해야 하는
   유일한 단계라, 무엇을 하면 되는지 정확히 알려야 한다.
"""
import subprocess

import pytest

from scripts import supabase_staging as ss


def _proc(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=["x"], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


# ------------------------------------------------------- 로그인 여부 판별
def test_logged_out_is_detected_from_the_cli_error():
    """CLI 가 실제로 내는 오류 형태 (2.117.0 기준)."""
    blob = ('{"_tag":"Error","error":{"code":"LegacyPlatformAuthRequiredError",'
            '"message":"Access token not provided. Supply an access token by running '
            '`supabase login` or setting the SUPABASE_ACCESS_TOKEN environment variable."}}')
    assert ss._looks_logged_out(_proc(stdout=blob, returncode=1))


@pytest.mark.parametrize("message", [
    "AuthRequiredError",
    "Access token not provided",
    "Please run supabase login first",
])
def test_multiple_signals_are_accepted(message):
    """**문구는 바뀐다.** 하나에만 의존하면 어느 날 조용히 오탐이 된다."""
    assert ss._looks_logged_out(_proc(stderr=message, returncode=1))


def test_a_successful_listing_is_not_read_as_logged_out():
    assert not ss._looks_logged_out(_proc(stdout="[]"))


def test_an_unrelated_failure_is_not_read_as_logged_out():
    """네트워크 오류를 "로그인하세요" 로 안내하면 엉뚱한 곳을 고치게 된다."""
    assert not ss._looks_logged_out(_proc(stderr="dial tcp: i/o timeout", returncode=1))


# --------------------------------------------------------- 기존 프로젝트
def test_existing_project_is_found_by_name():
    projects = [
        {"name": "other-project", "id": "aaaa"},
        {"name": ss.PROJECT_NAME, "id": "bbbb", "region": "ap-northeast-2"},
    ]
    assert ss._find_project(projects)["id"] == "bbbb"


def test_a_similar_name_is_not_treated_as_the_same_project():
    """`mediscan-note-staging-2` 를 같은 것으로 보면 엉뚱한 DB 에 붙는다."""
    assert ss._find_project([{"name": ss.PROJECT_NAME + "-2", "id": "x"}]) is None


def test_no_projects_means_none_found():
    assert ss._find_project([]) is None


def test_seoul_is_the_default_region():
    assert ss.REGION == "ap-northeast-2"


# ------------------------------------------------------------ JSON 파싱
def test_broken_json_does_not_crash():
    """CLI 가 경고 한 줄을 먼저 뱉으면 JSON 이 깨진다 — 죽지 말고 빈 목록으로."""
    assert ss._parse_json_list("warning: something\n[]") == []


def test_non_list_json_is_ignored():
    assert ss._parse_json_list('{"error": true}') == []


def test_empty_output_is_ignored():
    assert ss._parse_json_list("") == []


# ---------------------------------------------------- 실행 파일 찾기 (Windows)
def test_cli_command_uses_a_resolved_path(monkeypatch):
    """**Windows 에서 `npx` 는 `npx.cmd` 다.**

    이름만 넘기면 subprocess 가 "지정된 파일을 찾을 수 없습니다" 로 죽는다.
    실제로 여기서 한 번 걸렸다.
    """
    monkeypatch.setattr(ss.shutil, "which",
                        lambda name: r"C:\Program Files\nodejs\npx.CMD" if name == "npx" else None)
    command = ss.cli_command()
    assert command[0].endswith("npx.CMD")
    assert ss.CLI_PACKAGE in command


def test_a_globally_installed_cli_is_preferred(monkeypatch):
    monkeypatch.setattr(ss.shutil, "which",
                        lambda name: "/usr/local/bin/supabase" if name == "supabase" else "/x/npx")
    assert ss.cli_command() == ["/usr/local/bin/supabase"]


def test_missing_cli_is_reported_not_crashed(monkeypatch, capsys):
    monkeypatch.setattr(ss.shutil, "which", lambda name: None)
    assert ss.cli_command() is None
    assert ss.preflight(None) == 2
    assert "nodejs.org" in capsys.readouterr().out


# ------------------------------------------------------------- 안내 문구
def test_login_instructions_name_the_exact_command():
    """사용자가 직접 해야 하는 유일한 단계다 — 정확한 명령이 있어야 한다."""
    assert "supabase@latest login" in ss.LOGIN_INSTRUCTIONS


def test_login_instructions_do_not_ask_for_the_token():
    """**토큰을 붙여 달라고 하면 안 된다.** CLI 가 보관하게 둔다."""
    assert "보여주지 마세요" in ss.LOGIN_INSTRUCTIONS


def test_preflight_stops_at_login_without_touching_projects(monkeypatch, capsys):
    """로그인 전에는 조직·프로젝트를 묻지 않는다 — 어차피 실패한다."""
    monkeypatch.setattr(ss, "cli_command", lambda: ["fake-cli"])
    calls = []

    def fake_run(argv, timeout=180):
        calls.append(argv)
        if argv[1:] == ["--version"]:
            return _proc(stdout="2.117.0")
        return _proc(stderr="Access token not provided", returncode=1)

    monkeypatch.setattr(ss, "_run", fake_run)
    assert ss.preflight(None) == 1
    assert not any("orgs" in argv for argv in calls), "로그인 전에 조직을 묻지 않는다"
    assert "로그인 안 됨" in capsys.readouterr().out


def test_preflight_does_not_print_the_access_token(monkeypatch, capsys):
    monkeypatch.setenv("SUPABASE_ACCESS_TOKEN", "sbp_supersecret_value")
    monkeypatch.setattr(ss, "cli_command", lambda: ["fake-cli"])
    monkeypatch.setattr(ss, "_run", lambda argv, timeout=180: _proc(
        stdout="2.117.0" if argv[1:] == ["--version"] else "",
        stderr="" if argv[1:] == ["--version"] else "Access token not provided",
        returncode=0 if argv[1:] == ["--version"] else 1,
    ))
    ss.preflight(None)
    assert "sbp_supersecret_value" not in capsys.readouterr().out


def test_preflight_reuses_an_existing_project(monkeypatch, capsys):
    """**같은 이름을 둘 만들지 않는다.**"""
    monkeypatch.setattr(ss, "cli_command", lambda: ["fake-cli"])

    def fake_run(argv, timeout=180):
        if argv[1:] == ["--version"]:
            return _proc(stdout="2.117.0")
        if "orgs" in argv:
            return _proc(stdout='[{"id":"org_1","name":"내 조직"}]')
        return _proc(stdout='[{"name":"mediscan-note-staging","id":"ref123",'
                            '"region":"ap-northeast-2","status":"ACTIVE_HEALTHY"}]')

    monkeypatch.setattr(ss, "_run", fake_run)
    assert ss.preflight(None) == 0
    output = capsys.readouterr().out
    assert "이미 있음" in output
    assert "새로 만들지 않습니다" in output


def test_preflight_tells_you_how_to_create_when_missing(monkeypatch, capsys):
    monkeypatch.setattr(ss, "cli_command", lambda: ["fake-cli"])
    monkeypatch.setattr(ss, "_run", lambda argv, timeout=180: _proc(
        stdout="2.117.0" if argv[1:] == ["--version"] else "[]"))
    ss.preflight(None)
    assert "--org-id" in capsys.readouterr().out


# ------------------------------------------------------------------- 생성
def test_create_refuses_when_the_project_already_exists(monkeypatch, capsys):
    monkeypatch.setattr(ss, "cli_command", lambda: ["fake-cli"])
    monkeypatch.setattr(ss, "_run", lambda argv, timeout=180: _proc(
        stdout='[{"name":"mediscan-note-staging","id":"ref123"}]'))
    monkeypatch.setattr(type(ss.staging_secret.SECRET_PATH), "exists", lambda self: True)

    args = type("A", (), {"org_id": "org_1", "region": ss.REGION, "size": None})()
    assert ss.create(args) == 0
    assert "새로 만들지 않습니다" in capsys.readouterr().out


def test_create_passes_the_password_as_a_placeholder_token(monkeypatch):
    """**비밀번호가 argv 조립 단계에 평문으로 나타나지 않는다.**

    `staging_secret run` 이 마지막 순간에 바꿔 넣고, 화면에는 `***` 로 찍는다.
    """
    monkeypatch.setattr(ss, "cli_command", lambda: ["fake-cli"])
    monkeypatch.setattr(ss, "_run", lambda argv, timeout=180: _proc(stdout="[]"))
    monkeypatch.setattr(type(ss.staging_secret.SECRET_PATH), "exists", lambda self: True)

    captured = {}
    monkeypatch.setattr(ss.staging_secret, "main", lambda argv: captured.setdefault("argv", argv) or 0)

    args = type("A", (), {"org_id": "org_1", "region": ss.REGION, "size": None})()
    ss.create(args)

    argv = captured["argv"]
    assert argv[0] == "run"
    assert ss.staging_secret.SECRET_TOKEN in argv
    assert "--region" in argv and ss.REGION in argv


def test_create_stops_when_logged_out(monkeypatch, capsys):
    monkeypatch.setattr(ss, "cli_command", lambda: ["fake-cli"])
    monkeypatch.setattr(ss, "_run", lambda argv, timeout=180: _proc(
        stderr="Access token not provided", returncode=1))
    monkeypatch.setattr(type(ss.staging_secret.SECRET_PATH), "exists", lambda self: True)

    args = type("A", (), {"org_id": "org_1", "region": ss.REGION, "size": None})()
    assert ss.create(args) == 1
    assert "login" in capsys.readouterr().out
