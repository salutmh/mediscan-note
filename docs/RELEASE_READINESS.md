# Closed Beta 준비 상태 (RELEASE_READINESS)

> 최초 작성: 2026-09-08 / 기준 커밋: `ef56005`
> 이 문서는 **실제 코드를 읽고 확인한 사실만** 기록한다. 과거 리뷰 문서의 주장은 근거로 쓰지 않는다.
> 갱신 이력은 문서 맨 아래 "변경 로그" 참고.

---

## 1. 현재 제품 scope

**의료영상 판독 학습용 교육 서비스.** 실제 환자 진단이 아니다.

학습 루프: 교육용 영상 확인 → 사용자 ROI 표시 → **전문가 GT 기준 채점** → 정답 영역·해설 확인 →
AI 보조 피드백(참고) → 오답 재학습.

**이번 Closed Beta에서 활성화하지 않는 것**
- 개인 실제 MRI 업로드 진단 (화면 5는 `model_unavailable` 유지 — 규제 성격이 달라짐)
- DICOM 시리즈 업로드
- 실제 SNS OAuth

---

## 2. 구현 완료 (코드에서 확인함)

| 영역 | 확인 내용 | 근거 |
|---|---|---|
| 인증 | scrypt 해싱, HMAC-SHA256 서명 + 만료 토큰, 401 강제 | `app/security.py`, `app/deps.py` |
| SNS 로그인 | 토큰을 각 사에 되물어 **바뀌지 않는 식별자**를 저장. 미설정 제공자는 production 에서 거부 | `app/social_auth.py` |
| 동의 | 필수 5 + 선택 1, **append-only** 이력(버전·시각) | `app/routers/auth.py:49`, `app/models.py:38` |
| 채점 | **reference mask 전용** Dice/IoU/location_score. 보정 없음 | `app/grading.py:190`, `app/masks.py:103` |
| 채점 거부 | 기준 마스크 없으면 422 `CASE_NOT_GRADABLE` + **이력 미생성** | `app/routers/cases.py:41` |
| AI 분리 | sidecar 우선 → volume 모델은 2D 호출 차단 → 실패해도 예외 삼킴 | `app/grading.py:79` |
| 학습 상태 | `has_matched`(누적) / `needs_review`(최신 제출 기준) 두 축 | `app/repository.py:50` |
| 재도전 경과 | `progress`(회차·직전 점수·최고 점수·향상 여부). **학습자 자신의 숫자만**, grade 에 영향 없음 | `app/routers/cases.py`, `docs/api-spec.md` |
| 해설 3층 | `case_facts`/`disease_info`/`case_findings`, `content_levels`는 **파생 계산** | `app/explanations.py:35` |
| 업로드 검증 | 크기→포맷→손상→픽셀수→region, 미저장 + EXIF 제거 | `app/uploads.py` |
| 화면 5 | 지어내지 않고 `model_unavailable`, 데모는 flag OFF 기본 | `app/routers/analyze.py:74` |
| 스키마 | Alembic이 기준, 기동 시 자동 upgrade + 레거시 DB 감지 | `app/db.py:47` |
| 정적 자산 | 요청 주소 기준 절대 URL 생성 + **케이스 영상·마스크는 서명 URL 로만** (인증 없이 받을 수 없다) | `app/static_files.py`, `app/asset_urls.py` |
| 보안 헤더 | nosniff / X-Frame-Options DENY / Referrer-Policy / COOP / Permissions-Policy. CSP 는 **추측해서 만들지 않는다**(MEDISCAN_CSP 로 지정) | `app/security_headers.py` |
| 테스트 | 백엔드 **1011개**(SQLite·PostgreSQL 양쪽) + 프론트 **108개** + E2E 7종 + 접근성·좁은화면 점검 | `backend/tests/`, `frontend/src/**/*.test.js` |

**이미 해결된 것은 다시 만들지 않는다.** 위 항목은 재구현 대상이 아니다.

---

## 3. Critical — Closed Beta 공개 전 반드시

