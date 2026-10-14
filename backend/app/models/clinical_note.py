import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import TimestampMixin, str_enum
from app.models.patient import Patient
from app.models.user import User


class ClinicalNoteStatus(enum.StrEnum):
    DRAFT = "draft"  # 下書き
    FINALIZED = "finalized"  # 確定


# 修正履歴に保存する（= スタッフが編集できる）項目
EDITABLE_FIELDS = (
    "visited_at",
    "practitioner_id",
    "subjective",
    "objective",
    "assessment",
    "plan",
    "treatment_content",
    "precautions",
    "next_visit_suggestion",
    "pain_scale_before",
    "pain_scale_after",
)


class ClinicalNote(TimestampMixin, Base):
    """カルテ（1回の来院・施術の記録）。旧版の Visit / ChartNote / ClinicalNote を統合したもの。"""

    __tablename__ = "clinical_notes"
    __table_args__ = (
        Index("ix_clinical_notes_clinic_visited", "clinic_id", "visited_at"),
        Index("ix_clinical_notes_patient_visited", "patient_id", "visited_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    appointment_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"), unique=True
    )
    intake_id: Mapped[int | None] = mapped_column(ForeignKey("intakes.id", ondelete="SET NULL"))
    practitioner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    visited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[ClinicalNoteStatus] = mapped_column(
        str_enum(ClinicalNoteStatus), default=ClinicalNoteStatus.DRAFT
    )

    # SOAP
    subjective: Mapped[str] = mapped_column(Text, default="")
    objective: Mapped[str] = mapped_column(Text, default="")
    assessment: Mapped[str] = mapped_column(Text, default="")
    plan: Mapped[str] = mapped_column(Text, default="")

    treatment_content: Mapped[str] = mapped_column(Text, default="")  # 施術内容
    precautions: Mapped[str] = mapped_column(Text, default="")  # 生活指導・注意事項
    next_visit_suggestion: Mapped[str] = mapped_column(String(100), default="")
    # 痛みの強さ（NRS 0〜10）
    pain_scale_before: Mapped[int | None] = mapped_column(SmallInteger)
    pain_scale_after: Mapped[int | None] = mapped_column(SmallInteger)

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    finalized_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    patient: Mapped[Patient] = relationship(lazy="raise")
    practitioner: Mapped[User | None] = relationship(foreign_keys=[practitioner_id], lazy="raise")

    def snapshot(self) -> dict[str, Any]:
        data: dict[str, Any] = {f: getattr(self, f) for f in EDITABLE_FIELDS}
        data["visited_at"] = self.visited_at.isoformat()
        data["status"] = self.status.value
        return data


class ClinicalNoteRevision(Base):
    """カルテの修正履歴。更新のたびに「変更前」の内容を保存する。"""

    __tablename__ = "clinical_note_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    note_id: Mapped[int] = mapped_column(
        ForeignKey("clinical_notes.id", ondelete="CASCADE"), index=True
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    edited_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    edited_by: Mapped[User | None] = relationship(lazy="raise")
