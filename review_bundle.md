# 메디스캔노트 — 코드리뷰 번들 (API 계약 v0.4)

> 갱신일: 2026-09-08 / 대상: 외부 코드리뷰(ChatGPT 등)
> 리포: `mediscan-note` (의료영상 판독 학습 웹서비스, 학부 팀 프로젝트)
> **이 리포는 git 저장소입니다** (초기 커밋 `9383c15`) — `git log` / `git diff` 를 첨부할 수 있습니다.
> 6절의 코드 발췌는 맥락을 빨리 잡기 위해 그대로 남겨 둡니다.
>
> 이 문서는 **API 계약 v0.4 기준**입니다. 반영 내역은 2절에 정리했습니다.

---

## 1. 현재 구현 목표

예비 보건의료인이 의료영상에서 이상 부위를 **ROI로 직접 칠하고**, 전문가 검수 기준 마스크와
비교해 **일치/부분 일치/불일치**를 평가받으며, 일치하지 않은 케이스를 복습노트에서 반복
훈련하는 웹서비스. 두 번째 트랙으로 사용자가 가진 영상을 업로드해 AI 분석 결과를 확인한다.

### 기술 스택

- Frontend: Vue 3.5 + Vite 8, vue-router 5, 순수 CSS 토큰(UI 프레임워크 없음), Pretendard(로컬 번들)
- Backend: FastAPI 0.115, SQLAlchemy 2.0, **Alembic 1.19**(마이그레이션이 스키마의 기준), Pydantic 2.9, numpy 2.4 + Pillow 12
- DB: `DATABASE_URL` 로 SQLite(로컬) ↔ PostgreSQL(배포) 전환
- 모델: 뇌 MRI VS-SEG **연결됨 — 단, 참고 정보 전용**. 3D volume 모델이라 예측을 **미리 계산해 sidecar 로 서비스**하며
  백엔드 런타임에는 torch/monai 가 필요 없다. **채점에는 일절 쓰이지 않는다**
- 테스트: pytest 9 + httpx (**241개**) + 브라우저 E2E 3종(`tools/browser-verify/`, 단위 테스트 아님)
- 환경: Windows 11, Python 3.11.9, Node 24.15

### 설계 원칙 (CLAUDE.md)

1. **API 계약이 유일한 접점**이다. 모델이 바뀌어도 `docs/api-spec.md` 스키마가 유지되면 프론트는 손대지 않는다.
2. 평가는 **일치/부분 일치/불일치**(`match`/`partial_match`/`mismatch`). 우리가 의료인이 아니므로
   "정답/오답"처럼 확정적 의학 판단으로 읽히는 표현은 쓰지 않는다.
3. **검증되지 않은 의학 내용을 지어내지 않는다.** 채점 기준은 전문가 검수 마스크뿐이고,
   해설은 출처별 3층(`case_facts`/`disease_info`/`case_findings`)으로 나눠 없는 블록은 비워 둔다.
4. 체크포인트·데이터셋·실제 의료영상은 리포에 커밋하지 않는다.

---

## 2. 리뷰 지적사항 반영 내역

### 2-1. 1차 리뷰 (v0.2 → v0.3)

| # | 리뷰 지적 | 반영 결과 |
|---|---|---|
| 1 | 채점에 AI 예측을 쓰지 말고 전문가 검수 reference mask 고정 | **채점은 reference mask 전용.** AI 예측은 `ai_prediction` 참고 정보로 완전 분리. `ai_mask_url` → `reference_mask_url` 개명 |
| 2 | reference mask 없을 때 조용한 `v0-approx` 폴백 금지 | **422 `CASE_NOT_GRADABLE` + 제출 이력 미생성.** 좌표 근사는 `MEDISCAN_ALLOW_APPROX_GRADING=1` 개발 전용, 응답에 `is_provisional: true` |
| 3 | `fill_holes` 과보정 검토, 도구 UX 분리 | **자동 보정 제거**(백엔드·프론트 양쪽). contour 도구는 신설하지 않고 향후 과제로. 안내를 "칠해주세요"로 통일, 브러시 기본 굵기 16→24 |
| 4 | `solved` 상태 충돌 해소 | **`has_matched`(학습완료) + `needs_review`(복습필요)** 두 축으로 분리. 배타적이지 않음 |
| 5 | `/api/analyze` 업로드 검증 | 서버에서 크기·실제 포맷·손상·픽셀수·region 검증. **미저장 + EXIF 제거.** DICOM 은 향후 확장으로 문서화 |
| 6 | brain_mri_vs 를 완성으로 표시하지 말 것 | 당시 **"실제 모델 미연결"** 명시 + 4중 활성화 조건. → v0.4 에서 재현 검증을 통과해 연결(2-2 참고) |
| 7 | pytest 를 먼저 | 격리·인증부터 시작. v0.3 시점 124개 → **현재 241개** |

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

