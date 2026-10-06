import httpx
import respx

from app.models import InstagramSource, TikTokAccount
from app.services import credentials
from app.services.credential_checks import TIKTOK_TOKEN_URL

IG_SECRET = "0123456789abcdef0123456789abcdef"


def _card(client, headers, group):
    return next(c for c in client.get("/api/credentials", headers=headers).json() if c["group"] == group)


def test_member_sees_status_only_and_cannot_write(client, auth, member_auth):
    card = _card(client, member_auth, "tiktok")
    assert card["configured"] is True and "fields" not in card and "redirect_uri" not in card
    assert client.put("/api/credentials/tiktok", headers=member_auth, json={"values": {"client_key": "x"}}).status_code == 403
    assert client.post("/api/credentials/tiktok/validate", headers=member_auth, json={}).status_code == 403
    assert client.delete("/api/credentials/tiktok", headers=member_auth).status_code == 403
    integrations = client.get("/api/settings/integrations", headers=member_auth).json()
    assert all(i["masked"] in ("Configured", "Needs setup") for i in integrations)


def test_owner_card_masks_secrets_and_shows_redirect(client, auth):
    card = _card(client, auth, "tiktok")
    fields = {f["key"]: f for f in card["fields"]}
    assert fields["client_key"]["value"] == "tt-key" and fields["client_key"]["source"] == "env"
    assert fields["client_secret"]["value"] == "" and "tt-secret" not in str(card)
    assert card["redirect_uri"] == "http://api.test/api/tiktok/oauth/callback"
    assert card["state"] == "env"


@respx.mock
def test_tiktok_client_credentials_validation(client, auth):
    route = respx.post(TIKTOK_TOKEN_URL).mock(side_effect=[
        httpx.Response(200, json={"access_token": "clt.x", "expires_in": 7200, "token_type": "Bearer"}),
        httpx.Response(401, json={"error": "invalid_client", "error_description": "Client key or secret is incorrect."}),
    ])
    good = client.post("/api/credentials/tiktok/validate", headers=auth, json={"values": {"client_key": "k1", "client_secret": "s1"}}).json()
    assert good["ok"] is True
    assert b"grant_type=client_credentials" in route.calls[0].request.content
    bad = client.post("/api/credentials/tiktok/validate", headers=auth, json={"values": {"client_key": "k1", "client_secret": "nope"}}).json()
    assert bad["ok"] is False and "incorrect" in bad["message"]


@respx.mock
def test_save_validates_and_falls_back_on_remove(client, auth):
    respx.post(TIKTOK_TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "clt.x"}))
    r = client.put("/api/credentials/tiktok", headers=auth, json={"values": {"client_key": "new-key", "client_secret": "new-secret"}})
    assert r.status_code == 200 and r.json()["card"]["state"] == "valid"
    assert credentials.get("tiktok.client_key") == "new-key"
    assert "new-secret" not in r.text
    # blank secret keeps the stored one
    r = client.put("/api/credentials/tiktok", headers=auth, json={"values": {"client_key": "new-key-2", "client_secret": ""}})
    assert credentials.get("tiktok.client_secret") == "new-secret"
    r = client.delete("/api/credentials/tiktok", headers=auth)
    assert r.json()["fallback"] == "env" and credentials.get("tiktok.client_key") == "tt-key"
    logs = client.get("/api/logs?service=Settings", headers=auth).json()["items"]
    assert logs and all("new-secret" not in entry["message"] for entry in logs)


def test_instagram_saved_as_unverified_and_format_checked(client, auth):
    bad = client.post("/api/credentials/instagram/validate", headers=auth, json={"values": {"app_id": "abc", "app_secret": IG_SECRET}}).json()
    assert bad["ok"] is False
    r = client.put("/api/credentials/instagram", headers=auth, json={"values": {"app_id": "123456789", "app_secret": IG_SECRET}}).json()
    assert r["ok"] is None and r["card"]["state"] == "unverified"


@respx.mock
def test_changing_app_with_connected_accounts_requires_reconnect(client, auth, db, source, tiktok_account):
    respx.post(TIKTOK_TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "clt.x"}))
    body = {"values": {"client_key": "other-app", "client_secret": "other-secret"}}
    r = client.put("/api/credentials/tiktok", headers=auth, json=body)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "reconnect_required"
    assert credentials.get("tiktok.client_key") == "tt-key"  # nothing saved
    r = client.put("/api/credentials/tiktok", headers=auth, json={**body, "confirm_reconnect": True})
    assert r.status_code == 200
    db.expire_all()
    assert db.get(TikTokAccount, tiktok_account.id).status == "expired"

    r = client.put("/api/credentials/instagram", headers=auth, json={"values": {"app_id": "999999", "app_secret": IG_SECRET}, "confirm_reconnect": True})
    assert r.status_code == 200
    db.expire_all()
    assert db.get(InstagramSource, source.id).needs_reconnect is True


@respx.mock
def test_transcription_card_validates_against_models_endpoint(client, auth):
    assert _card(client, auth, "transcription")["state"] == "none"  # no key yet, defaults alone don't count
    route = respx.get("https://api.openai.com/v1/models").mock(side_effect=[httpx.Response(200, json={"data": []}), httpx.Response(401, json={"error": {"message": "Incorrect API key"}})])
    r = client.put("/api/credentials/transcription", headers=auth, json={"values": {"api_key": "sk-transcribe-123456"}}).json()
    assert r["ok"] is True and r["card"]["state"] == "valid"
    assert route.calls[0].request.headers["Authorization"] == "Bearer sk-transcribe-123456"
    assert credentials.get("transcription.api_key") == "sk-transcribe-123456"
    bad = client.post("/api/credentials/transcription/validate", headers=auth, json={}).json()
    assert bad["ok"] is False and bad["card"]["state"] == "invalid" and "Incorrect API key" in bad["message"]
