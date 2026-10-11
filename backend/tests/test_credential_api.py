import httpx
import respx

from app.models import TikTokAccount
from app.services import credentials
from app.services.credential_checks import TIKTOK_TOKEN_URL



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


@respx.mock
def test_changing_app_with_connected_accounts_requires_reconnect(client, auth, db, tiktok_account):
    respx.post(TIKTOK_TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "clt.x"}))
    body = {"values": {"client_key": "other-app", "client_secret": "other-secret"}}
    r = client.put("/api/credentials/tiktok", headers=auth, json=body)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "reconnect_required"
    assert credentials.get("tiktok.client_key") == "tt-key"  # nothing saved
    r = client.put("/api/credentials/tiktok", headers=auth, json={**body, "confirm_reconnect": True})
    assert r.status_code == 200
    db.expire_all()
    assert db.get(TikTokAccount, tiktok_account.id).status == "expired"


def test_transcription_and_instagram_cards_are_gone(client, auth):
    groups = [c["group"] for c in client.get("/api/credentials", headers=auth).json()]
    assert "transcription" not in groups and "instagram" not in groups
    assert client.put("/api/credentials/instagram", headers=auth, json={"values": {"app_id": "1"}}).status_code == 404
    assert client.put("/api/credentials/transcription", headers=auth, json={"values": {"api_key": "sk-x"}}).status_code == 404


class FakeSMTP:
    sent: list = []
    fail_login = False

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        import smtplib

        if FakeSMTP.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    def noop(self):
        return (250, b"ok")

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)

    def quit(self):
        pass


def test_smtp_card_validation_and_test_email(client, auth, monkeypatch, db):
    import smtplib

    from app.services import notify

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    FakeSMTP.sent, FakeSMTP.fail_login = [], False
    values = {"host": "smtp.gmail.com", "port": "587", "security": "starttls", "username": "me@gmail.com", "password": "abcd efgh ijkl mnop", "from_address": "me@gmail.com"}
    r = client.put("/api/credentials/smtp", headers=auth, json={"values": values}).json()
    assert r["ok"] is True and r["card"]["state"] == "valid" and "abcd efgh" not in str(r)

    assert client.post("/api/settings/notifications/test-email", headers=auth).status_code == 400  # no recipient yet
    client.put("/api/settings/notifications", headers=auth, json={"email": "ops@example.com, owner@example.com"})
    sent = client.post("/api/settings/notifications/test-email", headers=auth).json()
    assert sent["ok"] is True and FakeSMTP.sent[-1]["To"] == "ops@example.com, owner@example.com"

    assert notify.send(db, "violation", "Video flagged on @northbound") is True
    assert "flagged" in FakeSMTP.sent[-1]["Subject"]

    FakeSMTP.fail_login = True
    bad = client.post("/api/credentials/smtp/validate", headers=auth, json={}).json()
    assert bad["ok"] is False and "app password" in bad["message"]


@respx.mock
def test_youtube_api_key_is_saved_in_the_app(client, auth):
    from app.integrations import youtube

    assert youtube.api_key() == ""
    route = respx.get("https://www.googleapis.com/youtube/v3/channels").mock(side_effect=[httpx.Response(400, json={"error": {"message": "API key not valid"}}), httpx.Response(200, json={"items": []})])
    bad = client.post("/api/credentials/youtube/validate", headers=auth, json={"values": {"api_key": "nope"}}).json()
    assert bad["ok"] is False and "API key not valid" in bad["message"]
    saved = client.put("/api/credentials/youtube", headers=auth, json={"values": {"api_key": "AIza-real-key"}}).json()
    assert saved["ok"] is True and route.call_count == 2
    assert youtube.api_key() == "AIza-real-key"  # lookups now use the Data API
    assert "AIza-real-key" not in client.get("/api/credentials", headers=auth).text  # the secret never leaves the server
