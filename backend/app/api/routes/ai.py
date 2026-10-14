import re
from collections import defaultdict
from datetime import UTC, date, datetime

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select

from app.api.deps import DB, AdminUser, CurrentUser, not_found
from app.core.config import settings
from app.models import (
    AiJobKind,
    AiUsageLog,
    ClinicalNote,
    ClinicalNoteRevision,
    Recording,
    RecordingStatus,
)
from app.schemas.ai import AiUsageSummary, RecordingOut, UsageByDay, UsageByType
from app.services.ai.jobs import enqueue
from app.services.ai.quota import ensure_ai_allowed, month_range, recorded_seconds_this_month
from app.services.appointments import get_clinic_settings
from app.services.storage import signed_url, storage

router = APIRouter(tags=["ai"])

AUDIO_TYPES = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
}


def _rec_out(r: Recording) -> RecordingOut:
    out = RecordingOut.model_validate(r)
    out.audio_url = signed_url(r.audio_key)
    return out


async def _note_or_404(db: DB, clinic_id: int, note_id: int) -> ClinicalNote:
    note = await db.get(ClinicalNote, note_id)
    if note is None or note.clinic_id != clinic_id:
        raise not_found("カルテ")
    return note


async def _recording_or_404(db: DB, clinic_id: int, recording_id: int) -> Recording:
    rec = await db.get(Recording, recording_id)
    if rec is None or rec.clinic_id != clinic_id:
        raise not_found("録音")
    return rec


@router.post("/clinical-notes/{note_id}/recordings", response_model=RecordingOut, status_code=201)
async def upload_recording(
    db: DB,
    user: CurrentUser,
    note_id: int,
    file: UploadFile = File(),
    duration_sec: int = Form(ge=1, le=3 * 60 * 60),
) -> RecordingOut:
    """録音をアップロードし、文字起こしと SOAP 要約のジョブを登録する。"""
    note = await _note_or_404(db, user.clinic_id, note_id)
    mime = (file.content_type or "").split(";")[0].strip()
    ext = AUDIO_TYPES.get(mime)
    if ext is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "対応していない音声形式です。")
    await ensure_ai_allowed(db, user.clinic_id, add_seconds=duration_sec)
    data = await file.read(settings.max_audio_bytes + 1)
    if len(data) > settings.max_audio_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, "録音が長すぎます。分けて録音してください。"
        )

    rec = Recording(
        clinic_id=user.clinic_id,
        clinical_note_id=note.id,
        audio_key=storage.save(data, prefix="recordings", ext=ext),
        mime_type=mime,
        duration_sec=duration_sec,
        created_by_id=user.id,
    )
    db.add(rec)
    await db.flush()
    enqueue(
        db,
        kind=AiJobKind.PROCESS_RECORDING,
        clinic_id=user.clinic_id,
        user_id=user.id,
        recording_id=rec.id,
    )
    await db.commit()
    await db.refresh(rec)
    return _rec_out(rec)


@router.get("/clinical-notes/{note_id}/recordings", response_model=list[RecordingOut])
async def list_recordings(db: DB, user: CurrentUser, note_id: int) -> list[RecordingOut]:
    await _note_or_404(db, user.clinic_id, note_id)
    rows = await db.scalars(
        select(Recording)
        .where(Recording.clinical_note_id == note_id)
        .order_by(Recording.created_at.desc(), Recording.id.desc())
    )
    return [_rec_out(r) for r in rows]


@router.get("/recordings/{recording_id}", response_model=RecordingOut)
async def get_recording(db: DB, user: CurrentUser, recording_id: int) -> RecordingOut:
    return _rec_out(await _recording_or_404(db, user.clinic_id, recording_id))


@router.post("/recordings/{recording_id}/retry", response_model=RecordingOut)
async def retry_recording(db: DB, user: CurrentUser, recording_id: int) -> RecordingOut:
    rec = await _recording_or_404(db, user.clinic_id, recording_id)
    if rec.status != RecordingStatus.FAILED:
        raise HTTPException(status.HTTP_409_CONFLICT, "失敗した録音のみ再実行できます。")
    await ensure_ai_allowed(db, user.clinic_id)
    rec.status = RecordingStatus.QUEUED
    rec.error_message = ""
    enqueue(
        db,
        kind=AiJobKind.PROCESS_RECORDING,
        clinic_id=user.clinic_id,
        user_id=user.id,
        recording_id=rec.id,
    )
    await db.commit()
    await db.refresh(rec)
    return _rec_out(rec)


