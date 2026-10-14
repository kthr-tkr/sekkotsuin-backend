from datetime import UTC, datetime

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser, not_found
from app.api.routes.patients import get_patient_or_404
from app.models import (
    AiJobKind,
    ClinicalNote,
    PostureAssessment,
    PostureImage,
    PostureStatus,
    PostureView,
)
from app.schemas.common import Page
from app.schemas.patient import PatientBrief
from app.schemas.posture import (
    PostureCreate,
    PostureFindings,
    PostureImageOut,
    PostureOut,
    PostureUpdate,
)
from app.services.ai.jobs import enqueue
from app.services.ai.quota import ensure_ai_allowed
from app.services.storage import read_photo_upload, signed_url, storage

router = APIRouter(prefix="/posture-assessments", tags=["posture"])

_LOAD = (selectinload(PostureAssessment.patient), selectinload(PostureAssessment.images))


def _out(a: PostureAssessment) -> PostureOut:
    order = list(PostureView)
    images = [
        PostureImageOut(view=i.view, width=i.width, height=i.height, url=signed_url(i.image_key))
        for i in sorted(a.images, key=lambda i: order.index(i.view))
    ]
    return PostureOut(
        id=a.id,
        patient_id=a.patient_id,
        clinical_note_id=a.clinical_note_id,
        assessed_at=a.assessed_at,
        title=a.title,
        memo=a.memo,
        status=a.status,
        findings=PostureFindings.model_validate(a.findings or {}),
        ai_status=a.ai_status,
        ai_findings=PostureFindings.model_validate(a.ai_findings) if a.ai_findings else None,
        ai_error_message=a.ai_error_message,
        ai_analyzed_at=a.ai_analyzed_at,
        confirmed_at=a.confirmed_at,
        created_at=a.created_at,
        patient=PatientBrief.model_validate(a.patient),
        images=images,
    )


async def _get_or_404(db: DB, clinic_id: int, assessment_id: int) -> PostureAssessment:
    a = await db.scalar(
        select(PostureAssessment)
        .where(PostureAssessment.id == assessment_id)
        .options(*_LOAD)
        .execution_options(populate_existing=True)
    )
    if a is None or a.clinic_id != clinic_id:
        raise not_found("姿勢評価")
    return a


