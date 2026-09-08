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
| 동의 | 필수 5 + 선택 1, **append-only** 이력(버전·시각) | `app/routers/auth.py:49`, `app/models.py:38` |
| 채점 | **reference mask 전용** Dice/IoU/location_score. 보정 없음 | `app/grading.py:190`, `app/masks.py:103` |
| 채점 거부 | 기준 마스크 없으면 422 `CASE_NOT_GRADABLE` + **이력 미생성** | `app/routers/cases.py:41` |
| AI 분리 | sidecar 우선 → volume 모델은 2D 호출 차단 → 실패해도 예외 삼킴 | `app/grading.py:79` |
| 학습 상태 | `has_matched`(누적) / `needs_review`(최신 제출 기준) 두 축 | `app/repository.py:50` |
| 해설 3층 | `case_facts`/`disease_info`/`case_findings`, `content_levels`는 **파생 계산** | `app/explanations.py:35` |
| 업로드 검증 | 크기→포맷→손상→픽셀수→region, 미저장 + EXIF 제거 | `app/uploads.py` |
| 화면 5 | 지어내지 않고 `model_unavailable`, 데모는 flag OFF 기본 | `app/routers/analyze.py:74` |
| 스키마 | Alembic이 기준, 기동 시 자동 upgrade + 레거시 DB 감지 | `app/db.py:47` |
| 정적 자산 | 요청 주소 기준 절대 URL 생성 | `app/main.py:32` |
| 테스트 | **382개 통과** (22개 파일) | `backend/tests/` |

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
| H4 | 서버측 토큰 폐기 없음 | 로그아웃은 클라이언트 삭제만, 유출 토큰 최대 7일 유효 | 🔲 미착수 |
| H5 | 이메일 인증 / 비밀번호 재설정 없음 | 남의 이메일로 가입 가능, 비번 분실 시 계정 영구 상실 | 🔲 미착수 |
| H6 | 채점 임계값 하드코딩 | ~~상수~~ → `app/scoring_config.py` 분리 + 응답에 `validation_status` 노출 | ✅ DONE |
| H7 | 학습 분석 이벤트 없음 | ~~없음~~ → `learning_events` + `scripts/learning_report.py`. **개인정보 미수집**(이메일·IP·ROI 없음) | ✅ DONE |

---

## 5. Medium

| # | 항목 |
|---|---|
| M1 | 구조적 로깅 설정 없음 (현재 민감정보 로깅은 확인 결과 **없음** — 7.1 참고) |
| M2 | `_grade_by_points` 개발용 근사 채점 경로가 코드에 남아 있음 (`MEDISCAN_ALLOW_APPROX_GRADING`로만 동작) |
| ~~M3~~ | ~~난이도 메타데이터 없음~~ → `cases.difficulty` 추가 (Phase 5). **자동 판정하지 않고 전문가 검토 대상**(E2) |
| ~~M4~~ | ~~모델 평가 도구 없음~~ → `scripts/evaluate_model.py` (검출률·크기 구간별·버전 비교, Phase 7) |
| M5 | 예측 sidecar 수동 재계산 |
| M6 | 동시성/부하 미검증, PostgreSQL 실검증 없음 |

## 6. Low

| # | 항목 |
|---|---|
| ~~L1~~ | ~~`explanations.py` docstring stale~~ → Phase 4에서 수정 완료 |
| L2 | `cases.reference_shape` 레거시 컬럼 (근사 채점 전용) |
| L3 | `frontend/public/icons.svg` — Vite 템플릿 잔재, 어디서도 참조되지 않음 |

---

## 7. Security checklist

| 항목 | 상태 |
|---|---|
| production에서 SECRET_KEY 강제 | ✅ 미설정·dev값·32자 미만이면 기동 실패 |
| CORS origin 제한 | ✅ production 은 `MEDISCAN_CORS_ORIGINS` 필수 + 와일드카드 금지 |
| 인증 엔드포인트 rate limit | ✅ signup/login/social-login/탈퇴. 학습 흐름은 제외 |
| 비밀번호 해싱 | ✅ scrypt (n=2^14) |
| 토큰 서명·만료 | ✅ HMAC-SHA256 + exp |
| 서버측 토큰 폐기 | ❌ 미구현 (H4) |
| 이메일 인증 | ❌ 미구현 (H5) |
| 비밀번호 재설정 | ❌ 미구현 (H5) |
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
| 보안 최소선 (C1~C4) | ✅ 완료 (테스트 270개) |
| 학습 피드백이 점수 이상을 제공 | ✅ 완료 (geometry 한정) |
| 운영자가 콘텐츠를 다룰 수 있음 | ✅ 완료 (최소 CMS) |
| 케이스 10개 이상 + 해설 | 🔲 전문가 검토 대기 (E1) |
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
(이후 Phase 완료 시마다 여기에 추가한다)
