"""
docs/api-spec.md 의 응답 스키마와 1:1로 대응하는 pydantic 모델.
스키마를 바꿀 때는 이 파일과 api-spec.md를 함께 갱신한다.
"""
from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, field_validator


REQUIRED_CONSENT_KEYS = [
    "agree_terms",
    "agree_privacy",
    "agree_sensitive_data",
    "agree_ai_notice",
    "agree_age14",
]


class Consents(BaseModel):
    agree_terms: bool
    agree_privacy: bool
    agree_sensitive_data: bool
    agree_ai_notice: bool
    agree_age14: bool
    agree_marketing: bool = False

    def missing_required(self) -> list[str]:
        return [k for k in REQUIRED_CONSENT_KEYS if not getattr(self, k)]


class SignupRequest(BaseModel):
    email: str
    password: str
    nickname: str
    consents: Consents


class LoginRequest(BaseModel):
    email: str
    password: str


class SocialLoginRequest(BaseModel):
    provider: Literal["kakao", "google", "naver"]
    provider_token: str
    consents: Optional[Consents] = None  # 최초 가입일 때만 필수


class DeleteAccountRequest(BaseModel):
    """회원 탈퇴 확인. 이메일 계정은 비밀번호를 다시 받는다 (SNS 계정은 생략 가능)."""

    password: Optional[str] = None


class DeleteAccountResult(BaseModel):
    """무엇이 지워졌는지 사용자가 확인할 수 있게 건수까지 돌려준다."""

    deleted: bool = True
    user_id: str
    deleted_counts: dict
    deleted_scopes: list[str]


class AuthResult(BaseModel):
    user_id: str
    email: Optional[str] = None
    nickname: str
    access_token: str
    token_type: str = "bearer"
    is_new_user: Optional[bool] = None


class CaseSummary(BaseModel):
    case_id: str
    body_part: str
    disease: str
    thumbnail_url: str
    # v0.3: solved 를 두 축으로 분리 (배타적이지 않다 — 맞힌 뒤 다시 틀리면 둘 다 True)
    has_matched: bool
    needs_review: bool
    gradable: bool = True


class CaseSliceInfo(BaseModel):
    """학습자에게 보이는 slice 1장.

    **마스크 정보가 없다.** 어느 slice 에 기준 마스크가 있는지는 곧 정답 위치이므로
    채점 전에는 어떤 형태로도 내려보내지 않는다 (routers/cases.py `_slice_list` 참고).
    """

    slice_index: int
    image_url: str


class CaseDetail(BaseModel):
    case_id: str
    body_part: str
    disease: str
    image_url: Optional[str] = None
    image_meta: dict
    gradable: bool = True
    # 화면·채점에 쓰는 대표 slice (병변 면적이 가장 큰 slice)
    representative_slice: Optional[int] = None
    # 병변 주변 slice 목록. 볼륨 전체가 아니라 **등록된 범위**만 들어 있다.
    slices: list[CaseSliceInfo] = []


ContentLevel = Literal["dataset_verified", "literature_based", "expert_reviewed"]


class MedicalTerm(BaseModel):
    term: str
    description: str = ""


class Reference(BaseModel):
    title: str
    publisher: Optional[str] = None
    url: Optional[str] = None
    accessed: Optional[str] = None  # YYYY-MM-DD


class CaseFacts(BaseModel):
    """이 케이스에서 **직접 확인된 사실**. 사람이 타이핑하지 않고 GT/DICOM 에서 계산한다."""

    source: Literal["dataset_verified"] = "dataset_verified"
    disease_name: str
    disease_code: str
    laterality: Optional[Literal["right", "left"]] = None
    laterality_basis: Optional[str] = None
    representative_slice: Optional[int] = None
    total_slices: Optional[int] = None
    lesion_slice_range: Optional[list[int]] = None  # [시작, 끝] 원본 volume 인덱스
    representative_area_px: Optional[int] = None
    reference_region: str
    dataset: Optional[str] = None


class DiseaseInfo(BaseModel):
    """질환 단위 **문헌 기반 일반 학습정보**. 이 케이스의 소견이 아니다.

    `app/content/diseases/<disease_code>.json` 에서 온다. 파일이 없거나 비어 있으면 null.
    `notice` 는 콘텐츠 파일이 아니라 서버 상수에서 채운다.
    """

    source: Literal["literature_based"] = "literature_based"
    notice: str
    imaging_features: list[str] = []
    medical_terms: list[MedicalTerm] = []
    references: list[Reference] = []
    content_version: Optional[str] = None


FindingsStatus = Literal["needs_expert_review", "in_review", "approved"]


