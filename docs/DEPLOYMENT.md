# 배포 런북 (Closed Beta)

> 대상: 이 서비스를 실제 사용자에게 열어야 하는 사람.
> 최초 작성 2026-09-08 / 관련: `docs/RELEASE_READINESS.md`, `backend/README.md`

이 문서는 **Closed Beta 규모**(수십 명, 단일 서버)를 전제로 한다.
그 이상으로 키우려면 3절의 한계를 먼저 읽는다.

---

## 0. 배포 전 반드시 확인 (체크리스트)

| # | 항목 | 확인 방법 |
|---|---|---|
| 1 | 데이터셋·모델 이용 조건 확인 | **BLOCKER-1** — 외부 사용자에게 여는 것이 허용되는지 (`CLAUDE_HANDOFF.md`) |
| 2 | `MEDISCAN_ENV=production` | 아래 필수 값이 없으면 **기동 자체가 실패**한다 |
| 3 | `MEDISCAN_SECRET_KEY` 주입 | 32자 이상. 저장소의 개발용 값은 거부된다 |
| 4 | `MEDISCAN_CORS_ORIGINS` 지정 | 실제 프론트 도메인. 와일드카드 금지 |
| 5 | `DATABASE_URL` 명시 | 미설정 시 기동 실패 (컨테이너 로컬 SQLite = 재배포 시 데이터 소실) |
| 6 | PostgreSQL 검증 | `python -m scripts.verify_postgres --url ... --with-tests` |
| 7 | 백업 예약 | 아래 4절 |
| 8 | 케이스 등록·점검 | `python -m scripts.verify_cases` 전체 통과 |
| 9 | 최초 운영자 지정 | `python -m scripts.grant_admin --email <이메일>` |
| 10 | 개발 전용 스위치 제거 | 아래 3개가 배포 환경에 남아 있으면 **기동 실패**한다 |
| 11 | `MEDISCAN_RATE_LIMIT` 확인 | `0` 은 거부된다. 앞단에서 제한한다면 `external` 로 명시 |

**production 에서 기동을 막는 값들** — 잘못 뜬 서버는 겉보기에 정상이라 아무도 눈치채지 못한다.
그래서 경고가 아니라 실패로 처리한다.

```bash
MEDISCAN_ENV=production          # 이 값이 있어야 아래 가드가 켜진다
MEDISCAN_SECRET_KEY=...          # python -c "import secrets; print(secrets.token_urlsafe(48))"
MEDISCAN_CORS_ORIGINS=https://mediscan.example.com
DATABASE_URL=postgresql+psycopg2://user:pw@host:5432/mediscan
```

**production 에 있으면 기동을 막는 값들 (개발 전용 스위치)** — 로컬 `.env` 를 복사하거나
데모 준비 후 원복을 잊으면 따라오기 쉬운 값들이다. 켜진 채로 떠도 서버는 겉보기에 멀쩡하고,
사용자만 사실과 다른 것을 보게 된다.

| 환경변수 | 켜지면 무슨 일이 생기는가 |
|---|---|
| `MEDISCAN_ALLOW_APPROX_GRADING` | 전문가 검수 기준 마스크가 아니라 **원 근사로 grade 를 매긴다** |
| `MEDISCAN_SEED_MOCK_CASES` | 실제 의료영상이 아닌 **합성 자리표시자가 학습 콘텐츠로 노출**된다 |
| `MEDISCAN_ANALYZE_DEMO` | 모델이 없는데 **분석 결과가 있는 것처럼 보인다** |

셋 다 `MEDISCAN_ANALYZE_DEMO=0` 처럼 **명시적으로 꺼 두는 것은 허용**한다 (배포 템플릿에
목록으로 남겨두는 경우). 값이 `1`/`true` 는 물론이고 `ture` 같은 오타여도 기동을 막는다 —
production 에 이 이름이 붙어 있다는 것 자체가 설정 실수이기 때문이다.

