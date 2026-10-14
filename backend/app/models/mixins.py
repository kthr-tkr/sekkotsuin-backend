import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, func
from sqlalchemy.orm import Mapped, mapped_column


def str_enum(enum_cls: type[enum.StrEnum]) -> Enum:
    """StrEnum を値（小文字の文字列）のまま VARCHAR に保存する。"""
    return Enum(
        enum_cls, native_enum=False, length=20, values_callable=lambda e: [m.value for m in e]
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
