from pydantic import BaseModel, Field

from app.models.user import Role


class StaffCreate(BaseModel):
    username: str = Field(min_length=3, max_length=150, pattern=r"^[A-Za-z0-9_.@+-]+$")
    full_name: str = Field(min_length=1, max_length=100)
    role: Role = Role.PRACTITIONER
    password: str = Field(min_length=8, max_length=128)
