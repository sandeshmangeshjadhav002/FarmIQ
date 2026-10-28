"""Organic vs. modern farming advisor tests (feature: farming methods).

The comparison and transition plan are deterministic: they are built by rules
from the curated reference content (``app/data/farming_methods.json``) plus the
farmer's inputs. No LLM, no RAG, and — critically — no invented cost, yield,
labour or water figures. These tests assert that contract, that unsupported
inputs are rejected with structure, and that saved plans stay owner-scoped.
"""
import json
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "app" / "data" / "farming_methods.json"

VALID_CONTEXT = {
    "crop": "Tomato",
    "location": "Nashik, Maharashtra",
    "soil_type": "Loam",
    "area_acres": 2.5,
    "current_fertilizer": "Urea 18 kg/acre",
    "current_pesticide": "Imidacloprid",
    "resources": {"cow_dung": True, "compost": True, "crop_residues": True, "other": []},
    "preference": "integrated",
}


def test_farming_methods_options_are_served(app_client):
    r = app_client.get("/api/farming-methods")
    assert r.status_code == 200, r.text
    body = r.json()

    assert {"conventional", "organic", "integrated"} <= {
        m["id"] for m in body["metadata"]["methods"]
    }
    assert body["crops"] and body["soil_types"]
    assert {p["id"] for p in body["preferences"]} == {"organic", "modern", "integrated"}
    assert body["legend"] and body["cautions"]
    assert body["metadata"]["last_updated"]
    assert body["metadata"]["disclaimer"]
    # Definition notes must distinguish organic from natural and integrated.
    assert "organic_vs_natural" in body["definition_notes"]
    assert "integrated" in body["definition_notes"]
    assert "certification" in body["definition_notes"]


def test_every_method_labels_data_and_never_invents_cost_or_yield(app_client):
    methods = app_client.get("/api/farming-methods").json()["metadata"]["methods"]
    assert methods
    for method in methods:
        assert method["recommended_practices"]["status"] == "guidance"
        assert method["benefits"]["items"]
        assert method["limitations"]["items"]
        # Cost is never a number here: it must be explicitly unavailable.
        cost = method["estimated_cost_per_acre"]
        assert cost["value"] is None
        assert cost["status"] == "unavailable"
        assert cost["note"]
        # Yield impact must be guidance plus a "not a guarantee" style note.
        assert method["yield_impact"]["status"] == "guidance"
        assert method["yield_impact"]["note"]
        assert method["sources"]


def test_organic_alternatives_endpoint_lists_and_filters_by_crop(app_client):
    everything = app_client.get("/api/farming-methods/organic-alternatives").json()
    assert everything["total"] >= 10
    ids = {a["id"] for a in everything["alternatives"]}
    assert {"fym", "compost", "vermicompost", "residue_mulch", "green_manure",
            "crop_rotation", "neem", "rhizobium"} <= ids

    legumes = app_client.get(
        "/api/farming-methods/organic-alternatives", params={"crop": "Chickpea"}
    ).json()
    legume_ids = {a["id"] for a in legumes["alternatives"]}
    assert "rhizobium" in legume_ids  # legume-specific biofertiliser applies

    cereals = app_client.get(
        "/api/farming-methods/organic-alternatives", params={"crop": "Wheat"}
    ).json()
    cereal_ids = {a["id"] for a in cereals["alternatives"]}
    assert "rhizobium" not in cereal_ids  # not applicable to a cereal
    assert "residue_mulch" in cereal_ids  # "*" alternatives always apply


def test_every_alternative_has_guidance_and_precautions(app_client):
    alternatives = app_client.get("/api/farming-methods/organic-alternatives").json()["alternatives"]
    for alt in alternatives:
        assert alt["name"] and alt["category"]
        assert alt["what_it_does"] and alt["how_used"]
        assert alt["limitations"] and alt["precautions"]
        # Nutrient content is never stated as a figure — only unavailable+note.
        assert alt["nutrient_content"]["status"] == "unavailable"
        assert alt["nutrient_content"]["note"]
        assert alt["last_updated"]


def test_compare_requires_authentication(app_client):
    r = app_client.post("/api/farming-methods/compare", json=VALID_CONTEXT)
    assert r.status_code == 401


