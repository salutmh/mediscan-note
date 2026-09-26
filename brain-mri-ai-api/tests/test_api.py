"""API tests. 실제 가중치(weights/best.pt 또는 MODEL_PATH)를 로드해서 실행한다."""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import inference
from app.main import app

ASSETS = Path(__file__).parent / "assets"
EXPECTED_CLASSES = {
    0: "vestibular_schwannoma",
    1: "glioma",
    2: "brain_metastasis",
    3: "ischemic_stroke",
    4: "multiple_sclerosis",
}

pytestmark = pytest.mark.skipif(
    not inference.get_model_path().is_file(),
    reason=f"model weights not found: {inference.get_model_path()}",
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # lifespan 실행 → 모델 로드
        yield c


def _post_image(client: TestClient, path: Path, filename: str | None = None):
    with open(path, "rb") as f:
        return client.post(
            "/predict", files={"file": (filename or path.name, f, "image/png")}
        )


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["model"] == "YOLO26s-Seg"
    assert body["classes"] == 5
    assert {int(k): v for k, v in body["class_names"].items()} == EXPECTED_CLASSES


def test_predict_returns_valid_structure(client):
    r = _post_image(client, ASSETS / "sample_vs.png")
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "YOLO26s-Seg 5-disease integrated"
    assert body["image_width"] > 0 and body["image_height"] > 0
    assert body["is_diagnosis"] is False
    assert "진단" in body["disclaimer"]
    assert isinstance(body["predictions"], list)

    w, h = body["image_width"], body["image_height"]
    for p in body["predictions"]:
        assert p["class_id"] in EXPECTED_CLASSES
        assert p["disease"] == EXPECTED_CLASSES[p["class_id"]]
        assert 0.0 <= p["confidence"] <= 1.0
        x1, y1, x2, y2 = p["bbox"]
        assert 0 <= x1 <= x2 <= w + 1 and 0 <= y1 <= y2 <= h + 1
        assert isinstance(p["polygon"], list)
        for x, y in p["polygon"]:
            assert -1 <= x <= w + 1 and -1 <= y <= h + 1


def test_predict_sample_vs_has_detection(client):
    """VS 샘플은 라벨이 있는 슬라이스이므로 최소 1건 검출을 기대한다."""
    r = _post_image(client, ASSETS / "sample_vs.png")
    assert r.status_code == 200
    preds = r.json()["predictions"]
    assert len(preds) >= 1
    assert all(len(p["polygon"]) >= 3 for p in preds)


def test_predict_glioma_sample_no_error(client):
    """검출 0건이어도 200 + predictions 배열이어야 한다."""
    r = _post_image(client, ASSETS / "sample_glioma.png")
    assert r.status_code == 200
    assert isinstance(r.json()["predictions"], list)


def test_predict_blank_image_returns_empty_list(client):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("L", (256, 256), 0).save(buf, format="PNG")
    buf.seek(0)
    r = client.post("/predict", files={"file": ("blank.png", buf, "image/png")})
    assert r.status_code == 200
    assert r.json()["predictions"] == []


def test_predict_jpeg_accepted(client):
    from PIL import Image

    img = Image.open(ASSETS / "sample_vs.png").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    buf.seek(0)
    r = client.post("/predict", files={"file": ("sample.jpg", buf, "image/jpeg")})
    assert r.status_code == 200


def test_predict_rejects_bad_extension(client):
    r = client.post(
        "/predict", files={"file": ("scan.dcm", io.BytesIO(b"not an image"), "application/octet-stream")}
    )
    assert r.status_code == 415


def test_predict_rejects_corrupt_png(client):
    r = client.post("/predict", files={"file": ("bad.png", io.BytesIO(b"\x89PNG garbage"), "image/png")})
    assert r.status_code == 400


def test_predict_rejects_empty_file(client):
    r = client.post("/predict", files={"file": ("empty.png", io.BytesIO(b""), "image/png")})
    assert r.status_code == 400


def test_predict_missing_file_field(client):
    r = client.post("/predict")
    assert r.status_code == 422
