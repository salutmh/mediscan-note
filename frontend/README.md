# frontend

Vite + Vue 3 프로젝트. `docs/api-spec.md` 의 API 계약을 그대로 따라 화면을 붙인다.

## 실행

```
npm install                  # 최초 1회
npm run dev                  # http://localhost:5173
```

백엔드가 함께 떠 있어야 한다 (`backend/` 에서 `uvicorn app.main:app --reload`).
호출 주소는 `.env.development` 의 `VITE_API_BASE` 한 곳에서만 관리한다
(mock 정적 JSON으로 돌리려면 `/mock` 으로 바꾸면 화면 로직은 그대로 — api-spec.md 5절).

## 테스트

```
npm test          # vitest run (한 번 실행)
npm run test:watch
```

**개수를 늘리는 것이 목적이 아니다.** 실제로 깨질 수 있는 것만 고정한다:
빈/실패/경계 상태, 그리고 화면이 "없는 것을 있는 것처럼" 보여주지 않는지.

| 파일 | 무엇을 지키나 |
|---|---|
| `views/CaseListView.test.js` | 케이스가 없는 부위를 탭으로 만들지 않는다. 학습완료/복습필요 동시 표시. 조회 실패·빈 목록에서 화면이 깨지지 않는다 |
| `views/ReadingView.test.js` | slice 탐색(영상 전환·입력 잠금·**ROI 유지 설정**), 채점 후 다음 행동, slice 없는 케이스, 다음 대상 조회 실패 |
| `views/AccountView.test.js` | 비밀번호 변경(확인 불일치·짧은 비밀번호는 서버까지 가지 않는다, 성공 시 토큰 교체), 회원 탈퇴(무엇이 지워지는지 먼저 보여준다, 한 번에 삭제되지 않는다) |
| `views/AnalyzeView.test.js` | 준비 상태를 **하드코딩하지 않는다**, 불가능하면 업로드 전에 이유를 알리고 요청 버튼을 막는다, **확인 실패 시에는 잠그지 않는다** |
| `stores/auth.test.js` | 로그아웃이 **서버에 토큰 폐기를 요청**한다. 서버 실패 시에도 로컬 세션은 비운다. `clearSession` 은 서버를 부르지 않는다(401 재진입 방지) |

브라우저에서 실제로 도는지는 `tools/browser-verify/` 의 E2E 가 본다 (서버 + Chrome 필요).
여기 단위 테스트는 그 앞단에서 **빠르게** 경계 상황을 잡는 역할이다.

## 구조

```
src/
  api/
    client.js       공통 fetch 유틸. 토큰 자동 첨부(Authorization: Bearer), 에러 정규화(ApiError), 401 처리
    endpoints.js    api-spec.md 의 엔드포인트를 함수 1:1로 대응
  stores/auth.js    로그인 상태 + 토큰(localStorage). Pinia 없이 reactive 하나로 충분한 규모
  router/index.js   라우트 + 토큰 없으면 화면 0으로 보내는 가드
  components/
    ConsentForm.vue     동의 체크박스 (항목/문구는 GET /api/consents/current-version 응답을 렌더링)
    RoiCanvas.vue       ROI 입력 위젯 (클릭/브러시/지우개 + mask_png_base64 생성) — 화면 2·5 공용
    ResultCompare.vue   화면 3 — grade 뱃지(일치/부분 일치/불일치) + 수치 + 사용자/기준 마스크 합성 오버레이
    ExplanationPanel.vue 화면 4 — explanation 표시
  views/
    LoginView.vue      화면 0 — 로그인 / 회원가입 / SNS 간편가입 + 필수 동의
    CaseListView.vue   화면 1 — 케이스 목록 (부위 필터 + 학습완료/복습필요/미시도 뱃지)
    ReadingView.vue    화면 2 — 판독 훈련 + 제출 후 화면 3·4. 복습노트 재도전에도 재사용
    WrongNotesView.vue 화면 6 — 복습노트 목록 + 재도전 링크 (파일·라우트명은 API 계약대로 wrong-notes 유지)
    AnalyzeView.vue    화면 5 — 내 영상 업로드 AI 분석 (disclaimer 상단 고정)
    MyProgressView.vue 화면 7 — 진행현황 (집계 엔드포인트가 없어 프론트에서 계산)
public/            (케이스 영상·마스크는 백엔드가 서빙한다 — backend/app/static/)
                   API 가 절대 URL 로 내려주므로 프론트는 경로를 하드코딩하지 않는다.
```

## 진행 상황

- [x] 화면 0 — 로그인/회원가입 + 필수 동의 5개 / 선택 1개
- [x] 화면 1 — 케이스 목록
- [x] 화면 2 — 판독 훈련 (ROI 입력 + 제출, 제출 후 입력 잠금)
- [x] 화면 3 — 결과 비교 (grade 뱃지 일치/부분 일치/불일치 + 사용자=파랑/기준=초록/겹침=노랑 오버레이)
- [x] 화면 4 — 학습 해설 (submit 응답의 explanation)
- [x] 화면 6 — 복습노트 + 재도전 (POST /api/wrong-notes/{id}/retry)
- [x] 화면 5 — 사용자 영상 AI 분석 (POST /api/analyze)
- [x] 화면 7 — 마이 진행현황

## 라우트

| 경로 | 화면 |
|---|---|
| `/login` | 0 — 로그인/회원가입 |
| `/cases` | 1 — 케이스 목록 |
| `/cases/:caseId` | 2 (+ 제출 후 3·4) — 판독 훈련 |
| `/wrong-notes` | 6 — 복습노트 |
| `/wrong-notes/:caseId/retry` | 6 재도전 — 화면 2를 재사용, 제출만 retry 엔드포인트로 |
| `/analyze` | 5 — 내 영상 AI 분석 |
| `/progress` | 7 — 진행현황 |

## 남은 논의거리 (api-spec.md 6절 관련)

- `roi.type` 값 목록: 스펙에 `brush_mask` 만 정의돼 있어 클릭만 한 경우도 마스크를 함께 보내고
  `brush_mask` 로 고정했다.
- 화면 5의 `region` 은 스펙(2-6) 그대로 `{ type, points }` 만 보낸다. 모델이 마스크를 필요로 하면
  2-3처럼 `region.mask_png_base64` 를 스펙에 추가해야 한다.
- 화면 7의 "부위별 일치율"은 제출 이력이 필요해서 지금은 `has_matched` 기준 학습완료율만 계산한다.
  집계 엔드포인트가 정해지면 이 화면만 교체하면 된다.
