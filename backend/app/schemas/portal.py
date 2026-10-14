from datetime import date, datetime, time

from pydantic import AwareDatetime, BaseModel, EmailStr, Field

from app.models.appointment import AppointmentStatus
from app.schemas.patient import KANA_PATTERN


class PortalMenu(BaseModel):
    id: int
    name: str
    description: str
    price: int
    duration_minutes: int


class PortalClinic(BaseModel):
    name: str
    booking_slug: str
    phone: str
    address: str
    booking_description: str
    business_start_time: time
    business_end_time: time
    closed_weekdays: list[str]
    booking_window_days: int
    cancel_deadline_hours: int
    menus: list[PortalMenu]


class PortalSlot(BaseModel):
    start_at: datetime
    end_at: datetime
    available: bool


class PortalToken(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PasswordField(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class PortalRegister(PasswordField):
    """初めて来院する方の登録。"""

    last_name: str = Field(min_length=1, max_length=50)
    first_name: str = Field(min_length=1, max_length=50)
    last_name_kana: str = Field(min_length=1, max_length=50, pattern=KANA_PATTERN)
    first_name_kana: str = Field(min_length=1, max_length=50, pattern=KANA_PATTERN)
    birth_date: date
    phone: str = Field(min_length=1, max_length=20, pattern=r"^[0-9+\-() ]+$")
    email: EmailStr


class PortalLink(PasswordField):
    """来院したことがある方の本人確認とアカウント作成。"""

    last_name: str = Field(min_length=1, max_length=50)
    first_name: str = Field(min_length=1, max_length=50)
    birth_date: date
    phone: str = Field(min_length=1, max_length=20)
    email: EmailStr


class PortalLogin(BaseModel):
    login_id: str = Field(min_length=1, max_length=254, description="メールアドレスか診察券番号")
    password: str = Field(min_length=1, max_length=128)


class MeOut(BaseModel):
    patient_id: int
    card_no: str
    last_name: str
    first_name: str
    last_name_kana: str
    first_name_kana: str
    birth_date: date
    phone: str
    email: str
    address: str
    clinic_name: str
    clinic_slug: str


class MeUpdate(BaseModel):
    phone: str = Field(min_length=1, max_length=20, pattern=r"^[0-9+\-() ]+$")
    address: str = Field("", max_length=255)


class MyAppointment(BaseModel):
    id: int
    start_at: datetime
    end_at: datetime
    menu_name: str
    status: AppointmentStatus
    can_cancel: bool
    # 未回答の Web 問診があれば、その URL 用のトークン
    intake_token: str | None = None


class MyBookingCreate(BaseModel):
    treatment_menu_id: int
    start_at: AwareDatetime
    notes: str = Field("", max_length=500)
