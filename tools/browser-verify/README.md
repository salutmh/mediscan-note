# 브라우저 검증 스크립트

**주의: 이것은 단위 테스트가 아니라 수동 검증 자동화 스크립트다.**
pytest/vitest 스위트는 아직 없다 (`review_bundle.md` 7절 참고).

헤드리스 Chrome 을 DevTools Protocol(CDP)로 직접 몰아서 실제 화면을 렌더링하고,
스크린샷을 남기며, 콘솔 에러를 수집한다. Node 22+ 내장 WebSocket 만 쓰므로 추가 의존성이 없다.

| 스크립트 | 하는 일 |
|---|---|
| `user-flow.mjs` | 신규 가입 → 케이스 목록 → 틀리게 제출 → 복습노트 적재 → 재도전 성공 → 복습노트에서 제거 → 진행현황 확인 |
| `screenshot-all.mjs` | 화면 0~7 전부 촬영 (동의 폼, 판독, 결과 비교, 복습노트, 영상 업로드·분석, 진행현황, 모바일 폭) |

## 실행

1. 백엔드와 프론트를 띄운다.

```bash
cd backend && uvicorn app.main:app --reload --port 8010   # :8010
cd frontend && npm run dev                     # :5173
```

2. 헤드리스 Chrome 을 디버깅 포트와 함께 띄운다. (경로는 환경에 맞게)

```bash
# Windows
"C:/Program Files/Google/Chrome/Application/chrome.exe" \
  --headless=new --remote-debugging-port=9333 \
  --user-data-dir=/tmp/mediscan-verify-profile \
  --no-first-run --no-default-browser-check --no-sandbox about:blank

# macOS
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --remote-debugging-port=9333 \
  --user-data-dir=/tmp/mediscan-verify-profile about:blank
```

3. 스크립트를 실행한다. (인자: `<출력폴더> <디버깅포트>`)

```bash
node tools/browser-verify/user-flow.mjs ./out/flow 9333
node tools/browser-verify/screenshot-all.mjs ./out/shots 9333
```

## 참고

- 스크립트가 **실제로 API 에 가입**해서 진짜 토큰을 받는다 (백엔드가 서명·만료를 검증하므로
  위조 토큰은 통하지 않는다). 실행할 때마다 `flow<timestamp>@example.com` 계정이 DB에 쌓인다.
- ROI 는 캔버스에 PointerEvent 를 디스패치해 실제 브러시 궤적을 만든다.
- **재도전 단계는 기준 마스크 모양을 따라 칠한다.** 예전처럼 고정 반지름 원으로 칠하면
  실제 병변이 불규칙해서 Dice 가 0.63 언저리(임계값 0.60)에 머물러 반복 실행이 불안정했다.
  지금은 첫 제출 응답에서 `reference_mask_url` 을 받아 마스크를 픽셀로 읽고,
  **브러시 반지름만큼 침식한 영역만 가로 스캔라인으로 칠한다** — 붓끝이 GT 밖으로 나가지 않아
  과도하게 칠하지 않고, Dice 0.93 수준이 재현된다 (VS-SEG-202 기준 3회 반복 모두 0.9387).
  **채점 임계값은 바꾸지 않았다.** 바뀐 것은 "사용자가 얼마나 정확히 칠하는가" 쪽이다.
- `user-flow.mjs` 는 마지막에 검증 결과를 요약하고, 재도전이 `match` 가 아니거나
  Dice 가 0.85 미만이거나 콘솔 에러가 있으면 **exit code 1** 로 끝난다 (CI 에 걸기 좋다).
- 업로드 테스트용 영상은 페이지 안에서 캔버스로 생성한다 (네트워크·파일시스템 의존 없음).
- 마지막에 콘솔 에러 목록을 출력한다. 정상이면 "콘솔 에러 없음".
