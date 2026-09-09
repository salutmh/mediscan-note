# CLAUDE HANDOFF — 세션 인수인계

> **새 세션은 이 파일을 가장 먼저 읽는다.** 그다음 `docs/RELEASE_READINESS.md`, `git status`, `git diff`.
> 이미 완료·테스트된 작업은 반복하지 않는다. 아래 **NEXT STEP** 부터 이어간다.

---

## 0. 현재 상태 한눈에

| 항목 | 값 |
|---|---|
| 최종 갱신 | 2026-09-09 |
| 현재 커밋 | `3c9ea47` |
| 현재 브랜치 | `main` |
| 원격 | `https://github.com/salutmh/mediscan-note.git` (Public) |
| 현재 모드 | **지속 자율 개발 루프** (Phase 1~8 은 최초 백로그였고 전부 완료) |
| STATUS | `IN_PROGRESS` — 사이클마다 제품 재평가 → 최고가치 작업 선정 |
| 마지막 전체 검증 | 백엔드 **806 passed** (SQLite·PostgreSQL 양쪽) / 프론트 **74 passed** / E2E 7종 / 접근성·좁은화면 점검 0건 / `verify_cases` 6케이스 |

> **push 는 매번 사용자 승인이 필요하다.**
> force push / rebase / reset --hard / history rewrite 는 하지 않는다.

---

## 1. 전체 목표

발표 전까지 **Closed Beta로 실제 사용자에게 보여줄 수 있는 제품 완성도**를 만든다.
단순 데모가 아니라 (a) 보안 최소선, (b) 학습 피드백 품질, (c) 콘텐츠 운영 기반을 갖춘다.

**절대 어기지 않는 설계 원칙**
1. AI prediction을 정답으로 쓰지 않는다. 채점 기준은 전문가 GT뿐이다.
2. AI가 틀려도 사용자 채점은 정상 동작해야 한다 (VS-SEG-204 회귀 테스트로 고정).
3. 모델이 없으면 가짜 결과를 만들지 않고 `model_unavailable`을 반환한다.
4. 전문가 GT를 후처리해서 정답처럼 고치지 않는다.
5. 문헌 일반론 / case-specific finding / AI 설명을 섞지 않는다.
6. **출처 없는 의료 내용을 Claude가 생성하지 않는다.** 비어 있는 편이 낫다.
7. geometry로 알 수 있는 것만 자동 피드백한다 (내이도 침범·조영증강 등은 절대 추론 금지).

---

## 2. Phase 진행 상황

| Phase | 내용 | STATUS |
|---|---|---|
| 1 | repository 전체 점검 → `docs/RELEASE_READINESS.md` | **DONE** |
| 2 | Production Security Hardening (SECRET_KEY/CORS/rate limit/탈퇴/로깅) | **DONE** |
| 3 | 학습 피드백 엔진 (spatial feedback + threshold config) | **DONE** |
| 4 | `case_findings` 운영 구조 | **DONE** (구조만 — 내용은 전문가 대기) |
| 5 | 최소 Admin CMS | **DONE** |
| 6 | 콘텐츠 확장 준비 (케이스 후보 분석 도구) | **DONE** |
| 7 | 모델 평가 개선 | **DONE** |
| 8 | 사용자 테스트 이벤트 로그 | **DONE** |

---

## 3. 완료된 작업

### Phase 1 — repository 전체 점검 (DONE)
- 코드를 직접 읽고 구현 현황을 Critical/High/Medium/Low로 분류 → `docs/RELEASE_READINESS.md` 생성.
- **과거 리뷰 문서를 근거로 쓰지 않고 전부 코드에서 재확인함.**
- 이미 잘 구현되어 있어 **손대면 안 되는 것**: 채점 파이프라인(`grading.py`), AI 분리 구조,
  해설 3층(`explanations.py`), 업로드 검증(`uploads.py`), Alembic 마이그레이션, 241개 테스트.

### Phase 2 — Production Security Hardening (DONE)

| 항목 | 구현 | 파일 |
|---|---|---|
| C1 SECRET_KEY | `MEDISCAN_ENV=production` 이면 미설정·dev값·32자 미만 시 **기동 실패**(ConfigError). development 는 기존대로 경고 후 fallback | `app/config.py`(신규), `app/security.py` |
| C2 CORS | production 은 `MEDISCAN_CORS_ORIGINS` 필수 + 와일드카드 금지 + 메서드/헤더 축소. development 는 localhost 아무 포트 regex | `app/cors.py`(신규), `app/main.py` |
| C3 rate limit | 표준 라이브러리 슬라이딩 윈도 미들웨어. login 10/분, signup 10/시간, social-login 20/분, 탈퇴 5/시간. **학습 흐름(제출·조회)에는 걸지 않음**. `METHOD 경로` 로 키를 나눠 `GET /me` 가 `DELETE /me` 한도에 영향받지 않음 | `app/rate_limit.py`(신규) |
| C4 회원 탈퇴 | `DELETE /api/auth/me`. 이메일 계정은 비밀번호 재확인(403), SNS 계정은 토큰만. 계정·동의·제출 이력 하드 삭제, 삭제 건수 반환 | `app/account.py`(신규), `app/routers/auth.py` |
| 로깅 점검 | `logger.*` 전수 확인 — password/token/request body 로깅 **없음**. 추가 조치 불필요 | — |

**설계 메모 (다음 세션이 알아야 할 것)**
- 미들웨어는 **나중에 등록한 것이 바깥쪽**이다. CORS 를 마지막에 등록해야 429 응답에도
  CORS 헤더가 붙는다 (`app/main.py` 주석 참고). 순서를 바꾸면 브라우저가 429 본문을 못 읽는다.
- rate limit 은 **프로세스 메모리**에만 있다. 워커를 여러 개 띄우면 워커별로 센다 →
  확장 시 Redis 등 공유 저장소로 옮겨야 한다 (`app/rate_limit.py` docstring).
- 테스트 격리를 위해 `conftest.py` 에 `_reset_rate_limit` autouse fixture 를 추가했다.
  이게 없으면 앞 테스트의 로그인 시도가 뒤 테스트 한도를 깎아 **순서 의존 실패**가 난다.
- 탈퇴 삭제 범위는 `app/account.py::delete_account` **한 함수**에 모여 있다 (BLOCKER-3 대비).

### Phase 3 — 학습 피드백 엔진 (DONE)

| 항목 | 구현 | 파일 |
|---|---|---|
| H1 spatial feedback | 겹침·면적·중심에서 gt_coverage(recall) / user_precision / area_ratio / over·under_segmentation / centroid distance(정규화 포함) 계산 → 교육 문구 생성 | `app/feedback.py`(신규) |
| H6 임계값 config | `MATCH_DICE`/`PARTIAL_DICE` 를 `scoring_config` 로 분리. 응답 `evaluation.thresholds` 에 값 + `validation_status` 노출 | `app/scoring_config.py`(신규) |
| 계약 | `EvaluationResult.spatial_feedback` 추가(계약 v0.5), api-spec.md 2-3 동시 갱신 | `app/schemas.py`, `docs/api-spec.md` |
| 화면 | 화면 3에 "표시한 영역 분석" 블록. 서버 문구를 그대로 쓰고 프론트는 색만 나눈다 | `frontend/src/components/ResultCompare.vue` |

**설계 메모 (다음 세션이 알아야 할 것)**
- **`spatial_feedback` 은 채점에 관여하지 않는다.** grade 는 여전히 Dice 임계값만 본다.
  테스트 `test_feedback_does_not_change_grade` 가 이를 고정한다.
- **의료 어휘 금지가 테스트로 강제된다** (`test_messages_never_contain_medical_claims`).
  문구를 추가할 때 "내이도/조영/종괴/진단..." 류 단어가 들어가면 실패한다. 이건 의도된 가드다.
- 중심 거리는 **기준 마스크 등가반지름으로 정규화**한다. 작은 병변의 10px 와 큰 병변의 10px 는
  학습적으로 다른 이야기이기 때문이다.
- 좌표 근사 채점(개발 전용)에는 마스크가 없어 `spatial_feedback: null` 이다. 지어내지 않는다.
- 프론트는 서버 문구를 **그대로** 출력한다. 화면에서 의료적 해석을 덧붙이지 않기 위함이다.

### Phase 4 — case_findings 운영 구조 (DONE, 내용은 전문가 대기)

| 항목 | 구현 | 파일 |
|---|---|---|
| 학습 필드 확장 | `lesion_location` / `reference_region_note` / `learning_points[]` / `common_mistakes[]` / `content_version` 추가 (전부 선택, 전부 사람이 작성) | `app/schemas.py` |
| 검토 상태 | `cases.findings_status` 컬럼 (`needs_expert_review`/`in_review`/`approved`) + 응답 `explanation.case_findings_status` | `app/models.py`, `app/explanations.py` |
| 마이그레이션 | `e81bbce560b5` — **추가 전용**. server_default 로 기존 행은 `needs_expert_review` | `alembic/versions/` |
| 등록 경로 | `import_cases.py` 가 새 필드를 받되 없으면 빈 채로 둔다. 소견이 실제로 있을 때만 `approved` | `scripts/import_cases.py` |
| 화면 | 소견이 없을 때 **왜 없는지**를 상태별 문구로 말한다 | `frontend/src/components/ExplanationPanel.vue` |
| 규칙 문서 | `docs/CONTENT_GUIDELINES.md` 신규 — GT 원칙 / 등록 규칙 / 작성 규칙 / **AI 생성 가능·불가 목록** | |

