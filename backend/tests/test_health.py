"""Health and ML-status endpoint tests."""


def test_root(app_client):
    r = app_client.get("/")
    assert r.status_code == 200
    assert "running" in r.json()["message"]


def test_health(app_client):
    r = app_client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"
    assert r.json()["database"] == "connected"


def test_health_ml_reports_model_availability(app_client, ml_tmp_models):
    r = app_client.get("/api/health/ml")
    assert r.status_code == 200
    models = r.json()["models"]
    # Preprocessing artefacts exist for all four domains in the repo.
    for domain in ("crop", "fertilizer", "yield", "irrigation"):
        assert models[domain]["preprocessing"] is True, domain
    # Pointed at an empty temp models dir -> all report model=False.
    assert models["crop"]["model"] is False
    assert models["irrigation"]["model"] is False
