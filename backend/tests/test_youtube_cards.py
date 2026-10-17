import hashlib
import hmac
from datetime import timedelta
from urllib.parse import parse_qs

import httpx
import respx

from app.integrations import youtube
from app.models import utcnow
from app.services import detection, dispatch, push, youtube_usage
from tests.test_youtube import atom

KEY = "AIzaSyD-test-key-0123456789abcdefghijkl"
I18N = "https://www.googleapis.com/youtube/v3/i18nLanguages"
BASE = "https://clips.example.com"


@respx.mock
def test_youtube_data_api_card(client, auth, member_auth, monkeypatch):
    monkeypatch.setattr(youtube_usage, "_pending", {"units": 0, "video_calls": 0, "last_ok_at": None})
    assert client.get("/api/integrations/youtube", headers=member_auth).status_code == 403  # API keys are the admin's only
    status = client.get("/api/integrations/youtube", headers=auth).json()
    assert status["has_key"] is False and status["usage"]["units_today"] == 0
    assert client.post("/api/integrations/youtube/test", headers=auth).json()["message"] == "No API key saved."

    assert client.put("/api/integrations/youtube", headers=auth, json={"api_key": "short"}).status_code == 422
    assert client.put("/api/integrations/youtube", headers=auth, json={"project_id": "Bad Project"}).status_code == 422
    saved = client.put("/api/integrations/youtube", headers=auth, json={"api_key": KEY, "project_id": "clip-relay-123"})
    assert saved.status_code == 200 and KEY not in saved.text  # only the last four characters come back
    assert saved.json()["has_key"] and saved.json()["key_last4"] == KEY[-4:] and saved.json()["project_id"] == "clip-relay-123"
    assert youtube.api_key() == KEY

    google = respx.get(I18N).mock(return_value=httpx.Response(403, json={"error": {"message": "API key not valid.", "errors": [{"reason": "badRequest"}]}}))
    bad = client.post("/api/integrations/youtube/test", headers=auth).json()
    assert (bad["ok"], bad["status"], bad["reason"], bad["message"]) == (False, 403, "badRequest", "API key not valid.")
    google.mock(return_value=httpx.Response(200, json={"items": []}))
    good = client.post("/api/integrations/youtube/test", headers=auth).json()
    assert good["ok"] is True and good["status_info"]["usage"]["units_today"] == 2 and good["status_info"]["usage"]["last_ok_at"]

    assert client.delete("/api/integrations/youtube/key", headers=auth).json()["has_key"] is False
    assert youtube.api_key() == "" and client.delete("/api/integrations/youtube/key", headers=auth).status_code == 404


