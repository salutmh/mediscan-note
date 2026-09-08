"""
공간 피드백 (spatial feedback) — "왜 틀렸는지"를 학습자에게 돌려준다.

**이 모듈이 존재하는 이유**
Dice 0.32 와 "부분 일치"만 보여주면 학습자는 무엇을 고쳐야 할지 모른다.
같은 0.32 라도 (a) 위치는 맞았는데 너무 작게 칠한 경우와 (b) 엉뚱한 곳을 칠한 경우는
완전히 다른 학습 상황이다. 그 둘을 구분해서 알려주는 것이 여기 역할이다.

==========================================================================
**절대 규칙: geometry 로 확인할 수 있는 것만 말한다.**
==========================================================================
두 마스크의 겹침·면적·중심 거리에서 계산되는 사실만 문장으로 만든다.
아래는 **여기서 절대 생성하지 않는다** (전문가가 쓴 `case_findings` 자리다):
  - 내이도 침범 여부, 조영증강 양상, 종괴 성상, 낭성 변화 같은 영상 소견
  - 질환 추정, 감별 진단, 임상적 의미
  - "이 부위는 ~이므로" 같은 해부학적 해석

우리는 의료인이 아니다. 위치가 겹쳤다는 것은 말할 수 있지만,
그 위치가 해부학적으로 무엇인지는 말할 수 없다.

**채점에 관여하지 않는다.** grade 는 기존대로 Dice 임계값으로만 정해지고,
여기 값들은 설명용으로만 응답에 붙는다.
"""
import math

import numpy as np

from app import masks

# ---------------------------------------------------------------- 판정 기준
# geometry 문구를 고르는 기준값. 채점 임계값(scoring_config)과는 별개다 —
# 이건 "어떤 조언을 보여줄지"이지 합격/불합격 선이 아니다.
COVERAGE_GOOD = 0.80          # 기준 영역을 이 이상 덮으면 충분히 덮은 것으로 본다
COVERAGE_PARTIAL = 0.40       # 이 아래면 "상당 부분을 놓쳤다"
PRECISION_GOOD = 0.70         # 칠한 것 중 이 이상이 기준 안이면 군더더기가 적다
PRECISION_LOW = 0.40          # 이 아래면 "기준 밖을 많이 칠했다"
AREA_RATIO_LARGE = 1.5        # 기준 대비 이 배 이상이면 넓게 칠한 것
AREA_RATIO_SMALL = 0.6        # 이 아래면 작게 칠한 것
CENTER_ON_TARGET = 1.0        # 중심 거리 <= 기준 반지름 * 1.0 이면 중심을 맞춘 것
CENTER_NEAR = 2.0             # 이 배수 안이면 "조금 벗어남", 넘으면 "크게 벗어남"
OVERLAP_NEGLIGIBLE = 0.05     # 겹침이 이 아래면 사실상 다른 곳을 칠한 것


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    return (numerator / denominator) if denominator > 0 else None


def compute_metrics(user_mask: np.ndarray, reference_mask: np.ndarray) -> dict:
    """겹침·면적·중심에서 나오는 값들. 전부 순수 geometry 다.

    - gt_coverage      기준 영역 중 사용자가 덮은 비율 (recall)
    - user_precision   사용자가 칠한 것 중 기준 안에 있는 비율 (precision)
    - area_ratio       사용자 면적 / 기준 면적
    - over/under_segmentation_ratio  기준 면적 대비 넘친 양 / 놓친 양
    - centroid_distance_px           두 중심 사이 거리
    - centroid_distance_normalized   기준 마스크 등가반지름으로 나눈 값 (크기 무관 비교용)
    """
    user = masks.align(user_mask, reference_mask.shape)

    intersection = float(np.logical_and(user, reference_mask).sum())
    user_area = float(user.sum())
    ref_area = float(reference_mask.sum())

    user_centroid = masks.centroid(user)
    ref_centroid = masks.centroid(reference_mask)
    ref_radius = masks.equivalent_radius(reference_mask)

    distance = None
    if user_centroid is not None and ref_centroid is not None:
        distance = math.hypot(
            user_centroid[0] - ref_centroid[0], user_centroid[1] - ref_centroid[1]
        )

    return {
        "gt_coverage": _round(_safe_ratio(intersection, ref_area)),
        "user_precision": _round(_safe_ratio(intersection, user_area)),
        "area_ratio": _round(_safe_ratio(user_area, ref_area)),
        "over_segmentation_ratio": _round(_safe_ratio(user_area - intersection, ref_area)),
        "under_segmentation_ratio": _round(_safe_ratio(ref_area - intersection, ref_area)),
        "centroid_distance_px": _round(distance, 1),
        "centroid_distance_normalized": _round(
            _safe_ratio(distance, ref_radius) if distance is not None else None
        ),
        "user_area_px": int(user_area),
        "reference_area_px": int(ref_area),
    }


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(value, digits) if value is not None else None


