"""
스테이징 시드 — **엉뚱한 DB 에 쓰지 않는지**를 본다.

==========================================================================
가장 위험한 실수: `DATABASE_URL` 이 운영 DB 를 가리킨 채로 시드를 돌리는 것.
==========================================================================
그러면 운영 DB 에 계정이 생기고, 되돌리기 어렵다. 그래서 이 스크립트는
"이 DB 에 스테이징이 아닌 계정이 있으면" 멈춘다.

두 번째로 지키는 것: **비밀번호를 출력하지 않는다.**
세 번째: **이미 있는 계정의 비밀번호를 말없이 바꾸지 않는다** —
다른 곳에 적어 둔 값이 죽는다.
"""
import pytest
from sqlalchemy import select

from app.models import Consent, User
from app.schemas import REQUIRED_CONSENT_KEYS
from app.security import verify_password
from scripts import staging_seed
from scripts import staging_secret


@pytest.fixture
def db_session():
    """실제 세션. `_clean_user_data` 가 테스트마다 사용자 데이터를 비운다."""
    from app.db import SessionLocal

    with SessionLocal() as session:
        yield session


@pytest.fixture
def secret_file(tmp_path, monkeypatch):
    """**진짜 secret 파일을 건드리지 않는다.**"""
    path = tmp_path / ".supabase-secrets.json"
    monkeypatch.setattr(staging_secret, "SECRET_PATH", path)
    monkeypatch.setattr(staging_secret, "_is_gitignored", lambda p: True)
    return path


def _accounts(path):
    import json

    return json.loads(path.read_text(encoding="utf-8"))["staging_accounts"]


# ------------------------------------------------------------- 만드는 것
def test_seed_creates_exactly_two_accounts(db_session, secret_file):
    """운영자 1 + 학습자 1. **그 이상 만들지 않는다.**"""
    staging_seed.seed(db_session)
    users = db_session.scalars(select(User)).all()
    assert len(users) == 2, "검증용 계정 둘 말고는 만들지 않는다"
    assert {u.is_admin for u in users} == {True, False}


def test_seeded_emails_cannot_receive_real_mail(db_session, secret_file):
    """`.invalid` 는 예약 TLD 다 — 스테이징 메일이 남의 주소로 가지 않는다."""
    staging_seed.seed(db_session)
    for user in db_session.scalars(select(User)).all():
        assert user.email.endswith("@staging.invalid")


def test_seeded_accounts_can_actually_log_in(db_session, secret_file):
    """해시가 저장된 비밀번호와 맞는지 — 안 맞으면 E2E 가 첫 줄에서 막힌다."""
    staging_seed.seed(db_session)
    accounts = _accounts(secret_file)
    admin = db_session.scalar(
        select(User).where(User.email == "staging-admin@staging.invalid")
    )
    assert verify_password(accounts["admin"]["password"], admin.password_hash)


def test_required_consents_are_recorded(db_session, secret_file):
    """동의 5개가 없으면 계정이 성립하지 않는 구조다."""
    staging_seed.seed(db_session)
    admin = db_session.scalar(
        select(User).where(User.email == "staging-admin@staging.invalid")
    )
    keys = {
        c.key
        for c in db_session.scalars(select(Consent).where(Consent.user_id == admin.user_id))
    }
    assert set(REQUIRED_CONSENT_KEYS) <= keys


def test_consent_version_says_it_is_a_seed(db_session, secret_file):
    """**이건 실제 동의가 아니다.** 이력만 보고 증빙으로 오해하면 안 된다."""
    staging_seed.seed(db_session)
    versions = {c.version for c in db_session.scalars(select(Consent)).all()}
    assert versions == {"staging-seed"}


def test_no_cases_or_medical_content_are_created(db_session, secret_file):
    """의료 콘텐츠는 여기서 만들지 않는다 — 전문가 검수를 거친 것만 등록한다.

    케이스는 `scripts.import_cases` 로만 들어온다. 시드가 케이스를 하나라도
    만들면, 검수를 거치지 않은 의료 콘텐츠가 DB 에 생기는 셈이다.
    """
    from app.models import Case

    before = len(db_session.scalars(select(Case)).all())
    staging_seed.seed(db_session)
    assert len(db_session.scalars(select(Case)).all()) == before


