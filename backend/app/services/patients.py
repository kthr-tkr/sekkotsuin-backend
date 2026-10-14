from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Patient


async def next_card_no(db: AsyncSession, clinic_id: int) -> str:
    """院内の最大番号 + 1 を P000001 形式で返す（固定幅なので文字列の max で比較できる）。"""
    last = await db.scalar(
        select(func.max(Patient.card_no)).where(
            Patient.clinic_id == clinic_id,
            Patient.card_no.regexp_match(r"^P[0-9]{6}$"),
        )
    )
    number = int(last[1:]) + 1 if last else 1
    return f"P{number:06d}"
