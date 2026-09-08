"""
ROI 채점 (API 계약 v0.4).

**채점 기준은 전문가 검수 reference mask 하나뿐이다.**
AI 예측 마스크는 채점에 일절 관여하지 않는다 — 모델은 완벽하지 않으므로(뇌 MRI 기준 10명 중 8명 검출)
학습자를 모델 예측에 맞춰 채점하면 잘못된 피드백을 준다. 모델 결과는 `ai_prediction` 에
참고 정보로만 실린다.

기준 마스크가 없으면 **채점하지 않는다** (NotGradable 예외 -> 라우터가 422 로 변환, 제출 이력도 남기지 않음).
좌표 근사 채점은 개발용으로만 남겨두고 MEDISCAN_ALLOW_APPROX_GRADING=1 일 때만 동작하며,
그 경우 응답에 is_provisional=True 가 붙어 화면에서 경고로 표시된다.

제출 마스크는 보정하지 않는다. (v0.2 의 fill_holes 자동 보정은 윤곽선만 그린 ROI 를 과도하게
후하게 채점할 수 있어 제거했다. masks.fill_holes 는 향후 contour 도구용으로 남아 있다.)
"""
import logging
import math
import os
from pathlib import Path

from app import explanations, inference, masks, model_predictions
from app.static_files import resolve_local_path

logger = logging.getLogger(__name__)

# 판정 임계값 (Dice 기준) — 팀 논의로 조정 가능
MATCH_DICE = 0.60
PARTIAL_DICE = 0.15

METHOD_REFERENCE = "reference_mask"
METHOD_APPROX = "coordinate_approx"


def _approx_allowed() -> bool:
    """좌표 근사 채점은 개발 환경에서만. 일반 UI 흐름에서는 쓰지 않는다."""
    return os.getenv("MEDISCAN_ALLOW_APPROX_GRADING", "").strip() in {"1", "true", "True"}


class NotGradable(Exception):
    """기준 마스크가 없어 채점할 수 없음 -> 422 CASE_NOT_GRADABLE."""


class InvalidRoi(Exception):
    """ROI 가 비었거나 마스크를 읽을 수 없음 -> 400 INVALID_ROI."""


def _grade_from_dice(dice: float) -> str:
    if dice >= MATCH_DICE:
        return "match"
    if dice >= PARTIAL_DICE:
        return "partial_match"
    return "mismatch"


# ------------------------------------------------------------- 기준 마스크
def reference_mask_path(case) -> Path | None:
    """케이스에 등록된 전문가 검수 기준 마스크의 로컬 경로. 없으면 None."""
    return resolve_local_path(case.reference_mask_url)


def is_gradable(case) -> bool:
    """기준 마스크가 실제로 존재해야 채점 가능하다."""
    return reference_mask_path(case) is not None


def _load_reference(case):
    path = reference_mask_path(case)
    if path is None:
        return None
    try:
        mask = masks.from_path(path)
    except masks.MaskError:
        logger.warning("기준 마스크를 읽지 못함: %s", case.reference_mask_url)
        return None
    return mask if mask.any() else None


# --------------------------------------------------- AI 예측 (참고 정보 전용)
def ai_prediction(case, reference_mask=None) -> dict | None:
    """모델 참고 정보. **채점에는 절대 쓰이지 않는다.**

    두 경로가 있다:
      1. 미리 계산된 sidecar (뇌 MRI 처럼 volume 입력 + 무거운 모델) — scripts/run_model_predictions.py
      2. 요청 시 2D 추론 (가벼운 slice 단위 모델) — models/<부위>/inference.py 의 predict()

    실패해도 예외를 밖으로 내보내지 않는다 — 참고 정보가 없다고 채점이 막히면 안 된다.
    """
    precomputed = model_predictions.load(case.case_id)
    if precomputed is not None:
        return precomputed

    if not inference.is_available(case.body_part):
        return None

    module = inference.get_module(case.body_part)
    # volume 입력 모델은 slice PNG 로 부르면 안 된다 (학습 때와 다른 입력이 된다)
    if getattr(module, "INPUT_KIND", "image") == "volume":
        logger.debug("volume 입력 모델이라 요청 시 추론을 건너뜁니다: %s", case.body_part)
        return None

    image_path = resolve_local_path(case.image_url)
    if image_path is None:
        return None

    try:
        prediction = module.predict(
            str(image_path),
            reference_mask_path=str(reference_mask_path(case) or ""),
        )
    except Exception:
        logger.exception("모델 추론 실패 (참고 정보 생략): %s", case.case_id)
        return None

    if not isinstance(prediction, dict):
        return None

    dice_vs_reference = prediction.get("dice")
    if dice_vs_reference is None and reference_mask is not None and prediction.get("mask_path"):
        try:
            predicted = masks.from_path(prediction["mask_path"])
            dice_vs_reference = masks.dice_iou(predicted, reference_mask)[0]
        except masks.MaskError:
            dice_vs_reference = None

    return {
        "model_version": prediction.get("model_version")
        or getattr(module, "MODEL_VERSION", None)
        or f"{case.body_part}-model",
        # 모델 출력 마스크는 아직 정적 서빙 대상이 아니라 URL 이 없다 (models/<부위>/outputs/ 에만 존재)
        "mask_url": prediction.get("mask_url"),
        "dice_vs_reference": round(dice_vs_reference, 4) if dice_vs_reference is not None else None,
    }


