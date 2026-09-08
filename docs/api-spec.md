# 메디스캔노트 — API 명세 & 화면별 기능정의서 (프론트 개발용)

> **계약 버전: v0.4** (2026-09-08)
> v0.3 대비 변경: `explanation` 을 3층 구조(`case_facts`/`disease_info`/`case_findings`) +
> `content_levels` 로 재구성하고 평평한 `key_findings`/`review_status` 제거,
> `ai_prediction` 에 `detected`/`representative_slice_dice`/`computed_at` 추가,
> `/api/analyze` 에 `status`/`is_demo`/`unavailable_reason` 추가(고정 mock 제거),
> `cases` 를 volume 단위로 보고 `case_slices` 추가.
>
> v0.3 (v0.2 대비): `ai_mask_url`→`reference_mask_url`, `solved`→`has_matched`+`needs_review`,
> `gradable`/`evaluation`/`ai_prediction` 추가, 채점 기준을 전문가 검수 마스크로 고정, ROI 보정 제거.

> 목적: 모델(V1/V2/V3)이 바뀌어도 프론트가 다시 손댈 필요 없도록, 프론트 ↔ API 사이의 계약을 먼저 고정한다.
> 프론트는 아래 명세와 동일한 형태의 mock JSON으로 먼저 개발하고, 나중에 fetch 주소만 실제 API로 바꾼다.

---

## 0. 공통 규칙

- Base URL: `/api` (로컬 개발 시 `http://localhost:8010/api`, mock 개발 시 `/mock`)
- 모든 응답은 JSON, 실패 시 아래 공통 에러 포맷 사용

```json
{
  "error": true,
  "code": "CASE_NOT_FOUND",
  "message": "해당 케이스를 찾을 수 없습니다."
}
```

- 이미지/마스크는 URL로 전달 (base64 금지 — 응답 크기·렌더 속도 문제)
  **구현됨**: 백엔드가 `/static/...` 로 직접 서빙하고 응답에는 절대 URL 로 내려준다
  (`http://localhost:8010/static/cases/VS-SEG-202/slices/slice_035.png`).
  도메인은 `MEDISCAN_PUBLIC_BASE` 환경변수이며, **비워 두면 요청이 들어온 주소를 그대로 쓴다.**
  프론트가 canvas 로 마스크 픽셀을 읽어야 하므로 CORS 허용 헤더가 함께 나간다.
- 날짜: ISO 8601 (`2026-09-10T14:00:00+09:00`)
- 부위 코드: `brain_mri` | `brain_ct` | `chest_xray` | `abdomen_ct` | `knee_mri`
- `/api/cases/*`, `/api/wrong-notes/*`, `/api/analyze` 는 로그인 필요 (헤더 `Authorization: Bearer <token>`).
  토큰 없으면 401. **구현됨** — 토큰 없음은 `UNAUTHORIZED`, 서명 불일치/만료는 `INVALID_TOKEN` 으로 401.
- 실패 응답은 FastAPI 관례에 따라 위 공통 포맷이 `detail` 안에 담겨 나간다:
  `{"detail": {"error": true, "code": "CASE_NOT_FOUND", "message": "..."}}`.
  프론트 공통 fetch 유틸이 두 형태를 모두 같은 에러 객체로 정규화한다.

**주요 에러 코드**

| code | HTTP | 상황 |
|---|---|---|
| `UNAUTHORIZED` | 401 | 토큰 없음 |
| `INVALID_TOKEN` | 401 | 서명 불일치 / 만료 |
| `USER_NOT_FOUND` | 401 | 토큰의 사용자가 존재하지 않음 |
| `CONSENT_REQUIRED` | 400 / 403 | 가입 시 필수 동의 누락 / 민감정보 동의 없이 분석 요청 |
| `EMAIL_ALREADY_EXISTS` | 409 | 이메일 중복 |
| `CASE_NOT_FOUND` | 404 | 케이스 없음 |
| `CASE_NOT_GRADABLE` | 422 | 기준 마스크가 없어 채점 불가 (이력 저장 안 함) |
| `INVALID_ROI` | 400 | roi 누락 / 마스크 디코딩 실패 / 빈 마스크 |
| `IMAGE_REQUIRED` | 400 | 분석 요청에 영상이 없음 |
| `INVALID_IMAGE` | 400 | 손상·잘린 이미지 |
| `UNSUPPORTED_FORMAT` | 415 | PNG/JPEG 가 아님 |
| `IMAGE_TOO_LARGE` | 413 | 용량 또는 픽셀 수 초과 |
| `IMAGE_DIMENSION_OUT_OF_RANGE` | 422 | 이미지 크기가 허용 범위 밖 |
| `INVALID_REGION` | 422 | region 형식·좌표 오류 |

