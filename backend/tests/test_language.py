"""An account chooses English or Roman Urdu; the common refusals come back in its language."""

from app import i18n


def test_language_is_saved_and_messages_follow_it(client, auth):
    assert client.get("/api/auth/me", headers=auth).json()["language"] == "en"
    assert client.patch("/api/auth/me", headers=auth, json={"language": "ur"}).json()["language"] == "ur"
    assert client.patch("/api/auth/me", headers=auth, json={"language": "fr"}).status_code == 422
    bad = {"email": "nobody@example.com", "password": "wrong-password-1"}
    assert client.post("/api/auth/login", json=bad).json()["detail"] == "Incorrect email or password"
    assert client.post("/api/auth/login", json=bad, headers={"X-Lang": "ur"}).json()["detail"] == "Email ya password ghalat hai"


def test_patterns_carry_numbers_and_names():
    assert i18n.translate("Your plan allows 50 channels. Remove one, or ask the owner to upgrade your plan.", "ur").startswith("Aap ka plan 50 channels")
    assert "Rounded title box, Grain" in i18n.translate("These are for paid members: Rounded title box, Grain. Switch them off to save, or ask the owner to upgrade your plan.", "ur")
    assert i18n.translate("Something new", "ur") == "Something new" and i18n.translate("Incorrect email or password", "en") == "Incorrect email or password"
