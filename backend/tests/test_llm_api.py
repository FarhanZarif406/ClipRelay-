import httpx
import respx

from app.integrations import llm
from app.models import LLMProvider
from app.security import decrypt

GROQ_MODELS = "https://api.groq.com/openai/v1/models"
GROQ_CHAT = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_MODELS = "https://api.openai.com/v1/models"


def _create(client, auth, label="Groq", provider="groq", key="gsk-live-abcdef-123", model="llama-3.1-8b-instant", models_url=GROQ_MODELS):
    respx.get(models_url).mock(return_value=httpx.Response(200, json={"data": [{"id": model}]}))
    r = client.post("/api/llm-providers", headers=auth, json={"label": label, "provider": provider, "api_key": key, "model": model})
    assert r.status_code == 201, r.text
    return r.json()


@respx.mock
def test_validate_returns_models_and_errors(client, auth):
    respx.get(GROQ_MODELS).mock(side_effect=[httpx.Response(200, json={"data": [{"id": "b"}, {"id": "a"}]}), httpx.Response(401, json={"error": "invalid key"})])
    assert client.post("/api/llm-providers/validate", headers=auth, json={"provider": "groq", "api_key": "gsk"}).json() == {"models": ["a", "b"]}
    bad = client.post("/api/llm-providers/validate", headers=auth, json={"provider": "groq", "api_key": "nope"})
    assert bad.status_code == 400 and "rejected the API key" in bad.json()["detail"]
    custom = client.post("/api/llm-providers", headers=auth, json={"label": "x", "provider": "custom", "api_key": "k", "model": "m"})
    assert custom.status_code == 422


@respx.mock
def test_member_cannot_manage_or_see_keys(client, auth, member_auth):
    _create(client, auth)
    listing = client.get("/api/llm-providers", headers=member_auth).json()
    assert listing["items"] and "masked_key" not in listing["items"][0]
    assert client.post("/api/llm-providers/validate", headers=member_auth, json={"provider": "groq", "api_key": "k"}).status_code == 403
    assert client.post(f"/api/llm-providers/{listing['items'][0]['id']}/default", headers=member_auth).status_code == 403


@respx.mock
def test_create_first_is_default_and_used(client, auth, db):
    item = _create(client, auth)
    assert item["is_default"] is True and item["status"] == "valid" and "gsk-live-abcdef-123" not in str(item)
    assert item["masked_key"].endswith("-123")
    assert llm.resolve().provider == "groq"
    assert client.get("/api/prompts/meta", headers=auth).json()["model"] == "llama-3.1-8b-instant"


@respx.mock
def test_patch_blank_key_keeps_and_test_endpoint(client, auth, db):
    item = _create(client, auth)
    r = client.patch(f"/api/llm-providers/{item['id']}", headers=auth, json={"label": "Groq fast", "api_key": ""})
    assert r.json()["label"] == "Groq fast"
    assert decrypt(db.get(LLMProvider, item["id"]).api_key_enc) == "gsk-live-abcdef-123"
    respx.post(GROQ_CHAT).mock(side_effect=[httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]}), httpx.Response(401, json={})])
    ok = client.post(f"/api/llm-providers/{item['id']}/test", headers=auth).json()
    assert ok["ok"] is True and ok["item"]["status"] == "valid"
    bad = client.post(f"/api/llm-providers/{item['id']}/test", headers=auth).json()
    assert bad["ok"] is False and bad["item"]["status"] == "invalid" and bad["item"]["last_error"]


@respx.mock
def test_delete_default_needs_replacement_and_last_falls_back(client, auth):
    first = _create(client, auth)
    second = _create(client, auth, label="OpenAI", provider="openai", key="sk-o", model="gpt-4o-mini", models_url=OPENAI_MODELS)
    r = client.delete(f"/api/llm-providers/{first['id']}", headers=auth)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "choose_default"
    assert client.delete(f"/api/llm-providers/{first['id']}?new_default_id={second['id']}", headers=auth).json() == {"fallback": None}
    assert llm.resolve().provider == "openai"
    assert client.delete(f"/api/llm-providers/{second['id']}", headers=auth).json() == {"fallback": "env"}
    assert llm.resolve().id is None  # back to LLM_* from .env