---

## 1. 회원가입 / 로그인

의료영상(민감정보)을 다루는 서비스라, 가입 시 아래 4개 필수 동의를 반드시 받는다.
동의 없이는 계정 생성 자체가 불가하다 (서버에서 강제 검증).

**필수 동의 항목**
| 키 | 내용 |
|---|---|
| `agree_terms` | 서비스 이용약관 동의 |
| `agree_privacy` | 개인정보 수집·이용 동의 |
| `agree_sensitive_data` | 의료영상 등 민감정보 처리 동의 (개인정보보호법상 별도 동의 필요) |
| `agree_ai_notice` | "AI 분석 결과는 학습 참고용이며 확정 진단이 아님을 확인했습니다" |
| `agree_age14` | 만 14세 이상입니다 |

**선택 동의**
| 키 | 내용 |
|---|---|
| `agree_marketing` | 이벤트·마케팅 정보 수신 동의 |

동의 이력은 `consents` 테이블에 사용자별로 **동의 시각 + 약관 버전**과 함께 저장한다 (나중에 약관이
바뀌어도 "이 사용자가 몇 번 버전에 언제 동의했는지" 증빙이 남아야 함).

### 1-1. POST /api/auth/signup — 이메일 회원가입

**Request**
```json
{
  "email": "user@example.com",
  "password": "********",
  "nickname": "온",
  "consents": {
    "agree_terms": true,
    "agree_privacy": true,
    "agree_sensitive_data": true,
    "agree_ai_notice": true,
    "agree_age14": true,
    "agree_marketing": false
  }
}
```

필수 동의 중 하나라도 `false`면 `400 CONSENT_REQUIRED`로 거부.

**Response**
```json
{
  "user_id": "u_001",
  "email": "user@example.com",
  "nickname": "온",
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer"
}
```

### 1-2. POST /api/auth/login — 이메일 로그인

**Request**: `{ "email": "user@example.com", "password": "********" }`
**Response**: 1-1과 동일한 형태 (`user_id`, `access_token` 등)

### 1-3. POST /api/auth/social-login — SNS 간편가입/로그인

카카오·구글·네이버 등에서 받은 토큰을 그대로 백엔드에 전달 → 최초 로그인이면 계정 자동 생성.
**최초 가입인 경우도 동의 없이는 계정을 만들지 않는다** — 프론트에서 SNS 인증 직후, 계정이 없으면
동의 화면을 먼저 띄우고 `consents`를 함께 보내도록 흐름을 짠다 (아래 화면 0 참고).

**Request**
```json
{
  "provider": "kakao",
  "provider_token": "...",
  "consents": {
    "agree_terms": true,
    "agree_privacy": true,
    "agree_sensitive_data": true,
    "agree_ai_notice": true,
    "agree_age14": true,
    "agree_marketing": false
  }
}
```
> 이미 가입된 사용자의 재로그인이면 `consents`는 무시(또는 생략 가능).

**Response**: 1-1과 동일 + `is_new_user: true/false`

### 1-4. GET /api/auth/me

현재 로그인한 사용자 정보 확인 (토큰 유효성 체크용)

**Response**
```json
{ "user_id": "u_001", "email": "user@example.com", "nickname": "온" }
```

### 1-5. GET /api/consents/current-version

가입/동의 화면을 그릴 때 프론트가 "지금 보여줘야 할 약관 버전과 문구"를 받아오는 용도.

**Response**
```json
{
  "version": "2026-09-01",
  "items": [
    { "key": "agree_terms", "title": "서비스 이용약관 동의", "required": true, "url": "/legal/terms" },
    { "key": "agree_privacy", "title": "개인정보 수집·이용 동의", "required": true, "url": "/legal/privacy" },
    { "key": "agree_sensitive_data", "title": "의료영상 등 민감정보 처리 동의", "required": true, "url": "/legal/sensitive" },
    { "key": "agree_ai_notice", "title": "AI 분석 결과는 학습 참고용이며 확정 진단이 아닙니다", "required": true, "url": null },
    { "key": "agree_age14", "title": "만 14세 이상입니다", "required": true, "url": null },
    { "key": "agree_marketing", "title": "이벤트·마케팅 정보 수신 동의", "required": false, "url": null }
  ]
}
```

---

## 2. 케이스 · 판독 · 복습노트 · AI분석 엔드포인트

(이하 전부 로그인 필요 — `user_id`는 토큰에서 서버가 추출하므로 요청 바디에 넣지 않는다)

### 2-1. GET /api/cases

케이스 목록 조회 (판독 훈련 시작 화면)

