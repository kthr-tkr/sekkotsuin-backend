import base64
import binascii
from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser, not_found
from app.api.routes.patients import get_patient_or_404
from app.core.config import settings
from app.models import (
    ClinicalNote,
    TreatmentPlan,
    TreatmentPlanConsent,
    TreatmentPlanStatus,
)
from app.schemas.clinical_note import ClinicalNoteOut
from app.schemas.common import Page
from app.schemas.treatment_plan import (
    ConsentCreate,
    ConsentOut,
    TreatmentPlanCreate,
    TreatmentPlanOut,
    TreatmentPlanUpdate,
)
from app.services.storage import signed_url, storage

router = APIRouter(prefix="/treatment-plans", tags=["treatment-plans"])

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _today() -> date:
    return datetime.now(settings.tz).date()


def _consent_out(c: TreatmentPlanConsent) -> ConsentOut:
    out = ConsentOut.model_validate(c)
    out.signature_url = signed_url(c.signature_key)
    return out


async def _plan_out(db: DB, plan: TreatmentPlan) -> TreatmentPlanOut:
    latest = await db.scalar(
        select(TreatmentPlanConsent)
        .where(TreatmentPlanConsent.plan_id == plan.id)
        .options(selectinload(TreatmentPlanConsent.witnessed_by))
        .order_by(TreatmentPlanConsent.signed_at.desc(), TreatmentPlanConsent.id.desc())
        .limit(1)
    )
    out = TreatmentPlanOut.model_validate(plan)
    if latest is not None:
        out.latest_consent = _consent_out(latest)
        out.consent_outdated = latest.plan_snapshot != plan.content_snapshot()
    return out


async def _get_or_404(db: DB, clinic_id: int, plan_id: int) -> TreatmentPlan:
    plan = await db.scalar(
        select(TreatmentPlan)
        .where(TreatmentPlan.id == plan_id)
        .options(selectinload(TreatmentPlan.patient))
        .execution_options(populate_existing=True)
    )
    if plan is None or plan.clinic_id != clinic_id:
        raise not_found("施術計画")
    return plan


