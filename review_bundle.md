# 메디스캔노트 — 코드리뷰 번들 (API 계약 v0.4)

> 갱신일: 2026-09-08 / 대상: 외부 코드리뷰(ChatGPT 등)
> 리포: `mediscan-note` (의료영상 판독 학습 웹서비스, 학부 팀 프로젝트)
> **이 리포는 아직 git 저장소가 아니라 `git diff` 를 첨부할 수 없습니다.** 6절에 주요 코드를 발췌했습니다.
>
> 이 문서는 **1차 리뷰 지적사항을 반영한 v0.3 기준**입니다. 반영 내역은 2절에 정리했습니다.

---

## 1. 현재 구현 목표

예비 보건의료인이 의료영상에서 이상 부위를 **ROI로 직접 칠하고**, 전문가 검수 기준 마스크와
비교해 **일치/부분 일치/불일치**를 평가받으며, 일치하지 않은 케이스를 복습노트에서 반복
훈련하는 웹서비스. 두 번째 트랙으로 사용자가 가진 영상을 업로드해 AI 분석 결과를 확인한다.

### 기술 스택

- Frontend: Vue 3.5 + Vite 8, vue-router, 순수 CSS 토큰(UI 프레임워크 없음), Pretendard(로컬 번들)
- Backend: FastAPI 0.115, SQLAlchemy 2.0, Pydantic 2.9, numpy 2.4 + Pillow 12
- DB: `DATABASE_URL` 로 SQLite(로컬) ↔ PostgreSQL(배포) 전환
- 모델: PyTorch (**미설치·미연결** — lazy import 로 처리)
- 테스트: pytest 9 + httpx (**124개**)
- 환경: Windows 11, Python 3.11.9, Node 24.15

### 설계 원칙 (CLAUDE.md)

1. **API 계약이 유일한 접점**이다. 모델이 바뀌어도 `docs/api-spec.md` 스키마가 유지되면 프론트는 손대지 않는다.
2. 평가는 **일치/부분 일치/불일치**(`match`/`partial_match`/`mismatch`). 우리가 의료인이 아니므로
   "정답/오답"처럼 확정적 의학 판단으로 읽히는 표현은 쓰지 않는다.
3. 체크포인트·데이터셋은 리포에 커밋하지 않는다.

---

## 2. 1차 리뷰 지적사항 반영 내역 (v0.2 → v0.3)

| # | 리뷰 지적 | 반영 결과 |
|---|---|---|
| 1 | 채점에 AI 예측을 쓰지 말고 전문가 검수 reference mask 고정 | **채점은 reference mask 전용.** AI 예측은 `ai_prediction` 참고 정보로 완전 분리. `ai_mask_url` → `reference_mask_url` 개명 |
| 2 | reference mask 없을 때 조용한 `v0-approx` 폴백 금지 | **422 `CASE_NOT_GRADABLE` + 제출 이력 미생성.** 좌표 근사는 `MEDISCAN_ALLOW_APPROX_GRADING=1` 개발 전용, 응답에 `is_provisional: true` |
| 3 | `fill_holes` 과보정 검토, 도구 UX 분리 | **자동 보정 제거**(백엔드·프론트 양쪽). contour 도구는 신설하지 않고 향후 과제로. 안내를 "칠해주세요"로 통일, 브러시 기본 굵기 16→24 |
| 4 | `solved` 상태 충돌 해소 | **`has_matched`(학습완료) + `needs_review`(복습필요)** 두 축으로 분리. 배타적이지 않음 |
| 5 | `/api/analyze` 업로드 검증 | 서버에서 크기·실제 포맷·손상·픽셀수·region 검증. **미저장 + EXIF 제거.** DICOM 은 향후 확장으로 문서화 |
| 6 | brain_mri_vs 를 완성으로 표시하지 말 것 | **"실제 모델 미연결"** 명시. 4중 활성화 조건. smoke Dice 기준값은 만들지 않음 |
| 7 | pytest 를 먼저 | 격리·인증부터 시작해 현재 **124개** |

**v0.2 대비 API 변경 요약**

