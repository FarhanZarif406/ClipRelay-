from app.models import Credential
from app.services import credentials


def test_env_fallback_when_nothing_saved():
    assert credentials.get("tiktok.client_key") == "tt-key"  # from conftest env
    assert credentials.source("tiktok.client_key") == "env"
    assert credentials.get("transcription.api_key") == "" and credentials.source("transcription.api_key") is None


def test_db_overrides_env_and_is_encrypted(db):
    credentials.set_value(db, "tiktok.client_key", "db-key", user_id=None)
    db.commit()
    credentials.changed()
    assert credentials.get("tiktok.client_key") == "db-key"
    assert credentials.source("tiktok.client_key") == "app"
    stored = db.get(Credential, "tiktok.client_key").value_enc
    assert stored and "db-key" not in stored


def test_removal_falls_back_to_env(db):
    credentials.set_value(db, "tiktok.client_key", "db-key", user_id=None)
    db.commit()
    credentials.remove(db, ["tiktok.client_key"])
    db.commit()
    credentials.changed()
    assert credentials.get("tiktok.client_key") == "tt-key"


def test_cache_busts_on_write(db):
    assert credentials.get("instagram.app_id") == "ig-app"  # warms the cache
    credentials.set_value(db, "instagram.app_id", "123456", user_id=None)
    db.commit()
    assert credentials.get("instagram.app_id") == "123456"  # set_value busts the local cache


def test_group_status(db):
    assert credentials.group_status(db, "tiktok")["state"] == "env"
    assert credentials.group_status(db, "transcription")["state"] == "env"  # base_url/model default in Settings
    credentials.set_value(db, "tiktok.client_key", "k", user_id=None)
    assert credentials.group_status(db, "tiktok")["state"] == "unverified"
    credentials.set_status(db, "tiktok", "invalid", "bad secret")
    status = credentials.group_status(db, "tiktok")
    assert status["state"] == "invalid" and status["last_error"] == "bad secret"