**요청 수 제한** — 개발·E2E 에서는 `MEDISCAN_RATE_LIMIT=0` 으로 끄고 돌리므로
배포 환경에 따라오기 쉽다. 꺼지면 로그인 무차별 대입이 열리고 서버는 겉보기에 정상이다.

| 값 | production 에서 |
|---|---|
| (미설정) | 앱이 제한한다 — 기본값 |
| `0` / `false` | **거부**. 기동하지 않는다 |
| `external` | 허용. 앱은 제한하지 않고 기동 로그에 경고를 남긴다 — **앞단 프록시·WAF 가 `/api/auth/*` 를 제한하고 있어야 한다** |
| `MEDISCAN_RATE_LIMIT_MULTIPLIER` > 1 | **거부**. 모든 한도를 한꺼번에 늘려 로그인 대입 한도까지 풀린다. 특정 한도만 조정하려면 `app/rate_limit.py` 의 `RULES` 를 고친다 |

선택 값은 `backend/.env.example` 참고 (`MEDISCAN_TOKEN_TTL`, `MEDISCAN_PUBLIC_BASE`,
`MEDISCAN_ANALYTICS`).

---

## 1. 백엔드

```bash
cd backend
pip install -r requirements.txt
# 기동 시 Alembic 마이그레이션이 자동 적용된다
uvicorn app.main:app --host 0.0.0.0 --port 8010
```

- 워커를 여러 개 띄울 때의 주의는 3절 참고.
- 기동 직후 `/health` 로 설정이 의도대로인지 확인한다:

```bash
curl https://api.example.com/health
# {"status":"ok","env":"production","cors_origins":"https://mediscan.example.com","db":"postgresql",...}
```

`env` 가 `development` 로 나오면 **환경변수가 안 먹은 것**이다. 그 상태로 열지 말 것.

### 케이스 자산

교육용 영상·마스크는 `backend/app/static/cases/` 에 있고 **저장소에 없다**.
배포 서버에 별도로 올린 뒤 `scripts/import_cases.py` 로 등록하고 `verify_cases.py` 로 점검한다.
`MEDISCAN_PUBLIC_BASE` 를 설정하면 영상 URL 이 그 도메인 기준으로 만들어진다.

---

## 2. 프론트엔드

```bash
cd frontend
npm ci
# 배포 API 주소를 .env.production 에 넣는다
echo "VITE_API_BASE=https://api.example.com/api" > .env.production
npm run build          # dist/ 를 정적 호스팅에 올린다
```

`VITE_API_BASE` 는 **빌드 시점에 박힌다.** 주소가 바뀌면 다시 빌드해야 한다.

---

## 3. 알려진 운영 한계 (Closed Beta 규모 전제)

| 항목 | 내용 | 넘어설 때 |
|---|---|---|
| rate limit | **프로세스 메모리**에 센다. 워커를 N개 띄우면 실질 한도가 N배가 된다 | 워커 2개 이상 → Redis 등 공유 저장소로 |
| 토큰 폐기 | DB 기반이라 워커가 여러 개여도 정상 동작한다 | — |
| 예측 sidecar | 모델을 바꾸면 **수동** 재계산 (`run_model_predictions.py` → `verify_cases.py`) | 모델 갱신이 잦아지면 자동화 |
| 케이스 목록 | 케이스마다 파일 존재 확인이 돈다 (6케이스 13ms, 30케이스 ~50ms) | 100케이스 넘으면 캐시 |
| 접속기록(감사 로그) | 없음 — 법적 요건 확인 필요 (**BLOCKER-3**). 계정 삭제 등 일부 운영 이벤트는 애플리케이션 로그에 남는다 | 규제 검토 후 |
| 비밀번호 재설정 | **운영자가 코드를 발급**한다 (`/admin/cases` 하단). 본인 확인은 오프라인 | 메일 발송 수단 확보 시 셀프서비스로 |

---

## 4. 백업 (열기 전에 반드시 설정)

