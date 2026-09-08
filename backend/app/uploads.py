"""
사용자 업로드 영상 검증 (/api/analyze 전용).

**서버 검증이 권위다.** 프론트의 검사는 UX 용이고, 클라이언트가 보내는 MIME 타입이나
파일 확장자는 신뢰하지 않는다 — 실제 바이트를 열어 포맷을 확인한다.

**업로드 영상은 저장하지 않는다.** 메모리에서만 처리하고, 처리 직후 메타데이터를 제거한
새 이미지 객체로 바꿔 EXIF 등이 뒤로 흘러가지 않게 한다. 의료영상은 메타데이터에
환자 식별정보가 남아 있을 수 있어, 저장하는 순간 개인정보 보관 문제가 된다.

DICOM 은 이번 MVP 범위가 아니다 (PNG/JPEG 만). 향후 지원 시에는 픽셀 데이터뿐 아니라
DICOM 태그(환자명·ID·생년월일·검사일 등)를 반드시 제거하는 별도 파이프라인이 필요하다.
"""
import base64
import binascii
import io
import re

from PIL import Image, UnidentifiedImageError

# 디코딩 후 허용하는 최대 바이트 (12MB)
MAX_DECODED_BYTES = 12 * 1024 * 1024
# base64 는 원본의 약 4/3 배 — 디코딩 전에 길이로 먼저 걸러 큰 문자열을 디코딩하지 않는다
MAX_BASE64_CHARS = int(MAX_DECODED_BYTES * 4 / 3) + 1024

MIN_DIMENSION = 64
MAX_DIMENSION = 4096
MAX_PIXELS = MAX_DIMENSION * MAX_DIMENSION  # 압축 폭탄 방지

ALLOWED_FORMATS = {"PNG", "JPEG"}

MAX_REGION_POINTS = 20000
ALLOWED_REGION_TYPES = {"brush_mask", "point", "contour"}