**설계 메모 (다음 세션이 알아야 할 것)**
- **상태보다 실제 내용이 우선한다.** `findings_status=approved` 인데 소견이 비어 있으면
  응답은 `needs_expert_review` 로 나간다 (`explanations.findings_status`).
  상태 필드만 올려서 "검토된 것처럼" 보이게 하는 경로를 만들지 않기 위함이다.
- **의료 내용은 채우지 않았다.** 6케이스 전부 `needs_expert_review` 다. 이건 미완성이 아니라
  의도된 상태다 (BLOCKER-2).
- CLI 스크립트가 마이그레이션을 보장하지 않아 컬럼 추가 시 `no such column` 으로 죽었다.
  `verify_cases.py` / `remove_cases.py` 에 `run_migrations()` 를 추가해 `import_cases` 와 맞췄다.
  **앞으로 DB 를 읽는 스크립트를 만들면 같은 처리를 넣을 것.**

### Phase 5 — 최소 Admin CMS (DONE)

| 항목 | 구현 | 파일 |
|---|---|---|
| 권한 | `users.is_admin` + `current_admin` 의존성(403 `ADMIN_REQUIRED`). **토큰에 담지 않고 DB 만 본다** — 담으면 권한 회수 후에도 만료까지 관리자로 남는다 | `app/deps.py` |
| 최초 지정 | CLI 전용 `python -m scripts.grant_admin --email <이메일>`. 웹 승격 경로 없음 | `scripts/grant_admin.py` |
| 운영 API | 목록/상세/PATCH(활성·난이도·검토상태) / PUT·DELETE 소견 | `app/routers/admin.py` |
| 케이스 숨김 | `cases.is_active`. 학습자 목록·상세·제출에서 404. **삭제가 아니라 숨김** — 제출 이력은 남는다 | `app/routers/cases.py` |
| 난이도 | `cases.difficulty` (easy/medium/hard/null). **자동 판정하지 않는다** | `app/models.py` |
| 화면 | 표 하나짜리 최소 운영 화면 `/admin/cases` | `frontend/src/views/AdminCasesView.vue` |

**설계 메모 (다음 세션이 알아야 할 것)**
- **admin API 로 GT(기준 마스크)·case_facts·영상을 바꿀 수 없다.** 의도적이다.
  `test_admin_cannot_change_reference_mask` / `test_admin_cannot_overwrite_case_facts_via_findings` 가 고정한다.
- **소견 없이 `approved` 로 올릴 수 없다** (422 `FINDINGS_REQUIRED`). 상태만 올려
  "검토된 것처럼" 보이게 하는 경로를 막는다.
- 권한 격리 테스트는 `ADMIN_ENDPOINTS` 목록을 parametrize 한다.
  **admin 엔드포인트를 추가하면 이 목록에도 추가할 것** — 그래야 비로그인/일반 사용자 차단이 자동 검증된다.
- 프론트 라우트를 숨기지 않았다. 프론트 숨김은 권한이 아니고, 서버가 403 을 주면
  화면이 "운영자 권한이 필요합니다"를 그대로 보여주는 편이 덜 혼란스럽다.

### 자율 루프 #17 — 최근 추가 기능의 프론트 테스트 (DONE)

가장 최근에 만든 화면 로직(비밀번호 변경·탈퇴·분석 가용성)에 단위 테스트가 없었다.
**새로 만든 것일수록 테스트가 없다** — 의식적으로 채웠다.

- `AccountView` 9개: 확인 불일치·짧은 비밀번호는 **서버까지 가지 않는다**, 성공 시 토큰 교체,
  탈퇴는 무엇이 지워지는지 먼저 보여주고 **한 번에 삭제되지 않는다**
- `AnalyzeView` 6개: 준비 상태를 하드코딩하지 않는다, 불가능하면 업로드 전에 이유를 알리고
  요청 버튼을 막는다, **확인 실패 시에는 잠그지 않는다**

프론트 25 → **40개**.

---

### 자율 루프 #16 — 화면 5 헛수고 제거 + E2E 회귀 3건 (DONE)

**문제**: 사용자가 영상을 올리고 ROI 를 칠하고 요청까지 **다 한 뒤에야** "준비 중"을 만났다.
게다가 "준비 중"이라는 문구가 화면에 **하드코딩**돼 있어, 모델이 준비되면 반대로 거짓말을 하게 된다.

- `GET /api/analyze/availability` 신설 — 화면이 **업로드 전에** 물어본다
- 안내 문구를 서버 상태 기반으로 바꾸고, 불가능하면 요청 버튼을 비활성화 + 이유 표시
- 조회 실패 시에는 **막지 않는다** (확인을 못 했다고 기능을 잠그면 더 나쁘다)

**E2E 를 돌리다 찾은 회귀 3건 (전부 내가 만든 것)**

| # | 문제 | 원인 |
|---|---|---|
| 1 | `user-flow.mjs` 가입 실패 | 비밀번호를 8자로 올릴 때 `screenshot-all.mjs` 만 고치고 `user-flow.mjs` 의 `pw1234`(6자)를 놓쳤다 |
| 2 | 실패가 **3단계 뒤에** 엉뚱한 메시지로 터짐 | 가입 성공을 확인하지 않고 진행 → "reference_mask_url 을 얻지 못했습니다". **실패는 일어난 자리에서 알리도록** 가드 추가 |
| 3 | 내가 쓴 스크립트의 토큰 키가 틀림 | `mediscan.token` → 실제로는 `mediscan.access_token` |

**추가로 알게 된 것**: E2E 를 반복 실행하면 **가입 요청 수 제한(시간당 10회)**에 걸린다.
`tools/browser-verify/README.md` 에 `MEDISCAN_RATE_LIMIT=0` 으로 띄우라고 적었다.

**교훈**: 정책(비밀번호 길이 등)을 바꾸면 **그 정책을 쓰는 모든 곳**을 찾아야 한다.
백엔드 테스트는 통과했는데 E2E 스크립트가 조용히 깨져 있었다.

---

### 자율 루프 #15 — 콘텐츠 확장 준비 (후보 24건 선별, DONE)

**발견**: 콘텐츠 확장이 "데이터가 없어 막혀 있다"고 생각했는데, **원본 VS-SEG 데이터셋
242케이스가 로컬에 있었다** (`C:/Users/user/Downloads/vestibular_schwannoma_seg`).
학습 venv(`<학습리포>/.venv`)에 pydicom·rt_utils 가 있어 읽을 수 있다.

**한 일**: 242케이스를 전부 export 하면 케이스당 ~150MB 라 감당이 안 되므로,
**볼륨을 파일로 쓰지 않고** 편측성·병변 크기만 재는 스크리닝 도구를 만들었다.

| 결과 | 값 |
|---|---|
| 판독 가능 | **238 / 242** (4건은 T1 시리즈/RTSTRUCT 문제) |
| 편측 분포 | 좌 108 / 우 130 — **원본은 거의 균형** (편향은 우리 선택의 문제였다) |
| GT voxel | 330 ~ 44,230 (중앙 6,012) — **소형 병변이 충분히 있다** |
| 선별 후보 | **24건: 좌우 12:12, 크기 small/medium/large 8:8:8** |

**내가 만든 편향과 수정**: 첫 추천 로직은 "소형이 부족하니 작은 것부터"만 골랐더니
24건 전부가 최소 크기(330~1,777)로 나왔다. 데이터셋 중앙값이 6,012 인데 그 아래만 담은
셈이라 **반대 방향 편향**을 만든 것이다. 크기 3분위 계층을 추가해 고르게 뽑도록 고쳤다.

**여기서 멈춘 이유 (다음 세션이 이어갈 지점)**
파이프라인의 **육안 검수 단계는 사람이 GT 를 눈으로 확인하는 자리**라 건너뛸 수 없다
(CONTENT_GUIDELINES 3절). 스크리닝은 "어떤 케이스를 볼지" 고르는 데까지다.

다음 단계 (사람이 검수에 참여해야 한다):
```bash
cd backend
# 1) 선별된 24건 export (학습 venv, 케이스당 ~150MB → 약 3.6GB)
<학습리포>/.venv/Scripts/python -m scripts.export_vs_seg_npy     --data-root "C:/Users/user/Downloads/vestibular_schwannoma_seg"     --out data/vs_seg_export --cases VS-SEG-018 VS-SEG-182 ...
# 2) 검수 패킷 생성 → **사람이 오버레이를 보고 GT 확인**
python -m scripts.make_review_overlays ...
# 3) PNG 자산 생성 → 4) import_cases → 5) verify_cases
```
후보 목록은 `backend/data/vs_seg_screening.json` 의 `recommended` 에 있다
(gitignore 대상이라 커밋되지 않는다 — 다시 만들려면 `--from-json` 없이 재실행).