**Query**: `?body_part=brain_mri`

**Response**
```json
{
  "cases": [
    {
      "case_id": "VS-SEG-202",
      "body_part": "brain_mri",
      "disease": "vestibular_schwannoma",
      "thumbnail_url": "http://localhost:8010/static/cases/VS-SEG-202/thumb.png",
      "has_matched": false,
      "needs_review": false,
      "gradable": true
    }
  ]
}
```
> **학습 상태 (v0.3에서 분리)** — 로그인한 사용자 기준으로 계산된다.
>
> | 필드 | 의미 | 계산 |
> |---|---|---|
> | `has_matched` | 한 번이라도 `match` 를 받음 (화면 표기: **학습완료**) | 제출 이력에 `match` 존재 |
> | `needs_review` | 가장 최근 제출이 `match` 가 아님 (화면 표기: **복습필요**) | 최신 제출 `grade != match` |
> | `gradable` | 기준 마스크가 등록되어 채점 가능 | reference mask 파일 존재 |
>
> 두 상태는 **서로 배타적이지 않다.** 맞힌 뒤 다시 틀리면 `has_matched: true` 이면서
> `needs_review: true` 가 된다 — 모순이 아니라 실제 학습 상태이므로 화면에서 둘 다 표시한다.
> (v0.2 의 `solved` 는 "한 번이라도 match"와 "복습 대상"을 한 필드로 뭉뚱그려 화면 1과
> 복습노트가 서로 모순되게 보이는 문제가 있었다. v0.3에서 제거되었다.)

### 2-2. GET /api/cases/{case_id}

케이스 상세 (판독 화면에 이미지 로드)

**Response**
```json
{
  "case_id": "VS-SEG-202",
  "body_part": "brain_mri",
  "disease": "vestibular_schwannoma",
  "image_url": "http://localhost:8010/static/cases/VS-SEG-202/slices/slice_035.png",
  "image_meta": { "width": 512, "height": 512, "slice_index": 35, "total_slices": 120 },
  "gradable": true
}
```
> `gradable: false` 면 기준 마스크가 아직 없는 케이스다. 프론트는 제출 버튼을 비활성화하고
> 안내를 띄운다. 그래도 제출을 보내면 `422 CASE_NOT_GRADABLE` 로 거부되며 이력도 남지 않는다.
>
> **케이스 = volume 1개.** 뇌 MRI 는 원본이 여러 slice 로 구성되므로, `image_url` 과
> `reference_mask_url` 은 **대표 slice**(병변 면적이 가장 큰 slice)를 가리킨다.
> `image_meta.slice_index` 가 그 대표 slice 의 **원본 volume 인덱스**이고,
> `total_slices` 는 원본 volume 의 전체 slice 수다 (등록된 slice 수가 아니다).
> slice 별 자산은 `case_slices` 에 있으며 2.5D 확장 시 쓴다 (현재 API 로는 내려주지 않는다).

### 2-3. POST /api/cases/{case_id}/submit

사용자가 클릭/브러시로 표시한 ROI 제출 → 채점 결과 반환

**Request**
```json
{
  "roi": {
    "type": "brush_mask",
    "points": [[120, 88], [124, 90], [130, 95]],
    "mask_png_base64": "iVBORw0KGgoAAAANS..."
  }
}
```

**Response** — 기획서 기준 3단계 평가(일치/부분 일치/불일치)를 따르는 형태로 제안

```json
{
  "case_id": "VS-SEG-202",
  "grade": "match",
  "dice": 0.91,
  "iou": 0.84,
  "location_score": 92,
  "reference_mask_url": "http://localhost:8010/static/cases/VS-SEG-202/slices/mask_035.png",
  "evaluation": {
    "method": "reference_mask",
    "is_provisional": false
  },
  "ai_prediction": null,
  "explanation": {
    "content_levels": ["dataset_verified", "literature_based"],

    "case_facts": {
      "source": "dataset_verified",
      "disease_name": "전정신경초종 (Vestibular Schwannoma)",
      "disease_code": "vestibular_schwannoma",
      "laterality": "right",
      "laterality_basis": "DICOM ImageOrientationPatient + GT 마스크 열 중심",
      "representative_slice": 35,
      "total_slices": 120,
      "lesion_slice_range": [30, 41],
      "representative_area_px": 1539,
      "reference_region": "우측 (DICOM 영상 방향 ImageOrientationPatient 으로 확인한 전문가 GT 마스크 위치). 대표 slice 35 / 원본 120장, 병변 slice 30~41.",
      "dataset": "VS-SEG (RTSTRUCT 전문가 GT)"
    },

    "disease_info": {
      "source": "literature_based",
      "notice": "아래 내용은 해당 질환에 대한 문헌 기반 학습정보이며, 이 케이스의 개별 영상 소견을 확정하는 설명은 아닙니다.",
      "imaging_features": ["...", "..."],
      "medical_terms": [{ "term": "소뇌교각 (cerebellopontine angle, CPA)", "description": "..." }],
      "references": [{ "title": "...", "publisher": "...", "url": "...", "accessed": "2026-09-08" }],
      "content_version": "vs-2026-09-08"
    },
    "case_findings": null
  }
}
```

