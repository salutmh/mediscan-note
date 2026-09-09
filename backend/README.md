# backend

FastAPI 서비스. `docs/api-spec.md` 의 요청/응답 스키마를 그대로 구현한다.

## 실행

```
pip install -r requirements.txt      # 최초 1회 (numpy·pillow 포함)
uvicorn app.main:app --reload --port 8010   # http://localhost:8010
```

첫 실행 시 Alembic 마이그레이션이 적용된다. **합성 mock 케이스는 시드하지 않는다** —
실제 케이스는 `scripts/import_cases.py` 로만 등록한다 (아래 "실제 케이스 등록" 참고).
개발 중 자리표시자 케이스가 필요하면 `MEDISCAN_SEED_MOCK_CASES=1` 로 켠다 (테스트는 자동으로 켠다).
문서: http://localhost:8010/docs

## 테스트

```
pip install -r requirements-dev.txt
pytest                       # backend/ 에서 실행
pytest tests/test_isolation.py -v
```

임시 SQLite 파일을 만들어 돌기 때문에 개발용 `mediscan.db` 는 건드리지 않는다
(`tests/conftest.py` 가 app import 전에 `DATABASE_URL` 을 덮어쓴다).

| 파일 | 범위 |
|---|---|
| `tests/test_isolation.py` | 사용자간 데이터 격리, 보호 엔드포인트의 토큰 요구 |
| `tests/test_auth.py` | 가입·동의 검증, 로그인, 토큰(만료·변조·삭제된 사용자), SNS 간편가입 |
| `tests/test_grading.py` | 등급 판정, 기준 마스크 부재 시 422, ROI 검증, AI 예측이 채점에 개입하지 않음 |
| `tests/test_wrong_notes.py` | has_matched / needs_review 상태 매트릭스, 재도전 |
| `tests/test_analyze_upload.py` | 업로드 검증(포맷 위장·손상·크기·압축폭탄·region), 저장 안 함, EXIF 제거 |
| `tests/test_model_status.py` | 모델 unavailable 상태, PREPROCESS_VERIFIED 가드, /health 사유 노출 |
| `tests/test_migrations.py` | upgrade/downgrade, 모델↔마이그레이션 드리프트, 레거시 DB 감지 |
| `tests/test_case_import.py` | 케이스 등록·검증·gradable 판정, 등록된 케이스 채점 |
| `tests/test_volume_case_import.py` | volume 케이스: 원본 slice_index 보존, 작은 GT 유지, 재등록 정리, 해설 검토상태 |
| `tests/test_roi_selection.py` | VS-SEG export 의 종양 ROI 선택 (AN 인식, 자동 선택은 후보 1개일 때만) |
| `tests/test_explanation_content.py` | 해설 3층 구조, content_levels 파생, 질환 문헌 콘텐츠 로더 |
| `tests/test_ai_prediction.py` | 미리 계산된 예측 sidecar, **AI 실패(204)와 채점 독립성**, volume 모델 2D 호출 차단 |

현재 **241개**. 테스트가 실제로 회귀를 잡는지 변이(mutation)로 확인했다 — 채점 기준을 AI 예측으로
바꾸거나, fill 보정을 되살리거나, 사용자 격리를 없애면 해당 테스트가 실패한다.

## DB

### PostgreSQL 검증 (배포 전 필수)

개발은 SQLite, 배포는 PostgreSQL 이다. **테스트가 SQLite 에서만 돌면 이식성 문제를
배포에서 처음 만난다.** 실제로 이 검증을 처음 돌렸을 때 테스트 1건이 깨졌다 —
SQLite 는 외래키를 기본적으로 강제하지 않아, ORM cascade 를 우회하는 대량 삭제가
조용히 통과하고 있었다 (PostgreSQL 에서는 FK 위반).

```bash
# 일회용 컨테이너
docker run -d --name mediscan-pg-test -e POSTGRES_PASSWORD=testpw   -e POSTGRES_DB=mediscan_test -p 55432:5432 postgres:16-alpine

cd backend
python -m scripts.verify_postgres   --url postgresql+psycopg2://postgres:testpw@localhost:55432/mediscan_test --with-tests

docker rm -f mediscan-pg-test
```