학습 이력은 사용자가 시간을 들여 쌓은 것이고 **다시 만들 수 없다.**
케이스는 파이프라인으로 재생성할 수 있지만 제출 이력은 복구할 방법이 없다.

```bash
cd backend
python -m scripts.backup_db --out /var/backups/mediscan --keep 14
```

- SQLite 는 **온라인 백업 API** 를 쓴다 (서버가 도는 중에도 안전. 단순 복사는 깨질 수 있다).
- PostgreSQL 은 `pg_dump` 를 부른다.
- cron 예: `0 4 * * * cd /srv/mediscan/backend && python -m scripts.backup_db --out /var/backups/mediscan --keep 14`

> ⚠️ **백업 파일에는 계정·동의 이력·학습 이력이 들어 있다.** 원본 DB 와 같은 수준으로 보호한다.
> git·공개 저장소·공유 폴더에 두지 않는다.

**복구 연습을 한 번은 해본다.** 해본 적 없는 백업은 백업이 아니다.
- SQLite: 서버를 내리고 파일을 제자리에 되돌린다
- PostgreSQL: `psql -d mediscan -f <덤프파일>`

---

## 4-1. 로그

설정하지 않으면 앱의 INFO 로그가 **전부 버려진다** (root 로거 기본 레벨이 WARNING).
배포에서는 반드시 켠다 — 문의를 받았을 때 볼 것이 없으면 대응할 수 없다.

```bash
MEDISCAN_LOG_LEVEL=INFO      # DEBUG | INFO(기본) | WARNING | ERROR
MEDISCAN_LOG_FORMAT=json     # text(기본) | json — 로그 수집기에 넣을 때
```

`curl /health` 의 `logging` 항목으로 현재 설정을 확인할 수 있다.

**로그에 남기지 않는 것**: 비밀번호·토큰·요청 본문·업로드 영상.
사용자 식별은 내부 `user_id` 로만 하고 이메일·닉네임은 남기지 않는다 —
의료 서비스에서는 로그도 개인정보가 된다. (`tests/test_logging.py` 가 소스에서 검사한다.)

---

## 5. 운영 중 확인

| 무엇 | 명령 |
|---|---|
| 서비스 상태·설정 | `curl /health` (env, cors_origins, db, 모델 상태) |
| 케이스 상태·오래된 예측 | `python -m scripts.verify_cases` |
| 학습 지표 | `python -m scripts.learning_report` |
| 모델 성능 | `python -m scripts.evaluate_model` |
| 운영자 목록 | `python -m scripts.grant_admin --list` |

콘텐츠 관리(활성/비활성, 난이도, 전문가 소견)는 운영자 계정으로 `/admin/cases` 화면에서 한다.

---

## 6. 사고 대응

| 상황 | 대응 |
|---|---|
| 케이스 기준 마스크가 잘못됐다 | `/admin/cases` 에서 **비활성**으로 내린다. 학습자 목록·상세·제출·재도전에서 즉시 사라진다 (이력은 보존) |
| 토큰이 유출된 것 같다 | 사용자가 **비밀번호를 바꾸면 그 계정의 모든 기기 세션이 끊긴다**. 로그아웃은 그 토큰 하나만 폐기한다. 전 사용자를 끊어야 하는 최악의 경우에만 `MEDISCAN_SECRET_KEY` 교체 |
| 사용자가 비밀번호를 잊었다 | `/admin/cases` 하단에서 **재설정 코드 발급** → 본인 확인 후 전달. 24시간·일회용 |
| 운영자 권한을 회수해야 한다 | `python -m scripts.grant_admin --email <이메일> --revoke` — 즉시 반영된다(토큰에 담지 않는다) |
| 잘못된 소견이 등록됐다 | `/admin/cases` 에서 소견 **회수**. 상태가 `needs_expert_review` 로 돌아간다 |
| DB 를 되돌려야 한다 | 4절 복구 절차. 되돌리면 그 시점 이후 학습 이력은 사라진다 |
