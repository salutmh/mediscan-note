"""
전정신경초종 (Vestibular Schwannoma) 분할 모델 추론 wrapper.

======================================================================
이 모델은 **slice 1장이 아니라 volume 전체**를 입력으로 받는다.
======================================================================
VS_Seg 의 UNet2d5_spvPA 는 3D 네트워크이고, 추론은 MONAI sliding_window_inference 로
volume (H, W, S) 전체에 대해 한 번에 돈다. 그래서 케이스 PNG 한 장으로는 추론할 수 없다.

따라서 서비스는 **미리 계산된 예측**을 쓴다:
  1. (오프라인, 학습 venv) backend/scripts/run_model_predictions.py 가 이 모듈로 추론
  2. 결과를 케이스별 sidecar (prediction.png + prediction.json) 로 저장
  3. (온라인, 백엔드) app/model_predictions.py 가 sidecar 를 읽어 `ai_prediction` 에 실어 보냄

이 구조 덕분에 **백엔드 서비스에는 torch/monai 가 필요 없고**, 제출 요청이 무거운 3D 추론을
기다리지 않는다 (CPU 기준 케이스당 수 분).

**모델 출력은 채점에 쓰이지 않는다** (api-spec v0.4). 판독훈련 채점 기준은 전문가 GT
reference mask 뿐이고, 모델 결과는 `ai_prediction` 참고 정보로만 나간다.

----------------------------------------------------------------------
전처리·모델 구조 출처 (추정 없음)
----------------------------------------------------------------------
아래는 학습 담당자의 노트북 `02_run_pretrained_model.ipynb` cell 6/7/8 을 그대로 옮긴 것이다.
  - cell 6: volume 전체 z-score 정규화  (NormalizeIntensity 상당)
  - cell 7: UNet2d5_spvPA 하이퍼파라미터 + best_metric_model.pth 로드 (strict=True)
  - cell 8: sliding_window_inference(roi (384,384,64), gaussian, overlap 0.25) -> argmax

⚠️ **표시용 PNG 전처리(percentile 1~99% 클리핑)와 절대 공유하지 않는다.**
모델 입력은 원본 intensity volume 의 z-score 이고, 표시용은 화면 전용이다.

재현 검증: `run_model_predictions.py --verify-against <노트북 outputs>` 가 노트북 산출물과
Dice / 예측 voxel 수 / 마스크 배열을 대조한다. 이 대조를 통과했기에 PREPROCESS_VERIFIED=True 다.
"""
import logging
import os
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

MODEL_VERSION = "vs-seg-unet2d5-att-hard-t1"

# 이 모델은 volume 입력이다. 백엔드는 이 값을 보고 slice PNG 로 부르지 않는다.
INPUT_KIND = "volume"

# 학습 노트북(cell 6/7/8)과 동일함을 산출물 대조로 확인했다 -> True.
# (VS-SEG-202 예측 마스크 배열 완전 일치, 6케이스 Dice 소수점 4자리 일치)
PREPROCESS_VERIFIED = True

# 명시적 옵트인 환경변수 — 무거운 의존성이 깔렸다고 자동으로 켜지지 않게 한다.
ENABLE_ENV = "MEDISCAN_ENABLE_BRAIN_MRI_MODEL"

MODEL_DIR = Path(__file__).resolve().parent

# 학습 리포는 이 리포 밖에 둔다 (CLAUDE.md 원칙 6).
#
# **서비스 런타임은 이 경로에 의존하지 않는다.** 여기를 쓰는 것은 오프라인 예측 계산
# (backend/scripts/run_model_predictions.py) 뿐이고, 배포된 백엔드는 미리 계산된
# sidecar 만 읽는다. 그래서 학습 리포가 없어도 서비스는 정상 동작한다.
#
# 아래 Desktop 경로는 **로컬 개발 기본값**이다. 다른 환경에서는 MEDISCAN_VS_SEG_ROOT 로 지정한다.
VS_SEG_ROOT_ENV = "MEDISCAN_VS_SEG_ROOT"
DEFAULT_VS_SEG_ROOT = Path.home() / "Desktop" / "medical-ai" / "vestibular-schwannoma"