---

### 자율 루프 #14 — PostgreSQL 재검증 (DONE)

마이그레이션이 3개 늘어(세션 컷오프·재설정 코드 등) **다시 돌렸고, 또 잡혔다.**

- 마이그레이션 **8단계** upgrade/downgrade/재upgrade 전부 통과, 스키마 드리프트 없음
- **발견**: `test_expired_codes_are_purged` 가 존재하지 않는 `user_id="u_ghost"` 로
  행을 만들고 있었다. SQLite 는 외래키를 강제하지 않아 통과했지만 PostgreSQL 에서는 FK 위반.
  픽스처의 실제 사용자에 붙이도록 수정.
- 결과: **SQLite 471 / PostgreSQL 471 둘 다 통과**

**규칙으로 굳힌다: 테이블을 추가하면 PostgreSQL 검증을 반드시 다시 돌린다.**
두 번 돌렸고 두 번 다 이식성 문제를 잡았다 (`backend/README.md` 의 "이식성 함정" 참고).

```bash
docker run -d --name mediscan-pg-test -e POSTGRES_PASSWORD=testpw   -e POSTGRES_DB=mediscan_test -p 55432:5432 postgres:16-alpine
cd backend && python -m scripts.verify_postgres --url postgresql+psycopg2://postgres:testpw@localhost:55432/mediscan_test --with-tests
docker rm -f mediscan-pg-test
```

---

### 자율 루프 #13 — 비밀번호 재설정 (계정 복구의 마지막 공백, DONE)

**문제**: 비밀번호를 잊으면 **계정과 학습 이력을 영구히 잃었다.** 새로 가입하면 기록이 갈린다.
메일 발송 수단이 없어 표준적인 "비밀번호 찾기"를 만들 수 없는 상황이었다.

**해법**: 운영자가 일회용 코드를 발급하고 **본인 확인은 오프라인으로** 한다.
학내 Closed Beta 라 조교·담당자가 얼굴을 아는 상황을 전제한 것이고,
메일 발송 수단이 생기면 **발급 경로만** 바꾸면 된다 (검증·소비 로직은 그대로).

| 지킨 것 | 방법 |
|---|---|
| DB 가 새도 안전 | 코드는 **SHA-256 해시로만** 저장. 원문은 발급 응답에만 존재하고 로그에도 없다 |
| 일회용 | 성공 시 즉시 삭제. 새로 발급하면 기존 코드 무효 |
| 만료 | 24시간. 기동 시 만료분 정리 |
| 남의 코드 차단 | 코드가 맞아도 이메일이 다르면 거부 |
| 계정 열거 방지 | 실패 사유를 구분하지 않는다 — 전부 같은 400 메시지 |
| 계정 탈환 | 성공 시 **모든 기기 세션 무효화** |
| 토큰 미발급 | 재설정 후 토큰을 주지 않는다 — 코드만 가진 사람이 곧장 세션을 얻는 것보다 로그인을 한 번 더 거치는 편이 안전 |

**느린 KDF(scrypt)를 쓰지 않은 이유**: 비밀번호와 달리 **서버가 높은 엔트로피로 생성**하므로
무차별 대입이 통하지 않는다. SHA-256 으로 충분하다.

화면: 로그인 화면에 "비밀번호 재설정" 탭, 운영 화면 하단에 코드 발급 도구.

---

### 자율 루프 #12 — 로깅이 실제로 동작하지 않던 문제 (DONE)

**발견**: 실행 중인 서버 로그를 확인해보니 앱의 로그가 **한 줄도 없었다.**
`logger.info("계정 삭제: ...")` 같은 코드를 여러 곳에 써뒀는데, 로깅을 설정하지 않아
root 로거 기본 레벨(WARNING)에서 INFO 가 전부 버려지고 있었다.
**로그를 남기는 코드를 써놓고 실제로는 남기지 않는 상태**였고,
Closed Beta 에서 "제출이 안 된다"는 문의를 받아도 볼 것이 없었다.

| 항목 | 내용 |
|---|---|
| 설정 | `app/logging_config.py` — `MEDISCAN_LOG_LEVEL`(기본 INFO), `MEDISCAN_LOG_FORMAT`(text/json) |
| 적용 | 기동 시 가장 먼저 호출 (마이그레이션·시드 로그도 보이게) |
| 범위 | `app` 네임스페이스만 설정하고 `propagate=False` — uvicorn 로거와 겹쳐 중복 출력되지 않게 |
| 확인 | `/health` 의 `logging` 항목으로 현재 레벨·포맷을 볼 수 있다 |
| 민감정보 | 비밀번호·토큰·요청 본문·영상은 남기지 않는다. 식별은 내부 `user_id` 로만 |

**`test_no_secrets_are_logged_by_the_app`** 이 `app/` 의 모든 `logger.*` 호출을 훑어
`password`/`access_token`/`mask_png_base64` 등이 섞이면 실패시킨다 — 코드 리뷰의 자동화다.

**교훈**: "코드를 썼다"와 "실제로 동작한다"는 다르다. 로깅·메트릭처럼 **부작용이
눈에 안 보이는 코드**는 실행해서 출력을 눈으로 확인할 것.

---

### 자율 루프 #11 — 학습 지표를 운영자 화면에 (DONE)

**발견**: 난이도와 같은 유형. 학습 이벤트를 수집하면서도 **볼 방법이 CLI 뿐**이었다.
Closed Beta 운영자가 서버에 접속하지 않고는 "학습이 일어나고 있는지" 알 수 없다.

- 집계 로직을 `scripts/learning_report.py` → **`app/learning_stats.py`** 로 옮겼다.
  CLI 와 `GET /api/admin/learning-summary` 가 **같은 함수**를 쓴다 — 두 곳에서 따로
  계산하면 숫자가 갈라지고, 어느 쪽이 맞는지 아무도 모르게 된다.
- 운영 화면 상단에 지표 블록: 참여자 / 시작→제출 전환율 / 첫 시도 vs 재도전 Dice /
  **재도전 시 점수 변화**(학습 효과의 최소 신호) / 평균 소요시간
- `analytics_enabled` 를 함께 내려보낸다 — "데이터가 없다"와 "수집이 꺼져 있다"는 다른 이야기다
- **집계만 나간다.** `test_learning_summary_is_aggregate_only` 가 응답에 user_id·이메일이
  없음을 고정한다. 운영자가 개인의 학습 내용을 들여다보는 도구가 아니다
- 지표 조회가 실패해도 케이스 관리 화면은 그대로 뜬다

**admin 엔드포인트를 추가하면 `ADMIN_ENDPOINTS` 목록에도 넣을 것** — 그래야 비로그인/일반
사용자 차단이 자동으로 검증된다 (이번에도 넣었다).

---

### 자율 루프 #10 — 반쪽 기능 완결: 난이도 (DONE)

**발견**: Phase 5 에서 운영자용 `difficulty` 를 추가했는데 **학습자 경로에는 전혀 노출하지
않았다.** 운영자가 난이도를 설정해도 아무 일도 일어나지 않는 상태였다.
반쪽 기능은 없는 기능보다 나쁘다 — 운영자가 헛일을 하게 된다.

- `GET /api/cases`, `GET /api/cases/{id}` 응답에 `difficulty` 추가
- 케이스 카드에 난이도 뱃지. **미지정(null)이면 아무것도 표시하지 않는다** —
  자동 추정을 하지 않으므로 "표시가 없다 = 아직 판정 전"이 정확한 의미다
- 난이도가 **2종 이상** 지정돼 있을 때만 필터 탭이 생긴다 (부위 탭과 같은 원칙:
  눌러도 결과가 같은 죽은 컨트롤을 만들지 않는다)
- `test_difficulty_reaches_learners` 로 운영자→학습자 도달을 고정

**같은 유형을 앞으로도 확인할 것**: 관리 화면에서 설정할 수 있는 값이 학습자 경로까지
실제로 도달하는지. 설정만 되고 쓰이지 않는 필드가 또 생기기 쉽다.

---

### 자율 루프 #9 — 비밀번호 정책·변경 + 전체 세션 무효화 (DONE)

**발견**: 비밀번호 **최소 길이 정책이 아예 없었다** (한 글자로도 가입 가능).
그리고 비밀번호를 바꿀 방법이 없었다 — 유출이 의심돼도 사용자가 할 수 있는 게 없다.

| 작업 | 내용 |
|---|---|
| 정책 | 최소 8자. 복잡도 규칙(대문자·특수문자)은 두지 않는다 — 예측 가능한 패턴으로 우회하게 만들 뿐이다 |
| 변경 | `POST /api/auth/password`. **현재 비밀번호를 다시 받는다** (남의 기기 세션으로 계정을 빼앗기지 않게) |
| 전체 로그아웃 | `users.sessions_valid_from` — 이 시각 이전 `iat` 토큰을 전부 401 `SESSION_EXPIRED`. 개별 폐기(`revoked_tokens`)로는 **다른 기기 세션을 끊을 수 없다** |
| 화면 | `/account` 에 비밀번호 변경 폼. 변경 후 새 토큰으로 갈아끼워 이 기기는 끊기지 않는다 |

