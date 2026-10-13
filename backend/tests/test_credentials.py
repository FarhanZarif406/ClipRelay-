from app.models import Credential
from app.services import credentials


def test_env_fallback_when_nothing_saved():
    assert credentials.get("smtp.username") == "env-user"  # from conftest env
    assert credentials.source("smtp.username") == "env"
    assert credentials.get("smtp.host") == "" and credentials.source("smtp.host") is None


def test_db_overrides_env_and_is_encrypted(db):
    credentials.set_value(db, "smtp.username", "db-key", user_id=None)
    db.commit()
    credentials.changed()
    assert credentials.get("smtp.username") == "db-key"
    assert credentials.source("smtp.username") == "app"
    stored = db.get(Credential, "smtp.username").value_enc
    assert stored and "db-key" not in stored


def test_removal_falls_back_to_env(db):
    credentials.set_value(db, "smtp.username", "db-key", user_id=None)
    db.commit()
    credentials.remove(db, ["smtp.username"])
    db.commit()
    credentials.changed()
    assert credentials.get("smtp.username") == "env-user"


def test_cache_busts_on_write(db):
    assert credentials.get("smtp.username") == "env-user"  # warms the cache
    credentials.set_value(db, "smtp.username", "123456", user_id=None)
    db.commit()
    assert credentials.get("smtp.username") == "123456"  # set_value busts the local cache


def test_group_status(db):
    assert credentials.group_status(db, "youtube")["state"] == "none"
    assert credentials.group_status(db, "smtp")["state"] == "env"  # port/security default in Settings
    credentials.set_value(db, "youtube.api_key", "k", user_id=None)
    assert credentials.group_status(db, "youtube")["state"] == "unverified"
    credentials.set_status(db, "youtube", "invalid", "bad secret")
    status = credentials.group_status(db, "youtube")
    assert status["state"] == "invalid" and status["last_error"] == "bad secret"


def test_builtin_defaults_are_not_reported_as_env():
    assert credentials.source("smtp.security") == "default"
    assert credentials.source("smtp.port") == "default"
    assert credentials.source("smtp.username") == "env"