> **해설 3층 구조 (v0.4)** — 우리는 의료인이 아니므로 **검증되지 않은 의학 내용을 지어내지 않는다.**
> 그래서 해설을 출처가 다른 3개 블록으로 나누고, 각 블록이 자기 `source` 를 들고 다닌다.
> 하나로 뭉치면 학습자가 "이 케이스에서 확인된 것"과 "질환 일반론"을 구분할 수 없다.
>
> | 블록 | `source` | 근거 | 어디서 오나 |
> |---|---|---|---|
> | `case_facts` | `dataset_verified` | 전문가 GT(RTSTRUCT) + DICOM 태그에서 **계산**된 값 | manifest (사람이 타이핑하는 문장 없음) |
> | `disease_info` | `literature_based` | 질환 단위 문헌 학습정보. **이 케이스의 소견이 아니다** | `app/content/diseases/<disease_code>.json` |
> | `case_findings` | `expert_reviewed` | 전문가가 **이 케이스를 보고** 쓴 영상 소견 | manifest (reviewer / reviewed_at 필수) |
>
> - `content_levels` 는 **저장하지 않고 블록 존재 여부에서 계산한다.** 세 값은 서로 배타적이지
>   않아서(사실 + 문헌이 동시에 있을 수 있다) 스칼라 상태 필드로는 표현되지 않는다.
>   순서는 `dataset_verified` -> `literature_based` -> `expert_reviewed` 로 고정이며 화면이 이 순서대로 그린다.
> - `disease_info` 는 **manifest 로 넣을 수 없다.** 등록자가 임의로 쓴 문장이 "문헌 기반"으로
>   표시되는 경로를 만들지 않기 위해서다. 파일이 없거나 비어 있으면 `null` 이고 레벨에서도 빠진다.
> - `disease_info.notice` 와 각 블록의 `source` 는 콘텐츠 파일이 아니라 **서버 상수**에서 채운다.
> - `case_findings` 는 `reviewer` / `reviewed_at`(YYYY-MM-DD) 이 없으면 등록되지 않는다.
>   **검토 출처 메타데이터를 필수화**하는 것이지, 필드가 있다고 검토를 보증하는 것은 아니다.
> - `case_facts.reference_region` 은 검증 가능한 사실만 적는다 — 좌/우 편측성은 DICOM
>   `ImageOrientationPatient` 로 계산하고(+x = 환자 왼쪽), 위치는 전문가 GT 마스크에서 가져온다.
>
> v0.3 의 평평한 필드(`key_findings`, `medical_terms`, `reference`, `review_status`)는 **제거**됐다.
> "소견" 이라는 이름 아래에 문헌 일반론이 들어가면 학습자가 그것을 이 케이스의 관찰로 읽기 때문이다.
> (`/api/analyze` 응답의 `key_findings` 는 **다른 스키마**이며 그대로 유지된다.)

