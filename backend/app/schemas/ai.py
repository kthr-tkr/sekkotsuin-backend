from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from app.models.ai import AiUsageType, RecordingStatus
from app.schemas.common import ORMModel


class RecordingOut(ORMModel):
    id: int
    clinical_note_id: int
    mime_type: str
    duration_sec: int
    status: RecordingStatus
    error_message: str
    transcript: str
    summary: dict[str, Any]
    applied_at: datetime | None
    created_at: datetime
    audio_url: str | None = None


class UsageByType(BaseModel):
    usage_type: AiUsageType
    count: int
    audio_sec: int
    cost_yen: float


class UsageByDay(BaseModel):
    date: date
    audio_sec: int
    cost_yen: float


class AiUsageSummary(BaseModel):
    month: str
    ai_available: bool  # サーバー側で AI が使える設定か
    ai_enabled: bool  # 院の設定
    minutes_used: float
    minutes_limit: int
    cost_yen: float
    by_type: list[UsageByType]
    by_day: list[UsageByDay]
