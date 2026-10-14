from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import decode_access_token
from app.models import Role, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

DB = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(db: DB, token: Annotated[str, Depends(oauth2_scheme)]) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="認証情報が無効です。",
        headers={"WWW-Authenticate": "Bearer"},
    )
    sub = decode_access_token(token, "staff")
    if sub is None or not sub.isdigit():
        raise unauthorized
    user = await db.get(User, int(sub))
    if user is None or not user.is_active:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role):
    async def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "この操作を行う権限がありません。")
        return user

    return checker


AdminUser = Annotated[User, Depends(require_roles(Role.ADMIN))]


def not_found(what: str = "対象") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what}が見つかりません。")
