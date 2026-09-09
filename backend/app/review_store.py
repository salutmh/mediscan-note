"""
케이스 후보 **기술 검수** 상태 저장소.

==========================================================================
**기술 검수는 의학적 검수가 아니다.**
==========================================================================
여기서 다루는 `technical_review_status` 는 "export 파이프라인이 제대로 돌았는가"
하나만 뜻한다. 구체적으로는:

  - 마스크가 영상 위에 정렬돼 있는가
  - 메타데이터(대표 slice·편측성)와 그림이 맞는가
  - ROI 가 종양 구조인가
  - 학습 자료로 쓸 만한 화질인가

`TECH_PASS` 는 **다음 중 어느 것도 뜻하지 않는다**:
  ✗ 의학적으로 옳다
  ✗ 전문가 검수가 끝났다
  ✗ 서비스에 올려도 된다

그래서 상태를 **셋으로 분리**한다. 하나로 합치면 "검수 완료"라는 말이 어느 층위의
검수인지 알 수 없게 되고, 결국 검수되지 않은 GT 가 학습자의 채점 기준이 된다.

  technical_review_status   파이프라인이 제대로 돌았는가        (이 파일에서 사람이 정한다)
  expert_review_status      의학적으로 옳은가                  (전문가만, 기본 pending)
  activation_status         서비스에 노출되는가                (둘 다 끝나야 후보가 된다)

**activation 은 이 모듈에서 바꿀 수 없다.** 값을 읽고 보여줄 뿐이고,
전문가 검수가 끝나지 않은 케이스는 어떤 경로로도 자동 활성화되지 않는다.

저장 위치
--------
`<review_root>/review_results.json` — 후보는 아직 DB 케이스가 아니라 `data/` 안의
파일이므로 DB 가 아니라 파일에 남긴다. `data/` 는 gitignore 다(실제 의료영상 파생물).

쓰기는 **임시 파일 + 교체**로 한다. 검수 도중 중단돼도 이전 결과가 깨지지 않아야 한다.
"""
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------- 상태 값
# 기술 검수 — 사람이 오버레이 시트를 보고 정한다
TECH_UNREVIEWED = "unreviewed"
TECH_PASS = "tech_pass"
TECH_HOLD = "hold"
TECH_REJECT = "reject_tech"

TECHNICAL_STATUSES = (TECH_UNREVIEWED, TECH_PASS, TECH_HOLD, TECH_REJECT)

TECHNICAL_MEANING = {
    TECH_UNREVIEWED: "아직 보지 않았다",
    TECH_PASS: "export 상태가 정상이다 (의학적 판단 아님)",
    TECH_HOLD: "영상·마스크 정렬이나 export 상태를 다시 확인해야 한다",
    TECH_REJECT: "기술적인 이유로 후보에서 제외한다",
}

# 전문가 검수 — 이 화면에서는 **바꿀 수 없다**. 전문가가 별도로 판단한다.
EXPERT_PENDING = "pending"
EXPERT_IN_REVIEW = "in_review"
EXPERT_APPROVED = "approved"
EXPERT_REJECTED = "rejected"

EXPERT_STATUSES = (EXPERT_PENDING, EXPERT_IN_REVIEW, EXPERT_APPROVED, EXPERT_REJECTED)

# 활성화 — 두 검수가 모두 끝나야 후보가 된다. 이 모듈은 읽기만 한다.
ACTIVATION_CANDIDATE = "candidate"          # 아직 후보
ACTIVATION_INACTIVE_READY = "inactive_ready"  # 등록은 됐지만 비활성
ACTIVATION_ACTIVE = "active"                # 학습자에게 보인다

RESULTS_FILENAME = "review_results.json"
SCHEMA_VERSION = 1


