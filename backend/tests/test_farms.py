"""Farm CRUD + ownership tests."""


def _auth(fake_client, uid="u1"):
    fake_client.seed_profile(uid=uid, email=f"{uid}@example.com", mobile=f"+91{uid}0000000")
    return fake_client.auth_header(uid)


def test_create_get_list_update_delete_farm(app_client, fake_client):
    h = _auth(fake_client)
    r = app_client.post("/api/farms", json={"name": "Green Valley", "location": "Nashik"}, headers=h)
    assert r.status_code == 201, r.text
    farm = r.json()
    assert farm["name"] == "Green Valley"
    assert farm["owner_id"] == "u1"
    fid = farm["id"]

    # list
    lst = app_client.get("/api/farms", headers=h).json()
    assert lst["total"] >= 1
    assert any(f["id"] == fid for f in lst["items"])

    # get
    assert app_client.get(f"/api/farms/{fid}", headers=h).status_code == 200

    # update
    upd = app_client.patch(f"/api/farms/{fid}", json={"name": "Green Valley 2"}, headers=h)
    assert upd.status_code == 200
    assert upd.json()["name"] == "Green Valley 2"

    # delete
    assert app_client.delete(f"/api/farms/{fid}", headers=h).status_code == 204
    assert app_client.get(f"/api/farms/{fid}", headers=h).status_code == 404


def test_farm_not_owned_returns_404(app_client, fake_client):
    h1 = _auth(fake_client, "u1")
    h2 = _auth(fake_client, "u2")
    r = app_client.post("/api/farms", json={"name": "Owned by u2", "location": "Pune"}, headers=h2)
    fid = r.json()["id"]
    # u1 must not see or access u2's farm.
    assert app_client.get(f"/api/farms/{fid}", headers=h1).status_code == 404
    assert app_client.delete(f"/api/farms/{fid}", headers=h1).status_code == 404


def test_protected_route_requires_token(app_client):
    assert app_client.get("/api/farms").status_code == 401
