"""
운영자 권한 부여/회수 (CLI 전용).

**왜 CLI 인가**
웹에서 스스로 관리자가 되는 경로를 만들지 않기 위해서다. 그런 엔드포인트는 하나만
잘못 열려도 아무나 콘텐츠를 바꿀 수 있게 된다. 최초 관리자는 서버에 접근할 수 있는
사람이 직접 지정한다.

사용법
------
    cd backend
    python -m scripts.grant_admin --email admin@example.com
    python -m scripts.grant_admin --email admin@example.com --revoke
    python -m scripts.grant_admin --list
"""
import argparse
import sys
from pathlib import Path

from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db import SessionLocal, run_migrations  # noqa: E402
from app.models import User  # noqa: E402


def _print_admins(db) -> None:
    admins = db.scalars(select(User).where(User.is_admin.is_(True)).order_by(User.user_id)).all()
    if not admins:
        print("운영자가 없습니다.")
        return
    print(f"운영자 {len(admins)}명:")
    for user in admins:
        # 식별에 필요한 최소 정보만 출력한다
        print(f"  - {user.user_id}  {user.email or f'(SNS:{user.provider})'}  {user.nickname}")


def main() -> int:
    parser = argparse.ArgumentParser(description="운영자 권한 부여/회수")
    parser.add_argument("--email", help="대상 사용자의 이메일")
    parser.add_argument("--user-id", help="이메일 대신 user_id 로 지정 (SNS 계정)")
    parser.add_argument("--revoke", action="store_true", help="권한을 회수한다")
    parser.add_argument("--list", action="store_true", help="현재 운영자 목록만 출력")
    args = parser.parse_args()

    # 스키마를 head 까지 올린 뒤 읽는다 (다른 스크립트와 동일한 보장)
    run_migrations()

    with SessionLocal() as db:
        if args.list:
            _print_admins(db)
            return 0

        if not args.email and not args.user_id:
            parser.error("--email 또는 --user-id 가 필요합니다 (--list 는 예외)")

        if args.email:
            user = db.scalar(select(User).where(User.email == args.email))
            label = args.email
        else:
            user = db.get(User, args.user_id)
            label = args.user_id

        if user is None:
            print(f"사용자를 찾을 수 없습니다: {label}")
            return 1

        target = not args.revoke
        if user.is_admin == target:
            print(f"이미 {'운영자입니다' if target else '일반 사용자입니다'}: {label}")
            return 0

        user.is_admin = target
        db.commit()
        print(f"{'운영자로 지정했습니다' if target else '운영자 권한을 회수했습니다'}: {label}")
        _print_admins(db)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
