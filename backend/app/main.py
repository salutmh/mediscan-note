from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import inference, model_predictions
from app.db import DATABASE_URL, init_db
from app.static_files import STATIC_DIR, STATIC_URL_PREFIX, ensure_dirs, set_request_base
from app.routers import analyze, auth, cases, consents, wrong_notes


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 테이블 생성 + 케이스 시드 (없을 때만). DB 는 DATABASE_URL 로 결정된다 — db.py 참고.
    ensure_dirs()
    init_db()
    yield


app = FastAPI(title="메디스캔노트 API", version="0.2.0", lifespan=lifespan)

# 개발 중에는 프론트(Vite 기본 5173포트)에서 자유롭게 호출할 수 있도록 전체 허용.
# 배포 전에 실제 프론트 도메인으로 좁힐 것.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def remember_request_base(request, call_next):
    """영상·마스크 절대 URL 을 **요청이 들어온 주소 기준**으로 만든다.

    MEDISCAN_PUBLIC_BASE 를 설정하면 그 값이 우선한다(배포). 설정하지 않으면 여기서 잡은
    주소를 쓰므로, 백엔드를 8000 이든 8010 이든 어디에 띄워도 URL 이 따라간다.
    (예전에는 8000 으로 고정돼 있어 포트를 바꾸면 영상만 조용히 깨졌다.)
    """
    set_request_base(str(request.base_url))
    return await call_next(request)


# 케이스 영상/기준 마스크. 프론트가 다른 도메인에서 canvas 로 읽으므로 CORS 가 필요하다
# (위 CORSMiddleware 가 적용된다) — static_files.py 참고.
app.mount(STATIC_URL_PREFIX, StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(auth.router)
app.include_router(consents.router)
app.include_router(cases.router)
app.include_router(wrong_notes.router)
app.include_router(analyze.router)


@app.get("/health")
def health():
    # 어느 DB 를 쓰는지 바로 확인할 수 있게 드라이버 이름만 노출 (접속정보는 숨김)
    return {
        "status": "ok",
        "db": DATABASE_URL.split("://", 1)[0],
        "models": inference.status(),
        # 무거운 volume 모델은 요청 시 추론하지 않고 미리 계산된 예측을 쓴다
        "precomputed_predictions": model_predictions.summary(),
    }