# ------------------------------------------------ 개발용 좌표 근사 (폴백 아님)
def _fit_circle(points):
    valid = [p for p in points if isinstance(p, (list, tuple)) and len(p) >= 2]
    if not valid:
        return None
    xs = [float(p[0]) for p in valid]
    ys = [float(p[1]) for p in valid]
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    spread = max((math.hypot(x - cx, y - cy) for x, y in zip(xs, ys)), default=0.0)
    return cx, cy, max(spread, 8.0)


def _circle_overlap_area(r1: float, r2: float, d: float) -> float:
    if d >= r1 + r2:
        return 0.0
    if d <= abs(r1 - r2):
        return math.pi * min(r1, r2) ** 2
    a1 = r1**2 * math.acos((d**2 + r1**2 - r2**2) / (2 * d * r1))
    a2 = r2**2 * math.acos((d**2 + r2**2 - r1**2) / (2 * d * r2))
    a3 = 0.5 * math.sqrt(max(0.0, (-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2)))
    return a1 + a2 - a3


def _grade_by_points(case, roi: dict) -> dict:
    """개발 전용. 기준 영역(중심·반지름)과 사용자 좌표를 원으로 근사한다."""
    reference = case.reference_shape or {}
    fitted = _fit_circle(roi.get("points") or [])
    ref_cx, ref_cy, ref_r = reference.get("cx"), reference.get("cy"), reference.get("r")

    if fitted is None or ref_cx is None or ref_r is None:
        raise NotGradable("기준 영역 정보가 없어 근사 채점도 할 수 없습니다.")

    cx, cy, r = fitted
    d = math.hypot(cx - float(ref_cx), cy - float(ref_cy))
    inter = _circle_overlap_area(r, float(ref_r), d)
    area_sum = math.pi * r**2 + math.pi * float(ref_r) ** 2
    union = area_sum - inter
    dice = (2 * inter / area_sum) if area_sum > 0 else 0.0
    iou = (inter / union) if union > 0 else 0.0
    score = int(max(0.0, min(100.0, 100.0 * (1.0 - (d - float(ref_r)) / (2.0 * float(ref_r))))))

    return {
        "grade": _grade_from_dice(dice),
        "dice": round(dice, 4),
        "iou": round(iou, 4),
        "location_score": score,
        "reference_mask_url": case.reference_mask_url,
        "evaluation": {"method": METHOD_APPROX, "is_provisional": True},
        "ai_prediction": None,
        "explanation": explanations.build(case),
    }


# ---------------------------------------------------------------- 진입점
def evaluate_submission(case, roi: dict) -> dict:
    """api-spec.md 2-3 의 응답 본문(case_id 제외)을 만든다.

    raises:
        NotGradable — 기준 마스크 없음 (라우터가 422 로 변환)
        InvalidRoi  — ROI 가 비었거나 마스크를 읽을 수 없음 (라우터가 400 으로 변환)
    """
    reference = _load_reference(case)

    if reference is None:
        if _approx_allowed():
            logger.warning("기준 마스크 없음 -> 개발용 근사 채점 (case=%s)", case.case_id)
            return _grade_by_points(case, roi)
        raise NotGradable("이 케이스는 채점 기준(기준 마스크)이 아직 등록되지 않았습니다.")

    raw = roi.get("mask_png_base64")
    if not raw:
        raise InvalidRoi("표시한 영역(mask_png_base64)이 필요합니다.")
    try:
        user_mask = masks.from_base64(raw)
    except masks.MaskError as exc:
        raise InvalidRoi(f"표시한 영역을 읽을 수 없습니다: {exc}") from exc
    if not user_mask.any():
        raise InvalidRoi("표시한 영역이 비어 있습니다.")

    # 보정 없이 그대로 비교한다 (fill_holes 미적용)
    dice, iou = masks.dice_iou(user_mask, reference)
    score = masks.location_score(user_mask, reference)

    return {
        "grade": _grade_from_dice(dice),
        "dice": round(dice, 4),
        "iou": round(iou, 4),
        "location_score": score,
        "reference_mask_url": case.reference_mask_url,
        "evaluation": {"method": METHOD_REFERENCE, "is_provisional": False},
        "ai_prediction": ai_prediction(case, reference),
        "explanation": explanations.build(case),
    }