class ReviewStoreError(RuntimeError):
    """검수 결과를 읽거나 쓸 수 없을 때."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def results_path(review_root: Path) -> Path:
    return Path(review_root) / RESULTS_FILENAME


def load(review_root: Path) -> dict:
    """저장된 검수 결과. 없으면 빈 구조를 돌려준다 (파일이 없는 것은 오류가 아니다)."""
    path = results_path(review_root)
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "cases": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        # 깨진 파일을 조용히 빈 값으로 덮으면 그때까지의 검수가 사라진다.
        raise ReviewStoreError(
            f"검수 결과 파일을 읽을 수 없습니다: {path} ({exc}). "
            "파일을 직접 확인하세요 — 덮어쓰지 않았습니다."
        ) from exc
    if not isinstance(data, dict) or "cases" not in data:
        raise ReviewStoreError(f"검수 결과 파일 형식이 예상과 다릅니다: {path}")
    return data


def save(review_root: Path, data: dict) -> Path:
    """임시 파일에 쓴 뒤 교체한다. 중간에 끊겨도 이전 결과가 남는다."""
    root = Path(review_root)
    root.mkdir(parents=True, exist_ok=True)
    path = results_path(root)

    payload = json.dumps(data, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(dir=str(root), prefix=".review_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload + "\n")
        os.replace(tmp_name, path)  # 같은 볼륨 안이라 원자적이다
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return path


def default_entry(case_id: str) -> dict:
    """아직 검수하지 않은 케이스의 기본 상태.

    **전문가 검수는 항상 pending 으로 시작한다.** 기술 검수 결과와 무관하다.
    """
    return {
        "case_id": case_id,
        "technical_review_status": TECH_UNREVIEWED,
        "expert_review_status": EXPERT_PENDING,
        "activation_status": ACTIVATION_CANDIDATE,
        "note": "",
        "reviewed_at": None,
        "reviewer": None,
    }


def get_entry(data: dict, case_id: str) -> dict:
    entry = data.get("cases", {}).get(case_id)
    if entry is None:
        return default_entry(case_id)
    merged = default_entry(case_id)
    merged.update(entry)
    merged["case_id"] = case_id
    return merged


def set_technical_status(
    review_root: Path,
    case_id: str,
    *,
    status: str,
    note: str = "",
    reviewer: str | None = None,
) -> dict:
    """기술 검수 결과를 기록한다.

    **전문가 검수 상태와 활성화 상태는 건드리지 않는다.** 기술 검수가 통과했다고
    의학적 검수가 진행되거나 케이스가 활성화되면 안 된다.
    """
    if status not in TECHNICAL_STATUSES:
        raise ReviewStoreError(
            f"알 수 없는 기술 검수 상태: {status!r} (가능: {', '.join(TECHNICAL_STATUSES)})"
        )

    data = load(review_root)
    cases = data.setdefault("cases", {})
    entry = get_entry(data, case_id)

    entry["technical_review_status"] = status
    entry["note"] = (note or "").strip()[:500]
    entry["reviewer"] = (reviewer or "local reviewer").strip()[:80]
    entry["reviewed_at"] = None if status == TECH_UNREVIEWED else _now()
    # 아래 둘은 의도적으로 그대로 둔다 (기술 검수가 바꿀 수 있는 값이 아니다)
    entry.setdefault("expert_review_status", EXPERT_PENDING)
    entry.setdefault("activation_status", ACTIVATION_CANDIDATE)

    cases[case_id] = entry
    data["schema_version"] = SCHEMA_VERSION
    data["updated_at"] = _now()
    save(review_root, data)
    return entry


def counts(entries: list[dict]) -> dict:
    """진행 현황. 기술/전문가 검수를 **따로** 센다."""
    by_tech = {status: 0 for status in TECHNICAL_STATUSES}
    by_expert = {status: 0 for status in EXPERT_STATUSES}
    for entry in entries:
        tech = entry.get("technical_review_status", TECH_UNREVIEWED)
        expert = entry.get("expert_review_status", EXPERT_PENDING)
        if tech in by_tech:
            by_tech[tech] += 1
        if expert in by_expert:
            by_expert[expert] += 1
    return {
        "total": len(entries),
        "technical": by_tech,
        "expert": by_expert,
        # 화면 상단에 크게 보여줄 값 — "기술 통과했지만 전문가 검수가 남은" 수
        "awaiting_expert_review": sum(
            1
            for e in entries
            if e.get("technical_review_status") == TECH_PASS
            and e.get("expert_review_status") == EXPERT_PENDING
        ),
    }
