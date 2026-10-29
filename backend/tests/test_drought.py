"""Tests for POST /api/drought/assess and GET /api/drought/history.

Strategy:
* All weather fetches are mocked (no outbound HTTP).
* All RAG calls are mocked (no embedding model required).
* Tests cover:
    - Valid assessment with full inputs
    - Valid assessment with minimal inputs (partial data)
    - Missing required fields (422)
    - Invalid field values (422)
    - Multiple severity levels
    - Weather fetch failure gracefully handled
    - RAG unavailable gracefully handled
    - Save to account and retrieve from history
    - History ownership (user A cannot see user B's records)
    - Drought service unit tests (severity, categories)
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ────────────────────────────────────────────────────────────────

VALID_PAYLOAD = {
    "location": "Solapur, Maharashtra",
    "crop": "Soybean",
    "growth_stage": "Flowering",
    "soil_type": "Black (Vertisol)",
    "area_value": 2.5,
    "area_unit": "acres",
    "sowing_status": "already_sown",
    "recent_rainfall_mm": 18.0,
    "water_availability": "limited",
    "irrigation_type": "borewell",
    "irrigation_hours_available": 3.0,
    "budget_inr": 8000,
    "fetch_weather": False,   # avoid outbound HTTP in unit tests
    "save": False,
}

MINIMAL_PAYLOAD = {
    "location": "Pune",
    "crop": "Cotton",
    "growth_stage": "Vegetative",
    "soil_type": "Red (Alfisol)",
    "area_value": 1.0,
    "fetch_weather": False,
}


def _auth(app_client, fake_client, uid="u1"):
    fake_client.seed_profile(uid=uid)
    return fake_client.auth_header(uid)


# ── Happy path ───────────────────────────────────────────────────────────────

def test_assess_returns_full_response(app_client, fake_client):
    headers = _auth(app_client, fake_client)
    resp = app_client.post("/api/drought/assess", json=VALID_PAYLOAD, headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Required top-level fields
    assert data["crop"] == "Soybean"
    assert data["growth_stage"] == "Flowering"
    assert data["drought_severity"] in ("none", "mild", "moderate", "severe", "extreme")
    assert isinstance(data["drought_severity_reason"], str)
    assert isinstance(data["categories"], list)
    assert len(data["categories"]) == 6   # one per DROUGHT_CATEGORIES
    assert isinstance(data["disclaimers"], list)
    assert len(data["disclaimers"]) > 0


def test_assess_minimal_inputs_succeeds(app_client, fake_client):
    """Assessment proceeds even when most optional fields are absent."""
    headers = _auth(app_client, fake_client)
    resp = app_client.post("/api/drought/assess", json=MINIMAL_PAYLOAD, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["crop"] == "Cotton"
    # Data gaps should note missing optional fields
    assert isinstance(data["data_gaps"], list)
    assert len(data["data_gaps"]) > 0


def test_severe_drought_when_no_water_low_rain(app_client, fake_client):
    headers = _auth(app_client, fake_client)
    payload = {**VALID_PAYLOAD, "water_availability": "none", "recent_rainfall_mm": 5.0}
    resp = app_client.post("/api/drought/assess", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["drought_severity"] in ("severe", "extreme")


def test_no_drought_with_good_water(app_client, fake_client):
    headers = _auth(app_client, fake_client)
    payload = {**VALID_PAYLOAD, "water_availability": "good", "recent_rainfall_mm": 200.0}
    resp = app_client.post("/api/drought/assess", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["drought_severity"] == "none"


def test_categories_have_required_fields(app_client, fake_client):
    headers = _auth(app_client, fake_client)
    resp = app_client.post("/api/drought/assess", json=VALID_PAYLOAD, headers=headers)
    assert resp.status_code == 200
    for cat in resp.json()["categories"]:
        assert "category" in cat
        assert "category_label" in cat
        assert "urgency" in cat
        assert cat["urgency"] in ("critical", "high", "moderate", "low")
        assert isinstance(cat["items"], list)
        for item in cat["items"]:
            assert "action" in item
            assert "reason" in item
            assert "urgency" in item
            assert item["urgency"] in ("critical", "high", "moderate", "low")


def test_recommendations_have_no_fabricated_exact_prices(app_client, fake_client):
    """Cost estimates must be text strings (never raw floats or exact prices)."""
    headers = _auth(app_client, fake_client)
    resp = app_client.post("/api/drought/assess", json=VALID_PAYLOAD, headers=headers)
    assert resp.status_code == 200
    for cat in resp.json()["categories"]:
        for item in cat["items"]:
            cost = item.get("estimated_cost_inr")
            if cost is not None:
                # Must be a string (range or description), never a raw number
                assert isinstance(cost, str), f"Cost must be str, got {type(cost)}: {cost}"


def test_sowing_decision_category_present(app_client, fake_client):
    headers = _auth(app_client, fake_client)
    resp = app_client.post("/api/drought/assess", json=VALID_PAYLOAD, headers=headers)
    cats = {c["category"] for c in resp.json()["categories"]}
    assert "sowing_decision" in cats
    assert "water_conservation" in cats
    assert "irrigation_management" in cats
    assert "financial_planning" in cats


def test_not_yet_sown_triggers_sowing_delay_recommendation(app_client, fake_client):
    """Under severe drought + not-yet-sown, a sowing-delay recommendation must appear."""
    headers = _auth(app_client, fake_client)
    payload = {
        **VALID_PAYLOAD,
        "sowing_status": "not_yet_sown",
        "water_availability": "none",
        "recent_rainfall_mm": 3.0,
    }
    resp = app_client.post("/api/drought/assess", json=payload, headers=headers)
    assert resp.status_code == 200
    sowing_cat = next(c for c in resp.json()["categories"] if c["category"] == "sowing_decision")
    assert any("delay" in item["action"].lower() or "delay" in item["reason"].lower()
               for item in sowing_cat["items"])


def test_forecast_note_always_present(app_client, fake_client):
    """The forecast note warning about unconfirmed rain must always be present."""
    headers = _auth(app_client, fake_client)
    resp = app_client.post("/api/drought/assess", json=VALID_PAYLOAD, headers=headers)
    assert resp.status_code == 200
    weather = resp.json()["weather"]
    assert "forecast_note" in weather
    assert len(weather["forecast_note"]) > 20


# ── Input validation ─────────────────────────────────────────────────────────

def test_missing_required_fields_returns_422(app_client, fake_client):
    headers = _auth(app_client, fake_client)
    resp = app_client.post("/api/drought/assess", json={}, headers=headers)
    assert resp.status_code == 422


def test_negative_area_returns_422(app_client, fake_client):
    headers = _auth(app_client, fake_client)
    payload = {**VALID_PAYLOAD, "area_value": -1.0}
    resp = app_client.post("/api/drought/assess", json=payload, headers=headers)
    assert resp.status_code == 422


def test_rainfall_above_max_returns_422(app_client, fake_client):
    headers = _auth(app_client, fake_client)
    payload = {**VALID_PAYLOAD, "recent_rainfall_mm": 99999.0}
    resp = app_client.post("/api/drought/assess", json=payload, headers=headers)
    assert resp.status_code == 422


def test_unauthenticated_assess_returns_401(app_client, fake_client):
    resp = app_client.post("/api/drought/assess", json=VALID_PAYLOAD)
    assert resp.status_code == 401


# ── Weather failure handling ─────────────────────────────────────────────────

def test_weather_fetch_failure_does_not_block_assessment(app_client, fake_client):
    """A weather fetch failure returns a graceful data gap, not a 500."""
    headers = _auth(app_client, fake_client)
    payload = {**VALID_PAYLOAD, "fetch_weather": True}

    from app.weather import WeatherUnavailableError
    with patch("app.drought_service.weather_module.geocode",
               side_effect=WeatherUnavailableError("test outage")):
        resp = app_client.post("/api/drought/assess", json=payload, headers=headers)

    assert resp.status_code == 200
    weather = resp.json()["weather"]
    assert weather["fetched"] is False
    assert weather["fetch_error"] is not None


# ── RAG unavailable handling ─────────────────────────────────────────────────

def test_rag_unavailable_does_not_block_assessment(app_client, fake_client):
    headers = _auth(app_client, fake_client)
    from app.rag_service import RagUnavailableError
    # rag_service is imported inside _fetch_rag_context; patch at the source module
    with patch("app.rag_service.answer_question",
               side_effect=RagUnavailableError("no index")):
        resp = app_client.post("/api/drought/assess", json=VALID_PAYLOAD, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["rag_status"] in ("unavailable", "error", "not_attempted")


# ── Save and history ─────────────────────────────────────────────────────────

def test_save_persists_to_history(app_client, fake_client):
    headers = _auth(app_client, fake_client)
    payload = {**VALID_PAYLOAD, "save": True}
    resp = app_client.post("/api/drought/assess", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("saved_assessment_id") is not None

    # It should appear in history
    hist_resp = app_client.get("/api/drought/history", headers=headers)
    assert hist_resp.status_code == 200
    hist = hist_resp.json()
    assert hist["total"] >= 1
    ids = [item["id"] for item in hist["items"]]
    assert data["saved_assessment_id"] in ids


def test_history_is_owner_scoped(app_client, fake_client):
    """User B should not see User A's assessments."""
    headers_a = _auth(app_client, fake_client, uid="ua")
    fake_client.seed_profile(uid="ub", email="b@example.com", mobile="+910000000001")
    headers_b = fake_client.auth_header("ub")

    # User A saves an assessment
    app_client.post("/api/drought/assess", json={**VALID_PAYLOAD, "save": True}, headers=headers_a)

    # User B's history should be empty (separate owner)
    resp_b = app_client.get("/api/drought/history", headers=headers_b)
    assert resp_b.status_code == 200
    assert resp_b.json()["total"] == 0


