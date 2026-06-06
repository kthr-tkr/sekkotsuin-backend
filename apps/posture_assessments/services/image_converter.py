import os
import uuid
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

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

CONVERT_TO_JPEG_EXTENSIONS = {
    ".heic",
    ".heif",
}


def get_file_extension(uploaded_file):
    name = getattr(uploaded_file, "name", "") or ""
    _, ext = os.path.splitext(name.lower())
    return ext


def validate_posture_image(uploaded_file):
    ext = get_file_extension(uploaded_file)

    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError(
            "対応していない画像形式です。jpg / png / webp / heic / heif を使用してください。"
        )

    return True


def normalize_posture_image(uploaded_file, quality=88):
    """
    アップロードされた姿勢画像を安全に保存しやすい形式へ変換する。

    - HEIC/HEIF は JPEGへ変換
    - EXIFの向きを補正
    - RGBへ変換
    - ファイル名をuuid化
    - jpg/jpeg/png/webpは基本そのままではなく、JPEGへ統一する

    返り値:
    ContentFile
    """
    validate_posture_image(uploaded_file)

    ext = get_file_extension(uploaded_file)

    try:
        uploaded_file.seek(0)
    except Exception:
        pass

    image = Image.open(uploaded_file)
    image = ImageOps.exif_transpose(image)

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    if image.mode == "L":
        image = image.convert("RGB")

    output = BytesIO()
    image.save(output, format="JPEG", quality=quality, optimize=True)
    output.seek(0)

    filename = f"{uuid.uuid4().hex}.jpg"

    return ContentFile(output.read(), name=filename)

MAX_UPLOAD_SIZE = 10 * 1024 * 1024


def validate_posture_image(uploaded_file):
    ext = get_file_extension(uploaded_file)

    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError(
            "対応していない画像形式です。jpg / png / webp / heic / heif を使用してください。"
        )

    size = getattr(uploaded_file, "size", 0) or 0
    if size > MAX_UPLOAD_SIZE:
        raise ValueError("画像サイズが大きすぎます。10MB以下の画像を使用してください。")

    return True