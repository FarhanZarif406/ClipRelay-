def test_register_login_me(client):
    assert client.get("/api/auth/setup").json() == {"has_users": False, "registration_open": True}
    r = client.post("/api/auth/register", json={"email": "Alex@Example.com", "password": "password123", "name": "Alex"})
    assert r.status_code == 201
    token = r.json()["access_token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["email"] == "alex@example.com"

    login = client.post("/api/auth/login", json={"email": "alex@example.com", "password": "password123"})
    assert login.status_code == 200 and login.json()["access_token"]


def test_wrong_password_and_closed_registration(client, auth):
    assert client.post("/api/auth/login", json={"email": "alex@example.com", "password": "nope-nope"}).status_code == 401
    r = client.post("/api/auth/register", json={"email": "other@example.com", "password": "password123"})
    assert r.status_code == 403


def test_protected_routes_require_token(client):
    assert client.get("/api/dashboard/summary").status_code == 401
    assert client.get("/api/jobs", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_team_members(client, auth):
    r = client.post("/api/users", headers=auth, json={"email": "sam@example.com", "password": "password123", "name": "Sam"})
    assert r.status_code == 201
    users = client.get("/api/users", headers=auth).json()
    assert {u["email"] for u in users} == {"alex@example.com", "sam@example.com"}
    assert client.delete(f"/api/users/{users[0]['id']}", headers=auth).status_code == 400  # can't remove self