def test_history_requires_auth(app_client):
    resp = app_client.get("/api/drought/history")
    assert resp.status_code == 401


def test_detail_requires_auth(app_client):
    resp = app_client.get("/api/drought/history/some-id")
    assert resp.status_code == 401


def test_detail_not_found_for_wrong_owner(app_client, fake_client):
    headers_a = _auth(app_client, fake_client, uid="u-detail-owner")
    fake_client.seed_profile(uid="u-detail-other", email="other@example.com", mobile="+910000000099")
    headers_other = fake_client.auth_header("u-detail-other")

    # A saves an assessment, other tries to fetch it
    save_resp = app_client.post(
        "/api/drought/assess", json={**VALID_PAYLOAD, "save": True}, headers=headers_a
    )
    saved_id = save_resp.json().get("saved_assessment_id")
    assert saved_id

    resp = app_client.get(f"/api/drought/history/{saved_id}", headers=headers_other)
    assert resp.status_code == 404


# ── Drought service unit tests ───────────────────────────────────────────────

def test_severity_extreme_no_water_no_rain():
    from app.drought_service import _assess_severity
    sev, reason = _assess_severity({
        "water_availability": "none",
        "recent_rainfall_mm": 5.0,
    })
    assert sev == "extreme"
    assert len(reason) > 10


