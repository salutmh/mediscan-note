# MediScanNote (메디스캔노트)

의료영상 판독 학습을 위한 AI 보조 학습 웹서비스.

학습자가 의료영상에서 이상 부위를 직접 ROI로 표시하면, **전문가가 검수한 기준 마스크(GT)** 와
비교해 일치 정도를 돌려주고, 일치하지 않은 케이스를 복습노트에서 반복 훈련하게 하는 학부 팀 프로젝트입니다.

> ⚠️ **교육·연구용 프로토타입입니다. 임상 진단용이 아닙니다.**
> 이 서비스의 어떤 출력도 의학적 진단·판단으로 사용해서는 안 됩니다.

---

## 현재 MVP 범위

- **실데이터 뇌 MRI 6케이스** — VS-SEG(전정신경초종) 기반. 케이스 = volume 1개이고,
  화면 표시와 채점은 병변 면적이 가장 큰 **대표 slice** 로 한다.
- **사용자가 ROI를 직접 표시** — 다크 뷰어 위에서 브러시/지우개로 칠한다. 칠한 영역은 보정하지 않는다.
- **전문가 GT 기준 Dice/IoU 채점** — 채점 기준은 **전문가 검수 reference mask 하나뿐**이다.
  기준 마스크가 없는 케이스는 채점하지 않고 422로 거부하며 제출 이력도 남기지 않는다.
- **일치 / 부분 일치 / 불일치 판정** (`match` / `partial_match` / `mismatch`).
  우리는 의료인이 아니므로 "정답/오답" 같은 확정적 의학 판단으로 읽히는 표현을 쓰지 않는다.
- **복습노트 · 재도전 · 진행현황** — 학습 상태를 `has_matched`(학습완료) /
  `needs_review`(복습필요) 두 축으로 분리해 관리한다 (두 값은 배타적이지 않다).
- **AI prediction은 채점과 완전히 분리된 참고 정보** — 모델 예측은 `ai_prediction` 필드로만 나가고
  학습자 판정에 일절 관여하지 않는다. 모델이 병변을 전혀 찾지 못한 케이스(VS-SEG-204)에서도
  사용자가 기준대로 칠하면 정상적으로 `match` 가 나온다.
- **문헌 기반 질환 학습정보** — 해설을 출처가 다른 3블록으로 나눈다:
  `case_facts`(데이터에서 계산한 사실) / `disease_info`(질환 문헌 일반론) /
  `case_findings`(전문가가 이 케이스를 보고 쓴 소견). 없는 블록은 비워 둔다.

## 현재 제외된 기능

| 기능 | 상태 | 이유 |
|---|---|---|
| 개인 의료영상 실제 AI 분석 | `status: "model_unavailable"` (업로드·검증까지만 동작) | 3D volume 모델을 단일 PNG/JPEG에 억지로 쓰면 학습 때와 다른 입력이라 조용히 틀린 결과가 나온다. 단일 이미지용 2D 모델 확보 후 구현 |
| DICOM 시리즈 업로드 | 미지원 (PNG/JPEG만) | 태그 비식별화가 선행되어야 함 |
| 실제 SNS OAuth | **미연동** | 화면의 카카오·구글·네이버 버튼은 **개발용 예시 로그인**이다. `provider_token` 을 각 사 서버에 검증하지 않으며, 실제 SNS 계정 정보를 사용하지도 전송하지도 않는다 |

## 중요한 안내

- **교육·연구용 프로토타입**이며 **임상 진단용이 아니다.**
- 고지를 화면에 남긴다: 가입 시 "AI 분석 결과는 학습 참고용이며 확정 진단이 아닙니다"가 **필수 동의 항목**이고,
  영상 분석 화면은 같은 문구를 상단에 고정 노출하며, 질환 문헌 정보 블록에는
  "이 케이스의 개별 영상 소견을 확정하는 설명은 아닙니다"라는 안내가 항상 붙는다.
- **이 저장소에 포함하지 않는 것**: 실제 의료영상 원본과 그 파생 자산, 모델 가중치(`.pth` 등),
  데이터베이스 파일, 개인정보, 비밀값(`.env`). 전부 `.gitignore`로 차단되어 있다.
  저장소에 커밋된 이미지는 테스트용 **합성 자리표시자**이지 실제 의료영상이 아니다.

## 데이터 · 출처

