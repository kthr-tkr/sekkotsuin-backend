from datetime import date

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser, not_found
from app.models import Appointment, Intake, Patient
from app.schemas.appointment import AppointmentOut
from app.schemas.common import Page
from app.schemas.intake import IntakeOut
from app.schemas.patient import PatientCreate, PatientOut, PatientUpdate
from app.services.patients import next_card_no

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("", response_model=Page[PatientOut])
async def list_patients(
    db: DB,
    user: CurrentUser,
    q: str | None = Query(None, description="氏名・カナ・診察券番号・電話番号で検索"),
    birth_date: date | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    stmt = select(Patient).where(Patient.clinic_id == user.clinic_id)
    if q:
        for word in q.split():
            like = f"%{word}%"
            stmt = stmt.where(
                or_(
                    Patient.last_name.ilike(like),
                    Patient.first_name.ilike(like),
                    Patient.last_name_kana.ilike(like),
                    Patient.first_name_kana.ilike(like),
                    Patient.card_no.ilike(like),
                    Patient.phone.ilike(like),
                )
            )
    if birth_date:
        stmt = stmt.where(Patient.birth_date == birth_date)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await db.scalars(
        stmt.order_by(Patient.last_name_kana, Patient.first_name_kana, Patient.id)
        .limit(limit)
        .offset(offset)
    )
    return {"items": list(rows), "total": total}


@router.post("", response_model=PatientOut, status_code=201)
async def create_patient(db: DB, user: CurrentUser, body: PatientCreate) -> Patient:
    # 同時登録で番号が衝突した場合に備えてリトライ
    for _ in range(3):
        patient = Patient(
            clinic_id=user.clinic_id,
            card_no=await next_card_no(db, user.clinic_id),
            **body.model_dump(),
        )
        db.add(patient)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            continue
        await db.refresh(patient)
        return patient
    raise HTTPException(
        status.HTTP_409_CONFLICT, "診察券番号の採番に失敗しました。再試行してください。"
    )


async def get_patient_or_404(db: DB, clinic_id: int, patient_id: int) -> Patient:
    patient = await db.get(Patient, patient_id)
    if patient is None or patient.clinic_id != clinic_id:
        raise not_found("患者")
    return patient


@router.get("/{patient_id}", response_model=PatientOut)
async def get_patient(db: DB, user: CurrentUser, patient_id: int) -> Patient:
    return await get_patient_or_404(db, user.clinic_id, patient_id)


@router.put("/{patient_id}", response_model=PatientOut)
async def update_patient(
    db: DB, user: CurrentUser, patient_id: int, body: PatientUpdate
) -> Patient:
    patient = await get_patient_or_404(db, user.clinic_id, patient_id)
    for key, value in body.model_dump().items():
        setattr(patient, key, value)
    await db.commit()
    await db.refresh(patient)
    return patient


@router.get("/{patient_id}/appointments", response_model=list[AppointmentOut])
async def patient_appointments(db: DB, user: CurrentUser, patient_id: int) -> list[Appointment]:
    await get_patient_or_404(db, user.clinic_id, patient_id)
    rows = await db.scalars(
        select(Appointment)
        .where(Appointment.clinic_id == user.clinic_id, Appointment.patient_id == patient_id)
        .options(selectinload(Appointment.patient), selectinload(Appointment.assigned_staff))
        .order_by(Appointment.start_at.desc())
    )
    return list(rows)


@router.get("/{patient_id}/intakes", response_model=list[IntakeOut])
async def patient_intakes(db: DB, user: CurrentUser, patient_id: int) -> list[Intake]:
    await get_patient_or_404(db, user.clinic_id, patient_id)
    rows = await db.scalars(
        select(Intake)
        .where(Intake.clinic_id == user.clinic_id, Intake.patient_id == patient_id)
        .options(selectinload(Intake.patient))
        .order_by(Intake.created_at.desc())
    )
    return list(rows)