WEIGHTS_RELATIVE = Path("pretrained/UNet2d5_Att_Hard_T1_final/UNet2d5_Att_Hard_T1_final/model/best_metric_model.pth")
SOURCE_RELATIVE = Path("VS_Seg_original")

# --- 노트북 cell 7 의 모델 하이퍼파라미터 (그대로) ---
MODEL_KWARGS = dict(
    dimensions=3,
    in_channels=1,
    out_channels=2,
    channels=(16, 32, 48, 64, 80, 96),
    strides=((2, 2, 1), (2, 2, 1), (2, 2, 2), (2, 2, 2), (2, 2, 2)),
    kernel_sizes=((3, 3, 1), (3, 3, 1), (3, 3, 3), (3, 3, 3), (3, 3, 3), (3, 3, 3)),
    sample_kernel_sizes=((3, 3, 1), (3, 3, 1), (3, 3, 3), (3, 3, 3), (3, 3, 3)),
    num_res_units=2,
    dropout=0.1,
    attention_module=True,
)

# --- 노트북 cell 8 의 추론 설정 (그대로) ---
ROI_SIZE = (384, 384, 64)
FALLBACK_ROI_SIZE = (256, 256, 32)  # GPU VRAM 부족 시 (노트북과 동일한 폴백)
SW_BATCH_SIZE = 1
SW_MODE = "gaussian"
SW_OVERLAP = 0.25

_model = None
_model_device = None


class PredictionResult(TypedDict, total=False):
    mask: object          # numpy bool 배열 (H, W, S)
    model_version: str
    predicted_voxels: int
    dice: float | None
    roi_size: tuple


class VolumeModelError(RuntimeError):
    """모델을 쓸 수 없는 상태."""


def vs_seg_root() -> Path:
    override = os.getenv(VS_SEG_ROOT_ENV, "").strip()
    return Path(override) if override else DEFAULT_VS_SEG_ROOT


def weights_path() -> Path:
    return vs_seg_root() / WEIGHTS_RELATIVE


def source_path() -> Path:
    return vs_seg_root() / SOURCE_RELATIVE


def unavailable_reason() -> str | None:
    """왜 **이 프로세스에서** 추론할 수 없는지 한 줄로. 가능하면 None.

    백엔드 서비스에서는 보통 "torch 미설치"가 나오는 것이 정상이다 —
    서비스는 미리 계산된 sidecar 를 쓰고 직접 추론하지 않는다 (app/model_predictions.py).
    """
    if not PREPROCESS_VERIFIED:
        return "전처리 미검증 (PREPROCESS_VERIFIED=False)"
    if not weights_path().exists():
        return f"가중치 없음: {weights_path()}"
    if not (source_path() / "params" / "networks" / "nets" / "unet2d5_spvPA.py").exists():
        return f"모델 소스 없음: {source_path()} ({VS_SEG_ROOT_ENV} 로 경로 지정)"
    try:
        import monai  # noqa: F401
        import torch  # noqa: F401
    except ImportError as exc:
        return f"추론 의존성 미설치 ({exc.name}) — 서비스는 미리 계산된 예측을 사용합니다"
    if os.getenv(ENABLE_ENV, "").strip() not in {"1", "true", "True"}:
        return f"환경변수 옵트인 필요: {ENABLE_ENV}=1"
    return None


def is_available() -> bool:
    """이 프로세스에서 직접 추론이 가능한지. 예외를 던지지 않는다."""
    reason = unavailable_reason()
    if reason is not None:
        logger.debug("%s 직접 추론 불가: %s", MODEL_VERSION, reason)
        return False
    return True


