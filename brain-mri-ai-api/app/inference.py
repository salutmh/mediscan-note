"""YOLO26s-Seg model loading and inference helpers."""
from __future__ import annotations

import io
import os
from pathlib import Path
from threading import Lock

import numpy as np
from PIL import Image, UnidentifiedImageError

MODEL_NAME = "YOLO26s-Seg"
MODEL_LABEL = "YOLO26s-Seg 5-disease integrated"

# 학습 시 사용한 클래스 순서. 가중치 파일의 names와 일치해야 한다.
CLASS_NAMES: dict[int, str] = {
    0: "vestibular_schwannoma",
    1: "glioma",
    2: "brain_metastasis",
    3: "ischemic_stroke",
    4: "multiple_sclerosis",
}

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}


def get_model_path() -> Path:
    return Path(os.getenv("MODEL_PATH", "./weights/best.pt")).expanduser()


def get_conf_threshold() -> float:
    return float(os.getenv("CONF_THRESHOLD", "0.25"))


class SegmentationModel:
    """Thin wrapper around an ultralytics YOLO segmentation model."""

    def __init__(self, model_path: Path):
        from ultralytics import YOLO  # 지연 import: 서버 기동 시간 단축

        if not model_path.is_file():
            raise FileNotFoundError(
                f"모델 파일을 찾을 수 없습니다: {model_path} "
                "(.env의 MODEL_PATH를 확인하세요)"
            )
        self.model_path = model_path
        self.model = YOLO(str(model_path))
        self.names: dict[int, str] = {int(k): str(v) for k, v in self.model.names.items()}
        self._lock = Lock()

        if self.names != CLASS_NAMES:
            raise ValueError(
                f"가중치의 클래스가 예상과 다릅니다. expected={CLASS_NAMES} got={self.names}"
            )

    @property
    def device(self) -> str:
        try:
            return str(next(self.model.model.parameters()).device)
        except Exception:  # pragma: no cover
            return "unknown"

    def predict(self, image: Image.Image, conf: float | None = None) -> list[dict]:
        """이미지 1장 추론. 좌표는 모두 원본 픽셀 기준."""
        rgb = image.convert("RGB")
        conf = get_conf_threshold() if conf is None else conf

        with self._lock:  # ultralytics 모델은 스레드 안전하지 않음
            results = self.model.predict(rgb, conf=conf, verbose=False)

        result = results[0]
        preds: list[dict] = []
        if result.boxes is None or len(result.boxes) == 0:
            return preds

        boxes_xyxy = result.boxes.xyxy.cpu().numpy()
        cls_ids = result.boxes.cls.cpu().numpy().astype(int)
        confs = result.boxes.conf.cpu().numpy()
        # masks.xy: 원본 이미지 좌표계의 폴리곤 리스트 (박스 순서와 동일)
        polygons = result.masks.xy if result.masks is not None else [None] * len(cls_ids)

        for box, cid, c, poly in zip(boxes_xyxy, cls_ids, confs, polygons):
            preds.append(
                {
                    "class_id": int(cid),
                    "disease": self.names.get(int(cid), str(cid)),
                    "confidence": round(float(c), 4),
                    "bbox": [round(float(v), 1) for v in box],
                    "polygon": _round_polygon(poly),
                }
            )
        return preds


def _round_polygon(poly) -> list[list[float]]:
    if poly is None:
        return []
    arr = np.asarray(poly, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[0] < 3:
        return []
    return [[round(float(x), 1), round(float(y), 1)] for x, y in arr]


def decode_image(data: bytes) -> Image.Image:
    """업로드 바이트 → PIL 이미지. 실패 시 ValueError."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        return img
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError("이미지를 디코딩할 수 없습니다 (손상되었거나 PNG/JPG가 아님)") from e


def is_allowed_filename(filename: str | None) -> bool:
    if not filename:
        return False
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS
