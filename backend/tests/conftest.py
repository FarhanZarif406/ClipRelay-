import os
import tempfile

from cryptography.fernet import Fernet

_TMP = tempfile.mkdtemp(prefix="cliprelay-test-")
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": f"sqlite:///{os.path.join(_TMP, 'test.db')}",
        "SECRET_KEY": "test-secret",
        "ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "LLM_PROVIDER": "anthropic",
        "LLM_MODEL": "claude-test",
        "LLM_API_KEY": "sk-test",
        "TIKTOK_CLIENT_KEY": "tt-key",
        "TIKTOK_CLIENT_SECRET": "tt-secret",
        "STORAGE_BACKEND": "local",
        "STORAGE_LOCAL_PATH": os.path.join(_TMP, "media"),
        "PUBLIC_BASE_URL": "http://api.test",
        "FRONTEND_URL": "http://app.test",
    }
)

from datetime import timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.integrations import http as http_module  # noqa: E402
from app.main import app  # noqa: E402
from app.models import PromptTemplate, TikTokAccount, utcnow  # noqa: E402
from app.security import encrypt  # noqa: E402
from app.services import credentials, dispatch, llm_registry, media  # noqa: E402
from app.services.prompts import DEFAULT_TEMPLATE  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    dispatch.sent.clear()
    credentials.bust()
    llm_registry.bust()
    monkeypatch.setattr(http_module.time, "sleep", lambda *_: None)
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth(client):
    r = client.post("/api/auth/register", json={"email": "alex@example.com", "password": "password123", "name": "Alex Smith"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def template(db):
    t = PromptTemplate(**DEFAULT_TEMPLATE, is_default=True)
    db.add(t)
    db.commit()
    return t


@pytest.fixture
def tiktok_account(db):
    account = TikTokAccount(
        open_id="open-1",
        username="northbound",
        access_token_enc=encrypt("tt-access"),
        refresh_token_enc=encrypt("tt-refresh"),
        token_expires_at=utcnow() + timedelta(hours=20),
        refresh_expires_at=utcnow() + timedelta(days=300),
        daily_cap=10,
    )
    db.add(account)
    db.commit()
    return account


@pytest.fixture
def channel(db, tiktok_account):
    from app.models import Channel

    row = Channel(
        youtube_channel_id="UC" + "a" * 22, handle="@northbound", display_name="Northbound", active=True,
        default_tiktok_account_id=tiktok_account.id,
        monitoring_since=utcnow() - timedelta(days=1),
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def fake_media(monkeypatch):
    """Replace the YouTube download and FFmpeg. `calls` records every render with its settings."""
    from app.services import sources

    calls: list[dict] = []

    def make_file() -> str:
        fd, path = tempfile.mkstemp(suffix=".mp4")
        with os.fdopen(fd, "wb") as fh:
            fh.write(b"\x00" * 2048)
        return path

    class Adapter:
        name = "fake"

        def download(self, video):
            if calls and calls[0].get("fail_download"):
                calls[0]["fail_download"] -= 1
                raise sources.SourceError("The video is private")
            return make_file()

    def render(src, *, speed, flip, keep_audio):
        calls.append({"speed": speed, "flip": flip, "keep_audio": keep_audio})
        return make_file()

    monkeypatch.setattr(sources, "get_adapter", lambda: Adapter())
    monkeypatch.setattr(media, "probe", lambda path: media.ProbeResult(30.0, 1080, 1920, True))
    monkeypatch.setattr(media, "render", render)
    return calls


@pytest.fixture
def member_auth(client, auth):
    r = client.post("/api/users", headers=auth, json={"email": "sam@example.com", "password": "password123", "name": "Sam"})
    assert r.status_code == 201, r.text
    token = client.post("/api/auth/login", json={"email": "sam@example.com", "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
