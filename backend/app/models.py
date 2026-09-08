"""
SQLAlchemy 모델 — docs/api-spec.md 3절 "데이터 모델 요약"과 1:1로 대응한다.

WrongNote 는 별도 테이블을 두지 않고 Submission 에서 grade != 'match' 인 행을 뽑아 쓴다
(api-spec.md 3절에 "Submission 에서 grade≠match 인 것을 뷰로 뽑아도 됨"으로 열어둔 방식).
같은 케이스를 여러 번 풀 수 있으므로 "케이스별 최신 제출"을 기준으로 계산한다.
"""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # 이메일 가입이면 email/password_hash 가 채워지고, SNS 가입이면 provider/provider_subject 가 채워진다.
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, default=None)
    password_hash: Mapped[str | None] = mapped_column(String(255), default=None)
    nickname: Mapped[str] = mapped_column(String(60))
    provider: Mapped[str | None] = mapped_column(String(20), default=None)  # kakao | google | naver
    provider_subject: Mapped[str | None] = mapped_column(String(255), default=None)
    # 운영자 권한. **웹에서 스스로 올릴 수 있는 경로를 만들지 않는다** —
    # 최초 지정은 CLI(scripts/grant_admin.py)로만 한다.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    consents: Mapped[list["Consent"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    submissions: Mapped[list["Submission"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    # 탈퇴 시 관찰 로그도 함께 지운다 (app/account.py 의 삭제 범위에 포함된다)
    learning_events: Mapped[list["LearningEvent"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("provider", "provider_subject", name="uq_user_provider_subject"),)


class Consent(Base):
    """동의 이력. 약관이 바뀌어도 "누가 언제 몇 번 버전에 동의했는지" 증빙이 남아야 한다
    (api-spec.md 1절). 그래서 갱신이 아니라 append 로만 쌓는다."""

    __tablename__ = "consents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    key: Mapped[str] = mapped_column(String(40))  # agree_terms 등
    agreed: Mapped[bool] = mapped_column(Boolean)
    version: Mapped[str] = mapped_column(String(20))
    agreed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="consents")


