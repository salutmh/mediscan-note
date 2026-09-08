"""
케이스 삭제 (운영/개발 정리용).

케이스를 지우면 그 케이스에 달린 **제출 이력과 slice 도 함께 사라진다.** 그래서 기본은
dry-run 이고, 무엇이 지워지는지 먼저 보여준 뒤 --yes 를 줘야 실제로 지운다.

쓰는 곳
------
  - 합성 fixture 케이스(CXR-000x)를 서비스 DB 에서 걷어낼 때
  - 잘못 등록한 케이스를 다시 넣기 전에 정리할 때

사용법
------
    cd backend
    python -m scripts.remove_cases --case-ids CXR-0001 CXR-0002        # 미리보기
    python -m scripts.remove_cases --body-part chest_xray --yes        # 실제 삭제
    python -m scripts.remove_cases --all --yes --purge-files           # 전부 + static 파일까지

--purge-files 를 주면 static/cases/<case_id>/ 폴더도 지운다 (import 로 복사된 자산).
"""
import argparse
import shutil
import sys
from pathlib import Path

from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db import SessionLocal  # noqa: E402
from app.models import Case, CaseSlice, Submission  # noqa: E402
from app.static_files import STATIC_DIR  # noqa: E402

CASES_DIR = STATIC_DIR / "cases"


def _selected(db, case_ids, body_part, select_all) -> list[Case]:
    stmt = select(Case).order_by(Case.case_id)
    if case_ids:
        stmt = stmt.where(Case.case_id.in_(case_ids))
    elif body_part:
        stmt = stmt.where(Case.body_part == body_part)
    elif not select_all:
        return []
    return list(db.scalars(stmt).all())


def main() -> int:
    parser = argparse.ArgumentParser(description="케이스와 그에 딸린 제출 이력/slice 를 지운다.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--case-ids", nargs="+", help="지울 case_id 목록")
    group.add_argument("--body-part", help="해당 부위의 케이스를 전부 지운다 (예: chest_xray)")
    group.add_argument("--all", action="store_true", help="모든 케이스를 지운다")
    parser.add_argument("--yes", action="store_true", help="실제로 삭제 (없으면 미리보기만)")
    parser.add_argument(
        "--purge-files", action="store_true", help="static/cases/<case_id>/ 자산 폴더도 삭제"
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        cases = _selected(db, args.case_ids, args.body_part, args.all)
        if not cases:
            print("조건에 맞는 케이스가 없습니다.")
            return 0

        total_submissions = 0
        total_slices = 0
        print("삭제 대상:")
        for case in cases:
            submissions = db.scalars(
                select(Submission).where(Submission.case_id == case.case_id)
            ).all()
            slices = db.scalars(select(CaseSlice).where(CaseSlice.case_id == case.case_id)).all()
            total_submissions += len(submissions)
            total_slices += len(slices)
            print(
                f"  {case.case_id}  ({case.body_part}/{case.disease}) "
                f"제출 {len(submissions)}건, slice {len(slices)}개"
            )

        print(f"\n합계: 케이스 {len(cases)} / 제출 {total_submissions} / slice {total_slices}")
        if not args.yes:
            print("미리보기입니다. 실제로 지우려면 --yes 를 붙이세요.")
            return 0

        for case in cases:
            for submission in db.scalars(
                select(Submission).where(Submission.case_id == case.case_id)
            ).all():
                db.delete(submission)
            for case_slice in db.scalars(
                select(CaseSlice).where(CaseSlice.case_id == case.case_id)
            ).all():
                db.delete(case_slice)
            db.delete(case)
        db.commit()
        print("DB 삭제 완료.")

        if args.purge_files:
            for case in cases:
                folder = CASES_DIR / case.case_id
                if folder.exists():
                    shutil.rmtree(folder)
                    print(f"  자산 삭제: {folder}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
