# 배포 런북 (Closed Beta)

> 대상: 이 서비스를 실제 사용자에게 열어야 하는 사람.
> 최초 작성 2026-09-08 / 관련: `docs/RELEASE_READINESS.md`, `backend/README.md`

이 문서는 **Closed Beta 규모**(수십 명, 단일 서버)를 전제로 한다.
그 이상으로 키우려면 3절의 한계를 먼저 읽는다.

---

## 0. 배포 전 반드시 확인 (체크리스트)

**기계로 확인 가능한 항목은 한 번에 돌릴 수 있다:**

```bash
cd backend
python -m scripts.deploy_preflight --backup-dir /var/backups/mediscan
python -m scripts.deploy_preflight --simulate-production   # 로컬에서 미리보기
```

결과는 넷으로 나뉜다 — **차단 / 주의 / 확인못함 / 통과**.
`확인못함` 은 **통과가 아니다.** 데이터셋 이용 조건이나 전문가 GT 검수처럼 사람이
판단해야 하는 항목은 확인하는 척하지 않고 항상 여기 남는다.
차단이 하나라도 있으면 종료코드 1 이다.

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
| 11 | 보안 헤더·자산 서명 확인 | `curl /health` 의 `security_headers` / `asset_urls`. 케이스 영상은 서명 URL 로만 받을 수 있다 |
| 12 | `MEDISCAN_RATE_LIMIT` 확인 | `0` 은 거부된다. 앞단에서 제한한다면 `external` 로 명시 |

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
- **백업 직후 파일을 열어서 검증한다.** 무결성과 행 수를 원본과 대조하고, 실패하면 종료코드 1 이다.
  cron 에 걸었다면 이 종료코드를 알림으로 연결한다 — 조용히 실패하는 백업이 가장 나쁘다.
- cron 예: `0 4 * * * cd /srv/mediscan/backend && python -m scripts.backup_db --out /var/backups/mediscan --keep 14`

**검증이 잡아내는 것** (셋 다 "백업 완료" 만 보면 알 수 없다)

| 상황 | 어떻게 보이는가 | 검증 결과 |
|---|---|---|
| `DATABASE_URL` 미설정 → 엉뚱한 개발 DB 를 백업 | 파일이 정상적으로 생기고 크기도 그럴듯하다 | 원본에 사용자 데이터가 없다고 경고 |
| 디스크가 차서 파일이 잘림 | 크기만 보면 정상 | `integrity_check` 실패 → 종료코드 1 |
| `pg_dump` 가 도중에 끊김 | 파일이 남는다 | COPY 블록이 닫히지 않음 → 종료코드 1 |
| 원본엔 있는데 백업이 비어 있음 | — | 테이블별 대조에서 `!` 로 표시 → 종료코드 1 |

대조 대상은 **다시 만들 수 없는 데이터**다: `users` / `consents` / `submissions` / `learning_events`.
백업 스냅샷 이후에 새 행이 들어올 수 있으므로 백업 < 원본 은 정상으로 본다.
반대로 백업 > 원본 이면 다른 DB 를 백업한 것이므로 실패로 처리한다.

> ⚠️ **백업 파일에는 계정·동의 이력·학습 이력이 들어 있다.** 원본 DB 와 같은 수준으로 보호한다.
> git·공개 저장소·공유 폴더에 두지 않는다.

**복구 연습은 자동화돼 있다.** 해본 적 없는 백업은 백업이 아니다.

```bash
python -m scripts.restore_drill --backup /var/backups/mediscan/mediscan-<시각>.sqlite
```

백업을 **격리된 임시 위치**로 되돌리고, 마이그레이션을 최신까지 올린 뒤,
**앱을 실제로 띄워** 가입 → 케이스 목록 → 케이스 상세가 도는지 확인한다.
운영 DB 는 건드리지 않는다 (이 스크립트에는 운영 DB 로 되돌리는 경로가 없다).
실패하면 종료코드 1 이므로 백업 cron 과 함께 주기적으로 돌릴 수 있다.

수동으로 할 때는:
- SQLite: 서버를 내리고 파일을 제자리에 되돌린다
- PostgreSQL: `psql -d mediscan -f <덤프파일>`
- 보관 중인 백업만 다시 검사: `python -m scripts.backup_db --verify-only /var/backups/mediscan/mediscan-<시각>.sqlite`

> `backup_db.py` 의 검증은 "이 파일을 읽을 수 있고 안에 데이터가 있다" 까지다.
> **되돌려서 서비스가 뜨는지는 `restore_drill.py` 가 확인한다** — 잘린 파일과
> 옛 스키마 백업 둘 다 실제로 잡히는 것을 확인했다.
> 다만 **실제 복구 작업(서버 내리고 파일 되돌리기)은 여전히 사람이 한다.**

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
| 서비스 상태·설정 | `curl /health` — env, cors_origins, db 드라이버, 모델 상태에 더해 **적용 중인 채점 임계값**(`scoring`), **요청 수 제한 상태**(`rate_limit.mode`: app/external/off), **켜져 있는 개발 전용 스위치**(`dev_only_flags`, production 이면 항상 빈 배열)를 함께 보여준다. 배포 직후 여기부터 본다 |
| 케이스 상태·오래된 예측 | `python -m scripts.verify_cases` |
| 예측 sidecar 수명주기 | `python -m scripts.sidecar_manage status` — 무엇이 왜 오래됐는지. 재계산은 `plan` → 학습 venv 추론 → `validate` → `promote --apply` |
| 학습 지표 | `python -m scripts.learning_report` |
| 모델 성능 | `python -m scripts.evaluate_model` |
| 운영자 목록 | `python -m scripts.grant_admin --list` |
| 동시 쓰기 확인 | `python -m scripts.load_smoke --users 30` — 오류 없이 끝나야 한다 |
| 복구 훈련 | `python -m scripts.restore_drill --backup <최근 백업>` — 되돌린 DB 로 앱이 떠야 한다 |

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
