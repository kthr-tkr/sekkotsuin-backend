import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import str_enum


class NotificationChannel(enum.StrEnum):
    EMAIL = "email"
    SMS = "sms"


class NotificationKind(enum.StrEnum):
    BOOKING_CONFIRMED = "booking_confirmed"  # Web 予約の受付
    REMINDER = "reminder"  # 予約のリマインド
    CANCELLED = "cancelled"  # キャンセルの確認
    INTAKE_LINK = "intake_link"  # 問診 URL（スタッフが送信）
    PASSWORD_RESET = "password_reset"  # パスワード再設定


class NotificationStatus(enum.StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class Notification(Base):
    """送信待ち・送信済みの通知（outbox）。ワーカーが送信して結果を記録する。"""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_status_created", "status", "created_at"),
        Index("ix_notifications_clinic_created", "clinic_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id", ondelete="SET NULL"))
    appointment_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL")
    )
    kind: Mapped[NotificationKind] = mapped_column(str_enum(NotificationKind))
    channel: Mapped[NotificationChannel] = mapped_column(str_enum(NotificationChannel))
    to: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[NotificationStatus] = mapped_column(
        str_enum(NotificationStatus), default=NotificationStatus.QUEUED
    )
    attempts: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # 失敗後、次に送信を試す時刻（間隔をあけて再試行する）
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