| # | 항목 | 현재 상태 | 근거 | 상태 |
|---|---|---|---|---|
| C1 | `MEDISCAN_SECRET_KEY` production 가드 없음 | ~~미설정 시 dev 키로 기동~~ → **production 이면 기동 실패** | `app/security.py`, `app/config.py` | ✅ DONE |
| C2 | CORS wildcard | ~~`allow_origins=["*"]`~~ → production 은 오리진 명시 필수, dev 는 localhost regex | `app/cors.py` | ✅ DONE |
| C3 | rate limit 전무 | ~~무제한~~ → login 10/분, signup 10/시간, social 20/분, 탈퇴 5/시간 | `app/rate_limit.py` | ✅ DONE |
| C4 | 회원 탈퇴 API 없음 | ~~없음~~ → `DELETE /api/auth/me` (비밀번호 재확인 + 하드 삭제) | `app/account.py` | ✅ DONE |

---

## 4. High — Closed Beta 품질에 직접 영향

| # | 항목 | 현재 상태 | 상태 |
|---|---|---|---|
| H1 | **spatial feedback 없음** | ~~숫자뿐~~ → `spatial_feedback` 추가 (coverage/precision/중심거리/과소·과대 표시 + 교육 문구) | ✅ DONE |
| H2 | **`case_findings` 운영 구조 없음** | ~~검토 상태 없음~~ → 학습 필드 확장 + `findings_status`(DB) + 응답 `case_findings_status`. **내용은 전문가 대기(E1)** | ✅ 구조 DONE |
| H3 | Admin CMS 없음 | ~~CLI 뿐~~ → `/api/admin/*` + 최소 운영 화면. 활성/비활성·난이도·검토상태·소견 등록 | ✅ DONE |
| H4 | 서버측 토큰 폐기 없음 | ~~클라이언트 삭제만~~ → `POST /api/auth/logout` + `revoked_tokens` 폐기 목록 | ✅ DONE |
| H5 | 이메일 인증 / 비밀번호 재설정 | **변경·재설정 모두 구현.** 재설정은 운영자 발급 일회용 코드 방식(메일 불필요). **이메일 인증만 미구현** — 메일 발송 수단 필요 | 🟡 이메일 인증만 남음 |
| H6 | 채점 임계값 하드코딩 | ~~상수~~ → `app/scoring_config.py` 분리 + 응답에 `validation_status` 노출 | ✅ DONE |
| H7 | 학습 분석 이벤트 없음 | ~~없음~~ → `learning_events` + CLI + **운영자 화면 지표**(`GET /api/admin/learning-summary`). 개인정보 미수집, 집계만 노출. **소요시간·해설 열람률은 아무도 보내지 않아 비어 있었고, 이제 실제로 채워진다** | ✅ DONE |

---

## 5. Medium

| # | 항목 |
|---|---|
| ~~M1~~ | ~~구조적 로깅 없음~~ → `app/logging_config.py` (text/json, 레벨 설정). **원래 앱의 INFO 로그가 전부 버려지고 있었다** |
| ~~M2~~ | ~~`_grade_by_points` 개발용 근사 채점 경로가 코드에 남아 있음~~ → `MEDISCAN_ALLOW_APPROX_GRADING` 을 포함한 **개발 전용 스위치 3종이 production 에서 기동을 막는다**(`app/config.py`, `tests/test_dev_only_flags.py`). 경로 자체는 개발용으로 남긴다 |
| ~~M3~~ | ~~난이도 메타데이터 없음~~ → `cases.difficulty` 추가 (Phase 5). **자동 판정하지 않고 전문가 검토 대상**(E2) |
| ~~M4~~ | ~~모델 평가 도구 없음~~ → `scripts/evaluate_model.py` (검출률·크기 구간별·버전 비교, Phase 7) |
| ~~M5~~ | ~~예측 sidecar 수동 재계산~~ → **수명주기 도구**(`scripts/sidecar_manage.py`): stale 판정(모델버전·가중치 sha256·GT/volume sha256·GT voxel·스키마·자기모순) → 재계산 계획 → 검증 → **백업 후 승격**. GPU 없이 돌아가고 **검증 실패분은 승격하지 않는다.** 실제 추론만 학습 venv 가 필요하다 |
| M6 | ~~동시성 미검증~~ → **경쟁 조건 2건을 재현해서 고쳤다**(`tests/test_concurrency.py`): 로그아웃 더블클릭 시 IntegrityError → 500, 재설정 코드가 두 번 사용 가능. ~~PostgreSQL 실검증 없음~~ → **검증 완료**(scripts/verify_postgres.py, 544 테스트 통과). **동시 쓰기 스모크 확인**(`scripts/load_smoke.py`): 동시 30명 x 3회 = 90건 전부 성공, 중앙 445ms, SQLite 잠금 오류 0건. 단일 요청은 앱 내부 30ms / 네트워크 경유 44ms. 본격 부하 테스트(지속 처리량·한계점)는 여전히 미실시 — Closed Beta 규모에서는 우선순위가 낮다 |

