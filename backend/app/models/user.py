import enum

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import TimestampMixin, str_enum


class Role(enum.StrEnum):
    ADMIN = "admin"  # 管理者
    RECEPTION = "reception"  # 受付
    PRACTITIONER = "practitioner"  # 施術者


class User(TimestampMixin, Base):
    """スタッフユーザー（患者ポータルは後続フェーズで別モデルとして追加予定）"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"), index=True)
    username: Mapped[str] = mapped_column(String(150), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(100), default="")
    role: Mapped[Role] = mapped_column(str_enum(Role), default=Role.PRACTITIONER)
    is_active: Mapped[bool] = mapped_column(default=True)
