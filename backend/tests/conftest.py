"""
테스트 공통 설정.

주의: app 을 import 하기 **전에** 환경변수를 설정해야 한다.
`app/db.py` 와 `app/security.py` 가 import 시점에 os.getenv 를 읽기 때문에,
여기서 먼저 임시 DB 경로와 테스트용 서명 키를 넣는다.
"""
import base64
import io
import os
import tempfile
from pathlib import Path

# --- app import 이전에 실행되어야 하는 설정 -----------------------------------
_TMP_DIR = Path(tempfile.mkdtemp(prefix="mediscan-test-"))
# 기본은 임시 SQLite. **PostgreSQL 로도 그대로 돌려볼 수 있어야 한다** —
# 배포는 PostgreSQL 인데 테스트가 SQLite 에서만 돌면 이식성 문제를 배포에서 처음 만난다.
#   MEDISCAN_TEST_DATABASE_URL=postgresql+psycopg2://... pytest
# (docs/RELEASE_READINESS.md "PostgreSQL 검증" 참고)
os.environ["DATABASE_URL"] = os.environ.get(
    "MEDISCAN_TEST_DATABASE_URL",
    f"sqlite:///{(_TMP_DIR / 'test.db').as_posix()}",
)
os.environ["MEDISCAN_SECRET_KEY"] = "test-only-secret-key"
os.environ["MEDISCAN_TOKEN_TTL"] = "3600"
# 합성 mock 케이스(VS-SEG-202/115)는 **테스트 픽스처로만** 쓴다. 개발/운영 DB 에는 들어가지 않는다.
os.environ["MEDISCAN_SEED_MOCK_CASES"] = "1"
# ---------------------------------------------------------------------------

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Consent,
    LearningEvent,
    PasswordResetCode,
    RevokedToken,
    Submission,
    User,
)

# seed.py 의 REFERENCE_SHAPES 와 같은 값 (VS-SEG-202 기준 병변)
CASE_ID = "VS-SEG-202"
LESION = {"cx": 338, "cy": 307, "r": 32}
IMAGE_SIZE = 512

REQUIRED_CONSENTS = {
    "agree_terms": True,
    "agree_privacy": True,
    "agree_sensitive_data": True,
    "agree_ai_notice": True,
    "agree_age14": True,
    "agree_marketing": False,
}


@pytest.fixture(scope="session", autouse=True)
def _database():
    """스키마 + 시드를 세션 시작 시 한 번 만든다.

    client 픽스처의 lifespan 에서도 init_db 가 돌지만, client 를 쓰지 않는 테스트 모듈
    (예: 순수 함수 테스트)에서도 _clean_user_data 가 테이블을 지우려 하므로 여기서 보장한다.
    """
    from app.db import init_db

    init_db()


