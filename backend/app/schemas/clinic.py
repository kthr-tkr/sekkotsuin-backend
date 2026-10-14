from datetime import time
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORMModel

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class ClinicOut(ORMModel):
    id: int
    name: str
    booking_slug: str


class ClinicSettingsBase(BaseModel):
    display_name: str = Field("", max_length=120)
    phone: str = Field("", max_length=30)
    address: str = Field("", max_length=255)
    booking_description: str = ""
    business_start_time: time = time(9, 0)
    business_end_time: time = time(20, 0)
    break_start_time: time | None = time(13, 0)
    break_end_time: time | None = time(15, 0)
    appointment_interval_minutes: Literal[5, 10, 15, 20, 30, 60] = 30
    closed_weekdays: list[Weekday] = []
    primary_color: str = Field("#1D4ED8", pattern=r"^#[0-9A-Fa-f]{6}$")
    portal_enabled: bool = True
    portal_cancel_deadline_hours: int = Field(24, ge=0, le=24 * 14)
    portal_booking_window_days: int = Field(60, ge=1, le=365)
    notify_email_enabled: bool = True
    notify_sms_enabled: bool = False
    reminder_hours_before: int = Field(24, ge=0, le=24 * 7)
    ai_enabled: bool = True
    ai_monthly_minutes_limit: int = Field(1000, ge=0, le=100_000)

    @model_validator(mode="after")
    def _check_times(self) -> Self:
        if self.business_start_time >= self.business_end_time:
            raise ValueError("営業終了時刻は営業開始時刻より後にしてください。")
        if (self.break_start_time is None) != (self.break_end_time is None):
            raise ValueError("休憩時間を設定する場合は開始・終了の両方を入力してください。")
        if self.break_start_time and self.break_end_time:
            if self.break_start_time >= self.break_end_time:
                raise ValueError("休憩終了時刻は休憩開始時刻より後にしてください。")
            if (
                self.break_start_time < self.business_start_time
                or self.break_end_time > self.business_end_time
            ):
                raise ValueError("休憩時間は営業時間内に設定してください。")
        return self


class ClinicSettingsUpdate(ClinicSettingsBase):
    pass


class ClinicSettingsOut(ClinicSettingsBase, ORMModel):
    clinic_id: int


class TreatmentMenuBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    price: int = Field(0, ge=0)
    duration_minutes: int = Field(30, ge=5, multiple_of=5)
    is_active: bool = True
    display_order: int = 0


class TreatmentMenuCreate(TreatmentMenuBase):
    pass


class TreatmentMenuUpdate(TreatmentMenuBase):
    pass


class TreatmentMenuOut(TreatmentMenuBase, ORMModel):
    id: int