@router.get("", response_model=Page[PostureOut])
async def list_assessments(
    db: DB,
    user: CurrentUser,
    patient_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    stmt = select(PostureAssessment).where(PostureAssessment.clinic_id == user.clinic_id)
    if patient_id is not None:
        stmt = stmt.where(PostureAssessment.patient_id == patient_id)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await db.scalars(
        stmt.options(*_LOAD)
        .order_by(PostureAssessment.assessed_at.desc(), PostureAssessment.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return {"items": [_out(a) for a in rows], "total": total}


@router.post("", response_model=PostureOut, status_code=201)
async def create_assessment(db: DB, user: CurrentUser, body: PostureCreate) -> PostureOut:
    await get_patient_or_404(db, user.clinic_id, body.patient_id)
    assessed_at = body.assessed_at or datetime.now(UTC)
    if body.clinical_note_id is not None:
        note = await db.get(ClinicalNote, body.clinical_note_id)
        if note is None or note.clinic_id != user.clinic_id or note.patient_id != body.patient_id:
            raise not_found("カルテ")
        assessed_at = body.assessed_at or note.visited_at
    a = PostureAssessment(
        clinic_id=user.clinic_id,
        patient_id=body.patient_id,
        clinical_note_id=body.clinical_note_id,
        assessed_at=assessed_at,
        findings=PostureFindings().model_dump(),
        created_by_id=user.id,
    )
    db.add(a)
    await db.commit()
    return _out(await _get_or_404(db, user.clinic_id, a.id))


@router.get("/{assessment_id}", response_model=PostureOut)
async def get_assessment(db: DB, user: CurrentUser, assessment_id: int) -> PostureOut:
    return _out(await _get_or_404(db, user.clinic_id, assessment_id))


@router.put("/{assessment_id}", response_model=PostureOut)
async def update_assessment(
    db: DB, user: CurrentUser, assessment_id: int, body: PostureUpdate
) -> PostureOut:
    a = await _get_or_404(db, user.clinic_id, assessment_id)
    a.title = body.title
    a.assessed_at = body.assessed_at
    a.memo = body.memo
    a.findings = body.findings.model_dump()
    await db.commit()
    return _out(await _get_or_404(db, user.clinic_id, assessment_id))


@router.post("/{assessment_id}/confirm", response_model=PostureOut)
async def confirm_assessment(db: DB, user: CurrentUser, assessment_id: int) -> PostureOut:
    a = await _get_or_404(db, user.clinic_id, assessment_id)
    if a.status != PostureStatus.CONFIRMED:
        a.status = PostureStatus.CONFIRMED
        a.confirmed_at = datetime.now(UTC)
        a.confirmed_by_id = user.id
        await db.commit()
    return _out(await _get_or_404(db, user.clinic_id, assessment_id))


@router.put("/{assessment_id}/images/{view}", response_model=PostureOut)
async def upload_image(
    db: DB,
    user: CurrentUser,
    assessment_id: int,
    view: PostureView,
    file: UploadFile = File(),
) -> PostureOut:
    """指定した方向の写真をアップロードする（既にあれば差し替える）。"""
    a = await _get_or_404(db, user.clinic_id, assessment_id)
    data, width, height = await read_photo_upload(file)
    key = storage.save(data, prefix="posture", ext="jpg")

    old = next((i for i in a.images if i.view == view), None)
    old_key = old.image_key if old else None
    if old is not None:
        await db.delete(old)
        await db.flush()
    db.add(
        PostureImage(
            assessment_id=a.id,
            view=view,
            image_key=key,
            width=width,
            height=height,
            uploaded_by_id=user.id,
            created_at=datetime.now(UTC),
        )
    )
    await db.commit()
    if old_key:
        storage.delete(old_key)
    return _out(await _get_or_404(db, user.clinic_id, assessment_id))


@router.delete("/{assessment_id}/images/{view}", response_model=PostureOut)
async def delete_image(
    db: DB, user: CurrentUser, assessment_id: int, view: PostureView
) -> PostureOut:
    a = await _get_or_404(db, user.clinic_id, assessment_id)
    img = next((i for i in a.images if i.view == view), None)
    if img is None:
        raise not_found("写真")
    key = img.image_key
    await db.delete(img)
    await db.commit()
    storage.delete(key)
    return _out(await _get_or_404(db, user.clinic_id, assessment_id))


@router.post("/{assessment_id}/analyze", response_model=PostureOut)
async def analyze(db: DB, user: CurrentUser, assessment_id: int) -> PostureOut:
    """写真の AI 分析を登録する。結果は ai_findings に入り、スタッフが確認して反映する。"""
    a = await _get_or_404(db, user.clinic_id, assessment_id)
    if not a.images:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "写真を1枚以上登録してください。"
        )
    if a.ai_status in ("queued", "running"):
        raise HTTPException(status.HTTP_409_CONFLICT, "分析中です。")
    await ensure_ai_allowed(db, user.clinic_id)
    a.ai_status = "queued"
    a.ai_error_message = ""
    enqueue(
        db,
        kind=AiJobKind.ANALYZE_POSTURE,
        clinic_id=user.clinic_id,
        user_id=user.id,
        posture_assessment_id=a.id,
    )
    await db.commit()
    return _out(await _get_or_404(db, user.clinic_id, assessment_id))


@router.post("/{assessment_id}/apply-ai", response_model=PostureOut)
async def apply_ai(db: DB, user: CurrentUser, assessment_id: int) -> PostureOut:
    """AI の所見で findings を置き換える（空欄の部位は今の所見を残す）。"""
    a = await _get_or_404(db, user.clinic_id, assessment_id)
    if not a.ai_findings:
        raise HTTPException(status.HTTP_409_CONFLICT, "AI の分析結果がありません。")
    current = PostureFindings.model_validate(a.findings or {})
    ai = PostureFindings.model_validate(a.ai_findings)
    regions = current.regions.model_dump()
    regions.update({k: v for k, v in ai.regions.model_dump().items() if v})
    a.findings = PostureFindings(
        overall_summary=ai.overall_summary or current.overall_summary,
        important_points=ai.important_points or current.important_points,
        regions=regions,  # type: ignore[arg-type]
    ).model_dump()
    await db.commit()
    return _out(await _get_or_404(db, user.clinic_id, assessment_id))