> **채점 기준 (v0.3에서 확정)**
>
> 판독훈련 채점은 **사용자 ROI ↔ 전문가 검수 reference mask** 만으로 한다.
> AI 예측 마스크는 채점에 일절 관여하지 않고, 있을 때만 `ai_prediction` 에 참고 정보로 실린다.
> (모델은 완벽하지 않으므로 학습자를 모델 예측에 맞춰 채점하지 않는다.)
>
> - `reference_mask_url` — 채점 기준이 된 마스크. 화면 3 오버레이가 이걸 그린다.
>   (v0.2 까지 `ai_mask_url` 이던 필드. 실제로는 기준 마스크였으므로 이름을 바로잡았다.)
> - `evaluation.method` — `reference_mask` | `coordinate_approx`
> - `evaluation.is_provisional` — `true` 면 정식 채점이 아니다. 화면에 반드시 경고를 노출한다.
>   `coordinate_approx` 는 개발 환경(`MEDISCAN_ALLOW_APPROX_GRADING=1`)에서만 나온다.
> - `ai_prediction` — 모델 예측이 있으면 객체, 아니면 `null`:
>   ```json
>   {
>     "model_version": "vs-seg-unet2d5-att-hard-t1",
>     "mask_url": "http://.../static/cases/VS-SEG-202/prediction.png",
>     "dice_vs_reference": 0.9384,
>     "detected": true,
>     "representative_slice_dice": 0.9109,
>     "computed_at": "2026-09-08T12:00:00+00:00"
>   }
>   ```
>   뇌 MRI 모델은 3D volume 입력이라 **요청 시 추론하지 않고 미리 계산해 둔 결과**를 읽어 내려준다
>   (`backend/scripts/run_model_predictions.py` -> `app/model_predictions.py`).
>   `detected: false` 는 모델이 병변을 찾지 못한 케이스이고, 그때 `mask_url` 은 `null` 이다 —
>   "모델도 놓칠 수 있다"는 정보라 숨기지 않고 화면에 표시한다.
>   `dice_vs_reference` 는 volume 전체 기준, `representative_slice_dice` 는 화면에 보이는
>   대표 slice 기준이다. **둘 다 채점과 무관하다.**
>
> **VS-SEG-204 — AI 실패와 학습 채점 독립성의 대표 케이스**
>
> | 항목 | 값 |
> |---|---|
> | 전문가 GT | 존재 (3,628 voxel, 대표 slice 37 / 702px) |
> | 사용자 제출(기준 마스크 그대로) | `grade: "match"`, `dice: 1.0` |
> | AI 예측 | `dice_vs_reference: 0.0`, `detected: false`, `mask_url: null` |
>
> 모델이 완전히 실패했는데도 학습자 채점은 전문가 GT 기준으로 정상 동작한다.
> 이 케이스가 "AI 예측은 채점에 관여하지 않는다"는 계약의 실측 증거다.
>
> **기준 마스크가 없는 케이스는 채점하지 않는다.** 제출 이력도 만들지 않고 `422 CASE_NOT_GRADABLE`
> 를 반환한다. 프론트는 `GET /api/cases/{id}` 의 `gradable: false` 를 보고 제출 버튼을 미리 막는다.
>
> `grade` 는 Dice 기준: ≥ 0.60 `match`, ≥ 0.15 `partial_match`, 그 외 `mismatch`.
> 값 이름은 "정답/오답"이 아니라 **기준 마스크와의 일치 정도**를 뜻한다 — 우리가 의료인이 아니라서
> 확정적인 의학적 판단으로 읽히지 않게 하는 것이 중요하다.
>
> `location_score`(0~100)는 기존 `score` 를 이름만 명확히 한 것.

**ROI 입력 (`roi.type`)**

| 값 | 상태 | 설명 |
|---|---|---|
| `brush_mask` | **현재 유일하게 사용** | 브러시로 칠한 영역. `mask_png_base64` 필수 |
| `point` | 향후 | 클릭 한 번으로 위치만 지정. Dice 기반 채점과 맞지 않아 MVP에서 제외 |
| `contour` | 향후 | 닫힌 윤곽선으로 영역 지정. 내부를 채워서 채점 |

> MVP 판독훈련 화면은 **브러시 + 지우개만** 제공한다. 단일 클릭은 병변 위치를 정확히 찍어도
> 면적이 거의 없어 Dice 가 낮게 나오므로, 별도 채점 로직 없이 점 입력을 받는 것은 학습자에게
> 잘못된 피드백을 준다. 위치 기반 채점은 향후 별도 지표와 함께 도입한다.
>
> 제출된 마스크는 **보정하지 않는다**. (v0.2 에서 내부 구멍을 자동으로 메웠으나,
> 윤곽선만 그린 ROI 를 과도하게 후하게 채점할 수 있어 제거했다. `contour` 도구 도입 시 부활 예정.)

### 2-4. GET /api/wrong-notes

로그인한 사용자의 복습노트 목록 (grade가 partial_match/mismatch인 케이스)

> **구현됨**: 별도 테이블 없이 `submissions` 에서 **케이스별 최신 제출**이 `match` 가 아닌 것을 뽑는다.
> 재도전해서 맞히면 이 목록에서 빠진다.

**Response**
```json
{
  "items": [
    { "case_id": "VS-SEG-115", "body_part": "brain_mri", "grade": "mismatch", "attempted_at": "2026-09-10T14:00:00+09:00" }
  ]
}
```

### 2-5. POST /api/wrong-notes/{case_id}/retry

복습노트에서 재도전 — 응답 형식은 2-3(submit)과 동일

### 2-6. POST /api/analyze — 사용자 의료영상 AI 분석 (2번째 트랙)

