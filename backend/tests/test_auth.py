"""Auth endpoint tests (brokered Supabase Auth via the fake client)."""

REGISTER = {
    "full_name": "Meera Shah",
    "email": "meera@example.com",
    "mobile": "+919988776655",
    "role": "farmer",
    "password": "Secure123",
}


def test_register_returns_user_and_token(app_client):
    r = app_client.post("/api/auth/register", json=REGISTER)
    assert r.status_code == 201, r.text
    data = r.json()
    # Frontend contract: these fields are present and stored as the user object.
    assert data["full_name"] == "Meera Shah"
    assert data["email"] == "meera@example.com"
    assert data["mobile"] == "+919988776655"
    assert data["role"] == "farmer"
    assert data["created_at"]
    assert data["access_token"]


def test_login_with_registered_mobile(app_client):
    app_client.post("/api/auth/register", json=REGISTER)
    r = app_client.post("/api/auth/login", json={"mobile": REGISTER["mobile"], "password": REGISTER["password"]})
    assert r.status_code == 200, r.text
    assert r.json()["full_name"] == "Meera Shah"
    assert r.json()["access_token"]


def test_login_wrong_password(app_client):
    app_client.post("/api/auth/register", json=REGISTER)
    r = app_client.post("/api/auth/login", json={"mobile": REGISTER["mobile"], "password": "WrongPass1"})
    assert r.status_code == 401


def test_login_unknown_mobile(app_client):
    r = app_client.post("/api/auth/login", json={"mobile": "+910000000000", "password": "Whatever1"})
    assert r.status_code == 401


def test_register_duplicate_mobile_is_conflict(app_client):
    app_client.post("/api/auth/register", json=REGISTER)
    dup = {**REGISTER, "email": "other@example.com"}
    r = app_client.post("/api/auth/register", json=dup)
    assert r.status_code == 409


def test_register_invalid_role_rejected(app_client):
    bad = {**REGISTER, "role": "admin", "email": "bad@example.com", "mobile": "+919111111111"}
    r = app_client.post("/api/auth/register", json=bad)
    assert r.status_code == 400


def test_register_without_a_role_defaults_to_farmer(app_client):
    """The signup form no longer asks for a role; the backend must supply one.

    A farmer signing up cannot reasonably classify themselves at that moment,
    so ``role`` is optional and defaults to the common case. It stays editable
    afterwards through PATCH /api/users/me.
    """
    payload = {k: v for k, v in REGISTER.items() if k != "role"}
    payload["email"] = "norole@example.com"
    payload["mobile"] = "+919222233334"

    r = app_client.post("/api/auth/register", json=payload)
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "farmer"