## 6. Low

| # | 항목 |
|---|---|
| ~~L1~~ | ~~`explanations.py` docstring stale~~ → Phase 4에서 수정 완료 |
| ~~L2~~ | ~~`cases.reference_shape` 레거시 컬럼~~ → **죽은 코드가 아니다.** mock 케이스에는 기준 마스크가 없어서, 실제 의료영상 없이 채점 화면을 확인하려면 이 경로가 필요하다. production 에서는 기동이 막히므로(M2) 그대로 둔다 |
| ~~L3~~ | ~~`frontend/public/icons.svg`~~ → 삭제함 (참조 0건 확인) |
| L5 | `Submission.explanation` 은 쓰기만 하고 읽는 곳이 없다. **의도된 스냅샷**이라 지우지 않는다(전문가가 소견을 개정해도 학습자가 답할 당시 본 내용이 남아야 한다). 다만 아직 어디에도 노출되지 않는다 |
| L4 | **키보드만으로 ROI 를 그릴 수 없다.** 포인터 자유곡선 입력이라 대체 입력 수단이 필요하다. `tools/browser-verify/a11y-audit.mjs` 는 통과하지만 그 점검은 이 항목을 보지 않는다 |

---

## 7. Security checklist

| 항목 | 상태 |
|---|---|
| production에서 SECRET_KEY 강제 | ✅ 미설정·dev값·32자 미만이면 기동 실패 |
| CORS origin 제한 | ✅ production 은 `MEDISCAN_CORS_ORIGINS` 필수 + 와일드카드 금지 |
| 인증 엔드포인트 rate limit | ✅ signup/login/social-login/탈퇴. 학습 흐름은 제외 |
| 비밀번호 해싱 | ✅ scrypt (n=2^14) |
| 토큰 서명·만료 | ✅ HMAC-SHA256 + exp |
| 서버측 토큰 폐기 | ✅ 로그아웃 시 jti 기준 폐기. 다른 기기 세션은 유지. 만료분 자동 정리 |
| 이메일 인증 | ❌ 미구현 (H5) |
| 비밀번호 변경 | ✅ 현재 비밀번호 확인 + **다른 기기 전체 로그아웃** + 최소 8자 |
| 비밀번호 **분실** 시 재설정 | ✅ 운영자 발급 일회용 코드 (해시 저장·일회용·24h 만료·전체 세션 무효화) |
| 회원 탈퇴 / 데이터 삭제 | ✅ `DELETE /api/auth/me` + 화면(`/account`). 계정·동의·제출·학습기록 하드 삭제 |
| 민감정보 로깅 | ✅ 확인 결과 password/token/request body를 로깅하는 코드 없음 |
| 업로드 영상 미저장 + EXIF 제거 | ✅ 기존 구현 |
| 접속기록(감사 로그) | ❌ 미구현 — 법적 요건 확인 필요 (BLOCKER-3). 학습 이벤트 로그는 목적이 다르다(관찰용) |
| secret이 저장소에 없음 | ✅ 전체 history 스캔 완료, 실 키 0건 |

### 7.1 로깅 점검 결과
`logger.*` 호출 전수 확인 결과 password/token/credential/request body를 기록하는 지점 없음.
기록되는 것은 case_id, 파일 경로, 모델 실패 사유뿐. **추가 조치 불필요.**

---

## 8. Data / License checklist

| 항목 | 상태 |
|---|---|
| 실제 의료영상이 저장소에 없음 | ✅ history 전체 확인 (`.dcm/.nii/.npy` 0건) |
| 모델 가중치 없음 | ✅ (`.pth` 등 0건) |
| DB·secret·개인정보 없음 | ✅ |
| VS-SEG 데이터셋 출처 표기 | ✅ README + `content/diseases/*.json` references |
| **VS-SEG 이용 조건 확인** | ❌ **NEEDS_LICENSE_REVIEW** (BLOCKER-1) |
| **VS_Seg 모델 가중치 이용 조건** | ❌ **NEEDS_LICENSE_REVIEW** (BLOCKER-1) |
| 문헌 콘텐츠 | ✅ 직접 인용 아닌 요약 + 문장별 출처 + 확인일 |