### 2-2. 2차 리뷰 · 실데이터 반영 (v0.3 → v0.4)

| # | 지적 / 과제 | 반영 결과 |
|---|---|---|
| 1 | 자리표시자 영상으로는 판독훈련이라 할 수 없다 | **실데이터 뇌 MRI 전정신경초종(VS-SEG) 6케이스 등록.** DICOM -> npy -> 육안 검수 -> PNG 자산 -> 등록 **4단계 분리**(중간마다 사람이 확인) |
| 2 | 케이스 = 슬라이스 1장 가정이 3D 와 안 맞는다 | **케이스 = volume 1개**, 슬라이스별 자산은 `case_slices` 에 **원본 slice_index 그대로 보존**(2.5D 확장 대비). 화면·채점은 **대표 slice**(병변 면적 최대) |
| 3 | 문헌 일반론을 케이스 소견처럼 쓰지 말 것 | 해설을 **출처가 다른 3블록**으로 분리: `case_facts`(dataset_verified) / `disease_info`(literature_based) / `case_findings`(expert_reviewed). 있는 블록만 `content_levels` 에 나온다 |
| 4 | 좌/우 편측성을 추측하지 말 것 | **DICOM `ImageOrientationPatient` 에서 계산.** 202/203/204/207/212 우측, 211 좌측 |
| 5 | 전문가 GT 를 보정하지 말 것 | 최소 면적 필터·구멍 메우기·스무딩 **전부 금지**. 시작/끝 slice 의 2~24px 파편도 그대로 등록 |
| 6 | 모델을 붙이더라도 채점과 섞이면 안 된다 | 학습 노트북 재현 검증 통과(`PREPROCESS_VERIFIED=True`) 후 연결하되, **미리 계산한 sidecar** 를 `ai_prediction` 참고 정보로만 서비스. `verify_cases.py` 가 stale sidecar 를 실패로 잡는다 |
| 7 | `/api/analyze` 의 고정 mock 응답은 사실상 거짓 결과다 | **고정 mock 제거.** 3D volume 모델을 단일 PNG 에 억지로 쓰지 않고 `status: "model_unavailable"` 로 준비 중임을 밝힌다. 데모는 `MEDISCAN_ANALYZE_DEMO=1` 일 때만 `status: "demo"` + `is_demo: true` 로 분리 |
| 8 | `create_all` 은 스키마 변경을 감당 못 한다 | **Alembic 도입**(`backend/alembic/`, 리비전 2개). 기동 시 자동 upgrade, 모델<->마이그레이션 드리프트를 테스트로 감지 |

**v0.3 대비 API 변경 요약**

| 구분 | v0.3 | v0.4 |
|---|---|---|
| 해설 | 평평한 `key_findings` / `review_status` | `case_facts` / `disease_info` / `case_findings` 3층 + `content_levels` |
| AI 예측 | `model_version` / `mask_url` / `dice_vs_reference` | `detected` / `representative_slice_dice` / `computed_at` 추가 |
| 케이스 단위 | 슬라이스 1장 | **volume** + `case_slices`(원본 slice_index 보존) |
| `/api/analyze` | 고정 mock 결과 | `status` / `is_demo` / `unavailable_reason` |

---

## 3. 프로젝트 폴더 구조