| 구분 | v0.2 | v0.3 |
|---|---|---|
| 채점 응답 마스크 | `ai_mask_url` | `reference_mask_url` |
| 채점 방식 표시 | 최상위 `model_version` | `evaluation: { method, is_provisional }` |
| AI 예측 | 채점 기준으로 사용 | `ai_prediction` (참고, `null` 가능) |
| 학습 상태 | `solved` | `has_matched` + `needs_review` |
| 채점 가능 여부 | 없음 | `gradable` |
| 기준 마스크 없음 | `v0-approx` 로 채점 | 422, 이력 미생성 |
| ROI 보정 | `fill_holes` 자동 | 없음 |
| ROI 도구 | 브러시/클릭/지우개 | **브러시/지우개** |

---

## 3. 프로젝트 폴더 구조

```
mediscan-note/
├── CLAUDE.md                        프로젝트 브리프
├── docs/api-spec.md                 API 명세 v0.3 + 화면별 기능정의서 (계약 원본)
├── review_bundle.md                 ← 이 문서
│
├── backend/                         FastAPI (app 1,827줄 + tests 1,246줄)
│   ├── README.md · requirements.txt · requirements-dev.txt · pytest.ini · .env.example
│   ├── app/
│   │   ├── main.py(50)              앱 진입점, StaticFiles 마운트, /health
│   │   ├── db.py(55)                engine/세션/DATABASE_URL
│   │   ├── models.py(94)            SQLAlchemy 모델
│   │   ├── schemas.py(133)          pydantic 계약 모델
│   │   ├── security.py(110)         scrypt 해싱 + HMAC 서명 토큰
│   │   ├── deps.py(45)              current_user 의존성 (401)
│   │   ├── repository.py(70)        has_matched / needs_review 파생 조회
│   │   ├── grading.py(215)          ROI 채점 — reference mask 전용
│   │   ├── masks.py(140)            마스크 디코딩 + Dice/IoU (fill_holes 미사용)
│   │   ├── uploads.py(186)          업로드 검증 + 메타데이터 제거
│   │   ├── inference.py(125)        부위별 모델 레지스트리
│   │   ├── static_files.py(64)      케이스 자산 경로/URL
│   │   ├── seed.py(118)             mock_data → DB 시드
│   │   ├── routers/                 auth(148) consents(14) cases(114) wrong_notes(67) analyze(79)
│   │   ├── mock_data/               케이스 원본 JSON, 동의 문구
│   │   └── static/                  케이스 영상·기준 마스크 (자리표시자)
│   └── tests/                       conftest(147) + 6개 파일 = 124 테스트
│
├── frontend/                        Vue 3 + Vite (src 4,162줄)
│   └── src/  api/ stores/ router/ components/ views/ style.css
│
├── models/
│   ├── _template/inference.py(82)   새 부위 추가용 템플릿
│   └── brain_mri_vs/inference.py(233)  뇌 MRI — **실제 모델 미연결**
│
└── tools/browser-verify/            헤드리스 브라우저 검증 스크립트 (단위 테스트 아님)
```

---

## 4. 현재 구현 완료 기능

### 인증 · 동의

- 이메일 가입/로그인, SNS 간편가입 3종(**provider_token 은 mock**)
- 비밀번호 `hashlib.scrypt` 해싱 (평문 저장 없음)
- HMAC-SHA256 서명 + 만료(기본 7일) 토큰. 토큰 없음/위조/만료/삭제된 사용자 → 401
- 필수 동의 5 + 선택 1. 동의 이력은 **갱신이 아니라 append** (버전·시각 포함 증빙)
- `/api/analyze` 는 최신 `agree_sensitive_data` 를 서버가 확인 → 없으면 403

### 판독훈련 · 채점 (v0.3 핵심)

- **채점 기준은 전문가 검수 reference mask 하나뿐.** AI 예측은 채점에 일절 관여하지 않음
- 실제 마스크 Dice/IoU/위치점수 계산 (numpy + Pillow)
- 판정: Dice ≥ 0.60 `match`, ≥ 0.15 `partial_match`, 그 외 `mismatch`
- **ROI 자동 보정 없음** — 칠한 면적 그대로 채점
- ROI 도구는 **브러시 + 지우개**만 (단일 클릭은 면적이 없어 Dice 채점과 맞지 않아 제외)
- 기준 마스크 없는 케이스: `gradable: false` 로 제출 버튼 차단, 강제 제출 시 **422 + 이력 미생성**