확인 항목: 연결 / `upgrade head` / **모델↔스키마 드리프트 없음** / `downgrade base` 후 재 upgrade /
전체 pytest. `--with-tests` 없이 돌리면 스키마만 빠르게 본다.

테스트만 PostgreSQL 로 돌리려면:
```bash
MEDISCAN_TEST_DATABASE_URL=postgresql+psycopg2://... pytest
```

> ⚠️ 이 스크립트는 **downgrade 로 스키마를 통째로 내렸다 올린다.** 운영 DB 를 가리키지 말 것.

**이식성 함정 (둘 다 실제로 겪었다)**

1. **대량 삭제는 ORM cascade 를 타지 않는다.** `db.query(X).delete()` 는 SQLite 에서 통과하고
   PostgreSQL 에서 FK 위반이 난다. 사용자 삭제는 반드시 `db.delete(user)`
   (= `app/account.py` 가 쓰는 경로)를 쓴다.
2. **테스트에서 없는 외래키로 행을 만들지 않는다.** SQLite 는 외래키를 기본적으로 강제하지
   않아 `user_id="u_ghost"` 같은 고아 행이 조용히 만들어진다. PostgreSQL 에서는 실패한다.
   픽스처로 실제 사용자를 만들어 붙인다.

> **테이블을 추가하면 PostgreSQL 검증을 다시 돌릴 것.** 두 번 다 이 검증이 잡아냈다.

### 연결 설정

`DATABASE_URL` 환경변수 하나로 로컬과 배포를 모두 커버한다 (`app/db.py`).

| 상황 | 설정 |
|---|---|
| 로컬 개발 (기본) | 미설정 → `backend/mediscan.db` SQLite 파일 |
| PostgreSQL / AWS RDS | `DATABASE_URL=postgresql+psycopg2://user:pw@host:5432/mediscan` |

모델은 두 DB 모두에서 동작하는 타입만 쓰므로, 옮길 때 URL 만 바꾸면 된다.

### 마이그레이션 (Alembic)

**스키마의 기준은 마이그레이션이다.** `create_all` 은 기동 경로에서 쓰지 않는다 —
모델을 바꾸면 반드시 마이그레이션을 만든다.

```
cd backend
alembic revision --autogenerate -m "무엇을 바꿨는지"   # 모델 변경 후
alembic upgrade head                                  # 적용
alembic downgrade -1                                  # 한 단계 되돌리기
alembic current / alembic history                     # 상태 확인
```

앱을 띄우면 `init_db()` 가 `alembic upgrade head` 를 자동 실행한다(`app/db.py`).
접속 정보는 `alembic/env.py` 가 `app/db.py` 의 `DATABASE_URL` 을 그대로 읽으므로
`alembic.ini` 에 URL 을 적지 않는다 — 앱과 마이그레이션이 항상 같은 DB 를 본다.

> Alembic 도입 이전(`create_all`)에 만든 DB 는 `alembic_version` 테이블이 없어 그대로는 올라가지 않는다.
> 버려도 되면 DB 파일을 지우고, 데이터를 유지해야 하면 `alembic stamp head` 로 표시한 뒤 진행한다.
> (`app/db.py` 가 이 상황을 감지해 안내 메시지를 띄운다)

### 테이블 (`app/models.py` — api-spec.md 3절과 1:1)

| 테이블 | 용도 |
|---|---|
| `users` | 이메일 가입(email+password_hash) / SNS 가입(provider+provider_subject) |
| `consents` | 동의 이력. **갱신하지 않고 append** — "누가 언제 몇 번 버전에 동의했는지" 증빙이 남아야 함 |
| `cases` | 케이스(= volume 1개) 콘텐츠 + **검수 완료 기준 마스크**/기준 영역/해설. 대표 slice 를 가리킨다 |
| `case_slices` | volume 안의 slice. `slice_index` 는 **원본 volume 인덱스 그대로** (2.5D 확장 시 인접 slice 조회 키) |
| `submissions` | 제출 1건 = 채점 결과 1건. 같은 케이스를 여러 번 풀면 여러 행 |

