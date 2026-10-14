from datetime import date

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser, not_found
from app.api.routes.patients import get_patient_or_404
from app.core.config import settings
from app.models import (
    Appointment,
    ClinicalNote,
    SalesRecord,
    SalesStatus,
    TreatmentMenu,
    User,
)
from app.schemas.operations import SalesCreate, SalesOut, SalesPage, SalesUpdate

router = APIRouter(prefix="/sales", tags=["sales"])

_LOAD = (selectinload(SalesRecord.patient), selectinload(SalesRecord.staff))


def _invalid(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg)


async def _validate_refs(db: DB, clinic_id: int, body: SalesCreate | SalesUpdate) -> None:
    await get_patient_or_404(db, clinic_id, body.patient_id)
    if body.appointment_id is not None:
        a = await db.get(Appointment, body.appointment_id)
        if a is None or a.clinic_id != clinic_id or a.patient_id not in (None, body.patient_id):
            raise _invalid("予約が見つからないか、患者が一致しません。")
    if body.clinical_note_id is not None:
        n = await db.get(ClinicalNote, body.clinical_note_id)
        if n is None or n.clinic_id != clinic_id or n.patient_id != body.patient_id:
            raise _invalid("カルテが見つからないか、患者が一致しません。")
    if body.treatment_menu_id is not None:
        m = await db.get(TreatmentMenu, body.treatment_menu_id)
        if m is None or m.clinic_id != clinic_id:
            raise _invalid("施術メニューが見つかりません。")
    if body.staff_id is not None:
        s = await db.get(User, body.staff_id)
        if s is None or s.clinic_id != clinic_id:
            raise _invalid("担当者が見つかりません。")


async def _reload(db: DB, record_id: int) -> SalesRecord:
    r = await db.scalar(
        select(SalesRecord)
        .where(SalesRecord.id == record_id)
        .options(*_LOAD)
        .execution_options(populate_existing=True)
    )
    assert r is not None
    return r


@router.get("", response_model=SalesPage)
async def list_sales(
    db: DB,
    user: CurrentUser,
    start: date | None = None,
    end: date | None = Query(None, description="この日を含む"),
    status_: SalesStatus | None = Query(None, alias="status"),
    patient_id: int | None = None,
    clinical_note_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    stmt = select(SalesRecord).where(SalesRecord.clinic_id == user.clinic_id)
    if start:
        stmt = stmt.where(SalesRecord.treatment_date >= start)
    if end:
        stmt = stmt.where(SalesRecord.treatment_date <= end)
    if status_:
        stmt = stmt.where(SalesRecord.status == status_)
    if patient_id:
        stmt = stmt.where(SalesRecord.patient_id == patient_id)
    if clinical_note_id:
        stmt = stmt.where(SalesRecord.clinical_note_id == clinical_note_id)

    sub = stmt.subquery()
    total, paid, unpaid = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(case((sub.c.status == SalesStatus.PAID, sub.c.amount))), 0),
                func.coalesce(
                    func.sum(case((sub.c.status == SalesStatus.UNPAID, sub.c.amount))), 0
                ),
            ).select_from(sub)
        )
    ).one()
    rows = await db.scalars(
        stmt.options(*_LOAD)
        .order_by(SalesRecord.treatment_date.desc(), SalesRecord.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return {"items": list(rows), "total": total, "paid_amount": paid, "unpaid_amount": unpaid}


@router.get("/draft", response_model=SalesCreate)
async def sales_draft(db: DB, user: CurrentUser, clinical_note_id: int) -> SalesCreate:
    """カルテから会計の初期値を作る（予約のメニュー名・料金、担当者、施術日）。"""
    note = await db.get(ClinicalNote, clinical_note_id)
    if note is None or note.clinic_id != user.clinic_id:
        raise not_found("カルテ")
    draft = SalesCreate(
        patient_id=note.patient_id,
        clinical_note_id=note.id,
        appointment_id=note.appointment_id,
        staff_id=note.practitioner_id,
        treatment_date=note.visited_at.astimezone(settings.tz).date(),
        amount=0,
    )
    if note.appointment_id and (appt := await db.get(Appointment, note.appointment_id)):
        draft.description = appt.menu_name
        if appt.treatment_menu_id and (menu := await db.get(TreatmentMenu, appt.treatment_menu_id)):
            draft.treatment_menu_id = menu.id
            draft.amount = menu.price
    return draft


@router.post("", response_model=SalesOut, status_code=201)
async def create_sales(db: DB, user: CurrentUser, body: SalesCreate) -> SalesRecord:
    await _validate_refs(db, user.clinic_id, body)
    r = SalesRecord(clinic_id=user.clinic_id, **body.model_dump())
    db.add(r)
    await db.commit()
    return await _reload(db, r.id)


@router.put("/{record_id}", response_model=SalesOut)
async def update_sales(db: DB, user: CurrentUser, record_id: int, body: SalesUpdate) -> SalesRecord:
    r = await db.get(SalesRecord, record_id)
    if r is None or r.clinic_id != user.clinic_id:
        raise not_found("売上")
    await _validate_refs(db, user.clinic_id, body)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    await db.commit()
    return await _reload(db, record_id)