```
mediscan-note/                       git 저장소 (초기 커밋 9383c15, 추적 파일 112개)
├── CLAUDE.md                        프로젝트 브리프
├── docs/api-spec.md                 API 명세 v0.4 + 화면별 기능정의서 (계약 원본)
├── review_bundle.md                 ← 이 문서
│
├── backend/                         FastAPI (app 2,486줄 + tests 2,956줄 + scripts 2,215줄)
│   ├── README.md · requirements.txt · requirements-dev.txt · pytest.ini · .env.example
│   ├── alembic/                     **스키마의 기준.** 리비전 2개, 기동 시 자동 upgrade
│   ├── app/
│   │   ├── main.py(64)              앱 진입점, StaticFiles 마운트, /health
│   │   ├── db.py(93)                engine/세션/DATABASE_URL/마이그레이션 실행
│   │   ├── models.py(132)           SQLAlchemy 모델 (cases=volume, case_slices=slice)
│   │   ├── schemas.py(222)          pydantic 계약 모델
│   │   ├── security.py(110)         scrypt 해싱 + HMAC 서명 토큰
│   │   ├── deps.py(45)              current_user 의존성 (401)
│   │   ├── repository.py(70)        has_matched / needs_review 파생 조회
│   │   ├── grading.py(228)          ROI 채점 — reference mask 전용
│   │   ├── masks.py(140)            마스크 디코딩 + Dice/IoU (fill_holes 미사용)
│   │   ├── model_predictions.py(110) 미리 계산된 예측 sidecar 로더
│   │   ├── explanations.py(52)      해설 3층 조립 + content_levels 파생
│   │   ├── disease_content.py(141)  질환 문헌 콘텐츠 로더
│   │   ├── uploads.py(207)          업로드 검증 + 메타데이터 제거
│   │   ├── inference.py(127)        부위별 모델 레지스트리
│   │   ├── static_files.py(90)      케이스 자산 경로/URL
│   │   ├── seed.py(139)             mock_data → DB 시드 (기본 OFF)
│   │   ├── routers/                 auth(148) consents(14) cases(117) wrong_notes(67) analyze(170)
│   │   ├── content/diseases/        질환 문헌 학습정보 JSON (**커밋 대상**, 전정신경초종 1건)
│   │   ├── mock_data/               **테스트 픽스처 전용** 합성 데이터 (서비스 DB 미투입)
│   │   └── static/cases/            실제 케이스 영상·기준 마스크 (**gitignore**)
│   ├── scripts/                     실데이터 파이프라인 CLI
│   │   ├── export_vs_seg_npy.py(456)         DICOM/RTSTRUCT → npy (ROI 선택 포함)
│   │   ├── build_review_packet.py(322)       육안 검수용 패킷
│   │   ├── make_review_overlays.py(174)      검수 오버레이 이미지
│   │   ├── build_vs_seg_case_assets.py(250)  npy → PNG 자산
│   │   ├── import_cases.py(459)              manifest → DB 등록
│   │   ├── run_model_predictions.py(254)     예측 미리 계산 (기존 결과 대조)
│   │   ├── verify_cases.py(188)              등록 상태·stale sidecar 점검
│   │   └── remove_cases.py(112)              케이스 삭제
│   ├── data/                        실데이터 작업 폴더 (**gitignore**, manifest.example.json 만 커밋)
│   └── tests/                       conftest + 13개 파일 = **241 테스트**
│
├── frontend/                        Vue 3 + Vite (src 4,470줄)
│   └── src/  api/ stores/ router/ components/ views/ style.css
│
├── models/
│   ├── _template/inference.py(82)      새 부위 추가용 템플릿
│   └── brain_mri_vs/inference.py(275)  뇌 MRI — **연결됨**(volume 입력, 참고 정보 전용)
│
└── tools/browser-verify/            헤드리스 브라우저 검증 스크립트 3종 (단위 테스트 아님)
```

---

## 4. 현재 구현 완료 기능

### 인증 · 동의

- 이메일 가입/로그인, SNS 간편가입 3종(**provider_token 은 mock**)
- 비밀번호 `hashlib.scrypt` 해싱 (평문 저장 없음)
- HMAC-SHA256 서명 + 만료(기본 7일) 토큰. 토큰 없음/위조/만료/삭제된 사용자 → 401
- 필수 동의 5 + 선택 1. 동의 이력은 **갱신이 아니라 append** (버전·시각 포함 증빙)
- `/api/analyze` 는 최신 `agree_sensitive_data` 를 서버가 확인 → 없으면 403

### 판독훈련 · 채점 (v0.4 핵심)

- **채점 기준은 전문가 검수 reference mask 하나뿐.** AI 예측은 채점에 일절 관여하지 않음
- 실제 마스크 Dice/IoU/위치점수 계산 (numpy + Pillow)
- 판정: Dice ≥ 0.60 `match`, ≥ 0.15 `partial_match`, 그 외 `mismatch`
- **ROI 자동 보정 없음** — 칠한 면적 그대로 채점
- ROI 도구는 **브러시 + 지우개**만 (단일 클릭은 면적이 없어 Dice 채점과 맞지 않아 제외)
- 기준 마스크 없는 케이스: `gradable: false` 로 제출 버튼 차단, 강제 제출 시 **422 + 이력 미생성**