복습노트는 별도 테이블이 없다. `app/repository.py` 에서 **케이스별 최신 제출**이 `match` 가
아닌 것을 뽑는다 (재도전해서 맞히면 목록에서 빠진다).

## 인증

- 비밀번호: `hashlib.scrypt` (salt 포함) — `app/security.py`
- 토큰: HMAC-SHA256 서명 + 만료(기본 7일). JWT 와 같은 구조의 축소판
- `/api/cases/*`, `/api/wrong-notes/*`, `/api/analyze` 는 토큰 없으면 **401** (`app/deps.py`)
- `/api/analyze` 는 `agree_sensitive_data` 동의를 서버에서 실제로 확인 → 없으면 403

배포 전 필수: `MEDISCAN_SECRET_KEY` 환경변수 설정 (미설정 시 개발용 고정 키 + 경고).
`MEDISCAN_TOKEN_TTL` 로 토큰 수명(초)을 조절할 수 있다.

인증 쪽은 표준 라이브러리만 쓴다(추가 설치 불필요). 실서비스에서 bcrypt/JWT 로 바꾸려면
`security.py` 의 함수 4개만 갈아끼우면 된다.

## 채점 (app/grading.py) — API 계약 v0.4

**채점 기준은 전문가 검수 reference mask 하나뿐이다.** AI 예측 마스크는 채점에 일절 관여하지 않고,
모델이 준비된 경우에만 응답의 `ai_prediction` 에 참고 정보로 실린다.
(모델은 완벽하지 않으므로 — 뇌 MRI 기준 10명 중 8명 검출 — 학습자를 모델 예측에 맞춰 채점하지 않는다.)

- 지표: Dice / IoU / 위치 점수(중심 거리, 기준 마스크 크기로 정규화) — `app/masks.py`
- 판정: Dice ≥ 0.60 `match`, ≥ 0.15 `partial_match`, 그 외 `mismatch`
- **제출 마스크는 보정하지 않는다.** v0.2 는 내부 구멍을 자동으로 메웠으나(`fill_holes`),
  윤곽선만 그린 ROI 를 과도하게 후하게 채점할 수 있어 제거했다.
  대신 화면에서 "이상으로 판단되는 부위를 **칠해주세요**"로 안내하고 브러시 기본 굵기를 24로 올렸다.
  `masks.fill_holes` 함수는 향후 `contour` 도구용으로 남아 있다(현재 미사용).

**기준 마스크가 없으면 채점하지 않는다.**

| 상황 | 응답 |
|---|---|
| 기준 마스크 있음 | 200, `evaluation.method = "reference_mask"` |
| 기준 마스크 없음 | **422 `CASE_NOT_GRADABLE`** — 제출 이력도 만들지 않는다 |
| ROI 누락·디코딩 실패·빈 마스크 | 400 `INVALID_ROI` |

프론트는 `GET /api/cases/{id}` 의 `gradable: false` 를 보고 제출 버튼을 미리 막는다.

좌표 근사 채점(`coordinate_approx`)은 **개발 전용**이며 `MEDISCAN_ENV=production` 에서는
켜져 있기만 해도 기동이 실패한다 (검수되지 않은 기준으로 학습자를 평가하지 않기 위해서다).
`MEDISCAN_ALLOW_APPROX_GRADING=1` 일 때만
동작하고, 응답에 `is_provisional: true` 가 붙어 화면 상단에 경고가 뜬다. 일반 UI 흐름에서는 쓰지 않는다.

### 케이스 등록 운영 규칙 (MVP)

채점 기준이 곧 reference mask 이므로 **팀에서 검수를 마친 마스크만 케이스로 등록한다.**
모델이 자동 생성한 마스크를 기준으로 올리면 학습자가 잘못된 기준으로 평가받는다.
시드 시 마스크 파일이 없으면 경고 로그가 남고 해당 케이스는 `gradable: false` 로 내려간다 (`app/seed.py`).

## 실제 케이스 등록 (scripts/import_cases.py)

의료영상 원본과 reference mask 는 **git 에 커밋하지 않는다.** 리포 밖(또는 gitignore 된
`backend/data/`)에 둔 실제 파일을 manifest 로 가리키면, 스크립트가 검증 후 서비스가 서빙하는
위치(`app/static/cases/<case_id>/`, gitignore 대상)로 복사하고 DB 에 등록한다.

