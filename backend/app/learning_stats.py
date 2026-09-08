"""
학습 지표 집계 — "학습이 실제로 일어나는가"를 본다.

기록은 app/analytics.py 가 하고, 여기서는 **읽어서 요약만** 한다 (DB 를 바꾸지 않는다).

**개인 단위로 보지 않는다.** 집계만 만들고 user_id 는 세는 데만 쓴다 —
누가 무엇을 틀렸는지 들여다보는 도구가 아니다.

CLI(`scripts/learning_report.py`)와 운영자 API(`GET /api/admin/learning-summary`)가
**같은 함수를 쓴다.** 두 곳에서 따로 계산하면 숫자가 갈라진다.
"""
import statistics

from app import analytics
from app.models import LearningEvent


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