class CaseFindings(BaseModel):
    """전문가가 **이 케이스를 보고 쓴** 영상 소견.

    검토 출처 메타데이터(reviewer / reviewed_at)를 필수로 둔다 — 누가 언제 본 내용인지
    남지 않는 소견은 등록하지 않는다. (필드가 있다는 것만으로 검토를 보증하지는 않는다.)

    **여기 들어가는 문장은 전부 사람이 쓴 것이다.** 자동 생성하지 않는다.
    geometry 로 계산되는 내용은 `spatial_feedback` 이 따로 담당한다.

    학습용 필드(`learning_points` / `common_mistakes` 등)도 전문가가 채운다.
    비어 있으면 화면에서 그 줄이 빠질 뿐, 지어내서 채우지 않는다.
    """

    source: Literal["expert_reviewed"] = "expert_reviewed"
    findings: str                                  # 핵심 영상 소견
    lesion_location: Optional[str] = None          # 병변 위치 설명 (전문가 문장)
    reference_region_note: Optional[str] = None    # 정답(기준) 영역이 왜 그렇게 잡혔는지
    learning_points: list[str] = []                # 학습자가 확인할 포인트
    common_mistakes: list[str] = []                # 자주 놓치는 부분
    medical_terms: list[MedicalTerm] = []
    references: list[Reference] = []
    reviewer: str
    reviewed_at: str                               # YYYY-MM-DD
    content_version: Optional[str] = None


class Explanation(BaseModel):
    """화면 4(학습 해설) — 출처가 다른 3개 블록 (API 계약 v0.4).

    `content_levels` 는 저장하지 않고 **블록 존재 여부에서 계산**한다. 세 값은 서로
    배타적이지 않아서(사실 + 문헌이 동시에 있을 수 있다) 스칼라 상태 필드로는 표현되지 않는다.
    """

    content_levels: list[ContentLevel] = []
    case_facts: Optional[CaseFacts] = None
    disease_info: Optional[DiseaseInfo] = None
    case_findings: Optional[CaseFindings] = None
    # 소견이 없을 때 화면이 조용히 빈칸을 보여주는 대신 상태를 말할 수 있게 한다.
    # ("아직 없음"과 "검토 중"은 학습자에게 다른 정보다)
    case_findings_status: FindingsStatus = "needs_expert_review"


class ScoringThresholds(BaseModel):
    """판정에 쓰인 임계값과 그 **검증 상태**.

    `validation_status`를 함께 내려보내는 이유: 0.60/0.15 는 교육적으로 검증된 값이 아니다.
    검증된 의학 기준처럼 화면에 표시되면 안 되므로 상태를 응답에 남긴다.
    """

    match_dice: float
    partial_dice: float
    validation_status: str


class AdminCaseUpdate(BaseModel):
    """운영자가 바꿀 수 있는 것 — **운영 메타데이터뿐이다.**

    영상·기준 마스크·해설 본문은 여기 없다. 전문가 GT 를 화면에서 고치는 경로를
    만들지 않기 위해서다 (docs/CONTENT_GUIDELINES.md 2절).
    """

    is_active: Optional[bool] = None
    difficulty: Optional[str] = None       # easy | medium | hard | "" (미지정으로 되돌림)
    findings_status: Optional[str] = None  # needs_expert_review | in_review | approved


