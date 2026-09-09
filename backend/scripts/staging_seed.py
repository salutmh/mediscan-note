"""
스테이징 DB 에 **최소한의** 계정만 만든다.

==========================================================================
**production 데이터를 넣지 않는다. 실제 사용자 데이터도 넣지 않는다.**
==========================================================================
스테이징은 "붙는지, 스키마가 맞는지, E2E 가 도는지" 를 보는 곳이다.
실제 사용자 계정·제출 이력을 복사해 오면 그 순간 스테이징도 개인정보
처리 시스템이 된다 — 접근 통제도, 보관 기간도, 파기 절차도 따라와야 한다.
그래서 여기서 만드는 것은 **검증용 계정 두 개뿐**이다.

케이스(영상·기준마스크)는 여기서 만들지 않는다. `scripts.import_cases` 로
따로 등록한다. 영상 파일 자체는 **앱 서버 디스크에 있고 Supabase 로 올리지 않는다.**

만드는 것
---------
  * 운영자 계정 1개  — /admin 화면 확인용
  * 학습자 계정 1개  — 판독→채점→복습 E2E 용

비밀번호
--------
`staging_secret` 과 같은 로컬 secret 파일에 보관하고 **출력하지 않는다.**
확인은 지문으로 한다. 값이 필요하면 `staging_secret run` 으로 넘긴다.

동의 이력에 대해
----------------
이 계정들에도 필수 동의 5개가 기록된다 (없으면 계정이 성립하지 않는 구조다).
**이것은 실제 동의가 아니다.** 그래서 이메일을 `@staging.invalid` 로 둔다 —
`.invalid` 는 예약된 TLD 라 어떤 메일도 실제로 도달하지 않는다. 스테이징
DB 의 동의 이력을 증빙으로 쓰지 않는다.

사용법
------
    cd backend
    python -m scripts.staging_seed            # 만들기 (이미 있으면 건너뛴다)
    python -m scripts.staging_seed --check    # 상태만 확인
"""
import argparse
import os
import secrets
import string
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db import SessionLocal, run_migrations  # noqa: E402
from app.models import Consent, User  # noqa: E402
from app.schemas import REQUIRED_CONSENT_KEYS  # noqa: E402
from app.security import hash_password  # noqa: E402
from scripts import staging_secret  # noqa: E402

# `.invalid` 는 RFC 2606 예약 TLD — 실제로 메일이 가지 않는다.
# 실수로 진짜 주소를 쓰면 스테이징 알림이 모르는 사람에게 갈 수 있다.
STAGING_DOMAIN = "@staging.invalid"

ACCOUNTS = [
    {
        "key": "admin",
        "email": "staging-admin" + STAGING_DOMAIN,
        "nickname": "스테이징 운영자",
        "is_admin": True,
        "purpose": "/admin 화면과 운영자 전용 API 확인",
    },
    {
        "key": "learner",
        "email": "staging-learner" + STAGING_DOMAIN,
        "nickname": "스테이징 학습자",
        "is_admin": False,
        "purpose": "판독 → 채점 → 복습 E2E",
    },
]

CONSENT_VERSION = "staging-seed"  # 실제 약관 버전이 아님을 이력에 남긴다
PASSWORD_LENGTH = 24
ALPHABET = string.ascii_letters + string.digits


def _generate_password() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(PASSWORD_LENGTH))


def _is_staging_account(user: User) -> bool:
    return bool(user.email and user.email.endswith(STAGING_DOMAIN))


def _guard(db, allow_existing: bool) -> None:
    """**엉뚱한 DB 에 쓰지 않는다.**

    운영 DB 를 가리킨 채로 이 스크립트를 돌리면 운영 DB 에 계정이 생긴다.
    실수를 되돌리기 어려우니 여기서 막는다.
    """
    if os.getenv("MEDISCAN_ENV", "").lower() == "production":
        raise SystemExit(
            "MEDISCAN_ENV=production 입니다. 스테이징 시드는 production 에 넣지 않습니다."
        )

    others = [u for u in db.scalars(select(User)).all() if not _is_staging_account(u)]
    if others and not allow_existing:
        raise SystemExit(
            "이 DB 에는 스테이징이 아닌 계정이 {}개 있습니다.\n"
            "운영 DB 를 가리키고 있지 않은지 DATABASE_URL 을 확인하세요.\n"
            "정말 맞다면 --allow-existing-users 를 붙이세요.".format(len(others))
        )