> **이번 MVP 범위에서 실제 분석 기능은 제외**한다 (화면은 "준비 중" 상태 유지).
> 현재 뇌 MRI 모델은 3D ceT1 volume 입력이라 PNG/JPEG 단일 이미지에 억지로 쓰지 않는다.
> DICOM 시리즈 업로드도 이번 범위 밖이다. 단일 이미지용 2D 모델 확보 후 구현한다.
> **업로드 검증·미저장·EXIF 제거는 지금도 그대로 동작한다.**

사용자가 직접 불러온/공유한 영상에서 분석 영역 지정 후 요청

**Request**
```json
{
  "image_base64": "...",
  "region": { "type": "brush_mask", "points": [[100, 80]] }
}
```

**Request** 에 `body_part` (선택, 기본 `brain_mri`) 를 함께 보낼 수 있다.

**Response — 현재 기본 상태 (v0.4)**
```json
{
  "status": "model_unavailable",
  "is_demo": false,
  "model_version": null,
  "ai_mask_url": null,
  "suspected_region": "",
  "key_findings": "",
  "candidate_diseases": [],
  "unavailable_reason": "이 부위 모델은 volume(연속 슬라이스) 입력 전용이라 업로드한 이미지 한 장으로는 분석할 수 없습니다. ...",
  "disclaimer": "본 결과는 학습 참고용 AI 분석이며 확정 진단이 아닙니다."
}
```

> **`status`** — `ok` | `model_unavailable` | `demo`
>
> v0.3 까지는 고정 mock 이 `suspected_region` / `key_findings` / `candidate_diseases`(확률까지)를
> 지어내 내려보냈다. 그건 **사용자가 올린 영상을 실제로 분석한 결과처럼 보이는 검증되지 않은
> 의학적 출력**이라 제거했다. 모델이 없으면 소견을 비우고 `unavailable_reason` 만 밝힌다.
>
> 뇌 MRI 모델(VS_Seg)은 3D ceT1 **volume** 입력이라 업로드된 PNG/JPEG 한 장으로는 추론할 수 없다.
> 학습 때와 다른 입력을 넣으면 조용히 틀린 결과가 나오므로 연결하지 않는다.
>
> 2D 입력을 지원하는 부위 모델이 생기면 자동으로 붙는다 —
> `models/<부위>/inference.py` 에 `predict_image(image, region=None) -> dict` 를 두면 된다.
> **파일로 저장하지 않고 PIL 이미지 객체를 그대로 넘긴다** (업로드 미저장 규칙 유지).
>
> `MEDISCAN_ANALYZE_DEMO` 는 **기본 OFF**이며 개발 확인용으로만 켠다. 켜면
> `status: "demo"`, `is_demo: true` 가 붙고 `disclaimer` 에 "예시 데이터"임이 명시되며,
> 화면에도 "화면 확인용 예시 데이터" 배너가 떠 실제 분석과 명확히 분리된다.
>
> ⚠️ 여기의 `key_findings` 는 업로드 영상에 대한 **모델 출력**이며, 화면 4 해설의
> `case_findings`(전문가 검토 소견)와는 다른 것이다.

> `disclaimer` 필드는 검토노트 5번 항목(AI 분석 결과의 성격 명시) 반영 — 화면에 항상 노출되도록 프론트에서 고정 배치 추천.
> 업로드 자체도 가입 시 `agree_sensitive_data` 동의를 받은 사용자만 가능.
> **구현됨**: 서버가 `consents` 테이블의 가장 최근 `agree_sensitive_data` 값을 확인하고, 동의가 없으면 403 `CONSENT_REQUIRED`.
> 동의 확인은 이미지 파싱보다 **먼저** 수행한다.

**업로드 검증 (서버 기준 — 클라이언트 검사는 UX 용)**

클라이언트가 보내는 MIME 타입·확장자는 신뢰하지 않고 실제 바이트를 열어 판단한다.

| 검사 | 기준 | 실패 시 |
|---|---|---|
| base64 길이 (디코딩 전) | 디코딩 시 12MB 이하 | 413 `IMAGE_TOO_LARGE` |
| 실제 포맷 | PNG 또는 JPEG | 415 `UNSUPPORTED_FORMAT` |
| 손상 여부 | 헤더 확인 후 `verify()` | 400 `INVALID_IMAGE` |
| 이미지 크기 | 64×64 ~ 4096×4096 | 422 `IMAGE_DIMENSION_OUT_OF_RANGE` |
| 픽셀 수 (압축 폭탄) | 4096×4096 이하 | 413 `IMAGE_TOO_LARGE` |
| `region.type` | `brush_mask` \| `point` \| `contour` | 422 `INVALID_REGION` |
| `region.points` | 비어있지 않고, 각 좌표가 이미지 범위 내 | 422 `INVALID_REGION` |

