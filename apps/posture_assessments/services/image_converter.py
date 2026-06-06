import os
import uuid
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass


ALLOWED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".heic",
    ".heif",
}

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB


def get_file_extension(uploaded_file):
    name = getattr(uploaded_file, "name", "") or ""
    _, ext = os.path.splitext(name.lower())
    return ext


def validate_posture_image(uploaded_file):
    ext = get_file_extension(uploaded_file)

    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError(
            "対応していない画像形式です。jpg / jpeg / png / webp / heic / heif を使用してください。"
        )

    size = getattr(uploaded_file, "size", 0) or 0
    if size > MAX_UPLOAD_SIZE:
        raise ValueError("画像サイズが大きすぎます。10MB以下の画像を使用してください。")

    return True


def normalize_posture_image(uploaded_file, quality=88):
    """
    アップロードされた姿勢画像をJPEGへ統一する。

    - jpg / jpeg / png / webp / heic / heif を受け付ける
    - HEIC/HEIF は pillow-heif で読み込む
    - EXIFの向きを補正
    - RGBへ変換
    - UUIDファイル名の .jpg として返す
    """
    validate_posture_image(uploaded_file)

    try:
        uploaded_file.seek(0)
    except Exception:
        pass

    try:
        image = Image.open(uploaded_file)
        image = ImageOps.exif_transpose(image)

        if image.mode != "RGB":
            image = image.convert("RGB")

        output = BytesIO()
        image.save(output, format="JPEG", quality=quality, optimize=True)
        output.seek(0)

        filename = f"{uuid.uuid4().hex}.jpg"
        return ContentFile(output.read(), name=filename)

    except UnidentifiedImageError as e:
        raise ValueError(
            "画像ファイルとして読み込めませんでした。別の画像を選択してください。"
        ) from e

    except Exception as e:
        raise ValueError(f"画像ファイルの変換に失敗しました: {e}") from e