---

## 9. Model limitations

- 뇌 MRI VS-SEG: test 10명 중 8명 검출. 평균 Dice 0.7304 / 중앙값 0.9353.
- 미검출 2건은 threshold 0.5→0.001로도 개선 안 됨 → 원인 분석 미완.
- 예측은 **미리 계산된 sidecar**로만 서비스. 모델 교체 시 수동 재계산 필요.
- **모델 예측은 채점에 절대 관여하지 않는다.** VS-SEG-204(AI 완전 실패)로 회귀 테스트 고정.

---

## 10. Expert review 필요 (NEEDS_EXPERT_REVIEW)

| 항목 | 내용 |
|---|---|
| E1 | 6케이스 전부 `case_findings` 미작성. 전문가가 작성해야 하며 **Claude가 임의 생성하지 않는다** |
| E2 | 케이스 난이도(difficulty) 판정 |
| E3 | Dice 임계값 0.60/0.15의 교육적 타당성 — 값은 `app/scoring_config.py` 로 분리했고 응답에 `not_yet_educationally_validated` 를 함께 내려보낸다. **값 자체의 검증은 여전히 필요** |
| E4 | spatial feedback 문구가 학습자에게 오해를 주지 않는지 (문구는 `app/feedback.py` 에 모여 있고, 의료 어휘 금지를 테스트로 고정했다) |

---

## 11. Regulatory review 필요 (NEEDS_REGULATORY_REVIEW)

| 항목 | 내용 |
|---|---|
| R1 | 화면 5(개인 영상 분석) 활성화 시 의료기기 SW 해당 여부 — **이번 범위에서 비활성 유지** |
| R2 | 민감정보 처리자의 접속기록 보관 의무 범위·기간 |
| R3 | 회원 탈퇴 시 동의 이력 보존 vs 완전 삭제 (증빙 의무와 파기 의무의 충돌) |

---

## 12. Closed Beta readiness

| 게이트 | 상태 |
|---|---|
| 보안 최소선 (C1~C4) | ✅ 완료 |
| 학습 피드백이 점수 이상을 제공 | ✅ 완료 (geometry 한정) |
| 운영자가 콘텐츠를 다룰 수 있음 | ✅ 완료 (최소 CMS) |
| 케이스 10개 이상 | 🟡 **후보 24건 선별 완료** (좌우 12:12, 크기 8:8:8) — 육안 검수 후 등록하면 30케이스 |
| 케이스별 전문가 해설 | 🔲 전문가 검토 대기 (E1) |
| 사용 데이터 측정 | ✅ 완료 (최소 이벤트 로그) |
| 라이선스 확인 | ❌ BLOCKER-1 |

**현재 판정: 내부 테스트 가능 / 외부 Closed Beta는 BLOCKER-1 해소 후.**

---

## 변경 로그
- 2026-09-08: Phase 1 최초 작성 (커밋 `ef56005` 기준 전체 점검)
- 2026-09-08: Phase 2 완료 — C1~C4 해소. 테스트 241 → 270.
  신규: `app/config.py`, `app/cors.py`, `app/rate_limit.py`, `app/account.py`
- 2026-09-08: Phase 3 완료 — H1·H6 해소. 테스트 270 → 292.
  신규: `app/feedback.py`, `app/scoring_config.py`. 계약 v0.5(`spatial_feedback`, `evaluation.thresholds`)
- 2026-09-08: Phase 4 완료 — H2 구조 해소. 테스트 292 → 307.
  마이그레이션 `e81bbce560b5`(cases.findings_status, **추가 전용**).
  신규 문서 `docs/CONTENT_GUIDELINES.md`.
  부수 수정: `verify_cases.py` / `remove_cases.py` 가 마이그레이션을 보장하지 않아
  컬럼 추가 시 원시 에러로 죽던 문제 해결 (import_cases 와 동일하게 맞춤).
- 2026-09-08: Phase 5 완료 — H3 해소. 테스트 307 → 339 (admin 32개 중 권한 격리 10개).
  마이그레이션 `e93378ca7e48`(users.is_admin, cases.is_active/difficulty, **추가 전용**).
  신규: `app/routers/admin.py`, `scripts/grant_admin.py`, `frontend/.../AdminCasesView.vue`.