```
cd backend
python -m scripts.import_cases data/<manifest>.json --dry-run   # 검증만
python -m scripts.import_cases data/<manifest>.json             # 등록
python -m scripts.import_cases data/<manifest>.json --replace   # 덮어쓰기
```

manifest 형식은 `data/manifest.example.json` 참고. 케이스 하나에 영상, reference mask,
병명, 기준 영역, 주요 소견, 의학용어, 참고자료를 함께 적는다.
뇌 MRI 처럼 volume 로 들어오는 케이스는 `volume_id` / `representative_slice` / `slices[]` 를 더 준다.

**해설 3층 구조 (API 계약 v0.4)**

검증되지 않은 의학 내용을 채워 넣지 않는다. 우리는 의료인이 아니므로, 해설을 **출처별로 나눈다.**

| 블록 | `source` | 어디서 오나 |
|---|---|---|
| `case_facts` | `dataset_verified` | manifest. **GT/DICOM 에서 계산된 값만** (사람이 타이핑하는 문장 없음) |
| `disease_info` | `literature_based` | `app/content/diseases/<disease_code>.json`. **manifest 로는 못 넣는다** |
| `case_findings` | `expert_reviewed` | manifest. `findings` / `reviewer` / `reviewed_at` 이 모두 있어야 등록된다 |

- `content_levels` 는 저장하지 않고 블록 존재 여부에서 계산한다 (세 값은 배타적이지 않다).
- `disease_info` 를 manifest 로 막는 이유: 등록자가 임의로 쓴 문장이 "문헌 기반"으로 표시되면 안 된다.
- `reviewer` / `reviewed_at` 은 **검토 출처 메타데이터를 필수화**하는 것이지, 필드가 있다고 검토를
  보증하는 것은 아니다.
- v0.3 의 평평한 키(`key_findings`, `review_status`, `medical_terms`, `reference`)가 남아 있으면
  **등록이 실패한다** — 조용히 무시되면 옛 해설이 사라진 줄 모른다.

현재 VS-SEG 6케이스는 `content_levels: ["dataset_verified", "literature_based"]` 로 서비스된다
— 데이터에서 계산한 사실과 질환 문헌 학습정보(`content/diseases/vestibular_schwannoma.json`)는 있고,
**케이스별 소견(`case_findings`)만 비어 있다**(전문가 검토 전이라 `null`).

### 질환 문헌 학습정보 (`app/content/diseases/`)

질환 단위 콘텐츠라 케이스마다 복사하지 않는다 — 파일 하나를 고치면 그 질환의 모든 케이스에
반영된다(DB 재등록 불필요). 텍스트뿐이라 **git 에 커밋한다**(의료영상과 달리 개인정보가 없고,
출처가 바뀌면 diff 로 확인된다). 파일이 없거나 내용이 비면 `disease_info` 는 `null` 이다.
`source` 와 안내 문구(`notice`)는 파일 값을 쓰지 않고 서버 상수에서 채운다. 작성 규칙은
`app/content/diseases/README.md` 참고.

로더는 매 요청마다 파일 mtime/크기를 확인해 바뀌었을 때만 다시 읽는다 — 파일을 추가·수정·삭제하면
**서버 재시작 없이** 반영된다.

| 상황 | 처리 |
|---|---|
| 필수 항목 누락 / 영상 파일 없음·손상 | **등록 실패** (해당 케이스만 건너뜀) |
| reference mask 없음 · 손상 · 영상과 크기 불일치 | 케이스는 등록되고 **`gradable: false`** (제출 차단) |
| 정상 | 등록 + 썸네일 자동 생성 |

**운영 규칙**: 채점 기준이 곧 reference mask 이므로 **팀에서 검수를 마친 마스크만** 등록한다.

### 전문가 해설 검토 자료

```
python -m scripts.build_review_packet     # data/vs_seg_review_packet/ 생성
```

