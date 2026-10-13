import httpx
import respx




def _card(client, headers, group):
    return next(c for c in client.get("/api/credentials", headers=headers).json() if c["group"] == group)


def test_api_keys_are_for_the_admin_only(client, auth, member_auth):
    # A member cannot see the API keys section at all, let alone change it.
    assert client.get("/api/credentials", headers=member_auth).status_code == 403
    assert client.get("/api/settings/integrations", headers=member_auth).status_code == 403
    assert client.put("/api/credentials/youtube", headers=member_auth, json={"values": {"api_key": "x"}}).status_code == 403
    assert client.post("/api/credentials/youtube/validate", headers=member_auth, json={}).status_code == 403
    assert client.delete("/api/credentials/youtube", headers=member_auth).status_code == 403
    assert client.post("/api/settings/integrations/ffmpeg/test", headers=member_auth).status_code == 403
    assert client.put("/api/settings/notifications", headers=member_auth, json={"email": "x@example.com"}).status_code == 403
    card = _card(client, auth, "youtube")
    assert card["configured"] is False and "fields" in card and "redirect_uri" not in card


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

    assert notify.send(db, "failure", "Job #1 failed for northbound") is True
    assert "failed" in FakeSMTP.sent[-1]["Subject"]

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