### 학습 상태

- `has_matched`(한 번이라도 match) / `needs_review`(최신 제출이 match 아님) — 배타적이지 않음
- 복습노트는 별도 테이블 없이 **케이스별 최신 제출**에서 파생. 재도전해 맞히면 자동 제거

### 화면 (docs/api-spec.md 4절)

| 화면 | 상태 |
|---|---|
| 0 로그인/회원가입 + 동의 | 동작 |
| 1 케이스 목록 (학습완료/복습필요/미시도/채점준비중 뱃지) | 동작 |
| 2 판독 훈련 (다크 뷰어, 브러시+지우개) | 동작 |
| 3 결과 비교 (사용자=파랑/기준=초록/겹침=노랑 픽셀 합성) | 동작 |
| 4 학습 해설 | 동작 |
| 5 내 영상 분석 | UI·검증 동작 / **응답은 고정 mock** |
| 6 복습노트 + 재도전 | 동작 |
| 7 진행현황 | 동작 (프론트 집계) |

### 업로드 검증 (`/api/analyze`)

- base64 길이(디코딩 전) → 실제 포맷(PNG/JPEG) → 손상 여부 → 크기(64~4096) → 픽셀 수 → region 좌표
- 클라이언트 MIME 은 신뢰하지 않음. 프론트 검사는 UX 용
- **업로드 영상 미저장** (메모리 처리) + **EXIF 등 메타데이터 제거**

### 인프라

- `DATABASE_URL` 로 SQLite ↔ PostgreSQL 전환
- 케이스 영상·마스크를 백엔드가 서빙(`/static`), CORS 허용으로 프론트 canvas 픽셀 읽기 가능
- 부위별 모델 레지스트리 — 팀원이 `models/<부위>/inference.py` 만 추가하면 백엔드 수정 불필요

---

## 5. 아직 mock / 미완성인 기능

| 항목 | 현재 상태 | 비고 |
|---|---|---|
| **`/api/analyze` 응답** | **고정 mock** — 검증만 실제로 수행하고 결과는 하드코딩 | 모델 연결 시 교체 |
| **brain_mri_vs 모델** | **실제 모델 미연결** | 체크포인트·전처리 미확정 |
| 다른 부위 모델 4종 | 폴더 없음 | 템플릿만 준비 |
| SNS `provider_token` | mock 문자열 | 각 사 서버 검증 미구현 |
| 케이스 영상·기준 마스크 | 코드로 생성한 **자리표시자** | 실제 의료영상 아님 |
| 케이스 해설 | VS-SEG-115 가 202 해설 공유 | 케이스별 해설 필요 |
| 슬라이스 네비게이션 | 숫자만 변경 | 백엔드가 슬라이스별 영상 미제공 |
| `reference_shape` | `seed.py` 하드코딩 | 개발용 근사 채점에서만 사용 |
| DICOM 업로드 | 미지원 (PNG/JPEG 만) | 태그 비식별화 필요 — 향후 |
| PostgreSQL | 코드만 존재, SQLite 로만 검증 | |
| 마이그레이션 | alembic 없음 (`create_all`) | 스키마 변경 시 DB 삭제 |
| 관리자 기능 | 없음 | 케이스 등록은 시드 스크립트로만 |
| 비밀번호 재설정/이메일 인증/탈퇴 | 없음 | |
| 프론트 단위 테스트 | 없음 (vitest 미도입) | 백엔드만 124개 |

---

## 6. 주요 코드 (git 미사용 → 발췌)

### 6-1. `app/grading.py` — 채점 진입점 (v0.3 핵심)