# --------------------------------------------------------- 노트북 cell 6
def preprocess_volume(volume):
    """volume 전체 z-score 정규화 (노트북 cell 6 그대로).

    **표시용 percentile 클리핑과 다르다.** 원본 intensity 를 그대로 쓴다.
    """
    import numpy as np
    import torch

    volume = np.asarray(volume, dtype=np.float32)
    mean = float(volume.mean())
    std = float(volume.std())
    if std < 1e-8:
        raise VolumeModelError("영상 표준편차가 0에 가깝습니다.")

    volume_norm = (volume - mean) / std
    return torch.from_numpy(volume_norm).unsqueeze(0).unsqueeze(0).float()


# --------------------------------------------------------- 노트북 cell 7
def _build_model(device):
    import sys

    import torch
    from monai.networks.layers import Norm

    source = source_path()
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

    from params.networks.nets.unet2d5_spvPA import UNet2d5_spvPA

    model = UNet2d5_spvPA(norm=Norm.BATCH, **MODEL_KWARGS).to(device)
    state = torch.load(weights_path(), map_location=device, weights_only=False)
    model.load_state_dict(state, strict=True)
    model.eval()
    return model


def load_model(device=None):
    """가중치 로드 (프로세스당 1회)."""
    global _model, _model_device

    import torch

    if device is None:
        device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    if _model is not None and _model_device == str(device):
        return _model

    reason = unavailable_reason()
    if reason is not None:
        raise VolumeModelError(reason)

    _model = _build_model(device)
    _model_device = str(device)
    logger.info("%s 로드 완료: %s (device=%s)", MODEL_VERSION, weights_path(), device)
    return _model


# --------------------------------------------------------- 노트북 cell 8
def predict_volume(volume, reference_mask=None) -> PredictionResult:
    """volume (H, W, S) -> 예측 마스크 (H, W, S) bool.

    volume 은 **원본 intensity** 여야 한다 (표시용 8bit PNG 가 아니다).
    """
    import numpy as np
    import torch
    from monai.inferers import sliding_window_inference

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    model = load_model(device)
    input_tensor = preprocess_volume(volume)

    def predictor(x):
        return model(x)[0]

    def run(roi_size):
        with torch.inference_mode():
            return sliding_window_inference(
                inputs=input_tensor.to(device),
                roi_size=roi_size,
                sw_batch_size=SW_BATCH_SIZE,
                predictor=predictor,
                mode=SW_MODE,
                overlap=SW_OVERLAP,
            )

    used_roi = ROI_SIZE
    try:
        outputs = run(used_roi)
    except torch.cuda.OutOfMemoryError:
        logger.warning("GPU VRAM 부족 -> %s 로 재시도", FALLBACK_ROI_SIZE)
        torch.cuda.empty_cache()
        used_roi = FALLBACK_ROI_SIZE
        outputs = run(used_roi)

    predicted = torch.argmax(outputs, dim=1)[0].detach().cpu().numpy().astype(bool)

    dice = None
    if reference_mask is not None:
        reference = np.asarray(reference_mask).astype(bool)
        intersection = float(np.logical_and(predicted, reference).sum())
        denominator = float(predicted.sum() + reference.sum())
        dice = (2.0 * intersection / denominator) if denominator > 0 else 1.0

    return {
        "mask": predicted,
        "model_version": MODEL_VERSION,
        "predicted_voxels": int(predicted.sum()),
        "dice": dice,
        "roi_size": used_roi,
    }


def predict(image_path: str, reference_mask_path: str | None = None):
    """부위별 레지스트리의 2D 계약. **이 모델은 지원하지 않는다.**

    slice PNG 한 장으로 추론하면 학습 때와 다른 입력이 되어 조용히 틀린 마스크가 나온다.
    백엔드는 INPUT_KIND == "volume" 을 보고 이 경로를 타지 않는다.
    """
    raise VolumeModelError(
        "이 모델은 volume 입력 전용입니다 (INPUT_KIND='volume'). "
        "slice PNG 로는 추론하지 않습니다 — predict_volume() 을 쓰거나, "
        "서비스에서는 backend/scripts/run_model_predictions.py 로 미리 계산한 결과를 사용하세요."
    )
