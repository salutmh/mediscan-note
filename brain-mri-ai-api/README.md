# brain-mri-ai-api

> mediscan-note 저장소의 하위 폴더(`mediscan-note/brain-mri-ai-api`)입니다.
> 기존 `ai_service`(미리 계산된 데모 케이스 결과 조회)와 달리, 이 API는 업로드한 이미지를 **실시간으로 추론**합니다.
> 두 서비스 모두 기본 포트가 8000이므로 함께 띄울 때는 이 API를 다른 포트(예: 8001)로 실행하세요.

뇌 MRI 이미지 한 장을 업로드하면 **5가지 질환 영역을 찾아 위치(박스)와 외곽선(폴리곤)을 돌려주는 HTTP API**입니다.
YOLO26s-Seg 세그멘테이션 모델 1개로 5질환을 통합 추론합니다.

> **주의: 이 모델은 교육/연구용 참고 모델입니다. 의료 진단 도구가 아니며, 결과를 진단·치료 판단에 사용하면 안 됩니다.**
> 응답의 `confidence`는 "모델의 확신 점수(model confidence score)"이지 질병에 걸릴 확률이 아닙니다.

## 지원 질환 (5 클래스)

| class_id | disease | 한글 |
|---|---|---|
| 0 | vestibular_schwannoma | 전정신경초종 |
| 1 | glioma | 신경교종 |
| 2 | brain_metastasis | 뇌 전이암 |
| 3 | ischemic_stroke | 허혈성 뇌졸중 |
| 4 | multiple_sclerosis | 다발성 경화증 |

## 1. 설치

Python 3.10 이상이 필요합니다. (3.11에서 검증)

```bash
# mediscan-note 저장소의 하위 폴더입니다.
git clone https://github.com/salutmh/mediscan-note.git
cd mediscan-note/brain-mri-ai-api

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

첫 설치 시 PyTorch와 ultralytics가 함께 설치되어 몇 분 걸릴 수 있습니다.
GPU가 없어도 CPU로 동작합니다 (이미지 1장당 약 0.2~2초).

## 2. 모델 파일 위치

가중치 파일 `best.pt`(약 92MB)는 저장소에 **포함되어 있지 않습니다.**
GitHub Release에서 내려받아 아래 위치에 넣으세요.

- Release 페이지: https://github.com/salutmh/mediscan-note/releases/tag/brain-mri-ai-api-v0.1.0
- 직접 다운로드: https://github.com/salutmh/mediscan-note/releases/download/brain-mri-ai-api-v0.1.0/best.pt

```
brain-mri-ai-api/
  weights/
    best.pt   ← 여기 (파일명 그대로 best.pt)
```

명령으로 받으려면 (프로젝트 루트 `brain-mri-ai-api/` 에서):

```bash
# Windows PowerShell
Invoke-WebRequest -Uri https://github.com/salutmh/mediscan-note/releases/download/brain-mri-ai-api-v0.1.0/best.pt -OutFile weights\best.pt

# macOS / Linux
curl -L -o weights/best.pt https://github.com/salutmh/mediscan-note/releases/download/brain-mri-ai-api-v0.1.0/best.pt
```

받은 파일이 맞는지 확인하려면 MD5가 `5ab0561235ab4aeb27f11ce2a1afb4da`, 크기가 92,393,497 bytes 인지 보면 됩니다.
Release 태그는 `brain-mri-ai-api-v0.1.0`, 모델은 YOLO26s-Seg 5질환 통합 모델(v0.1.0)입니다.

다른 위치에 두고 싶으면 `.env`에서 `MODEL_PATH`로 지정합니다.

```bash
cp .env.example .env     # Windows: copy .env.example .env
```

`.env` 내용 예:

```
MODEL_PATH=./weights/best.pt
HOST=0.0.0.0
PORT=8000
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000
CONF_THRESHOLD=0.25
MAX_UPLOAD_MB=20
```

| 변수 | 의미 | 기본값 |
|---|---|---|
| `MODEL_PATH` | 가중치 파일 경로 | `./weights/best.pt` |
| `HOST` / `PORT` | 서버 주소/포트 (uvicorn 옵션으로도 지정 가능) | `0.0.0.0` / `8000` |
| `CORS_ORIGINS` | 호출을 허용할 프론트엔드 주소 목록 (쉼표 구분) | localhost:5173, 3000, 8080 |
| `CONF_THRESHOLD` | 이 값 미만의 검출은 버림 (0~1) | `0.25` |
| `MAX_UPLOAD_MB` | 업로드 허용 최대 크기 | `20` |

## 3. 서버 실행

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

정상 실행 시 로그에 `Model loaded on device=cpu classes={...}` 와 `Uvicorn running on http://0.0.0.0:8000` 이 보입니다.