def _bullets(items: list[str]) -> str:
    return "\n".join(f"・{re.sub(r'^[・\\-\\s]+', '', i)}" for i in items if i.strip())


@router.post("/recordings/{recording_id}/apply", response_model=RecordingOut)
async def apply_recording(db: DB, user: CurrentUser, recording_id: int) -> RecordingOut:
    """AI の SOAP 下書きをカルテに反映する（記入済みの欄には追記する）。修正履歴を残す。"""
    rec = await _recording_or_404(db, user.clinic_id, recording_id)
    if rec.status != RecordingStatus.DONE:
        raise HTTPException(status.HTTP_409_CONFLICT, "要約が完了していません。")
    note = await _note_or_404(db, user.clinic_id, rec.clinical_note_id)

    before = note.snapshot()
    soap = rec.summary.get("soap") or {}
    for field, key in (
        ("subjective", "S"),
        ("objective", "O"),
        ("assessment", "A"),
        ("plan", "P"),
    ):
        text = _bullets(soap.get(key) or [])
        if not text:
            continue
        current = getattr(note, field)
        setattr(note, field, f"{current}\n{text}" if current else text)
    if note.pain_scale_before is None and rec.summary.get("pain_scale") is not None:
        note.pain_scale_before = rec.summary["pain_scale"]

    now = datetime.now(UTC)
    if note.snapshot() != before:
        db.add(
            ClinicalNoteRevision(
                note_id=note.id, snapshot=before, edited_by_id=user.id, created_at=now
            )
        )
        note.updated_by_id = user.id
    rec.applied_at = now
    await db.commit()
    await db.refresh(rec)
    return _rec_out(rec)


@router.get("/ai/usage", response_model=AiUsageSummary)
async def ai_usage(
    db: DB,
    user: AdminUser,
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$", description="YYYY-MM"),
) -> AiUsageSummary:
    today = datetime.now(settings.tz).date()
    target = date.fromisoformat(f"{month}-01") if month else today.replace(day=1)
    start, end = month_range(target)
    cs = await get_clinic_settings(db, user.clinic_id)
    await db.commit()

    logs = list(
        await db.scalars(
            select(AiUsageLog).where(
                AiUsageLog.clinic_id == user.clinic_id,
                AiUsageLog.created_at >= start,
                AiUsageLog.created_at < end,
            )
        )
    )
    by_type: dict[str, UsageByType] = {}
    by_day: dict[date, UsageByDay] = defaultdict(
        lambda: UsageByDay(date=today, audio_sec=0, cost_yen=0)
    )
    for lg in logs:
        t = by_type.setdefault(
            lg.usage_type.value,
            UsageByType(usage_type=lg.usage_type, count=0, audio_sec=0, cost_yen=0),
        )
        t.count += 1
        t.audio_sec += lg.audio_sec
        t.cost_yen = round(t.cost_yen + lg.estimated_cost_yen, 2)
        d = lg.created_at.astimezone(settings.tz).date()
        day = by_day[d]
        day.date = d
        day.audio_sec += lg.audio_sec
        day.cost_yen = round(day.cost_yen + lg.estimated_cost_yen, 2)

    if target.replace(day=1) == today.replace(day=1):
        seconds = await recorded_seconds_this_month(db, user.clinic_id)
    else:
        seconds = sum(lg.audio_sec for lg in logs)
    return AiUsageSummary(
        month=target.strftime("%Y-%m"),
        ai_available=settings.ai_provider != "disabled",
        ai_enabled=cs.ai_enabled,
        minutes_used=round(seconds / 60, 1),
        minutes_limit=cs.ai_monthly_minutes_limit,
        cost_yen=round(sum(lg.estimated_cost_yen for lg in logs), 2),
        by_type=sorted(by_type.values(), key=lambda t: t.usage_type.value),
        by_day=sorted(by_day.values(), key=lambda d: d.date),
    )
