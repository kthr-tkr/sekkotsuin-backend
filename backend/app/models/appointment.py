import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import TimestampMixin, str_enum
from app.models.patient import Patient
from app.models.user import User


class AppointmentStatus(enum.StrEnum):
    PENDING = "pending"  # 問診待ち
    BOOKED = "booked"  # 予約確定
    ARRIVED = "arrived"  # 来院
    COMPLETED = "completed"  # 完了
    CANCELLED = "cancelled"  # キャンセル
    NO_SHOW = "no_show"  # 無断キャンセル


# 担当者の時間帯を占有するステータス
BLOCKING_STATUSES = (
    AppointmentStatus.PENDING,
    AppointmentStatus.BOOKED,
    AppointmentStatus.ARRIVED,
)


class BookingSource(enum.StrEnum):
    HP = "hp"
    LINE = "line"
    GOOGLE = "google"
    INSTAGRAM = "instagram"
    QR = "qr"
    FLYER = "flyer"
    REFERRAL = "referral"
    SMS = "sms"
    EMAIL = "email"
    STAFF = "staff"
    UNKNOWN = "unknown"
    OTHER = "other"


class Appointment(TimestampMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        Index("ix_appointments_clinic_start", "clinic_id", "start_at"),
        Index("ix_appointments_staff_start", "assigned_staff_id", "start_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    patient_id: Mapped[int | None] = mapped_column(
        ForeignKey("patients.id", ondelete="SET NULL"), index=True
    )
    treatment_menu_id: Mapped[int | None] = mapped_column(
        ForeignKey("treatment_menus.id", ondelete="SET NULL")
    )
    # メニュー名のスナップショット（メニュー削除・改名後も表示できるように）
    menu_name: Mapped[str] = mapped_column(String(120), default="")

    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    assigned_staff_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    status: Mapped[AppointmentStatus] = mapped_column(
        str_enum(AppointmentStatus), default=AppointmentStatus.PENDING
    )
    booking_source: Mapped[BookingSource] = mapped_column(
        str_enum(BookingSource), default=BookingSource.UNKNOWN
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    patient: Mapped[Patient | None] = relationship(lazy="raise")
    assigned_staff: Mapped[User | None] = relationship(
        foreign_keys=[assigned_staff_id], lazy="raise"
    )