def test_severity_none_good_water_high_rain():
    from app.drought_service import _assess_severity
    sev, reason = _assess_severity({
        "water_availability": "good",
        "recent_rainfall_mm": 250.0,
    })
    assert sev == "none"


def test_severity_severe_no_irrigation():
    from app.drought_service import _assess_severity
    sev, _ = _assess_severity({
        "water_availability": "none",
        "recent_rainfall_mm": 100.0,
    })
    assert sev == "severe"


def test_build_categories_returns_all_six():
    from app.drought_service import build_categories
    cats = build_categories(
        {
            "crop": "Maize",
            "growth_stage": "Grain Filling",
            "location": "Nagpur",
            "soil_type": "Black",
            "area_value": 3.0,
            "area_unit": "acres",
            "sowing_status": "already_sown",
            "recent_rainfall_mm": 20.0,
            "water_availability": "limited",
            "irrigation_type": "borewell",
            "irrigation_hours_available": None,
            "budget_inr": None,
        },
        severity="moderate",
    )
    assert len(cats) == 6
    cat_keys = {c["category"] for c in cats}
    from app.schemas import DROUGHT_CATEGORIES
    assert cat_keys == set(DROUGHT_CATEGORIES)


def test_financial_category_includes_pmfby():
    from app.drought_service import _financial_planning_recommendations
    recs = _financial_planning_recommendations(
        {"budget_inr": None, "crop": "soybean"}, severity="severe"
    )
    texts = " ".join(r["action"] + r["reason"] for r in recs)
    assert "PMFBY" in texts or "Fasal Bima" in texts


