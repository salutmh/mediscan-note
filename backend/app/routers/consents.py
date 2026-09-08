import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/api/consents", tags=["consents"])

MOCK_DIR = Path(__file__).resolve().parent.parent / "mock_data"


@router.get("/current-version")
def current_version():
    path = MOCK_DIR / "consents_version.json"
    return json.loads(path.read_text(encoding="utf-8"))
