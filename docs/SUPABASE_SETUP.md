# Supabase 스테이징 연결 절차

> **이 문서는 연결 문자열을 만들어내지 않는다.**
> 실제 값은 Supabase Dashboard 의 **Connect** 에서 받은 것을 그대로 쓴다.
> 우리가 host 패턴을 조립하면 Supabase 가 형식을 바꿨을 때 조용히 틀린다.

---

## 0. 시작하기 전에 — 무엇을 올리고 무엇을 올리지 않는가

| | Supabase 에 올리는가 | 이유 |
|---|---|---|
| 계정·동의·제출·학습 이력 (DB) | **예** | 스테이징은 **합성 데이터만** 쓴다 |
| 케이스 영상·기준 마스크 | **아니오 (권장)** | 실제 환자 영상 파생물이다. 앱 서버에서 서빙한다 |
| 실제 학습자 데이터 | **아니오** | 개인정보 국외이전 문제가 된다 (BLOCKER-3) |

**영상을 앱 서버에 두는 것이 그대로 동작한다.** 서명 URL(`app/asset_urls.py`)이
`MEDISCAN_PUBLIC_BASE` 기준으로 만들어지므로, DB 만 Supabase 로 옮겨도 영상 경로는 그대로다.

> 데이터셋을 외부 서비스에 올리는 것은 **BLOCKER-1**(데이터셋·모델 이용 조건)에 걸린다.
> 답이 나오기 전까지는 DB 만 올린다.

---

## 1. 연결 방식 세 가지 — **포트만으로 구분하지 않는다**

Supabase 는 연결 방법이 셋이고 **세션 풀러도 5432 를 쓴다.**
host 와 사용자명까지 봐야 무엇인지 알 수 있다.

| 방식 | host | port | 사용자명 | 특징 |
|---|---|---|---|---|
| **Direct** | `db.<project-ref>.supabase.co` | 5432 | `postgres` | 전용 연결. prepared statement 사용 가능. **기본이 IPv6** |
| **Session pooler** | `<region>.pooler.supabase.com` | 5432 | `postgres.<project-ref>` | 세션 동안 연결 유지 → **Direct 처럼 동작**. IPv4 가능 |
| **Transaction pooler** | `<region>.pooler.supabase.com` | 6543 | `postgres.<project-ref>` | 트랜잭션 단위로 연결을 돌려씀. **prepared statement 제약** |

풀러는 **Supavisor** 다 (예전 PgBouncer 기준으로 알고 있으면 세부가 다르다).

### 용도별로 무엇을 쓰나

| 용도 | 권장 | 이유 |
|---|---|---|
| **마이그레이션 (Alembic)** | **Direct** | 스키마 변경은 세션 수준 기능을 쓴다 |
| **백업 / 복구 (pg_dump)** | **Direct** | 같은 이유 |
| **상시 실행 백엔드** | **Direct**, 필요하면 Session pooler | IPv4 전용 네트워크거나 연결 수가 많으면 Session pooler |
| serverless / 짧은 연결 | Transaction pooler | **이 프로젝트는 해당 없음** (상시 실행 프로세스다) |

> 앱이 이 구분을 알고 있다 (`app/db_connection.py`).
> 마이그레이션을 Transaction pooler 로 돌리면 **기동 로그에 경고**가 나오고,
> `deploy_preflight` 와 `/health` 에도 현재 연결 방식이 표시된다.
> **막지는 않는다** — 인프라 사정(IPv4 전용 등)을 우리가 알 수 없기 때문이다.

---

## 2. Dashboard 에서 값 받기

1. Supabase 프로젝트 → **Connect** (상단 버튼)
2. 화면에 세 가지 연결 문자열이 나온다. 목적에 맞는 것을 고른다.
3. `[YOUR-PASSWORD]` 자리에 프로젝트 DB 비밀번호를 넣는다.
4. **드라이버 접두사를 이 프로젝트 형식으로 바꾼다:**
   `postgresql://...` → `postgresql+psycopg2://...`
5. 끝에 `?sslmode=require` 를 붙인다 (Supabase 는 TLS 를 요구한다. 명시하는 편이 명확하다).

비밀번호에 `@` `:` `/` 같은 문자가 있으면 **percent-encoding** 해야 한다
(`@` → `%40`). 안 그러면 URL 파싱이 엉뚱하게 된다.

---

## 3. 환경변수 목록

### 3-1. 반드시 설정해야 하는 것 (없으면 **기동 실패**)

