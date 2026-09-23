# 39. 뇌 MRI 5질환 데모 케이스 → 기존 학습 흐름 등록

## 이번 패키지가 하는 일

현재 Docker가 정상 실행되는 메디스캔노트에, 통합 YOLO26s의 서비스 추론 샘플을 기존 학습 케이스 구조로 연결합니다.

등록 흐름:

원본 MRI slice
→ 통합 데이터셋의 GT polygon 라벨
→ reference_mask.png 복원
→ 메디스캔노트 Case 등록
→ 사용자가 ROI 표시
→ GT reference mask 기준 채점
→ 채점 후 같은 case_id의 AI sidecar 결과 표시

AI 예측 mask는 reference mask 생성에 사용하지 않습니다.

## 왜 15개 중 10개만 학습 DB에 등록하는가

35번 추론 산출물은 질환별로 양성 2건 + 음성 1건, 총 15건입니다.

현재 판독훈련 화면은 사용자가 병변 영역을 ROI로 표시해 제출하는 구조이고,
'병변 없음'을 정답으로 제출하는 별도 액션이 없습니다.

따라서:
- 양성 10건: 실제 학습/채점 케이스로 등록
- 음성 5건: AI sidecar 테스트에는 그대로 유지, 메인 학습 DB 등록은 보류

빈 GT mask를 억지로 채점에 넣으면 정상적인 '병변 없음' 답안을 만들 수 없으므로 이렇게 처리합니다.

## 설치

이 ZIP의 내용을 `C:\Users\user\Desktop\mediscan-note`에 합칩니다.

추가되는 파일:
- backend/scripts/register_brain5_demo_cases.py
- register-brain5-demo.ps1

기존 코드는 교체하지 않습니다.

## 실행

현재 Docker Compose가 켜져 있어도 됩니다.
새 PowerShell 창을 `mediscan-note` 폴더에서 열고 아래를 실행합니다.

PowerShell 실행정책 때문에 ps1이 막히면:

    powershell -ExecutionPolicy Bypass -File .\register-brain5-demo.ps1

정상적으로 실행되면 먼저 dry-run을 하고, 오류가 없을 때만 실제 DB 등록을 진행합니다.

## 사용하는 실제 데이터

기본 경로:
- C:/Users/user/Desktop/medical-ai/service_inference_5disease
- C:/Users/user/Desktop/medical-ai/yolo_brain_5disease_integrated

`service_inference_5disease`의 case_id를 그대로 사용하므로 AI sidecar와 메인 학습 케이스 ID가 일치합니다.

## 완료 확인

1. http://localhost:5173/cases
2. 뇌 MRI 케이스 목록에서 새 10건 확인
3. 케이스 선택 → ROI 표시 → 제출
4. 전문가 기준 GT로 채점
5. 완료 후 AI 참고 패널 표시

등록 결과 보고서:
- backend/data/brain5_registration_report.json

## 안전장치

- GT 라벨을 찾지 못하면 중단
- index의 양성/음성과 GT mask 유무가 다르면 중단
- 오류가 하나라도 있으면 DB 변경 롤백
- AI prediction mask를 채점 기준으로 사용하지 않음
- 전문가 케이스별 소견은 임의 생성하지 않고 `needs_expert_review` 상태로 등록