```python
def evaluate_submission(case, roi: dict) -> dict:
    """raises: NotGradable(422) / InvalidRoi(400)"""
    reference = _load_reference(case)

    if reference is None:
        if _approx_allowed():          # 개발 전용 (MEDISCAN_ALLOW_APPROX_GRADING=1)
            return _grade_by_points(case, roi)
        raise NotGradable("이 케이스는 채점 기준(기준 마스크)이 아직 등록되지 않았습니다.")

    raw = roi.get("mask_png_base64")
    if not raw:
        raise InvalidRoi("표시한 영역(mask_png_base64)이 필요합니다.")
    try:
        user_mask = masks.from_base64(raw)
    except masks.MaskError as exc:
        raise InvalidRoi(f"표시한 영역을 읽을 수 없습니다: {exc}") from exc
    if not user_mask.any():
        raise InvalidRoi("표시한 영역이 비어 있습니다.")

    # 보정 없이 그대로 비교한다 (fill_holes 미적용)
    dice, iou = masks.dice_iou(user_mask, reference)
    score = masks.location_score(user_mask, reference)

    return {
        "grade": _grade_from_dice(dice),
        "dice": round(dice, 4), "iou": round(iou, 4), "location_score": score,
        "reference_mask_url": case.reference_mask_url,
        "evaluation": {"method": METHOD_REFERENCE, "is_provisional": False},
        "ai_prediction": ai_prediction(case, reference),   # 참고 정보 전용
        "explanation": case.explanation or {},
    }
```

```python
def ai_prediction(case, reference_mask=None) -> dict | None:
    """모델이 준비된 경우에만 참고 정보를 만든다. **채점에는 절대 쓰지 않는다.**
    실패해도 예외를 밖으로 내보내지 않는다 — 참고 정보가 없다고 채점이 막히면 안 된다."""
    if not inference.is_available(case.body_part):
        return None
    ...
    return {"model_version": ..., "mask_url": ..., "dice_vs_reference": ...}
```

**리뷰 포인트**: 임계값 0.60/0.15 근거, `location_score` 정규화식, 개발용 근사 채점을 아예 삭제할지.

### 6-2. `app/routers/cases.py` — 채점 불가 시 이력 미생성

```python
def grade_and_store(case: Case, roi: dict, user, db) -> dict:
    """채점 -> 이력 저장 -> 응답. 채점 불가/ROI 오류면 **저장하지 않고** 예외."""
    try:
        result = evaluate_submission(case, roi)
    except NotGradable as exc:
        raise _error(422, "CASE_NOT_GRADABLE", str(exc)) from exc
    except InvalidRoi as exc:
        raise _error(400, "INVALID_ROI", str(exc)) from exc

    db.add(Submission(user_id=user.user_id, case_id=case.case_id, grade=result["grade"], ...))
    db.commit()
    ...
```

### 6-3. `app/repository.py` — 상태 두 축

```python
def has_matched_case_ids(db, user_id) -> set[str]:
    """한 번이라도 'match' 를 받은 케이스 (학습완료). 한 번 달성하면 취소되지 않는다."""
    return set(db.scalars(select(Submission.case_id).where(
        Submission.user_id == user_id, Submission.grade == "match")).all())


def wrong_note_items(db, user_id) -> list[Submission]:
    """최신 제출이 match 가 아닌 케이스 (복습필요)."""
    return [s for s in latest_submissions(db, user_id) if s.grade != "match"]
```

**리뷰 포인트**: 두 상태가 동시에 true 인 케이스("맞혔지만 최근에 틀림")를 화면에서 어떻게 보여줄지.

### 6-4. `app/uploads.py` — 업로드 검증 순서

```python
def decode_image(image_base64) -> Image.Image:
    """검사 순서가 중요하다: 큰 문자열을 디코딩하기 전에 길이부터,
    픽셀을 디코딩하기 전에 헤더에서 포맷·크기를 먼저 확인한다(압축 폭탄 방지)."""
    payload = _strip_data_url(image_base64)
    if len(payload) > MAX_BASE64_CHARS:
        raise UploadError(413, "IMAGE_TOO_LARGE", ...)
    raw = base64.b64decode(payload, validate=False)
    ...
    probe = Image.open(io.BytesIO(raw))        # 지연 로딩 — 아직 픽셀을 풀지 않는다
    image_format, (width, height) = probe.format, probe.size
    if image_format not in ALLOWED_FORMATS:    # 클라이언트 MIME 이 아니라 실제 포맷
        raise UploadError(415, "UNSUPPORTED_FORMAT", ...)
    if width * height > MAX_PIXELS: ...        # 압축 폭탄
    if width < MIN_DIMENSION or ...: ...
    Image.open(io.BytesIO(raw)).verify()       # 손상 여부
    image = Image.open(io.BytesIO(raw)); image.load(); image = image.convert("RGB")
    return strip_metadata(image)


def strip_metadata(image):
    """copy() 는 .info 를 함께 가져가므로 픽셀 바이트만으로 새 객체를 만든다."""
    return Image.frombytes(image.mode, image.size, image.tobytes())
```

