from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.intake import SymptomType
from app.schemas.common import ORMModel
from app.schemas.patient import PatientBrief


class IntakeCreate(BaseModel):
    patient_id: int
    appointment_id: int | None = None


class IntakeAnswers(BaseModel):
    """患者が回答する問診内容。"""

    chief_complaint: str = Field(min_length=1, max_length=255)
    symptom_type: SymptomType = SymptomType.UNKNOWN
    onset: str = Field("", max_length=100)
    # 痛む部位（例: ["neck", "lower_back"]）
    pain_areas: list[str] = []
    # 痛みの強さ 0〜10（NRS）
    pain_scale: int | None = Field(None, ge=0, le=10)
    cause: str = ""
    medical_history: str = ""
    medications: str = ""
    allergies: str = ""
    is_pregnant: bool | None = None
    notes: str = ""
    consent_agreed: bool


class IntakeOut(ORMModel):
    id: int
    patient_id: int
    appointment_id: int | None
    access_token: str
    token_expires_at: datetime
    submitted_at: datetime | None
    chief_complaint: str
    symptom_type: SymptomType
    onset: str
    payload: dict[str, Any]
    created_at: datetime
    patient: PatientBrief


class PublicIntakeOut(BaseModel):
    """患者向け: 個人情報は最小限のみ返す。"""

    clinic_name: str
    patient_display_name: str
    submitted: bool
    expires_at: datetime
    answers: IntakeAnswers | None = None
