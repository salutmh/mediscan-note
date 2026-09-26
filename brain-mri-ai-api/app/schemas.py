"""Pydantic response schemas for the brain MRI segmentation API."""
from __future__ import annotations

from pydantic import BaseModel, Field

DISCLAIMER = (
    "이 결과는 교육/연구용 AI 모델의 참고 결과이며 의료 진단 결과가 아닙니다. "
    "실제 진단은 반드시 의료 전문가가 수행해야 합니다."
)


class Prediction(BaseModel):
    class_id: int = Field(..., description="클래스 번호 (0~4)")
    disease: str = Field(..., description="클래스 이름")
    confidence: float = Field(
        ..., ge=0.0, le=1.0,
        description="Model confidence score (0~1). 질병 확률이 아님.",
    )
    bbox: list[float] = Field(
        ..., min_length=4, max_length=4,
        description="[x1, y1, x2, y2] 원본 이미지 픽셀 좌표",
    )
    polygon: list[list[float]] = Field(
        default_factory=list,
        description="세그멘테이션 외곽선 [[x, y], ...] 원본 이미지 픽셀 좌표",
    )


class PredictResponse(BaseModel):
    model: str
    image_width: int
    image_height: int
    predictions: list[Prediction]
    confidence_note: str = "confidence는 model confidence score이며 질병 확률이 아닙니다."
    is_diagnosis: bool = False
    disclaimer: str = DISCLAIMER


class HealthResponse(BaseModel):
    status: str
    model: str
    classes: int
    class_names: dict[int, str]
    device: str
    model_path: str
