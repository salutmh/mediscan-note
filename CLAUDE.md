# 메디스캔노트 (MediScanNote) — 프로젝트 브리프

이 파일은 클로드 코드가 이 리포지토리를 처음 열었을 때 프로젝트 전체 맥락을 파악하기 위한 문서입니다.
새 세션에서 작업을 시작할 때 이 파일을 먼저 읽고, `docs/api-spec.md`를 함께 참고하세요.

## 한 줄 요약

예비 보건의료인이 의료영상에서 이상 부위를 ROI로 직접 판독·평가받고, 기준과 일치하지 않은 케이스를 반복 훈련하며,
사용자가 불러온 의료영상에 대한 AI 분석 결과까지 확인할 수 있는 통합 의료영상 학습 웹 서비스.

## 현재 상태 (2026.09 기준)

- **Closed Beta 준비 단계.** MVP 구현을 마치고 제품 완성도를 올리는 중이다.
  현재 상태와 다음 작업은 **`docs/CLAUDE_HANDOFF.md` 를 먼저 읽는다** (매 작업마다 갱신된다).
  배포는 `docs/DEPLOYMENT.md`, 준비 상태는 `docs/RELEASE_READINESS.md`.
- 팀 구성: 팀원 5명이 부위별로 모델을 각자 담당 (뇌MRI/뇌CT/흉부X-ray/복부CT/무릎)
- 이 리포는 **서비스(백엔드+프론트) 전용**. 모델 학습·실험 코드는 별도 폴더에서 진행하고, 검증이 끝난 모델만
  `models/<부위>/inference.py` 형태의 가벼운 추론 wrapper로 이 리포에 들어온다. 체크포인트(.pth 등)와
  학습 노트북, 원본 데이터셋은 이 리포에 절대 포함하지 않는다 (`.gitignore` 참고).
- 뇌 MRI 담당(전정신경초종, VS_Seg pretrained 2.5D Attention U-Net) 진행 상황:
  - test 10명 중 8명 검출, 평균 Dice 0.7304 / 중앙값 0.9353 / 최고 0.9621
  - 미검출 2건은 threshold 조정(0.5→0.001)으로도 개선 안 됨 → 모델 자체의 미검출 케이스로 판단, 원인 분석 진행 중
  - 다음 확인: 미검출 2건의 확률맵 시각화, 종양 크기 비교 (소형 intracanalicular 종양 가능성)
- 프론트/백엔드 진행 상황:
  - 백엔드: 화면 0~7 이 쓰는 엔드포인트 전부 동작. **DB 연동 완료** (SQLAlchemy, `DATABASE_URL` 로
    로컬 SQLite ↔ PostgreSQL 전환). 비밀번호 해싱(scrypt) + 서명·만료 있는 토큰 + 401/403 강제,
    사용자별 학습 상태(`has_matched`/`needs_review`)·복습노트·제출 이력 저장까지 완료.
    자세한 내용은 `backend/README.md`.
  - 프론트: Vue 3 + Vite. 화면 0~7 전부 구현, 디자인 토큰(Pretendard, 밝은 임상 톤 + 다크 뷰어) 적용.
    자세한 내용은 `frontend/README.md`.
  - 채점(API 계약 **v0.4**): **전문가 검수 reference mask 기준 Dice/IoU** 로만 평가한다.
    AI 예측은 채점에서 완전히 분리되어 `ai_prediction` 참고 정보로만 나간다.
    기준 마스크가 없는 케이스는 422 로 거부하고 이력도 남기지 않는다.
    학습 상태는 `has_matched`(학습완료) / `needs_review`(복습필요) 두 축으로 분리.
  - 업로드(`/api/analyze`, 화면 5): **이번 MVP 범위에서 실제 분석 기능은 제외**한다.
    서버 검증(포맷·손상·크기·압축폭탄·region)과 영상 미저장 + EXIF 제거는 그대로 동작하고,
    응답은 `status: "model_unavailable"` 로 "준비 중"임을 밝힌다.
    3D ceT1 volume 모델을 PNG/JPEG 단일 이미지에 억지로 쓰지 않는다 — 학습 때와 다른 입력이면
    조용히 틀린 결과가 나온다. 단일 이미지용 2D 모델을 확보한 뒤 구현한다.
    DICOM 시리즈 업로드도 이번 MVP 범위 밖이다.
    `MEDISCAN_ANALYZE_DEMO` 는 **기본 OFF**(개발 확인용). 켜면 `status: "demo"` + `is_demo: true`
    로 실제 분석과 명확히 분리해 표시된다.
  - 뇌 MRI 모델: **연결됨 (참고 정보 전용)**. 학습 노트북의 전처리·모델 구조를 그대로 재현해
    산출물 대조를 통과했고(`PREPROCESS_VERIFIED=True`), 6케이스 예측을 **미리 계산해** sidecar 로
    서비스한다. 백엔드는 직접 추론하지 않아 torch/monai 가 필요 없다.
    **채점에는 절대 쓰이지 않는다** — `ai_prediction` 참고 정보로만 나간다.
  - 스키마: **Alembic 마이그레이션이 기준** (`backend/alembic/`). 앱 기동 시 자동 upgrade.
    모델을 바꾸면 반드시 `alembic revision --autogenerate` 로 마이그레이션을 만든다.
  - 실제 케이스 등록: `python -m scripts.import_cases <manifest>` — 영상·기준마스크·해설을 함께 등록.
    실제 데이터 파일은 커밋하지 않는다 (`backend/data/`, `app/static/cases/` gitignore).
  - 테스트: 백엔드 pytest **1011개** (`cd backend && pytest`) — **SQLite·PostgreSQL 양쪽에서 통과**
    (`scripts/verify_postgres.py --with-tests`). 프론트 vitest **108개** (`cd frontend && npm test`).
    브라우저 검증은 `tools/browser-verify/` — E2E 7종(user-flow / slice-navigation /
    consent-and-sns / screenshot-all / error-paths / case-review / admin-ux)
    + 접근성 점검(`a11y-audit`) + 좁은 화면 점검(`responsive-check`).
    배포 형태 시뮬레이션은 `tools/staging/`. 동시 쓰기 스모크는 `scripts/load_smoke.py`.
  - 보안: production 에서 `MEDISCAN_SECRET_KEY`/`MEDISCAN_CORS_ORIGINS`/`DATABASE_URL` 이
    없으면 **기동이 실패한다**. 인증 엔드포인트 rate limit, 로그아웃 시 서버측 토큰 폐기,
    회원 탈퇴(화면 포함)까지 구현됐다.
  - 운영: `/admin/cases` 최소 CMS (활성·비활성 / 난이도 / 전문가 소견). 최초 운영자는
    `scripts/grant_admin.py` 로만 지정한다. 백업은 `scripts/backup_db.py`.
  - 로컬 개발 포트: backend **:8010**, frontend **:5173**. 영상 URL 은 요청 주소 기준으로 생성된다.