- 2026-09-08: Phase 6~8 완료 — M3·M4·H7 해소. 테스트 339 → 382.
  마이그레이션 `0fc6767cf5ba`(learning_events, **신규 테이블만 추가**).
  신규 스크립트: `analyze_case_candidates.py`, `evaluate_model.py`, `learning_report.py`.
  신규 모듈: `app/analytics.py`.
  **발견**: 현재 6케이스는 우측 5/좌측 1 로 편향돼 있고, AI 미검출 1건은 최소 병변이다
  (small 구간 검출률 0.5 vs medium/large 1.0). 콘텐츠 확장 시 좌측·소형 병변을 우선 확보할 것.
- 2026-09-08: H4 서버측 토큰 폐기 완료. 테스트 382 → 396.
  마이그레이션 `72c54e42f82a`(revoked_tokens, **신규 테이블만**).
  부수 발견·수정: 401 핸들러가 `logout()` 을 부르면 무효 토큰으로 서버를 다시 호출해
  401 루프가 될 수 있었다 → `clearSession()` 으로 분리.
- 2026-09-08: **버그 수정** — 비활성 케이스가 재도전 경로로 새고 있었다.
  `POST /wrong-notes/{id}/retry` 가 `is_active` 를 보지 않아, 운영자가 내린 케이스로
  계속 채점이 이뤄졌다(케이스를 내리는 이유가 "기준 마스크에 문제 있음"일 수 있으므로
  잘못된 학습 결과로 이어질 수 있는 문제). 복습노트 목록도 함께 필터.
  교차 엔드포인트 불변조건을 `tests/test_case_visibility.py` 로 고정. 테스트 396 → 405.
  부수 수정: 테스트 정리 픽스처가 learning_events/revoked_tokens 를 비우지 않아
  테스트 간 데이터가 누적되고 있었다 (대량 delete 는 ORM cascade 를 타지 않는다).
- 2026-09-08: **화면 2 slice 탐색 구현** — 동작하지 않던 슬라이더를 실제 뷰어로 교체.
  `GET /api/cases/{id}` 가 `slices` + `representative_slice` 를 내려보낸다.
  **마스크 정보는 노출하지 않는다**(정답 위치이므로). ROI·채점은 대표 slice 고정.
  부수 버그 수정: `RoiCanvas` 가 imageUrl 변경 시 그린 ROI 를 지워, slice 를 넘겨보고
  돌아오면 작업이 사라졌다 → `clearOnImageChange` 로 분리. 테스트 405 → 414.
- 2026-09-08: **화면 전수 점검** — 죽은 필터 탭 4개 제거, 개발자 메모/CORS 안내가
  사용자 화면에 노출되던 것 2건 수정, 채점 후 다음 행동 제시로 학습 루프를 닫음.
  UI 문자열에 내부 용어가 새지 않도록 주의할 것.
- 2026-09-08: **PostgreSQL 이식성 검증 완료** (docker postgres:16-alpine).
  마이그레이션 6단계 upgrade/downgrade, 모델↔스키마 드리프트 없음, 전체 414 테스트 통과.
  **발견·수정**: 테스트 1건이 대량 삭제(ORM cascade 우회)를 써서 PostgreSQL FK 제약에 걸렸다.
  앱의 실제 탈퇴 경로는 ORM 삭제라 정상이었으나, 테스트를 실제 경로에 맞췄다.
  `MEDISCAN_TEST_DATABASE_URL` 로 테스트 DB 를 바꿔 돌릴 수 있게 했다.
- 2026-09-08: **프론트 단위 테스트 도입** (vitest + @vue/test-utils, 22개).
  이번 세션에 프론트를 6번 바꿨는데 단위 테스트가 0개였다. 개수가 목적이 아니라
  빈/실패/경계 상태와 "없는 것을 있는 것처럼 보여주지 않는지"를 고정했다.
  성능 실측: 케이스 목록 13ms/6케이스 — 목표 30케이스에서도 문제 없음.
- 2026-09-08: **배포 준비** — `DATABASE_URL` 을 production 필수로 강제.
  미설정 시 컨테이너 안 로컬 SQLite 로 조용히 떨어져 **재배포마다 학습 데이터가 사라지는**
  구조였다 (겉보기에는 정상 동작하므로 눈치채기 어렵다).
  `scripts/backup_db.py` 신규 (SQLite 온라인 백업 API / pg_dump, 보관 개수 관리).
  `docs/DEPLOYMENT.md` 신규 — 체크리스트·한계·백업·사고 대응 런북.
