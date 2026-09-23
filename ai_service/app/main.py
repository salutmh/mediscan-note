from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routers.ai_cases import router as ai_cases_router
from app.services.ai_case_store import get_data_root

app = FastAPI(title="Medical Image Learning AI Sidecar", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ai_cases_router)

DATA_ROOT = get_data_root()
if DATA_ROOT.exists():
    app.mount("/ai-assets", StaticFiles(directory=str(DATA_ROOT)), name="ai-assets")

@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "medical-image-learning-ai-sidecar",
        "ai_data_root": str(DATA_ROOT),
        "ai_data_exists": DATA_ROOT.exists(),
    }
