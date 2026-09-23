$ErrorActionPreference = "Stop"

$medicalAiRoot = "C:/Users/user/Desktop/medical-ai"

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "39. Brain MRI 5-disease case registration" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path "$medicalAiRoot/service_inference_5disease/index.json")) {
    Write-Host "Missing AI inference index.json:" -ForegroundColor Red
    Write-Host "$medicalAiRoot/service_inference_5disease/index.json"
    exit 1
}

if (-not (Test-Path "$medicalAiRoot/yolo_brain_5disease_integrated")) {
    Write-Host "Missing integrated YOLO dataset:" -ForegroundColor Red
    Write-Host "$medicalAiRoot/yolo_brain_5disease_integrated"
    exit 1
}

Write-Host "[1/2] Dry-run: checking images, GT labels, and DB structure." -ForegroundColor Yellow
docker compose --env-file .env.docker run --rm --no-deps `
  -v "${medicalAiRoot}:/medical-ai:ro" `
  backend `
  python -m scripts.register_brain5_demo_cases --medical-ai-root /medical-ai --dry-run

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Dry-run failed. No DB changes were made." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "[2/2] Registering 15 learning cases (10 positive + 5 negative)." -ForegroundColor Yellow
docker compose --env-file .env.docker run --rm --no-deps `
  -v "${medicalAiRoot}:/medical-ai:ro" `
  backend `
  python -m scripts.register_brain5_demo_cases --medical-ai-root /medical-ai

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Registration failed. DB changes should be rolled back." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Open: http://localhost:5173/cases"
Write-Host "AI sidecar uses the same case_id, so AI reference output can appear after scoring."
Write-Host "Negative cases (empty expert reference mask) are answered with the explicit No-abnormality button."
