import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import TimestampMixin, str_enum
from app.models.patient import Patient


class SymptomType(enum.StrEnum):
    ACUTE = "acute"  # 急性
    CHRONIC = "chronic"  # 慢性
    UNKNOWN = "unknown"  # 不明


class Intake(TimestampMixin, Base):
    """Web問診。スタッフが発行したURL（access_token）から患者が回答する。"""

    __tablename__ = "intakes"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"), index=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    appointment_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"), unique=True
    )

    access_token: Mapped[str] = mapped_column(String(64), unique=True)
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # 一覧で使う要点はカラム化、詳細は payload に保持
    chief_complaint: Mapped[str] = mapped_column(String(255), default="")
    symptom_type: Mapped[SymptomType] = mapped_column(
        str_enum(SymptomType), default=SymptomType.UNKNOWN
    )
    onset: Mapped[str] = mapped_column(String(100), default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    patient: Mapped[Patient] = relationship(lazy="raise")