### 6-5. `models/brain_mri_vs/inference.py` — 4중 활성화 조건

```python
PREPROCESS_VERIFIED = False        # 담당자가 전처리 일치를 확인한 뒤 True
ENABLE_ENV = "MEDISCAN_ENABLE_BRAIN_MRI_MODEL"

def unavailable_reason() -> str | None:
    if not CHECKPOINT_PATH.exists():   return f"체크포인트 없음: {CHECKPOINT_PATH.name}"
    try: import torch
    except ImportError:                return "torch 미설치"
    if os.getenv(ENABLE_ENV, "") not in {"1", "true", "True"}:
                                       return f"환경변수 옵트인 필요: {ENABLE_ENV}=1"
    if not PREPROCESS_VERIFIED:        return "전처리 미검증 (PREPROCESS_VERIFIED=False)"
    return None

def predict(image_path, reference_mask_path=None):
    # 가드를 먼저 둔다 — torch 가 없는 환경에서도 "전처리 미검증"이라는 진짜 이유가 보여야 한다.
    if not PREPROCESS_VERIFIED:
        raise RuntimeError("전처리가 검증되지 않아 추론할 수 없습니다. ...")
    import numpy as np, torch
    ...
```

### 6-6. `app/security.py` — 토큰 (변경 없음, 리뷰 대상)

```python
def decode_access_token(token: str) -> dict | None:
    body, signature = token.split(".")
    expected = _b64e(hmac.new(SECRET_KEY.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, signature):  return None
    payload = json.loads(_b64d(body))
    if int(payload.get("exp", 0)) < int(time.time()): return None
    return payload
```

### 6-7. `frontend/src/components/ResultCompare.vue` — 오버레이 (fill 제거)

```js
// 채점과 동일하게 보정 없이 그대로 비교해 그린다 (v0.3에서 fill 보정 제거)
if (props.userMaskDataUrl) userBits = toMaskBits(await loadImage(props.userMaskDataUrl), w, h)
if (referenceMaskUrl.value) aiBits = toMaskBits(await loadImage(referenceMaskUrl.value), w, h)

const COLOR = { both: [250,204,21,205], user: [47,98,232,175], ai: [16,185,129,175] }
```

---

## 7. 테스트 결과

```
241 passed in 50s        (backend/ 에서 pytest)
```

| 파일 | 개수 | 범위 |
|---|---|---|
| `test_case_import.py` | 16 | 케이스 등록·검증·gradable 판정, 등록된 케이스 채점 |
| `test_volume_case_import.py` | 17 | volume 케이스: 원본 slice_index 보존, 작은 GT 유지, 재등록 정리, 해설 블록 규칙 |
| `test_roi_selection.py` | 16 | VS-SEG export 의 종양 ROI 선택 (AN 인식, 자동 선택은 후보 1개일 때만) |
| `test_explanation_content.py` | 21 | 해설 3층 구조, content_levels 파생, 질환 문헌 콘텐츠 로더 |
| `test_ai_prediction.py` | 13 | 미리 계산된 예측 sidecar, **AI 실패(204)와 채점 독립성** |
| `test_api_contract.py` | 18 | 문서(api-spec.md) ↔ 실제 응답 필드 불일치 감지 |
| `test_migrations.py` | 7 | upgrade/downgrade, 모델↔마이그레이션 드리프트, 레거시 DB 감지 |
| `test_analyze_upload.py` | 31 | 포맷 위장·손상·크기·압축폭탄·region·미저장·EXIF 제거·403 |
| `test_auth.py` | 29 | 가입·동의 append·로그인·토큰(만료/변조/삭제된 사용자)·SNS |
| `test_grading.py` | 22 | 등급 판정, 계약 스키마, ROI 검증, 422+이력미생성, **AI 미개입** |
| `test_isolation.py` | 22 | 사용자간 데이터 격리, 보호 엔드포인트 토큰 요구 |
| `test_wrong_notes.py` | 11 | has_matched/needs_review 매트릭스, 재도전 |
| `test_model_status.py` | 9 | 모델 unavailable, PREPROCESS_VERIFIED 가드, /health 사유 |

