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
        "INSTAGRAM_APP_ID": "ig-app",
        "INSTAGRAM_APP_SECRET": "ig-secret",
        "TIKTOK_CLIENT_KEY": "tt-key",
        "TIKTOK_CLIENT_SECRET": "tt-secret",
        "TRANSCRIPTION_API_KEY": "",
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
from app.models import InstagramSource, PromptTemplate, TikTokAccount, utcnow  # noqa: E402
from app.security import encrypt  # noqa: E402
from app.services import credentials, dispatch, media  # noqa: E402
from app.services.prompts import DEFAULT_TEMPLATE  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    dispatch.sent.clear()
    credentials.bust()
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
def source(db, tiktok_account):
    s = InstagramSource(
        ig_user_id="1789",
        username="slowtravel",
        access_token_enc=encrypt("ig-access"),
        token_expires_at=utcnow() + timedelta(days=50),
        token_refreshed_at=utcnow(),
        is_active=True,
        refresh_interval_minutes=30,
    )
    s.tiktok_accounts = [tiktok_account]
    db.add(s)
    db.commit()
    return s


@pytest.fixture
def fake_media(monkeypatch):
    """Replace download + ffprobe. Durations are looked up by media URL."""
    durations: dict[str, float] = {}

    def download(url: str, retries: int = 3) -> str:
        fd, path = tempfile.mkstemp(suffix=".mp4")
        with os.fdopen(fd, "wb") as fh:
            fh.write(b"\x00" * 2048)
        durations[path] = durations.get(url, 30.0)
        return path

    def probe(path: str) -> media.ProbeResult:
        return media.ProbeResult(durations[path], 1080, 1920)

    monkeypatch.setattr(media, "download", download)
    monkeypatch.setattr(media, "probe", probe)
    return durations


@pytest.fixture
def member_auth(client, auth):
    r = client.post("/api/users", headers=auth, json={"email": "sam@example.com", "password": "password123", "name": "Sam"})
    assert r.status_code == 201, r.text
    token = client.post("/api/auth/login", json={"email": "sam@example.com", "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
