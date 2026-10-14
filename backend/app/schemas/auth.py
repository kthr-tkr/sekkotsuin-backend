from pydantic import BaseModel

from app.models.user import Role
from app.schemas.common import ORMModel


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORMModel):
    id: int
    clinic_id: int
    username: str
    full_name: str
    role: Role
    is_active: bool
