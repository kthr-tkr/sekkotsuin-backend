from datetime import datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, Field

from app.models.clinical_note import ClinicalNoteStatus
from app.schemas.appointment import StaffBrief
from app.schemas.common import ORMModel
from app.schemas.patient import PatientBrief


class ClinicalNoteFields(BaseModel):
    visited_at: AwareDatetime
    practitioner_id: int | None = None
    subjective: str = ""
    objective: str = ""
    assessment: str = ""
    plan: str = ""
    treatment_content: str = ""
    precautions: str = ""
    next_visit_suggestion: str = Field("", max_length=100)
    pain_scale_before: int | None = Field(None, ge=0, le=10)
    pain_scale_after: int | None = Field(None, ge=0, le=10)


class ClinicalNoteCreate(BaseModel):
    """予約から作る場合は appointment_id だけで良い（患者・日時・担当・問診を引き継ぐ）。"""

    appointment_id: int | None = None
    patient_id: int | None = None
    visited_at: AwareDatetime | None = None


class ClinicalNoteUpdate(ClinicalNoteFields):
    pass


class ClinicalNoteOut(ClinicalNoteFields, ORMModel):
    id: int
    patient_id: int
    appointment_id: int | None
    intake_id: int | None
    status: ClinicalNoteStatus
    finalized_at: datetime | None
    created_at: datetime
    updated_at: datetime
    patient: PatientBrief
    practitioner: StaffBrief | None = None


class ClinicalNoteRevisionOut(ORMModel):
    id: int
    snapshot: dict[str, Any]
    created_at: datetime
    edited_by: StaffBrief | None = None
