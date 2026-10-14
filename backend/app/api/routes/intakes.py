import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser, not_found
from app.api.routes.patients import get_patient_or_404
from app.core.config import settings
from app.models import Appointment, AppointmentStatus, Clinic, Intake
from app.schemas.common import Page
from app.schemas.intake import IntakeAnswers, IntakeCreate, IntakeOut, PublicIntakeOut

router = APIRouter(prefix="/intakes", tags=["intakes"])
public_router = APIRouter(prefix="/public/intakes", tags=["public"])


async def _reload(db: DB, intake_id: int) -> Intake:
    intake = await db.scalar(
        select(Intake)
        .where(Intake.id == intake_id)
        .options(selectinload(Intake.patient))
        .execution_options(populate_existing=True)
    )
    assert intake is not None
    return intake


@router.get("", response_model=Page[IntakeOut])
async def list_intakes(
    db: DB,
    user: CurrentUser,
    submitted: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    stmt = select(Intake).where(Intake.clinic_id == user.clinic_id)
    if submitted is True:
        stmt = stmt.where(Intake.submitted_at.is_not(None))
    elif submitted is False:
        stmt = stmt.where(Intake.submitted_at.is_(None))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await db.scalars(
        stmt.options(selectinload(Intake.patient))
        .order_by(Intake.created_at.desc(), Intake.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return {"items": list(rows), "total": total}


@router.post("", response_model=IntakeOut, status_code=201)
async def create_intake(db: DB, user: CurrentUser, body: IntakeCreate) -> Intake:
    """問診URLを発行する。予約に紐づく問診が既にあればそれを返す。"""
    await get_patient_or_404(db, user.clinic_id, body.patient_id)

    if body.appointment_id is not None:
        appt = await db.get(Appointment, body.appointment_id)
        if appt is None or appt.clinic_id != user.clinic_id:
            raise not_found("予約")
        if appt.patient_id is not None and appt.patient_id != body.patient_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "予約の患者と問診の患者が一致していません。"
            )
        existing = await db.scalar(
            select(Intake.id).where(Intake.appointment_id == body.appointment_id)
        )
        if existing is not None:
            return await _reload(db, existing)

    intake = Intake(
        clinic_id=user.clinic_id,
        patient_id=body.patient_id,
        appointment_id=body.appointment_id,
        access_token=secrets.token_urlsafe(32),
        token_expires_at=datetime.now(UTC) + timedelta(days=settings.intake_token_expire_days),
        payload={},
    )
    db.add(intake)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "問診の発行に失敗しました。") from e
    return await _reload(db, intake.id)


@router.get("/{intake_id}", response_model=IntakeOut)
async def get_intake(db: DB, user: CurrentUser, intake_id: int) -> Intake:
    intake = await db.get(Intake, intake_id)
    if intake is None or intake.clinic_id != user.clinic_id:
        raise not_found("問診")
    return await _reload(db, intake_id)


# --- 患者向け（認証なし・トークンでアクセス） ---


async def _get_by_token(db: DB, token: str) -> Intake:
    intake = await db.scalar(
        select(Intake).where(Intake.access_token == token).options(selectinload(Intake.patient))
    )
    if intake is None or intake.token_expires_at < datetime.now(UTC):
        raise not_found("問診")
    return intake


async def _public_out(db: DB, intake: Intake) -> PublicIntakeOut:
    clinic = await db.get(Clinic, intake.clinic_id)
    answers = intake.payload.get("answers") if intake.payload else None
    return PublicIntakeOut(
        clinic_name=clinic.name if clinic else "",
        patient_display_name=f"{intake.patient.last_name} 様",
        submitted=intake.submitted_at is not None,
        expires_at=intake.token_expires_at,
        answers=IntakeAnswers.model_validate(answers) if answers else None,
    )


@public_router.get("/{token}", response_model=PublicIntakeOut)
async def public_get_intake(db: DB, token: str) -> PublicIntakeOut:
    return await _public_out(db, await _get_by_token(db, token))


@public_router.put("/{token}", response_model=PublicIntakeOut)
async def public_submit_intake(db: DB, token: str, body: IntakeAnswers) -> PublicIntakeOut:
    intake = await _get_by_token(db, token)
    if intake.submitted_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "この問診は既に送信済みです。修正は院にお問い合わせください。"
        )
    if not body.consent_agreed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "個人情報の取り扱いへの同意が必要です。"
        )

    intake.chief_complaint = body.chief_complaint
    intake.symptom_type = body.symptom_type
    intake.onset = body.onset
    intake.payload = {"version": 1, "answers": body.model_dump(mode="json")}
    intake.submitted_at = datetime.now(UTC)

    # 「問診待ち」の予約は回答をもって予約確定にする
    if intake.appointment_id is not None:
        appt = await db.get(Appointment, intake.appointment_id)
        if appt is not None and appt.status == AppointmentStatus.PENDING:
            appt.status = AppointmentStatus.BOOKED

    await db.commit()
    return await _public_out(db, intake)
