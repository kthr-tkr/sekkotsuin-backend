from collections import defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import DB, AdminUser
from app.core.config import settings
from app.models import (
    Appointment,
    AppointmentStatus,
    ClinicalNote,
    Patient,
    SalesRecord,
    SalesStatus,
    User,
)
from app.schemas.operations import Kpi, KpiDaily, KpiSource, KpiStaff
from app.services.ai.quota import month_range

router = APIRouter(prefix="/kpi", tags=["kpi"])


@router.get("", response_model=Kpi)
async def kpi(
    db: DB,
    user: AdminUser,
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$", description="YYYY-MM"),
) -> Kpi:
    today = datetime.now(settings.tz).date()
    first = date.fromisoformat(f"{month}-01") if month else today.replace(day=1)
    start, end = month_range(first)
    d_start, d_end = start.date(), end.date()
    prev_start, _ = month_range(d_start - timedelta(days=1))
    cid = user.clinic_id

    sales = list(
        await db.scalars(
            select(SalesRecord).where(
                SalesRecord.clinic_id == cid,
                SalesRecord.treatment_date >= d_start,
                SalesRecord.treatment_date < d_end,
            )
        )
    )
    paid = [s for s in sales if s.status == SalesStatus.PAID]
    unpaid = [s for s in sales if s.status == SalesStatus.UNPAID]
    prev_total = await db.scalar(
        select(func.coalesce(func.sum(SalesRecord.amount), 0)).where(
            SalesRecord.clinic_id == cid,
            SalesRecord.status == SalesStatus.PAID,
            SalesRecord.treatment_date >= prev_start.date(),
            SalesRecord.treatment_date < d_start,
        )
    )

    appts = list(
        await db.scalars(
            select(Appointment).where(
                Appointment.clinic_id == cid,
                Appointment.start_at >= start,
                Appointment.start_at < end,
            )
        )
    )
    done = [a for a in appts if a.status == AppointmentStatus.COMPLETED]
    cancels = [
        a for a in appts if a.status in (AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW)
    ]

    new_patients = await db.scalar(
        select(func.count()).where(
            Patient.clinic_id == cid, Patient.created_at >= start, Patient.created_at < end
        )
    )

    daily: dict[date, KpiDaily] = {}
    d = d_start
    while d < d_end:
        daily[d] = KpiDaily(date=d, sales=0, visits=0)
        d += timedelta(days=1)
    for s in paid:
        daily[s.treatment_date].sales += s.amount
    for a in done:
        daily[a.start_at.astimezone(settings.tz).date()].visits += 1

    sources: dict[str, int] = defaultdict(int)
    for a in appts:
        if a.status not in (AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW):
            sources[a.booking_source.value] += 1

    notes_by_staff: dict[int, int] = defaultdict(int)
    for practitioner_id, count in await db.execute(
        select(ClinicalNote.practitioner_id, func.count())
        .where(
            ClinicalNote.clinic_id == cid,
            ClinicalNote.visited_at >= start,
            ClinicalNote.visited_at < end,
            ClinicalNote.practitioner_id.is_not(None),
        )
        .group_by(ClinicalNote.practitioner_id)
    ):
        notes_by_staff[practitioner_id] = count
    staff_rows: list[KpiStaff] = []
    for s in await db.scalars(select(User).where(User.clinic_id == cid).order_by(User.id)):
        row = KpiStaff(
            staff_id=s.id,
            name=s.full_name or s.username,
            sales=sum(x.amount for x in paid if x.staff_id == s.id),
            visits=sum(1 for a in done if a.assigned_staff_id == s.id),
            notes=notes_by_staff.get(s.id, 0),
        )
        if row.sales or row.visits or row.notes or s.is_active:
            staff_rows.append(row)

    total = sum(s.amount for s in paid)
    return Kpi(
        month=first.strftime("%Y-%m"),
        sales_total=total,
        sales_total_prev_month=prev_total or 0,
        paid_count=len(paid),
        average_spend=round(total / len(paid)) if paid else 0,
        unpaid_count=len(unpaid),
        unpaid_amount=sum(s.amount for s in unpaid),
        appointments=len(appts),
        visits=len(done),
        cancellations=len(cancels),
        cancel_rate=round(len(cancels) / len(appts), 3) if appts else 0,
        new_patients=new_patients or 0,
        daily=list(daily.values()),
        booking_sources=[
            KpiSource(source=k, count=v)  # type: ignore[arg-type]
            for k, v in sorted(sources.items(), key=lambda kv: -kv[1])
        ],
        by_staff=sorted(staff_rows, key=lambda r: (-r.sales, -r.visits, r.staff_id)),
    )