### 실데이터 케이스 (뇌 MRI 전정신경초종, VS-SEG)

- **6케이스 등록 완료** — VS-SEG-202/203/207/211/212(모델 검출 양호) + **204**(모델 미검출)
- 케이스 = volume 1개. 화면 표시·채점은 **대표 slice**(병변 면적 최대), 슬라이스 자산은
  `case_slices` 에 **원본 slice_index 그대로** 저장 (2.5D 확장 대비)
- 파이프라인을 **DICOM → npy → 육안 검수 → PNG 자산 → 등록** 으로 분리해 사람이 확인하는 지점을 남김
- 편측성은 추측하지 않고 **DICOM 방향 태그에서 계산** (202/203/204/207/212 우측, 211 좌측)
- 전문가 GT 는 손대지 않는다 — 최소 면적 필터·구멍 메우기·스무딩 없음
- 흉부 X-ray 합성 케이스(CXR-000x)는 파이프라인 검증용 fixture 였고 **서비스에서 제거**(테스트 안에서만 생성)

### 해설 3층 (출처 분리)

| 블록 | 출처 | 현재 6케이스 |
|---|---|---|
| `case_facts` | 데이터에서 계산한 사실 (dataset_verified) | 있음 |
| `disease_info` | 질환 문헌 일반론 (literature_based) | 있음 — `content/diseases/vestibular_schwannoma.json` |
| `case_findings` | 전문가가 이 케이스를 보고 쓴 소견 (expert_reviewed) | **비어 있음** (검토자·검토일 없이는 등록하지 않는다) |

→ 현재 `content_levels: ["dataset_verified", "literature_based"]`

### AI 예측 (참고 정보 전용)

- 뇌 MRI 모델 **연결됨**. 학습 노트북(cell 6/7/8)의 전처리·모델 구조를 그대로 이식해
  산출물 대조를 통과한 뒤 `PREPROCESS_VERIFIED = True` 로 전환
- 3D volume 모델이라 **예측을 미리 계산해 sidecar 로 서비스** — 백엔드는 직접 추론하지 않아
  torch/monai 불필요. 모델 버전이 바뀌면 수동 재계산(`run_model_predictions.py` → `verify_cases.py`)
- `verify_cases.py` 가 sidecar 의 model_version / GT voxel 수를 현재 상태와 대조해 **stale 예측을 실패로 잡는다**
- **VS-SEG-204 = AI 실패와 채점 독립성의 대표 케이스** (9절 참고)

### 화면 (docs/api-spec.md 4절)

| 화면 | 상태 |
|---|---|
| 0 로그인/회원가입 + 동의 | 동작 |
| 1 케이스 목록 (학습완료/복습필요/미시도/채점준비중 뱃지) | 동작 |
| 2 판독 훈련 (다크 뷰어, 브러시+지우개) | 동작 |
| 3 결과 비교 (사용자=파랑/기준=초록/겹침=노랑 픽셀 합성) | 동작 |
| 4 학습 해설 (3층 블록, 있는 것만 표시) | 동작 |
| 5 내 영상 분석 | 업로드·검증 동작 / 분석은 **`model_unavailable`(준비 중)** — MVP 범위 밖 |
| 6 복습노트 + 재도전 | 동작 |
| 7 진행현황 | 동작 (프론트 집계) |

### 업로드 검증 (`/api/analyze`)

- base64 길이(디코딩 전) → 실제 포맷(PNG/JPEG) → 손상 여부 → 크기(64~4096) → 픽셀 수 → region 좌표
- 클라이언트 MIME 은 신뢰하지 않음. 프론트 검사는 UX 용
- **업로드 영상 미저장** (메모리 처리) + **EXIF 등 메타데이터 제거**
- 검증을 통과해도 **분석 결과를 지어내지 않는다** — `status: "model_unavailable"`.
  발표용 예시가 필요하면 `MEDISCAN_ANALYZE_DEMO=1`(기본 OFF) 로만 `status: "demo"` + `is_demo: true`

### 인프라

- `DATABASE_URL` 로 SQLite ↔ PostgreSQL 전환. **Alembic 마이그레이션이 스키마의 기준**(기동 시 자동 upgrade)
- 케이스 영상·마스크를 백엔드가 서빙(`/static`), CORS 허용으로 프론트 canvas 픽셀 읽기 가능.
  영상 URL 은 요청 주소 기준으로 생성 (로컬 개발 포트 8010)
