import enum
from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import TimestampMixin, str_enum
from app.models.patient import Patient
from app.models.user import User


class TreatmentPlanStatus(enum.StrEnum):
    ACTIVE = "active"  # 進行中
    COMPLETED = "completed"  # 完了
    PAUSED = "paused"  # 中断


class VisitGuideType(enum.StrEnum):
    DAILY = "daily"  # 毎日
    WEEKLY = "weekly"  # 週◯回
    MONTHLY = "monthly"  # 月◯回
    CUSTOM = "custom"  # 個別設定


# 患者に説明・署名してもらう内容（署名時のスナップショットに含める項目）
PLAN_CONTENT_FIELDS = (
    "title",
    "chief_complaint",
    "start_date",
    "next_visit_date",
    "visit_guide_type",
    "visit_guide_count",
    "visit_guide_note",
    "bath_instruction",
    "walking_instruction",
    "exercise_instruction",
    "work_instruction",
    "lifestyle_instruction",
    "caution_notes",
    "expected_recovery_weeks_min",
    "expected_recovery_weeks_max",
    "rebound_reaction_note",
)


class TreatmentPlan(TimestampMixin, Base):
    """施術計画。経過は計画期間中のカルテで追う（旧版の TreatmentProgress は廃止）。"""

    __tablename__ = "treatment_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"), index=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    clinical_note_id: Mapped[int | None] = mapped_column(
        ForeignKey("clinical_notes.id", ondelete="SET NULL")
    )

    title: Mapped[str] = mapped_column(String(200), default="")
    chief_complaint: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[TreatmentPlanStatus] = mapped_column(
        str_enum(TreatmentPlanStatus), default=TreatmentPlanStatus.ACTIVE
    )
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)  # 完了・中断にした日
    next_visit_date: Mapped[date | None] = mapped_column(Date)

    visit_guide_type: Mapped[VisitGuideType | None] = mapped_column(str_enum(VisitGuideType))
    visit_guide_count: Mapped[int | None]
    visit_guide_note: Mapped[str] = mapped_column(String(100), default="")

    bath_instruction: Mapped[str] = mapped_column(Text, default="")
    walking_instruction: Mapped[str] = mapped_column(Text, default="")
    exercise_instruction: Mapped[str] = mapped_column(Text, default="")
    work_instruction: Mapped[str] = mapped_column(Text, default="")
    lifestyle_instruction: Mapped[str] = mapped_column(Text, default="")
    caution_notes: Mapped[str] = mapped_column(Text, default="")

    expected_recovery_weeks_min: Mapped[int | None]
    expected_recovery_weeks_max: Mapped[int | None]
    rebound_reaction_note: Mapped[str] = mapped_column(Text, default="")

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    patient: Mapped[Patient] = relationship(lazy="raise")

    def content_snapshot(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for f in PLAN_CONTENT_FIELDS:
            v = getattr(self, f)
            data[f] = v.isoformat() if isinstance(v, date) else v
        return data


class TreatmentPlanConsent(Base):
    """施術計画への同意（院内のタブレット等で患者がサインする）。"""

    __tablename__ = "treatment_plan_consents"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("treatment_plans.id", ondelete="CASCADE"), index=True
    )
    signed_name: Mapped[str] = mapped_column(String(100))
    signature_key: Mapped[str] = mapped_column(String(255))
    plan_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # 署名に立ち会ったスタッフ
    witnessed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    ip_address: Mapped[str] = mapped_column(String(45), default="")
    user_agent: Mapped[str] = mapped_column(Text, default="")

    witnessed_by: Mapped[User | None] = relationship(lazy="raise")
