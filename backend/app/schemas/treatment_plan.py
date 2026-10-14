from datetime import date, datetime
from typing import Any, Self

from pydantic import BaseModel, Field, model_validator

from app.models.treatment_plan import TreatmentPlanStatus, VisitGuideType
from app.schemas.appointment import StaffBrief
from app.schemas.common import ORMModel
from app.schemas.patient import PatientBrief


class TreatmentPlanFields(BaseModel):
    title: str = Field("", max_length=200)
    chief_complaint: str = Field("", max_length=255)
    start_date: date
    next_visit_date: date | None = None
    visit_guide_type: VisitGuideType | None = None
    visit_guide_count: int | None = Field(None, ge=1, le=31)
    visit_guide_note: str = Field("", max_length=100)
    bath_instruction: str = ""
    walking_instruction: str = ""
    exercise_instruction: str = ""
    work_instruction: str = ""
    lifestyle_instruction: str = ""
    caution_notes: str = ""
    expected_recovery_weeks_min: int | None = Field(None, ge=0, le=104)
    expected_recovery_weeks_max: int | None = Field(None, ge=0, le=104)
    rebound_reaction_note: str = ""

    @model_validator(mode="after")
    def _check_weeks(self) -> Self:
        lo, hi = self.expected_recovery_weeks_min, self.expected_recovery_weeks_max
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("改善目安の最長週は最短週以上にしてください。")
        return self


class TreatmentPlanCreate(BaseModel):
    patient_id: int
    # カルテから作る場合は主訴（S）と評価（A）を引き継ぐ
    clinical_note_id: int | None = None
    start_date: date | None = None


class TreatmentPlanUpdate(TreatmentPlanFields):
    status: TreatmentPlanStatus = TreatmentPlanStatus.ACTIVE


class ConsentOut(ORMModel):
    id: int
    signed_name: str
    signed_at: datetime
    signature_url: str | None = None
    plan_snapshot: dict[str, Any]
    witnessed_by: StaffBrief | None = None


class TreatmentPlanOut(TreatmentPlanFields, ORMModel):
    id: int
    patient_id: int
    clinical_note_id: int | None
    status: TreatmentPlanStatus
    end_date: date | None
    created_at: datetime
    updated_at: datetime
    patient: PatientBrief
    latest_consent: ConsentOut | None = None
    # 最後に署名してから計画の内容が変わっている（再署名が必要）
    consent_outdated: bool = False


class ConsentCreate(BaseModel):
    signed_name: str = Field(min_length=1, max_length=100)
    # canvas.toDataURL('image/png') の値
    signature_data_url: str = Field(pattern=r"^data:image/png;base64,", max_length=2_000_000)
