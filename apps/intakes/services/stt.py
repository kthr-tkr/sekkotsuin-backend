# apps/intakes/services/stt.py

import os
import tempfile
from pathlib import Path

from openai import OpenAI

client = OpenAI()

SUPPORTED_EXT = {
    ".mp3",
    ".wav",
    ".m4a",
    ".webm",
    ".mp4",
    ".mpeg",
    ".mpga",
    ".ogg",
    ".flac",
}


def _get_file_ext(file_name: str) -> str:
    ext = Path(file_name or "").suffix.lower()
    return ext if ext else ".webm"


def _copy_django_file_to_temp(django_file, suffix: str) -> str:
    """
    S3 / ローカル両対応。
    DjangoのFileFieldを storage.open() 経由で読み、一時ファイルへコピーする。
    OpenAI Audio APIへ渡すための実体パスを作る。
    """
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)

    try:
        django_file.open("rb")

        try:
            for chunk in django_file.chunks():
                tmp.write(chunk)
        finally:
            django_file.close()

        tmp.flush()
        tmp.close()

        return tmp.name

    except Exception:
        tmp.close()

        if os.path.exists(tmp.name):
            os.remove(tmp.name)

        raise


def run_stt(
    audio_file,
    mime_type: str = "",
    *,
    language: str = "ja",
    model: str = "gpt-4o-mini-transcribe",
):
    """
    音声文字起こし。
    S3 / ローカル保存の両方に対応。

    audio_file:
        recording.audio_file のような Django FileField を渡す。
        旧仕様の audio_path 文字列ではなく、FileField を渡す前提。
    """

    if not audio_file:
        raise ValueError("音声ファイルがありません。")

    file_name = getattr(audio_file, "name", "") or "audio.webm"
    file_ext = _get_file_ext(file_name)

    if file_ext not in SUPPORTED_EXT:
        raise ValueError(
            f"Unsupported audio format: {file_ext} "
            f"(supported: {sorted(SUPPORTED_EXT)})"
        )

    temp_path = _copy_django_file_to_temp(audio_file, file_ext)

    try:
        size = os.path.getsize(temp_path)

        if size < 2000:
            raise ValueError("録音データが小さすぎます（無音または録音失敗の可能性）")

        with open(temp_path, "rb") as f:
            tr = client.audio.transcriptions.create(
                model=model,
                file=f,
                language=language,
                response_format="json",
            )

        text = getattr(tr, "text", None)
        if text is None and isinstance(tr, dict):
            text = tr.get("text")

        if text is None:
            raise ValueError(f"Unexpected STT response: {tr!r}")

        if not text.strip():
            raise ValueError("文字起こし結果が空です（無音/小音量/短すぎる可能性）")

        transcript_json = {
            "model": model,
            "language": language,
            "mime_type": mime_type or "",
            "file_ext": file_ext,
            "file_size": size,
            "storage_name": file_name,
            "response_format": "json",
            "storage_safe": True,
        }

        return text.strip(), transcript_json

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)