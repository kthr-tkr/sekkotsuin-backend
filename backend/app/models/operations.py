"""売上・シフト・休暇。"""

import enum
from datetime import date, time

from sqlalchemy import Date, ForeignKey, Index, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import TimestampMixin, str_enum
from app.models.patient import Patient
from app.models.user import User


class PaymentMethod(enum.StrEnum):
    CASH = "cash"  # 現金
    CARD = "card"  # カード
    QR = "qr"  # QR 決済
    BANK_TRANSFER = "bank_transfer"  # 銀行振込
    OTHER = "other"


class SalesStatus(enum.StrEnum):
    UNPAID = "unpaid"  # 未会計
    PAID = "paid"  # 支払い済み
    CANCELED = "canceled"  # 取消


class SalesRecord(TimestampMixin, Base):
    __tablename__ = "sales_records"
    __table_args__ = (Index("ix_sales_records_clinic_date", "clinic_id", "treatment_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"), index=True
    )
    appointment_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL")
    )
    clinical_note_id: Mapped[int | None] = mapped_column(
        ForeignKey("clinical_notes.id", ondelete="SET NULL")
    )
    treatment_menu_id: Mapped[int | None] = mapped_column(
        ForeignKey("treatment_menus.id", ondelete="SET NULL")
    )
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    treatment_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(120), default="")  # 明細（メニュー名など）
    amount: Mapped[int] = mapped_column(default=0)  # 円（税込）
    payment_method: Mapped[PaymentMethod] = mapped_column(
        str_enum(PaymentMethod), default=PaymentMethod.CASH
    )
    status: Mapped[SalesStatus] = mapped_column(str_enum(SalesStatus), default=SalesStatus.PAID)
    memo: Mapped[str] = mapped_column(Text, default="")

    patient: Mapped[Patient] = relationship(lazy="raise")
    staff: Mapped[User | None] = relationship(lazy="raise")


class ShiftStatus(enum.StrEnum):
    WORKING = "working"  # 勤務
    OFF = "off"  # 休み
    HALF_DAY = "half_day"  # 半休
    TRAINING = "training"  # 研修
    OTHER = "other"


class StaffShift(TimestampMixin, Base):
    __tablename__ = "staff_shifts"
    __table_args__ = (
        UniqueConstraint("staff_id", "date", name="uq_staff_shifts_staff_date"),
        Index("ix_staff_shifts_clinic_date", "clinic_id", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    staff_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    status: Mapped[ShiftStatus] = mapped_column(str_enum(ShiftStatus), default=ShiftStatus.WORKING)
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    memo: Mapped[str] = mapped_column(String(255), default="")


class LeaveType(enum.StrEnum):
    PAID_LEAVE = "paid_leave"  # 有給
    MORNING_OFF = "morning_off"  # 午前休
    AFTERNOON_OFF = "afternoon_off"  # 午後休
    ABSENCE = "absence"  # 欠勤
    TRAINING = "training"  # 研修
    OTHER = "other"


class LeaveStatus(enum.StrEnum):
    REQUESTED = "requested"  # 申請中
    APPROVED = "approved"  # 承認済み
    REJECTED = "rejected"  # 却下
    CANCELED = "canceled"  # 取消


class StaffLeave(TimestampMixin, Base):
    __tablename__ = "staff_leaves"
    __table_args__ = (Index("ix_staff_leaves_clinic_start", "clinic_id", "start_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    staff_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    leave_type: Mapped[LeaveType] = mapped_column(str_enum(LeaveType))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[LeaveStatus] = mapped_column(
        str_enum(LeaveStatus), default=LeaveStatus.REQUESTED
    )
    reason: Mapped[str] = mapped_column(String(255), default="")
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    staff: Mapped[User] = relationship(foreign_keys=[staff_id], lazy="raise")