class CaseFindingsInput(BaseModel):
    """전문가 소견 입력. `reviewer` / `reviewed_at` 이 **필수**다.

    누가 언제 본 내용인지 남지 않는 소견은 등록하지 않는다.
    (필드가 채워졌다는 것만으로 검토를 보증하지는 않는다 — 출처를 필수화하는 장치다.)
    """

    findings: str
    reviewer: str
    reviewed_at: str  # YYYY-MM-DD
    lesion_location: Optional[str] = None
    reference_region_note: Optional[str] = None
    learning_points: list[str] = []
    common_mistakes: list[str] = []
    medical_terms: list[MedicalTerm] = []
    references: list[Reference] = []
    content_version: Optional[str] = None

    @field_validator("findings", "reviewer", "reviewed_at")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("필수 항목은 비워 둘 수 없습니다.")
        return text

    @field_validator("reviewed_at")
    @classmethod
    def _iso_date(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("reviewed_at 은 YYYY-MM-DD 형식이어야 합니다.") from exc
        return value

    def to_block(self) -> dict:
        """DB(cases.explanation.case_findings)에 저장할 형태.

        `source` 는 입력값을 믿지 않고 항상 서버가 채운다.
        빈 항목은 빈 채로 둔다 — 등록 과정에서 내용을 만들어 넣지 않는다.
        """
        return {
            "source": "expert_reviewed",
            "findings": self.findings,
            "lesion_location": (self.lesion_location or "").strip() or None,
            "reference_region_note": (self.reference_region_note or "").strip() or None,
            "learning_points": [p.strip() for p in self.learning_points if p.strip()],
            "common_mistakes": [m.strip() for m in self.common_mistakes if m.strip()],
            "medical_terms": [t.model_dump() for t in self.medical_terms],
            "references": [r.model_dump() for r in self.references],
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at,
            "content_version": (self.content_version or "").strip() or None,
        }


class Evaluation(BaseModel):
    """어떤 방식으로 채점했는지. coordinate_approx 는 개발 전용이며 is_provisional=True 로 나간다."""

    method: Literal["reference_mask", "coordinate_approx"]
    is_provisional: bool = False
    thresholds: Optional[ScoringThresholds] = None


class SpatialFeedbackMetrics(BaseModel):
    """두 마스크의 겹침·면적·중심에서 계산된 값. **전부 geometry 다.**"""

    gt_coverage: Optional[float] = None            # 기준 영역 중 덮은 비율 (recall)
    user_precision: Optional[float] = None         # 칠한 것 중 기준 안 비율 (precision)
    area_ratio: Optional[float] = None             # 사용자 면적 / 기준 면적
    over_segmentation_ratio: Optional[float] = None
    under_segmentation_ratio: Optional[float] = None
    centroid_distance_px: Optional[float] = None
    centroid_distance_normalized: Optional[float] = None
    user_area_px: int = 0
    reference_area_px: int = 0


class SpatialFeedbackItem(BaseModel):
    code: str      # POSITION_ON_TARGET / UNDER_SEGMENTED / OVER_SEGMENTED ...
    message: str   # 그대로 노출 가능한 교육용 문장


class SpatialFeedback(BaseModel):
    """"왜 틀렸는지"를 알려주는 공간 피드백.

    **geometry 로 확인되는 것만 담는다.** 내이도 침범·조영증강·종괴 성상 같은 영상 소견은
    여기 들어오지 않는다 — 그건 전문가가 쓴 `explanation.case_findings` 자리다.
    채점(grade)에는 관여하지 않는다.
    """

    source: Literal["geometry"] = "geometry"
    primary_message: str
    items: list[SpatialFeedbackItem] = []
    metrics: SpatialFeedbackMetrics


class AiPrediction(BaseModel):
    """모델 예측 참고 정보. **채점에는 쓰이지 않는다** (api-spec v0.4).

    뇌 MRI 는 volume 입력 모델이라 요청 시 추론하지 않고, 미리 계산된 결과를 읽어 내려준다
    (`app/model_predictions.py`). `detected: false` 는 모델이 병변을 찾지 못한 케이스다 —
    학습자에게는 "모델도 놓칠 수 있다"는 정보라 숨기지 않는다.
    """

    model_version: str
    mask_url: Optional[str] = None          # 미검출이면 null
    dice_vs_reference: Optional[float] = None  # volume 전체 기준
    detected: bool = True
    representative_slice_dice: Optional[float] = None
    computed_at: Optional[str] = None

    model_config = {"protected_namespaces": ()}


class EvaluationResult(BaseModel):
    case_id: str
    grade: Literal["match", "partial_match", "mismatch"]
    dice: float
    iou: float
    location_score: int
    # 채점 기준이 된 전문가 검수 마스크 (v0.2 의 ai_mask_url 을 이름만 바로잡은 것)
    reference_mask_url: Optional[str] = None
    evaluation: Evaluation
    # geometry 기반 학습 피드백. 좌표 근사 채점(개발 전용)에서는 만들 수 없어 null 이다.
    spatial_feedback: Optional[SpatialFeedback] = None
    ai_prediction: Optional[AiPrediction] = None
    explanation: Explanation


class WrongNoteItem(BaseModel):
    case_id: str
    body_part: str
    grade: Literal["partial_match", "mismatch"]
    attempted_at: str


class CandidateDisease(BaseModel):
    name: str
    probability: float


class AnalyzeResult(BaseModel):
    """화면 5 — 사용자 업로드 영상 AI 분석 (api-spec 2-6).

    `status` 로 실제 분석인지 구분한다:
      ok                — 실제 모델 추론 결과
      model_unavailable — 해당 부위의 2D 분석 모델이 없음. 소견/후보질환은 비어 있다
                          (지어낸 값을 채우지 않는다)
      demo              — MEDISCAN_ANALYZE_DEMO=1 로 켠 화면 확인용 예시. is_demo=true

    ※ 여기의 key_findings 는 업로드 영상에 대한 모델 출력이며, 화면 4 해설의
      case_findings(전문가 검토 소견)와는 다른 것이다.
    """

    status: Literal["ok", "model_unavailable", "demo"] = "ok"
    is_demo: bool = False
    model_version: Optional[str] = None
    ai_mask_url: Optional[str] = None
    suspected_region: str = ""
    key_findings: str = ""
    candidate_diseases: list[CandidateDisease] = []
    unavailable_reason: Optional[str] = None
    disclaimer: str
