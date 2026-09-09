import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import asset_urls, config, inference, logging_config, model_predictions, scoring_config, security_headers
from app.cors import cors_kwargs, describe as describe_cors
from app.db import DATABASE_URL, init_db
from app import rate_limit as rate_limit_module
from app.rate_limit import RateLimitMiddleware
from app.asset_urls import SignedAssetMiddleware
from app.security_headers import SecurityHeadersMiddleware
from app.static_files import STATIC_DIR, STATIC_URL_PREFIX, ensure_dirs, set_request_base
from app.routers import admin, analyze, auth, cases, consents, review, wrong_notes


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 로깅을 가장 먼저 켠다 — 이후 기동 과정(마이그레이션·시드·정리)의 로그를 보기 위해서다.
    # 설정하지 않으면 app 의 logger.info 가 전부 버려진다 (root 기본 레벨이 WARNING).
    logging_config.configure()
    # 개발 전용 스위치가 production 에 남아 있으면 여기서 기동을 막는다.
    # DB 를 건드리기 **전에** 확인한다 — 시드 스위치가 켜져 있으면 init_db 가
    # 합성 케이스를 이미 넣어버리기 때문이다.
    config.assert_dev_only_flags_off()
    _warn_dev_only_flags()
    # 채점 임계값이 서로 모순되지 않는지. 잘못되면 등급 하나가 통째로 사라질 수 있는데
    # 응답 형태는 정상이라 눈치채기 어렵다 — 첫 제출이 아니라 기동 때 막는다.
    scoring_config.assert_valid()
    # 요청 수 제한이 production 에서 조용히 꺼져 있지 않은지.
    rate_limit_module.assert_valid()
    _note = rate_limit_module.describe()
    if _note:
        logging.getLogger("app").warning(_note)
    # 테이블 생성 + 케이스 시드 (없을 때만). DB 는 DATABASE_URL 로 결정된다 — db.py 참고.
    ensure_dirs()
    init_db()
    yield


def _warn_dev_only_flags() -> None:
    """개발 환경에서 켜진 스위치를 기동 로그에 남긴다.

    production 은 위에서 이미 막혔으므로 여기 오면 development 다. 켜둔 사실을
    잊고 "왜 이런 결과가 나오지?" 로 시간을 쓰는 일을 줄이기 위해 눈에 띄게 남긴다.
    """
    for name in config.describe_dev_only_flags():
        logging.getLogger("app").warning(
            "개발 전용 설정이 켜져 있습니다 - %s: %s", name, config.DEV_ONLY_FLAGS[name]
        )


app = FastAPI(title="메디스캔노트 API", version="0.2.0", lifespan=lifespan)

# 미들웨어는 **나중에 등록한 것이 바깥쪽**이다 (starlette). 그래서 CORS 를 마지막에 등록해
# 가장 바깥에 두어야 rate limit 이 돌려주는 429 응답에도 CORS 헤더가 붙는다.
# (그렇지 않으면 브라우저가 429 본문을 읽지 못해 "네트워크 오류"로만 보인다.)
# 보안 헤더는 rate limit 보다 **바깥**에 둔다 — 429 응답에도 붙어야 한다.
# (CORS 보다는 안쪽이다. CORS 는 preflight 를 가로채므로 가장 바깥이어야 한다.)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
# 케이스 자산(실제 의료영상) 서명 확인. StaticFiles 보다 **앞**에 있어야 막을 수 있다.
app.add_middleware(SignedAssetMiddleware)

# CORS 는 환경에 따라 갈린다 (app/cors.py):
#   development — localhost 아무 포트 허용 (프론트 5173, 포트 변경에도 그대로 동작)
#   production  — MEDISCAN_CORS_ORIGINS 필수, 와일드카드 금지
app.add_middleware(CORSMiddleware, **cors_kwargs())


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
app.include_router(admin.router)
# 케이스 후보 기술 검수 (운영자 전용 로컬 도구). 등록·활성화는 하지 않는다.
app.include_router(review.router)


@app.get("/health")
def health():
    # 어느 DB 를 쓰는지 바로 확인할 수 있게 드라이버 이름만 노출 (접속정보는 숨김)
    return {
        "status": "ok",
        # 배포에서 설정 실수를 빨리 알아채기 위한 값들 (접속정보·키는 노출하지 않는다)
        "env": config.env(),
        "cors_origins": describe_cors(),
        "logging": logging_config.describe(),
        "db": DATABASE_URL.split("://", 1)[0],
        # 어떤 채점 기준으로 돌고 있는지. 환경변수로 덮을 수 있으므로 배포된 값을
        # 눈으로 확인할 수 있어야 한다 (validation_status 도 함께 나간다).
        "scoring": scoring_config.thresholds(),
        # 요청 수 제한이 켜져 있는지. 꺼져 있다면 왜 꺼졌는지(off/external)까지.
        "rate_limit": rate_limit_module.describe_status(),
        # production 에서는 항상 비어 있다 (켜져 있으면 기동이 실패한다).
        # 개발에서 "왜 이런 결과가 나오지?" 를 빨리 좁히기 위한 값이다.
        "dev_only_flags": config.describe_dev_only_flags(),
        # 배포 후 보안 헤더가 실제로 붙었는지 확인할 수 있어야 한다
        "security_headers": security_headers.describe(),
        "asset_urls": asset_urls.describe(),
        "models": inference.status(),
        # 무거운 volume 모델은 요청 시 추론하지 않고 미리 계산된 예측을 쓴다
        "precomputed_predictions": model_predictions.summary(),
    }