- API 문서(자동 생성): http://localhost:8000/docs
- 상태 확인: http://localhost:8000/health

## 4. API

### GET /health

서버와 모델이 준비되었는지 확인합니다.

```json
{
  "status": "ok",
  "model": "YOLO26s-Seg",
  "classes": 5,
  "class_names": {
    "0": "vestibular_schwannoma",
    "1": "glioma",
    "2": "brain_metastasis",
    "3": "ischemic_stroke",
    "4": "multiple_sclerosis"
  },
  "device": "cpu",
  "model_path": "weights/best.pt"
}
```

### POST /predict

- 형식: `multipart/form-data`
- 필드: `file` = MRI 이미지 (PNG / JPG / JPEG)
- 흑백(1채널) 이미지도 그대로 보내면 됩니다.

**요청 예 (curl)**

```bash
curl -X POST http://localhost:8000/predict -F "file=@tests/assets/sample_vs.png"
```

**응답 예 (검출 1건)**

```json
{
  "model": "YOLO26s-Seg 5-disease integrated",
  "image_width": 512,
  "image_height": 512,
  "predictions": [
    {
      "class_id": 0,
      "disease": "vestibular_schwannoma",
      "confidence": 0.8678,
      "bbox": [206.4, 297.7, 230.6, 323.8],
      "polygon": [[216.0, 298.0], [214.0, 300.0], [213.0, 300.0], "..."]
    }
  ],
  "confidence_note": "confidence는 model confidence score이며 질병 확률이 아닙니다.",
  "is_diagnosis": false,
  "disclaimer": "이 결과는 교육/연구용 AI 모델의 참고 결과이며 의료 진단 결과가 아닙니다. 실제 진단은 반드시 의료 전문가가 수행해야 합니다."
}
```

**응답 예 (검출 0건)**: 오류가 아니라 빈 배열입니다.

```json
{
  "model": "YOLO26s-Seg 5-disease integrated",
  "image_width": 240,
  "image_height": 240,
  "predictions": [],
  "confidence_note": "...",
  "is_diagnosis": false,
  "disclaimer": "..."
}
```

**응답 필드 설명**

| 필드 | 설명 |
|---|---|
| `image_width`, `image_height` | 업로드한 원본 이미지 크기 (px) |
| `predictions[].class_id` / `disease` | 클래스 번호와 이름 |
| `predictions[].confidence` | 모델 확신 점수 0~1. **질병 확률 아님** |
| `predictions[].bbox` | `[x1, y1, x2, y2]` 원본 이미지 픽셀 좌표 |
| `predictions[].polygon` | 병변 외곽선 `[[x, y], ...]` 원본 이미지 픽셀 좌표. 마스크 전체 대신 폴리곤으로 전달해 응답을 작게 유지 |
| `is_diagnosis` | 항상 `false` |
| `disclaimer` | 교육/연구용 안내 문구 |

**오류 응답**

| 상황 | 상태 코드 |
|---|---|
| `file` 필드가 없음 | 422 |
| 확장자가 png/jpg/jpeg가 아님 (예: .dcm) | 415 |
| 빈 파일 또는 이미지 디코딩 실패 | 400 |
| 파일이 `MAX_UPLOAD_MB` 초과 | 413 |

## 5. 뷰어(프론트엔드) 연결 예제

### JavaScript (브라우저 / Vue / React)

```javascript
// file: <input type="file"> 에서 선택한 File 객체
async function analyzeMri(file) {
  const formData = new FormData()
  formData.append("file", file)

  const response = await fetch("http://localhost:8000/predict", {
    method: "POST",
    body: formData,
  })
  if (!response.ok) {
    throw new Error(`API error ${response.status}: ${await response.text()}`)
  }

  const result = await response.json()
  // result.predictions[i].bbox / polygon 은 원본 이미지 픽셀 좌표이므로
  // 화면 표시 배율(displayWidth / result.image_width)을 곱해서 그리면 됩니다.
  return result
}
```

캔버스에 폴리곤을 그리는 예:

```javascript
function drawPredictions(ctx, result, scale) {
  for (const p of result.predictions) {
    ctx.beginPath()
    p.polygon.forEach(([x, y], i) =>
      i === 0 ? ctx.moveTo(x * scale, y * scale) : ctx.lineTo(x * scale, y * scale)
    )
    ctx.closePath()
    ctx.strokeStyle = "red"
    ctx.stroke()
    ctx.fillText(`${p.disease} (${p.confidence.toFixed(2)})`, p.bbox[0] * scale, p.bbox[1] * scale - 4)
  }
}
```

