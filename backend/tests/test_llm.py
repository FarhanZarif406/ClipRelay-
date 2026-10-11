import httpx
import pytest
import respx

from app.integrations import llm
from app.integrations.http import AuthError
from app.models import LLMProvider
from app.security import encrypt
from app.services import llm_registry

CASES = {
    # provider: (models url, models response, completion url, completion response)
    "anthropic": ("https://api.anthropic.com/v1/models", {"data": [{"id": "claude-sonnet-5-5"}, {"id": "claude-haiku-4-5"}]},
                  "https://api.anthropic.com/v1/messages", {"content": [{"type": "text", "text": "OK"}]}),
    "openai": ("https://api.openai.com/v1/models", {"data": [{"id": "gpt-4o-mini"}]},
               "https://api.openai.com/v1/chat/completions", {"choices": [{"message": {"content": "OK"}}]}),
    "openrouter": ("https://openrouter.ai/api/v1/models", {"data": [{"id": "meta-llama/llama-3-70b"}]},
                   "https://openrouter.ai/api/v1/chat/completions", {"choices": [{"message": {"content": "OK"}}]}),
    "groq": ("https://api.groq.com/openai/v1/models", {"data": [{"id": "llama-3.1-8b-instant"}]},
             "https://api.groq.com/openai/v1/chat/completions", {"choices": [{"message": {"content": "OK"}}]}),
    "mistral": ("https://api.mistral.ai/v1/models", {"data": [{"id": "mistral-small-latest"}]},
                "https://api.mistral.ai/v1/chat/completions", {"choices": [{"message": {"content": "OK"}}]}),
    "custom": ("https://llm.internal/v1/models", {"data": [{"id": "local-model"}]},
               "https://llm.internal/v1/chat/completions", {"choices": [{"message": {"content": "OK"}}]}),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/models",
               {"models": [{"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent", "countTokens"]},
                           {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]}]},
               "https://generativelanguage.googleapis.com/v1beta/models/m1:generateContent",
               {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]}),
}


def _cfg(provider: str) -> llm.LLMConfig:
    return llm.LLMConfig(provider=provider, api_key="key-123", model="m1", base_url="https://llm.internal/v1" if provider == "custom" else None)


@pytest.mark.parametrize("provider", list(CASES))
@respx.mock
def test_adapter_list_models_and_complete(provider):
    models_url, models_body, complete_url, complete_body = CASES[provider]
    models_route = respx.get(url__startswith=models_url).mock(return_value=httpx.Response(200, json=models_body))
    complete_route = respx.post(complete_url).mock(return_value=httpx.Response(200, json=complete_body))
    models = llm.list_models(_cfg(provider))
    assert models and "text-embedding-004" not in models
    if provider == "gemini":
        assert models == ["gemini-2.5-flash"]  # "models/" prefix stripped, non-generateContent filtered out
        assert models_route.calls[0].request.headers["x-goog-api-key"] == "key-123"
    assert llm.complete_with(_cfg(provider), "Say OK", system="sys", max_tokens=5) == "OK"
    sent = complete_route.calls[0].request
    if provider == "anthropic":
        assert sent.headers["x-api-key"] == "key-123"
    elif provider == "gemini":
        assert b'"maxOutputTokens":5' in sent.content.replace(b" ", b"")
    else:
        assert sent.headers["Authorization"] == "Bearer key-123"


@pytest.mark.parametrize("provider", list(CASES))
@respx.mock
def test_adapter_auth_errors(provider):
    models_url, _, complete_url, _ = CASES[provider]
    respx.get(url__startswith=models_url).mock(return_value=httpx.Response(401, json={"error": "bad key"}))
    respx.post(complete_url).mock(return_value=httpx.Response(403, json={"error": "forbidden"}))
    with pytest.raises(AuthError):
        llm.list_models(_cfg(provider))
    with pytest.raises(AuthError):
        llm.complete_with(_cfg(provider), "hi")


def test_custom_requires_base_url():
    with pytest.raises(Exception, match="base URL"):
        llm.list_models(llm.LLMConfig(provider="custom", api_key="k", model="m"))


def test_env_fallback_when_table_empty():
    cfg = llm.resolve()
    assert cfg.provider == "anthropic" and cfg.model == "claude-test" and cfg.id is None  # from conftest env


def _provider(db, label, provider="openai", model="gpt-4o-mini", is_default=False):
    row = LLMProvider(label=label, provider=provider, api_key_enc=encrypt(f"key-{label}"), model=model, is_default=is_default)
    db.add(row)
    db.commit()
    llm_registry.bust()
    return row


def test_default_resolution_and_specific_provider(db):
    first = _provider(db, "first")
    second = _provider(db, "second", provider="groq", model="llama", is_default=True)
    assert llm.resolve().id == second.id  # default wins over insertion order
    assert llm.resolve(first.id).api_key == "key-first"
    assert llm.resolve(99999).id == second.id  # unknown id → default
    second.is_default = False
    db.commit()
    llm_registry.bust()
    assert llm.resolve().id == first.id  # no default flagged → first provider


@respx.mock
def test_complete_uses_default_provider(db):
    _provider(db, "groq-default", provider="groq", model="llama", is_default=True)
    route = respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "Hola"}}]})
    )
    assert llm.complete("translate") == "Hola"
    assert b'"model":"llama"' in route.calls[0].request.content.replace(b" ", b"")


@respx.mock
def test_template_uses_its_own_model(db, tiktok_account, template):
    from tests.test_pipeline import _make_job
    from app.services import pipeline

    _provider(db, "default", provider="openai", model="gpt-4o-mini", is_default=True)
    groq = _provider(db, "groq", provider="groq", model="llama")
    template.llm_provider_id = groq.id
    db.commit()
    llm_registry.bust()
    groq_route = respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "#a #b"}}]})
    )
    openai_route = respx.post("https://api.openai.com/v1/chat/completions")
    job = _make_job(db, tiktok_account, status="rewriting", caption="pending")
    assert pipeline.rewrite_job(db, job.id) == "awaiting_approval"
    assert groq_route.call_count == 3 and openai_route.call_count == 0
