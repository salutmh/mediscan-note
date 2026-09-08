"""
부위별 모델 가용성 / 상태 노출 테스트.

뇌 MRI 모델은 학습 노트북의 전처리·모델 구조를 그대로 재현해 **검증을 통과**했고
(PREPROCESS_VERIFIED=True), 서비스에는 **미리 계산된 예측**으로 연결된다.

여기서 고정하는 것:
  - 백엔드 프로세스는 직접 추론하지 않는다 (torch/monai 없이도 정상 동작해야 한다)
  - volume 입력 모델을 slice PNG 로 부르는 경로가 되살아나지 않는다
  - 전처리 미검증 상태로 되돌아가면 추론이 다시 막힌다
"""
import pytest

from app import inference

BODY_PARTS = ["brain_mri", "brain_ct", "chest_xray", "abdomen_ct", "knee_mri"]


@pytest.fixture(autouse=True)
def _clear_registry_cache():
    """모듈 캐시가 테스트 사이에 새지 않게."""
    inference._cache.clear()
    yield
    inference._cache.clear()


def _brain_module():
    module = inference.get_module("brain_mri")
    assert module is not None, "뇌 MRI wrapper 모듈은 로드되어야 한다"
    return module


# ------------------------------------------------------------ 현재 상태
def test_no_body_part_infers_inside_the_backend(client):
    """백엔드 프로세스는 어떤 부위도 직접 추론하지 않는다 (무거운 의존성을 넣지 않는다)."""
    for body_part in BODY_PARTS:
        assert inference.is_available(body_part) is False, body_part


def test_brain_mri_module_loads_but_backend_does_not_infer():
    """모듈은 로드되지만 백엔드 프로세스에서는 직접 추론하지 않는다.

    서비스 venv 에는 torch/monai 가 없다 (넣을 이유도 없다) — 예측은 미리 계산해 둔다.
    """
    module = _brain_module()
    assert module.MODEL_VERSION
    assert module.is_available() is False
    assert module.unavailable_reason() is not None


def test_preprocess_is_verified():
    """학습 노트북 산출물과 대조해 재현을 확인했으므로 True 다.

    되돌릴 일이 생기면(전처리 변경 등) 반드시 False 로 내리고 재검증한다.
    """
    assert _brain_module().PREPROCESS_VERIFIED is True


def test_model_is_volume_input():
    assert _brain_module().INPUT_KIND == "volume"


def test_two_dimensional_predict_is_blocked(tmp_path):
    """slice PNG 로 부르면 학습 때와 다른 입력이 된다 — 되살아나지 않게 막아둔다."""
    module = _brain_module()
    with pytest.raises(RuntimeError) as exc:
        module.predict(str(tmp_path / "any.png"))
    assert "volume" in str(exc.value)


def test_unverified_preprocess_blocks_everything(monkeypatch):
    """PREPROCESS_VERIFIED 를 내리면 즉시 사용 불가로 떨어진다 (안전장치 회귀 방지)."""
    module = _brain_module()
    monkeypatch.setattr(module, "PREPROCESS_VERIFIED", False)

    assert module.is_available() is False
    assert "전처리" in (module.unavailable_reason() or "")


def test_env_optin_alone_does_not_enable_model(monkeypatch):
    """환경변수만 켜도 의존성·가중치가 없으면 여전히 불가."""
    module = _brain_module()
    monkeypatch.setenv(module.ENABLE_ENV, "1")
    assert module.is_available() is False
    assert module.unavailable_reason() is not None


# --------------------------------------------------------- /health 노출
def test_health_exposes_model_status(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert set(body["models"]) == set(BODY_PARTS)


def test_health_reports_unavailable_reason(client):
    models = client.get("/health").json()["models"]

    brain = models["brain_mri"]
    assert brain["module_loaded"] is True
    assert brain["available"] is False
    assert brain["model_version"] == "vs-seg-unet2d5-att-hard-t1"
    assert brain["input_kind"] == "volume"
    assert brain["unavailable_reason"], "왜 직접 추론을 못 하는지 사유가 있어야 한다"

    missing = models["chest_xray"]
    assert missing["module_loaded"] is False
    assert "inference.py" in missing["unavailable_reason"]


def test_unknown_body_part_reports_reason():
    assert "알 수 없는 부위" in (inference.unavailable_reason("unknown_part") or "")


# ---------------------------------------- 모델이 없어도 서비스는 정상 동작
def test_grading_works_without_any_model(user_a, roi_match):
    """모델 미연결(예측 sidecar 없음) 상태에서도 채점은 기준 마스크로 정상 수행된다."""
    body = user_a.submit(roi_match).json()
    assert body["grade"] == "match"
    assert body["evaluation"]["method"] == "reference_mask"
    assert body["ai_prediction"] is None


def test_health_reports_precomputed_predictions(client):
    """미리 계산된 예측이 몇 케이스에 있는지 /health 에서 확인할 수 있어야 한다."""
    summary = client.get("/health").json()["precomputed_predictions"]
    assert "cases_with_prediction" in summary
    assert isinstance(summary["case_ids"], list)
