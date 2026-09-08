"""
케이스 시드 — mock_data 의 JSON 을 DB(cases 테이블)로 옮긴다.

**mock_data 는 합성 자리표시자이지 서비스 콘텐츠가 아니다.**
실제 서비스 케이스는 scripts/import_cases.py 로만 등록한다 (뇌 MRI VS-SEG).
그래서 이 시드는 기본적으로 **꺼져 있고**, MEDISCAN_SEED_MOCK_CASES=1 일 때만 동작한다
(테스트 conftest 가 켠다). 이렇게 해두면 개발 DB 에 합성 케이스가 슬쩍 섞이지 않는다.

**운영 규칙 (MVP)**
판독훈련 채점 기준은 케이스에 등록된 reference mask 하나뿐이다. 따라서
**팀에서 검수를 마친 마스크만 케이스로 등록한다.** 검수되지 않은 마스크나
모델이 자동 생성한 마스크를 기준으로 올리면 학습자가 잘못된 기준으로 평가받는다.
기준 마스크가 없는 케이스는 목록에는 보이지만 `gradable: false` 로 내려가고 제출이 막힌다
(api-spec.md v0.4, 2-2/2-3).

이미 있는 case_id 는 건드리지 않는다(사용자 제출 이력이 붙어 있으므로).
**실제 케이스를 추가할 때 이 파일을 고치지 않는다** — scripts/import_cases.py 를 쓴다.
"""
import json
import logging
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Case

logger = logging.getLogger(__name__)

MOCK_DIR = Path(__file__).resolve().parent / "mock_data"

# 개발 전용 좌표 근사 채점(grading.py, MEDISCAN_ALLOW_APPROX_GRADING=1)이 쓰는 기준 영역.
# 합성 픽스처 영상의 병변 위치에 맞춘 값이며, 실제 케이스는 기준 마스크로 채점하므로 쓰지 않는다.
REFERENCE_SHAPES: dict[str, dict] = {
    "VS-SEG-202": {"cx": 338, "cy": 307, "r": 32},
    "VS-SEG-115": {"cx": 215, "cy": 282, "r": 26},
}


def _static(path: str | None) -> str | None:
    """mock JSON 의 "/images/x.png" 를 백엔드가 서빙하는 "/static/images/x.png" 로 옮긴다."""
    if not path:
        return None
    if path.startswith("/static/"):
        return path
    return "/static" + (path if path.startswith("/") else "/" + path)


def _load(filename: str) -> dict | None:
    path = MOCK_DIR / filename
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


MOCK_SEED_ENV = "MEDISCAN_SEED_MOCK_CASES"


def mock_seeding_enabled() -> bool:
    """합성 mock 케이스를 DB 에 넣을지. 기본은 끔 (실데이터만 서비스 DB 에 둔다)."""
    return os.getenv(MOCK_SEED_ENV, "").strip() in {"1", "true", "True"}


def seed_cases(db: Session) -> int:
    """추가된 케이스 수를 반환."""
    if not mock_seeding_enabled():
        logger.info(
            "합성 mock 케이스 시드를 건너뜁니다 (%s 미설정). "
            "실제 케이스는 scripts/import_cases.py 로 등록하세요.",
            MOCK_SEED_ENV,
        )
        _warn_missing_reference_masks(db)
        return 0

    listing = _load("cases.json") or {"cases": []}

    # 상세(image_url, image_meta)는 case_<번호>.json 에 따로 있다 — 있으면 합쳐서 넣는다.
    details: dict[str, dict] = {}
    for path in MOCK_DIR.glob("case_*.json"):
        detail = json.loads(path.read_text(encoding="utf-8"))
        if detail.get("case_id"):
            details[detail["case_id"]] = detail

    # 해설(explanation)은 submit_<번호>.json 예시에서 가져온다.
    explanations: dict[str, dict] = {}
    for path in MOCK_DIR.glob("submit_*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("case_id") and payload.get("explanation"):
            explanations[payload["case_id"]] = payload["explanation"]

    existing = set(db.scalars(select(Case.case_id)).all())
    added = 0

    for row in listing.get("cases", []):
        case_id = row["case_id"]
        if case_id in existing:
            continue
        detail = details.get(case_id, {})
        number = case_id.split("-")[-1]
        # 픽스처끼리는 202 해설(case_facts)을 공유한다 — 실제 케이스는 import_cases 가 따로 넣는다
        explanation = explanations.get(case_id) or next(iter(explanations.values()), None)
        db.add(
            Case(
                case_id=case_id,
                body_part=row["body_part"],
                disease=row["disease"],
                thumbnail_url=_static(row.get("thumbnail_url")),
                image_url=_static(detail.get("image_url")),
                image_meta=detail.get("image_meta"),
                reference_mask_url=f"/static/results/{number}_mask.png",
                reference_shape=REFERENCE_SHAPES.get(case_id),
                explanation=explanation,
            )
        )
        added += 1

    if added:
        db.commit()

    _warn_missing_reference_masks(db)
    return added


def _warn_missing_reference_masks(db: Session) -> None:
    """기준 마스크 파일이 실제로 있는지 확인하고, 없으면 경고를 남긴다.

    없다고 시드를 막지는 않는다 (케이스 자체는 목록에 보여야 하고, 채점만 막힌다).
    """
    from app.static_files import resolve_local_path

    for case in db.scalars(select(Case)).all():
        if resolve_local_path(case.reference_mask_url) is None:
            logger.warning(
                "기준 마스크가 없어 채점 불가 상태입니다 (case_id=%s, path=%s). "
                "검수 완료된 마스크를 backend/app/static/results/ 에 넣어주세요.",
                case.case_id,
                case.reference_mask_url,
            )
