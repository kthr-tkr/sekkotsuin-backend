import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import TimestampMixin, str_enum
from app.models.patient import Patient


class PostureStatus(enum.StrEnum):
    DRAFT = "draft"  # 下書き
    CONFIRMED = "confirmed"  # 確定


class PostureView(enum.StrEnum):
    FRONT = "front"  # 正面
    SIDE_RIGHT = "side_right"  # 右側面
    SIDE_LEFT = "side_left"  # 左側面
    BACK = "back"  # 背面


class PostureAssessment(TimestampMixin, Base):
    """姿勢評価。所見（findings）は AI 分析でも同じ構造で埋める。"""

    __tablename__ = "posture_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"), index=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    clinical_note_id: Mapped[int | None] = mapped_column(
        ForeignKey("clinical_notes.id", ondelete="SET NULL")
    )
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    title: Mapped[str] = mapped_column(String(120), default="姿勢評価")
    memo: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[PostureStatus] = mapped_column(
        str_enum(PostureStatus), default=PostureStatus.DRAFT
    )
    findings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    patient: Mapped[Patient] = relationship(lazy="raise")
    images: Mapped[list["PostureImage"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
        order_by="PostureImage.view",
        lazy="raise",
    )


class PostureImage(Base):
    __tablename__ = "posture_images"
    __table_args__ = (UniqueConstraint("assessment_id", "view", name="uq_posture_images_view"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("posture_assessments.id", ondelete="CASCADE")
    )
    view: Mapped[PostureView] = mapped_column(str_enum(PostureView))
    image_key: Mapped[str] = mapped_column(String(255))
    width: Mapped[int]
    height: Mapped[int]
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    assessment: Mapped[PostureAssessment] = relationship(back_populates="images", lazy="raise")
