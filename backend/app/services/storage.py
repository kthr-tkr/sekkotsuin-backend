"""アップロードファイルの保存と、署名付きURLの発行。

<img src> は Authorization ヘッダーを送れないため、ファイルは有効期限付きの
署名付きURL（/api/files/<key>?exp=...&sig=...）で配信する。
本番で S3 などに移す場合は Storage の実装を差し替える。
"""

import hashlib
import hmac
import re
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

KEY_RE = re.compile(r"^[a-z0-9_-]+(/[a-z0-9_-]+)*/[A-Za-z0-9_-]+\.(png|jpe?g|webp|heic)$")
IMAGE_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/heic": "heic",
}


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        if not KEY_RE.match(key):
            raise ValueError("invalid key")
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("invalid key")
        return path

    def save(self, data: bytes, *, prefix: str, ext: str) -> str:
        now = datetime.now(UTC)
        key = f"{prefix}/{now:%Y}/{now:%m}/{secrets.token_urlsafe(16)}.{ext}"
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def path_for(self, key: str) -> Path | None:
        try:
            path = self._path(key)
        except ValueError:
            return None
        return path if path.is_file() else None

    def delete(self, key: str) -> None:
        if path := self.path_for(key):
            path.unlink(missing_ok=True)


storage = LocalStorage(settings.media_dir)


def _sign(key: str, exp: int) -> str:
    msg = f"{key}:{exp}".encode()
    return hmac.new(settings.secret_key.encode(), msg, hashlib.sha256).hexdigest()


def signed_url(key: str | None) -> str | None:
    """API のベースURLからの相対パスを返す（フロントで apiBase を前に付ける）。"""
    if not key:
        return None
    exp = int(time.time()) + settings.file_url_expire_seconds
    return f"/api/files/{key}?{urlencode({'exp': exp, 'sig': _sign(key, exp)})}"


def verify_signature(key: str, exp: int, sig: str) -> bool:
    return exp >= time.time() and hmac.compare_digest(_sign(key, exp), sig)


async def read_image_upload(file: UploadFile) -> tuple[bytes, str]:
    """画像アップロードを検証して (データ, 拡張子) を返す。"""
    ext = IMAGE_TYPES.get(file.content_type or "")
    if ext is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "PNG / JPEG / WebP / HEIC の画像をアップロードしてください。",
        )
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "ファイルサイズが大きすぎます。")
    return data, ext