- **실데이터 = 뇌 MRI 전정신경초종(VS-SEG)**. 흉부 X-ray 합성 케이스(CXR-000x)는 파이프라인 검증용
  fixture 였고 **서비스에서 제거**했다 (지금은 테스트 안에서만 만들어 쓴다).
  - 등록 완료 6케이스: VS-SEG-202/203/207/211/212(검출 양호) + 204(모델 미검출).
    케이스 = volume 1개이고, 화면 표시·채점은 **대표 slice**(병변 면적 최대)로 한다.
    slice 별 자산은 `case_slices` 에 있고 **원본 slice_index 를 그대로 보존**한다(2.5D 확장 대비).
  - DICOM -> npy -> 육안 검수 -> PNG 자산 -> 등록 **4단계로 분리**해 진행한다. 중간에 사람이
    확인하는 지점을 남기기 위해서다. 절차와 지켜야 할 규칙은 `backend/README.md` 참고.
  - **VS-SEG-204 = AI 실패와 학습 채점 독립성의 대표 케이스.** 전문가 GT(3,628 voxel)는 정상이고
    사용자가 기준대로 칠하면 Dice 1.0 / `match` 가 나오지만, AI 는 병변을 전혀 찾지 못한다
    (`dice_vs_reference: 0.0`, `detected: false`, `mask_url: null`).
    **AI 실패가 학습자 grade 에 아무 영향을 주지 않는다**는 것을 이 케이스로 확인한다
    (`tests/test_ai_prediction.py::test_ai_failure_case_shape_vs_seg_204`).
  - 해설은 **출처가 다른 3개 블록**이다 (API 계약 v0.4): `case_facts`(dataset_verified) /
    `disease_info`(literature_based) / `case_findings`(expert_reviewed).
    지금 6케이스는 `content_levels: ["dataset_verified", "literature_based"]` —
    사실 블록과 질환 문헌 정보가 있고, 케이스별 소견(`case_findings`)만 비어 있다.
    편측성은 DICOM 방향 태그로 계산했다: 202/203/204/207/212 우측, 211 좌측.
  - 모델 예측 sidecar 재계산은 **MVP 에서는 수동**이다. 모델 버전을 바꾸면
    `run_model_predictions.py` (기존 결과와 대조) -> sidecar 갱신 -> `verify_cases.py` 순서로 돌린다.
    `verify_cases.py` 가 sidecar 의 model_version / GT voxel 수를 현재 상태와 대조해
    **오래된(stale) 예측을 실패로 잡는다.**
  - `MEDISCAN_VS_SEG_ROOT` — 학습 리포 경로. Desktop 기본값은 **로컬 개발용**이며,
    **서비스 런타임은 학습 리포에 의존하지 않는다** (미리 계산된 sidecar 만 읽는다).
  - **남은 것은 이 네 가지뿐이다**:
    1. 케이스별 영상 소견 전문가 검토(`case_findings`) — 지금은 null, 검토자·검토일 없이는 등록하지 않는다
    2. 화면 5 용 단일 이미지 2D 모델 (확보 전까지 `model_unavailable` 유지)
    3. 다른 부위 확장 — 팀원들이 `models/_template/` 복사해서 추가
    4. **SNS 앱 등록** — 토큰 실검증 로직은 구현됐다(`app/social_auth.py`).
       각 사(카카오·구글·네이버)에 앱을 등록하고 ID 를 환경변수로 넣으면 켜진다.
       **설정 전까지 production 은 SNS 로그인을 503 으로 거부한다** — 검증 없는
       SNS 로그인은 토큰 값만 아는 사람이 그 계정으로 들어가는 계정 탈취 경로다.
       (배포 하드닝의 나머지는 완료: production 에서 `MEDISCAN_SECRET_KEY`/`MEDISCAN_CORS_ORIGINS`/
       `DATABASE_URL` 미설정 시 **기동 실패**, 개발 전용 스위치 3종도 production 에서 기동을 막는다.
       PostgreSQL 전환은 `scripts/verify_postgres.py` 로 검증 완료.)

