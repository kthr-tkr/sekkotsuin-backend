"""通知の登録（outbox）と送信。送信はワーカー（app/worker.py）が行う。"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.models import (
    Appointment,
    AppointmentStatus,
    Clinic,
    ClinicSettings,
    Intake,
    Notification,
    NotificationChannel,
    NotificationKind,
    NotificationStatus,
    Patient,
)
from app.services.appointments import get_clinic_settings
from app.services.notify import templates
from app.services.notify.senders import DeliveryError, mobile_e164, send_email, send_sms

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
RETRY_INTERVAL = timedelta(minutes=5)  # 失敗後は 5 分、10 分とあけて再試行する


def now() -> datetime:
    return datetime.now(UTC)


def enqueue(
    db: AsyncSession,
    *,
    clinic_id: int,
    patient: Patient,
    cs: ClinicSettings,
    kind: NotificationKind,
    message: templates.Message,
    appointment_id: int | None = None,
    channels: set[NotificationChannel] | None = None,
    email: str | None = None,
) -> list[Notification]:
    """送れる経路（メール / SMS）に通知を積む。channels を省略すると院の設定に従う。

    メールは院でメール通知が有効で、メールアドレスがある場合。SMS は院で SMS 通知が
    有効で、携帯番号（070/080/090）の場合。
    """
    want = channels or {NotificationChannel.EMAIL, NotificationChannel.SMS}
    out: list[Notification] = []
    address = email or patient.email
    if NotificationChannel.EMAIL in want and cs.notify_email_enabled and address:
        out.append(
            Notification(
                clinic_id=clinic_id,
                patient_id=patient.id,
                appointment_id=appointment_id,
                kind=kind,
                channel=NotificationChannel.EMAIL,
                to=address,
                subject=message.subject,
                body=message.email_body,
                created_at=now(),
            )
        )
    mobile = mobile_e164(patient.phone)
    if NotificationChannel.SMS in want and cs.notify_sms_enabled and mobile and message.sms_body:
        out.append(
            Notification(
                clinic_id=clinic_id,
                patient_id=patient.id,
                appointment_id=appointment_id,
                kind=kind,
                channel=NotificationChannel.SMS,
                to=mobile,
                body=message.sms_body,
                created_at=now(),
            )
        )
    db.add_all(out)
    return out


async def _context(db: AsyncSession, clinic_id: int) -> tuple[Clinic, ClinicSettings, str]:
    clinic = await db.get(Clinic, clinic_id)
    assert clinic is not None
    cs = await get_clinic_settings(db, clinic_id)
    return clinic, cs, cs.display_name or clinic.name


async def _open_intake_token(db: AsyncSession, appointment_id: int) -> str | None:
    intake = await db.scalar(select(Intake).where(Intake.appointment_id == appointment_id))
    if intake is None or intake.submitted_at is not None or intake.token_expires_at < now():
        return None
    return intake.access_token


async def notify_appointment(
    db: AsyncSession, kind: NotificationKind, appt: Appointment
) -> list[Notification]:
    """予約の受付・リマインド・キャンセルの通知を積む。"""
    if appt.patient_id is None:
        return []
    patient = await db.get(Patient, appt.patient_id)
    assert patient is not None
    clinic, cs, name = await _context(db, appt.clinic_id)
    common = {
        "name": f"{patient.last_name} {patient.first_name}",
        "clinic": name,
        "phone": cs.phone,
        "slug": clinic.booking_slug,
        "start": appt.start_at,
    }
    if kind == NotificationKind.CANCELLED:
        message = templates.cancelled(**common)
    else:
        token = await _open_intake_token(db, appt.id)
        build = (
            templates.booking_confirmed
            if kind == NotificationKind.BOOKING_CONFIRMED
            else templates.reminder
        )
        message = build(**common, menu=appt.menu_name, intake_token=token)
    return enqueue(
        db,
        clinic_id=appt.clinic_id,
        patient=patient,
        cs=cs,
        kind=kind,
        message=message,
        appointment_id=appt.id,
    )


async def schedule_reminders(db: AsyncSession) -> int:
    """リマインドの時刻になった予約に通知を積む。積んだ予約の数を返す。

    予約の受付がリマインドの時刻より後（直前の予約）の場合は、受付の通知と重なるので送らない。
    """
    rows = (
        await db.execute(
            select(Appointment, ClinicSettings.reminder_hours_before)
            .join(ClinicSettings, ClinicSettings.clinic_id == Appointment.clinic_id)
            .join(Patient, Patient.id == Appointment.patient_id)
            .where(
                ClinicSettings.reminder_hours_before > 0,
                Patient.reminders_enabled.is_(True),
                Appointment.reminder_sent_at.is_(None),
                Appointment.status.in_([AppointmentStatus.PENDING, AppointmentStatus.BOOKED]),
                Appointment.start_at > now(),
                # 院ごとの時間は SQL で比較しにくいので、最大 7 日先までを取り出して下で絞る
                Appointment.start_at <= now() + timedelta(days=7),
            )
            .with_for_update(of=Appointment, skip_locked=True)
        )
    ).all()
    count = 0
    for appt, hours in rows:
        remind_at = appt.start_at - timedelta(hours=hours)
        if remind_at > now():
            continue
        appt.reminder_sent_at = now()
        if appt.created_at < remind_at:
            await notify_appointment(db, NotificationKind.REMINDER, appt)
            count += 1
    await db.commit()
    return count


async def send_one() -> bool:
    """送信待ちの通知を 1 件送る。送ったら（失敗も含め処理したら）True。"""
    async with SessionLocal() as db:
        n = await db.scalar(
            select(Notification)
            .where(
                Notification.status == NotificationStatus.QUEUED,
                Notification.attempts < MAX_ATTEMPTS,
                or_(Notification.next_attempt_at.is_(None), Notification.next_attempt_at <= now()),
            )
            .order_by(Notification.created_at, Notification.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if n is None:
            return False
        n.attempts += 1
        try:
            if n.channel == NotificationChannel.EMAIL:
                _, _, name = await _context(db, n.clinic_id)
                await send_email(n.to, n.subject, n.body, from_name=name)
            else:
                await send_sms(n.to, n.body)
            n.status = NotificationStatus.SENT
            n.sent_at = now()
            n.error_message = ""
        except Exception as e:  # noqa: BLE001 - 失敗は通知に記録して再試行する
            log.warning("notification %s failed: %s", n.id, e)
            n.error_message = (str(e) if isinstance(e, DeliveryError) else repr(e))[:500]
            if n.attempts >= MAX_ATTEMPTS:
                n.status = NotificationStatus.FAILED
            else:
                n.next_attempt_at = now() + RETRY_INTERVAL * n.attempts
        await db.commit()
        return True


async def send_pending(limit: int = 100) -> int:
    count = 0
    while count < limit and await send_one():
        count += 1
    return count
