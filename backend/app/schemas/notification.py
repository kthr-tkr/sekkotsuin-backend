from datetime import datetime

from pydantic import BaseModel, Field

from app.models.notification import NotificationChannel, NotificationKind, NotificationStatus
from app.schemas.common import ORMModel


class NotificationOut(ORMModel):
    id: int
    patient_id: int | None
    appointment_id: int | None
    kind: NotificationKind
    channel: NotificationChannel
    to: str
    subject: str
    status: NotificationStatus
    attempts: int
    error_message: str
    created_at: datetime
    sent_at: datetime | None


class SendIntakeLink(BaseModel):
    channels: list[NotificationChannel] = Field(min_length=1)