def test_compare_returns_three_methods_alternatives_and_cautions(app_client, fake_client):
    fake_client.seed_profile()
    r = app_client.post(
        "/api/farming-methods/compare", json=VALID_CONTEXT, headers=fake_client.auth_header()
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert [m["id"] for m in body["methods"]] == ["conventional", "organic", "integrated"]
    assert all(m["fit_note"] for m in body["methods"])
    assert body["organic_alternatives"]
    assert body["preference"] == "integrated"
    assert body["recommendation"]["nutrient_note"].lower().startswith("do not replace")
    assert body["warnings"]
    assert body["cautions"]
    assert body["sources"]["content_source"] == "reference_file"
    assert body["sources"]["last_updated"]


def test_compare_rejects_unsupported_crop_with_structure(app_client, fake_client):
    fake_client.seed_profile()
    bad = {**VALID_CONTEXT, "crop": "Dragonfruit"}
    r = app_client.post(
        "/api/farming-methods/compare", json=bad, headers=fake_client.auth_header()
    )
    assert r.status_code == 422, r.text
    body = r.json()
    fields = {e["field"] for e in body["errors"]}
    assert "crop" in fields
    supported = next(e for e in body["errors"] if e["field"] == "crop")["supported"]
    assert "Tomato" in supported


def test_compare_rejects_unsupported_preference(app_client, fake_client):
    fake_client.seed_profile()
    bad = {**VALID_CONTEXT, "preference": "biodynamic"}
    r = app_client.post(
        "/api/farming-methods/compare", json=bad, headers=fake_client.auth_header()
    )
    assert r.status_code == 422
    fields = {e["field"] for e in r.json()["errors"]}
    assert "preference" in fields


def test_compare_rejects_non_positive_area(app_client, fake_client):
    fake_client.seed_profile()
    bad = {**VALID_CONTEXT, "area_acres": 0}
    r = app_client.post(
        "/api/farming-methods/compare", json=bad, headers=fake_client.auth_header()
    )
    assert r.status_code == 422
    # Rejected by the schema layer, which reports the field in its `loc`.
    located = {e["loc"][-1] for e in r.json()["errors"] if "loc" in e}
    assert "area_acres" in located


def test_compare_enforces_farm_ownership(app_client, fake_client):
    fake_client.seed_profile()
    # A farm belonging to a different user must not be usable.
    fake_client.tables.setdefault("farms", []).append(
        {"id": "farm-other", "owner_id": "u2", "name": "Other Farm"}
    )
    r = app_client.post(
        "/api/farming-methods/compare",
        json={**VALID_CONTEXT, "farm_id": "farm-other"},
        headers=fake_client.auth_header("u1"),
    )
    assert r.status_code == 404


def test_compare_accepts_an_owned_farm(app_client, fake_client):
    fake_client.seed_profile()
    fake_client.tables.setdefault("farms", []).append(
        {"id": "farm-mine", "owner_id": "u1", "name": "My Farm"}
    )
    r = app_client.post(
        "/api/farming-methods/compare",
        json={**VALID_CONTEXT, "farm_id": "farm-mine"},
        headers=fake_client.auth_header(),
    )
    assert r.status_code == 200, r.text


def test_transition_plan_is_gradual_and_states_uncertainty(app_client, fake_client):
    fake_client.seed_profile()
    body = {**VALID_CONTEXT, "preference": "organic"}
    r = app_client.post(
        "/api/farming-methods/transition-plan", json=body, headers=fake_client.auth_header()
    )
    assert r.status_code == 200, r.text
    plan = r.json()

    phase_ids = [p["id"] for p in plan["phases"]]
    assert phase_ids[0] == "assessment" and "soil_test" in phase_ids and "decision" in phase_ids
    # The assessment must reflect the farmer's reported current practice.
    assert any("Urea 18 kg/acre" in s["text"] for s in plan["phases"][0]["steps"])
    # Costs are never invented.
    assert plan["costs_and_resources"]["status"] == "unavailable"
    assert plan["costs_and_resources"]["estimated_cost_per_acre"] is None
    assert plan["costs_and_resources"]["reported_on_farm_materials"]
    assert plan["decision_indicators"]
    assert "guarantee" in plan["uncertainty_note"].lower() or "may change" in plan["uncertainty_note"].lower()
    assert plan["professional_advice_note"]
    assert plan["cautions"]


def test_saved_plans_are_owner_scoped(app_client, fake_client):
    fake_client.seed_profile(uid="u1", mobile="+919111111111", email="u1@example.com")
    fake_client.seed_profile(uid="u2", mobile="+919222222222", email="u2@example.com")

    saved = app_client.post(
        "/api/farming-methods/compare",
        json={**VALID_CONTEXT, "save": True},
        headers=fake_client.auth_header("u1"),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["saved_plan"]["id"]

    mine = app_client.get("/api/farming-methods/plans", headers=fake_client.auth_header("u1"))
    assert mine.status_code == 200
    assert mine.json()["total"] == 1
    assert mine.json()["plans"][0]["crop"] == "Tomato"

    theirs = app_client.get("/api/farming-methods/plans", headers=fake_client.auth_header("u2"))
    assert theirs.status_code == 200
    assert theirs.json()["total"] == 0


def test_plans_list_requires_authentication(app_client):
    assert app_client.get("/api/farming-methods/plans").status_code == 401


def test_content_can_be_served_from_the_database(app_client, fake_client):
    """When the reference tables are seeded, the API reads them instead of the file."""
    content = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    fake_client.tables["farming_methods"] = [
        {"id": m["id"], "sort_order": i + 1, "payload": m, "last_updated": "2026-01-01"}
        for i, m in enumerate(content["methods"])
    ]
    body = app_client.get("/api/farming-methods").json()
    assert body["metadata"]["methods"]
    assert all(m["last_updated"] == "2026-01-01" for m in body["metadata"]["methods"])

    fake_client.seed_profile()
    compared = app_client.post(
        "/api/farming-methods/compare", json=VALID_CONTEXT, headers=fake_client.auth_header()
    ).json()
    assert compared["sources"]["content_source"] == "database"