- 부위별 모델 레지스트리 — 팀원이 `models/<부위>/inference.py` 만 추가하면 백엔드 수정 불필요

---

## 5. 아직 mock / 미완성인 기능

| 항목 | 현재 상태 | 비고 |
|---|---|---|
| **`/api/analyze` 분석 결과** | **`model_unavailable`** — 검증만 수행하고 결과는 내지 않음 | 고정 mock 은 제거. 단일 이미지용 2D 모델 확보 후 구현 |
| **케이스별 영상 소견 `case_findings`** | **비어 있음** | 의료 전문가 검토 필요. 검토자·검토일 없이는 등록하지 않는다 |
| 다른 부위 모델 4종 | 폴더 없음 | 템플릿(`models/_template/`)만 준비 |
| AI 예측 재계산 | **수동** (`run_model_predictions.py` → sidecar → `verify_cases.py`) | 자동화는 MVP 범위 밖. stale 은 verify 가 잡는다 |
| SNS `provider_token` | mock 문자열 | 각 사 서버 검증 미구현 (화면에 "개발용 예시 로그인" 명시) |
| 슬라이스 네비게이션 | 대표 slice 만 표시 | 자산·`case_slices` 는 준비됨, UI 미구현 |
| DICOM 업로드 | 미지원 (PNG/JPEG 만) | 태그 비식별화 필요 — MVP 범위 밖 |
| PostgreSQL | 코드·마이그레이션만 존재, SQLite 로만 검증 | 배포 전 전환 검증 필요 |
| 관리자 기능 | 없음 | 케이스 등록은 CLI(`scripts/import_cases.py`)로만 |
| 비밀번호 재설정/이메일 인증/탈퇴 | 없음 | |
| 프론트 단위 테스트 | 없음 (vitest 미도입) | 백엔드 241개 + 브라우저 E2E 3종 |
| 배포 하드닝 | 미완 | `MEDISCAN_SECRET_KEY` 주입, CORS 좁히기 (8절 참고) |

---

## 6. 주요 코드 발췌

> 전체 코드는 리포에 있습니다 (커밋 `9383c15`). 여기서는 리뷰 포인트가 있는 부분만 옮깁니다.

### 6-1. `app/grading.py` — 채점 진입점 (v0.4 핵심)

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
        "explanation": explanations.build(case),           # 3층 블록 + content_levels
    }
```

```python
def ai_prediction(case, reference_mask=None) -> dict | None:
    """모델 참고 정보. **채점에는 절대 쓰이지 않는다.**

    두 경로가 있다:
      1. 미리 계산된 sidecar (뇌 MRI 처럼 volume 입력 + 무거운 모델) — scripts/run_model_predictions.py
      2. 요청 시 2D 추론 (가벼운 slice 단위 모델) — models/<부위>/inference.py 의 predict()

    실패해도 예외를 밖으로 내보내지 않는다 — 참고 정보가 없다고 채점이 막히면 안 된다.
    """
    precomputed = model_predictions.load(case.case_id)
    if precomputed is not None:
        return precomputed

    if not inference.is_available(case.body_part):
        return None

    module = inference.get_module(case.body_part)
    # volume 입력 모델은 slice PNG 로 부르면 안 된다 (학습 때와 다른 입력이 된다)
    if getattr(module, "INPUT_KIND", "image") == "volume":
        return None
    ...
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

### 6-5. `models/brain_mri_vs/inference.py` — 연결 조건과 volume 가드

```python
MODEL_VERSION = "vs-seg-unet2d5-att-hard-t1"

# 이 모델은 volume 입력이다. 백엔드는 이 값을 보고 slice PNG 로 부르지 않는다.
INPUT_KIND = "volume"

# 학습 노트북(cell 6/7/8)과 동일함을 산출물 대조로 확인했다 -> True.
# (VS-SEG-202 예측 마스크 배열 완전 일치, 6케이스 Dice 소수점 4자리 일치)
PREPROCESS_VERIFIED = True

ENABLE_ENV = "MEDISCAN_ENABLE_BRAIN_MRI_MODEL"


def unavailable_reason() -> str | None:
    """왜 **이 프로세스에서** 추론할 수 없는지 한 줄로. 가능하면 None.

    백엔드 서비스에서는 보통 "추론 의존성 미설치"가 나오는 것이 정상이다 —
    서비스는 미리 계산된 sidecar 를 쓰고 직접 추론하지 않는다 (app/model_predictions.py).
    """
    if not PREPROCESS_VERIFIED:        return "전처리 미검증 (PREPROCESS_VERIFIED=False)"
    if not weights_path().exists():    return f"가중치 없음: {weights_path()}"
    if not (source_path() / ...).exists():
                                       return f"모델 소스 없음: {source_path()}"
    try: import monai, torch
    except ImportError as exc:         return f"추론 의존성 미설치 ({exc.name}) — 서비스는 미리 계산된 예측을 사용합니다"
    if os.getenv(ENABLE_ENV, "").strip() not in {"1", "true", "True"}:
                                       return f"환경변수 옵트인 필요: {ENABLE_ENV}=1"
    return None
```

