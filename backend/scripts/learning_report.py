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
import statistics
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app import analytics  # noqa: E402
from app.db import SessionLocal, run_migrations  # noqa: E402
from app.models import LearningEvent  # noqa: E402


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def build_report(events: list[LearningEvent]) -> dict:
    opened = [e for e in events if e.event == analytics.CASE_OPENED]
    graded = [e for e in events if e.event == analytics.SUBMISSION_GRADED]

    # 전환율은 "(사용자, 케이스)" 쌍 기준이다. 한 사람이 같은 케이스를 여러 번 열어도 1로 센다.
    opened_pairs = {(e.user_id, e.case_id) for e in opened}
    graded_pairs = {(e.user_id, e.case_id) for e in graded}
    converted = opened_pairs & graded_pairs

    first_attempts = [e for e in graded if e.attempt_number == 1 and e.dice is not None]
    retries = [e for e in graded if (e.attempt_number or 1) > 1 and e.dice is not None]

    # 같은 (사용자, 케이스)에서 1회차 -> 최종회차 점수 변화
    by_pair: dict = {}
    for event in graded:
        if event.dice is None:
            continue
        by_pair.setdefault((event.user_id, event.case_id), []).append(event)
    improvements = []
    for attempts in by_pair.values():
        if len(attempts) < 2:
            continue
        ordered = sorted(attempts, key=lambda e: (e.attempt_number or 0, e.id))
        improvements.append(ordered[-1].dice - ordered[0].dice)

    durations = [e.duration_seconds for e in graded if e.duration_seconds is not None]

    per_case: dict = {}
    for event in graded:
        row = per_case.setdefault(
            event.case_id, {"attempts": 0, "first_attempts": 0, "first_match": 0, "dices": []}
        )
        row["attempts"] += 1
        if event.dice is not None:
            row["dices"].append(event.dice)
        if event.attempt_number == 1:
            row["first_attempts"] += 1
            if event.grade == "match":
                row["first_match"] += 1

    return {
        "users_seen": len({e.user_id for e in events}),
        "events": len(events),
        "cases_opened": len(opened_pairs),
        "cases_submitted": len(graded_pairs),
        "start_to_submit_rate": (
            round(len(converted) / len(opened_pairs), 4) if opened_pairs else None
        ),
        "submissions": len(graded),
        "first_attempt_mean_dice": _mean([e.dice for e in first_attempts]),
        "retry_mean_dice": _mean([e.dice for e in retries]),
        "retry_count": len(retries),
        # 재도전한 (사용자, 케이스) 쌍의 첫 시도 대비 최종 점수 변화
        "mean_improvement": _mean(improvements),
        "improved_pairs": sum(1 for d in improvements if d > 0),
        "worsened_pairs": sum(1 for d in improvements if d < 0),
        "mean_duration_seconds": _mean(durations),
        "per_case": {
            case_id: {
                "attempts": row["attempts"],
                "first_attempt_match_rate": (
                    round(row["first_match"] / row["first_attempts"], 4)
                    if row["first_attempts"]
                    else None
                ),
                "mean_dice": _mean(row["dices"]),
            }
            for case_id, row in sorted(per_case.items(), key=lambda kv: str(kv[0]))
        },
    }


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