### 변이 테스트 (테스트가 실제로 회귀를 잡는지 검증)

| 주입한 결함 | 결과 |
|---|---|
| AI 예측을 채점 기준으로 교체 | `test_ai_model_never_overrides_reference_grading` 실패 |
| 기준 마스크 없어도 근사 채점 | 3개 실패 |
| `fill_holes` 재적용 | `test_outline_only_roi_is_not_auto_filled` 실패 |
| `has_matched` 를 최신 제출 기준으로 | `test_match_then_mismatch_keeps_both_states` 실패 |
| 포맷 검사 제거 | 2개 실패 |
| EXIF 제거 생략 | 1개 실패 |
| 크기 검사 제거 | 1개 실패 |
| `PREPROCESS_VERIFIED=True` 로 켬 | 2개 실패 |
| 사용자 격리 제거 | 4개 실패 |
| 토큰 만료 검사 제거 | 1개 실패 |
| 필수 동의 검증 제거 | 5개 실패 |

### 브라우저 E2E (헤드리스 Chrome + CDP, `tools/browser-verify/`)

신규 가입 → 두 케이스 **미시도** → 엉뚱한 곳 제출 **불일치(0.0)** → 복습노트 적재 →
재도전(칠하기) **일치(0.8218)** → 복습노트에서 제거 → 진행현황 50%. **콘솔 에러 0건.**
맞힌 뒤 다시 틀린 상태에서 뱃지가 **"학습완료 | 복습필요"** 둘 다 노출되는 것도 확인.

### 채점 실측 (기준 병변 중심 (338,307) 반지름 32)

| 제출 | grade | Dice |
|---|---|---|
| 정확히 덮음 | match | 0.978 |
| 안쪽에 작게 | partial_match | 0.422 |
| 40px 어긋남 | partial_match | 0.259 |
| 완전히 딴 곳 | mismatch | 0.0 |
| **둘레만 그림** | partial_match | **0.563** ← 보정 제거의 의도된 결과 |

### 정적 점검

pyflakes 지적 3건은 모두 `# noqa: F401` 이 붙은 의도된 import 다
(`db.py` 의 모델 등록용 import, wrapper 2곳의 torch 설치 여부 확인용).
중복 함수·클래스 정의 없음, 중복 import 없음, v0.2 필드 잔재 없음.
"죽은 코드" 로 보이는 5건은 `@router.get/post` 라우트 핸들러(프레임워크 호출)라 오탐이다.
실제 미사용은 `masks.fill_holes` 하나이며, 향후 contour 도구용으로 의도적으로 남기고
docstring 에 "현재 호출되지 않음"을 명시했다.
프론트 `npm run build` 통과.

---

## 8. 현재 알려진 리스크

### 보안 · 프라이버시

| # | 내용 | 심각도 |
|---|---|---|
| 1 | `MEDISCAN_SECRET_KEY` 미설정 시 **개발용 고정 키로 기동**(경고만) — 배포 사고 시 토큰 위조 가능 | 높음 |
| 2 | 토큰을 **localStorage** 저장 — XSS 시 탈취. 로그아웃은 클라이언트 삭제뿐(서버 폐기 목록 없음) | 중간 |
| 3 | SNS `provider_token` 을 각 사 서버에 **검증하지 않음** — 임의 문자열로 계정 생성 가능. 화면에는 "개발용 예시 로그인"이라고 명시했다 | 실서비스 전 필수 |
| 4 | CORS `allow_origins=["*"]` | 배포 전 필수 |
| 5 | 업로드는 미저장·EXIF 제거하지만, **로그에 요청 본문이 남지 않는지** 미확인 | 중간 |

### 데이터 · 운영