class Case(Base):
    """케이스 = **volume 1개** (뇌 MRI 는 원본이 여러 slice 로 구성된다).

    화면 표시와 채점은 대표 slice 로 한다 — image_url / reference_mask_url 은 대표 slice 를
    가리키므로 현재 프론트(단일 이미지 기준)는 그대로 동작한다.
    slice 별 자산은 case_slices 테이블에 있고, 2.5D 확장 시 volume_id + slice_index 로
    previous / current / next 를 찾는다.
    """

    __tablename__ = "cases"

    case_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    body_part: Mapped[str] = mapped_column(String(20), index=True)
    disease: Mapped[str] = mapped_column(String(60))
    thumbnail_url: Mapped[str | None] = mapped_column(String(255), default=None)
    image_url: Mapped[str | None] = mapped_column(String(255), default=None)
    image_meta: Mapped[dict | None] = mapped_column(JSON, default=None)
    # 원본 volume 식별자 (예: "VS-SEG-202/T1"). 2.5D 입력 구성 시 인접 slice 조회 키가 된다.
    volume_id: Mapped[str | None] = mapped_column(String(80), default=None)
    # 화면 표시·채점에 쓰는 대표 slice (병변 면적이 가장 큰 slice)
    representative_slice: Mapped[int | None] = mapped_column(Integer, default=None)
    # 채점 기준이 되는 마스크 경로. 화면 3 오버레이에 그대로 내려주고, 2단계에서 실제 채점에도 쓴다.
    reference_mask_url: Mapped[str | None] = mapped_column(String(255), default=None)
    # 좌표 기반 임시 채점용 기준 영역 {cx, cy, r} (원본 픽셀 좌표).
    # 2단계에서 reference_mask_url 의 마스크에서 직접 계산하도록 대체된다 — grading.py 참고.
    reference_shape: Mapped[dict | None] = mapped_column(JSON, default=None)
    # 화면 4(학습 해설)에 쓰는 케이스별 해설. api-spec.md 2-3 의 explanation 객체 형태.
    explanation: Mapped[dict | None] = mapped_column(JSON, default=None)
    # 전문가 소견(case_findings)의 검토 진행 상태.
    # needs_expert_review(기본) | in_review | approved
    # 소견이 비어 있는 이유가 "아직 아무도 안 봤다"인지 "검토 중"인지 구분해야
    # 운영자가 진행 상황을 알 수 있고, 화면도 학습자에게 사실대로 말할 수 있다.
    findings_status: Mapped[str] = mapped_column(
        String(30), default="needs_expert_review", server_default="needs_expert_review"
    )
    # 학습자에게 노출할지 여부. 비활성 케이스는 목록·상세에서 숨긴다.
    # **삭제가 아니라 숨김이다** — 이미 쌓인 제출 이력은 그대로 남는다.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    # 난이도. **전문가 검토 대상**이라 자동으로 채우지 않는다 (CONTENT_GUIDELINES 참고).
    # easy | medium | hard | null(미지정)
    difficulty: Mapped[str | None] = mapped_column(String(10), default=None)

    submissions: Mapped[list["Submission"]] = relationship(back_populates="case")
    slices: Mapped[list["CaseSlice"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="CaseSlice.slice_index"
    )


class CaseSlice(Base):
    """volume 안의 slice 1장.

    병변이 있는 slice 와 앞뒤 여유분만 저장한다 (120장 전부는 불필요).
    slice_index 는 **원본 volume 기준 인덱스를 그대로 보존**한다 — 2.5D 로 확장할 때
    previous(i-1) / current(i) / next(i+1) 를 원본과 같은 좌표로 찾기 위함이다.
    """

    __tablename__ = "case_slices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    slice_index: Mapped[int] = mapped_column(Integer)
    image_url: Mapped[str] = mapped_column(String(255))
    # 해당 slice 의 전문가 검수 마스크 (병변이 없는 slice 면 None)
    mask_url: Mapped[str | None] = mapped_column(String(255), default=None)
    lesion_area_px: Mapped[int] = mapped_column(Integer, default=0)

    case: Mapped[Case] = relationship(back_populates="slices")

    __table_args__ = (UniqueConstraint("case_id", "slice_index", name="uq_case_slice_index"),)


class LearningEvent(Base):
    """학습 관찰 로그 (Closed Beta 측정용).

    **개인정보를 과도하게 담지 않는다** — 이메일·닉네임·IP·User-Agent·ROI 원본은 없다.
    남기는 것은 내부 user_id, case_id, 이벤트 종류, 시각, 그리고 점수/회차/소요시간뿐이다.
    자세한 이유는 app/analytics.py 참고.

    **채점이나 학습 상태 계산에 쓰이지 않는다.** 순수 관찰용이라 이 테이블을 통째로 비워도
    서비스는 그대로 동작한다.
    """

    __tablename__ = "learning_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 계정을 지우면 이벤트도 함께 사라진다 (User.learning_events 의 cascade)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    case_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    event: Mapped[str] = mapped_column(String(40), index=True)
    grade: Mapped[str | None] = mapped_column(String(20), default=None)
    dice: Mapped[float | None] = mapped_column(Float, default=None)
    attempt_number: Mapped[int | None] = mapped_column(Integer, default=None)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    user: Mapped[User] = relationship(back_populates="learning_events")


class Submission(Base):
    """제출 1건 = 채점 결과 1건. 같은 케이스를 여러 번 풀면 여러 행이 쌓인다."""

    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    grade: Mapped[str] = mapped_column(String(20))  # match | partial_match | mismatch
    dice: Mapped[float | None] = mapped_column(Float, default=None)
    iou: Mapped[float | None] = mapped_column(Float, default=None)
    location_score: Mapped[int | None] = mapped_column(Integer, default=None)
    # 채점 기준이 된 전문가 검수 마스크 (v0.2 의 ai_mask_url — 실제로는 기준 마스크였다)
    reference_mask_url: Mapped[str | None] = mapped_column(String(255), default=None)
    evaluation_method: Mapped[str] = mapped_column(String(30), default="reference_mask")
    is_provisional: Mapped[bool] = mapped_column(Boolean, default=False)
    explanation: Mapped[dict | None] = mapped_column(JSON, default=None)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    user: Mapped[User] = relationship(back_populates="submissions")
    case: Mapped[Case] = relationship(back_populates="submissions")