| 환경변수 | 값 | 비고 |
|---|---|---|
| `MEDISCAN_ENV` | `production` | 이 값이 있어야 아래 가드가 켜진다 |
| `MEDISCAN_SECRET_KEY` | 32자 이상 무작위 | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `MEDISCAN_CORS_ORIGINS` | 프론트 실제 주소 | 와일드카드 금지. 예: `https://mediscan-staging.pages.dev` |
| `DATABASE_URL` | Supabase 연결 문자열 | **Connect 에서 받은 값** + `+psycopg2` + `?sslmode=require` |

### 3-2. 스테이징에서 함께 설정할 것

| 환경변수 | 값 | 왜 |
|---|---|---|
| `MEDISCAN_PUBLIC_BASE` | API 의 공개 주소 | **자산 서명이 이 주소로 걸린다.** 비우면 요청 주소를 쓰는데, 프록시 뒤에서는 내부 주소가 잡힐 수 있다 |
| `MEDISCAN_LOG_FORMAT` | `json` | 로그 수집을 붙일 거라면 |
| `MEDISCAN_LOG_LEVEL` | `INFO` | |

### 3-3. 선택 (기본값으로 두어도 된다)

| 환경변수 | 기본 | 설명 |
|---|---|---|
| `MEDISCAN_ASSET_URL_TTL` | `86400` | 케이스 영상 URL 유효기간(초) |
| `MEDISCAN_DB_POOL_SIZE` | `5` | 연결 풀 크기. **Supabase 무료 플랜은 연결 수 제한이 낮다** |
| `MEDISCAN_DB_MAX_OVERFLOW` | `5` | 위와 같음 |
| `MEDISCAN_TOKEN_TTL` | `604800` | 토큰 수명(초) |
| `MEDISCAN_CSP` | (없음) | 배포 형태가 정해진 뒤에 넣는다. **추측해서 만들지 않는다** |
| `MEDISCAN_RATE_LIMIT` | (없음=켜짐) | 앞단에서 제한한다면 `external` |

### 3-4. **절대 설정하면 안 되는 것** (production 에서 기동이 실패한다)

```
MEDISCAN_ALLOW_APPROX_GRADING   검수 안 된 기준으로 채점한다
MEDISCAN_SEED_MOCK_CASES        합성 자리표시자가 학습 콘텐츠로 노출된다
MEDISCAN_ANALYZE_DEMO           모델이 없는데 분석 결과가 있는 것처럼 보인다
MEDISCAN_RATE_LIMIT=0           로그인 무차별 대입이 열린다 (external 은 허용)
```

### 3-5. SNS 로그인 (선택 — 안 넣으면 SNS 로그인이 503 으로 거부된다)

| 환경변수 | 값 | 비고 |
|---|---|---|
| `MEDISCAN_OAUTH_GOOGLE_CLIENT_ID` | 구글 OAuth 클라이언트 ID | 공개 값 |
| `MEDISCAN_OAUTH_KAKAO_APP_ID` | 카카오 앱 ID | 공개 값 |
| `MEDISCAN_OAUTH_NAVER_ENABLED` | `1` | |

### 3-6. 프론트엔드 (빌드 시점)

| 환경변수 | 값 |
|---|---|
| `VITE_API_BASE` | API 의 공개 주소 + `/api` (예: `https://api-staging.example.com/api`) |

> **빌드 시점에 번들로 박힌다.** 설정하지 않거나 localhost 를 넣으면
> `vite.config.js` 가 **빌드를 실패시킨다** — 예전에는 조용히 localhost 가 박혀서
> 배포하면 아무 요청도 나가지 않는 화면이 됐다.

---

## 4. 연결 절차

