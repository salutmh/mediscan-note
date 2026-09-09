# 브라우저 검증 스크립트

**주의: 이것은 단위 테스트가 아니라 수동 검증 자동화 스크립트다.**
백엔드 단위 테스트는 `backend/` 의 pytest 414개이고, **프론트 단위 테스트(vitest)는 아직 없다**
(`review_bundle.md` 7절 참고).

헤드리스 Chrome 을 DevTools Protocol(CDP)로 직접 몰아서 실제 화면을 렌더링하고,
스크린샷을 남기며, 콘솔 에러를 수집한다. Node 22+ 내장 WebSocket 만 쓰므로 추가 의존성이 없다.

| 스크립트 | 하는 일 |
|---|---|
| `user-flow.mjs` | 신규 가입 → 케이스 목록 → 틀리게 제출 → 복습노트 적재 → 재도전 성공 → 복습노트에서 제거 → 진행현황 확인 |
| `consent-and-sns.mjs` | 화면 0: 동의 체크박스(실제 마우스 클릭) + SNS 개발용 예시 로그인 3종 + 이메일 가입 |
| `slice-navigation.mjs` | 화면 2 slice 탐색: 영상이 실제로 바뀌는가, **slice 를 넘겨도 그리던 ROI 가 유지되는가**, 대표 slice 밖에서 입력이 잠기는가 |
| `screenshot-all.mjs` | 화면 0~7 전부 촬영 (동의 폼, 판독, 결과 비교, 복습노트, 영상 업로드·분석, 진행현황, 모바일 폭) |

## 실행

> ⚠️ **E2E 를 반복 실행하면 가입 요청 수 제한(기본 시간당 10회)에 걸린다.**
> 검증용으로 띄울 때는 제한을 끄거나 넉넉히 준다:
> ```bash
> MEDISCAN_RATE_LIMIT=0 uvicorn app.main:app --port 8010
> # 또는 MEDISCAN_RATE_LIMIT_MULTIPLIER=20
>
> 둘 다 **개발 전용**이다. `MEDISCAN_ENV=production` 에서는 기동이 거부된다
> (앞단에서 제한한다면 `MEDISCAN_RATE_LIMIT=external`). 배포 환경에 가져가지 않는다.
> ```
> (제한 자체를 검증하는 것은 `backend/tests/test_rate_limit.py` 가 한다.)

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
node tools/browser-verify/consent-and-sns.mjs ./out/consent 9333
node tools/browser-verify/slice-navigation.mjs ./out/slices 9333
node tools/browser-verify/screenshot-all.mjs ./out/shots 9333
node tools/browser-verify/a11y-audit.mjs ./out/a11y 9333
node tools/browser-verify/responsive-check.mjs ./out/responsive 9333
# 케이스 후보 기술 검수 화면 (운영자 계정이 먼저 필요하다)
#   python -m scripts.grant_admin --email <이메일>
node tools/browser-verify/case-review.mjs ./out/review 9333 <운영자이메일>
node tools/browser-verify/error-paths.mjs ./out/errors 9333
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


---

## a11y-audit.mjs — 접근성 기본 점검

실제로 렌더된 DOM 에서 **기계로 확실히 알 수 있는 것만** 본다:
이미지 대체 텍스트, 버튼·링크의 읽을 이름, 입력의 label, canvas 대체 설명,
제목 단계 건너뜀, `<html lang>`.

색 대비나 "키보드만으로 ROI 를 그릴 수 있는가" 는 **판단하지 않는다** — 사람이 봐야 한다.
지적이 있어도 종료코드는 0 이다 (빌드를 막는 도구가 아니라 검토할 목록을 만드는 도구다).

출력에 `[입력N 버튼N 이미지N 캔버스N]` 을 함께 찍는다.
**"0건 지적"이 제대로 본 결과인지 화면이 안 그려진 탓인지 구분하기 위해서다.**
회원가입 화면에서 입력이 10개로 나오지 않으면 점검기가 화면을 못 본 것이다.

### 이 도구를 만들면서 두 번 틀렸던 것 (같은 실수 반복 방지)

1. 로그인한 상태로 `/login` 을 열어서 `/cases` 로 튕겼다 → 입력이 가장 많은 화면이
   통째로 점검에서 빠졌다. **로그인 화면은 로그아웃 상태에서 먼저 본다.**
