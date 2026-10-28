"""Profile endpoints (GET/PATCH /api/users/me).

The role is editable here because the signup form no longer asks for one — so
"agricultural_expert" must stay reachable without a supervisor editing the row
in the database.
"""


def _auth(fake_client, uid="u1", **profile):
    fake_client.seed_profile(uid=uid, email=f"{uid}@example.com", **profile)
    return fake_client.auth_header(uid)


def test_get_me_returns_the_profile(app_client, fake_client):
    h = _auth(fake_client, full_name="Ravi Kumar", role="farmer")
    r = app_client.get("/api/users/me", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == "u1"
    assert body["full_name"] == "Ravi Kumar"
    assert body["role"] == "farmer"


def test_get_me_requires_a_token(app_client):
    assert app_client.get("/api/users/me").status_code == 401


def test_patch_me_updates_the_full_name(app_client, fake_client):
    h = _auth(fake_client)
    r = app_client.patch("/api/users/me", json={"full_name": "Ravi S. Kumar"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["full_name"] == "Ravi S. Kumar"


def test_patch_me_accepts_a_supported_role(app_client, fake_client):
    h = _auth(fake_client, role="farmer")
    r = app_client.patch("/api/users/me", json={"role": "agricultural_expert"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "agricultural_expert"

    # The change must persist, not just be echoed.
    assert app_client.get("/api/users/me", headers=h).json()["role"] == "agricultural_expert"


def test_patch_me_rejects_an_unknown_role(app_client, fake_client):
    h = _auth(fake_client)
    r = app_client.patch("/api/users/me", json={"role": "admin"}, headers=h)
    assert r.status_code == 400, r.text
    assert "role must be one of" in r.json()["detail"]


def test_patch_me_requires_a_token(app_client):
    assert app_client.patch("/api/users/me", json={"full_name": "Nobody"}).status_code == 401