def _secret_store() -> dict:
    return staging_secret._load()


def _save_account_password(key: str, password: str) -> str:
    data = _secret_store()
    accounts = data.setdefault("staging_accounts", {})
    accounts[key] = {
        "password": password,
        "fingerprint": staging_secret.fingerprint(password),
    }
    staging_secret._save(data)
    return accounts[key]["fingerprint"]


def _stored_password(key: str) -> str | None:
    entry = (_secret_store().get("staging_accounts") or {}).get(key)
    return entry.get("password") if entry else None


def seed(db, *, allow_existing: bool = False) -> list[dict]:
    _guard(db, allow_existing)
    staging_secret._require_gitignored()

    report = []
    for spec in ACCOUNTS:
        existing = db.scalar(select(User).where(User.email == spec["email"]))
        if existing:
            # **비밀번호를 말없이 바꾸지 않는다.** 다른 곳에 적어 둔 값이 죽는다.
            report.append({
                "key": spec["key"], "email": spec["email"], "created": False,
                "fingerprint": (_secret_store().get("staging_accounts") or {})
                               .get(spec["key"], {}).get("fingerprint", "(없음)"),
            })
            continue

        password = _stored_password(spec["key"]) or _generate_password()
        fingerprint = _save_account_password(spec["key"], password)

        user = User(
            user_id="u_" + uuid.uuid4().hex[:8],
            email=spec["email"],
            password_hash=hash_password(password),
            nickname=spec["nickname"],
            is_admin=spec["is_admin"],
        )
        db.add(user)
        db.flush()
        for consent_key in REQUIRED_CONSENT_KEYS:
            db.add(Consent(user_id=user.user_id, key=consent_key,
                           agreed=True, version=CONSENT_VERSION))
        report.append({
            "key": spec["key"], "email": spec["email"], "created": True,
            "fingerprint": fingerprint,
        })

    db.commit()
    return report


def check(db) -> int:
    print("스테이징 계정")
    missing = 0
    for spec in ACCOUNTS:
        user = db.scalar(select(User).where(User.email == spec["email"]))
        if not user:
            print("  [없음]  {}  — {}".format(spec["email"], spec["purpose"]))
            missing += 1
            continue
        admin_ok = user.is_admin == spec["is_admin"]
        consents = db.scalars(
            select(Consent).where(Consent.user_id == user.user_id)
        ).all()
        print("  [있음]  {}  운영자={}{}  동의 {}건".format(
            spec["email"], user.is_admin, "" if admin_ok else " (기대와 다름!)", len(consents)))
        if not admin_ok:
            missing += 1

    others = [u for u in db.scalars(select(User)).all() if not _is_staging_account(u)]
    print("\n스테이징이 아닌 계정: {}개{}".format(
        len(others), "  ← 운영 DB 일 수 있습니다" if others else ""))
    return 1 if missing else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="스테이징 검증용 계정만 만든다")
    parser.add_argument("--check", action="store_true", help="만들지 않고 상태만 본다")
    parser.add_argument("--allow-existing-users", action="store_true",
                        help="스테이징이 아닌 계정이 있어도 진행한다")
    args = parser.parse_args(argv)

    run_migrations()
    with SessionLocal() as db:
        if args.check:
            return check(db)

        report = seed(db, allow_existing=args.allow_existing_users)
        for row in report:
            print("{}  {}  지문 {}".format(
                "만듦  " if row["created"] else "이미 있음", row["email"], row["fingerprint"]))
        print("\n비밀번호는 출력하지 않습니다. {} 에 있습니다.".format(
            staging_secret.SECRET_PATH.name))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