프론트엔드 주소가 `localhost:5173`, `3000`, `8080`이 아니면 `.env`의 `CORS_ORIGINS`에 추가해야 브라우저에서 호출됩니다.

### Python (requests)

```python
import requests

with open("tests/assets/sample_vs.png", "rb") as f:
    r = requests.post("http://localhost:8000/predict", files={"file": f})

r.raise_for_status()
result = r.json()
for p in result["predictions"]:
    print(p["disease"], p["confidence"], p["bbox"], len(p["polygon"]), "points")
```

## 6. 테스트

```bash
pytest tests -v
```

실제 `best.pt`를 로드해 `/health`, `/predict`(검출 있음/없음, JPEG), 잘못된 확장자, 손상 파일, 빈 파일, 필드 누락을 검사합니다.
가중치가 없으면 테스트는 자동으로 skip 됩니다.

## 7. 프로젝트 구조

```
brain-mri-ai-api/
  app/
    main.py        # FastAPI 앱, /health, /predict, CORS
    inference.py   # 모델 로드 + 추론 + 폴리곤 변환
    schemas.py     # 응답 JSON 스키마
  weights/         # best.pt 를 여기에 (git 제외)
  tests/
    test_api.py
    assets/        # 테스트용 샘플 MRI PNG 2장 (출처는 8절)
  .env.example
  requirements.txt
```

## 8. 테스트 이미지 출처 및 라이선스 (`tests/assets/`)

`tests/assets/`의 PNG 2장은 아래 TCIA(The Cancer Imaging Archive) 공개 컬렉션에서 가져온
**파생본**입니다. 원본 3D 볼륨(DICOM / NIfTI)에서 축 방향 슬라이스 1장을 추출해 0~255 uint8로
정규화한 뒤 PNG로 저장한 것이며, 원본 파일이 아닙니다. 두 컬렉션 모두 **CC BY 4.0** 라이선스입니다.

| 파일 | 원본 컬렉션 | 원본 케이스 / 슬라이스 | 라이선스 |
|---|---|---|---|
| `sample_vs.png` | Vestibular-Schwannoma-SEG (TCIA) | VS-SEG-202, T1 MRI (DICOM), slice z=031 | CC BY 4.0 |
| `sample_glioma.png` | UTSW-Glioma (TCIA) | BT0002, T1CE MRI (NIfTI), slice z=073 | CC BY 4.0 |

**Vestibular-Schwannoma-SEG** (DOI: [10.7937/TCIA.9YTJ-5Q73](https://doi.org/10.7937/TCIA.9YTJ-5Q73))
> Shapey, J., Kujawa, A., Dorent, R., Wang, G., Bisdas, S., Dimitriadis, A., Grishchuk, D., Paddick, I., Kitchen, N., Bradford, R., Saeed, S., Ourselin, S., & Vercauteren, T. (2021). *Segmentation of Vestibular Schwannoma from Magnetic Resonance Imaging: An Open Annotated Dataset and Baseline Algorithm* (version 2) [Data set]. The Cancer Imaging Archive. https://doi.org/10.7937/TCIA.9YTJ-5Q73
>
> Shapey, J. et al. (2021). Segmentation of vestibular schwannoma from MRI, an open annotated dataset and baseline algorithm. *Scientific Data*, 8(1). https://doi.org/10.1038/s41597-021-01064-w

**UTSW-Glioma** (DOI: [10.7937/DFAE-1B86](https://doi.org/10.7937/DFAE-1B86))
> Reddy, D., Saadat, N., Holcomb, J., Wagner, B., Truong, N., Bowerman, J., Hatanpaa, K., Patel, T., Pinho, M., Yu, F., Zhang, K., Lodhi, S., Madhuranthakam, A., Bangalore Yogananda, C. G., & Maldjian, J. (2026). *The University of Texas Southwestern Glioma MRI dataset with molecular marker characterization and segmentations (UTSW-Glioma)* (Version 1) [Data set]. The Cancer Imaging Archive. https://doi.org/10.7937/DFAE-1B86

**TCIA** (공통)
> Clark, K., Vendt, B., Smith, K., et al. (2013). The Cancer Imaging Archive (TCIA): Maintaining and Operating a Public Information Repository. *Journal of Digital Imaging*, 26(6), 1045–1057. https://doi.org/10.1007/s10278-013-9622-7

원본 데이터는 각 컬렉션 페이지(https://www.cancerimagingarchive.net/)에서 받을 수 있으며,
재배포 시 위 인용과 CC BY 4.0 표시를 유지해야 합니다.

## 9. 면책

이 저장소의 모델과 API는 교육 및 연구 목적의 참고용입니다.
의료기기가 아니며 임상 진단, 치료 결정, 환자 관리에 사용해서는 안 됩니다.