**핵심**: 서비스 런타임은 학습 리포·torch 에 의존하지 않는다. `MEDISCAN_VS_SEG_ROOT` 를 쓰는 것은
오프라인 예측 계산(`scripts/run_model_predictions.py`)뿐이고, 배포된 백엔드는 sidecar 만 읽는다.

**리뷰 포인트**: 미리 계산 방식이라 모델 교체 시 sidecar 갱신을 잊으면 조용히 낡은 결과가 나갈 수 있다.
지금은 `verify_cases.py` 가 model_version / GT voxel 수를 대조해 stale 을 잡는 것으로 막고 있다.

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
241 passed in 47s        (backend/ 에서 pytest — 커밋 9383c15 기준 재확인)
```

| 파일 | 개수 | 범위 |
|---|---|---|
| `test_case_import.py` | 17 | 케이스 등록·검증·gradable 판정, 등록된 케이스 채점 |
| `test_volume_case_import.py` | 17 | volume 케이스: 원본 slice_index 보존, 작은 GT 유지, 재등록 정리, 해설 블록 규칙 |
| `test_roi_selection.py` | 16 | VS-SEG export 의 종양 ROI 선택 (AN 인식, 자동 선택은 후보 1개일 때만) |
| `test_explanation_content.py` | 20 | 해설 3층 구조, content_levels 파생, 질환 문헌 콘텐츠 로더 |
| `test_ai_prediction.py` | 13 | 미리 계산된 예측 sidecar, **AI 실패(204)와 채점 독립성** |
| `test_api_contract.py` | 18 | 문서(api-spec.md) ↔ 실제 응답 필드 불일치 감지 |
| `test_migrations.py` | 7 | upgrade/downgrade, 모델↔마이그레이션 드리프트, 레거시 DB 감지 |
| `test_analyze_upload.py` | 37 | 포맷 위장·손상·크기·압축폭탄·region·미저장·EXIF 제거·403 |
| `test_auth.py` | 29 | 가입·동의 append·로그인·토큰(만료/변조/삭제된 사용자)·SNS |
| `test_grading.py` | 22 | 등급 판정, 계약 스키마, ROI 검증, 422+이력미생성, **AI 미개입** |
| `test_isolation.py` | 22 | 사용자간 데이터 격리, 보호 엔드포인트 토큰 요구 |
| `test_wrong_notes.py` | 11 | has_matched/needs_review 매트릭스, 재도전 |
| `test_model_status.py` | 12 | 모델 상태·가드, volume 모델을 slice 로 부르지 않는지, /health 사유 |

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

| 스크립트 | 하는 일 |
|---|---|
| `user-flow.mjs` | 신규 가입 → **미시도** → 엉뚱한 곳 제출 **불일치(0.0)** → 복습노트 적재 → 재도전 **일치** → 복습노트에서 제거 → 진행현황 |
| `consent-and-sns.mjs` | 화면 0: 동의 체크박스(실제 마우스 클릭) + SNS 개발용 예시 로그인 3종 + 이메일 가입 |
| `screenshot-all.mjs` | 화면 0~7 전부 촬영 (모바일 폭 포함) |

- 재도전 단계는 **기준 마스크 모양을 따라** 칠한다 (브러시 반지름만큼 침식한 영역만 스캔라인으로).
  실제 병변이 불규칙해 고정 반지름 원으로는 Dice 가 임계값(0.60) 언저리에 머물러 불안정했기 때문이다.
  **채점 임계값은 바꾸지 않았다** — 바뀐 것은 "사용자가 얼마나 정확히 칠하는가" 쪽이다.
  VS-SEG-202 기준 3회 반복 모두 Dice 0.9387 (`tools/browser-verify/README.md`).
- `user-flow.mjs` 는 재도전이 `match` 가 아니거나 Dice < 0.85 이거나 콘솔 에러가 있으면 **exit 1**.
- 맞힌 뒤 다시 틀린 상태에서 뱃지가 **"학습완료 | 복습필요"** 둘 다 노출되는 것도 확인. **콘솔 에러 0건.**

### 채점 실측 (합성 fixture 기준 — 지금은 테스트 안에서만 쓰는 케이스, 병변 중심 (338,307) 반지름 32)

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
프론트 `npm run build` 통과. 로컬 개발은 backend **:8010** / frontend **:5173**.

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
| 7-1 | **케이스별 영상 소견(`case_findings`)이 비어 있다(null).** 의료 전문가를 확보하기 어려워,
        해설을 출처별 3층(`case_facts` / `disease_info` / `case_findings`)으로 나누고 검증된 것만 서비스한다.
        현재 6케이스는 `content_levels: ["dataset_verified", "literature_based"]` —
        데이터에서 계산한 사실과 질환 문헌 학습정보(`content/diseases/vestibular_schwannoma.json`)는
        있고, **전문가 소견만 비어 있다.** 검토자·검토일 없이는 등록하지 않는다 |
| 7-2 | 211/212 의 종양 ROI 이름이 `AN` 이라 예전 키워드 목록에 걸리지 않았고, **우연히 첫 번째 ROI**
        여서 맞았다. 지금은 `AN`/`acoustic neuroma` 를 키워드에 넣고, 못 찾으면 **중단**하도록 바꿨다 |
| 8 | 기준 마스크 검수 절차가 **문서상 규칙일 뿐** 시스템적 강제가 없음 (DB 필드 없음).
      해설 쪽은 `case_findings` 가 `reviewer` / `reviewed_at` 를 **필수 필드**로 요구하는 정도로만 강제된다
      (필드가 있다는 것이 검토를 보증하지는 않는다) |
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

MVP 구현은 마무리됐다 (실데이터 등록 / Alembic / 문헌 콘텐츠 / 뇌 MRI 모델 연결 완료).
남은 것은 아래 네 가지다.

| 순위 | 항목 | 내용 |
|---|---|---|
| 1 | **케이스별 영상 소견(`case_findings`)** | 의료 전문가 검토 후 등록. **검토자·검토일이 함께 있어야** 등록된다. 지금은 null 이고 화면에서 해당 블록을 그리지 않는다 |
| 2 | **화면 5 용 단일 이미지 2D 모델** | 3D ceT1 volume 모델을 PNG/JPEG 한 장에 억지로 쓰지 않는다 — 학습 때와 다른 입력이면 조용히 틀린 결과가 나온다. 모델 확보 전까지 `model_unavailable` 유지. DICOM 시리즈 업로드도 범위 밖 |
| 3 | **다른 부위 모델 확장** | 뇌CT / 흉부X-ray / 복부CT / 무릎. `models/_template/inference.py` 복사 + 같은 응답 스키마 → 백엔드 수정 불필요. 10절 체크리스트를 부위마다 다시 밟는다 |
| 4 | **배포 하드닝** | `MEDISCAN_SECRET_KEY` 주입, CORS 좁히기, PostgreSQL 전환 검증, SNS provider_token 실검증(현재는 **개발용 예시 로그인**이지 실제 OAuth 가 아니다), 로그에 요청 본문이 남지 않는지 확인 |

### 모델 연결 결과 요약 (v0.4, 뇌 MRI)

| 항목 | 상태 |
|---|---|
| 전처리·모델 구조 | 학습 노트북 cell 6/7/8 그대로 이식, 산출물 대조 통과 → `PREPROCESS_VERIFIED=True` |
| 재현 검증 | VS-SEG-202 예측 마스크 배열 완전 일치, 6케이스 Dice·voxel 전부 일치 |
| 연결 방식 | 3D volume 모델이라 **미리 계산한 sidecar** 를 서비스 (백엔드에 torch/monai 불필요) |
| 채점 영향 | **없음.** `ai_prediction` 참고 정보로만 나간다 |
| 재계산 | MVP 는 수동 (`run_model_predictions.py` → sidecar 갱신 → `verify_cases.py` 가 stale 검사) |

### VS-SEG-204 — AI 실패와 학습 채점 독립성 검증 케이스

| 항목 | 값 |
|---|---|
| 전문가 GT | 존재 (3,628 voxel, 대표 slice 37 / 702px) |
| 사용자 제출(기준 마스크 그대로) | Dice **1.0** / `match` |
| AI 예측 | Dice **0.0** / `detected: false` / `mask_url: null` |

모델이 완전히 실패해도 학습자 채점은 전문가 GT 기준으로 정상 동작한다
(`tests/test_ai_prediction.py::test_ai_failure_case_shape_vs_seg_204`).

---

## 10. 부위별 모델을 붙일 때의 체크리스트

뇌 MRI 에서 실제로 밟은 항목이다. **다른 부위를 추가할 때 그대로 다시 밟는다.**
하나라도 어긋나면 조용히 틀린 결과가 나온다.

### 체크포인트

| # | 항목 | 뇌 MRI 결과 |
|---|---|---|
| 1 | 저장 형식 (`torch.save(model)` vs `state_dict`) | `state_dict`, VS_Seg 의 `UNet2d5_spvPA` 에 `strict=True` 로드 |
| 2 | 학습 시점 torch/CUDA 버전과 추론 환경 호환성 | 학습 venv 에서 오프라인 계산하므로 서비스와 분리 |
| 3 | 체크포인트 보관 위치·공유 방법 | 리포 밖(학습 리포). git 에 커밋하지 않음 |

### 전처리 (가장 위험)

| # | 항목 | 뇌 MRI 결과 |
|---|---|---|
| 4 | 입력 단위 | **volume 전체** (slice 1장 아님) → `INPUT_KIND = "volume"` |
| 5 | 정규화 | 노트북 cell 6 그대로 **volume z-score**. 표시용 PNG 전처리(1~99% 클리핑)와 **절대 공유하지 않는다** |
| 6 | 추론 방식 | `sliding_window_inference(roi (384,384,64), gaussian, overlap 0.25)` → argmax. VRAM 부족 시 (256,256,32) 폴백(노트북과 동일) |
| 7 | 검증 방법 | `run_model_predictions.py --verify-against <노트북 outputs>` 로 Dice·voxel 수·마스크 배열 대조 |

> 위 항목이 산출물 대조로 확인되기 전에는 `PREPROCESS_VERIFIED = True` 로 바꾸면 안 된다.

### 검증

| # | 항목 | 상태 |
|---|---|---|
| 8 | 예측 좌표계·해상도가 기준 마스크와 일치하는가 | 확인됨 (512×512, 원본 slice_index 보존) |
| 9 | 미검출 케이스 원인 분석 | **미완.** test 10명 중 8명 검출, threshold 0.5→0.001 로도 개선 안 됨. 확률맵 시각화·종양 크기 비교(소형 intracanalicular 가능성) 남음 |
| 10 | stale 예측 감지 | `verify_cases.py` 가 sidecar 의 model_version / GT voxel 수를 대조 |

### 통합

| # | 항목 | 상태 |
|---|---|---|
| 11 | 예측 마스크 저장·서빙 위치 | 케이스별 sidecar(`prediction.png` + `prediction.json`) → `ai_prediction.mask_url` |
| 12 | 추론 시간 | CPU 기준 케이스당 수 분 → **요청 시 추론하지 않고 미리 계산**하는 이유 |
| 13 | `/api/analyze` 는 기준 마스크가 없는 사용자 업로드다 | 그래서 **결과를 내지 않는다** (`model_unavailable`). 2D 모델 확보 후 신뢰도 표기와 함께 구현 |

### 확인 방법

```bash
curl http://localhost:8010/health          # 부위별 모델 상태·사유
cd backend && pytest tests/test_model_status.py -v
cd backend && python -m scripts.verify_cases   # 등록 케이스 + sidecar stale 점검
```

---

## 부록. 리뷰에서 특히 봐주셨으면 하는 것

1. **채점 임계값과 지표 설계** — Dice 0.60/0.15, `location_score` 정규화식이 학습 도구로 타당한가
2. **`has_matched` / `needs_review` 동시 노출** UX
3. **인증 설계** — 자체 HMAC 토큰 vs 표준 JWT, localStorage, 로그아웃/폐기 전략
4. **업로드 검증 순서와 누락된 공격 표면** (SVG·다중 프레임·polyglot 파일 등)
5. **동적 모듈 로드**(`app/inference.py`)의 안전성
6. **API 계약 유지 원칙**이 실제로 지켜지는 구조인지 (모델 교체 시 프론트 무수정)
