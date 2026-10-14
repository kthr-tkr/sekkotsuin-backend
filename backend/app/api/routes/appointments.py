from datetime import date

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import AwareDatetime
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser, not_found
from app.models import Appointment, AppointmentStatus, NotificationKind
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentOut,
    AppointmentUpdate,
    AvailabilitySlot,
)
from app.services import appointments as svc
from app.services.notify.queue import notify_appointment

router = APIRouter(prefix="/appointments", tags=["appointments"])

_LOAD = (selectinload(Appointment.patient), selectinload(Appointment.assigned_staff))


async def _reload(db: DB, appt_id: int) -> Appointment:
    appt = await db.scalar(
        select(Appointment)
        .where(Appointment.id == appt_id)
        .options(*_LOAD)
        .execution_options(populate_existing=True)
    )
    assert appt is not None
    return appt


@router.get("", response_model=list[AppointmentOut])
async def list_appointments(
    db: DB,
    user: CurrentUser,
    start: AwareDatetime = Query(description="この日時以降に終了する予約"),
    end: AwareDatetime = Query(description="この日時より前に開始する予約"),
    staff_id: int | None = None,
    include_cancelled: bool = False,
) -> list[Appointment]:
    stmt = (
        select(Appointment)
        .where(
            Appointment.clinic_id == user.clinic_id,
            Appointment.start_at < end,
            Appointment.end_at > start,
        )
        .options(*_LOAD)
        .order_by(Appointment.start_at)
    )
    if staff_id is not None:
        stmt = stmt.where(Appointment.assigned_staff_id == staff_id)
    if not include_cancelled:
        stmt = stmt.where(
            Appointment.status.not_in([AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW])
        )
    return list(await db.scalars(stmt))


@router.get("/availability", response_model=list[AvailabilitySlot])
async def get_availability(
    db: DB,
    user: CurrentUser,
    day: date = Query(alias="date"),
    duration_minutes: int = Query(30, ge=5, le=480),
    staff_id: int | None = None,
) -> list[AvailabilitySlot]:
    slots = await svc.availability(
        db,
        clinic_id=user.clinic_id,
        day=day,
        duration_minutes=duration_minutes,
        staff_id=staff_id,
    )
    await db.commit()
    return [AvailabilitySlot(start_at=s, end_at=e, available=a) for s, e, a in slots]


@router.post("", response_model=AppointmentOut, status_code=201)
async def create_appointment(db: DB, user: CurrentUser, body: AppointmentCreate) -> Appointment:
    appt = Appointment(
        clinic_id=user.clinic_id,
        created_by_id=user.id,
        **body.model_dump(exclude={"end_at", "notify_patient"}),
        end_at=body.end_at,
    )
    await svc.validate_and_apply(
        db,
        appt,
        clinic_id=user.clinic_id,
        menu_changed=True,
        end_given=body.end_at is not None,
    )
    db.add(appt)
    if body.notify_patient:
        await db.flush()
        await notify_appointment(db, NotificationKind.BOOKING_CONFIRMED, appt)
    await db.commit()
    return await _reload(db, appt.id)


async def _get_or_404(db: DB, clinic_id: int, appt_id: int) -> Appointment:
    appt = await db.get(Appointment, appt_id)
    if appt is None or appt.clinic_id != clinic_id:
        raise not_found("予約")
    return appt


@router.get("/{appt_id}", response_model=AppointmentOut)
async def get_appointment(db: DB, user: CurrentUser, appt_id: int) -> Appointment:
    await _get_or_404(db, user.clinic_id, appt_id)
    return await _reload(db, appt_id)


@router.patch("/{appt_id}", response_model=AppointmentOut)
async def update_appointment(
    db: DB, user: CurrentUser, appt_id: int, body: AppointmentUpdate
) -> Appointment:
    appt = await _get_or_404(db, user.clinic_id, appt_id)
    data = body.model_dump(exclude_unset=True)
    for key in ("start_at", "end_at", "status", "booking_source", "notes"):
        if key in data and data[key] is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"{key} は null にできません。"
            )
    duration = appt.end_at - appt.start_at
    for key, value in data.items():
        setattr(appt, key, value)

    menu_changed = "treatment_menu_id" in data
    end_given = "end_at" in data
    if "start_at" in data and not end_given and not menu_changed:
        # 開始時刻だけ動かした場合（ドラッグ移動など）は所要時間を保つ
        appt.end_at = appt.start_at + duration
        end_given = True
    await svc.validate_and_apply(
        db, appt, clinic_id=user.clinic_id, menu_changed=menu_changed, end_given=end_given
    )
    await db.commit()
    return await _reload(db, appt_id)


@router.delete("/{appt_id}", status_code=204)
async def delete_appointment(db: DB, user: CurrentUser, appt_id: int) -> None:
    appt = await _get_or_404(db, user.clinic_id, appt_id)
    await db.delete(appt)
    await db.commit()