- 2026-09-08: **비밀번호 정책·변경** — 최소 길이 정책이 아예 없어 한 글자로도 가입이 됐다.
  8자 최소 + `POST /api/auth/password`(현재 비밀번호 확인, **다른 기기 전체 로그아웃**).
  `users.sessions_valid_from` 으로 "모든 기기 로그아웃"을 구현 — 개별 토큰 폐기로는
  다른 기기 세션을 끊을 수 없다. 테스트 417 → 433.
  구현 중 발견: `iat`(초 단위)와 컷오프(마이크로초) 정밀도가 달라 새로 발급한 토큰이
  즉시 거부됐다 → 컷오프를 초 단위로 내림.
- 2026-09-08: **반쪽 기능 완결** — 운영자가 `difficulty` 를 설정할 수 있는데 학습자 화면에는
  전혀 반영되지 않고 있었다(설정해도 아무 일도 안 일어남). 목록·상세 응답에 노출하고
  뱃지·필터를 붙였다. **미지정은 표시하지 않는다** — 추측해서 채우지 않으므로
  "표시가 없다 = 아직 판정 전"이 정확한 의미다. 테스트 433 → 435, 프론트 22 → 25.
- 2026-09-08: **학습 지표를 운영자 화면에 노출.** 이벤트를 수집하면서도 볼 방법이 CLI 뿐이라
  운영자가 서버 접속 없이는 학습이 일어나는지 알 수 없었다. 집계 로직을
  `app/learning_stats.py` 로 옮겨 **CLI 와 API 가 같은 함수를 쓰게** 했다
  (두 곳에서 따로 계산하면 숫자가 갈라진다). 응답에 개인 식별자가 없음을 테스트로 고정.
- 2026-09-08: **로깅 설정** — 앱 곳곳에 `logger.info` 를 써뒀는데 **아무 데도 출력되지
  않고 있었다**(root 기본 레벨 WARNING). 로그를 남기는 코드를 써놓고 실제로는 남기지 않는
  상태. `app/logging_config.py` 로 text/json 포맷과 레벨을 설정하고 기동 시 적용.
  민감정보가 로그에 들어가지 않는지 소스 검사 테스트로 고정.
- 2026-09-08: **비밀번호 재설정** — 분실 시 계정과 학습 이력을 영구히 잃는 상태였다.
  메일 발송 수단이 없어도 되도록 **운영자 발급 일회용 코드** 방식으로 구현.
  코드는 SHA-256 해시로만 저장하고 로그에도 남기지 않는다. 일회용·24시간 만료,
  성공 시 전체 세션 무효화. 실패 사유를 구분하지 않아 가입 여부를 캐낼 수 없다.
  테스트 450 → 471.
- 2026-09-08: **콘텐츠 확장이 막혀 있지 않음을 확인.** 원본 데이터셋 242케이스가 로컬에 있다.
  볼륨을 만들지 않고 편측성·병변 크기만 재는 스크리닝 도구(`screen_vs_seg_dataset.py`)를 만들어
  238케이스를 판독했다 (좌 108 / 우 130, GT voxel 330~44,230).
  **균형 잡힌 후보 24건 선별**: 좌우 12:12, 크기 small/medium/large 8:8:8.
  등록은 육안 검수를 포함한 기존 4단계 파이프라인을 그대로 거쳐야 하므로 **사람의 검수 대기**.
  (첫 추천 로직은 "작은 것부터"만 골라 24건 전부가 최소 크기로 나왔다 — 반대 편향을
  만든 것을 발견하고 크기 계층 균형을 추가했다.)
- 2026-09-08: **화면 5 흐름 개선** — 업로드·ROI·요청을 다 한 뒤에야 "준비 중"을 만나던
  헛수고를 제거. `GET /api/analyze/availability` 로 **미리** 확인하고 요청 버튼을 막는다.
  하드코딩된 "준비 중" 문구도 서버 상태 기반으로 교체(모델이 준비되면 거짓말이 되므로).
  E2E 회귀 3건 수정: 비밀번호 정책 변경 시 놓친 스크립트, 실패를 늦게 알리던 가드 부재,
  토큰 키 오기입.
(이후 Phase 완료 시마다 여기에 추가한다)
