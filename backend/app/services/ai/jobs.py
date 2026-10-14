"""AI ジョブの登録と実行。ワーカー（app/worker.py）とテストから使う。"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import SessionLocal
from app.models import (
    AiJob,
    AiJobKind,
    AiJobStatus,
    AiUsageLog,
    AiUsageType,
    ClinicalNote,
    PostureAssessment,
    Recording,
    RecordingStatus,
)
from app.schemas.posture import PostureFindings
from app.services.ai.provider import Usage, estimate_cost_yen, get_provider
from app.services.storage import storage

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
STALE_AFTER = timedelta(minutes=15)  # ワーカーが落ちて RUNNING のまま残ったジョブを再実行する
VIEW_LABELS = {"front": "正面", "side_right": "右側面", "side_left": "左側面", "back": "背面"}


def now() -> datetime:
    return datetime.now(UTC)


def enqueue(
    db: AsyncSession,
    *,
    kind: AiJobKind,
    clinic_id: int,
    user_id: int | None,
    recording_id: int | None = None,
    posture_assessment_id: int | None = None,
) -> AiJob:
    job = AiJob(
        clinic_id=clinic_id,
        kind=kind,
        recording_id=recording_id,
        posture_assessment_id=posture_assessment_id,
        created_by_id=user_id,
        created_at=now(),
    )
    db.add(job)
    return job


async def _claim(db: AsyncSession) -> int | None:
    stale = await db.execute(
        update(AiJob)
        .where(
            AiJob.status == AiJobStatus.RUNNING,
            AiJob.started_at < now() - STALE_AFTER,
            AiJob.attempts < MAX_ATTEMPTS,
        )
        .values(status=AiJobStatus.QUEUED)
    )
    if stale.rowcount:  # type: ignore[attr-defined]
        log.warning("requeued %s stale ai jobs", stale.rowcount)  # type: ignore[attr-defined]

    job = await db.scalar(
        select(AiJob)
        .where(AiJob.status == AiJobStatus.QUEUED)
        .order_by(AiJob.created_at, AiJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        await db.commit()
        return None
    job.status = AiJobStatus.RUNNING
    job.attempts += 1
    job.started_at = now()
    await db.commit()
    return job.id


def _log_usage(db: AsyncSession, job: AiJob, usage_type: AiUsageType, usage: Usage) -> None:
    db.add(
        AiUsageLog(
            clinic_id=job.clinic_id,
            usage_type=usage_type,
            model=usage.model,
            audio_sec=usage.audio_sec,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            estimated_cost_yen=estimate_cost_yen(usage),
            job_id=job.id,
            created_at=now(),
        )
    )


async def _process_recording(db: AsyncSession, job: AiJob) -> None:
    rec = await db.get(Recording, job.recording_id)
    if rec is None:
        return
    note = await db.scalar(
        select(ClinicalNote)
        .where(ClinicalNote.id == rec.clinical_note_id)
        .options(selectinload(ClinicalNote.patient))
    )
    path = storage.path_for(rec.audio_key)
    if note is None or path is None:
        raise RuntimeError("録音ファイルまたはカルテが見つかりません。")
    provider = get_provider()

    rec.status = RecordingStatus.TRANSCRIBING
    await db.commit()
    tr = await provider.transcribe(path.read_bytes(), path.name, rec.mime_type)
    if not tr.usage.audio_sec:
        tr.usage.audio_sec = rec.duration_sec
    else:
        rec.duration_sec = tr.usage.audio_sec
    rec.transcript = tr.text
    rec.status = RecordingStatus.SUMMARIZING
    _log_usage(db, job, AiUsageType.TRANSCRIPTION, tr.usage)
    await db.commit()

    context = f"# 患者\n{note.patient.last_name} 様（診察券番号 {note.patient.card_no}）"
    if note.subjective:
        context += f"\n# カルテの S（記入済み）\n{note.subjective}"
    summary, usage = await provider.summarize_visit(tr.text, context)
    rec.summary = summary.model_dump()
    rec.status = RecordingStatus.DONE
    rec.error_message = ""
    _log_usage(db, job, AiUsageType.SUMMARY, usage)


async def _analyze_posture(db: AsyncSession, job: AiJob) -> None:
    a = await db.scalar(
        select(PostureAssessment)
        .where(PostureAssessment.id == job.posture_assessment_id)
        .options(selectinload(PostureAssessment.images))
    )
    if a is None:
        return
    images = []
    for img in a.images:
        if path := storage.path_for(img.image_key):
            images.append((VIEW_LABELS.get(img.view.value, img.view.value), path.read_bytes()))
    if not images:
        raise RuntimeError("分析する写真がありません。")
    a.ai_status = "running"
    await db.commit()

    context = "# 撮影時のメモ\n" + (a.memo or "（なし）")
    result, usage = await get_provider().analyze_posture(images, context)
    a.ai_findings = PostureFindings.model_validate(result.model_dump()).model_dump()
    a.ai_status = "done"
    a.ai_error_message = ""
    a.ai_analyzed_at = now()
    _log_usage(db, job, AiUsageType.POSTURE, usage)


async def _mark_failed(job_id: int, message: str) -> None:
    async with SessionLocal() as db:
        job = await db.get(AiJob, job_id)
        if job is None:
            return
        retry = job.attempts < MAX_ATTEMPTS
        job.status = AiJobStatus.QUEUED if retry else AiJobStatus.FAILED
        job.error_message = message
        if not retry:
            job.finished_at = now()
            if job.recording_id and (rec := await db.get(Recording, job.recording_id)):
                rec.status = RecordingStatus.FAILED
                rec.error_message = message
            if job.posture_assessment_id and (
                a := await db.get(PostureAssessment, job.posture_assessment_id)
            ):
                a.ai_status = "failed"
                a.ai_error_message = message
        await db.commit()


async def run_one() -> bool:
    """キューから1件取り出して実行する。実行したら True。"""
    async with SessionLocal() as db:
        job_id = await _claim(db)
    if job_id is None:
        return False

    async with SessionLocal() as db:
        job = await db.get(AiJob, job_id)
        assert job is not None
        try:
            if job.kind == AiJobKind.PROCESS_RECORDING:
                await _process_recording(db, job)
            elif job.kind == AiJobKind.ANALYZE_POSTURE:
                await _analyze_posture(db, job)
            job.status = AiJobStatus.SUCCEEDED
            job.error_message = ""
            job.finished_at = now()
            await db.commit()
        except Exception as e:  # noqa: BLE001 - 失敗はジョブに記録して再試行する
            log.exception("ai job %s failed", job_id)
            await db.rollback()
            await _mark_failed(job_id, f"{type(e).__name__}: {e}"[:500])
    return True


async def run_pending(limit: int = 100) -> int:
    count = 0
    while count < limit and await run_one():
        count += 1
    return count
