"""
배포 직전 점검.

**점검 도구의 가장 큰 위험은 "전부 통과"가 거짓일 때다.**
확인하지 못한 것을 "이상 없음"으로 뭉개면 체크리스트가 있으나 마나다.
그래서 이 도구는 결과를 넷으로 나눈다: 차단 / 주의 / **확인못함** / 통과.

사람이 판단할 항목(데이터셋 이용 조건, 전문가 GT 검수, 규제 검토)은
확인하는 척하지 않고 항상 "확인못함"에 남긴다.
"""
import pytest

from scripts import deploy_preflight as pre


def _levels(report, check_name):
    return [r["level"] for r in report.rows if r["check"] == check_name]


def _clear_env(monkeypatch):
    for name in (
        "MEDISCAN_ENV",
        "MEDISCAN_SECRET_KEY",
        "MEDISCAN_CORS_ORIGINS",
        "DATABASE_URL",
        "MEDISCAN_RATE_LIMIT",
        "MEDISCAN_RATE_LIMIT_MULTIPLIER",
        "MEDISCAN_MATCH_DICE",
        "MEDISCAN_PARTIAL_DICE",
        "MEDISCAN_ALLOW_APPROX_GRADING",
        "MEDISCAN_SEED_MOCK_CASES",
        "MEDISCAN_ANALYZE_DEMO",
    ):
        monkeypatch.delenv(name, raising=False)


def _production(monkeypatch, **overrides):
    _clear_env(monkeypatch)
    values = {
        "MEDISCAN_ENV": "production",
        "MEDISCAN_SECRET_KEY": "x" * 48,
        "MEDISCAN_CORS_ORIGINS": "https://mediscan.example.com",
        "DATABASE_URL": "postgresql+psycopg2://u:p@db:5432/mediscan",
    }
    values.update(overrides)
    for key, value in values.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)


# ------------------------------------------------------------------ 시크릿
def test_repository_dev_secret_blocks_deploy(monkeypatch):
    """저장소에 공개된 값이라 누구나 토큰을 위조할 수 있다."""
    _production(monkeypatch, MEDISCAN_SECRET_KEY=pre.DEV_SECRET)
    report = pre.Report()
    pre.check_environment(report)
    assert pre.BLOCK in _levels(report, "MEDISCAN_SECRET_KEY")


def test_missing_secret_blocks_deploy(monkeypatch):
    _production(monkeypatch, MEDISCAN_SECRET_KEY=None)
    report = pre.Report()
    pre.check_environment(report)
    assert pre.BLOCK in _levels(report, "MEDISCAN_SECRET_KEY")


def test_short_secret_blocks_deploy(monkeypatch):
    _production(monkeypatch, MEDISCAN_SECRET_KEY="short")
    report = pre.Report()
    pre.check_environment(report)
    assert pre.BLOCK in _levels(report, "MEDISCAN_SECRET_KEY")


def test_good_secret_passes(monkeypatch):
    _production(monkeypatch)
    report = pre.Report()
    pre.check_environment(report)
    assert _levels(report, "MEDISCAN_SECRET_KEY") == [pre.OK]


# ------------------------------------------------------------------ CORS
def test_wildcard_cors_blocks_deploy(monkeypatch):
    _production(monkeypatch, MEDISCAN_CORS_ORIGINS="*")
    report = pre.Report()
    pre.check_environment(report)
    assert pre.BLOCK in _levels(report, "MEDISCAN_CORS_ORIGINS")


def test_missing_cors_blocks_deploy(monkeypatch):
    _production(monkeypatch, MEDISCAN_CORS_ORIGINS=None)
    report = pre.Report()
    pre.check_environment(report)
    assert pre.BLOCK in _levels(report, "MEDISCAN_CORS_ORIGINS")


# ------------------------------------------------------------------ DB URL
def test_missing_database_url_blocks_deploy(monkeypatch):
    """컨테이너 로컬 SQLite 로 떨어지면 재배포 때 학습 이력이 사라진다."""
    _production(monkeypatch, DATABASE_URL=None)
    report = pre.Report()
    pre.check_environment(report)
    assert pre.BLOCK in _levels(report, "DATABASE_URL")


