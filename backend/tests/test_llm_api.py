import httpx
import respx

from sqlalchemy import select

from app.integrations import llm
from app.models import LLMProvider, User
from app.security import decrypt
from app.services import acting, llm_registry

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
def test_every_member_has_their_own_models(client, auth, member_auth, db):
    owners = _create(client, auth)
    # A member sees none of the owners' models, cannot touch them, and has no AI until they add their own.
    assert client.get("/api/llm-providers", headers=member_auth).json()["items"] == []
    assert client.post(f"/api/llm-providers/{owners['id']}/default", headers=member_auth).status_code == 404
    member_id = db.scalar(select(User.id).where(User.role == "member"))
    with acting.scope(member_id):
        assert llm.resolve() is None
    with acting.scope(None):
        assert llm.resolve().label == "Groq"

    # Their own model is theirs alone; they see the end of its key.
    mine = _create(client, member_auth, label="Mine", key="gsk-member-key-9876")
    assert mine["is_default"] is True and mine["masked_key"].endswith("9876")
    assert [i["label"] for i in client.get("/api/llm-providers", headers=member_auth).json()["items"]] == ["Mine"]
    assert [i["label"] for i in client.get("/api/llm-providers", headers=auth).json()["items"]] == ["Groq"]
    llm_registry.bust()
    with acting.scope(member_id):
        assert llm.resolve().label == "Mine"
        assert llm.resolve(owners["id"]).label == "Mine"  # a template pointing at the owners' model still uses the member's own

    # An owner can manage a member's models for them; a member cannot reach another account's.
    assert [i["label"] for i in client.get(f"/api/llm-providers?for_user={member_id}", headers=auth).json()["items"]] == ["Mine"]
    assert client.get("/api/llm-providers?for_user=1", headers=member_auth).status_code == 403


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
