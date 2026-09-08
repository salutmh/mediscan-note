"""
마스크 디코딩 + 분할 지표 계산.

프론트가 보내는 mask_png_base64(캔버스 toDataURL 결과)와 케이스의 기준 마스크 PNG 를
같은 크기의 boolean 배열로 만든 뒤 Dice/IoU 를 계산한다.

마스크 PNG 형태가 두 가지라 둘 다 지원한다 (프론트 ResultCompare.vue 와 같은 판정 규칙):
  - 투명 배경 + 불투명 마스크  -> 알파 > 16 을 마스크로 본다
  - 검은 배경 + 흰 마스크      -> 밝기 > 64 를 마스크로 본다
"""
import base64
import binascii
import io
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ALPHA_THRESHOLD = 16
LUMA_THRESHOLD = 64


class MaskError(ValueError):
    """마스크를 읽을 수 없을 때."""


def _to_bool(image: Image.Image) -> np.ndarray:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    alpha = rgba[..., 3]
    # 알파가 전부 불투명하면 알파로는 구분이 안 되므로 밝기로 판정한다
    if bool((alpha >= 250).all()):
        luma = rgba[..., :3].mean(axis=2)
        return luma > LUMA_THRESHOLD
    return alpha > ALPHA_THRESHOLD


def from_base64(data: str) -> np.ndarray:
    """data URL 접두사가 붙어 있어도 처리한다."""
    if not data:
        raise MaskError("빈 마스크")
    if "," in data and data.strip().startswith("data:"):
        data = data.split(",", 1)[1]
    try:
        raw = base64.b64decode(data, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise MaskError(f"base64 디코딩 실패: {exc}") from exc
    try:
        with Image.open(io.BytesIO(raw)) as image:
            return _to_bool(image)
    except OSError as exc:
        raise MaskError(f"PNG 파싱 실패: {exc}") from exc


def from_path(path: str | Path) -> np.ndarray:
    p = Path(path)
    if not p.exists():
        raise MaskError(f"마스크 파일 없음: {p}")
    try:
        with Image.open(p) as image:
            return _to_bool(image)
    except OSError as exc:
        raise MaskError(f"PNG 파싱 실패: {p} ({exc})") from exc


def align(mask: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """크기가 다르면 기준 마스크 크기에 맞춘다 (최근접 보간 — 이진 마스크이므로)."""
    if mask.shape == shape:
        return mask
    resized = Image.fromarray(mask.astype(np.uint8) * 255).resize(
        (shape[1], shape[0]), resample=Image.NEAREST
    )
    return np.asarray(resized, dtype=np.uint8) > 127


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """마스크 내부의 닫힌 빈 공간을 채운다.

    ⚠️ **현재 호출되지 않는다 (API 계약 v0.4).** 윤곽선만 그린 ROI 를 과도하게 후하게 채점할 수
    있어 채점 경로에서 제거했다. 향후 `contour`(닫힌 윤곽선) 도구를 추가할 때 그 도구에 한해
    다시 쓰기 위해 함수만 남겨둔다 — grading.py 참고.


    브러시로 병변 **둘레를 그리면** 가운데가 빈 도넛 모양이 된다. 사용자의 의도는
    "이 안쪽 영역"이므로, 테두리에서 배경을 flood fill 한 뒤 바깥과 연결되지 않은
    배경 픽셀(= 내부 구멍)을 마스크에 포함시킨다.
    칠해서 채운 경우에는 아무 영향이 없다.
    """
    if not mask.any():
        return mask

    height, width = mask.shape
    # 바깥 배경이 항상 연결되도록 1픽셀 패딩을 두고 flood fill 한다
    padded = Image.new("L", (width + 2, height + 2), 255)
    padded.paste(Image.fromarray((~mask).astype(np.uint8) * 255, mode="L"), (1, 1))
    ImageDraw.floodfill(padded, (0, 0), 128)

    background = np.asarray(padded, dtype=np.uint8)[1 : height + 1, 1 : width + 1]
    holes = background == 255  # flood fill 이 닿지 못한 배경 = 내부 구멍
    return np.logical_or(mask, holes)


def dice_iou(user: np.ndarray, reference: np.ndarray) -> tuple[float, float]:
    user = align(user, reference.shape)
    intersection = float(np.logical_and(user, reference).sum())
    user_area = float(user.sum())
    ref_area = float(reference.sum())
    union = user_area + ref_area - intersection

    dice = (2.0 * intersection / (user_area + ref_area)) if (user_area + ref_area) > 0 else 0.0
    iou = (intersection / union) if union > 0 else 0.0
    return dice, iou


def centroid(mask: np.ndarray) -> tuple[float, float] | None:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return None
    return float(xs.mean()), float(ys.mean())


def equivalent_radius(mask: np.ndarray) -> float:
    """면적이 같은 원의 반지름 — 위치 점수 정규화에 쓴다."""
    area = float(mask.sum())
    return math.sqrt(area / math.pi) if area > 0 else 0.0


def location_score(user: np.ndarray, reference: np.ndarray) -> int:
    """0~100. 두 마스크 중심이 얼마나 가까운지 (기준 마스크 크기로 정규화)."""
    user = align(user, reference.shape)
    uc = centroid(user)
    rc = centroid(reference)
    if uc is None or rc is None:
        return 0
    r = equivalent_radius(reference)
    if r <= 0:
        return 0
    distance = math.hypot(uc[0] - rc[0], uc[1] - rc[1])
    # 중심이 기준 반지름 안이면 100점, 3배 거리에서 0점
    return int(max(0.0, min(100.0, 100.0 * (1.0 - (distance - r) / (2.0 * r)))))