def test_sqlite_in_production_is_a_warning(monkeypatch):
    """막지는 않는다 — 소규모에서는 쓸 수 있다. 다만 알고 있어야 한다."""
    _production(monkeypatch, DATABASE_URL="sqlite:///./app.db")
    report = pre.Report()
    pre.check_environment(report)
    assert _levels(report, "DATABASE_URL") == [pre.WARN]


# ------------------------------------------------------- 개발 전용 스위치
@pytest.mark.parametrize(
    "flag", ["MEDISCAN_ALLOW_APPROX_GRADING", "MEDISCAN_SEED_MOCK_CASES", "MEDISCAN_ANALYZE_DEMO"]
)
def test_dev_only_flag_blocks_deploy(monkeypatch, flag):
    _production(monkeypatch)
    monkeypatch.setenv(flag, "1")
    report = pre.Report()
    pre.check_environment(report)
    assert pre.BLOCK in _levels(report, "개발 전용 스위치")


def test_no_dev_flags_passes(monkeypatch):
    _production(monkeypatch)
    report = pre.Report()
    pre.check_environment(report)
    assert _levels(report, "개발 전용 스위치") == [pre.OK]


# ------------------------------------------------------------ 요청 수 제한
def test_disabled_rate_limit_blocks_deploy(monkeypatch):
    _production(monkeypatch, **{"MEDISCAN_RATE_LIMIT": "0"})
    report = pre.Report()
    pre.check_rate_limit(report)
    assert pre.BLOCK in _levels(report, "요청 수 제한")


def test_external_rate_limit_is_a_warning(monkeypatch):
    """앞단에서 막는 정상 구성 — 다만 정말 막고 있는지는 사람이 확인해야 한다."""
    _production(monkeypatch, **{"MEDISCAN_RATE_LIMIT": "external"})
    report = pre.Report()
    pre.check_rate_limit(report)
    assert _levels(report, "요청 수 제한") == [pre.WARN]


# ------------------------------------------------------------ 채점 임계값
def test_reversed_thresholds_block_deploy(monkeypatch):
    """partial > match 면 partial_match 등급이 통째로 사라진다."""
    _production(monkeypatch)
    monkeypatch.setenv("MEDISCAN_MATCH_DICE", "0.5")
    monkeypatch.setenv("MEDISCAN_PARTIAL_DICE", "0.9")

    report = pre.Report()
    pre.check_scoring(report)
    assert pre.BLOCK in _levels(report, "채점 임계값")


def test_overridden_thresholds_are_warned(monkeypatch):
    _production(monkeypatch)
    monkeypatch.setenv("MEDISCAN_MATCH_DICE", "0.7")
    report = pre.Report()
    pre.check_scoring(report)
    assert _levels(report, "채점 임계값") == [pre.WARN]


def test_threshold_validity_is_always_unknown(monkeypatch):
    """**임계값이 교육적으로 타당한지는 기계가 판단할 수 없다.**

    기본값이어도 "통과"로 적지 않는다 — 전문가 검토 대상이다.
    """
    _production(monkeypatch)
    report = pre.Report()
    pre.check_scoring(report)
    assert _levels(report, "채점 임계값 교육적 타당성") == [pre.UNKNOWN]


# --------------------------------------------- 사람이 판단할 항목 (핵심)
def test_human_judgement_items_are_never_marked_ok():
    """확인하는 척하지 않는다. 이 항목들이 통과로 바뀌면 체크리스트가 무의미해진다."""
    report = pre.Report()
    pre.add_human_checks(report)

    assert report.rows, "사람 판단 항목이 비어 있다"
    assert all(r["level"] == pre.UNKNOWN for r in report.rows)
    names = {r["check"] for r in report.rows}
    assert "데이터셋·모델 이용 조건" in names
    assert "전문가 GT 검수" in names
    assert "개인정보·규제 검토" in names
    # 실검증 로직은 구현됐고 기계가 설정 여부를 확인한다.
    # 남은 사람 판단은 "각 사에 앱을 등록하고 ID 를 받는 것"이다.
    assert "SNS 앱 등록" in names


def test_unknown_does_not_count_as_blocking():
    """사람이 봐야 하는 항목이 배포를 막지는 않는다 — 판단은 사람 몫이다."""
    report = pre.Report()
    pre.add_human_checks(report)
    assert report.count(pre.BLOCK) == 0
    assert report.count(pre.UNKNOWN) >= 4