## 기술 스택

- Frontend: Vue.js
- Backend: FastAPI
- DB: PostgreSQL
- 인프라(추후): AWS(웹/API/DB), Cloudflare Pages(프론트 배포)
- 모델: 부위별로 상이 (뇌 MRI는 PyTorch, 2.5D Attention U-Net)

## 개발 원칙

1. **프론트와 모델을 분리해서 병렬 진행한다.** 프론트는 `docs/api-spec.md`에 정의된 JSON 스키마와 동일한
   mock 데이터로 먼저 개발한다. 모델이 V1→V2→V3로 바뀌어도 이 스키마가 유지되는 한 프론트는 손대지 않는다.
2. **API 계약이 유일한 접점이다.** 백엔드 라우터를 만들 때도 `docs/api-spec.md`의 요청/응답 형태를 그대로 따른다.
   스키마를 바꿔야 하면 이 문서와 백엔드/프론트 양쪽을 함께 갱신한다.
3. **평가는 일치/부분 일치/불일치 3단계(`grade`: `match`/`partial_match`/`mismatch`)를 기본으로 한다.**
   기준 마스크와의 *일치 정도*를 뜻하는 표현을 쓴다 — 우리가 의료인이 아니므로 "정답/오답"처럼
   확정적인 의학적 판단으로 읽히는 표현은 쓰지 않는다. (boolean으로 갈지는 팀 논의 필요 — api-spec.md 5절 참고)
4. **검증되지 않은 의학 내용을 지어내지 않는다.** 우리는 의료인이 아니다.
   - 채점 기준은 **전문가가 검수한 reference mask** 뿐이다. 모델 예측은 채점에 관여하지 않는다.
   - 전문가 GT(RTSTRUCT 등)를 임의로 손대지 않는다 — 최소 면적 필터·구멍 메우기·스무딩 금지.
   - 해설은 **출처별로 분리한다**: 데이터에서 계산된 사실(`case_facts`), 질환 문헌 일반론
     (`disease_info`), 전문가가 이 케이스를 보고 쓴 소견(`case_findings`).
     문헌 일반론을 특정 케이스의 소견처럼 쓰지 않고, 없는 블록은 비워 둔다.
   - 전문가 소견에는 **검토자와 검토일을 함께** 남긴다 (누가 언제 본 내용인지 모르면 등록하지 않는다).
   - 좌/우 편측성처럼 계산할 수 있는 사실은 추측하지 말고 DICOM 태그에서 계산한다.
5. **다른 부위(흉부/복부/무릎/뇌CT) 모델도 같은 응답 스키마를 쓰도록 유도한다.** 그래야 프론트 컴포넌트를
   부위별로 재사용할 수 있다.
6. 무거운 파일(체크포인트, 데이터셋, 노트북)은 이 리포에 커밋하지 않는다. 실제 의료영상도 마찬가지다
   (`backend/data/`, `backend/app/static/cases/` 는 통째로 gitignore).

## 폴더 구조

