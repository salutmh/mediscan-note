"""FastAPI entrypoint: 5-disease brain MRI YOLO26s-Seg inference API."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app import inference
from app.schemas import HealthResponse, PredictResponse

load_dotenv()
logger = logging.getLogger("brain-mri-ai-api")
logging.basicConfig(level=logging.INFO)

DEFAULT_ORIGINS = (
    "http://localhost:5173,http://127.0.0.1:5173,"
    "http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:8080,http://127.0.0.1:8080"
)


def get_cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", DEFAULT_ORIGINS)
    return [o.strip() for o in raw.split(",") if o.strip()]


def get_max_upload_bytes() -> int:
    return int(float(os.getenv("MAX_UPLOAD_MB", "20")) * 1024 * 1024)


@asynccontextmanager
async def lifespan(app: FastAPI):
    model_path = inference.get_model_path()
    logger.info("Loading model from %s", model_path)
    app.state.model = inference.SegmentationModel(model_path)
    logger.info(
        "Model loaded on device=%s classes=%s", app.state.model.device, app.state.model.names
    )
    yield
    app.state.model = None


app = FastAPI(
    title="Brain MRI 5-Disease Segmentation API",
    description="YOLO26s-Seg 기반 뇌 MRI 5질환 세그멘테이션 추론 API (교육/연구용)",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health():
    model: inference.SegmentationModel = app.state.model
    return HealthResponse(
        status="ok",
        model=inference.MODEL_NAME,
        classes=len(model.names),
        class_names=model.names,
        device=model.device,
        model_path=str(model.model_path),
    )


@app.post("/predict", response_model=PredictResponse)
async def predict(file: UploadFile = File(..., description="뇌 MRI 이미지 (PNG/JPG/JPEG)")):
    if not inference.is_allowed_filename(file.filename):
        raise HTTPException(
            status_code=415,
            detail=f"지원하지 않는 파일 형식입니다. 허용: {sorted(inference.ALLOWED_EXTENSIONS)}",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    if len(data) > get_max_upload_bytes():
        raise HTTPException(status_code=413, detail="파일이 너무 큽니다 (MAX_UPLOAD_MB 확인).")

    try:
        image = inference.decode_image(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    model: inference.SegmentationModel = app.state.model
    preds = model.predict(image)

    return PredictResponse(
        model=inference.MODEL_LABEL,
        image_width=image.width,
        image_height=image.height,
        predictions=preds,
    )
