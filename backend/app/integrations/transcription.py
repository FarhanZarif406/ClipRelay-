"""Optional speech-to-text (OpenAI-compatible /audio/transcriptions) used by the language gate."""

from app.config import get_settings
from app.integrations.http import ApiError, request

LANGUAGE_NAMES = {
    "hindi": "hi", "urdu": "ur", "english": "en", "spanish": "es", "portuguese": "pt", "japanese": "ja",
    "french": "fr", "german": "de", "italian": "it", "arabic": "ar", "bengali": "bn", "punjabi": "pa",
    "turkish": "tr", "russian": "ru", "chinese": "zh", "korean": "ko", "indonesian": "id",
}


def enabled() -> bool:
    return bool(get_settings().transcription_api_key)


def transcribe(audio_path: str) -> tuple[str, str | None]:
    """Return (transcript, ISO language code or None)."""
    s = get_settings()
    with open(audio_path, "rb") as fh:
        response = request(
            "POST",
            f"{s.transcription_base_url.rstrip('/')}/audio/transcriptions",
            headers={"Authorization": f"Bearer {s.transcription_api_key}"},
            data={"model": s.transcription_model, "response_format": "verbose_json"},
            files={"file": ("audio.mp3", fh, "audio/mpeg")},
            timeout=120,
        )
    if response.status_code >= 400:
        raise ApiError(f"Transcription failed {response.status_code}: {response.text[:200]}", status=response.status_code)
    data = response.json()
    language = (data.get("language") or "").lower() or None
    if language and len(language) > 3:
        language = LANGUAGE_NAMES.get(language, language)
    return data.get("text", ""), language
