"""
사용자 영상 업로드 검증 (/api/analyze) — api-spec.md 2-6.

서버 검증이 권위다. 클라이언트가 보내는 MIME/확장자는 신뢰하지 않고 실제 바이트를 연다.
업로드 영상은 저장하지 않고 메모리에서만 처리하며, EXIF 등 메타데이터를 제거한다.
DICOM 은 이번 범위가 아니다 (PNG/JPEG 만).
"""
import base64
import io

import pytest
from PIL import Image
from app.db import SessionLocal
from app.models import Consent
from app.uploads import MAX_DECODED_BYTES, MAX_DIMENSION, MIN_DIMENSION


def _image_b64(width=256, height=256, fmt="PNG", color=(90, 90, 90), **save_kwargs) -> str:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, fmt, **save_kwargs)
    return base64.b64encode(buf.getvalue()).decode()


_DEFAULT = object()  # None 자체를 region 값으로 보낼 수 있도록 별도 sentinel 을 쓴다


def _payload(image_b64=_DEFAULT, region=_DEFAULT) -> dict:
    return {
        "image_base64": _image_b64() if image_b64 is _DEFAULT else image_b64,
        "region": {"type": "brush_mask", "points": [[10, 10], [20, 20]]} if region is _DEFAULT else region,
    }


# ------------------------------------------------------------------- 정상
def test_valid_png_is_accepted(user_a):
    res = user_a.post("/api/analyze", json=_payload())
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["disclaimer"]
    assert body["status"] in {"ok", "model_unavailable", "demo"}


def test_no_model_means_no_invented_findings(user_a, monkeypatch):
    """모델이 없을 때 소견·후보질환을 지어내면 안 된다 (기본 동작)."""
    monkeypatch.delenv("MEDISCAN_ANALYZE_DEMO", raising=False)

    body = user_a.post("/api/analyze", json=_payload()).json()

    assert body["status"] == "model_unavailable"
    assert body["is_demo"] is False
    assert body["candidate_diseases"] == []
    assert body["key_findings"] == ""
    assert body["suspected_region"] == ""
    assert body["ai_mask_url"] is None
    assert body["unavailable_reason"], "왜 못 하는지 알려줘야 한다"


def test_volume_model_reason_is_explained(user_a, monkeypatch):
    """뇌 MRI 모델은 volume 입력이라 업로드 1장으로는 분석할 수 없다는 사실을 밝힌다."""
    monkeypatch.delenv("MEDISCAN_ANALYZE_DEMO", raising=False)

    body = user_a.post("/api/analyze", json=_payload()).json()
    assert "volume" in body["unavailable_reason"]


def test_demo_mode_is_labelled_as_demo(user_a, monkeypatch):
    """데모를 켜도 '실제 분석 결과'로 보이면 안 된다."""
    monkeypatch.setenv("MEDISCAN_ANALYZE_DEMO", "1")

    body = user_a.post("/api/analyze", json=_payload()).json()

    assert body["status"] == "demo"
    assert body["is_demo"] is True
    assert "예시" in body["disclaimer"]
    assert body["candidate_diseases"]


def test_valid_jpeg_is_accepted(user_a):
    res = user_a.post("/api/analyze", json=_payload(_image_b64(fmt="JPEG")))
    assert res.status_code == 200


def test_data_url_prefix_is_accepted(user_a):
    """프론트가 canvas.toDataURL() 결과를 그대로 보내도 처리한다."""
    res = user_a.post("/api/analyze", json=_payload("data:image/png;base64," + _image_b64()))
    assert res.status_code == 200


# ------------------------------------------------------------- 포맷 위장
def test_text_disguised_as_image_is_rejected(user_a):
    fake = base64.b64encode(b"this is definitely not an image").decode()
    res = user_a.post("/api/analyze", json=_payload(fake))
    assert res.status_code == 415
    assert res.json()["detail"]["code"] == "UNSUPPORTED_FORMAT"


def test_gif_is_rejected(user_a):
    """PNG/JPEG 만 허용 — 클라이언트 MIME 이 아니라 실제 포맷으로 판단한다."""
    res = user_a.post("/api/analyze", json=_payload(_image_b64(fmt="GIF")))
    assert res.status_code == 415
    assert res.json()["detail"]["code"] == "UNSUPPORTED_FORMAT"


def test_bmp_is_rejected(user_a):
    res = user_a.post("/api/analyze", json=_payload(_image_b64(fmt="BMP")))
    assert res.status_code == 415