```bash
cd backend

# 0) 연결 방식이 무엇으로 인식되는지 먼저 확인한다 (오타·모드 착각을 여기서 잡는다)
DATABASE_URL="<Direct 연결 문자열>" python -c "
from app.db import DATABASE_URL
from app import db_connection as c
d = c.describe(DATABASE_URL)
print(d['label'], d['port'], 'ssl=' + str(d['sslmode']))
for n in c.advisories(DATABASE_URL, purpose='migration'): print(' -', n)
"

# 1) 스키마 — **Direct connection 으로**
DATABASE_URL="<Direct 연결 문자열>" python -c "from app.db import init_db; init_db()"

# 2) 케이스 등록 — Direct 로 (자산 파일은 앱 서버 디스크에 있어야 한다)
DATABASE_URL="<Direct 연결 문자열>" python -m scripts.import_cases data/vs_seg_cases/manifest.json

# 3) 등록 확인
DATABASE_URL="<Direct 연결 문자열>" python -m scripts.verify_cases

# 4) 최초 운영자 지정
DATABASE_URL="<Direct 연결 문자열>" python -m scripts.grant_admin --email <이메일>

# 5) 배포 직전 점검 — 차단 항목이 없어야 한다
MEDISCAN_ENV=production \
MEDISCAN_SECRET_KEY="<무작위 48자>" \
MEDISCAN_CORS_ORIGINS="https://<프론트 주소>" \
DATABASE_URL="<런타임 연결 문자열>" \
  python -m scripts.deploy_preflight --backup-dir /var/backups/mediscan

# 6) 백엔드 기동 (Direct 또는 Session pooler)
MEDISCAN_ENV=production \
MEDISCAN_SECRET_KEY="<무작위 48자>" \
MEDISCAN_CORS_ORIGINS="https://<프론트 주소>" \
MEDISCAN_PUBLIC_BASE="https://<API 주소>" \
DATABASE_URL="<런타임 연결 문자열>" \
  python -m uvicorn app.main:app --host 0.0.0.0 --port 8010

# 7) 프론트 빌드 — VITE_API_BASE 는 **반드시** 실제 주소
cd ../frontend
VITE_API_BASE="https://<API 주소>/api" npm run build
#   dist/ 를 정적 호스팅에 올린다. **SPA fallback 설정을 꼭 켠다**
#   (없으면 /cases/VS-SEG-202 로 새로고침할 때 404 가 난다)
```

---

## 5. 연결된 뒤 확인할 것

```bash
curl https://<API 주소>/health
```

응답에서 볼 것:

| 필드 | 기대값 |
|---|---|
| `env` | `production` |
| `db_connection.label` | `Supabase Direct connection` 또는 `Session pooler` |
| `db_connection.sslmode` | `require` |
| `dev_only_flags` | `[]` (production 이면 항상 비어 있다) |
| `security_headers.headers` | 5종이 들어 있다 |
| `asset_urls.protected_prefix` | `/static/cases/` |
| `social_login.unverified` | 앱 ID 를 안 넣었으면 세 제공자가 다 여기 있다 |

그다음:

```bash
# 백업 — Direct 로
DATABASE_URL="<Direct>" python -m scripts.backup_db --out /var/backups/mediscan

# 복구 훈련 (SQLite 백업만 지원. PostgreSQL 덤프는 psql 로 빈 DB 에 되돌려 확인)
python -m scripts.restore_drill --backup <백업파일>

# 동시 쓰기
python -m scripts.load_smoke --base https://<API 주소> --users 20
```

---

## 6. 자주 걸리는 것

| 증상 | 원인 |
|---|---|
| 연결 자체가 안 됨 | Direct 는 **기본이 IPv6** 다. IPv4 전용 네트워크면 **Session pooler** 를 쓴다 |
| 인증 실패 | 풀러는 사용자명이 `postgres.<project-ref>` 다. `postgres` 만 쓰면 안 된다 |
| 마이그레이션이 이상하게 실패 | Transaction pooler(6543)로 돌린 것이 아닌지 확인. **Direct 를 쓴다** |
| 한산한 시간 뒤 500 | `pool_pre_ping` 이 켜져 있는지 (지금은 기본으로 켜져 있다) |
| 연결 수 초과 | `MEDISCAN_DB_POOL_SIZE` / `MEDISCAN_DB_MAX_OVERFLOW` 를 줄인다 |
| 영상이 안 보임 | `MEDISCAN_PUBLIC_BASE` 가 실제 공개 주소인지 (서명이 이 주소로 걸린다) |
| 새로고침하면 화면이 사라짐 | 정적 호스팅에 **SPA fallback** 설정이 빠졌다 |
| 아무 요청도 안 나감 | 빌드할 때 `VITE_API_BASE` 를 안 넣었다 (지금은 빌드가 실패한다) |

---

## 7. 로컬에서 먼저 연습하기

Supabase 계정 없이도 **배포와 같은 형태**를 로컬에 세울 수 있다:
`tools/staging/README.md` 참고. 실제로 그렇게 해서 두 가지 문제를 찾았다
(연결 풀 pre-ping 없음, 빌드에 localhost 박힘).
