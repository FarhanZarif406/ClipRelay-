"""Every member uses their own AI model and YouTube key; the owners' are never used for a member's videos."""

from sqlalchemy import select

from app.integrations import youtube
from app.models import CaptionStatus, JobStatus, LLMProvider, User, Video
from app.security import encrypt
from app.services import acting, credentials, llm_registry, pipeline
from tests.test_pipeline import _make_job  # noqa: E402


def test_a_member_has_their_own_youtube_key(client, auth, member_auth, db, monkeypatch):
    member_id = db.scalar(select(User.id).where(User.role == "member"))
    assert client.get("/api/my-keys/youtube", headers=member_auth).json() == {"has_key": False, "key_last4": "", "shared": False}
    monkeypatch.setattr(youtube, "test_key", lambda key: {"ok": key.endswith("good"), "message": "OK" if key.endswith("good") else "API key not valid"})
    assert client.put("/api/my-keys/youtube", headers=member_auth, json={"api_key": "AIzaSy-member-key-is-bad"}).status_code == 400
    saved = client.put("/api/my-keys/youtube", headers=member_auth, json={"api_key": "AIzaSy-member-key-is-good"}).json()
    assert saved["has_key"] is True and saved["key_last4"] == "good"

    # Lookups made for the member use their key; the owners' shared key stays theirs.
    monkeypatch.setattr(credentials, "get", lambda key: "owners-shared-key" if key == "youtube.api_key" else "")
    with acting.scope(member_id):
        assert youtube.api_key() == "AIzaSy-member-key-is-good"
    with acting.scope(None):
        assert youtube.api_key() == "owners-shared-key"

    # The owner can see and set it for them; a member cannot reach another account's.
    assert client.get(f"/api/my-keys/youtube?for_user={member_id}", headers=auth).json()["has_key"] is True
    assert client.get("/api/my-keys/youtube?for_user=1", headers=member_auth).status_code == 403
    assert client.delete(f"/api/my-keys/youtube?for_user={member_id}", headers=auth).json()["has_key"] is False


def test_a_members_video_never_uses_the_owners_ai_model(db, member_auth, template):
    db.add(LLMProvider(label="Owners", provider="groq", api_key_enc=encrypt("gsk-owner"), model="m", is_default=True))
    db.commit()
    llm_registry.bust()
    job = _make_job(db, status=JobStatus.REWRITING, caption="pending")
    db.get(Video, job.video_id).user_id = db.scalar(select(User.id).where(User.role == "member"))
    db.commit()
    pipeline.rewrite_job(db, job.id)  # no network call is made: the member has no model of their own
    assert job.caption_status == CaptionStatus.FALLBACK and job.rewritten_caption == "Hidden beaches in Crete"
