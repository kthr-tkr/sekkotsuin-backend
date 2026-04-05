# apps/intakes/services/stt.py などに分離推奨（views.py 直書きでもOK）
from pathlib import Path
from openai import OpenAI

client = OpenAI()

SUPPORTED_EXT = {".mp3", ".wav", ".m4a", ".webm", ".mp4", ".mpeg", ".mpga", ".ogg", ".flac"}

def run_stt(audio_path: str, mime_type: str, *, language: str = "ja", model: str = "gpt-4o-mini-transcribe"):
    p = Path(audio_path)
    if not p.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if p.suffix.lower() not in SUPPORTED_EXT:
        raise ValueError(f"Unsupported audio format: {p.suffix} (supported: {sorted(SUPPORTED_EXT)})")

    size = p.stat().st_size
    if size < 2000:  # 2KB未満はほぼ無音/壊れ
        raise ValueError("録音データが小さすぎます（無音または録音失敗の可能性）")

    with p.open("rb") as f:
        tr = client.audio.transcriptions.create(
            model=model,
            file=f,
            language=language,
            response_format="json",
        )

    # ✅ 空文字を「そのまま」扱う（orで潰さない）
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
        "file_ext": p.suffix.lower(),
        "file_size": size,
        "response_format": "json",
    }

    return text.strip(), transcript_json