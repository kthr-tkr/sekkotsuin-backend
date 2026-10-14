from datetime import date, datetime, time

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Recording
from app.services.appointments import get_clinic_settings


def month_range(month: date) -> tuple[datetime, datetime]:
    start = datetime.combine(month.replace(day=1), time.min, settings.tz)
    nxt = (
        month.replace(year=month.year + 1, month=1, day=1)
        if month.month == 12
        else month.replace(month=month.month + 1, day=1)
    )
    return start, datetime.combine(nxt, time.min, settings.tz)


async def recorded_seconds_this_month(db: AsyncSession, clinic_id: int) -> int:
    start, end = month_range(datetime.now(settings.tz).date())
    return (
        await db.scalar(
            select(func.coalesce(func.sum(Recording.duration_sec), 0)).where(
                Recording.clinic_id == clinic_id,
                Recording.created_at >= start,
                Recording.created_at < end,
            )
        )
        or 0
    )


async def ensure_ai_allowed(db: AsyncSession, clinic_id: int, *, add_seconds: int = 0) -> None:
    """AI が使えるか（サーバー設定・院の設定・月の上限）を確認する。"""
    if settings.ai_provider == "disabled":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "AI 機能はこのサーバーで無効になっています。"
        )
    cs = await get_clinic_settings(db, clinic_id)
    if not cs.ai_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "院の設定で AI 機能が無効になっています。")
    if add_seconds:
        used = await recorded_seconds_this_month(db, clinic_id)
        if used + add_seconds > cs.ai_monthly_minutes_limit * 60:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"今月の録音の上限（{cs.ai_monthly_minutes_limit}分）を超えるため受け付けられません。",
            )
