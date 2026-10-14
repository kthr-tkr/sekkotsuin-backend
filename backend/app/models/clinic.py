from datetime import time

from sqlalchemy import JSON, ForeignKey, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import TimestampMixin

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class Clinic(TimestampMixin, Base):
    __tablename__ = "clinics"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    # 患者向け予約URL用（/b/<slug>）
    booking_slug: Mapped[str] = mapped_column(String(80), unique=True)

    settings: Mapped["ClinicSettings"] = relationship(
        back_populates="clinic", uselist=False, cascade="all, delete-orphan", lazy="raise"
    )


class ClinicSettings(TimestampMixin, Base):
    __tablename__ = "clinic_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(
        ForeignKey("clinics.id", ondelete="CASCADE"), unique=True
    )
    display_name: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(30), default="")
    address: Mapped[str] = mapped_column(String(255), default="")
    booking_description: Mapped[str] = mapped_column(Text, default="")

    business_start_time: Mapped[time] = mapped_column(Time, default=time(9, 0))
    business_end_time: Mapped[time] = mapped_column(Time, default=time(20, 0))
    break_start_time: Mapped[time | None] = mapped_column(Time, default=time(13, 0))
    break_end_time: Mapped[time | None] = mapped_column(Time, default=time(15, 0))
    appointment_interval_minutes: Mapped[int] = mapped_column(default=30)
    # 例: ["sun", "wed"]
    closed_weekdays: Mapped[list[str]] = mapped_column(JSON, default=list)

    primary_color: Mapped[str] = mapped_column(String(7), default="#1D4ED8")

    # 患者向けポータル（Web 予約・マイページ）
    portal_enabled: Mapped[bool] = mapped_column(default=True, server_default="true")
    # 予約の何時間前までキャンセルできるか
    portal_cancel_deadline_hours: Mapped[int] = mapped_column(default=24, server_default="24")
    # 何日先まで予約を受け付けるか
    portal_booking_window_days: Mapped[int] = mapped_column(default=60, server_default="60")

    # 患者への通知
    notify_email_enabled: Mapped[bool] = mapped_column(default=True, server_default="true")
    notify_sms_enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    # 予約の何時間前にリマインドを送るか（0 で送らない）
    reminder_hours_before: Mapped[int] = mapped_column(default=24, server_default="24")

    # AI（録音の文字起こし・要約、姿勢分析）
    ai_enabled: Mapped[bool] = mapped_column(default=True, server_default="true")
    # 月の録音分数の上限（超えると新しい録音を受け付けない）
    ai_monthly_minutes_limit: Mapped[int] = mapped_column(default=1000, server_default="1000")

    clinic: Mapped[Clinic] = relationship(back_populates="settings", lazy="raise")


class TreatmentMenu(TimestampMixin, Base):
    __tablename__ = "treatment_menus"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[int] = mapped_column(default=0)
    duration_minutes: Mapped[int] = mapped_column(default=30)
    is_active: Mapped[bool] = mapped_column(default=True)
    display_order: Mapped[int] = mapped_column(default=0)