케이스별로 병명·편측성·대표 slice·병변 범위·GT 면적과 **이미 만들어 둔 육안 검수 오버레이**를
모아 `expert_review.md`(읽고 채우는 문서) + `expert_review_form.csv`(표 양식)를 만든다.
**의학 소견은 한 글자도 생성하지 않는다** — 주요 소견/의학용어/참고자료/검토자/검토일/승인 여부는 빈칸이다.

검토가 끝나면 manifest 의 `explanation` 을 채우고 `review_status` 를 `expert_reviewed` 로 바꾼 뒤
`import_cases ... --replace` 로 다시 등록한다. **승인 없이 상태만 바꾸는 경로는 만들지 않았다.**

### 등록 후 점검 / 되돌리기

```
python -m scripts.verify_cases                       # 전체 sanity check
python -m scripts.remove_cases --case-ids VS-SEG-202 # 미리보기 (--yes 로 실제 삭제)
```

`verify_cases` 는 파일 존재·크기 일치·slice 연결을 보고, **기준 마스크를 그대로 제출해
Dice=1.0 이 나오는지**까지 확인한다 (채점 경로가 그 케이스에서 실제로 도는지 보는 점검이다).

## 뇌 MRI VS-SEG 실데이터 파이프라인 (scripts/)

DICOM 원본에서 서비스 케이스까지 **4단계로 나눠** 진행한다. 중간에 사람이 눈으로 확인하는
지점을 남기기 위해서다 (한 번에 등록하지 않는다).

```
1) export      DICOM -> npy (원본 volume + 전문가 GT)
   python -m scripts.export_vs_seg_npy --data-root <DICOM루트> --out data/vs_seg_export        --cases VS-SEG-202 ... [--verify-against <노트북 outputs>]
2) 육안 검수    npy -> 오버레이 시트 PNG (DB 등록 없음)
   python -m scripts.make_review_overlays --export-root data/vs_seg_export --out data/vs_seg_review
   # 사람이 보기 전에 기계가 셀 수 있는 것부터 (덩어리 수·정렬·ROI·편측성)
   python -m scripts.pre_review_check --export-root data/vs_seg_export --json data/vs_seg_review/pre_review.json
   # 판단 기준: docs/CASE_REVIEW_CHECKLIST.md — 사전점검이 깨끗해도 전부 눈으로 본다
3) 자산 생성    npy -> 표시용 PNG + 마스크 PNG + manifest
   python -m scripts.build_vs_seg_case_assets --export-root data/vs_seg_export        --out data/vs_seg_cases --margin 3
4) 등록         python -m scripts.import_cases data/vs_seg_cases/manifest.json
5) 모델 예측     (학습 venv 로) python -m scripts.run_model_predictions                      --export-root data/vs_seg_export --verify-against <노트북 outputs>
```

`export_vs_seg_npy.py` 는 학습 노트북(`02_run_pretrained_model.ipynb`)의 cell 3/4/5 를 그대로
옮긴 것이고 **새 전처리를 만들지 않는다.** `--verify-against` 로 노트북 산출물과 배열까지 대조한다.

지켜야 할 규칙 3가지:

- **ROI 자동 선택은 후보가 정확히 1개일 때만.** 종양 ROI 이름(`TV`/`AN`/`GTV`/`tumor`/
  `schwannoma` 등)에 맞는 것이 **0개여도, 2개 이상이어도** export 를 **중단**하고
  사람이 `--roi CASE=ROI이름` 으로 지정해야 진행된다.
  (211/212 는 ROI 가 `AN` 이라 예전 키워드에는 걸리지 않았고, 우연히 첫 번째였을 뿐이다.
  등록된 6케이스가 규칙 변경 후에도 같은 ROI 를 고르는지는 `tests/test_roi_selection.py` 가 고정한다.)
- **전문가 GT 를 수정하지 않는다.** 최소 면적 필터·구멍 메우기·스무딩 전부 없다.
  GT 가 1px 이라도 있는 slice 는 그대로 등록되고 `lesion_area_px` 도 그대로 보존한다.
- **표시용 정규화(volume 별 percentile 1~99% 클리핑 -> 8bit)를 모델 전처리와 공유하지 않는다.**
  모델 입력은 z-score 이고, 이 둘이 섞이면 조용히 틀린 추론이 나온다.
  육안 검수 시트와 서비스 PNG 는 **같은 함수**를 써서 "승인한 그림 = 올라간 그림"을 보장한다.