@respx.mock
def test_push_notifications_card(client, auth, member_auth, db, channel):
    hub = respx.post(youtube.HUB_URL).mock(return_value=httpx.Response(202))
    assert client.get("/api/integrations/push", headers=member_auth).status_code == 403
    status = client.get("/api/integrations/push", headers=auth).json()
    assert status["available"] is False and status["callback_url"] == "" and status["subscriptions"] == []  # http://api.test is not public
    assert client.post("/api/integrations/push/subscribe", headers=auth, json={"channel_id": channel.youtube_channel_id}).status_code == 422

    for bad in ("not a url", "http://clips.example.com", "https://localhost:8000"):
        assert client.put("/api/integrations/push", headers=auth, json={"public_base_url": bad}).status_code == 422
    assert client.put("/api/integrations/push", headers=auth, json={"verify_token": "has spaces"}).status_code == 422

    # Saving a public address subscribes every monitored channel to the new callback, with a verify token.
    status = client.put("/api/integrations/push", headers=auth, json={"public_base_url": BASE + "/"}).json()
    assert status["available"] and status["callback_url"] == BASE + "/api/youtube/webhook" and status["base_source"] == "app"
    sent = {k: v[0] for k, v in parse_qs(hub.calls[0].request.content.decode()).items()}
    token = sent["hub.verify_token"]
    assert sent["hub.callback"] == BASE + "/api/youtube/webhook" and token == push.verify_token() and len(token) >= 8
    assert status["has_token"] and status["token_last4"] == token[-4:] and token not in str(status)
    assert status["subscriptions"] == [{"channel_id": channel.youtube_channel_id, "status": "pending", "detail": "Hub accepted the request; waiting for it to verify the callback.", "expires_at": None}]
    assert client.get("/api/channels", headers=auth).json()["push_available"] is True

    # The hub's verification is answered only with the saved token.
    topic = youtube.topic_url(channel.youtube_channel_id)
    ask = {"hub.mode": "subscribe", "hub.topic": topic, "hub.challenge": "xyz", "hub.lease_seconds": 432000}
    assert client.get("/api/youtube/webhook", params={**ask, "hub.verify_token": "wrong-token"}).status_code == 404
    db.refresh(channel)
    assert detection.push_status(channel) == "failed" and "verify token" in channel.pubsub_error
    r = client.get("/api/youtube/webhook", params={**ask, "hub.verify_token": token})
    assert r.status_code == 200 and r.text == "xyz"
    db.refresh(channel)
    assert detection.push_status(channel) == "subscribed"
    # A stranger with a wrong token cannot break a subscription that already works.
    assert client.get("/api/youtube/webhook", params={**ask, "hub.verify_token": "wrong-token"}).status_code == 404
    db.refresh(channel)
    assert detection.push_status(channel) == "subscribed"

    # A replaced token is used from the next subscribe request on.
    client.put("/api/integrations/push", headers=auth, json={"verify_token": "my-own-token-1"})
    assert push.verify_token() == "my-own-token-1" and hub.call_count == 1  # the address did not change: nothing is re-subscribed
    client.post("/api/integrations/push/subscribe", headers=auth, json={"channel_id": channel.youtube_channel_id})
    assert "hub.verify_token=my-own-token-1" in hub.calls[1].request.content.decode()
    assert client.post("/api/integrations/push/subscribe", headers=auth, json={"channel_id": "UC" + "z" * 22}).status_code == 404
    assert client.post("/api/integrations/push/subscribe", headers=auth, json={"channel_id": "nope"}).status_code == 422

    # Notifications are counted.
    body = atom(("abc", utcnow().isoformat()))
    signature = "sha1=" + hmac.new(youtube.hub_secret().encode(), body, hashlib.sha1).hexdigest()
    client.post("/api/youtube/webhook", content=body, headers={"X-Hub-Signature": "sha1=forged"})
    client.post("/api/youtube/webhook", content=body, headers={"X-Hub-Signature": signature})
    assert client.get("/api/integrations/push", headers=auth).json()["notifications"]["today"] == 1
    assert [(name, args[:2]) for name, args in dispatch.sent] == [("discover_video", (channel.youtube_channel_id, "abc"))]  # the title and upload time come along


@respx.mock
def test_failed_subscriptions_are_retried_alone(client, auth, db, channel):
    hub = respx.post(youtube.HUB_URL).mock(return_value=httpx.Response(500, text="hub is down"))
    status = client.put("/api/integrations/push", headers=auth, json={"public_base_url": BASE}).json()
    assert status["subscriptions"][0]["status"] == "failed" and "hub is down" in status["subscriptions"][0]["detail"]
    hub.mock(return_value=httpx.Response(202))
    before = hub.call_count
    assert client.post("/api/integrations/push/retry-failed", headers=auth).json()["subscriptions"][0]["status"] == "pending"
    assert hub.call_count == before + 1
    client.post("/api/integrations/push/retry-failed", headers=auth)
    assert hub.call_count == before + 1  # nothing failed any more, so nothing is sent

    # The hub accepted the request but never called back: after a minute that is a failure, with the reason.
    db.refresh(channel)
    channel.pubsub_requested_at = utcnow() - timedelta(minutes=2)
    db.commit()
    assert detection.push_status(channel) == "failed" and "never verified" in detection.push_detail(channel)
    # The hub says no.
    channel.pubsub_requested_at = utcnow()
    db.commit()
    client.get("/api/youtube/webhook", params={"hub.mode": "denied", "hub.topic": youtube.topic_url(channel.youtube_channel_id), "hub.reason": "blocked"})
    db.refresh(channel)
    assert channel.pubsub_error == "Hub denied: blocked"
