from datetime import date, datetime, time
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.models.appointment import BookingSource
from app.models.operations import (
    LeaveStatus,
    LeaveType,
    PaymentMethod,
    SalesStatus,
    ShiftStatus,
)
from app.schemas.appointment import StaffBrief
from app.schemas.common import ORMModel
from app.schemas.patient import PatientBrief


class SalesFields(BaseModel):
    patient_id: int
    appointment_id: int | None = None
    clinical_note_id: int | None = None
    treatment_menu_id: int | None = None
    staff_id: int | None = None
    treatment_date: date
    description: str = Field("", max_length=120)
    amount: int = Field(ge=0, le=10_000_000)
    payment_method: PaymentMethod = PaymentMethod.CASH
    status: SalesStatus = SalesStatus.PAID
    memo: str = ""


class SalesCreate(SalesFields):
    pass


class SalesUpdate(SalesFields):
    pass


class SalesOut(SalesFields, ORMModel):
    id: int
    created_at: datetime
    patient: PatientBrief
    staff: StaffBrief | None = None


class SalesPage(BaseModel):
    items: list[SalesOut]
    total: int
    paid_amount: int
    unpaid_amount: int


class ShiftUpsert(BaseModel):
    status: ShiftStatus = ShiftStatus.WORKING
    start_time: time | None = None
    end_time: time | None = None
    memo: str = Field("", max_length=255)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.status == ShiftStatus.OFF:
            self.start_time = self.end_time = None
            return self
        if self.start_time is None or self.end_time is None:
            raise ValueError("休み以外は勤務開始・終了の時刻を入力してください。")
        if self.start_time >= self.end_time:
            raise ValueError("勤務終了時刻は勤務開始時刻より後にしてください。")
        return self


class ShiftOut(ShiftUpsert, ORMModel):
    id: int
    staff_id: int
    date: date


class LeaveCreate(BaseModel):
    staff_id: int | None = None  # 省略時は自分。他のスタッフの分は管理者のみ
    leave_type: LeaveType
    start_date: date
    end_date: date
    reason: str = Field("", max_length=255)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("終了日は開始日以降にしてください。")
        if (self.end_date - self.start_date).days > 60:
            raise ValueError("休暇の期間は60日以内にしてください。")
        return self


class LeaveDecision(BaseModel):
    status: Literal[LeaveStatus.APPROVED, LeaveStatus.REJECTED]


class LeaveOut(ORMModel):
    id: int
    staff_id: int
    leave_type: LeaveType
    start_date: date
    end_date: date
    status: LeaveStatus
    reason: str
    created_at: datetime
    staff: StaffBrief


class KpiDaily(BaseModel):
    date: date
    sales: int
    visits: int


class KpiSource(BaseModel):
    source: BookingSource
    count: int


class KpiStaff(BaseModel):
    staff_id: int
    name: str
    sales: int
    visits: int
    notes: int


class Kpi(BaseModel):
    month: str
    sales_total: int
    sales_total_prev_month: int
    paid_count: int
    average_spend: int
    unpaid_count: int
    unpaid_amount: int
    appointments: int
    visits: int  # 完了した予約
    cancellations: int  # キャンセル + 無断キャンセル
    cancel_rate: float  # 0〜1
    new_patients: int
    daily: list[KpiDaily]
    booking_sources: list[KpiSource]
    by_staff: list[KpiStaff]
