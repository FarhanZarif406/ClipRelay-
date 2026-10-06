import httpx
import respx

from app.models import ActivityLog, LLMProvider
from app.security import encrypt
from app.services import credential_checks, credentials, workspace_settings
from app.services.credential_checks import TIKTOK_TOKEN_URL


@respx.mock
def test_daily_check_marks_failures_and_notifies(db):
    credentials.set_value(db, "tiktok.client_key", "k", None)
    credentials.set_value(db, "tiktok.client_secret", "s", None)
    credentials.set_status(db, "tiktok", "valid")
    db.add(LLMProvider(label="Groq", provider="groq", api_key_enc=encrypt("gsk"), model="llama", is_default=True, status="valid"))
    workspace_settings.update(db, "notifications", {"webhook_url": "https://hooks.example.com/x"})
    db.commit()
    credentials.changed()
    respx.post(TIKTOK_TOKEN_URL).mock(return_value=httpx.Response(401, json={"error": "invalid_client", "error_description": "revoked"}))
    respx.get("https://api.groq.com/openai/v1/models").mock(return_value=httpx.Response(200, json={"data": [{"id": "llama"}]}))
    hook = respx.post("https://hooks.example.com/x").mock(return_value=httpx.Response(200))

    summary = credential_checks.run_daily(db)
    assert summary["checked"] == 2 and summary["failed"] == ["tiktok"]
    assert credentials.group_status(db, "tiktok")["state"] == "invalid"
    assert db.query(LLMProvider).one().status == "valid"
    assert hook.call_count == 1 and b"Tiktok credentials stopped working" in hook.calls[0].request.content
    assert db.query(ActivityLog).filter(ActivityLog.event == "credential_check_failed").count() == 1

    # Already invalid → no repeat alert
    credential_checks.run_daily(db)
    assert hook.call_count == 1