**개인정보 처리**

- 업로드 영상은 **저장하지 않는다.** 메모리에서만 처리한다 (디스크·DB 어디에도 남기지 않음).
- EXIF 등 **메타데이터를 제거**한 뒤 사용한다. 의료영상 메타데이터에는 촬영기기·환자 관련
  정보가 남아 있을 수 있어, 그대로 두면 개인정보를 함께 처리하는 셈이 된다.

**향후 확장: DICOM**

이번 MVP 범위는 PNG/JPEG 뿐이다. DICOM 을 지원하려면 아래가 별도로 필요하다:

1. `pydicom` 등으로 픽셀 데이터 추출 + 윈도우 레벨(WW/WL) 적용
2. **DICOM 태그 비식별화** — 환자명(0010,0010), 환자 ID(0010,0020), 생년월일(0010,0030),
   검사일시, 기관명, 장비 일련번호 등을 제거해야 한다. 픽셀만 지우는 것으로는 부족하고,
   영상 내부에 새겨진(burned-in) 텍스트도 확인해야 한다.
3. 다중 프레임/시리즈 처리 정책 (슬라이스 선택 UI 포함)

---

## 3. 데이터 모델 요약

| 모델 | 주요 필드 |
|---|---|
| User | user_id, email, nickname, provider(null이면 이메일 가입), created_at |
| Consent | user_id, key(agree_terms 등), agreed(bool), version, agreed_at |
| Case | case_id, body_part, disease, image_url, image_meta, **volume_id, representative_slice**, reference_mask_url, explanation |
| CaseSlice | case_id, **slice_index(원본 volume 인덱스)**, image_url, mask_url(병변 없으면 null), lesion_area_px |
| Submission/Evaluation | user_id, case_id, grade, dice, iou, location_score, reference_mask_url, evaluation_method, is_provisional, explanation, submitted_at |
| WrongNote | user_id, case_id, grade, attempted_at (Submission에서 grade≠match인 것을 뷰로 뽑아도 됨) |

실제 구현은 `backend/app/models.py` (users / consents / cases / case_slices / submissions).
WrongNote 는 테이블 없이 `backend/app/repository.py` 에서 계산한다. DB 는 `DATABASE_URL` 환경변수로
로컬 SQLite ↔ PostgreSQL 을 바꿀 수 있다 — `backend/README.md` 참고.
**스키마의 기준은 Alembic 마이그레이션이다** (`backend/alembic/`).

> **Case 는 volume 1개다.** 뇌 MRI 는 원본이 여러 slice 로 오므로, 케이스의 `image_url` /
> `reference_mask_url` 은 대표 slice 를 가리키고 slice 별 자산은 `case_slices` 에 둔다.
> `slice_index` 를 0부터 다시 매기지 않고 **원본 volume 인덱스 그대로** 저장하는 이유는,
> 2.5D 입력(previous/current/next)을 구성할 때 원본과 같은 좌표로 인접 slice 를 찾기 위해서다.
> `lesion_area_px` 는 전문가 GT 를 그대로 센 값이다 — 작다고 걸러내지 않는다.

---

## 4. 화면별 기능정의서

### 화면 0 — 로그인 / 회원가입
- 상단: SNS 간편가입 버튼(카카오/구글/네이버) + 하단에 이메일 로그인/가입 전환 링크
- SNS 인증 성공 후 신규 사용자면 **동의 화면**으로 이동 (필수 5개 체크박스 + 선택 1개, 필수 전부 체크해야 "가입 완료" 버튼 활성화)
- 이메일 가입도 같은 동의 화면을 폼 하단에 포함
- 연동 API: `GET /api/consents/current-version`(동의 문구 로드), `POST /api/auth/signup`, `POST /api/auth/social-login`, `POST /api/auth/login`

### 화면 1 — 케이스 목록
- 부위(뇌MRI/흉부/복부/무릎) 탭 또는 필터
- 케이스 썸네일 + 학습 상태 뱃지: `has_matched`(학습완료) / `needs_review`(복습필요) / 둘 다 아니면 미시도
  (두 값은 배타적이지 않아 동시에 노출될 수 있다)
- 연동 API: `GET /api/cases`

### 화면 2 — 판독 훈련 (핵심 화면)
- 구성: MRI 이미지 뷰어 + 브러시/지우개 ROI 입력 도구 + `제출` 버튼
- 현재는 **대표 slice 1장**만 보여준다. slice 이동 UI 는 `case_slices` 가 준비돼 있으므로
  API 에 slice 목록을 추가하면 붙일 수 있다 (MVP 범위 밖).
