"""
학습 지표 리포트 — Closed Beta 에서 "학습이 실제로 일어나는가"를 본다.

기록은 app/analytics.py 가 하고, 여기서는 **읽기만** 한다 (DB 변경 없음).

보는 것
------
  - 케이스 시작 -> 제출 전환율        열어보기만 하고 나가는 비율
  - 첫 시도 vs 재도전 점수 변화        학습 효과의 최소 신호
  - 케이스당 평균 소요시간
  - 케이스별 시도 횟수와 첫 시도 성공률

**개인 단위로 보지 않는다.** 집계만 출력하고 user_id 는 세는 데만 쓴다.
(누가 무엇을 틀렸는지 들여다보는 도구가 아니다.)

사용법
------
    cd backend
    python -m scripts.learning_report
    python -m scripts.learning_report --out data/learning_report.json
"""
import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, run_migrations  # noqa: E402
from app.learning_stats import build_report  # noqa: E402
from app.models import LearningEvent  # noqa: E402


def print_report(report: dict) -> None:
    if not report["events"]:
        print("아직 기록된 학습 이벤트가 없습니다.")
        print("(Closed Beta 사용자가 케이스를 열고 제출하면 쌓입니다.)")
        return

    print(f"사용자 {report['users_seen']}명 / 이벤트 {report['events']}건")
    print(
        f"케이스 시작 {report['cases_opened']} -> 제출 {report['cases_submitted']} "
        f"(전환율 {report['start_to_submit_rate']})"
    )
    print(f"제출 {report['submissions']}건 / 재도전 {report['retry_count']}건")
    print()
    print(f"첫 시도 평균 Dice: {report['first_attempt_mean_dice']}")
    print(f"재도전 평균 Dice:  {report['retry_mean_dice']}")
    print(
        f"첫 시도 대비 변화:  평균 {report['mean_improvement']} "
        f"(개선 {report['improved_pairs']} / 하락 {report['worsened_pairs']})"
    )
    print(f"평균 소요시간: {report['mean_duration_seconds']}초")
    rate = report["submit_to_explanation_rate"]
    print(
        "해설 열람: "
        + (
            f"{report['explanations_viewed']}건 (제출한 케이스의 {rate * 100:.0f}%)"
            if rate is not None
            else "아직 제출 기록이 없습니다"
        )
    )
    print()

    print("케이스별")
    print(f"  {'case_id':<16}{'시도':>6}{'첫시도 일치율':>14}{'평균 Dice':>12}")
    for case_id, row in report["per_case"].items():
        print(
            f"  {str(case_id):<16}{row['attempts']:>6}"
            f"{str(row['first_attempt_match_rate']):>14}{str(row['mean_dice']):>12}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="학습 지표 리포트 (읽기 전용)")
    parser.add_argument("--out", help="결과 JSON 저장 경로")
    args = parser.parse_args()

    run_migrations()
    with SessionLocal() as db:
        events = db.scalars(select(LearningEvent).order_by(LearningEvent.id)).all()
        report = build_report(events)

    print_report(report)
    print("\n※ 집계만 출력합니다. 개인 단위 학습 내용을 들여다보는 도구가 아닙니다.")

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"저장했습니다: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