def test_irrigation_critical_stage_flagged_correctly():
    """Critical stage flag must trigger high-urgency irrigation recommendation."""
    from app.drought_service import _irrigation_management_recommendations
    recs = _irrigation_management_recommendations(
        {
            "growth_stage": "flowering",
            "irrigation_type": "borewell",
            "irrigation_hours_available": None,
            "crop": "cotton",
        },
        severity="severe",
    )
    urgencies = {r["urgency"] for r in recs}
    assert "critical" in urgencies or "high" in urgencies


def test_water_conservation_includes_mulching():
    from app.drought_service import _water_conservation_recommendations
    recs = _water_conservation_recommendations(
        {"soil_type": "loam", "crop": "soybean"}, severity="moderate"
    )
    texts = " ".join(r["action"] for r in recs).lower()
    assert "mulch" in texts


def test_no_fabricated_costs_in_service():
    """Service-level check: cost fields must be strings, not numbers."""
    from app.drought_service import build_categories
    cats = build_categories(
        {"crop": "Jowar", "growth_stage": "tillering", "location": "Aurangabad",
         "soil_type": "black", "area_value": 1.0, "area_unit": "acres",
         "sowing_status": "already_sown", "recent_rainfall_mm": 10.0,
         "water_availability": "limited", "irrigation_type": "none",
         "irrigation_hours_available": None, "budget_inr": 3000},
        severity="moderate"
    )
    for cat in cats:
        for item in cat["items"]:
            cost = item.get("estimated_cost_inr")
            if cost is not None:
                assert isinstance(cost, str), f"Cost must be string: {cost}"


def test_assess_drought_returns_disclaimers():
    from app.drought_service import assess_drought
    result = assess_drought({**VALID_PAYLOAD})
    assert len(result["disclaimers"]) >= 4
    assert any("FarmIQ cannot guarantee" in d for d in result["disclaimers"])


def test_different_crops_all_succeed(app_client, fake_client):
    """Basic smoke test across several crop types."""
    headers = _auth(app_client, fake_client, uid="u-crops")
    crops = ["Rice", "Wheat", "Sugarcane", "Cotton", "Tur (Arhar)", "Onion"]
    for crop in crops:
        payload = {**VALID_PAYLOAD, "crop": crop}
        resp = app_client.post("/api/drought/assess", json=payload, headers=headers)
        assert resp.status_code == 200, f"Failed for crop {crop}: {resp.text}"


def test_different_soil_types_all_succeed(app_client, fake_client):
    headers = _auth(app_client, fake_client, uid="u-soils")
    soils = ["Black (Vertisol)", "Red (Alfisol)", "Sandy Loam", "Alluvial", "Laterite"]
    for soil in soils:
        payload = {**VALID_PAYLOAD, "soil_type": soil}
        resp = app_client.post("/api/drought/assess", json=payload, headers=headers)
        assert resp.status_code == 200, f"Failed for soil {soil}: {resp.text}"
