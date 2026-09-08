"""
부위별 추론 wrapper 템플릿.

새 부위를 추가하는 팀원은 이 파일을 `models/<부위폴더>/inference.py` 로 복사해서 채운다.
백엔드는 부위 코드로 이 모듈을 찾아 자동으로 쓴다 (backend/app/inference.py 의 BODY_PART_MODULES).
백엔드 코드는 고칠 필요가 없다.

지켜야 할 계약 세 가지:
  MODEL_VERSION : 응답의 model_version 으로 그대로 나간다. 화면 하단에 표시되므로
                  "vs-2.5d-attn-unet-v1" 처럼 무엇으로 채점됐는지 알 수 있게 적는다.
  is_available(): 지금 추론이 가능한지 (체크포인트 파일 존재, torch import 가능 등).
                  False 면 백엔드가 기준 마스크 비교로 자동 폴백한다. 예외를 던지지 말 것.
  predict()     : 아래 PredictionResult 를 반환.

주의:
  - torch/numpy 같은 무거운 import 는 **함수 안에서** 한다 (모듈 최상단 금지).
    그래야 torch 가 없는 환경에서도 백엔드가 기동한다.
  - 체크포인트(.pth)와 데이터셋은 커밋하지 않는다 (.gitignore 참고).
"""
from pathlib import Path
from typing import TypedDict

MODEL_VERSION = "template-not-implemented"

# 담당자가 학습 전처리와 predict() 의 전처리가 일치함을 확인한 뒤 True 로 바꾼다.
# False 인 동안 is_available() 은 False 이고 predict() 는 예외를 던져야 한다.
# (전처리가 다르면 조용히 틀린 마스크가 나온다 — 화면에 그대로 노출되면 위험하다)
PREPROCESS_VERIFIED = False

# 체크포인트만 있다고 자동으로 켜지지 않도록 명시적 옵트인을 둔다.
ENABLE_ENV = "MEDISCAN_ENABLE_<부위>_MODEL"

MODEL_DIR = Path(__file__).resolve().parent
CHECKPOINT_PATH = MODEL_DIR / "checkpoints" / "model.pth"  # git 에는 커밋하지 않음


class PredictionResult(TypedDict, total=False):
    mask_path: str        # 모델이 만든 마스크 PNG 의 로컬 경로 (필수)
    mask_url: str | None  # 프론트가 접근할 URL (없으면 백엔드가 기준 마스크 URL 을 쓴다)
    model_version: str
    dice: float | None    # 기준 마스크가 주어진 경우 모델 스스로 계산한 값 (선택)
    iou: float | None


def unavailable_reason() -> str | None:
    """왜 쓸 수 없는지 한 줄로. 사용 가능하면 None. (선택 구현이지만 권장 — /health 에 노출된다)"""
    import os

    if not CHECKPOINT_PATH.exists():
        return f"체크포인트 없음: {CHECKPOINT_PATH.name}"
    try:
        import torch  # noqa: F401
    except ImportError:
        return "torch 미설치"
    if os.getenv(ENABLE_ENV, "").strip() not in {"1", "true", "True"}:
        return f"환경변수 옵트인 필요: {ENABLE_ENV}=1"
    if not PREPROCESS_VERIFIED:
        return "전처리 미검증 (PREPROCESS_VERIFIED=False)"
    return None


def is_available() -> bool:
    """추론 준비 여부. 예외를 던지지 말고 True/False 만 반환한다."""
    return unavailable_reason() is None


def load_model():
    """체크포인트 로드. 첫 호출 결과를 모듈 전역에 캐시하는 방식을 권장."""
    raise NotImplementedError("모델 로드 구현 필요")


def predict(image_path: str, reference_mask_path: str | None = None) -> PredictionResult:
    """
    image_path          : 추론할 영상 경로
    reference_mask_path : 기준 마스크가 있으면 경로 (없으면 빈 문자열/None)

    마스크 PNG 로 저장한 뒤 그 경로를 mask_path 로 반환한다.
    마스크 형식: 병변 = 불투명, 배경 = 투명 (또는 흰색/검은색) — 백엔드가 둘 다 인식한다.
    """
    if not PREPROCESS_VERIFIED:
        raise RuntimeError("전처리가 검증되지 않아 추론할 수 없습니다 (PREPROCESS_VERIFIED=False).")
    raise NotImplementedError("추론 구현 필요")
