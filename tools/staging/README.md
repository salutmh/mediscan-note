# 로컬 스테이징 시뮬레이션

**배포와 같은 형태를 로컬에 세운다.** 지금까지의 E2E 7종은 전부 Vite dev 서버로 돌아서,
배포에서만 드러나는 것들을 한 번도 확인하지 못했다.

## dev 서버와 무엇이 다른가

| | Vite dev | 실제 배포 |
|---|---|---|
| API 주소 | 실행할 때 읽는다 | **빌드 시점에 번들로 박힌다** |
| 출처 | 느슨하다 | **다르다 — CORS 가 실제로 필요하다** |
| 자산 URL | 요청 주소 기준 | `MEDISCAN_PUBLIC_BASE` 기준 — **서명이 그 주소로 걸린다** |
| 깊은 경로 새로고침 | dev 서버가 알아서 처리 | **정적 호스팅에 fallback 설정이 필요하다** |
| DB | 로컬 SQLite | 원격 PostgreSQL — **유휴 연결이 끊긴다** |

마지막 두 개는 배포 후에야 드러난다. 새로고침하면 화면이 사라지고, 한산한 시간대에 500 이 난다.

## 세우기

```bash
# 0) PostgreSQL (스테이징 DB 를 흉내낸다)
docker run -d --name mediscan-staging-db \
  -e POSTGRES_PASSWORD=test -e POSTGRES_DB=mediscan -p 55433:5432 postgres:16-alpine

# 1) 스키마 + 케이스
cd backend
DATABASE_URL="postgresql+psycopg2://postgres:test@localhost:55433/mediscan" \
  python -c "from app.db import init_db; init_db()"
DATABASE_URL="postgresql+psycopg2://postgres:test@localhost:55433/mediscan" \
  python -m scripts.import_cases data/vs_seg_cases/manifest.json

# 2) API — 배포처럼 PUBLIC_BASE 와 CORS 를 명시한다
MEDISCAN_RATE_LIMIT=0 \
MEDISCAN_PUBLIC_BASE="http://127.0.0.1:8010" \
MEDISCAN_CORS_ORIGINS="http://localhost:4173" \
DATABASE_URL="postgresql+psycopg2://postgres:test@localhost:55433/mediscan" \
  python -m uvicorn app.main:app --host 127.0.0.1 --port 8010

# 3) 프론트 — **실제 production 빌드**를 만든다
cd ../frontend
VITE_ALLOW_LOCALHOST=1 VITE_API_BASE="http://127.0.0.1:8010/api" npm run build

# 4) dist 를 정적 서버로 (SPA fallback 포함)
cd ..
node tools/staging/serve-dist.mjs 4173 frontend/dist

# 5) 검증
node tools/staging/verify-staging.mjs ./out/staging 9333
```

> `VITE_ALLOW_LOCALHOST=1` 은 **로컬 시뮬레이션 전용**이다.
> 실제 배포 빌드에서 쓰면 브라우저가 자기 자신의 localhost 로 요청한다.
> 이 값 없이 로컬 주소로 빌드하면 vite.config.js 가 빌드를 **실패시킨다**.

## 이 시뮬레이션을 만들면서 찾은 것

| 무엇이 잘못돼 있었나 | 어떻게 드러났나 |
|---|---|
| **연결 풀에 `pool_pre_ping` 이 없었다** | 원격 DB 가 유휴 연결을 끊으면 죽은 연결을 꺼내 쓴다. 서버에서 연결을 강제로 끊고 재현했더니 `OperationalError` — 배포 후 첫 한산한 시간대에 500 이 난다 |
| **빌드에 `localhost:8010` 이 조용히 박혔다** | `.env.production` 이 없어서 기본값이 들어갔다. E2E 가 전부 dev 서버라 한 번도 안 걸렸다 |

두 번째는 이제 **빌드가 실패한다**. 첫 번째는 `pool_pre_ping` + `pool_recycle` 로 고쳤다.

## 검사 도구를 만들면서 두 번 틀렸다 (같은 실수 반복 방지)

1. **`npm run build 2>&1 | grep "built in"` 이 빌드 실패를 삼켰다.**
   가드에 걸려 빌드가 실패했는데 grep 이 아무것도 출력하지 않아 성공한 줄 알았고,
   `dist/` 에는 이전 빌드가 남아 있었다. **파이프로 성공 여부를 판단하지 않는다.**
2. **손으로 만든 `OPTIONS` 요청은 preflight 가 아니다.**
   브라우저가 Origin 을 붙이지 않아 서버가 405 를 냈고, "CORS 가 깨졌다"는 잘못된
   결론을 낼 뻔했다. **실제 교차 출처 요청**을 보내야 브라우저가 스스로 preflight 를 돈다.

## 정리

```bash
docker rm -f mediscan-staging-db
# dist 는 다시 빌드하면 된다 (배포용으로 다시 만들 것)
```