**구현 중 만든 버그와 수정 (같은 실수 주의)**
`iat` 는 `int(time.time())` 이라 **초 단위**인데 `sessions_valid_from` 에 마이크로초가 붙어
있었다. 그래서 비밀번호 변경 직후 새로 발급한 토큰(같은 초)이 컷오프보다 이르다고 판정돼
**즉시 거부**됐다. 컷오프를 `replace(microsecond=0)` 으로 내림해 해결.
대가로 "같은 초에 발급된 토큰"은 살아남는 1초 미만의 창이 있다 (문서에 명시).

**테스트 설계 메모**: 다른 기기 로그아웃을 통합 테스트로 확인하려 했더니 테스트가 1초 안에
끝나 그 창에 걸렸다. 타이밍 운에 기대는 대신 (a) 컷오프 기록 여부, (b) 컷오프를 명시적으로
앞당긴 뒤 enforcement 경로, (c) 경계 조건 단위 테스트로 나눴다.

---

### 자율 루프 #8 — 배포 준비: 데이터 손실 차단 + 런북 (DONE)

**발견**: `MEDISCAN_ENV=production` 이어도 `DATABASE_URL` 이 없으면 **조용히 컨테이너 안
로컬 SQLite 파일로 뜬다.** 겉보기에는 정상 동작하고 학습 이력도 쌓이는데, 재배포하면
통째로 사라진다. SECRET_KEY·CORS 는 막아뒀으면서 정작 **데이터가 사라지는 경로**는 열려 있었다.

| 작업 | 내용 |
|---|---|
| 데이터 손실 차단 | production 에서 `DATABASE_URL` 미설정 시 **기동 실패**. SQLite 자체를 금지하진 않는다 — 볼륨 경로를 명시적으로 정하게 할 뿐 (`sqlite:////data/...`) |
| 백업 | `scripts/backup_db.py` — SQLite 는 **온라인 백업 API**(단순 복사는 쓰기 중이면 깨진다), PostgreSQL 은 `pg_dump`. 보관 개수 관리 포함 |
| 런북 | `docs/DEPLOYMENT.md` — 배포 전 체크리스트 9항목, 알려진 운영 한계, 백업 절차, **사고 대응**(잘못된 GT/토큰 유출/권한 회수/소견 회수/DB 복구) |

**백업에 개인정보가 들어간다**는 점을 스크립트 출력과 문서 양쪽에 적었다.
원본 DB 와 같은 수준으로 보호해야 한다.

**작업 중 겪은 것**: 히어독으로 Python 코드를 쓰면서 `
` 이스케이프가 실제 개행으로
들어가 파일이 깨졌다. 여러 줄 문자열을 다룰 때는 Edit 도구를 쓰는 편이 안전하다.

---

### 자율 루프 #7 — 프론트 단위 테스트 도입 + 성능 실측 (DONE)

**왜 골랐나**: 이번 세션에 프론트를 6번 바꿨는데 단위 테스트가 **0개**였다.
E2E 가 핵심 흐름을 보지만 서버·Chrome 이 다 떠 있어야 하고, 경계 상황은 잡지 못한다.

