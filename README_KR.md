# 메디스캔노트 Docker 1차 통합 패키지

## 왜 이렇게 묶는가

현재 개발 중인 메디스캔노트는 사용자가 보는 홈페이지는 하나지만 내부 실행 요소가 나뉘어 있습니다.

- Vue/Vite 프론트: 5173
- 기존 메디스캔노트 FastAPI 백엔드: 8010
- 5질환 통합모델 결과용 AI sidecar FastAPI: 8000

이번 1차 정리는 이 세 가지를 **하나의 Docker Compose 명령으로 동시에 실행**하기 위한 것입니다.
아직 AI sidecar를 메인 백엔드 코드 안으로 억지로 합치지는 않습니다.
먼저 실행 환경을 안정화한 뒤, 다음 단계에서 API/데이터 구조를 정리하는 편이 안전합니다.

## 적용 위치

이 ZIP의 내용물을 `C:\Users\user\Desktop\mediscan-note` 최상위에 합쳐 넣습니다.

결과는 대략 다음 구조입니다.

mediscan-note/
├─ backend/
│  ├─ Dockerfile          ← 새 파일
│  └─ 기존 코드...
├─ frontend/
│  ├─ Dockerfile          ← 새 파일
│  └─ 기존 코드...
├─ ai_service/            ← 새 폴더
├─ docker-compose.yml     ← 새 파일
├─ .env.docker.example    ← 새 파일
├─ docker-up.ps1
└─ docker-down.ps1

기존 backend/frontend 소스 자체를 이 패키지가 교체하지 않습니다.
각 폴더에는 Dockerfile/.dockerignore만 추가합니다.

## 처음 한 번

1. Docker Desktop 설치 및 실행
2. `.env.docker.example`을 `.env.docker`로 복사
3. `.env.docker`에서 아래 경로가 실제로 존재하는지 확인

AI_DATA_ROOT_HOST=C:/Users/user/Desktop/medical-ai/service_inference_5disease

## 실행

PowerShell에서:

cd C:\Users\user\Desktop\mediscan-note
.\docker-up.ps1

또는 직접:

docker compose --env-file .env.docker up --build

처음 빌드는 Python/Node 패키지를 내려받으므로 시간이 걸릴 수 있습니다.

## 정상일 때

- 홈페이지: http://localhost:5173
- 기존 메인 API: http://localhost:8010/health
- AI API: http://localhost:8000/health
- AI 케이스: http://localhost:8000/api/cases

이제 각각 터미널을 따로 켤 필요가 없습니다.
`docker-up.ps1`을 실행한 터미널 하나만 유지하면 됩니다.

## 종료

.\docker-down.ps1

## 주의: DB

이 스타터는 Docker에서 기존 PC의 SQLite 파일을 실수로 훼손하지 않도록
기본값을 별도 Docker volume의 SQLite(`sqlite:////data/mediscan.db`)로 둡니다.

따라서 첫 실행에서 기존 사용자/케이스 데이터가 그대로 안 보일 수 있습니다.
현재 사용 중인 PostgreSQL을 그대로 붙이는 단계는 **DB 접속 문자열과 마이그레이션 상태를 확인한 다음** 진행하는 게 안전합니다.

## 다음 단계

1. 이 Compose로 세 서비스가 동시에 뜨는지 확인
2. 기존 메인 백엔드의 실제 DB 연결 확인
3. 15개 AI 샘플을 기존 Case/CaseSlice 구조에 정식 등록
4. AI sidecar 응답을 메인 API 계약 안으로 흡수
5. 최종적으로 프론트는 메인 API 한 곳만 바라보도록 정리

즉, 지금 목표는 "기능을 더 붙이기"가 아니라 "실행 구조를 먼저 안정화하기"입니다.
