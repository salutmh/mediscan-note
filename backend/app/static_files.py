"""
케이스 영상/마스크 정적 파일.

지금까지는 자리표시자 영상이 frontend/public 아래에 있어서 프론트가 직접 서빙했다.
하지만 실제 채점은 백엔드가 기준 마스크 파일을 **읽어야** 하므로, 케이스 자산의
소유권을 백엔드로 옮긴다.

  backend/app/static/images/   케이스 원본 영상
  backend/app/static/results/  기준 마스크 / 모델 출력 마스크

DB 에는 "/static/images/202_t1.png" 처럼 루트 상대 경로만 저장하고, 응답을 만들 때
MEDISCAN_PUBLIC_BASE 를 붙여 절대 URL 로 내려준다. 배포 도메인이 바뀌어도 DB 는 그대로다.

프론트가 다른 도메인(5173)에서 이 이미지를 canvas 로 읽어야 하므로(화면 3 겹침 색상 계산)
CORS 허용 헤더가 필요하다 — main.py 의 CORSMiddleware 가 처리한다.
"""
import os
from contextvars import ContextVar
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
STATIC_URL_PREFIX = "/static"

# 배포 시 실제 API 도메인으로 설정 (예: https://api.mediscan.example.com)
# **미설정이면 요청이 들어온 주소를 그대로 쓴다** (아래 _request_base).
# 예전에는 http://localhost:8000 으로 고정돼 있어서, 백엔드를 다른 포트로 띄우면
# 영상·마스크 URL 만 8000 을 가리켜 화면이 조용히 깨졌다.
PUBLIC_BASE = os.getenv("MEDISCAN_PUBLIC_BASE", "").rstrip("/")

# 개발 기본 포트. 요청 컨텍스트가 없을 때(스크립트·테스트)만 쓰인다.
FALLBACK_BASE = "http://localhost:8010"

_request_base: ContextVar[str] = ContextVar("mediscan_request_base", default="")


def set_request_base(base: str | None) -> None:
    """요청마다 미들웨어가 호출한다 (app/main.py)."""
    _request_base.set((base or "").rstrip("/"))


def public_base() -> str:
    """환경변수 > 현재 요청 주소 > 개발 기본값 순."""
    return PUBLIC_BASE or _request_base.get() or FALLBACK_BASE


def ensure_dirs() -> None:
    (STATIC_DIR / "images").mkdir(parents=True, exist_ok=True)
    (STATIC_DIR / "results").mkdir(parents=True, exist_ok=True)


def absolute_url(path: str | None) -> str | None:
    """DB 의 루트 상대 경로를 프론트가 바로 쓸 수 있는 절대 URL 로."""
    if not path:
        return None
    if path.startswith(("http://", "https://")):
        return path
    base = public_base()
    return f"{base}{path if path.startswith('/') else '/' + path}"


def resolve_local_path(url: str | None) -> Path | None:
    """반대로, URL 에서 로컬 파일 경로를 찾는다 (채점에서 파일을 읽을 때).

    /static/... 뿐 아니라 예전 형식(/images/..., /results/...)도 받아준다.
    """
    if not url:
        return None
    path = url
    # 어떤 host/port 로 만들어진 절대 URL 이든 경로만 남긴다
    for prefix in (PUBLIC_BASE, public_base(), "http://localhost:8000", "http://127.0.0.1:8000"):
        if prefix and path.startswith(prefix):
            path = path[len(prefix) :]
            break
    else:
        if path.startswith(("http://", "https://")):
            from urllib.parse import urlparse

            path = urlparse(path).path
    if path.startswith(STATIC_URL_PREFIX):
        relative = path[len(STATIC_URL_PREFIX) :].lstrip("/")
    else:
        relative = path.lstrip("/")
    candidate = (STATIC_DIR / relative).resolve()
    # 경로 탈출 방지
    try:
        candidate.relative_to(STATIC_DIR.resolve())
    except ValueError:
        return None
    return candidate if candidate.exists() else None
