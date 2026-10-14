from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import AwareDatetime
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser, not_found
from app.api.routes.patients import get_patient_or_404
from app.models import (
    Appointment,
    AppointmentStatus,
    ClinicalNote,
    ClinicalNoteRevision,
    ClinicalNoteStatus,
    Intake,
    User,
)
from app.schemas.clinical_note import (
    ClinicalNoteCreate,
    ClinicalNoteOut,
    ClinicalNoteRevisionOut,
    ClinicalNoteUpdate,
)
from app.schemas.common import Page

router = APIRouter(prefix="/clinical-notes", tags=["clinical-notes"])

_LOAD = (selectinload(ClinicalNote.patient), selectinload(ClinicalNote.practitioner))


async def _reload(db: DB, note_id: int) -> ClinicalNote:
    note = await db.scalar(
        select(ClinicalNote)
        .where(ClinicalNote.id == note_id)
        .options(*_LOAD)
        .execution_options(populate_existing=True)
    )
    assert note is not None
    return note


async def _get_or_404(db: DB, clinic_id: int, note_id: int) -> ClinicalNote:
    note = await db.get(ClinicalNote, note_id)
    if note is None or note.clinic_id != clinic_id:
        raise not_found("カルテ")
    return note


@router.get("", response_model=Page[ClinicalNoteOut])
async def list_notes(
    db: DB,
    user: CurrentUser,
    patient_id: int | None = None,
    status_: ClinicalNoteStatus | None = Query(None, alias="status"),
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    stmt = select(ClinicalNote).where(ClinicalNote.clinic_id == user.clinic_id)
    if patient_id is not None:
        stmt = stmt.where(ClinicalNote.patient_id == patient_id)
    if status_ is not None:
        stmt = stmt.where(ClinicalNote.status == status_)
    if start is not None:
        stmt = stmt.where(ClinicalNote.visited_at >= start)
    if end is not None:
        stmt = stmt.where(ClinicalNote.visited_at < end)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await db.scalars(
        stmt.options(*_LOAD)
        .order_by(ClinicalNote.visited_at.desc(), ClinicalNote.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return {"items": list(rows), "total": total}


@router.post("", response_model=ClinicalNoteOut, status_code=201)
async def create_note(db: DB, user: CurrentUser, body: ClinicalNoteCreate) -> ClinicalNote:
    """カルテを作成する。予約に紐づくカルテが既にあればそれを返す。"""
    if body.appointment_id is not None:
        appt = await db.get(Appointment, body.appointment_id)
        if appt is None or appt.clinic_id != user.clinic_id:
            raise not_found("予約")
        if appt.patient_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "患者が設定されていない予約です。"
            )
        existing = await db.scalar(
            select(ClinicalNote.id).where(ClinicalNote.appointment_id == appt.id)
        )
        if existing is not None:
            return await _reload(db, existing)

        intake = await db.scalar(select(Intake).where(Intake.appointment_id == appt.id))
        note = ClinicalNote(
            clinic_id=user.clinic_id,
            patient_id=appt.patient_id,
            appointment_id=appt.id,
            intake_id=intake.id if intake else None,
            practitioner_id=appt.assigned_staff_id or user.id,
            visited_at=appt.start_at,
            # 問診の主訴と痛みの強さを S と施術前 PS の初期値にする
            subjective=intake.chief_complaint if intake and intake.submitted_at else "",
            pain_scale_before=(
                (intake.payload.get("answers") or {}).get("pain_scale") if intake else None
            ),
        )
    else:
        if body.patient_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "appointment_id か patient_id のどちらかを指定してください。",
            )
        await get_patient_or_404(db, user.clinic_id, body.patient_id)
        note = ClinicalNote(
            clinic_id=user.clinic_id,
            patient_id=body.patient_id,
            practitioner_id=user.id,
            visited_at=body.visited_at or datetime.now(UTC),
        )

    note.created_by_id = user.id
    note.updated_by_id = user.id
    db.add(note)
    await db.commit()
    return await _reload(db, note.id)


@router.get("/{note_id}", response_model=ClinicalNoteOut)
async def get_note(db: DB, user: CurrentUser, note_id: int) -> ClinicalNote:
    await _get_or_404(db, user.clinic_id, note_id)
    return await _reload(db, note_id)


@router.put("/{note_id}", response_model=ClinicalNoteOut)
async def update_note(
    db: DB, user: CurrentUser, note_id: int, body: ClinicalNoteUpdate
) -> ClinicalNote:
    note = await _get_or_404(db, user.clinic_id, note_id)
    if body.practitioner_id is not None:
        staff = await db.get(User, body.practitioner_id)
        if staff is None or staff.clinic_id != user.clinic_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "担当者が見つかりません。")

    before = note.snapshot()
    for key, value in body.model_dump().items():
        setattr(note, key, value)
    if note.snapshot() == before:
        return await _reload(db, note_id)

    db.add(
        ClinicalNoteRevision(
            note_id=note.id,
            snapshot=before,
            edited_by_id=user.id,
            created_at=datetime.now(UTC),
        )
    )
    note.updated_by_id = user.id
    await db.commit()
    return await _reload(db, note_id)


@router.post("/{note_id}/finalize", response_model=ClinicalNoteOut)
async def finalize_note(db: DB, user: CurrentUser, note_id: int) -> ClinicalNote:
    """カルテを確定する。予約があれば「完了」にする。"""
    note = await _get_or_404(db, user.clinic_id, note_id)
    if note.status != ClinicalNoteStatus.FINALIZED:
        note.status = ClinicalNoteStatus.FINALIZED
        note.finalized_at = datetime.now(UTC)
        note.finalized_by_id = user.id
        if note.appointment_id is not None:
            appt = await db.get(Appointment, note.appointment_id)
            if appt is not None and appt.status in (
                AppointmentStatus.PENDING,
                AppointmentStatus.BOOKED,
                AppointmentStatus.ARRIVED,
            ):
                appt.status = AppointmentStatus.COMPLETED
        await db.commit()
    return await _reload(db, note_id)


@router.get("/{note_id}/revisions", response_model=list[ClinicalNoteRevisionOut])
async def list_revisions(db: DB, user: CurrentUser, note_id: int) -> list[ClinicalNoteRevision]:
    await _get_or_404(db, user.clinic_id, note_id)
    rows = await db.scalars(
        select(ClinicalNoteRevision)
        .where(ClinicalNoteRevision.note_id == note_id)
        .options(selectinload(ClinicalNoteRevision.edited_by))
        .order_by(ClinicalNoteRevision.created_at.desc(), ClinicalNoteRevision.id.desc())
    )
    return list(rows)
