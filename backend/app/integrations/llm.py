"""LLM client — provider and model come from .env (LLM_PROVIDER / LLM_MODEL / LLM_API_KEY / LLM_BASE_URL)."""

import json
import re

from app.config import get_settings
from app.integrations.http import ApiError, AuthError, request

SYSTEM_PROMPT = (
    "You rewrite short-form social video metadata for TikTok. "
    "Return only the requested text — no preamble, no quotes, no explanations."
)


def complete(prompt: str, *, system: str = SYSTEM_PROMPT, max_tokens: int | None = None) -> str:
    s = get_settings()
    if not s.llm_api_key:
        raise ApiError("LLM_API_KEY is not configured")
    max_tokens = max_tokens or s.llm_max_tokens
    if s.llm_provider == "anthropic":
        base = (s.llm_base_url or "https://api.anthropic.com").rstrip("/")
        response = request(
            "POST",
            f"{base}/v1/messages",
            headers={"x-api-key": s.llm_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={
                "model": s.llm_model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        data = _check(response)
        return "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text").strip()

    base = (s.llm_base_url or "https://api.openai.com/v1").rstrip("/")
    response = request(
        "POST",
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {s.llm_api_key}", "Content-Type": "application/json"},
        json={
            "model": s.llm_model,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    data = _check(response)
    return (data["choices"][0]["message"]["content"] or "").strip()


def _check(response) -> dict:
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code in (401, 403):
        raise AuthError(f"LLM auth error: {response.text[:200]}", status=response.status_code)
    if response.status_code >= 400:
        raise ApiError(f"LLM error {response.status_code}: {response.text[:300]}", status=response.status_code, body=data)
    return data


def detect_language(text: str) -> tuple[str, float]:
    """Return (ISO 639-1 code, confidence 0-1) for the given text."""
    prompt = (
        "Identify the language of the following text. Hindi written in Latin script counts as Hindi, "
        'Urdu written in Latin script counts as Urdu. Respond with JSON only: {"language": "<ISO 639-1>", "confidence": <0-1>}.\n\n'
        f"Text:\n{text[:4000]}"
    )
    raw = complete(prompt, system="You are a precise language identification tool.", max_tokens=60)
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        raise ApiError(f"Unparseable language detection response: {raw[:120]}")
    data = json.loads(match.group(0))
    return str(data.get("language", "und")).lower()[:8], float(data.get("confidence", 0))