@pytest.fixture(scope="session")
def client():
    """TestClient 진입 시 lifespan 이 돌면서 마이그레이션 + 케이스 시드까지 수행된다."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _static_dir_is_untouched():
    """테스트는 앱의 실제 static 폴더(케이스 영상·기준 마스크)를 절대 바꾸면 안 된다.

    모든 테스트 산출물은 pytest tmp_path 아래에만 만든다.
    (과거 가짜 모델 테스트가 static/images 에 _fakepred.png 를 남긴 적이 있어 가드를 둔다.)
    """
    from app.static_files import STATIC_DIR

    def snapshot() -> dict[str, int]:
        return {
            str(p.relative_to(STATIC_DIR)): p.stat().st_size
            for p in STATIC_DIR.rglob("*")
            if p.is_file()
        }

    before = snapshot()
    yield
    after = snapshot()
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    assert not (added or removed or changed), (
        f"테스트가 앱 static 폴더를 변경했습니다 "
        f"(추가={added}, 삭제={removed}, 변경={changed}). tmp_path 를 쓰세요."
    )


@pytest.fixture(autouse=True)
def _isolated_model_predictions(tmp_path, monkeypatch):
    """테스트는 앱의 실제 예측 sidecar(app/static/cases/*/prediction.json)를 읽지 않는다.

    실데이터 케이스와 mock 픽스처가 같은 case_id(VS-SEG-202)를 쓰기 때문에, 격리하지 않으면
    실제 모델 예측이 테스트 응답에 섞여 들어온다. sidecar 가 필요한 테스트는 직접 넣는다.
    """
    from app import model_predictions

    monkeypatch.setattr(model_predictions, "CASES_DIR", tmp_path / "no-predictions")
    model_predictions.clear_cache()
    yield
    model_predictions.clear_cache()


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """rate limit 카운터를 테스트마다 비운다.

    미들웨어가 프로세스 안 메모리에 요청 시각을 쌓으므로, 비우지 않으면 앞 테스트의
    로그인 시도가 뒤 테스트의 한도를 깎아 **테스트 순서에 따라 실패**하게 된다.
    (rate limit 자체를 검증하는 테스트는 tests/test_rate_limit.py 에 따로 있다.)
    """
    from app import rate_limit

    rate_limit.reset()
    yield
    rate_limit.reset()


@pytest.fixture(autouse=True)
def _clean_user_data():
    """테스트마다 사용자 데이터를 비운다. 케이스(시드 데이터)는 유지.

    **자식 테이블을 먼저, 명시적으로 지운다.** `db.query(User).delete()` 는 대량 삭제라
    ORM 의 cascade 를 타지 않는다 — 빠뜨리면 learning_events 같은 행이 테스트 내내 쌓이고,
    전체 건수를 세는 테스트가 앞 테스트의 잔여물에 걸려 넘어진다.
    사용자 데이터 테이블을 추가하면 여기에도 추가할 것.
    """
    yield
    with SessionLocal() as db:
        db.query(LearningEvent).delete()
        db.query(PasswordResetCode).delete()
        db.query(RevokedToken).delete()
        db.query(Submission).delete()
        db.query(Consent).delete()
        db.query(User).delete()
        db.commit()


# --------------------------------------------------------------------- 헬퍼
def _mask_base64(cx: int, cy: int, r: int) -> str:
    """프론트 캔버스가 만드는 것과 같은 형태(투명 배경 + 불투명 마스크)의 PNG."""
    img = Image.new("RGBA", (IMAGE_SIZE, IMAGE_SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture
def roi_match() -> dict:
    """기준 병변을 정확히 덮는 ROI -> match 가 나와야 한다."""
    return {
        "type": "brush_mask",
        "points": [[LESION["cx"], LESION["cy"]]],
        "mask_png_base64": _mask_base64(LESION["cx"], LESION["cy"], LESION["r"]),
    }


@pytest.fixture
def roi_mismatch() -> dict:
    """병변과 완전히 떨어진 ROI -> mismatch 가 나와야 한다."""
    return {
        "type": "brush_mask",
        "points": [[100, 120]],
        "mask_png_base64": _mask_base64(100, 120, 30),
    }


class UserSession:
    """가입까지 끝난 테스트 사용자."""

    def __init__(self, client: TestClient, email: str, password: str, payload: dict):
        self._client = client
        self.email = email
        self.password = password
        self.user_id = payload["user_id"]
        self.token = payload["access_token"]

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, path: str, **kwargs):
        return self._client.get(path, headers=self.headers, **kwargs)

    def post(self, path: str, json=None, **kwargs):
        return self._client.post(path, json=json, headers=self.headers, **kwargs)

    def put(self, path: str, json=None, **kwargs):
        return self._client.request("PUT", path, json=json, headers=self.headers, **kwargs)

    def patch(self, path: str, json=None, **kwargs):
        return self._client.request("PATCH", path, json=json, headers=self.headers, **kwargs)

    def delete(self, path: str, json=None, **kwargs):
        return self._client.request("DELETE", path, json=json, headers=self.headers, **kwargs)

    def submit(self, roi: dict, case_id: str = CASE_ID):
        return self.post(f"/api/cases/{case_id}/submit", json={"roi": roi})


@pytest.fixture
def make_user(client):
    """이메일 가입 사용자를 만들어 주는 팩토리. 테스트마다 겹치지 않는 이메일을 쓴다."""
    counter = {"n": 0}

    def _make(nickname: str = "테스트") -> UserSession:
        counter["n"] += 1
        email = f"user{counter['n']}@example.com"
        password = "pw12345678"
        res = client.post(
            "/api/auth/signup",
            json={
                "email": email,
                "password": password,
                "nickname": nickname,
                "consents": dict(REQUIRED_CONSENTS),
            },
        )
        assert res.status_code == 200, res.text
        return UserSession(client, email, password, res.json())

    return _make


@pytest.fixture
def admin_session(make_user) -> UserSession:
    """운영자 세션.

    일반 사용자를 만든 뒤 **DB 에서** 승격한다 — 웹으로 스스로 관리자가 되는 경로는 없다
    (실제 운영에서도 scripts/grant_admin.py 로만 지정한다).
    """
    session = make_user("운영자")
    with SessionLocal() as db:
        db.get(User, session.user_id).is_admin = True
        db.commit()
    return session


@pytest.fixture
def user_a(make_user) -> UserSession:
    return make_user("사용자A")


@pytest.fixture
def user_b(make_user) -> UserSession:
    return make_user("사용자B")
