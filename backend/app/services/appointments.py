from datetime import date, datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import (
    Appointment,
    ClinicSettings,
    LeaveStatus,
    Patient,
    Role,
    ShiftStatus,
    StaffLeave,
    StaffShift,
    TreatmentMenu,
    User,
)
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


FULL_DAY_LEAVES = ("paid_leave", "absence", "training", "other")


async def _working_windows(
    db: AsyncSession, clinic_id: int, day: date, cs: ClinicSettings, staff_ids: list[int]
) -> dict[int, tuple[datetime, datetime] | None]:
    """施術者ごとのその日の勤務時間帯（勤務しない場合は None）。

    シフトがあればシフトの時間、無ければ営業時間。承認済みの休暇を反映する。
    """
    tz = settings.tz
    open_t, close_t = cs.business_start_time, cs.business_end_time
    noon = cs.break_start_time or time(13, 0)
    afternoon = cs.break_end_time or time(13, 0)

    shifts = {
        s.staff_id: s
        for s in await db.scalars(
            select(StaffShift).where(StaffShift.clinic_id == clinic_id, StaffShift.date == day)
        )
    }
    leaves = list(
        await db.scalars(
            select(StaffLeave).where(
                StaffLeave.clinic_id == clinic_id,
                StaffLeave.status == LeaveStatus.APPROVED,
                StaffLeave.start_date <= day,
                StaffLeave.end_date >= day,
            )
        )
    )

    windows: dict[int, tuple[datetime, datetime] | None] = {}
    for sid in staff_ids:
        shift = shifts.get(sid)
        if shift is not None and (shift.status == ShiftStatus.OFF or not shift.start_time):
            windows[sid] = None
            continue
        start_t = shift.start_time if shift else open_t
        end_t = shift.end_time if shift and shift.end_time else close_t
        for lv in (lv for lv in leaves if lv.staff_id == sid):
            if lv.leave_type.value in FULL_DAY_LEAVES:
                start_t = end_t  # 終日不在
            elif lv.leave_type.value == "morning_off":
                start_t = max(start_t, afternoon)
            elif lv.leave_type.value == "afternoon_off":
                end_t = min(end_t, noon)
        windows[sid] = (
            (datetime.combine(day, start_t, tz), datetime.combine(day, end_t, tz))
            if start_t < end_t
            else None
        )
    return windows


async def availability(
    db: AsyncSession,
    *,
    clinic_id: int,
    day: date,
    duration_minutes: int,
    staff_id: int | None,
) -> list[tuple[datetime, datetime, bool]]:
    """指定日の予約枠と空き状況を返す。

    シフトと承認済みの休暇から施術者ごとの勤務時間帯を求め、
    その枠に勤務している施術者のうち予約の入っていない人がいれば空きとする。
    staff_id 指定時はその担当者だけで判定する。
    """
    cs = await get_clinic_settings(db, clinic_id)
    if WEEKDAYS[day.weekday()] in (cs.closed_weekdays or []):
        return []

    tz = settings.tz
    day_start = datetime.combine(day, time.min, tz)
    day_end = day_start + timedelta(days=1)

    if staff_id is not None:
        staff_ids = [staff_id]
    else:
        # 施術者ロールがいない院（院長 1 人など）は管理者を施術者として数える
        for role in (Role.PRACTITIONER, Role.ADMIN):
            staff_ids = list(
                await db.scalars(
                    select(User.id).where(
                        User.clinic_id == clinic_id, User.is_active.is_(True), User.role == role
                    )
                )
            )
            if staff_ids:
                break
    windows = await _working_windows(db, clinic_id, day, cs, staff_ids)

    booked = (
        await db.execute(
            select(Appointment.start_at, Appointment.end_at, Appointment.assigned_staff_id).where(
                Appointment.clinic_id == clinic_id,
                Appointment.status.in_(BLOCKING_STATUSES),
                Appointment.start_at < day_end,
                Appointment.end_at > day_start,
            )
        )
    ).all()

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

        def overlaps(s: datetime, e: datetime, a: datetime = cursor, b: datetime = end) -> bool:
            return s < b and e > a

        # この枠に勤務していて、自分の予約が入っていない施術者
        free = [
            sid
            for sid, w in windows.items()
            if w is not None
            and w[0] <= cursor
            and end <= w[1]
            and not any(st == sid and overlaps(s, e) for s, e, st in booked)
        ]
        if staff_id is not None:
            available = bool(free)
        else:
            # 担当者未定の予約も、空いている施術者を1人ずつ埋めるとみなす
            unassigned = sum(1 for s, e, st in booked if st is None and overlaps(s, e))
            available = len(free) > unassigned
        slots.append((cursor, end, available))
        cursor += step
    return slots
