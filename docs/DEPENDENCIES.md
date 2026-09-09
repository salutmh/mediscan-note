# 의존성·자산 라이선스 목록

> `python -m scripts.license_inventory --markdown docs/DEPENDENCIES.md` 로 생성됩니다.
> **이 문서는 라이선스를 판단하지 않습니다.** 무엇을 쓰고 있는지를 모은 자료이고,
> '써도 되는가' 는 사람이 검토할 문제입니다.

생성 시각: 2026-09-09T02:06:10+00:00

---

## 0. 코드가 아닌 자산 (가장 먼저 볼 것)

**코드 라이선스와 전혀 다른 문제다.** 의료 데이터셋과 모델 가중치는 조건이 별도로 붙는다.

| 항목 | 종류 | 쓰임 | 저장소 포함 | 상태 |
|---|---|---|---|---|
| VS-SEG (Vestibular Schwannoma Segmentation) 데이터셋 | 의료영상 데이터셋 | 학습 케이스의 영상과 전문가 GT(RTSTRUCT) | 아니오 | **NEEDS_LICENSE_REVIEW** (BLOCKER-1) |
| VS_Seg 사전학습 가중치 (UNet2d5_spvPA) | 모델 가중치 | AI 예측 sidecar 계산 (참고 정보 전용, 채점에 쓰지 않음) | 아니오 | **NEEDS_LICENSE_REVIEW** (BLOCKER-1) |
| Pretendard 폰트 | 폰트 | 프론트 타이포그래피 | 아니오 | **확인됨** |

- **VS-SEG (Vestibular Schwannoma Segmentation) 데이터셋** — 원본 DICOM 과 파생 npy·PNG 는 저장소에 커밋하지 않는다 (backend/data/, app/static/cases/ 는 gitignore). 다만 **외부 사용자에게 서비스로 보여주는 것**은 별도 문제다.
- **VS_Seg 사전학습 가중치 (UNet2d5_spvPA)** — 가중치 파일(.pth)은 저장소에 없다. 계산된 예측 지표만 sidecar 로 서비스한다. 재배포가 아니라 **결과 활용**이므로 조건이 다를 수 있다 — 확인이 필요하다.
- **Pretendard 폰트** — npm 패키지로 들어온다 (아래 프론트 목록에도 나온다). SIL Open Font License.

> 미해결: BLOCKER-1 (`docs/CLAUDE_HANDOFF.md` 하단 BLOCKERS 참고)

---

## 1. 확인이 필요한 항목

| 패키지 | 버전 | 라이선스 | 이유 |
|---|---|---|---|
| `psycopg2-binary` | 2.9.9 | LGPL with exceptions | 배포 형태에 따라 의무가 생길 수 있다 (LGPL with exceptions) |

> **금지 목록이 아니다.** 배포 형태(서버에서 실행 / 재배포 / 정적 링크)에 따라
> 의무가 달라지므로 확인이 필요하다는 뜻이다.

---

## 2. 백엔드 (Python)

| 패키지 | 버전 | 라이선스 |
|---|---|---|
| `alembic` | 1.19.2 | MIT |
| `fastapi` | 0.115.0 | MIT License |
| `numpy` | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| `pillow` | 12.3.0 | MIT-CMU |
| `psycopg2-binary` | 2.9.9 | LGPL with exceptions |
| `pydantic` | 2.9.2 | MIT License |
| `python-multipart` | 0.0.9 | Apache Software License |
| `sqlalchemy` | 2.0.35 | MIT |
| `uvicorn` | 0.30.6 | BSD License |

---

## 3. 프론트엔드 (npm)

| 패키지 | 버전 | 라이선스 |
|---|---|---|
| `@vitejs/plugin-vue` | 6.0.8 | MIT |
| `@vue/test-utils` | 2.5.0 | MIT |
| `jsdom` | 30.0.1 | MIT |
| `pretendard` | 1.3.9 | OFL-1.1 |
| `vite` | 8.2.2 | MIT |
| `vitest` | 3.2.7 | MIT |
| `vue` | 3.5.42 | MIT |
| `vue-router` | 5.3.1 | MIT |

---

## 4. 이 프로젝트의 라이선스

저장소 루트에 LICENSE 파일이 없다면 **아직 정하지 않은 것**이다.
Public 저장소라도 라이선스가 없으면 기본적으로 모든 권리가 유보된다.

