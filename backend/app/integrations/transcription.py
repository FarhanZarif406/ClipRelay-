"""Optional speech-to-text (OpenAI-compatible /audio/transcriptions) used by the language gate."""

from app.services import credentials
from app.integrations.http import ApiError, request

LANGUAGE_NAMES = {
    "hindi": "hi", "urdu": "ur", "english": "en", "spanish": "es", "portuguese": "pt", "japanese": "ja",
    "french": "fr", "german": "de", "italian": "it", "arabic": "ar", "bengali": "bn", "punjabi": "pa",
    "turkish": "tr", "russian": "ru", "chinese": "zh", "korean": "ko", "indonesian": "id",
}


def enabled() -> bool:
    return bool(credentials.get("transcription.api_key"))


def transcribe(audio_path: str) -> tuple[str, str | None]:
    """Return (transcript, ISO language code or None)."""
    base_url = credentials.get("transcription.base_url") or "https://api.openai.com/v1"
    with open(audio_path, "rb") as fh:
        response = request(
            "POST",
            f"{base_url.rstrip('/')}/audio/transcriptions",
            headers={"Authorization": f"Bearer {credentials.get('transcription.api_key')}"},
            data={"model": credentials.get("transcription.model") or "whisper-1", "response_format": "verbose_json"},
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
