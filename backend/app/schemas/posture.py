from datetime import datetime

from pydantic import AwareDatetime, BaseModel, Field

from app.models.posture import PostureStatus, PostureView
from app.schemas.common import ORMModel
from app.schemas.patient import PatientBrief


class PostureRegions(BaseModel):
    """部位ごとの所見（旧版 AI 出力の posture_findings と同じ区分）。"""

    head_neck: str = ""  # 頭部・頸部
    shoulder: str = ""  # 肩・肩甲帯
    spine: str = ""  # 脊柱・体幹
    pelvis: str = ""  # 骨盤
    hip: str = ""  # 股関節
    knee: str = ""  # 膝
    ankle_foot: str = ""  # 足関節・足部
    balance: str = ""  # 全体バランス


class PostureFindings(BaseModel):
    overall_summary: str = ""
    important_points: list[str] = Field(default_factory=list, max_length=20)
    regions: PostureRegions = Field(default_factory=PostureRegions)


class PostureCreate(BaseModel):
    patient_id: int
    clinical_note_id: int | None = None
    assessed_at: AwareDatetime | None = None


class PostureUpdate(BaseModel):
    title: str = Field("姿勢評価", min_length=1, max_length=120)
    assessed_at: AwareDatetime
    memo: str = ""
    findings: PostureFindings = Field(default_factory=PostureFindings)


class PostureImageOut(ORMModel):
    view: PostureView
    width: int
    height: int
    url: str | None = None


class PostureOut(ORMModel):
    id: int
    patient_id: int
    clinical_note_id: int | None
    assessed_at: datetime
    title: str
    memo: str
    status: PostureStatus
    findings: PostureFindings
    ai_status: str = ""  # "" / queued / running / done / failed
    ai_findings: PostureFindings | None = None
    ai_error_message: str = ""
    ai_analyzed_at: datetime | None = None
    confirmed_at: datetime | None
    created_at: datetime
    patient: PatientBrief
    images: list[PostureImageOut] = []