@router.get("", response_model=Page[TreatmentPlanOut])
async def list_plans(
    db: DB,
    user: CurrentUser,
    patient_id: int | None = None,
    status_: TreatmentPlanStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    stmt = select(TreatmentPlan).where(TreatmentPlan.clinic_id == user.clinic_id)
    if patient_id is not None:
        stmt = stmt.where(TreatmentPlan.patient_id == patient_id)
    if status_ is not None:
        stmt = stmt.where(TreatmentPlan.status == status_)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    plans = await db.scalars(
        stmt.options(selectinload(TreatmentPlan.patient))
        .order_by(TreatmentPlan.start_date.desc(), TreatmentPlan.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return {"items": [await _plan_out(db, p) for p in plans], "total": total}


@router.post("", response_model=TreatmentPlanOut, status_code=201)
async def create_plan(db: DB, user: CurrentUser, body: TreatmentPlanCreate) -> TreatmentPlanOut:
    await get_patient_or_404(db, user.clinic_id, body.patient_id)
    plan = TreatmentPlan(
        clinic_id=user.clinic_id,
        patient_id=body.patient_id,
        start_date=body.start_date or _today(),
        created_by_id=user.id,
    )
    if body.clinical_note_id is not None:
        note = await db.get(ClinicalNote, body.clinical_note_id)
        if note is None or note.clinic_id != user.clinic_id or note.patient_id != body.patient_id:
            raise not_found("カルテ")
        plan.clinical_note_id = note.id
        plan.chief_complaint = note.subjective.splitlines()[0][:255] if note.subjective else ""
        plan.title = note.assessment.splitlines()[0][:200] if note.assessment else ""
        plan.start_date = body.start_date or note.visited_at.astimezone(settings.tz).date()
    db.add(plan)
    await db.commit()
    return await _plan_out(db, await _get_or_404(db, user.clinic_id, plan.id))


@router.get("/{plan_id}", response_model=TreatmentPlanOut)
async def get_plan(db: DB, user: CurrentUser, plan_id: int) -> TreatmentPlanOut:
    return await _plan_out(db, await _get_or_404(db, user.clinic_id, plan_id))


@router.put("/{plan_id}", response_model=TreatmentPlanOut)
async def update_plan(
    db: DB, user: CurrentUser, plan_id: int, body: TreatmentPlanUpdate
) -> TreatmentPlanOut:
    plan = await _get_or_404(db, user.clinic_id, plan_id)
    was_active = plan.status == TreatmentPlanStatus.ACTIVE
    for key, value in body.model_dump().items():
        setattr(plan, key, value)
    if was_active and plan.status != TreatmentPlanStatus.ACTIVE:
        plan.end_date = _today()
    elif plan.status == TreatmentPlanStatus.ACTIVE:
        plan.end_date = None
    await db.commit()
    return await _plan_out(db, await _get_or_404(db, user.clinic_id, plan_id))


@router.get("/{plan_id}/progress", response_model=list[ClinicalNoteOut])
async def plan_progress(db: DB, user: CurrentUser, plan_id: int) -> list[ClinicalNote]:
    """計画期間中のカルテ（施術経過）を古い順に返す。"""
    plan = await _get_or_404(db, user.clinic_id, plan_id)
    start = datetime.combine(plan.start_date, time.min, settings.tz)
    stmt = select(ClinicalNote).where(
        ClinicalNote.clinic_id == user.clinic_id,
        ClinicalNote.patient_id == plan.patient_id,
        ClinicalNote.visited_at >= start,
    )
    if plan.end_date is not None:
        end = datetime.combine(plan.end_date + timedelta(days=1), time.min, settings.tz)
        stmt = stmt.where(ClinicalNote.visited_at < end)
    rows = await db.scalars(
        stmt.options(
            selectinload(ClinicalNote.patient), selectinload(ClinicalNote.practitioner)
        ).order_by(ClinicalNote.visited_at)
    )
    return list(rows)


@router.get("/{plan_id}/consents", response_model=list[ConsentOut])
async def list_consents(db: DB, user: CurrentUser, plan_id: int) -> list[ConsentOut]:
    await _get_or_404(db, user.clinic_id, plan_id)
    rows = await db.scalars(
        select(TreatmentPlanConsent)
        .where(TreatmentPlanConsent.plan_id == plan_id)
        .options(selectinload(TreatmentPlanConsent.witnessed_by))
        .order_by(TreatmentPlanConsent.signed_at.desc(), TreatmentPlanConsent.id.desc())
    )
    return [_consent_out(c) for c in rows]


@router.post("/{plan_id}/consents", response_model=ConsentOut, status_code=201)
async def create_consent(
    db: DB, user: CurrentUser, plan_id: int, body: ConsentCreate, request: Request
) -> ConsentOut:
    """患者の同意サインを保存する（院内の端末でスタッフ立ち会いのもと署名する想定）。"""
    plan = await _get_or_404(db, user.clinic_id, plan_id)
    try:
        data = base64.b64decode(body.signature_data_url.split(",", 1)[1], validate=True)
    except (binascii.Error, IndexError) as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "サイン画像の形式が正しくありません。"
        ) from e
    if not data.startswith(PNG_MAGIC):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "サイン画像の形式が正しくありません。"
        )

    key = storage.save(data, prefix="signatures", ext="png")
    consent = TreatmentPlanConsent(
        plan_id=plan.id,
        signed_name=body.signed_name,
        signature_key=key,
        plan_snapshot=plan.content_snapshot(),
        signed_at=datetime.now(UTC),
        witnessed_by_id=user.id,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", "")[:500],
    )
    db.add(consent)
    await db.commit()
    consent = await db.scalar(
        select(TreatmentPlanConsent)
        .where(TreatmentPlanConsent.id == consent.id)
        .options(selectinload(TreatmentPlanConsent.witnessed_by))
    )
    assert consent is not None
    return _consent_out(consent)