# Pillow 자체 방어선도 함께 낮춘다 (기본값은 약 1.79억 픽셀)
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class UploadError(Exception):
    """검증 실패. 라우터가 status/code/message 를 그대로 응답으로 변환한다."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


_WHITESPACE = re.compile(r"\s+")


def _strip_data_url(data: str) -> str:
    if data.strip().startswith("data:") and "," in data:
        return data.split(",", 1)[1]
    return data


def _normalize_base64(payload: str) -> str:
    """엄격 검증(validate=True) 전에 안전하게 정규화한다.

    - 공백/개행 제거: JSON 을 보기 좋게 포맷하거나 긴 문자열을 줄바꿈해 보내는 클라이언트가 있다.
      (표준 base64 는 개행을 허용하지만 validate=True 는 거부하므로 먼저 지운다)
    - 패딩 보정: '=' 를 생략해 보내는 클라이언트가 있다. 길이만 4의 배수로 맞춘다.

    알파벳 검증 자체는 완화하지 않는다 — base64 가 아닌 문자가 섞이면 그대로 실패한다.
    """
    compact = _WHITESPACE.sub("", payload)
    remainder = len(compact) % 4
    if remainder:
        compact += "=" * (4 - remainder)
    return compact


def decode_image(image_base64) -> Image.Image:
    """base64 -> 검증된 PIL 이미지 (메타데이터 제거됨).

    검사 순서가 중요하다: 큰 문자열을 디코딩하기 전에 길이부터 보고,
    이미지 픽셀을 디코딩하기 전에 헤더에서 포맷·크기를 먼저 확인한다(압축 폭탄 방지).
    """
    if not isinstance(image_base64, str) or not image_base64.strip():
        raise UploadError(400, "IMAGE_REQUIRED", "분석할 영상(image_base64)이 필요합니다.")

    payload = _normalize_base64(_strip_data_url(image_base64))

    if len(payload) > MAX_BASE64_CHARS:
        raise UploadError(
            413,
            "IMAGE_TOO_LARGE",
            f"영상이 너무 큽니다. 최대 {MAX_DECODED_BYTES // (1024 * 1024)}MB 까지 업로드할 수 있습니다.",
        )

    # validate=True: base64 알파벳 밖의 문자를 조용히 버리지 않고 거부한다.
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise UploadError(400, "INVALID_IMAGE", f"영상 데이터를 해석할 수 없습니다: {exc}") from exc

    if not raw:
        raise UploadError(400, "IMAGE_REQUIRED", "영상 데이터가 비어 있습니다.")
    if len(raw) > MAX_DECODED_BYTES:
        raise UploadError(
            413,
            "IMAGE_TOO_LARGE",
            f"영상이 너무 큽니다. 최대 {MAX_DECODED_BYTES // (1024 * 1024)}MB 까지 업로드할 수 있습니다.",
        )

    # 1) 헤더만 읽어 포맷/크기 확인 (Image.open 은 지연 로딩이라 아직 픽셀을 풀지 않는다)
    try:
        probe = Image.open(io.BytesIO(raw))
        image_format = probe.format
        width, height = probe.size
    except UnidentifiedImageError as exc:
        raise UploadError(415, "UNSUPPORTED_FORMAT", "PNG 또는 JPEG 이미지가 아닙니다.") from exc
    except Image.DecompressionBombError as exc:
        raise UploadError(413, "IMAGE_TOO_LARGE", "이미지 픽셀 수가 허용 범위를 초과했습니다.") from exc
    except OSError as exc:
        raise UploadError(400, "INVALID_IMAGE", f"영상을 열 수 없습니다: {exc}") from exc

    if image_format not in ALLOWED_FORMATS:
        raise UploadError(
            415,
            "UNSUPPORTED_FORMAT",
            f"지원하지 않는 형식입니다: {image_format}. 지금은 PNG/JPEG 만 지원합니다 (DICOM 은 추후 지원).",
        )

    if width * height > MAX_PIXELS:
        raise UploadError(413, "IMAGE_TOO_LARGE", "이미지 픽셀 수가 허용 범위를 초과했습니다.")
    if width < MIN_DIMENSION or height < MIN_DIMENSION:
        raise UploadError(
            422,
            "IMAGE_DIMENSION_OUT_OF_RANGE",
            f"이미지가 너무 작습니다. 최소 {MIN_DIMENSION}×{MIN_DIMENSION} 이상이어야 합니다.",
        )
    if width > MAX_DIMENSION or height > MAX_DIMENSION:
        raise UploadError(
            422,
            "IMAGE_DIMENSION_OUT_OF_RANGE",
            f"이미지가 너무 큽니다. 최대 {MAX_DIMENSION}×{MAX_DIMENSION} 까지 지원합니다.",
        )

    # 2) 손상 여부 확인. verify() 후에는 객체를 다시 쓸 수 없으므로 새로 연다.
    try:
        Image.open(io.BytesIO(raw)).verify()
    except Exception as exc:  # PIL 은 손상 유형에 따라 다양한 예외를 던진다
        raise UploadError(400, "INVALID_IMAGE", "손상되었거나 잘린 이미지입니다.") from exc

    # 3) 실제 디코딩
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
        image = image.convert("RGB")
    except Image.DecompressionBombError as exc:
        raise UploadError(413, "IMAGE_TOO_LARGE", "이미지 픽셀 수가 허용 범위를 초과했습니다.") from exc
    except OSError as exc:
        raise UploadError(400, "INVALID_IMAGE", "손상되었거나 잘린 이미지입니다.") from exc

    return strip_metadata(image)


def strip_metadata(image: Image.Image) -> Image.Image:
    """EXIF 등 부가 정보를 떼어낸 새 이미지를 만든다.

    copy() 는 .info 를 함께 가져가므로, 픽셀 바이트만으로 새 객체를 만든다.
    (의료영상 EXIF 에 촬영기기·환자 관련 정보가 남아 있을 수 있다.)
    """
    clean = Image.frombytes(image.mode, image.size, image.tobytes())
    return clean


def validate_region(region, width: int, height: int) -> dict:
    """분석 영역(api-spec 2-6 `region`)을 검증한다."""
    if region is None:
        raise UploadError(422, "INVALID_REGION", "분석할 영역(region)이 필요합니다.")
    if not isinstance(region, dict):
        raise UploadError(422, "INVALID_REGION", "region 형식이 올바르지 않습니다.")

    region_type = region.get("type")
    if region_type not in ALLOWED_REGION_TYPES:
        raise UploadError(
            422,
            "INVALID_REGION",
            f"지원하지 않는 region.type 입니다: {region_type}",
        )

    points = region.get("points")
    if not isinstance(points, list) or not points:
        raise UploadError(422, "INVALID_REGION", "region.points 가 비어 있습니다.")
    if len(points) > MAX_REGION_POINTS:
        raise UploadError(422, "INVALID_REGION", "region.points 개수가 너무 많습니다.")

    cleaned: list[list[int]] = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            raise UploadError(422, "INVALID_REGION", "region.points 는 [x, y] 목록이어야 합니다.")
        try:
            x, y = int(point[0]), int(point[1])
        except (TypeError, ValueError) as exc:
            raise UploadError(422, "INVALID_REGION", "region.points 좌표는 숫자여야 합니다.") from exc
        if not (0 <= x < width and 0 <= y < height):
            raise UploadError(
                422,
                "INVALID_REGION",
                f"region.points 좌표가 이미지 범위를 벗어났습니다: ({x}, {y}) / {width}×{height}",
            )
        cleaned.append([x, y])

    return {"type": region_type, "points": cleaned}