- 상태: 제출 전(입력 가능) → 제출 중(로딩) → 결과 표시(입력 잠금)
- 연동 API: `GET /api/cases/{id}`, `POST /api/cases/{id}/submit`

### 화면 3 — 결과 비교
- 사용자 ROI vs 전문가 검수 기준 마스크 오버레이 (색상 구분: 사용자=파랑, 기준=초록, 겹침=노랑)
- grade 뱃지(일치/부분 일치/불일치), Dice·location_score 수치 표시
- 연동 API: submit 응답 그대로 사용 (별도 호출 없음)

### 화면 4 — 학습 해설
- 해설을 **3개 섹션**으로 나눠 표시하고, 각 섹션에 출처 칩을 단다. **내부 값(`dataset_verified` 등)은
  화면에 그대로 노출하지 않는다.**

  | 섹션 | 화면 표기 | 내용 |
  |---|---|---|
  | `case_facts` | **데이터셋 확인 정보** | 병명 · 편측성 · 기준 영역 · 대표 slice · 병변 slice · GT 면적 |
  | `disease_info` | **문헌 기반 학습정보** | 일반적 MRI 특징 · 의학용어 · 참고문헌 |
  | `case_findings` | **전문가 검토 소견** | 소견 본문 + 검토자 · 검토일 |

- 문헌 섹션은 **다른 배경면으로 감싸** 케이스 소견과 섞여 보이지 않게 하고, 상단에 다음 문구를 노출한다:
  *"아래 내용은 해당 질환에 대한 문헌 기반 학습정보이며, 이 케이스의 개별 영상 소견을 확정하는 설명은 아닙니다."*
  소제목에도 "소견" 이라는 단어를 쓰지 않는다 (`일반 정보`).
- **없는 블록도 섹션을 숨기지 않고** "등록되지 않았습니다"로 표시한다 — 없다는 것도 정보다.
- 연동 API: submit 응답의 `explanation` 객체

### 화면 5 — AI 설명 영역 (사용자 영상 분석 트랙)
- 업로드/화면공유 버튼 → 영역 지정 → 분석 결과(candidate_diseases, key_findings) 표시
- `disclaimer` 문구 항상 상단 고정
- 연동 API: `POST /api/analyze`

### 화면 6 — 복습노트
- grade가 partial_match/mismatch인 케이스 리스트, 클릭 시 재도전
- 연동 API: `GET /api/wrong-notes`, `POST /api/wrong-notes/{id}/retry`

### 화면 7 — 마이 진행현황 (선택, 여유 있으면)
- 전체 케이스 대비 해결률, 부위별 일치율 요약
- 연동 API: 별도 집계 엔드포인트 필요 시 추가 논의

---

## 5. Mock 데이터 개발 가이드

1. `/mock/cases.json`, `/mock/case_202.json`, `/mock/submit_202.json` 처럼 위 응답 예시를 그대로 정적 JSON 파일로 두고 fetch
2. 로그인도 mock 단계에서는 `POST /mock/auth/login`이 고정된 `access_token: "mock-token"`을 반환하게 해두고, 프론트는 이 토큰을 localStorage에 저장 → 이후 요청 헤더에 그대로 실어 보내는 구조까지 mock 단계에서 미리 만들어두면 실제 API 전환이 매끄러움
3. API 준비되면 fetch 함수의 base URL만 `/mock` → `/api`로 교체 (응답 스키마가 동일하므로 화면 로직은 그대로)
4. 모델 V1 → V2 → V3로 바뀌어도 `model_version` 값만 달라질 뿐 스키마는 고정 — 프론트는 `model_version`을 화면 하단에 작게 표시해두면 데모 때 버전 설명하기 편함

---

## 6. 다음 확인 필요 사항 (팀 논의용)

- `grade`를 3단계 enum(`match`/`partial_match`/`mismatch`)으로 갈지, 기존 `correct_region` boolean으로 갈지 결정
- 다른 부위(흉부/복부/무릎) 담당 팀원의 응답 포맷도 이 구조(case_id, model_version, grade, dice, explanation)와
  grade 값 이름(`match`/`partial_match`/`mismatch`)까지 맞출 수 있는지 확인 — 맞추면 프론트 컴포넌트를 부위별로 재사용 가능
- SNS 간편가입은 카카오/구글/네이버 중 어디까지 지원할지 (개발사 등록·앱 키 발급이 필요해서 발표 전 시간 여유 보고 결정)
- 동의 항목 문구(`/legal/terms`, `/legal/privacy`, `/legal/sensitive`)의 실제 내용은 지도교수/멘토 검토가 필요할 수 있음 — 최소한 "무엇에 동의하는지"가 명확한 문장으로 작성