편측성(좌/우)은 추측하지 않고 DICOM `ImageOrientationPatient` 로 계산한다
(+x = 환자 왼쪽). FOV 중심과 머리 전경 중심 두 기준이 일치할 때만 값을 채우고,
어긋나면 비워 사람이 확인하게 한다.

## 업로드 검증 (app/uploads.py)

`/api/analyze` 전용. **서버 검증이 권위이고 클라이언트 검사는 UX 용이다** — 클라이언트가 보내는
MIME 타입은 신뢰하지 않고 실제 바이트를 열어 포맷을 판단한다.

base64 길이 → 실제 포맷(PNG/JPEG) → 손상 여부 → 이미지 크기(64~4096) → 픽셀 수(압축 폭탄) →
region 좌표 순으로 검사한다. 큰 문자열을 디코딩하기 전에 길이부터 보고, 픽셀을 풀기 전에
헤더에서 크기를 확인하는 순서가 중요하다.

**업로드 영상은 저장하지 않는다.** 메모리에서만 처리하고 EXIF 등 메타데이터를 제거한다
(의료영상 메타데이터에 환자 식별정보가 남아 있을 수 있다). DICOM 은 MVP 범위 밖이며,
지원 시 태그 비식별화가 별도로 필요하다 — api-spec.md 2-6 참고.

**분석 결과는 기본적으로 `status: "model_unavailable"` 이다.** 예전 고정 mock 은 소견과
후보질환 확률을 지어내 내려보냈는데, 사용자가 올린 영상을 실제로 분석한 것처럼 보이는
검증되지 않은 의학적 출력이라 제거했다. 뇌 MRI 모델은 volume 입력이라 업로드 1장으로는
분석할 수 없다.

**화면 5 는 이번 MVP 범위에서 실제 분석 기능 제외**로 확정됐다. 3D ceT1 volume 모델을
단일 이미지에 억지로 쓰지 않고, DICOM 시리즈 업로드도 이번 범위 밖이다.
단일 이미지용 2D 모델을 확보한 뒤 구현한다.

2D 입력 모델이 생기면 자동으로 연결된다 — `models/<부위>/inference.py` 에
`predict_image(image, region=None)` 을 두면 된다 (**PIL 객체를 그대로 받는다**, 파일 저장 없음).

`MEDISCAN_ANALYZE_DEMO` 는 **기본 OFF**이고 개발 확인용으로만 켠다. 켜면 `status: "demo"` +
`is_demo: true` 가 붙고 화면에도 "화면 확인용 예시 데이터" 배너가 떠 실제 분석과 분리된다.

## 부위별 모델 (app/inference.py)

`models/<폴더>/inference.py` 를 동적으로 import 하는 레지스트리다. 부위 코드 → 폴더 매핑만
백엔드가 알고, 나머지는 models/ 폴더 구성에 따른다 — 팀원이 새 부위를 추가할 때 백엔드
코드를 고칠 필요가 없다. 계약과 추가 방법은 `models/README.md` 참고.

torch 가 없거나 체크포인트가 없으면 해당 부위만 "모델 없음"으로 처리되고 서비스는 정상 동작한다.
현재 상태와 **사용 불가 사유**는 `GET /health` 의 `models` 항목에서 확인한다.

```json
"brain_mri": {
  "folder": "brain_mri_vs", "module_loaded": true, "available": false,
  "model_version": "vs-2.5d-attn-unet-v1",
  "unavailable_reason": "체크포인트 없음: vs_seg_v1.pth"
}
```

### 뇌 MRI 모델 — 연결 완료 (참고 정보 전용)

학습 노트북(`02_run_pretrained_model.ipynb` cell 6/7/8)의 전처리·모델 구조·추론 설정을
그대로 옮겼고, 산출물 대조로 재현을 확인한 뒤 `PREPROCESS_VERIFIED = True` 로 올렸다.

