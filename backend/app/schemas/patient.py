from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel

KANA_PATTERN = r"^[ァ-ヶーぁ-ゖ\s　]+$"


class PatientBase(BaseModel):
    last_name: str = Field(min_length=1, max_length=50)
    first_name: str = Field(min_length=1, max_length=50)
    last_name_kana: str = Field(min_length=1, max_length=50, pattern=KANA_PATTERN)
    first_name_kana: str = Field(min_length=1, max_length=50, pattern=KANA_PATTERN)
    birth_date: date
    phone: str = Field(min_length=1, max_length=20, pattern=r"^[0-9+\-() ]+$")
    email: EmailStr | None = None
    address: str = Field("", max_length=255)
    notes: str = ""


class PatientCreate(PatientBase):
    pass


class PatientUpdate(PatientBase):
    pass


class PatientOut(PatientBase, ORMModel):
    id: int
    card_no: str
    created_at: datetime


class PatientBrief(ORMModel):
    id: int
    card_no: str
    last_name: str
    first_name: str
    last_name_kana: str
    first_name_kana: str
