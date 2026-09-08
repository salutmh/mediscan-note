"""
미리 계산된 모델 예측 (`ai_prediction` 참고 정보).

**채점에는 쓰이지 않는다** (api-spec v0.4). 판독훈련 채점 기준은 전문가 GT reference mask 뿐이고,
모델 결과는 화면 3 에 "AI 예측(참고)" 로만 표시된다.

왜 미리 계산하나
---------------
뇌 MRI 모델(VS_Seg UNet2d5_spvPA)은 3D volume 입력이라 slice PNG 한 장으로 추론할 수 없고,
sliding-window 추론이 케이스당 수 분 걸린다. 제출 요청이 이걸 기다릴 수 없고, 백엔드에
torch/monai 를 깔 이유도 없다. 그래서 학습 venv 에서
`scripts/run_model_predictions.py` 로 한 번 돌려 sidecar 로 남기고, 여기서는 읽기만 한다.

  app/static/cases/<case_id>/prediction.json   지표 + model_version
  app/static/cases/<case_id>/prediction.png    대표 slice 예측 마스크 (미검출이면 없음)

sidecar 가 없으면 None 이고, 그 케이스는 `ai_prediction: null` 로 나간다.
파일 mtime 을 확인하므로 다시 계산해 덮어쓰면 서버 재시작 없이 반영된다.
"""
import json
import logging

from app.static_files import STATIC_DIR

logger = logging.getLogger(__name__)

CASES_DIR = STATIC_DIR / "cases"
SIDECAR_NAME = "prediction.json"

_cache: dict[str, tuple[tuple, dict | None]] = {}


def sidecar_path(case_id: str):
    return CASES_DIR / case_id / SIDECAR_NAME


def _stamp(path) -> tuple:
    try:
        stat = path.stat()
    except OSError:
        return (False, 0, 0)
    return (True, stat.st_mtime_ns, stat.st_size)


def clear_cache() -> None:
    _cache.clear()


def load(case_id: str | None) -> dict | None:
    """api-spec 의 `ai_prediction` 객체. 없으면 None."""
    if not case_id:
        return None

    stamp = _stamp(sidecar_path(case_id))
    cached = _cache.get(case_id)
    if cached is not None and cached[0] == stamp:
        return cached[1]

    prediction = _read(case_id)
    _cache[case_id] = (stamp, prediction)
    return prediction


def _read(case_id: str) -> dict | None:
    path = sidecar_path(case_id)
    if not path.exists():
        return None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("모델 예측 sidecar 를 읽지 못했습니다: %s", path)
        return None
    if not isinstance(raw, dict) or not raw.get("model_version"):
        logger.warning("모델 예측 sidecar 형식이 올바르지 않습니다: %s", path)
        return None

    def rounded(value):
        return round(float(value), 4) if value is not None else None

    dice = raw.get("dice_vs_reference")
    return {
        "model_version": raw["model_version"],
        # 미검출 케이스는 마스크 파일이 없다 -> null (빈 PNG 를 내려보내지 않는다)
        "mask_url": raw.get("mask_url"),
        "dice_vs_reference": rounded(dice),
        "detected": bool(raw.get("detected", False)),
        "representative_slice_dice": rounded(raw.get("representative_slice_dice")),
        "computed_at": raw.get("generated_at"),
    }


def raw_sidecar(case_id: str):
    """점검 스크립트용 원본 sidecar (API 응답에는 쓰지 않는다)."""
    path = sidecar_path(case_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def summary() -> dict:
    """/health 용. 미리 계산된 예측이 몇 케이스에 있는지."""
    if not CASES_DIR.exists():
        return {"cases_with_prediction": 0, "case_ids": []}

    case_ids = sorted(p.parent.name for p in CASES_DIR.glob(f"*/{SIDECAR_NAME}"))
    return {"cases_with_prediction": len(case_ids), "case_ids": case_ids}
