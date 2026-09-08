"""
부위별 추론 모델 레지스트리.

`models/<폴더>/inference.py` 를 동적으로 import 한다. 백엔드는 부위 코드만 알고,
어떤 모델이 붙는지는 models/ 폴더 구성에 따라 결정된다 —
팀원이 새 부위를 추가할 때 백엔드 코드를 고칠 필요가 없다 (CLAUDE.md 개발원칙 4).

각 inference.py 가 지켜야 할 계약 (models/_template/inference.py 참고):
    MODEL_VERSION: str
    def is_available() -> bool
    def predict(image_path, reference_mask_path=None) -> dict
    def unavailable_reason() -> str | None   (선택 — /health 에 사유를 노출하고 싶을 때)

torch 같은 무거운 의존성은 각 모듈 안에서 lazy import 한다. 그래서 torch 가 설치되지
않은 환경에서도 백엔드는 정상 기동하고, 해당 부위만 "모델 없음"으로 처리된다.
"""
import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# backend/ 의 부모 = 리포 루트
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MODELS_DIR = REPO_ROOT / "models"

# 부위 코드 -> models/ 하위 폴더명 (api-spec.md 0절 부위 코드)
BODY_PART_MODULES: dict[str, str] = {
    "brain_mri": "brain_mri_vs",
    "brain_ct": "brain_ct",
    "chest_xray": "chest_xray",
    "abdomen_ct": "abdomen_ct",
    "knee_mri": "knee_mri",
}

_cache: dict[str, Any | None] = {}


def _load_module(folder: str) -> Any | None:
    path = MODELS_DIR / folder / "inference.py"
    if not path.exists():
        return None

    module_name = f"mediscan_models.{folder}"
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # 모델 쪽 import 오류가 서비스 전체를 막지 않도록
        logger.exception("추론 모듈 로드 실패: %s", path)
        sys.modules.pop(module_name, None)
        return None
    return module


def get_module(body_part: str) -> Any | None:
    """해당 부위의 추론 모듈. 없거나 로드 실패면 None."""
    if body_part in _cache:
        return _cache[body_part]
    folder = BODY_PART_MODULES.get(body_part)
    module = _load_module(folder) if folder else None
    _cache[body_part] = module
    return module


def is_available(body_part: str) -> bool:
    """모듈이 있고, 그 모듈이 실제로 추론할 준비가 됐는지(체크포인트 등)."""
    module = get_module(body_part)
    if module is None:
        return False
    checker = getattr(module, "is_available", None)
    if checker is None:
        return False
    try:
        return bool(checker())
    except Exception:
        logger.exception("is_available() 실패: %s", body_part)
        return False


def unavailable_reason(body_part: str) -> str | None:
    """왜 이 부위 모델을 쓸 수 없는지. 사용 가능하면 None.

    모듈이 unavailable_reason() 을 제공하면 그 값을, 아니면 일반적인 사유를 돌려준다.
    """
    module = get_module(body_part)
    if module is None:
        folder = BODY_PART_MODULES.get(body_part)
        if folder is None:
            return f"알 수 없는 부위 코드: {body_part}"
        return f"추론 모듈 없음: models/{folder}/inference.py"

    reporter = getattr(module, "unavailable_reason", None)
    if callable(reporter):
        try:
            return reporter()
        except Exception:
            logger.exception("unavailable_reason() 실패: %s", body_part)
            return "상태 확인 중 오류"

    return None if is_available(body_part) else "모델이 준비되지 않음"


def status() -> dict[str, dict]:
    """부위별 모델 상태 — /health 와 운영 확인용."""
    result: dict[str, dict] = {}
    for body_part, folder in BODY_PART_MODULES.items():
        module = get_module(body_part)
        available = is_available(body_part)
        result[body_part] = {
            "folder": folder,
            "module_loaded": module is not None,
            "available": available,
            "model_version": getattr(module, "MODEL_VERSION", None) if module else None,
            # "volume" 이면 slice PNG 로 요청 시 추론하지 않고 미리 계산된 예측을 쓴다
            "input_kind": getattr(module, "INPUT_KIND", "image") if module else None,
            "unavailable_reason": None if available else unavailable_reason(body_part),
        }
    return result