| # | 내용 |
|---|---|
| 6 | ~~alembic 없음~~ → **해결**. `backend/alembic/` 이 스키마의 기준이고 기동 시 자동 upgrade |
| 7 | ~~케이스 영상·마스크가 자리표시자~~ → **해결**. 뇌 MRI VS-SEG 실데이터 6케이스 등록 완료.
      다만 원본은 리포에 커밋하지 않으며, 공개·배포 시 데이터셋 라이선스 확인이 남아 있다 |
| 7-1 | **케이스별 영상 소견이 비어 있다.** 의료 전문가를 확보하기 어려워, 해설을 출처별 3층
        (`case_facts` / `disease_info` / `case_findings`)으로 나누고 검증된 사실만 서비스한다.
        현재 6케이스는 `content_levels: ["dataset_verified"]` 이고, 질환 문헌 학습정보는 미작성이다 |
| 7-2 | 211/212 의 종양 ROI 이름이 `AN` 이라 예전 키워드 목록에 걸리지 않았고, **우연히 첫 번째 ROI**
        여서 맞았다. 지금은 `AN`/`acoustic neuroma` 를 키워드에 넣고, 못 찾으면 **중단**하도록 바꿨다 |
| 8 | 기준 마스크 검수 절차가 **문서상 규칙일 뿐** 시스템적 강제가 없음 (DB 필드 없음).
      해설 쪽은 `explanation.review_status` 로 일부 강제된다 |
| 9 | numpy/pillow 버전 핀 고정 — 팀원 다른 파이썬 환경에서 충돌 가능 |
| 10 | 동시성/부하 미검증. `latest_submissions` 는 케이스 수만큼 파이썬에서 후처리 |

### 학습 도구로서의 타당성 (리뷰 요청)

| # | 내용 |
|---|---|
| 11 | Dice 임계값 0.60/0.15 의 **교육적 근거 없음** — 팀/지도교수 검토 필요 |
| 12 | 브러시로만 칠하는 방식이 실제 판독 훈련과 얼마나 맞는지 미검증 |
| 13 | `has_matched` 와 `needs_review` 동시 노출이 학습자에게 혼란스러운지 미검증 |
| 14 | 케이스 6개(전부 전정신경초종, 우측 5 / 좌측 1)라 난이도·부위 다양성이 없다.
       204 만 "모델 미검출" 케이스로 성격이 다르다 |
| 15 | 병변 시작/끝 slice 에 2~24px 짜리 GT 파편이 있다. 전문가 GT 를 손대지 않기로 해서
       그대로 등록했고, 채점은 대표 slice 로만 하므로 현재 영향은 없다.
       slice 네비게이션을 붙일 때 학습자에게 어떻게 보일지 검토가 필요하다 |

---

## 9. 다음 작업 우선순위

**1순위 — 배포 준비 / 케이스 확대**
- 화면 5 는 **MVP 범위에서 실제 분석 제외**로 확정 (준비 중 상태 유지, DICOM 도 범위 밖).
  단일 이미지용 2D 모델 확보 후 구현한다
- 케이스별 영상 소견(`case_findings`)은 전문가 확보 후. 검토자·검토일이 함께 있어야 등록된다
- (실데이터 등록 / alembic / 문헌 콘텐츠 / 뇌 MRI 모델 연결은 완료)

**모델 연결 요약 (v0.4)**

| 항목 | 상태 |
|---|---|
| 전처리·모델 구조 | 학습 노트북 cell 6/7/8 그대로 이식, 산출물 대조 통과 → `PREPROCESS_VERIFIED=True` |
| 재현 검증 | VS-SEG-202 예측 마스크 배열 완전 일치, 6케이스 Dice·voxel 전부 일치 |
| 연결 방식 | 3D volume 모델이라 **미리 계산한 sidecar** 를 서비스 (백엔드에 torch/monai 불필요) |
| 채점 영향 | **없음.** `ai_prediction` 참고 정보로만 나간다 |
| 재계산 | MVP 는 수동 (`run_model_predictions.py` → `verify_cases.py` 가 stale 검사) |

**VS-SEG-204 — AI 실패와 학습 채점 독립성 검증 케이스**

| 항목 | 값 |
|---|---|
| 전문가 GT | 존재 (3,628 voxel, 대표 slice 37 / 702px) |
| 사용자 제출(기준 마스크 그대로) | Dice **1.0** / `match` |
| AI 예측 | Dice **0.0** / `detected: false` / `mask_url: null` |

