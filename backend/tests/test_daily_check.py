import httpx
import respx

from app.models import ActivityLog, LLMProvider
from app.security import encrypt
from app.services import credential_checks, credentials, workspace_settings


@respx.mock
def test_daily_check_marks_failures_and_notifies(db):
    credentials.set_value(db, "youtube.api_key", "k", None)
    credentials.set_status(db, "youtube", "valid")
    db.add(LLMProvider(label="Groq", provider="groq", api_key_enc=encrypt("gsk"), model="llama", is_default=True, status="valid"))
    workspace_settings.update(db, "notifications", {"webhook_url": "https://hooks.example.com/x"})
    db.commit()
    credentials.changed()
    respx.get("https://www.googleapis.com/youtube/v3/channels").mock(return_value=httpx.Response(400, json={"error": {"message": "API key not valid"}}))
    respx.get("https://api.groq.com/openai/v1/models").mock(return_value=httpx.Response(200, json={"data": [{"id": "llama"}]}))
    hook = respx.post("https://hooks.example.com/x").mock(return_value=httpx.Response(200))

    summary = credential_checks.run_daily(db)
    assert summary["checked"] == 2 and summary["failed"] == ["youtube"]
    assert credentials.group_status(db, "youtube")["state"] == "invalid"
    assert db.query(LLMProvider).one().status == "valid"
    assert hook.call_count == 1 and b"Youtube credentials stopped working" in hook.calls[0].request.content
    assert db.query(ActivityLog).filter(ActivityLog.event == "credential_check_failed").count() == 1

    # Already invalid → no repeat alert
    credential_checks.run_daily(db)
    assert hook.call_count == 1
