"""Input validation + out-of-range warning tests (feature 2).

The unit tests exercise ``ml.validation`` directly against the raw datasets
that ship with the repository, so they assert the ranges are *derived*, not
invented. The endpoint tests confirm the API rejects unusable payloads with
HTTP 422 instead of silently producing a prediction, and that values which are
valid but lie outside the training data come back as warnings (HTTP 200)
rather than being clamped.
"""
from ml import validation


def _crop(**overrides):
    body = {"N": 90, "P": 40, "K": 40, "temperature": 25, "humidity": 80,
            "ph": 6.5, "rainfall": 200}
    body.update(overrides)
    return body


def _auth(fake_client, uid="u1"):
    fake_client.seed_profile(uid=uid, email=f"{uid}@example.com", mobile=f"+91{uid}0000000")
    return fake_client.auth_header(uid)


# ─────────────────────────────────────────────────────────────────────────
# ml.validation unit tests
# ─────────────────────────────────────────────────────────────────────────

def test_out_of_supported_range_is_invalid():
    out = validation.validate("crop", _crop(N=900))
    assert out["ok"] is False
    issue = next(i for i in out["invalid"] if i["field"] == "N")
    assert issue["kind"] == "out_of_supported_range"
    assert issue["supported_min"] == 0 and issue["supported_max"] == 200
    assert "not changed" in issue["message"]


def test_missing_value_is_invalid():
    out = validation.validate("crop", _crop(humidity=None))
    assert out["ok"] is False
    issue = next(i for i in out["invalid"] if i["field"] == "humidity")
    assert issue["kind"] == "missing"


def test_non_numeric_value_is_invalid():
    out = validation.validate("crop", _crop(ph="not-a-number"))
    assert out["ok"] is False
    issue = next(i for i in out["invalid"] if i["field"] == "ph")
    assert issue["kind"] == "not_a_number"


def test_valid_but_outside_training_range_is_unusual_not_invalid():
    """N = 180 is a real agricultural value inside the supported range (<=200)
    but above the crop dataset's maximum (140): warn, do not block."""
    out = validation.validate("crop", _crop(N=180))
    assert out["ok"] is True
    assert out["invalid"] == []
    issue = next(u for u in out["unusual"] if u["field"] == "N")
    assert issue["kind"] == "outside_training_range"
    assert issue["training_max"] == 140.0
    assert issue["value"] == 180


def test_validation_never_mutates_the_payload():
    body = _crop(N=900, rainfall=99999)
    before = dict(body)
    validation.validate("crop", body)
    assert body == before


def test_every_valid_prediction_carries_the_accuracy_advisory():
    out = validation.validate("crop", _crop())
    assert out["ok"] is True
    assert out["advisory"]
    assert "does not guarantee" in out["advisory"][0]


def test_schema_exposes_supported_and_training_ranges():
    fields = {f["field"]: f for f in validation.schema("crop")["fields"]}
    n = fields["N"]
    assert n["supported_min"] == 0 and n["supported_max"] == 200
    assert n["training_max"] == 140.0
    assert n["unit"] == "kg/ha"


# ─────────────────────────────────────────────────────────────────────────
# Endpoint tests
# ─────────────────────────────────────────────────────────────────────────

def test_schema_endpoint(app_client):
    r = app_client.get("/api/predictions/schema/crop")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["domain"] == "crop"
    assert any(f["field"] == "N" and f["supported_max"] == 200 for f in body["fields"])
    assert body["advisory"]


def test_schema_endpoint_unknown_domain_is_404(app_client):
    assert app_client.get("/api/predictions/schema/nope").status_code == 404


def test_out_of_range_value_is_rejected_before_any_prediction(app_client, fake_client, ml_tmp_models):
    h = _auth(fake_client)
    r = app_client.post("/api/predictions/crop", json=_crop(N=900), headers=h)
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["detail"]
    assert body["errors"], "422 must explain what is wrong"
    # Nothing was predicted — the invalid value was not clamped and used.
    assert "prediction" not in body


def test_missing_required_field_is_rejected(app_client, fake_client, ml_tmp_models):
    h = _auth(fake_client)
    body = _crop()
    body.pop("rainfall")
    r = app_client.post("/api/predictions/crop", json=body, headers=h)
    assert r.status_code == 422, r.text
    assert "prediction" not in r.json()