모델이 완전히 실패해도 학습자 채점은 전문가 GT 기준으로 정상 동작한다.

**2순위 — ~~모델 연결~~ → 완료**
- 뇌 MRI: 학습 노트북 재현 검증 통과 → `PREPROCESS_VERIFIED = True`, 6케이스 예측 미리 계산
- 남은 것: 다른 부위 모델, 화면 5 용 2D 추론 경로

**3순위 — 배포 준비**
- `MEDISCAN_SECRET_KEY` 주입, CORS 좁히기, PostgreSQL 전환 검증
- SNS provider_token 실검증

**4순위 — 확장**
- 다른 부위 모델 4종 (`models/_template/` 복사)
- 프론트 vitest 도입, 슬라이스 네비게이션, DICOM

---

## 10. 실제 모델 연결 전에 확인해야 할 사항

모델을 붙이기 전에 **반드시** 확인할 항목이다. 하나라도 어긋나면 조용히 틀린 결과가 나온다.

### 체크포인트

1. **저장 형식** — `torch.save(model)` 인지 `state_dict` 만인지.
   state_dict 면 `_build_model()` 에 VS_Seg 의 `AttentionUNet` 클래스를 import 해 채워야 한다
   (현재 `NotImplementedError`).
2. 학습 시점의 **torch/CUDA 버전**과 추론 환경 호환성
3. 체크포인트 보관 위치 (S3/드라이브) 와 팀 공유 방법 — git 에는 커밋하지 않음

### 전처리 (가장 위험)

4. **입력 크기·리사이즈 방식** — 현재 자리표시자는 512 bilinear
5. **정규화** — [0,1] 인지 z-score 인지, 채널별 mean/std 값
6. **2.5D 입력 구성** — 현재는 같은 슬라이스를 3채널 복제하는 자리표시자.
   실제로는 **인접 슬라이스 3장**을 쌓아야 하며, 그러려면 API 가 슬라이스별 영상을 제공해야 한다
7. 윈도우 레벨/조영 전후 구분 등 전처리 파라미터

> 위 4~7 이 확정되기 전에는 `PREPROCESS_VERIFIED = True` 로 바꾸면 안 된다.

### 검증

8. **smoke test fixture** — 알려진 입력·기대 Dice 범위. (지금은 기준값이 없어 만들지 않았다)
9. 미검출 2건(테스트 10명 중 8명 검출) 원인 분석 완료 여부 —
   확률맵 시각화, 종양 크기 비교(소형 intracanalicular 가능성). 결과에 따라 `THRESHOLD` 재조정
10. 모델 출력 마스크의 **좌표계·해상도**가 기준 마스크와 일치하는지

### 통합

11. 모델 출력 마스크를 어디에 저장하고 어떤 URL 로 서빙할지
    (현재 `models/<부위>/outputs/` 에만 저장되고 `ai_prediction.mask_url` 은 `null`)
12. 추론 시간 — 요청당 동기 실행이 가능한 수준인지, 아니면 큐/비동기가 필요한지
13. `/api/analyze` 는 사용자 업로드 영상이라 케이스 기준 마스크가 없다.
    결과 신뢰도를 어떻게 표기할지 (현재 `disclaimer` 고정 노출)

### 확인 방법

```bash
curl http://localhost:8000/health    # models.brain_mri.unavailable_reason 로 진행 상황 확인
cd backend && pytest tests/test_model_status.py -v
```

---

## 부록. 리뷰에서 특히 봐주셨으면 하는 것

1. **채점 임계값과 지표 설계** — Dice 0.60/0.15, `location_score` 정규화식이 학습 도구로 타당한가
2. **`has_matched` / `needs_review` 동시 노출** UX
3. **인증 설계** — 자체 HMAC 토큰 vs 표준 JWT, localStorage, 로그아웃/폐기 전략
4. **업로드 검증 순서와 누락된 공격 표면** (SVG·다중 프레임·polyglot 파일 등)
5. **동적 모듈 로드**(`app/inference.py`)의 안전성
6. **API 계약 유지 원칙**이 실제로 지켜지는 구조인지 (모델 교체 시 프론트 무수정)