2. `?tab=signup` 으로 탭이 바뀔 거라 가정했다 → 실제로는 버튼 클릭이라
   로그인 탭을 두 번 본 꼴이었다. **탭은 눌러서 전환한다.**

둘 다 "통과" 로 보였다는 점이 핵심이다. 점검 도구는 무엇을 봤는지 함께 내야 한다.


---

## responsive-check.mjs — 좁은 화면 점검

휴대폰(390) / 태블릿 세로(768) / 태블릿 가로(1024) 폭에서 **기계로 확실히 알 수 있는 깨짐**만 본다:
가로 스크롤, 화면 밖으로 삐져나온 요소, 누르기 힘든 크기(32px 미만)의 버튼, 판독 캔버스 크기.

"보기 좋은가"는 판단하지 않는다 — 지적이 있으면 스크린샷을 남기니 사람이 본다.
지적이 있어도 종료코드는 0 이다.

화면 밖 요소는 **조상이 이미 넘쳤으면 자식을 세지 않는다.** 그러지 않으면 원인 하나가
수십 개 항목으로 불어나 목록이 쓸모없어진다.

### 처음 돌렸을 때 나온 것 (2026-09-09)

레이아웃 자체는 390px 까지 멀쩡했다 — 가로 스크롤도, 화면 밖 요소도 0건이었다.
실제 문제는 **터치 대상 크기**였고, 그중 판독훈련의 slice 이동 화살표(`‹` `›`)가
27px 폭이었던 것이 핵심이다. 핵심 조작에서 헛누르면 학습 흐름이 끊긴다.


---

## case-review.mjs — 케이스 후보 기술 검수 화면

**가장 중요한 검사: TECH_PASS 를 눌러도 전문가 검수와 활성화 상태가 바뀌지 않는가.**
기술 검수가 활성화로 번지면 검수되지 않은 GT 가 학습자의 채점 기준이 된다.
화면과 서버 응답 **양쪽에서** 확인한다 (화면만 바뀐 것이 아닌지).

함께 확인: 인증 뒤에 있는 검수 시트가 실제로 로드되는가(blob), 판단이 새로고침 후에도
남는가, 헤더 현황이 즉시 갱신되는가, 필터·단축키가 동작하는가.

운영자 계정이 필요하다. **자동 승격은 하지 않는다** — 웹으로 스스로 운영자가 되는 경로를
만들지 않는다는 규칙 때문이다.

### 상태에 의존하지 않게 만든 것

검수 결과는 파일(`review_results.json`)에 남으므로 **이전 실행 상태를 물려받는다.**
처음에는 "미검수 23건" 같은 절대값으로 검사해서 두 번째 실행부터 실패했다 —
그건 제품 문제가 아니라 검사가 상태에 의존한 것이다. 지금은 **변화량**으로 본다.


---

## error-paths.mjs — 오류 경로

정상 흐름은 다른 스크립트가 본다. 여기서는 **잘못됐을 때 사용자가 무엇을 보는지**를 본다:

| 상황 | 확인하는 것 |
|---|---|
| 없는 케이스로 직접 진입 | 안내가 나오고 **돌아갈 길이 있는가** (막다른 화면이 아닌가) |
| 로그인 실패 | 사람이 읽을 수 있는가 · **가입 여부를 흘리지 않는가** · 에러 코드가 노출되지 않는가 |
| 무효 토큰 | 로그인으로 돌려보내는가 · 토큰을 지우는가 · **401 재진입 루프가 없는가** |
| 백엔드 연결 실패 | **개발자용 실행 안내가 아니라 사용자용 문구**가 나오는가 |
| 권한 없이 운영자 화면 | 왜 안 되는지 · 어떻게 얻는지 알려주는가 |
| 빈 제출 | 입력 없이 제출이 막혀 있는가 (헛수고 방지) |

401/403 은 이 검증이 **일부러 만드는** 상황이라 콘솔 에러 집계에서 제외한다.
그 외의 콘솔 에러는 진짜 문제로 본다.

백엔드 연결 실패는 **실제 서버를 죽이지 않고** `window.fetch` 를 실패시켜 재현한다 —
같은 세션의 다른 검증에 영향을 주지 않기 위해서다.