# --------------------------------------------------------------- 손상 파일
def test_truncated_png_is_rejected(user_a):
    full = base64.b64decode(_image_b64())
    truncated = base64.b64encode(full[: len(full) // 2]).decode()
    res = user_a.post("/api/analyze", json=_payload(truncated))
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "INVALID_IMAGE"


def test_png_header_with_garbage_body_is_rejected(user_a):
    broken = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 200).decode()
    res = user_a.post("/api/analyze", json=_payload(broken))
    assert res.status_code in {400, 415}
    assert res.json()["detail"]["code"] in {"INVALID_IMAGE", "UNSUPPORTED_FORMAT"}


def test_invalid_base64_is_rejected(user_a):
    """base64 알파벳 밖의 문자는 조용히 버려지지 않고 거부된다 (validate=True)."""
    res = user_a.post("/api/analyze", json=_payload("!!!not-base64!!!"))
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "INVALID_IMAGE"


def test_base64_with_whitespace_is_accepted(user_a):
    """줄바꿈·공백이 섞인 base64 는 정규화 후 처리한다 (정상 이미지가 깨지면 안 된다)."""
    raw = _image_b64()
    wrapped = "\n".join(raw[i : i + 76] for i in range(0, len(raw), 76))
    res = user_a.post("/api/analyze", json=_payload("  " + wrapped + "  "))
    assert res.status_code == 200, res.text


def test_base64_without_padding_is_accepted(user_a):
    """'=' 패딩을 생략해 보내는 클라이언트도 처리한다."""
    res = user_a.post("/api/analyze", json=_payload(_image_b64().rstrip("=")))
    assert res.status_code == 200, res.text


def test_data_url_with_whitespace_is_accepted(user_a):
    """data URL + 줄바꿈 조합도 그대로 동작한다."""
    raw = _image_b64()
    wrapped = "\n".join(raw[i : i + 60] for i in range(0, len(raw), 60))
    res = user_a.post("/api/analyze", json=_payload("data:image/png;base64,\n" + wrapped))
    assert res.status_code == 200, res.text


@pytest.mark.parametrize("value", ["__missing__", "", "   "])
def test_missing_image_is_rejected(user_a, value):
    payload = _payload()
    if value == "__missing__":
        payload.pop("image_base64")
    else:
        payload["image_base64"] = value
    res = user_a.post("/api/analyze", json=payload)
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "IMAGE_REQUIRED"


# ------------------------------------------------------------- 크기 제한
def test_oversized_payload_is_rejected_before_decoding(user_a):
    """디코딩 전에 base64 길이로 먼저 걸러낸다 (큰 문자열을 풀지 않는다)."""
    huge = "A" * (MAX_DECODED_BYTES * 4 // 3 + 5000)
    res = user_a.post("/api/analyze", json=_payload(huge))
    assert res.status_code == 413
    assert res.json()["detail"]["code"] == "IMAGE_TOO_LARGE"


def test_too_small_image_is_rejected(user_a):
    res = user_a.post("/api/analyze", json=_payload(_image_b64(MIN_DIMENSION - 1, MIN_DIMENSION - 1)))
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "IMAGE_DIMENSION_OUT_OF_RANGE"


def test_too_large_dimension_is_rejected(user_a):
    """압축이 잘 되는 단색 큰 이미지 = 압축 폭탄과 같은 형태. 픽셀 수로 막는다."""
    oversized = _image_b64(MAX_DIMENSION + 8, MAX_DIMENSION + 8)
    res = user_a.post("/api/analyze", json=_payload(oversized))
    assert res.status_code in {413, 422}
    assert res.json()["detail"]["code"] in {"IMAGE_TOO_LARGE", "IMAGE_DIMENSION_OUT_OF_RANGE"}


def test_dimension_boundaries_are_accepted(user_a):
    res = user_a.post("/api/analyze", json=_payload(_image_b64(MIN_DIMENSION, MIN_DIMENSION)))
    assert res.status_code == 200


# ------------------------------------------------------------ region 검증
@pytest.mark.parametrize(
    "region",
    [
        None,                                              # 없음
        {},                                                # 타입/좌표 없음
        {"type": "brush_mask"},                            # points 없음
        {"type": "brush_mask", "points": []},              # 빈 목록
        {"type": "unknown_tool", "points": [[1, 1]]},      # 미지원 타입
        {"type": "brush_mask", "points": [[1]]},           # 좌표 형식 오류
        {"type": "brush_mask", "points": [["a", "b"]]},    # 숫자 아님
        {"type": "brush_mask", "points": [[9999, 10]]},    # 이미지 범위 밖
        {"type": "brush_mask", "points": [[-5, 10]]},      # 음수 좌표
    ],
)
def test_invalid_region_is_rejected(user_a, region):
    res = user_a.post("/api/analyze", json=_payload(region=region))
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "INVALID_REGION"


def test_region_at_image_edge_is_accepted(user_a):
    region = {"type": "brush_mask", "points": [[0, 0], [255, 255]]}
    res = user_a.post("/api/analyze", json=_payload(region=region))
    assert res.status_code == 200


# ------------------------------------------------- 동의 없는 사용자 (403)
def test_analyze_blocked_without_sensitive_consent(user_a):
    with SessionLocal() as db:
        db.add(Consent(user_id=user_a.user_id, key="agree_sensitive_data", agreed=False, version="test"))
        db.commit()

    res = user_a.post("/api/analyze", json=_payload())
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "CONSENT_REQUIRED"


def test_consent_is_checked_before_image_validation(user_a):
    """동의가 없으면 이미지를 파싱하기 전에 막는다 (불필요한 처리·노출 방지)."""
    with SessionLocal() as db:
        db.add(Consent(user_id=user_a.user_id, key="agree_sensitive_data", agreed=False, version="test"))
        db.commit()

    res = user_a.post("/api/analyze", json=_payload("garbage"))
    assert res.status_code == 403  # 415/400 이 아니라 403


def test_analyze_requires_login(client):
    res = client.post("/api/analyze", json=_payload())
    assert res.status_code == 401


# --------------------------------------------------- 저장 안 함 / 메타 제거
def test_upload_is_not_persisted(user_a, tmp_path):
    """업로드 영상은 정적 폴더나 DB 어디에도 남지 않는다."""
    from app.static_files import STATIC_DIR

    before = {p.name for p in STATIC_DIR.rglob("*") if p.is_file()}
    user_a.post("/api/analyze", json=_payload())
    after = {p.name for p in STATIC_DIR.rglob("*") if p.is_file()}
    assert before == after, "업로드 영상이 정적 폴더에 저장되면 안 된다"


def test_exif_metadata_is_stripped():
    """decode_image 를 통과한 이미지에는 EXIF 등 부가 정보가 남지 않는다."""
    from app.uploads import decode_image

    img = Image.new("RGB", (128, 128), (10, 20, 30))
    exif = img.getexif()
    exif[271] = "SecretScannerVendor"  # Make
    exif[272] = "PatientDeviceModel"   # Model
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif.tobytes())
    raw = buf.getvalue()

    # 원본에는 EXIF 가 들어 있다
    assert Image.open(io.BytesIO(raw)).getexif()

    cleaned = decode_image(base64.b64encode(raw).decode())
    assert not cleaned.getexif(), "EXIF 가 제거되어야 한다"
    assert cleaned.info == {} or "exif" not in cleaned.info
    assert cleaned.size == (128, 128)


# ------------------------------------------- 사전 가용성 조회 (헛수고 방지)
def test_availability_reports_unavailable_with_reason(user_a):
    """사용자가 영상을 올리고 ROI 를 칠한 뒤에야 "준비 중"을 만나면 노력이 낭비된다."""
    body = user_a.get("/api/analyze/availability").json()

    assert body["available"] is False
    assert body["unavailable_reason"]
    # volume 입력 모델이라는 사실을 사실대로 알린다
    assert "volume" in body["unavailable_reason"]
    assert body["disclaimer"]


def test_availability_requires_authentication(client):
    assert client.get("/api/analyze/availability").status_code == 401


def test_availability_matches_actual_analyze_result(user_a):
    """미리 알려준 것과 실제 결과가 다르면 안내가 거짓말이 된다."""
    availability = user_a.get("/api/analyze/availability").json()
    actual = user_a.post("/api/analyze", json=_payload()).json()

    if availability["available"]:
        assert actual["status"] in {"ok", "demo"}
    else:
        assert actual["status"] in {"model_unavailable", "demo"}
        if actual["status"] == "model_unavailable":
            assert actual["unavailable_reason"] == availability["unavailable_reason"]


def test_availability_reports_demo_mode(user_a, monkeypatch):
    """데모 예시가 실제 분석처럼 보이면 안 되므로 상태를 알린다."""
    monkeypatch.setenv("MEDISCAN_ANALYZE_DEMO", "1")
    assert user_a.get("/api/analyze/availability").json()["is_demo"] is True
