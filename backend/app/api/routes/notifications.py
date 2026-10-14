from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import DB, AdminUser, CurrentUser, not_found
from app.models import (
    Clinic,
    Intake,
    Notification,
    NotificationKind,
    NotificationStatus,
    Patient,
)
from app.schemas.common import Page
from app.schemas.notification import NotificationOut, SendIntakeLink
from app.services.appointments import get_clinic_settings
from app.services.notify import templates
from app.services.notify.queue import enqueue

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=Page[NotificationOut])
async def list_notifications(
    db: DB,
    user: AdminUser,
    status_: NotificationStatus | None = Query(None, alias="status"),
    patient_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """送信履歴（管理者のみ）。"""
    stmt = select(Notification).where(Notification.clinic_id == user.clinic_id)
    if status_:
        stmt = stmt.where(Notification.status == status_)
    if patient_id:
        stmt = stmt.where(Notification.patient_id == patient_id)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await db.scalars(
        stmt.order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return {"items": list(rows), "total": total}


@router.post("/intakes/{intake_id}/send", response_model=list[NotificationOut], status_code=202)
async def send_intake_link(
    db: DB, user: CurrentUser, intake_id: int, body: SendIntakeLink
) -> list[Notification]:
    """問診 URL を患者にメール / SMS で送る。"""
    intake = await db.get(Intake, intake_id)
    if intake is None or intake.clinic_id != user.clinic_id:
        raise not_found("問診")
    if intake.submitted_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "この問診は回答済みです。")
    patient = await db.get(Patient, intake.patient_id)
    clinic = await db.get(Clinic, user.clinic_id)
    assert patient is not None and clinic is not None
    cs = await get_clinic_settings(db, user.clinic_id)
    queued = enqueue(
        db,
        clinic_id=user.clinic_id,
        patient=patient,
        cs=cs,
        kind=NotificationKind.INTAKE_LINK,
        message=templates.intake_link(
            name=f"{patient.last_name} {patient.first_name}",
            clinic=cs.display_name or clinic.name,
            phone=cs.phone,
            token=intake.access_token,
        ),
        appointment_id=intake.appointment_id,
        channels=set(body.channels),
    )
    if not queued:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "送信できる宛先がありません（メールアドレス・携帯番号の登録と、院の通知設定をご確認ください）。",
        )
    await db.commit()
    return queued