```
medscannote/
  backend/            FastAPI 서비스 (DB 연동 완료)
    app/
      main.py           앱 진입점, 라우터 등록
      models.py         SQLAlchemy 모델 (cases = volume 1개, case_slices = slice)
      schemas.py        pydantic 응답 모델 (api-spec.md와 1:1 대응)
      grading.py        채점 — 기준 마스크 전용. AI 예측은 참고 정보로만
      model_predictions.py 미리 계산된 모델 예측 sidecar 로더
      explanations.py   해설 3층 조립 (case_facts / disease_info / case_findings)
      disease_content.py 질환 문헌 콘텐츠 로더
      content/diseases/ 질환별 문헌 학습정보 JSON (**git 커밋 대상**, 전정신경초종 1건 작성 완료)
      routers/          엔드포인트별 라우터
      static/cases/     실제 케이스 영상·기준 마스크 (gitignore)
      mock_data/        *.json — **테스트 픽스처 전용** 합성 데이터.
                        서비스 DB 에는 들어가지 않는다 (MEDISCAN_SEED_MOCK_CASES=1 일 때만 시드)
    alembic/            마이그레이션 — **스키마의 기준은 create_all 이 아니라 마이그레이션이다**
    scripts/            실데이터 파이프라인 CLI (export / 검수 / 자산생성 / 등록 / 점검 / 삭제)
    data/               실데이터 작업 폴더 (gitignore, manifest.example.json 만 커밋)
  frontend/           Vue 3 + Vite. 화면 0~7 + 계정(/account)·운영자(/admin/cases). vitest 59개
  models/
    brain_mri_vs/      전정신경초종 추론 wrapper (inference.py) — **연결됨**(volume 입력,
                       미리 계산한 sidecar 를 참고 정보로만 서비스)
    _template/         새 부위 추가용 템플릿
    <다른 부위>/        팀원들이 검증 끝나면 같은 패턴으로 추가
  docs/
    api-spec.md         API 명세 + 화면별 기능정의서 (원본)
```

## 회원가입 / 로그인

의료영상(민감정보)을 다루는 서비스라, 가입 시 이용약관·개인정보·민감정보 처리·AI 분석 성격 고지·연령 확인
5개 필수 동의 + 마케팅 수신(선택) 1개를 반드시 받는다. 동의 없이는 계정이 생성되지 않도록 백엔드에서
강제 검증한다 (`backend/app/routers/auth.py`의 `missing_required()` 체크 참고). 간편가입은 SNS(카카오/구글/네이버)
+ 이메일 로그인을 함께 지원하고, SNS 최초 가입도 동의 화면을 반드시 거치게 한다.
**SNS 토큰 실검증은 구현돼 있다** (`app/social_auth.py`) — 각 사에 토큰을 되물어
**바뀌지 않는 사용자 식별자**를 받아 계정 키로 쓴다. 각 사 앱 ID 만 환경변수로 넣으면 켜지고,
설정 전까지 **production 은 SNS 로그인을 거부한다**(개발에서는 예시 로그인이 그대로 동작).
검증 없이 토큰을 식별자로 쓰면 (a) 토큰 값만 아는 사람이 그 계정에 들어가고
(b) 토큰이 갱신될 때마다 같은 사람이 새 계정이 된다. 자세한 내용은
`docs/api-spec.md` 1장 참고.

## 시작 순서 (권장)

1. `backend/`: `pip install -r requirements.txt` 후 mock 데이터를 반환하는 엔드포인트부터 완성 (실제 DB 연결 전)
2. `frontend/`: `npm create vite@latest . -- --template vue` 로 프로젝트 생성 후, 화면 0(로그인/회원가입 + 동의)부터 시작 —
   이후 모든 API가 로그인 토큰을 요구하므로 화면 0을 가장 먼저 붙여야 다음 화면들을 mock으로도 자연스럽게 이어갈 수 있음.
   그다음 화면 1~4(케이스 목록 → 판독 → 결과비교 → 해설) 순서로 mock API 연결
3. ~~PostgreSQL 스키마 설계 및 backend DB 연동~~ → **완료** (SQLAlchemy + Alembic 마이그레이션 + 인증)
4. ~~실제 채점 연결~~ → **완료**. 전문가 검수 reference mask 기준 Dice/IoU 채점 동작.
   뇌 MRI 모델도 재현 검증 후 연결됐지만 **참고 정보 전용**이다 (채점에 관여하지 않는다)
5. ~~복습노트(화면 6)~~ → **완료**. 화면 5(사용자 영상 분석)는 **업로드·검증까지만** 완료이고
   분석은 단일 이미지 2D 모델 확보 전까지 `model_unavailable` 이다
6. 다른 부위 모델은 `models/_template/inference.py` 를 복사해서 추가 —
   백엔드 코드 수정 불필요 (`models/README.md` 참고)
7. 배포 — **`docs/DEPLOYMENT.md` 가 런북이다** (0절 체크리스트부터). 시크릿 주입·CORS·PostgreSQL 은
   가드와 검증이 붙어 있고, 남은 것은 SNS 실검증이다. 준비 상태는 `docs/RELEASE_READINESS.md`.

## 참고 문서

- `docs/api-spec.md` — 엔드포인트별 요청/응답 스키마, 화면별 기능정의서, mock 데이터 가이드
