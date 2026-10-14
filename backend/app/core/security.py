from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


# トークンの種別。スタッフ用と患者用のトークンを取り違えて使えないようにする
TokenType = Literal["staff", "patient"]


def create_access_token(subject: str | int, typ: TokenType = "staff") -> str:
    minutes = (
        settings.access_token_expire_minutes
        if typ == "staff"
        else settings.patient_token_expire_minutes
    )
    expire = datetime.now(UTC) + timedelta(minutes=minutes)
    payload = {"sub": str(subject), "typ": typ, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, typ: TokenType = "staff") -> str | None:
    """指定した種別のトークンなら sub を返す。種別が違う・無効なら None。"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != typ:
        return None
    return payload.get("sub")
