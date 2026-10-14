from datetime import date, datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Appointment, ClinicSettings, Patient, Role, TreatmentMenu, User
from app.models.appointment import BLOCKING_STATUSES
from app.models.clinic import WEEKDAYS

STAFF_ROLES = (Role.ADMIN, Role.RECEPTION, Role.PRACTITIONER)


def _invalid(field: str, message: str) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        [{"loc": ["body", field], "msg": message, "type": "value_error"}],
    )


async def get_clinic_settings(db: AsyncSession, clinic_id: int) -> ClinicSettings:
    cs = await db.scalar(select(ClinicSettings).where(ClinicSettings.clinic_id == clinic_id))
    if cs is None:
        cs = ClinicSettings(clinic_id=clinic_id)
        db.add(cs)
        await db.flush()
    return cs


async def validate_and_apply(
    db: AsyncSession, appt: Appointment, *, clinic_id: int, menu_changed: bool, end_given: bool
) -> None:
    """関連の院一致チェック、終了時刻の補完、担当者の重複チェックを行う。"""
    if appt.patient_id is not None:
        patient = await db.get(Patient, appt.patient_id)
        if patient is None or patient.clinic_id != clinic_id:
            raise _invalid("patient_id", "患者が見つかりません。")

    menu: TreatmentMenu | None = None
    if appt.treatment_menu_id is not None:
        menu = await db.get(TreatmentMenu, appt.treatment_menu_id)
        if menu is None or menu.clinic_id != clinic_id:
            raise _invalid("treatment_menu_id", "施術メニューが見つかりません。")
        if menu_changed:
            appt.menu_name = menu.name
    elif menu_changed:
        appt.menu_name = ""

    if not end_given and (menu_changed or appt.end_at is None):
        if menu is not None:
            minutes = menu.duration_minutes
        else:
            minutes = (await get_clinic_settings(db, clinic_id)).appointment_interval_minutes
        appt.end_at = appt.start_at + timedelta(minutes=minutes)

    if appt.end_at <= appt.start_at:
        raise _invalid("end_at", "終了時刻は開始時刻より後にしてください。")

    if appt.assigned_staff_id is not None:
        # 担当者行をロックして、同時の予約登録による重複を防ぐ
        staff = await db.scalar(
            select(User).where(User.id == appt.assigned_staff_id).with_for_update()
        )
        if staff is None or staff.clinic_id != clinic_id or not staff.is_active:
            raise _invalid("assigned_staff_id", "担当者が見つかりません。")

        if appt.status in BLOCKING_STATUSES:
            stmt = select(func.count()).where(
                Appointment.clinic_id == clinic_id,
                Appointment.assigned_staff_id == appt.assigned_staff_id,
                Appointment.status.in_(BLOCKING_STATUSES),
                Appointment.start_at < appt.end_at,
                Appointment.end_at > appt.start_at,
            )
            if appt.id is not None:
                stmt = stmt.where(Appointment.id != appt.id)
            if await db.scalar(stmt):
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "担当者の同時間帯に既に予約が入っています。"
                )


async def availability(
    db: AsyncSession,
    *,
    clinic_id: int,
    day: date,
    duration_minutes: int,
    staff_id: int | None,
) -> list[tuple[datetime, datetime, bool]]:
    """指定日の予約枠と空き状況を返す。

    staff_id 指定時はその担当者の空き、未指定時は「施術者数 > 重複予約数」で空きと判定する。
    """
    cs = await get_clinic_settings(db, clinic_id)
    if WEEKDAYS[day.weekday()] in (cs.closed_weekdays or []):
        return []

    tz = settings.tz
    day_start = datetime.combine(day, time.min, tz)
    day_end = day_start + timedelta(days=1)

    stmt = select(Appointment.start_at, Appointment.end_at).where(
        Appointment.clinic_id == clinic_id,
        Appointment.status.in_(BLOCKING_STATUSES),
        Appointment.start_at < day_end,
        Appointment.end_at > day_start,
    )
    if staff_id is not None:
        stmt = stmt.where(Appointment.assigned_staff_id == staff_id)
        capacity = 1
    else:
        capacity = (
            await db.scalar(
                select(func.count()).where(
                    User.clinic_id == clinic_id,
                    User.is_active.is_(True),
                    User.role == Role.PRACTITIONER,
                )
            )
        ) or 1
    booked = (await db.execute(stmt)).all()

    open_at = datetime.combine(day, cs.business_start_time, tz)
    close_at = datetime.combine(day, cs.business_end_time, tz)
    break_range = None
    if cs.break_start_time and cs.break_end_time:
        break_range = (
            datetime.combine(day, cs.break_start_time, tz),
            datetime.combine(day, cs.break_end_time, tz),
        )

    step = timedelta(minutes=cs.appointment_interval_minutes)
    duration = timedelta(minutes=duration_minutes)
    slots: list[tuple[datetime, datetime, bool]] = []
    cursor = open_at
    while cursor + duration <= close_at:
        end = cursor + duration
        if break_range and cursor < break_range[1] and end > break_range[0]:
            cursor += step
            continue
        overlapping = sum(1 for s, e in booked if s < end and e > cursor)
        slots.append((cursor, end, overlapping < capacity))
        cursor += step
    return slots
