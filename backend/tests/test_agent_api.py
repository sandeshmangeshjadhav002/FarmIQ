"""Tests for the agent HTTP surface (app.routers.agent).

The service layer is exercised in test_agent_service.py; these tests cover the
HTTP contract: authentication, validation, the response body shape, and that
one farmer's request never returns another farmer's data.

Both the weather provider and the RAG assistant are stubbed, so no network or
LLM is involved.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import agent_service, farm_context_manager as ctx

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
UID = "u1"
OTHER = "u2"
FARM_ID = "f1"


def _iso(hours_ago: float = 0.0) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


FARM_ROW = {
    "id": FARM_ID,
    "owner_id": UID,
    "name": "Green Valley Farm",
    "location": "Nashik, Maharashtra",
    "area_value": 2.5,
    "area_unit": "acres",
    "soil_type": "Black (Vertisol)",
    "current_crop": "Wheat",
    "irrigation_type": "drip",
    "latitude": 19.9975,
    "longitude": 73.7898,
    "created_at": _iso(24 * 30),
}


def _weather_ok(*_, **__):
    return {
        "source": "Open-Meteo",
        "fetched_at": NOW.isoformat(),
        "location": {"name": "Nashik, Maharashtra"},
        "current": {
            "observed_at": NOW.isoformat(),
            "temperature_c": 41.0,
            "humidity_pct": 48.0,
            "precipitation_mm": 0.0,
        },
        "forecast_rainfall": {"total_mm": 1.0, "daily": []},
        "historical_rainfall": {"total_mm": 142.5},
    }


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    from app import weather as weather_module

    ctx.reset_caches()
    agent_service.reset_cache()
    monkeypatch.setattr(weather_module, "build_report", _weather_ok)
    monkeypatch.setattr(
        "app.rag_service.answer_question",
        lambda *_, **__: {"answer": "", "llm_used": False, "sources": []},
    )
    # The LLM tool planner is stubbed to None so the suite stays hermetic and
    # exercises the deterministic fallback unless a test overrides it.
    monkeypatch.setattr("app.rag_service.llm_generate", lambda *_, **__: None)
    yield
    ctx.reset_caches()
    agent_service.reset_cache()


def _seed(fake_client, *, reading=None, predictions=None):
    fake_client.seed_profile(uid=UID)
    fake_client.tables.setdefault("farms", []).append(dict(FARM_ROW))
    if reading is not None:
        fake_client.tables.setdefault("sensor_readings", []).append(
            {"owner_id": UID, "farm_id": FARM_ID, "device_id": "d1", **reading}
        )
    for row in predictions or []:
        fake_client.tables.setdefault("predictions", []).append(
            {"owner_id": UID, "source": "model", **row}
        )


def _reading(**overrides):
    return {
        "created_at": _iso(0.2),
        "soil_moisture": 20.0,
        "temperature": 41.0,
        "humidity": 48.0,
        "ph": 6.8,
        "nitrogen": 42.0,
        "phosphorous": 18.0,
        "potassium": 55.0,
        "soil_temperature": 27.5,
        **overrides,
    }


# ── Authentication ───────────────────────────────────────────────────────────

def test_chat_requires_auth(app_client):
    resp = app_client.post("/api/agent/chat", json={"message": "hello"})
    assert resp.status_code == 401


def test_context_requires_auth(app_client):
    resp = app_client.get("/api/agent/context")
    assert resp.status_code == 401


def test_an_invalid_token_is_rejected(app_client):
    resp = app_client.post(
        "/api/agent/chat",
        json={"message": "hello"},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401


# ── Validation ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "payload",
    [
        {"message": ""},
        {"message": "hi", "language": "fr"},
        {"message": "hi", "language": "mr-IN"},
        {"language": "en"},
    ],
)
def test_invalid_payloads_are_rejected(app_client, fake_client, payload):
    fake_client.seed_profile(uid=UID)
    resp = app_client.post(
        "/api/agent/chat", json=payload, headers=fake_client.auth_header(UID)
    )
    assert resp.status_code == 422


# ── Chat ─────────────────────────────────────────────────────────────────────

def test_chat_returns_a_structured_answer_with_evidence(app_client, fake_client):
    _seed(fake_client, reading=_reading())

    resp = app_client.post(
        "/api/agent/chat",
        json={"message": "What is the soil moisture level?"},
        headers=fake_client.auth_header(UID),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "sensors"
    assert body["tools_used"] == ["get_sensor_readings"]
    assert body["language"] == "en"
    assert body["llm_used"] is False
    assert "20" in body["answer"]
    # Structured sections and the evidence behind them.
    assert body["sections"]["observation"]
    assert body["context"]["sensors"]["soil_moisture"] == 20.0
    assert body["freshness"]["get_sensor_readings"] == _iso(0.2)
    # A sensor question never fetches the farm profile (tool narrowing).
    assert body["context"]["farm"] is None


def test_the_llm_planner_drives_tool_selection(app_client, fake_client, monkeypatch):
    """The endpoint honours the planner's choice, not a keyword rule."""
    _seed(fake_client, reading=_reading())
    monkeypatch.setattr(
        "app.rag_service.llm_generate",
        lambda *_, **__: '{"intent": "weather", "tools": ["get_weather_information"], '
                         '"needs_retrieval": false}',
    )

    resp = app_client.post(
        "/api/agent/chat",
        json={"message": "how is the sky looking today"},
        headers=fake_client.auth_header(UID),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "weather"
    assert body["tools_used"] == ["get_weather_information"]
    # Only the planner-selected tool was read.
    assert body["context"]["sensors"] is None


def test_chat_surfaces_a_conflict_as_a_warning(app_client, fake_client):
    _seed(
        fake_client,
        reading=_reading(soil_moisture=20.0),
        predictions=[
            {"id": "p1", "domain": "irrigation", "output": {"prediction": 0},
             "created_at": _iso(1.0)}
        ],
    )

    resp = app_client.post(
        "/api/agent/chat",
        json={"message": "Should I irrigate my wheat?"},
        headers=fake_client.auth_header(UID),
    )

    body = resp.json()
    assert any(c["kind"] == "ml_vs_sensor" for c in body["conflicts"])
    assert body["sections"]["warning"]


def test_chat_reports_missing_data_instead_of_inventing_it(app_client, fake_client):
    fake_client.seed_profile(uid=UID)  # no farm, no sensors

    resp = app_client.post(
        "/api/agent/chat",
        json={"message": "Should I irrigate my wheat?"},
        headers=fake_client.auth_header(UID),
    )

    body = resp.json()
    assert "sensor_readings" in body["missing"]
    assert body["context"]["sensors"] is None


def test_marathi_request_returns_marathi_text(app_client, fake_client):
    _seed(fake_client, reading=_reading())

    resp = app_client.post(
        "/api/agent/chat",
        json={"message": "माती ओलावा किती आहे?", "language": "mr"},
        headers=fake_client.auth_header(UID),
    )

    body = resp.json()
    assert body["language"] == "mr"
    assert "निरीक्षण" in body["answer"]


def test_repeating_a_question_is_served_from_cache(app_client, fake_client):
    _seed(fake_client, reading=_reading())
    headers = fake_client.auth_header(UID)
    payload = {"message": "What is the soil moisture level?"}

    first = app_client.post("/api/agent/chat", json=payload, headers=headers).json()
    second = app_client.post("/api/agent/chat", json=payload, headers=headers).json()

    assert first["cached"] is False
    assert second["cached"] is True


def test_a_specific_farm_can_be_requested(app_client, fake_client):
    _seed(fake_client, reading=_reading())
    fake_client.tables["farms"].append(
        {**FARM_ROW, "id": "f2", "name": "Second Farm", "location": "Pune, Maharashtra"}
    )

    resp = app_client.post(
        "/api/agent/chat",
        json={"message": "What is my land area?", "farm_id": "f2"},
        headers=fake_client.auth_header(UID),
    )

    body = resp.json()
    assert body["context"]["farm"]["location"] == "Pune, Maharashtra"
    # Coordinates and ownership are never returned.
    assert "latitude" not in body["context"]["farm"]
    assert "longitude" not in body["context"]["farm"]
    assert "owner_id" not in body["context"]["farm"]


# ── Isolation ────────────────────────────────────────────────────────────────

def test_another_farmer_cannot_read_this_farm(app_client, fake_client):
    _seed(fake_client, reading=_reading())
    fake_client.seed_profile(uid=OTHER, email="other@example.com", mobile="+919000000002")

    resp = app_client.post(
        "/api/agent/chat",
        json={"message": "What is the soil moisture level?"},
        headers=fake_client.auth_header(OTHER),
    )

    body = resp.json()
    assert body["context"]["sensors"] is None
    assert body["context"]["farm"] is None
    assert "20" not in body["answer"]
    assert "Wheat" not in body["answer"]


def test_another_farmer_cannot_select_a_foreign_farm(app_client, fake_client):
    _seed(fake_client, reading=_reading())
    fake_client.seed_profile(uid=OTHER, email="other@example.com", mobile="+919000000002")

    resp = app_client.post(
        "/api/agent/chat",
        json={"message": "What is the soil moisture level?", "farm_id": FARM_ID},
        headers=fake_client.auth_header(OTHER),
    )

    body = resp.json()
    assert body["context"]["sensors"] is None
    assert body["context"]["farm"] is None


# ── Context endpoint ─────────────────────────────────────────────────────────

def test_context_returns_the_full_structured_snapshot(app_client, fake_client):
    _seed(
        fake_client,
        reading=_reading(),
        predictions=[
            {"id": "p1", "domain": "crop", "output": {"prediction": "Wheat"},
             "created_at": _iso(1.0)}
        ],
    )

    resp = app_client.get("/api/agent/context", headers=fake_client.auth_header(UID))

    assert resp.status_code == 200
    body = resp.json()
    assert body["owner_id"] == UID
    assert body["farm"]["current_crop"] == "Wheat"
    assert body["sensors"]["soil_moisture"] == 20.0
    assert body["weather"]["temperature_c"] == 41.0
    assert body["ml"]["latest"]["crop"]["prediction"] == "Wheat"
    assert body["generated_at"]


def test_context_can_skip_the_weather_lookup(app_client, fake_client):
    _seed(fake_client, reading=_reading())

    resp = app_client.get(
        "/api/agent/context",
        params={"include_weather": "false"},
        headers=fake_client.auth_header(UID),
    )

    body = resp.json()
    assert body["weather"] is None
    assert "weather" in body["missing"]


def test_context_for_an_empty_account_is_honest(app_client, fake_client):
    fake_client.seed_profile(uid=OTHER, email="empty@example.com", mobile="+919000000002")

    resp = app_client.get("/api/agent/context", headers=fake_client.auth_header(OTHER))

    body = resp.json()
    assert body["farm"] is None
    assert body["sensors"] is None
    assert "farm_profile" in body["missing"]
    assert "sensor_readings" in body["missing"]


def test_context_never_leaks_another_farmers_rows(app_client, fake_client):
    _seed(fake_client, reading=_reading())
    fake_client.seed_profile(uid=OTHER, email="other@example.com", mobile="+919000000002")

    resp = app_client.get(
        "/api/agent/context",
        params={"farm_id": FARM_ID},
        headers=fake_client.auth_header(OTHER),
    )

    body = resp.json()
    assert body["farm"] is None
    assert body["sensors"] is None