vitest + @vue/test-utils, **22개**. `cd frontend && npm test`.
개수를 늘리는 것이 목적이 아니라 실제로 깨질 수 있는 것만 골랐다:
- `CaseListView` 8개 — 죽은 탭 회귀 방지, 상태 동시 표시, 조회 실패·빈 목록
- `ReadingView` 10개 — slice 전환/입력 잠금/**ROI 유지 설정**, 다음 행동(4가지 상황), slice 없는 케이스
- `stores/auth` 4개 — 로그아웃의 서버 폐기 요청, 실패 시 로컬 정리, `clearSession` 의 401 재진입 방지

**성능 실측** (추측하지 않고 측정): 케이스 목록 13.2ms(6케이스), 상세 12.9ms,
복습노트 4.0ms, `/auth/me` 3.1ms. 목록의 ~10ms 는 케이스마다 도는 파일 존재 확인(`is_gradable`)이다.
목표인 30케이스에서 ~50ms 로 **아직 문제가 아니다.** 100케이스를 넘기면 그때 캐시를 고려한다.

---

### 자율 루프 #6 — PostgreSQL 이식성 검증 (DONE)

**왜 골랐나**: "DATABASE_URL 하나로 SQLite↔PostgreSQL 전환"을 표방하면서 **한 번도
PostgreSQL 에서 돌려본 적이 없었다.** 배포 DB 에서 처음 문제를 만나는 것은 피해야 한다.

**결과**: docker `postgres:16-alpine` 로 전 항목 검증 통과.
- 마이그레이션 6단계 `upgrade head` / `downgrade base` / 재 upgrade
- 모델↔스키마 드리프트 없음 (autogenerate 빈 diff)
- **전체 414 테스트가 PostgreSQL 에서도 통과**

**발견한 이식성 함정 (중요)**
`db.query(X).delete()` 같은 **대량 삭제는 ORM cascade 를 타지 않는다.**
SQLite 는 외래키를 기본적으로 강제하지 않아 조용히 통과하지만 PostgreSQL 에서는 FK 위반이다.
`tests/test_auth.py` 1건이 여기 걸렸다 (앱의 실제 탈퇴 경로는 `db.delete(user)` 라 정상).
→ **사용자를 지울 때는 반드시 `db.delete(user)`**. `conftest._clean_user_data` 처럼
대량 삭제를 써야 한다면 자식 테이블부터 명시적으로 지운다.

**재현 방법**: `python -m scripts.verify_postgres --url ... --with-tests`
(`backend/README.md` "PostgreSQL 검증" 절 참고). 테스트만 바꿔 돌리려면
`MEDISCAN_TEST_DATABASE_URL=postgresql+psycopg2://... pytest`.

---

### 자율 루프 #5 — 화면 전수 점검으로 찾은 UI 문제 (DONE)

**방법**: `screenshot-all.mjs` 로 화면 0~7 을 전부 촬영해 눈으로 봤다.
스크린샷 리뷰가 세 번 연속 실제 문제를 찾아냈다 — **코드만 읽어서는 안 보이는 것들이다.**

| 문제 | 수정 |
|---|---|
| 화면 1 **죽은 필터 탭 4개** — 계약에 정의된 5개 부위를 다 깔아뒀는데 실제 케이스는 뇌 MRI 뿐. 나머지는 눌러도 빈 목록 | 실제로 케이스가 있는 부위만 탭으로 만든다. 부위가 하나뿐이면 탭 자체를 감춘다. 다른 부위가 등록되면 자동으로 생긴다 |
| 화면 7 **개발자 메모 노출** — "지금 API(GET /api/cases)는 has_matched/needs_review 두 상태만 주기 때문에… (api-spec.md 4절 화면 7)" 가 사용자 화면에 그대로 | 학습자 언어로 교체 ("학습완료는 한 번이라도 일치 판정을 받은 것…") |
| 화면 3 **CORS 안내 노출** — 오버레이 폴백 시 "백엔드에서 CORS 허용 헤더를 주면…" 을 사용자에게 안내 | "겹침 색을 계산하지 못해 반투명으로 겹쳐 표시합니다" 로 교체. 원인 추적은 개발자 콘솔 몫이다 |

**교훈 (다음 세션도 지킬 것)**: 개발 중 남긴 설명이 사용자 화면에 그대로 남기 쉽다.
UI 문자열에 `API` / 엔드포인트 경로 / `api-spec.md` / 내부 필드명이 들어가면 안 된다.

**남겨둔 관찰 (아직 수정 안 함)**
- 화면 5: 업로드 → ROI → 요청까지 다 하고 나서야 "준비 중"을 확인하게 된다.
  상단에 미리 안내가 있어 거짓말은 아니지만, 사용자 노력이 낭비되는 흐름이다.
- `Submission.explanation` 스냅샷은 저장만 되고 아무도 읽지 않는다 (죽은 데이터).
  제거하려면 파괴적 마이그레이션이라 보류.

---

### 자율 루프 #4 — 학습 루프 닫기 (다음 행동 제시, DONE)

**왜 골랐나**: 결과 화면 스크린샷을 실제로 보다가 발견했다. 케이스를 끝내면 버튼이
"다시 풀기" 하나뿐이라 **다음에 무엇을 할지가 없었다.** 매번 사용자가 직접 목록으로
돌아가야 했고, 학습 서비스에서 그 지점이 곧 세션이 끊기는 자리다.

| 상황 | 제시되는 다음 행동 |
|---|---|
| 판독훈련 완료 | **다음 케이스 →** (아직 학습완료가 아닌 것 중 첫 번째) / 다시 풀기 / 케이스 목록으로 |
| 재도전 완료 | **다음 복습 케이스 →** / 다시 풀기 / 복습노트로 |
| 남은 게 없음 | "모든 케이스를 학습완료했습니다" |

남은 개수도 함께 보여준다 ("아직 학습완료가 아닌 케이스 5개가 남아 있습니다").

**설계 메모**: 다음 대상 조회가 실패해도 결과 화면은 그대로 보인다 (버튼만 생략).
채점 결과를 보여주는 것이 우선이고, 다음 행동 제안 때문에 화면이 막히면 안 된다.

---

### 자율 루프 #3 — 화면 2 slice 탐색 (DONE)

**왜 골랐나**: 핵심 학습 화면에 **동작하지 않는 슬라이더**가 있었다. 숫자만 바뀌고 영상은
그대로였고, 도움말이 그 사실을 그대로 적어두고 있었다. Closed Beta 에서 거짓말하는 컨트롤은
없는 것보다 나쁘다. 게다가 대표 slice 한 장만 보여주면 "찾는" 훈련이 되지 않는다.

| 항목 | 내용 |
|---|---|
| API | `GET /api/cases/{id}` → `representative_slice` + `slices[{slice_index, image_url}]` |
| **정답 누출 방지** | slice 항목에 **마스크 정보를 넣지 않는다**. `has_mask` 하나만 있어도 병변 위치가 드러난다. `tests/test_case_slices_api.py` 가 필드 집합과 페이로드 문자열 양쪽으로 고정 |
| 화면 | 좌우 버튼 + 슬라이더. 대표 slice 에는 "대표" 태그 |
| **채점 안전** | ROI 입력·채점은 **대표 slice 에서만**. 다른 slice 는 캔버스 잠금 + "대표 slice로 이동" 버튼. 채점 계약을 건드리지 않았다 |

**설계 결정**: slice 별 채점은 하지 않았다. GT 는 slice 마다 있지만, 제출에 slice_index 를
추가하고 그 slice 의 마스크로 채점하는 것은 **채점 계약 변경**이라 별도 설계가 필요하다
(병변 없는 slice 에 그린 경우의 의미 등). 지금은 탐색만 열고 채점은 그대로 뒀다.

**브라우저 검증 완료**: `tools/browser-verify/slice-navigation.mjs` 신규.
실제 Chrome 에서 영상 전환·ROI 유지·입력 잠금·제출까지 13개 항목 전부 통과, 콘솔 에러 0.
`user-flow.mjs` 도 함께 돌려 기존 학습 흐름 회귀 없음을 확인했다 (재도전 Dice 0.9387).

**추가 UX 정리**: 제출 시 대표 slice 로 자동 복귀한다 — 다른 slice 를 보던 중에 제출하면
아래 결과 오버레이(대표 slice 기준)와 화면이 어긋나기 때문이다.

**작업 중 발견한 버그 (수정 완료)**
`RoiCanvas` 가 `imageUrl` 이 바뀌면 그린 ROI 를 지우고 있었다. slice 탐색을 붙이는 순간
**옆 slice 를 확인하고 돌아오면 칠하던 게 사라지는** 상태가 될 뻔했다.
배경은 `<img>` 로 그리므로 캔버스를 초기화할 이유가 없다 → `clearOnImageChange` prop 으로
분리(화면 5 업로드 교체는 true, 화면 2 slice 이동은 false).

---

### 자율 루프 #2 — 비활성 케이스 누수 버그 수정 (DONE)

**발견 경위**: 루프 #1 을 마치고 제품을 재평가하다가 `wrong_notes.py` 를 읽던 중 발견.
`submit` 은 `is_active` 를 확인하는데 `retry` 는 확인하지 않았다.

**왜 심각한가**: 운영자가 케이스를 내리는 이유는 대개 "이 케이스에 문제가 있다"이다
(기준 마스크 오류, 검수 미완). 재도전 경로가 열려 있으면 **문제 있는 기준으로 채점이 계속된다**
= 잘못된 학습 결과 (1순위).

| 수정 | 내용 |
|---|---|
| `retry_case` | `is_active` 확인 → 404, 제출 이력도 남기지 않는다 |
| `list_wrong_notes` | 숨겨졌거나 삭제된 케이스를 목록에서 제외 (누를 수 없는 항목은 404 밖에 안 된다) |
| 회귀 고정 | `tests/test_case_visibility.py` — **케이스를 다루는 학습자 경로를 추가하면 여기에도 추가할 것** |

**숨김은 삭제가 아니다**: 제출 이력은 그대로 두므로 케이스를 다시 노출하면 복습노트에도 돌아온다.

**부수 수정**: `conftest._clean_user_data` 가 `learning_events`/`revoked_tokens` 를 비우지 않았다.
`db.query(User).delete()` 는 대량 삭제라 **ORM cascade 를 타지 않는다** — 사용자 데이터
테이블을 추가하면 이 픽스처에도 반드시 추가해야 한다.

---

### 자율 루프 #1 — 서버측 토큰 폐기 (H4, DONE)

**왜 이걸 먼저 골랐나**: 이 서비스는 학내 실습실 같은 **공용 PC 배포**를 상정한다.
로그아웃해도 그 토큰이 최대 7일 유효한 것은 실제 위험(1순위: 보안)이라 판단했다.

| 항목 | 구현 |
|---|---|
| 토큰 식별 | `create_access_token` 이 토큰마다 `jti` 를 넣는다. 이게 있어야 **이 세션 하나만** 끊을 수 있다 |
| 폐기 목록 | `revoked_tokens` 테이블(DB 기반이라 워커 여러 개에서도 동작). 허용목록 대신 폐기목록 — 로그아웃한 것만 남기면 되어 훨씬 작다 |
| 검사 | `current_user` 가 매 요청 폐기 여부 확인 → 401 `TOKEN_REVOKED` |
| 엔드포인트 | `POST /api/auth/logout` (멱등). 탈퇴 시에도 함께 폐기 |
| 정리 | 앱 기동 시 만료된 폐기 기록 삭제 (`purge_expired`) |
| 프론트 | 로그아웃이 서버 폐기를 먼저 호출. 실패해도 로컬은 비우고 **"서버에 닿지 못했다"고 로그인 화면에 안내** |

**설계 결정 (되돌리기 전에 읽을 것)**
- `current_token_payload` 는 **의도적으로 폐기 목록을 보지 않는다.** 로그아웃을 두 번 눌러도
  성공해야 하기 때문이다. 이 경로는 토큰 외 입력이 없고 폐기만 하므로 얻을 수 있는 게 없다.
  데이터를 만지는 엔드포인트는 전부 `current_user`(폐기 확인 O)를 쓴다.
- `revoked_tokens.user_id` 에 **외래키를 걸지 않았다.** 계정이 삭제돼도 그 토큰이 만료될 때까지는
  폐기 기록이 남아 있어야 하기 때문이다.
- `jti` 없는 옛 토큰은 개별 폐기가 불가능하다. 성공한 척하지 않고 `token_revoked: false` 로 알린다.
  기존 로그인 세션은 그대로 동작한다(`test_legacy_token_without_jti_still_authenticates`).

**작업 중 발견한 버그 (수정 완료)**
`main.js` 의 401 핸들러가 `logout()` 을 부르고 있었다. 로그아웃이 서버 호출을 하게 되면서
**무효 토큰으로 서버를 다시 불러 401 이 또 나는 재진입 구조**가 될 뻔했다.
로컬 정리 전용 `clearSession()` 을 분리해 401 핸들러·탈퇴 완료 두 곳에 적용했다.

---

### Phase 6~8 — 콘텐츠 확장 준비 / 모델 평가 / 학습 이벤트 (DONE)

| Phase | 구현 | 파일 |
|---|---|---|
| 6 | 케이스 후보의 **객관적 metadata** 계산 (편측·GT voxel·상대크기·AI 검출·FN/FP). 난이도는 채우지 않는다 | `scripts/analyze_case_candidates.py` |
| 7 | 모델 평가 — 검출률 / 전체 Dice vs 검출건만 Dice / **크기 구간별** / 버전 비교 | `scripts/evaluate_model.py` |
| 8 | 학습 이벤트 기록 + 집계 리포트 | `app/analytics.py`, `app/models.py`(LearningEvent), `scripts/learning_report.py` |

**실제로 드러난 사실 (콘텐츠 계획에 반영할 것)**
- 현재 6케이스는 **우측 5 / 좌측 1** 로 편향돼 있다. 이대로 늘리면 학습자가 "오른쪽을 칠하면 맞는" 훈련을 하게 된다.
- AI 미검출 1건(VS-SEG-204)은 **세트에서 가장 작은 병변**이다.
  small 구간 검출률 0.5 vs medium/large 1.0 → CLAUDE.md 의 "소형 intracanalicular" 가설과 방향이 맞는다.
- 평균 Dice 0.79 는 이 모델을 잘못 요약한다. 검출건만 보면 0.9488 이다
  (= "전반적으로 부정확"이 아니라 "가끔 완전히 놓치는" 모델).

**설계 메모 (다음 세션이 알아야 할 것)**
- FN/FP 는 마스크 npy 를 다시 읽지 않고 **Dice 에서 교집합을 역산**해 구한다
  (`overlap_from_dice`). 수백 MB 파일을 건드리지 않기 위함이다.
- `size_bucket_relative` 는 **분석 대상 안에서의 3분위**다. 절대 기준이 아니고 의학적 분류도 아니다.
  `test_same_sizes_in_a_different_set_get_different_buckets` 가 이 성질을 고정한다.
- 버전 비교는 **평균이 올라도 회귀를 잡는다** — 이전에 검출하던 케이스를 놓치면 `[회귀]` 를 찍는다.
- 학습 이벤트에는 **개인정보 칸이 아예 없다**. 컬럼 집합을 테스트가 고정하므로
  (`test_event_table_has_no_personal_fields`) 나중에 이메일·IP 를 추가하려 하면 실패한다. 의도된 가드다.
- 이벤트는 채점·학습 상태 계산에 개입하지 않는다. 테이블을 통째로 비워도 서비스는 동작한다.
- 탈퇴 시 이벤트도 함께 삭제된다 (`DELETED_SCOPES` 에 포함).

---

## 4. 자율 개발 루프 #20~32 (2026-09-09)

Phase 백로그가 끝난 뒤 스스로 선정해서 진행한 작업들이다.
**대부분은 "화면에는 있는데 실제로는 동작하지 않던 것"과 "조용히 잘못되는 설정"이었다.**

### 실제 결함 (조용히 틀리던 것들)

| # | 무엇이 잘못돼 있었나 | 어떻게 드러났나 |
|---|---|---|
| 20 | `MEDISCAN_ALLOW_APPROX_GRADING` / `SEED_MOCK_CASES` / `ANALYZE_DEMO` 가 production 가드 없이 켜질 수 있었다 | 켜져도 서버는 겉보기에 정상. 각각 검수 안 된 채점·합성 콘텐츠·꾸며낸 분석 결과를 낸다 |
| 21 | `MEDISCAN_MATCH_DICE=75`(75% 의도)가 **조용히 0.60 으로** 되돌아갔다. `partial > match` 뒤집힘은 아무도 검사 안 했다 | 뒤집히면 `partial_match` 등급이 통째로 도달 불가능해진다 |
| 22 | `MEDISCAN_RATE_LIMIT=0` 이 production 으로 따라갈 수 있었다 (문서가 E2E 용으로 쓰라고 안내까지 했다) | 로그인 무차별 대입이 열린 채로 정상 기동 |
| 25 | 백업이 **읽히는지 아무도 확인하지 않았다** | `DATABASE_URL` 미설정으로 빈 개발 DB 를 백업해도 "백업 완료" |
| 26 | 로그아웃 더블클릭 → IntegrityError → **500**. 재설정 코드가 **두 번 사용 가능**했다 | 재현해서 확인. `일회용`이 실제로는 보장되지 않았다 |
| 27 | 가입 버튼 더블클릭 → **500**. 경쟁 구간이 scrypt 해싱이라 **사람이 두 번 누를 수 있는 폭** | 409 여야 할 것이 서버 오류로 보였다 |
| 30 | `ResultCompare` 가 `getContext('2d')` null 이면 mounted 에서 터졌다 | 겹쳐보기 하나 때문에 등급·수치까지 사라진다 |

### 반쪽 기능 (수집·표시 한쪽만 있던 것)

| # | 무엇 |
|---|---|
| 30 | 회차(`attempt_number`)를 세서 **운영자 로그에만** 넣었다. 재도전한 학습자는 자기 변화를 볼 수 없었다 → `progress` 블록 |
| 31 | 운영자 화면이 "평균 소요시간"을 보여주는데 **프론트가 값을 안 보냈다** → 항상 `—` |
| 32 | `EXPLANATION_VIEWED` 상수만 있고 **기록하는 곳이 없었다** → 해설 열람률 |

### 그 밖에

| # | 무엇 |
|---|---|
| 23 | `/health` 가 실제 적용 중인 설정(채점 임계값·제한 상태·개발 스위치)을 보여준다. `scoring_config` 주석은 "/health 에 노출한다"고 적혀 있었지만 실제로는 아니었다 |
| 24 | 사용자에게 보이던 개발자 안내 정리 (`uvicorn ... 실행 중인지 확인하세요`), 5xx/4xx 구분, 429 의 `Retry-After` 를 사람이 읽는 단위로 |
| 28 | 접근성 점검 도구(`tools/browser-verify/a11y-audit.mjs`) + 캔버스 대체 설명. 실제 지적은 1건이었다 |
| 29 | 죽은 코드 항목 3건을 확인 — **둘은 죽은 코드가 아니었다** (근사 채점은 mock 케이스용으로 필요, `Submission.explanation` 은 의도된 스냅샷) |

---

## 5. 케이스 검수 워크플로 · 운영 자동화 (2026-09-09, 루프 #35~39)

사용자 요청으로 케이스 검수 UI 를 만들고, 이어서 운영 자동화 백로그를 진행했다.

### 케이스 후보 기술 검수 (`/admin/review`)

**핵심 설계: 검수 상태를 셋으로 분리했다.** 하나로 합치면 "검수 완료"가 어느 층위의
검수인지 알 수 없게 되고, 결국 검수되지 않은 GT 가 학습자의 채점 기준이 된다.

| 상태 | 누가 정하나 | 뜻 |
|---|---|---|
| `technical_review_status` | 운영자 (이 화면) | export 파이프라인이 제대로 돌았는가 |
| `expert_review_status` | 전문가만 | 의학적으로 옳은가 (기본 `pending`) |
| `activation_status` | 둘 다 끝난 뒤 | 학습자에게 보이는가 |

**`TECH_PASS` 로는 나머지 둘을 바꿀 수 없다** — API 스키마가 아예 받지 않고,
테스트가 화면·서버 양쪽에서 고정한다. AI 예측은 GT 와 다른 색·점선 블록으로 분리한다.

관련: `app/review_store.py` · `app/review_candidates.py` · `app/routers/review.py` ·
`frontend/src/views/CaseReviewView.vue` · `docs/CASE_REVIEW_CHECKLIST.md`

### 운영 자동화 (이번에 추가한 스크립트)

| 스크립트 | 무엇 | 안전 규칙 |
|---|---|---|
| `review_package.py` | 검수 결과 summary + 다음 단계 manifest **후보** | 등록·활성화하지 않는다. 난이도·소견은 비운다 |
| `preflight_candidates.py` | 기술 통과 후보 사전 검증 | 의료 판단 없음 |
| `sidecar_manage.py` | 예측 sidecar status/plan/validate/promote | **검증 실패분은 승격하지 않는다.** 승격 전 백업 |
| `restore_drill.py` | 백업을 되돌려 **앱이 실제로 뜨는지** | 운영 DB 로 되돌리는 경로가 없다 |
| `deploy_preflight.py` | 배포 직전 점검 | 사람 판단 항목은 **"확인못함"** 으로 남긴다 |

### 이번에 고친 실제 결함

| 무엇이 잘못돼 있었나 |
|
### 운영 자동화 2차 (루프 #40~44)

| 스크립트·모듈 | 무엇 | 안전 규칙 |
|---|---|---|
| `deploy_preflight.py` | 배포 직전 점검 | 사람 판단 항목은 **"확인못함"** — 통과로 뭉개지 않는다 |
| `license_inventory.py` | 의존성·자산 라이선스 목록 | **판단하지 않는다.** 데이터셋·가중치는 사람 검토 항목 |
| `app/asset_urls.py` | 케이스 영상·마스크 **서명 URL** | 인증 없이 의료영상을 받을 수 없다 |
| `app/security_headers.py` | 보안 헤더 | **CSP 는 추측해서 만들지 않는다** (`MEDISCAN_CSP`) |
| `tests/test_error_contract.py` | 에러 코드 양방향 대조 | 코드↔문서가 어긋나면 실패 |
| `tests/test_documentation_drift.py` | 문서 표류 점검 | 없는 스크립트·환경변수·문서 참조를 잡는다 |
| `tools/browser-verify/error-paths.mjs` | 오류 경로 E2E | 사용자가 잘못됐을 때 무엇을 보는가 |

### 운영자 화면 UX (루프 #45)

화면을 실제로 띄워 보고 세 가지를 고쳤다.

| 무엇이 잘못돼 있었나 |
|---|
| 소견 없이 `검토 완료` 를 **고를 수 있게 해놓고** 서버가 422 로 실패시켰다 |
| 버튼이 **상태**("노출 중")를 말해서 누르면 노출된다고 읽혔다 (실제로는 숨겨진다) |
| **제출 332건짜리 케이스가 클릭 한 번에** 사라졌다 (확인 단계 없음) |

검색·필터 5종을 추가했다. 24건 확장 후에는 스크롤로 못 찾는다.
"소견 없음" 필터는 전문가 검토 대상을 추리는 데 바로 쓰인다.

### SNS 토큰 실검증 (루프 #46)

**계정 탈취 경로가 열려 있었다.** `provider_token` 을 검증 없이 계정 식별자로 써서:

  1. 토큰 값만 알면 **남의 계정으로 로그인**됐다
  2. 토큰이 갱신되면 **같은 사람이 새 계정**이 됐다 (학습 이력이 갈린다)

각 사에 토큰을 되물어 **바뀌지 않는 식별자**를 받아 계정 키로 쓴다(`app/social_auth.py`).
`aud`/`app_id` 를 확인해 **다른 서비스용 토큰**으로 들어오는 것도 막는다.
설정되지 않으면 **production 은 503 으로 거부**한다 — "아직 안 만들었다"와
"열려 있다"는 다르다. 앱 시크릿은 필요 없고 공개 값(앱 ID)만 있으면 켜진다.

### 2차 보안 점검에서 나온 실제 취약점

**`/static/cases/.../slice_035.png` 를 로그인 없이 받을 수 있었다** (실제 의료영상 155KB).
`case_id` 가 예측 가능해 열거 가능했고 기준 마스크(정답)도 같았다.
`<img src>` 에 헤더를 붙일 수 없어 **서명 URL**(HMAC, 기본 24시간)로 막았다.
URL 생성이 `absolute_url()` 한 곳이라 거기만 고쳐 전 응답이 함께 보호된다.

### 추가로 고친 것

| 무엇이 잘못돼 있었나 |
|---|
| `INVALID_CREDENTIALS`(로그인 실패)가 **api-spec 에러 코드 표에서 빠져** 있었다 |
| 루트 README **417** / CLAUDE.md **563** / RELEASE_READINESS **662** — 실제는 786 이었다 |
| 보안 헤더가 **하나도 없었다** (클릭재킹·MIME 스니핑 방어 없음) |
| 저장소에 **LICENSE 파일이 없다** → BLOCKER-5 로 기록 |
| `psycopg2-binary` 가 LGPL 계열 → 배포 형태 확인 대상으로 문서화 |

---
|
| 검수 화면에서 PASS 해도 **상단 진행 현황이 갱신되지 않았다** (서버 스냅샷을 그대로 씀) |
| **케이스 등록이 전체 한 트랜잭션**이라 20번째에서 실패하면 앞 19건이 날아가고, DB 는 롤백되는데 **static 에 파일은 남았다** |
| `pre_review_check` 에서 **빈 마스크가 경고 없이 통과**했다 |
| `restore_drill` 서브프로세스 출력을 cp949 로 읽어 한국어 로그에서 UnicodeDecodeError |
| `deploy_preflight` 에서 DB 연결 실패가 **전체 점검을 중단**시켜 환경 설정 결과까지 잃었다 |

---

## 6. 아직 하지 않은 작업

**사람이 있어야 하는 것**
- **케이스 24건 육안 검수** — `/admin/review` 에서 판단하면 된다. 준비는 전부 끝났다.
  이게 제품을 가장 크게 바꾼다 (지금 6케이스로는 학습 분량이 부족하다)
- **`case_findings` 입력** — 구조 완성, 전문가 대기 (BLOCKER-2)
- **SNS 앱 등록** — 실검증 로직은 끝났다. 각 사에서 앱 ID 를 받아 환경변수에 넣으면 켜진다

**코드로 가능한 것 (남은 것이 많지 않다)**
- 키보드로 ROI 입력할 수단 (자유곡선 대체 — 설계 판단 필요)
- `Submission.explanation` 스냅샷을 어디에 보여줄지
- 본격 부하 테스트 (동시성 **정확성**은 확인했다)
- CSP 정책 확정 (배포 형태가 정해진 뒤 `MEDISCAN_CSP` 로)

**외부 수단·판단이 필요한 것**
- 이메일 인증 (BLOCKER-4)
- 접속기록(감사 로그) 범위 (BLOCKER-3)
- 저장소 라이선스 (BLOCKER-5)

---

## 7. 변경된 주요 파일

**Phase 2**
- 신규: `backend/app/config.py`, `backend/app/cors.py`, `backend/app/rate_limit.py`, `backend/app/account.py`
- 신규 테스트: `backend/tests/test_production_config.py`(12), `test_rate_limit.py`(8), `test_account_deletion.py`(9)
- 수정: `backend/app/main.py`(미들웨어·health), `backend/app/security.py`(키 가드),
  `backend/app/schemas.py`(DeleteAccount*), `backend/app/routers/auth.py`(DELETE /me),
  `backend/tests/conftest.py`(rate limit 리셋 + UserSession.delete),
  `backend/.env.example`, `docs/api-spec.md`(1-4-1, 에러코드 2건)

---

## 8. Migration 여부

마이그레이션 3건 추가 (**전부 추가 전용, 데이터 파괴 없음**):
- `e81bbce560b5` cases.findings_status (Phase 4)
- `e93378ca7e48` users.is_admin, cases.is_active, cases.difficulty (Phase 5)
- `0fc6767cf5ba` learning_events 테이블 신규 (Phase 8)
- `72c54e42f82a` revoked_tokens 테이블 신규 (자율 루프 #1)
스키마 변경 시 반드시:
```
cd backend && alembic revision --autogenerate -m "<설명>"
```
기존 데이터를 파괴할 수 있는 마이그레이션은 임의로 만들지 않는다 (BLOCKER로 남긴다).

---

## 9~10. 테스트

**마지막 전체 검증 (자율 루프 #32 이후)**

| 무엇 | 명령 | 결과 |
|---|---|---|
| 백엔드 (SQLite) | `cd backend && pytest` | **806 passed** |
| 백엔드 (PostgreSQL) | `python -m scripts.verify_postgres --url ... --with-tests` | 마이그레이션 up/down/up + 전체 테스트 통과 |
| 케이스 | `python -m scripts.verify_cases` | 6케이스 통과 |
| 프론트 단위 | `cd frontend && npx vitest run` | **74 passed** |
| 빌드 | `npm run build` | 통과 |
| 브라우저 E2E | `tools/browser-verify/{user-flow,slice-navigation,consent-and-sns,screenshot-all}.mjs` | 4종 통과 |
| 접근성 | `tools/browser-verify/a11y-audit.mjs` | 지적 0건 |

현재 실패하는 테스트: **없음**

**추이** (테스트가 늘어난 지점 = 무언가 깨져 있던 지점이다)

| 시점 | 백엔드 | 프론트 |
|---|---|---|
| Phase 1 (시작) | 241 | 0 |
| Phase 8 | 382 | 0 |
| 자율 #19 | 475 | 40 |
| 자율 #32 | 563 | 59 |
| 루프 #39 (현재) | **701** | **59** |

**테스트를 돌릴 때 알아둘 것**
- E2E 는 백엔드를 `MEDISCAN_RATE_LIMIT=0` 으로 띄운다 (반복 실행하면 한도에 걸린다).
  이 값은 **production 에서 기동을 막는다** — 배포 환경에 가져가지 않는다.
- 백엔드 코드를 고쳤으면 **uvicorn 을 다시 띄운다.** 옛 프로세스가 포트를 잡고 있으면
  새 엔드포인트가 404 로 나온다 (`netstat -ano | grep 8010` 으로 PID 확인).
- 테이블을 추가했으면 **PostgreSQL 재검증을 돌린다.** 지금까지 두 번 돌려 두 번 다
  SQLite 에서는 안 보이던 문제를 잡았다.

---

## 11. 발견된 문제

`docs/RELEASE_READINESS.md` 3~6절에 Critical(C1~C4) / High(H1~H7) / Medium / Low로 정리.

---

## 12. 사용자 판단이 필요한 사항 (BLOCKERS)

문서 하단 "BLOCKERS" 절 참고. 현재 5건 (데이터셋·모델 라이선스 1, 전문가 1, 규제 1, 메일 발송 수단 1, 저장소 라이선스 1).

---

## 13. NEXT STEP — 다음 세션이 가장 먼저 할 일

> **Phase 1~8 과 자율 루프가 전부 끝났다. 이미 있는 것을 다시 만들지 말 것.**
> 4·5절과 `docs/RELEASE_READINESS.md` 3~6절을 먼저 본다.
>
> **1순위 — 사람이 있어야 진행되는 것**
> - [ ] **케이스 24건 육안 검수**: `/admin/review` 에서 카드를 보고 PASS/HOLD/REJECT.
>       준비는 전부 끝났다 (export · 검수 시트 · 기계 사전점검 · 기록 저장 · 단축키).
>       운영자 계정이 필요하다: `python -m scripts.grant_admin --email <이메일>`
>       판단 기준은 `docs/CASE_REVIEW_CHECKLIST.md` 2절.
>       **6케이스로는 학습 분량이 부족하다 — 이게 제품을 가장 크게 바꾼다.**
> - [ ] **`case_findings` 입력**: 전문가가 `/admin/cases` 에서 (BLOCKER-2)
>
> 검수가 끝나면 이어지는 것은 전부 준비돼 있다:
> ```bash
> python -m scripts.review_package --review-root data/expansion_review --export-root data/expansion_export
> python -m scripts.preflight_candidates --review-root data/expansion_review --export-root data/expansion_export
> # 통과분만 자산 생성 -> import_cases (is_active=false 로 들어간다)
> ```
>
> **2순위 — 코드로 가능한 것 (사용자가 준 백로그 순서)**
> - [ ] error-path E2E — 오류 화면·복구 경로를 브라우저에서 확인
> - [ ] security review 2차
> - [ ] API error contract 정리
> - [ ] Admin UX
> - [ ] dependency / license inventory
> - [ ] documentation drift 자동 점검
>
> **3순위 — 외부 수단·판단**
> - [ ] SNS 실인증 (CLAUDE.md 가 "실서비스 전 반드시"라고 적은 유일한 하드닝 잔여 항목)
> - [ ] 이메일 인증 (BLOCKER-4) / 접속기록 범위 (BLOCKER-3)
>
> ---
>
> **작업 규칙 (실제로 사고가 났던 것들)**
>
> *검증*
> - 테이블을 추가하면 **PostgreSQL 검증을 다시 돌린다**
> - 백엔드를 고쳤으면 **uvicorn 을 다시 띄운다** (옛 프로세스가 포트를 잡으면 404)
> - **점검 도구는 무엇을 봤는지 함께 출력한다.** 0건 지적이 "제대로 봤는데 없음"인지
>   "아무것도 못 봤음"인지 구분되어야 한다 (접근성 점검에서 두 번 틀렸고 둘 다 통과로 보였다)
> - 어떤 동작을 새로 만들면 **켜지는 것과 안 켜지는 것을 모두 확인한다**
> - **"전부 통과"가 나오면 일부러 깨뜨려 본다.** 그렇게 해서 빈 마스크가 경고 없이
>   통과하던 것과 sidecar 자기모순을 찾았다
> - **점검 도구는 한 항목이 터져도 나머지를 계속한다** (deploy_preflight 에서 겪었다)
>
> *설계*
> - 관리 화면에서 설정하는 값이 **학습자 경로까지 실제로 가는지** 확인한다
> - 개발 편의 스위치를 추가하면 **production 에서 막을지 정한다** (`config.DEV_ONLY_FLAGS`)
> - 설정을 읽을 때 **잘못된 값을 기본값으로 되돌리지 않는다** — 그게 "조용히 잘못됨"이다
> - 없는 값을 0 으로 채우지 않는다
> - **확인하지 못한 것을 "이상 없음"으로 뭉개지 않는다** (unchecked / 확인못함으로 남긴다)
> - DB 와 파일을 함께 바꾸는 작업은 **케이스 단위로 원자화**한다 (import_cases 참고)
> - UI 문자열에 API 경로·내부 필드명·실행 방법이 새지 않게 한다
>
> *의료 안전*
> - **기술 검수 ≠ 전문가 검수 ≠ 서비스 활성 승인.** 상태를 합치지 않는다
> - AI 예측은 GT 와 시각적으로 완전히 분리한다 (VS-SEG-204 가 반례다)
> - 난이도·소견을 자동으로 채우지 않는다. 비워 두는 것이 정답이다
>
> *테스트*
> - admin 엔드포인트를 추가하면 `tests/test_admin.py` 의 `ADMIN_ENDPOINTS` 에도 넣는다
> - 사용자 데이터 테이블을 추가하면 `conftest._clean_user_data` 에도 넣는다
> - 동시성은 **스레드 대신 인터리빙을 결정적으로 만들어** 테스트한다
> - E2E 반복 실행은 `MEDISCAN_RATE_LIMIT=0` 으로 띄운 백엔드에서 (개발 전용)
> - 테스트가 실제 `static/` 을 건드리지 않게 `CASES_DIR` 을 monkeypatch 한다
>
> *셸*
> - 파이썬/JS 파일을 bash heredoc 으로 쓰면 이스케이프가 깨진다 — 전용 도구를 쓴다
> - 콘솔이 cp949 라 `PYTHONIOENCODING=utf-8` 을 붙인다.
>   서브프로세스 출력도 `encoding="utf-8"` 로 읽는다

---

## BLOCKERS

### BLOCKER-1 — VS-SEG 데이터셋 / VS_Seg 가중치 이용 조건 (`NEEDS_LICENSE_REVIEW`)
- **무엇이 필요한가**: 데이터셋과 pretrained 가중치를 Closed Beta(외부 사용자 대상)에서 쓸 수 있는지 확인.
- **왜 필요한가**: 연구 목적 로컬 사용과, 외부 사용자에게 영상을 보여주는 서비스는 조건이 다를 수 있다.
- **선택지**: (a) 원 저작자/데이터 제공처 조건 확인 후 진행 (b) 조건 불명확하면 Closed Beta를
  학내 비공개 사용으로 제한 (c) 자체 확보한 교육용 영상으로 교체.
- **추천**: (a). 확인 전까지는 (b)로 범위를 제한.
- **영향**: 외부 공개 Closed Beta의 전제 조건. 코드 작업은 계속 가능.

### BLOCKER-2 — `case_findings` 의료 소견 작성 (`NEEDS_EXPERT_REVIEW`)
- **무엇이 필요한가**: 6케이스의 영상 소견을 작성할 의료 전문가 1명 + 검토자명/검토일.
- **왜 필요한가**: 학습 피드백의 핵심이며, **Claude가 임의 생성하면 안 되는 내용**이다.
- **선택지**: (a) 지도교수/멘토 검토 (b) 임상 실습 경험자 검토 후 표기 (c) 비워둔 채 Closed Beta 진행.
- **추천**: (c)로 시작하되 구조는 미리 만들어 두고(Phase 4), 확보되는 대로 입력.
- **영향**: 없어도 서비스는 동작한다(블록이 비면 화면에서 생략). 학습 가치는 크게 떨어진다.

### BLOCKER-5 — 저장소 라이선스 미지정 (`NEEDS_USER_DECISION`)
- **무엇이 문제인가**: 저장소를 Public 으로 돌렸는데 `LICENSE` 파일이 없다.
  라이선스가 없으면 기본적으로 **모든 권리가 유보**된다 — 남이 볼 수는 있어도
  쓰거나 고칠 권리는 없다. 팀 프로젝트로 공개하는 의도와 맞는지 확인이 필요하다.
- **왜 자동으로 정하지 않았나**: 라이선스 선택은 프로젝트 소유자의 결정이다.
  특히 이 프로젝트는 의료 데이터셋·모델 가중치를 쓰고 있어(BLOCKER-1) 코드 라이선스만
  단독으로 정하기 어려울 수 있다.
- **참고**: `docs/DEPENDENCIES.md` 에 현재 쓰는 의존성과 각 라이선스가 정리돼 있다.
  `psycopg2-binary` 가 LGPL 계열이라 **배포 형태에 따라** 의무가 생길 수 있다
  (서버에서 실행하는 형태면 통상 문제되지 않지만 확인 대상이다).
- **영향**: 서비스 동작에는 영향이 없다. 공개·재사용 조건의 문제다.

### BLOCKER-4 — 이메일 발송 수단 (`NEEDS_USER_DECISION`)
- **무엇이 필요한가**: 이메일 인증과 셀프서비스 비밀번호 찾기를 하려면 메일 발송 수단이 필요하다.
- **왜 필요한가**: 지금은 남의 이메일로 가입할 수 있고, 비밀번호 재설정은 운영자를 거쳐야 한다.
- **선택지**: (a) 외부 메일 서비스 가입(유료일 수 있음) (b) 학교 SMTP 사용
  (c) Closed Beta 규모에서는 현재 방식(운영자 발급 코드)으로 충분하다고 보고 미룬다.
- **추천**: (c). 수십 명 규모에서 운영자 발급으로 감당 가능하고, 외부 서비스 결제는
  사용자 승인이 필요한 사항이다.
- **영향**: 없어도 서비스는 동작한다. 가입 이메일의 진위만 보증되지 않는다.

### BLOCKER-3 — 탈퇴 시 동의 이력 처리 / 접속기록 보관 (`NEEDS_REGULATORY_REVIEW`)
- **무엇이 필요한가**: 회원 탈퇴 시 동의 이력을 함께 지울지, 증빙으로 보존할지에 대한 판단.
- **왜 필요한가**: 개인정보 파기 의무와 동의 증빙 보존이 충돌한다. 법률 판단 영역이다.
- **선택지**: (a) 전부 하드 삭제 (b) 계정·제출 이력 삭제 + 동의 이력은 익명화 보존
  (c) 소프트 삭제 후 유예기간.
- **추천**: Closed Beta 규모에서는 (a)가 사용자에게 가장 안전하고 설명하기 쉽다. Phase 2에서
  (a)로 구현하되, 판단이 서면 (b)로 바꿀 수 있게 삭제 로직을 한 함수에 모아둔다.
- **영향**: Phase 2 C4 구현 방식. 이미 (a)로 구현했다면 되돌리는 비용은 작다.
