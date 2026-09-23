$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker 명령을 찾을 수 없습니다. Docker Desktop을 설치하고 실행한 뒤 다시 시도하세요." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".env.docker")) {
    Copy-Item ".env.docker.example" ".env.docker"
    Write-Host ".env.docker를 만들었습니다. AI_DATA_ROOT_HOST 경로를 확인한 뒤 다시 실행하세요." -ForegroundColor Yellow
    exit 0
}

docker compose --env-file .env.docker up --build
