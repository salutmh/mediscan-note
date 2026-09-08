# models/ 폴더 규칙

각 부위 담당 팀원은 학습/실험 코드는 이 리포 밖(개인 폴더)에 두고,
검증이 끝난 모델만 아래 패턴으로 여기에 추가한다.

```
models/
  _template/          새 부위를 추가할 때 복사해 쓰는 템플릿 ← 여기서 시작
  brain_mri_vs/       뇌 MRI · 전정신경초종 (**연결 완료** — volume 입력, 예측은 미리 계산)
  brain_ct/           뇌 CT 담당자 추가 예정
  chest_xray/         흉부 X-ray 담당자 추가 예정
  abdomen_ct/         복부 CT 담당자 추가 예정
  knee_mri/           무릎 담당자 추가 예정
```

## 새 부위 추가하는 법 (3단계)

1. `_template/inference.py` 를 `models/<부위폴더>/inference.py` 로 복사한다.
   폴더명은 `backend/app/inference.py` 의 `BODY_PART_MODULES` 에 정의된 이름을 쓴다
   (`chest_xray`, `abdomen_ct`, `knee_mri`, `brain_ct`).
2. `MODEL_VERSION` / `is_available()` / `predict()` 세 가지를 채운다.
3. 체크포인트를 `models/<부위폴더>/checkpoints/` 에 둔다 (git 에는 커밋하지 않음).

**백엔드 코드는 고칠 필요가 없다.** 백엔드가 부위 코드로 이 모듈을 찾아 자동으로 쓴다.

## 지켜야 할 계약

| 이름 | 역할 |
|---|---|
| `MODEL_VERSION` | 응답 `ai_prediction.model_version` 으로 나간다. 어떤 모델의 참고 결과인지 알 수 있게 적는다 |
| `is_available()` | 지금 추론 가능한지(체크포인트 존재, torch import 가능). **예외를 던지지 말 것** — False 면 `ai_prediction` 이 null 로 나갈 뿐 채점에는 영향이 없다 |
| `predict(image_path, reference_mask_path=None)` | 마스크 PNG 를 저장하고 그 경로를 `mask_path` 로 반환 |
| `INPUT_KIND` (선택) | `"image"`(기본) 또는 `"volume"`. `"volume"` 이면 백엔드가 slice PNG 로 `predict()` 를 부르지 않는다 |
| `predict_image(image, region=None)` (선택) | 화면 5(업로드 분석)용. **PIL 이미지 객체를 그대로 받는다** — 업로드 영상을 파일로 저장하지 않기 위해서다 |

- torch/numpy 같은 무거운 import 는 **함수 안에서** 한다. 그래야 torch 가 없는 환경에서도
  백엔드가 기동하고, 해당 부위만 "모델 없음"으로 처리된다.
- 마스크 PNG 형식: 병변 = 불투명, 배경 = 투명 (또는 흰색/검은색). 백엔드가 둘 다 인식한다.

## 모델 결과는 채점에 쓰이지 않는다 (중요)

API 계약 v0.3부터 **판독훈련 채점 기준은 전문가 검수 reference mask 하나뿐**이다.
모델이 준비되어도 채점 기준이 바뀌지 않는다 — 모델 출력은 응답의 `ai_prediction` 에
참고 정보(모델 버전, 기준 마스크와의 Dice)로만 실린다.

학습자를 "완벽하지 않은 모델의 예측"에 맞춰 채점하면 잘못된 피드백을 주기 때문이다.
모델의 역할은 **채점자가 아니라 비교 대상**이다.

## 전처리를 서비스 표시 규칙과 섞지 말 것 (뇌 MRI 사례)

서비스에 등록된 뇌 MRI 케이스 PNG 는 **표시용**이다 — volume 별 percentile 1~99% 클리핑 후
8bit 로 만든 것이고, 모델 입력 전처리(z-score)와 **아무 관련이 없다.**
두 규칙이 섞이면 조용히 틀린 마스크가 나오므로, `predict()` 는 표시용 PNG 를 그대로
정규화 없이 먹이지 말고 담당자가 학습 때 쓴 전처리를 다시 확인해야 한다.

원본 volume(npy)과 전문가 GT 는 `backend/scripts/export_vs_seg_npy.py` 가 학습 노트북과
**바이트 단위로 동일하게** 재현한다. 추론은 표시용 PNG 가 아니라 이 volume 을 쓴다.

## 무거운 모델은 미리 계산해서 붙인다 (뇌 MRI 방식)

VS_Seg 모델은 3D volume + sliding-window 추론이라 케이스당 수 분 걸린다. 제출 요청이 이걸
기다릴 수 없고, 백엔드에 torch/monai 를 깔 이유도 없다. 그래서:

```
(학습 venv) backend/scripts/run_model_predictions.py   # 추론 -> sidecar 저장
(백엔드)    app/model_predictions.py                    # sidecar 읽기만
```

sidecar 는 `app/static/cases/<case_id>/prediction.json` + `prediction.png` 다.
다시 계산해 덮어쓰면 서버 재시작 없이 반영된다 (mtime 확인).

**전처리 검증 규칙은 그대로다.** `PREPROCESS_VERIFIED = False` 로 내리면 즉시 추론이 막힌다.
뇌 MRI 는 노트북 산출물과 예측 마스크 배열까지 대조해 일치를 확인한 뒤 True 로 올렸다
(VS-SEG-202 완전 일치, 6케이스 Dice 일치).

## 현재 상태 확인

```
curl http://localhost:8010/health
```

`models` 항목에 부위별 `module_loaded` / `available` / `model_version` 이 나온다.