학습 케이스의 영상과 전문가 GT는 공개 데이터셋 **VS-SEG (Vestibular-Schwannoma-SEG)** 에서 왔다.

> Shapey J, et al. *Segmentation of vestibular schwannoma from MRI, an open annotated dataset and
> baseline algorithm.* Scientific Data 8:286 (2021). DOI [10.1038/s41597-021-01064-w](https://doi.org/10.1038/s41597-021-01064-w)

- **데이터셋 파일 자체는 이 저장소에 포함하지 않는다.** 원본과 그 파생물(npy, slice PNG, 기준 마스크)은
  모두 로컬 작업 폴더에 두고 gitignore한다. 사용하려면 데이터셋을 직접 받아 각자의 이용 약관을 확인해야 한다.
- 모델은 VS_Seg의 `UNet2d5_spvPA` 를 사용한다. **모델 소스와 가중치도 이 저장소에 포함하지 않는다.**
  예측은 오프라인에서 미리 계산해 케이스별 sidecar로 서비스하므로, **서비스 런타임은 학습 리포에도
  torch/monai에도 의존하지 않는다.** 예측을 다시 계산할 때만 `MEDISCAN_VS_SEG_ROOT` 로 학습 리포를 가리킨다.
- 질환 문헌 학습정보(`backend/app/content/diseases/`)는 문장마다 출처를 표기했고,
  참고한 문헌의 URL과 확인일을 함께 남겼다.

## 로컬 실행

```bash
# backend — http://localhost:8010
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8010

# frontend — http://localhost:5173
cd frontend
npm install
npm run dev
```

- 환경변수는 `backend/.env.example`, `frontend/.env.example` 를 복사해서 채운다.
  **배포 시 `MEDISCAN_SECRET_KEY` 주입은 필수다** (미설정이면 개발용 고정 키로 기동되며 경고가 뜬다).
- 첫 실행 시 Alembic 마이그레이션이 자동 적용된다. `DATABASE_URL` 미설정이면 로컬 SQLite를 쓴다.
- 기본 상태에서는 케이스가 비어 있다. 실제 케이스는 `scripts/import_cases.py` 로만 등록한다
  (데이터가 필요하므로 clone 직후에는 목록이 비어 있는 것이 정상이다).

## 현재 테스트 상태

| 검증 | 결과 |
|---|---|
| `cd backend && pytest` | **241 passed** |
| `cd backend && python -m scripts.verify_cases` | **VS-SEG 6케이스 통과** (등록 상태 + 오래된 예측 sidecar 점검) |
| `cd frontend && npm run build` | **통과** |

브라우저 E2E 스크립트 3종은 `tools/browser-verify/` 에 있다 (단위 테스트가 아닌 수동 검증 자동화).

## 저장소 구조

```
mediscan-note/
├── backend/          FastAPI + SQLAlchemy + Alembic
│   ├── app/          라우터 / 채점(grading) / 해설 조립 / 예측 sidecar 로더
│   ├── alembic/      마이그레이션 — 스키마의 기준
│   ├── scripts/      실데이터 파이프라인 CLI (export → 검수 → 자산생성 → 등록 → 점검)
│   └── tests/        pytest 241개
├── frontend/         Vue 3 + Vite. 화면 0~7
├── models/           부위별 추론 wrapper (+ 새 부위용 _template)
├── docs/api-spec.md  API 명세 v0.4 — 프론트·백엔드의 유일한 접점
├── CLAUDE.md         프로젝트 브리프 (작업 맥락)
└── review_bundle.md  코드리뷰용 상세 문서 (구현 현황·알려진 리스크)
```

## 남은 작업

1. **케이스별 영상 소견(`case_findings`) 전문가 검토** — 지금은 비어 있다(`null`).
   검토자와 검토일이 함께 남지 않는 소견은 등록하지 않는다.
2. **화면 5용 단일 이미지 2D 모델** — 확보 전까지 `model_unavailable` 을 유지한다.
3. **다른 부위 모델 확장** — 뇌CT / 흉부X-ray / 복부CT / 무릎.
   `models/_template/` 을 복사하고 같은 응답 스키마를 지키면 백엔드 수정이 필요 없다.
4. **배포 하드닝** — `MEDISCAN_SECRET_KEY` 주입, CORS 좁히기, PostgreSQL 전환 검증, SNS 실인증 연동.