# ------------------------------------------------------------- 비밀번호
def test_passwords_are_not_printed(db_session, secret_file, capsys):
    staging_seed.seed(db_session)
    output = capsys.readouterr().out
    for entry in _accounts(secret_file).values():
        assert entry["password"] not in output


def test_passwords_are_stored_in_the_local_secret_file(db_session, secret_file):
    staging_seed.seed(db_session)
    accounts = _accounts(secret_file)
    assert set(accounts) == {"admin", "learner"}
    for entry in accounts.values():
        assert len(entry["password"]) == staging_seed.PASSWORD_LENGTH
        assert entry["fingerprint"].startswith("sha256:")


def test_each_account_gets_a_different_password(db_session, secret_file):
    staging_seed.seed(db_session)
    accounts = _accounts(secret_file)
    assert accounts["admin"]["password"] != accounts["learner"]["password"]


def test_rerunning_does_not_change_existing_passwords(db_session, secret_file):
    """**말없이 바꾸면 다른 곳에 적어 둔 값이 죽는다.**"""
    staging_seed.seed(db_session)
    before = _accounts(secret_file)["admin"]["password"]
    hash_before = db_session.scalar(
        select(User).where(User.email == "staging-admin@staging.invalid")
    ).password_hash

    staging_seed.seed(db_session)
    assert _accounts(secret_file)["admin"]["password"] == before
    assert db_session.scalar(
        select(User).where(User.email == "staging-admin@staging.invalid")
    ).password_hash == hash_before


def test_seed_refuses_when_the_secret_file_could_be_committed(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(staging_secret, "SECRET_PATH", tmp_path / ".supabase-secrets.json")
    monkeypatch.setattr(staging_secret, "_is_gitignored", lambda p: False)
    with pytest.raises(SystemExit):
        staging_seed.seed(db_session)


# ------------------------------------------------------------------ 안전장치
def test_seed_is_idempotent(db_session, secret_file):
    staging_seed.seed(db_session)
    staging_seed.seed(db_session)
    assert len(db_session.scalars(select(User)).all()) == 2


def test_seed_refuses_a_database_holding_other_users(db_session, secret_file):
    """**운영 DB 를 가리켰을 때 멈추게 하는 장치다.**"""
    db_session.add(User(user_id="u_real0001", email="someone@example.com",
                        password_hash="x", nickname="실제 사용자"))
    db_session.commit()

    with pytest.raises(SystemExit) as exc:
        staging_seed.seed(db_session)
    assert "DATABASE_URL" in str(exc.value)
    assert db_session.scalars(
        select(User).where(User.email.like("%staging.invalid"))
    ).all() == []


def test_the_override_is_available_but_explicit(db_session, secret_file):
    """막기만 하면 정당한 경우에 손발이 묶인다 — 대신 명시적으로 넘게 한다."""
    db_session.add(User(user_id="u_real0001", email="someone@example.com",
                        password_hash="x", nickname="실제 사용자"))
    db_session.commit()

    staging_seed.seed(db_session, allow_existing=True)
    assert len(db_session.scalars(select(User)).all()) == 3


def test_seed_refuses_in_production(db_session, secret_file, monkeypatch):
    monkeypatch.setenv("MEDISCAN_ENV", "production")
    with pytest.raises(SystemExit) as exc:
        staging_seed.seed(db_session)
    assert "production" in str(exc.value)


# --------------------------------------------------------------------- check
def test_check_reports_missing_accounts(db_session, secret_file, capsys):
    assert staging_seed.check(db_session) == 1
    assert "[없음]" in capsys.readouterr().out


def test_check_passes_after_seeding(db_session, secret_file, capsys):
    staging_seed.seed(db_session)
    capsys.readouterr()
    assert staging_seed.check(db_session) == 0
    assert "[있음]" in capsys.readouterr().out


def test_check_flags_a_database_that_looks_like_production(db_session, secret_file, capsys):
    staging_seed.seed(db_session)
    db_session.add(User(user_id="u_real0001", email="someone@example.com",
                        password_hash="x", nickname="실제 사용자"))
    db_session.commit()
    capsys.readouterr()
    staging_seed.check(db_session)
    assert "운영 DB 일 수 있습니다" in capsys.readouterr().out
