from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_DATA_ROOT = Path("/data/ai")

def get_data_root() -> Path:
    return Path(os.getenv("MEDICAL_AI_DATA_ROOT", str(DEFAULT_DATA_ROOT)))

def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def load_index() -> dict[str, Any]:
    return _load_json(get_data_root() / "index.json")

def list_cases() -> list[dict[str, Any]]:
    return load_index().get("cases", [])

def find_case(case_id: str) -> dict[str, Any] | None:
    for case in list_cases():
        if case.get("case_id") == case_id:
            return case
    return None

def load_case_prediction(case_id: str) -> dict[str, Any]:
    case = find_case(case_id)
    if not case:
        raise KeyError(case_id)
    return _load_json(get_data_root() / case["ai_prediction_json"])

def public_asset_url(relative_path: str | None) -> str | None:
    if not relative_path:
        return None
    clean = relative_path.replace("\\", "/").lstrip("/")
    return f"/ai-assets/{clean}"

def build_case_response(case_id: str) -> dict[str, Any]:
    case = find_case(case_id)
    if not case:
        raise KeyError(case_id)

    prediction_payload = load_case_prediction(case_id)
    ai = prediction_payload.get("ai_prediction", {})

    predictions = [
        {**p, "mask_url": public_asset_url(p.get("mask_image"))}
        for p in ai.get("predictions", [])
    ]

    return {
        "case_id": case_id,
        "source_disease": case.get("source_disease"),
        "source_image_url": public_asset_url(case.get("source_image")),
        "gt_summary": {
            "is_positive": case.get("is_positive_gt"),
            "object_count": case.get("gt_object_count"),
        },
        "ai_prediction": {
            "supplemental_only": ai.get("supplemental_only", True),
            "model_name": ai.get("model_name"),
            "confidence_threshold": ai.get("confidence_threshold"),
            "prediction_count": ai.get("prediction_count", 0),
            "overlay_url": public_asset_url(ai.get("overlay_image")),
            "predictions": predictions,
        },
        "scoring_policy": {
            "source": "expert_ground_truth",
            "ai_used_for_scoring": False,
        },
    }
