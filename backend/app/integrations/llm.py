"""LLM client with one adapter per API family.

Providers are configured in Settings → AI models (`llm_providers` table); when none exist, the LLM_* values in
.env are used. `complete()` keeps its original signature and resolves the default
provider unless `provider_id` is given.
"""

import json
from dataclasses import dataclass

from app.integrations.http import ApiError, AuthError, request

SYSTEM_PROMPT = (
    "You rewrite short-form social video metadata for TikTok. "
    "Return only the requested text — no preamble, no quotes, no explanations."
)

PROVIDERS = ("anthropic", "openai", "gemini", "openrouter", "groq", "mistral", "custom")
DEFAULT_BASES = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "gemini": "https://generativelanguage.googleapis.com",
}
OPENAI_STYLE = {"openai", "openrouter", "groq", "mistral", "custom"}


@dataclass
class LLMConfig:
    provider: str
    api_key: str
    model: str
    base_url: str | None = None
    max_tokens: int = 600
    temperature: float | None = None
    id: int | None = None
    label: str = ""

    @property
    def base(self) -> str:
        if self.base_url:
            return self.base_url.rstrip("/")
        if self.provider == "custom":
            raise ApiError("A base URL is required for custom providers")
        return DEFAULT_BASES[self.provider]


def _check(response, provider: str) -> dict:
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code in (401, 403):
        raise AuthError(f"{provider} rejected the API key ({response.status_code}): {response.text[:200]}", status=response.status_code)
    if response.status_code >= 400:
        raise ApiError(f"{provider} error {response.status_code}: {response.text[:300]}", status=response.status_code, body=data)
    return data


# ------------------------------------------------------------------ adapters

def _anthropic_headers(cfg: LLMConfig) -> dict:
    return {"x-api-key": cfg.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}


def _anthropic_models(cfg: LLMConfig) -> list[str]:
    data = _check(request("GET", f"{cfg.base}/v1/models", params={"limit": 1000}, headers=_anthropic_headers(cfg), retries=2, timeout=20), "anthropic")
    return [m["id"] for m in data.get("data", []) if m.get("id")]


def _anthropic_complete(cfg: LLMConfig, prompt: str, system: str, max_tokens: int) -> str:
    body: dict = {"model": cfg.model, "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": prompt}]}
    if cfg.temperature is not None:
        body["temperature"] = cfg.temperature
    data = _check(request("POST", f"{cfg.base}/v1/messages", headers=_anthropic_headers(cfg), json=body, timeout=60), "anthropic")
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()


def _openai_headers(cfg: LLMConfig) -> dict:
    return {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}


def _openai_models(cfg: LLMConfig) -> list[str]:
    data = _check(request("GET", f"{cfg.base}/models", headers=_openai_headers(cfg), retries=2, timeout=20), cfg.provider)
    return [m["id"] for m in data.get("data", []) if m.get("id")]


def _openai_complete(cfg: LLMConfig, prompt: str, system: str, max_tokens: int) -> str:
    body: dict = {"model": cfg.model, "max_tokens": max_tokens, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    if cfg.temperature is not None:
        body["temperature"] = cfg.temperature
    data = _check(request("POST", f"{cfg.base}/chat/completions", headers=_openai_headers(cfg), json=body, timeout=60), cfg.provider)
    return (data["choices"][0]["message"]["content"] or "").strip()


def _gemini_headers(cfg: LLMConfig) -> dict:
    return {"x-goog-api-key": cfg.api_key, "Content-Type": "application/json"}


def _gemini_models(cfg: LLMConfig) -> list[str]:
    data = _check(request("GET", f"{cfg.base}/v1beta/models", params={"pageSize": 1000}, headers=_gemini_headers(cfg), retries=2, timeout=20), "gemini")
    return [
        m["name"].removeprefix("models/")
        for m in data.get("models", [])
        if "generateContent" in m.get("supportedGenerationMethods", []) and m.get("name")
    ]


def _gemini_complete(cfg: LLMConfig, prompt: str, system: str, max_tokens: int) -> str:
    generation: dict = {"maxOutputTokens": max_tokens}
    if cfg.temperature is not None:
        generation["temperature"] = cfg.temperature
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": generation,
    }
    model = cfg.model.removeprefix("models/")
    data = _check(request("POST", f"{cfg.base}/v1beta/models/{model}:generateContent", headers=_gemini_headers(cfg), json=body, timeout=60), "gemini")
    candidates = data.get("candidates") or []
    if not candidates:
        raise ApiError(f"gemini returned no candidates: {json.dumps(data.get('promptFeedback', {}))[:200]}")
    return "".join(p.get("text", "") for p in candidates[0].get("content", {}).get("parts", [])).strip()


def _adapter(provider: str):
    if provider == "anthropic":
        return _anthropic_models, _anthropic_complete
    if provider == "gemini":
        return _gemini_models, _gemini_complete
    if provider in OPENAI_STYLE:
        return _openai_models, _openai_complete
    raise ApiError(f"Unknown LLM provider: {provider}")


# ------------------------------------------------------------------ public API

def list_models(cfg: LLMConfig) -> list[str]:
    if not cfg.api_key:
        raise ApiError("API key is required")
    return sorted(set(_adapter(cfg.provider)[0](cfg)))


def complete_with(cfg: LLMConfig, prompt: str, *, system: str = SYSTEM_PROMPT, max_tokens: int | None = None) -> str:
    if not cfg.api_key:
        raise ApiError("LLM API key is not configured")
    return _adapter(cfg.provider)[1](cfg, prompt, system, max_tokens or cfg.max_tokens)


def resolve(provider_id: int | None = None) -> LLMConfig | None:
    from app.services import llm_registry

    return llm_registry.get_config(provider_id)


def is_configured() -> bool:
    cfg = resolve()
    return bool(cfg and cfg.api_key)


def complete(prompt: str, *, system: str = SYSTEM_PROMPT, max_tokens: int | None = None, provider_id: int | None = None) -> str:
    cfg = resolve(provider_id)
    if cfg is None or not cfg.api_key:
        raise ApiError("No AI model of your own is set up — add one on your Integrations page")
    return complete_with(cfg, prompt, system=system, max_tokens=max_tokens)