| 확인 항목 | 결과 |
|---|---|
| VS-SEG-202 예측 마스크 배열 | 노트북 산출물과 **완전히 일치** (`np.array_equal`) |
| 6케이스 Dice / 예측 voxel | 기존 분석 CSV 와 **전부 일치** |

**모델은 3D volume 입력이라 slice PNG 로는 부르지 않는다** (`INPUT_KIND = "volume"`).
케이스당 수 분 걸리는 sliding-window 추론이라 요청 시 돌리지도 않는다. 대신 학습 venv 에서
`scripts/run_model_predictions.py` 로 미리 계산해 sidecar 로 남기고, 백엔드는 그걸 읽기만 한다:

```
app/static/cases/<case_id>/prediction.json   model_version / dice / detected
app/static/cases/<case_id>/prediction.png    대표 slice 예측 마스크 (미검출이면 없음)
```

그래서 **백엔드 서비스에는 torch/monai 가 필요 없다.** `/health` 의 brain_mri 가
"추론 의존성 미설치"로 나오는 것이 정상이며, 실제 연결 여부는 `precomputed_predictions` 로 본다.

`PREPROCESS_VERIFIED` 를 False 로 내리면 즉시 추론이 막힌다 (안전장치 유지).
**예측은 채점에 일절 관여하지 않는다** — `ai_prediction` 참고 정보로만 나간다.

학습 리포 경로는 `MEDISCAN_VS_SEG_ROOT` 로 지정한다. 기본값(`~/Desktop/medical-ai/
vestibular-schwannoma`)은 **로컬 개발용**이며, **서비스 런타임은 학습 리포에 의존하지 않는다** —
배포된 백엔드는 sidecar 만 읽으므로 학습 리포가 없어도 정상 동작한다.

#### 예측 재계산 (MVP 는 수동)

모델 버전을 바꾸거나 volume 을 다시 export 했으면 아래 순서로 갱신한다:

```
1) (학습 venv) python -m scripts.run_model_predictions --export-root data/vs_seg_export        --verify-against <노트북 outputs>      # 기존 결과와 대조하며 재계산
2) python -m scripts.verify_cases              # stale 여부까지 재점검
```

sidecar 에는 stale 판별용 메타데이터가 들어 있다: `model_version` / `generated_at` /
`case_id` / `representative_slice` / `predicted_voxels` / `reference_voxels` /
`dice_vs_reference` / `representative_slice_dice` / `roi_size` / 가중치·입력 volume 의
sha256 지문 / `regenerate_with` 명령.

`verify_cases.py` 는 sidecar 의 `model_version` 이 현재 wrapper 와 다르거나, 예측 계산 시점의
GT voxel 수가 지금 등록된 마스크 총합과 다르면 **실패로 잡는다.**

#### VS-SEG-204 — AI 실패와 학습 채점 독립성 검증 케이스

| 항목 | 값 |
|---|---|
| 전문가 GT | 존재 (3,628 voxel, 대표 slice 37 / 702px) |
| 사용자 제출 (기준 마스크 그대로) | **Dice 1.0 / `match`** |
| AI 예측 | **Dice 0.0 / `detected: false` / `mask_url: null`** |

모델이 완전히 실패한 케이스인데도 학습자 채점은 전문가 GT 기준으로 정상 동작한다.
이것이 "AI 예측은 채점에 관여하지 않는다"는 설계의 실측 증거이며,
`tests/test_ai_prediction.py::test_ai_failure_case_shape_vs_seg_204` 가 같은 조건을 고정한다.
학습 콘텐츠로서도 "모델도 놓칠 수 있다"를 보여주는 케이스라 화면 3 에 그대로 노출한다.

## 케이스 영상 / 마스크 (app/static_files.py)

채점이 기준 마스크 파일을 **읽어야** 하므로 케이스 자산은 백엔드가 소유한다.

```
backend/app/static/images/    (레거시) mock 케이스 영상 · 썸네일
backend/app/static/results/   (레거시) mock 기준 마스크
backend/app/static/cases/<case_id>/thumb.png          목록 썸네일
backend/app/static/cases/<case_id>/slices/slice_NNN.png  표시용 slice (NNN = 원본 인덱스)
backend/app/static/cases/<case_id>/slices/mask_NNN.png   전문가 GT 마스크
```

