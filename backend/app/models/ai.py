import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import TimestampMixin, str_enum


class RecordingStatus(enum.StrEnum):
    QUEUED = "queued"  # 処理待ち
    TRANSCRIBING = "transcribing"  # 文字起こし中
    SUMMARIZING = "summarizing"  # 要約中
    DONE = "done"  # 完了
    FAILED = "failed"  # 失敗


class Recording(TimestampMixin, Base):
    """施術中・問診中の録音。文字起こしと SOAP 要約を作り、スタッフが確認してカルテに反映する。

    旧版の InterviewRecording と TreatmentSession（録音部分）を統合したもの。
    """

    __tablename__ = "recordings"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"), index=True)
    clinical_note_id: Mapped[int] = mapped_column(
        ForeignKey("clinical_notes.id", ondelete="CASCADE"), index=True
    )
    audio_key: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    duration_sec: Mapped[int] = mapped_column(default=0)
    status: Mapped[RecordingStatus] = mapped_column(
        str_enum(RecordingStatus), default=RecordingStatus.QUEUED
    )
    error_message: Mapped[str] = mapped_column(Text, default="")
    transcript: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AiJobKind(enum.StrEnum):
    PROCESS_RECORDING = "process_recording"  # 文字起こし → SOAP 要約
    ANALYZE_POSTURE = "analyze_posture"  # 姿勢写真の分析


class AiJobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AiJob(Base):
    """AI 処理のジョブキュー（DB のみで動かす。ワーカーは SKIP LOCKED で取り出す）。"""

    __tablename__ = "ai_jobs"
    __table_args__ = (Index("ix_ai_jobs_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    kind: Mapped[AiJobKind] = mapped_column(str_enum(AiJobKind))
    status: Mapped[AiJobStatus] = mapped_column(str_enum(AiJobStatus), default=AiJobStatus.QUEUED)
    recording_id: Mapped[int | None] = mapped_column(
        ForeignKey("recordings.id", ondelete="CASCADE")
    )
    posture_assessment_id: Mapped[int | None] = mapped_column(
        ForeignKey("posture_assessments.id", ondelete="CASCADE")
    )
    attempts: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiUsageType(enum.StrEnum):
    TRANSCRIPTION = "transcription"  # 文字起こし
    SUMMARY = "summary"  # SOAP 要約
    POSTURE = "posture"  # 姿勢分析


class AiUsageLog(Base):
    __tablename__ = "ai_usage_logs"
    __table_args__ = (Index("ix_ai_usage_logs_clinic_created", "clinic_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    usage_type: Mapped[AiUsageType] = mapped_column(str_enum(AiUsageType))
    model: Mapped[str] = mapped_column(String(100))
    audio_sec: Mapped[int] = mapped_column(default=0)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    estimated_cost_yen: Mapped[float] = mapped_column(default=0)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("ai_jobs.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
