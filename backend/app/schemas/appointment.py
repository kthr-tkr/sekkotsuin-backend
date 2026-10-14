from datetime import datetime

from pydantic import AwareDatetime, BaseModel

from app.models.appointment import AppointmentStatus, BookingSource
from app.schemas.common import ORMModel
from app.schemas.patient import PatientBrief


class AppointmentCreate(BaseModel):
    patient_id: int | None = None
    treatment_menu_id: int | None = None
    start_at: AwareDatetime
    # 省略時はメニューの所要時間（メニューも無ければ院の予約単位）から算出
    end_at: AwareDatetime | None = None
    assigned_staff_id: int | None = None
    status: AppointmentStatus = AppointmentStatus.BOOKED
    booking_source: BookingSource = BookingSource.STAFF
    notes: str = ""
    # 患者に予約確認をメール / SMS で送る
    notify_patient: bool = False


class AppointmentUpdate(BaseModel):
    """部分更新。送られたフィールドのみ反映する。"""

    patient_id: int | None = None
    treatment_menu_id: int | None = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    assigned_staff_id: int | None = None
    status: AppointmentStatus | None = None
    booking_source: BookingSource | None = None
    notes: str | None = None


class StaffBrief(ORMModel):
    id: int
    full_name: str
    username: str


class AppointmentOut(ORMModel):
    id: int
    patient_id: int | None
    treatment_menu_id: int | None
    menu_name: str
    start_at: datetime
    end_at: datetime
    assigned_staff_id: int | None
    status: AppointmentStatus
    booking_source: BookingSource
    notes: str
    created_at: datetime
    patient: PatientBrief | None = None
    assigned_staff: StaffBrief | None = None


class AvailabilitySlot(BaseModel):
    start_at: datetime
    end_at: datetime
    available: bool