실제 케이스는 `cases/` 아래에 있고 통째로 gitignore 대상이다.

DB 에는 `/static/images/202_t1.png` 처럼 루트 상대 경로만 저장하고, 응답을 만들 때
`MEDISCAN_PUBLIC_BASE` 를 붙여 절대 URL 로 내려준다. **이 값을 비워 두면 요청이 들어온 주소를
그대로 쓴다** — 백엔드를 8000 이든 8010 이든 어디에 띄워도 영상 URL 이 따라간다.
(예전에는 8000 으로 고정돼 있어 포트를 바꾸면 영상만 조용히 깨졌다.) 배포 시에만 도메인을 넣는다.
배포 도메인이 바뀌어도 DB 는 그대로다.

프론트가 다른 도메인(5173)에서 이 마스크를 canvas 로 읽어 겹침 색상을 계산하므로
CORS 허용 헤더가 필요하다 — `main.py` 의 CORSMiddleware 가 처리한다.

## 폴더

```
app/
  main.py        앱 진입점, 라우터 등록, 시작 시 init_db()
  explanations.py 해설 3층 조립 (case_facts / disease_info / case_findings + content_levels)
  disease_content.py 질환 문헌 콘텐츠 로더 (app/content/diseases/<질환>.json)
  db.py          engine/세션/DATABASE_URL
  models.py      SQLAlchemy 모델
  schemas.py     pydantic 요청 모델 (api-spec.md 와 1:1)
  security.py    비밀번호 해싱 + 토큰
  deps.py        current_user 의존성 (401 처리)
  repository.py  제출 이력 파생 조회 (has_matched / needs_review)
  grading.py     ROI 채점 (기준 마스크 전용. AI 예측은 참고 정보로만)
  masks.py       마스크 디코딩 + Dice/IoU/위치점수 (fill_holes 는 현재 미사용)
  inference.py   부위별 모델 레지스트리 (models/<부위>/inference.py 동적 로드)
  static_files.py 케이스 영상·마스크 경로/URL 처리
  model_predictions.py 미리 계산된 모델 예측 sidecar 로더 (ai_prediction)
  uploads.py     사용자 업로드 영상 검증 + 메타데이터 제거
alembic/         마이그레이션 (env.py 는 app/db.py 의 DATABASE_URL 사용)
scripts/
  export_vs_seg_npy.py         VS-SEG DICOM -> npy (노트북 로직 그대로 + ROI 안전장치)
  make_review_overlays.py      등록 전 육안 검수 오버레이 시트 (DB 등록 없음)
  pre_review_check.py          육안 검수 **전** 기계 점검 — 사람 검수를 대신하지 않고 볼 순서를 정한다
  review_package.py            검수 결과 패키지 (summary json/csv + 다음 단계 manifest 후보). 등록·활성화는 하지 않는다
  preflight_candidates.py      기술 통과 후보 사전 검증 (무결성·중복·자산·sidecar). 의료 판단 없음
  sidecar_manage.py            AI 예측 sidecar 운영 (status / plan / validate / promote).
                               GPU 없이 돌아간다. 검증 실패분은 승격하지 않는다
  build_vs_seg_case_assets.py  npy -> 표시용 PNG + 마스크 PNG + manifest
  import_cases.py              실제 케이스 등록 CLI (단일 영상 / volume 둘 다)
  verify_cases.py              등록 후 sanity check (Dice=1.0 자가점검 포함)
  run_model_predictions.py     실제 모델 추론을 미리 계산해 sidecar 저장 (학습 venv 필요)
  build_review_packet.py       전문가 해설 검토용 문서/양식 생성 (의학 내용 자동 작성 없음)
  remove_cases.py              케이스 + 제출 이력 + slice 삭제 (기본 미리보기)
data/
  manifest.example.json  케이스 manifest 예시 (실제 데이터는 gitignore)
  static/        케이스 영상·기준 마스크 실제 파일
  seed.py        mock_data 의 케이스를 DB로 시드
  routers/       엔드포인트별 라우터
  mock_data/     케이스 원본 JSON (시드 소스) + 동의 문구/버전
```
