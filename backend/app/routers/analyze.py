"""
사용자 의료영상 AI 분석 (2번째 트랙) — api-spec.md 2-6.

보안·프라이버시 규칙:
- 로그인 필요 (api-spec 0절)
- 업로드는 `agree_sensitive_data` 동의를 받은 사용자만 (서버가 동의 이력으로 실제 확인 → 403)
- **업로드 영상은 저장하지 않는다.** 메모리에서만 처리하고 EXIF 등 메타데이터를 제거한다
  (의료영상 메타데이터에 환자 식별정보가 남아 있을 수 있다) — app/uploads.py
- 크기·포맷·손상 여부·픽셀 수·region 좌표를 **서버에서** 검증한다. 클라이언트 검사는 UX 용이다.

모델 연결 상태 (v0.4)
--------------------
**기본값은 "모델 미연결"이다.** 예전에는 고정 mock 이 `suspected_region` / `key_findings` /
`candidate_diseases` 를 지어내 내려보냈는데, 그건 사용자가 올린 영상을 실제로 분석한 결과처럼
보이는 **검증되지 않은 의학적 출력**이라 제거했다.

뇌 MRI 모델(VS_Seg)은 3D ceT1 **volume** 입력이라 업로드된 PNG/JPEG 한 장으로는 추론할 수 없다.
학습 때와 다른 입력을 넣으면 조용히 틀린 결과가 나온다. 그래서 지금은 검증만 하고
`status: "model_unavailable"` 을 돌려준다.

2D 입력을 지원하는 부위 모델이 생기면 자동으로 연결된다:
    models/<부위>/inference.py 에 predict_image(image, region=None) -> dict 를 두면 된다.
    **파일로 저장하지 않고 PIL 이미지 객체를 그대로 넘긴다** (업로드 미저장 규칙 유지).

발표·데모용으로 예전 예시 응답이 필요하면 MEDISCAN_ANALYZE_DEMO=1 로 켠다.
그때는 `status: "demo"` + `is_demo: true` 가 붙어 실제 분석이 아님이 응답에 남는다.
"""
import logging
import os

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app import inference
from app.deps import CurrentUser, DbSession
from app.models import Consent
from app.static_files import absolute_url
from app.uploads import UploadError, decode_image, validate_region

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analyze", tags=["analyze"])

DISCLAIMER = "본 결과는 학습 참고용 AI 분석이며 확정 진단이 아닙니다."
DEMO_ENV = "MEDISCAN_ANALYZE_DEMO"
DEFAULT_BODY_PART = "brain_mri"


def _demo_enabled() -> bool:
    return os.getenv(DEMO_ENV, "").strip() in {"1", "true", "True"}


def _demo_response() -> dict:
    """발표·화면 확인용 예시. **실제 분석 결과가 아니다** — 응답에 그렇게 표시된다."""
    return {
        "status": "demo",
        "is_demo": True,
        "model_version": "demo-example",
        "ai_mask_url": absolute_url("/static/results/upload_001_mask.png"),
        "suspected_region": "우측 소뇌교각",
        "key_findings": "경계가 명확한 조영증강 병변",
        "candidate_diseases": [
            {"name": "전정신경초종", "probability": 0.78},
            {"name": "수막종", "probability": 0.12},
        ],
        "unavailable_reason": None,
        "disclaimer": (
            "이것은 화면 확인용 **예시 데이터**이며 업로드한 영상을 분석한 결과가 아닙니다. "
            + DISCLAIMER
        ),
    }


def _unavailable_response(reason: str) -> dict:
    """모델이 없을 때. 지어낸 소견 대신 사실을 돌려준다."""
    return {
        "status": "model_unavailable",
        "is_demo": False,
        "model_version": None,
        "ai_mask_url": None,
        "suspected_region": "",
        "key_findings": "",
        "candidate_diseases": [],
        "unavailable_reason": reason,
        "disclaimer": DISCLAIMER,
    }


def _analyze_with_model(body_part: str, image, region):
    """2D 입력을 지원하는 부위 모델이 있으면 그것으로 분석한다.

    **이미지를 파일로 저장하지 않는다** — PIL 객체를 그대로 넘긴다 (업로드 미저장 규칙).
    """
    module = inference.get_module(body_part)
    if module is None:
        return None, f"추론 모듈 없음: {body_part}"
    if getattr(module, "INPUT_KIND", "image") == "volume":
        return None, (
            "이 부위 모델은 volume(연속 슬라이스) 입력 전용이라 업로드한 이미지 한 장으로는 "
            "분석할 수 없습니다. 학습 때와 다른 입력을 넣으면 잘못된 결과가 나옵니다."
        )
    if not inference.is_available(body_part):
        return None, inference.unavailable_reason(body_part) or "모델이 준비되지 않음"

    predict_image = getattr(module, "predict_image", None)
    if not callable(predict_image):
        return None, "이 부위 모델은 업로드 이미지 분석(predict_image)을 지원하지 않습니다."

    try:
        result = predict_image(image, region=region)
    except Exception:
        logger.exception("업로드 영상 추론 실패: %s", body_part)
        return None, "분석 중 오류가 발생했습니다."
    if not isinstance(result, dict):
        return None, "모델이 올바른 결과를 돌려주지 않았습니다."
    return result, None


def _error(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"error": True, "code": code, "message": message, **extra},
    )


def _has_sensitive_data_consent(db: DbSession, user_id: str) -> bool:
    """가장 최근에 기록된 agree_sensitive_data 동의 값을 본다 (동의 이력은 append 방식)."""
    latest = db.scalar(
        select(Consent)
        .where(Consent.user_id == user_id, Consent.key == "agree_sensitive_data")
        .order_by(Consent.agreed_at.desc(), Consent.id.desc())
        .limit(1)
    )
    return bool(latest and latest.agreed)


@router.post("")
def analyze(payload: dict, user: CurrentUser, db: DbSession):
    if not _has_sensitive_data_consent(db, user.user_id):
        raise _error(
            403,
            "CONSENT_REQUIRED",
            "의료영상 등 민감정보 처리 동의가 필요합니다.",
            missing=["agree_sensitive_data"],
        )

    if not isinstance(payload, dict):
        raise _error(400, "IMAGE_REQUIRED", "분석할 영상(image_base64)이 필요합니다.")

    try:
        # 검증 + 메타데이터 제거. 여기서 나온 image 는 메모리에만 존재하며 저장하지 않는다.
        image = decode_image(payload.get("image_base64"))
        region = validate_region(payload.get("region"), image.width, image.height)
    except UploadError as exc:
        raise _error(exc.status, exc.code, exc.message) from exc

    body_part = payload.get("body_part") or DEFAULT_BODY_PART
    result, reason = _analyze_with_model(body_part, image, region)
    if result is not None:
        return {
            "status": "ok",
            "is_demo": False,
            "unavailable_reason": None,
            "disclaimer": DISCLAIMER,
            **result,
        }

    if _demo_enabled():
        return _demo_response()
    return _unavailable_response(reason)
