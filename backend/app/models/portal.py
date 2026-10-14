from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import TimestampMixin
from app.models.patient import Patient


class PatientAccount(TimestampMixin, Base):
    """患者向けポータルのログインアカウント（患者 1 人につき 1 つ）。"""

    __tablename__ = "patient_accounts"
    __table_args__ = (
        UniqueConstraint("clinic_id", "email", name="uq_patient_accounts_clinic_email"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"), index=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), unique=True
    )
    # 小文字に正規化して保存する
    email: Mapped[str] = mapped_column(String(254))
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # パスワード再設定（トークンはハッシュだけ保存する）
    reset_token_hash: Mapped[str | None] = mapped_column(String(64))
    reset_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    patient: Mapped[Patient] = relationship(lazy="raise")