# ------------------------------------------------------------------ 문구 생성
# 각 항목은 (code, message). code 는 프론트가 아이콘·색을 고를 때 쓰고,
# message 는 그대로 보여줘도 되는 교육용 문장이다.
def _position_item(metrics: dict) -> tuple[str, str]:
    normalized = metrics.get("centroid_distance_normalized")
    coverage = metrics.get("gt_coverage") or 0.0

    if normalized is None:
        return ("POSITION_UNKNOWN", "표시한 영역의 위치를 계산할 수 없습니다.")
    if coverage <= OVERLAP_NEGLIGIBLE:
        return (
            "POSITION_OFF_TARGET",
            "표시한 영역이 기준 영역과 거의 겹치지 않습니다. 기준 영역의 위치부터 다시 확인해 보세요.",
        )
    if normalized <= CENTER_ON_TARGET:
        return ("POSITION_ON_TARGET", "표시한 영역의 중심 위치는 기준과 일치합니다.")
    if normalized <= CENTER_NEAR:
        return ("POSITION_NEAR", "표시한 영역의 중심이 기준에서 조금 벗어나 있습니다.")
    return ("POSITION_FAR", "표시한 영역의 중심이 기준에서 크게 벗어나 있습니다.")


def _extent_items(metrics: dict) -> list[tuple[str, str]]:
    """얼마나 덮었는지 / 얼마나 넘쳤는지. 둘 다 해당될 수 있다."""
    items: list[tuple[str, str]] = []
    coverage = metrics.get("gt_coverage")
    precision = metrics.get("user_precision")
    area_ratio = metrics.get("area_ratio")

    if coverage is not None and coverage > OVERLAP_NEGLIGIBLE:
        if coverage < COVERAGE_PARTIAL:
            items.append(
                ("UNDER_SEGMENTED", "기준 영역의 상당 부분을 표시하지 않았습니다. 범위를 더 넓게 확인해 보세요.")
            )
        elif coverage < COVERAGE_GOOD:
            items.append(("SLIGHTLY_UNDER_SEGMENTED", "기준 영역의 일부를 놓쳤습니다. 경계를 조금 더 확인해 보세요."))

    if precision is not None and precision < PRECISION_LOW:
        items.append(
            ("OVER_SEGMENTED", "기준 영역 밖을 많이 표시했습니다. 표시 범위를 좁혀 보세요.")
        )
    elif area_ratio is not None and area_ratio >= AREA_RATIO_LARGE:
        items.append(
            ("SLIGHTLY_OVER_SEGMENTED", "기준 영역보다 넓게 표시했습니다. 경계를 조금 더 좁혀 보세요.")
        )
    elif area_ratio is not None and area_ratio <= AREA_RATIO_SMALL and not items:
        items.append(("SMALL_AREA", "기준 영역보다 작게 표시했습니다."))

    if (
        coverage is not None
        and coverage >= COVERAGE_GOOD
        and precision is not None
        and precision >= PRECISION_GOOD
    ):
        items.append(("WELL_MATCHED", "기준 영역의 범위와 경계를 잘 맞췄습니다."))

    return items


def build(user_mask: np.ndarray, reference_mask: np.ndarray) -> dict:
    """응답에 실릴 spatial_feedback 객체.

    `primary_message` 는 화면 상단에 한 줄로 띄우기 위한 대표 문장(위치 판정)이다.
    """
    metrics = compute_metrics(user_mask, reference_mask)
    position = _position_item(metrics)
    items = [position, *_extent_items(metrics)]

    return {
        # geometry 로만 만들어졌음을 응답에 남긴다 — 전문가 소견과 섞이면 안 된다
        "source": "geometry",
        "primary_message": position[1],
        "items": [{"code": code, "message": message} for code, message in items],
        "metrics": metrics,
    }
