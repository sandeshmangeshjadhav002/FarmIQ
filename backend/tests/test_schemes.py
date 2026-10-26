"""Government schemes tests (feature 6).

The content is static, human-verified reference data in
``app/data/government_schemes.json`` — no LLM and no RAG. These tests assert the
endpoint serves it, that every scheme carries an official application link and a
last-verified date, and that fields which could not be confirmed from an
official source are explicitly marked ``needs_verification`` rather than
presented as fact.
"""
REQUIRED_SCHEMES = {"pm-kisan", "pmfby", "soil-health-card"}
VALID_STATUSES = {"confirmed", "needs_verification"}


def test_schemes_list_serves_metadata_and_schemes(app_client):
    r = app_client.get("/api/schemes")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["total"] >= 3
    assert REQUIRED_SCHEMES <= {s["id"] for s in body["schemes"]}
    assert body["metadata"]["last_verified"]
    assert body["metadata"]["disclaimer"]
    assert set(body["legend"]) == VALID_STATUSES
    assert body["categories"]
    assert body["cautions"]


def test_every_scheme_has_an_official_link_or_explains_why_not(app_client):
    schemes = app_client.get("/api/schemes").json()["schemes"]
    assert schemes
    for scheme in schemes:
        assert scheme["name"]
        assert scheme["last_verified"], scheme["id"]
        if scheme["official_links"]:
            for link in scheme["official_links"]:
                assert link["label"]
                assert link["url"].startswith("https://"), link["url"]
        else:
            # No link was invented for schemes administered offline (banks /
            # state departments) — the reason must be stated instead.
            assert scheme.get("verification_note"), scheme["id"]


def test_unverifiable_fields_are_flagged_not_presented_as_fact(app_client):
    """Anything that is not confirmed must carry an explicit status."""
    schemes = app_client.get("/api/schemes").json()["schemes"]
    for scheme in schemes:
        assert scheme["purpose"]["status"] in VALID_STATUSES, scheme["id"]
        assert scheme["eligibility"]["status"] in VALID_STATUSES, scheme["id"]
        for benefit in scheme["benefits"]:
            assert benefit["status"] in VALID_STATUSES, scheme["id"]
        for step in scheme["application_process"]:
            assert step["step"]
            assert step["status"] in VALID_STATUSES, scheme["id"]


def test_required_schemes_are_documented_in_depth(app_client):
    for scheme_id in sorted(REQUIRED_SCHEMES):
        r = app_client.get(f"/api/schemes/{scheme_id}")
        assert r.status_code == 200, r.text
        scheme = r.json()
        assert scheme["purpose"]["text"]
        assert scheme["eligibility"]["text"]
        assert scheme["benefits"]
        assert scheme["application_process"]


def test_category_filter_is_case_insensitive(app_client):
    all_schemes = app_client.get("/api/schemes").json()
    category = all_schemes["categories"][0]

    filtered = app_client.get("/api/schemes", params={"category": category.upper()}).json()
    assert filtered["total"] >= 1
    assert all(s["category"] == category for s in filtered["schemes"])
    assert filtered["total"] <= all_schemes["total"]


def test_unknown_scheme_is_404(app_client):
    r = app_client.get("/api/schemes/does-not-exist")
    assert r.status_code == 404
    assert "does-not-exist" in r.json()["detail"]
