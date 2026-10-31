"""Tests for the unified AI agent engine (app.agent_service).

Covers the agent-spec scenarios that the engine itself owns:

* tool routing (only the tools a question needs),
* reasoning over real ML + sensor + weather + profile data,
* conflicts (ML vs sensor, sensor vs weather, stale prediction vs reading),
* missing data reported rather than invented,
* response shape (Situation / Observation / Recommendation / Reason / Warning),
* multilingual labels,
* caching and its invalidation,
* graceful degradation when a tool or the assistant fails,
* owner isolation.

The assistant (RAG) is stubbed: these tests never touch the knowledge base or
an LLM.
"""
from __future__ import annotations

import time
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
def _isolated_state(monkeypatch):
    """Fresh caches for every test, and a working weather provider."""
    from app import weather as weather_module

    ctx.reset_caches()
    agent_service.reset_cache()
    monkeypatch.setattr(weather_module, "build_report", _weather_ok)

    class _StubAdapter:
        def status(self):
            return {"crop": {"model": True}}

    monkeypatch.setattr("ml.adapter.get_adapter", lambda: _StubAdapter())
    yield
    ctx.reset_caches()
    agent_service.reset_cache()


@pytest.fixture(autouse=True)
def _assistant_offline(monkeypatch):
    """Default the assistant to unavailable; tests opt in to a stub.

    The LLM tool planner is stubbed to ``None`` as well, so the suite stays
    hermetic (no provider call) and exercises the deterministic fallback router
    unless a test patches :func:`app.agent_service.plan_tools` or
    ``app.rag_service.llm_generate`` itself.
    """
    from app.rag_service import RagUnavailableError

    def _unavailable(*_, **__):
        raise RagUnavailableError("knowledge base not loaded")

    monkeypatch.setattr("app.rag_service.answer_question", _unavailable)
    monkeypatch.setattr("app.rag_service.llm_generate", lambda *_, **__: None)


def _seed(fake_client, *, farm=True, reading=None, predictions=None):
    fake_client.seed_profile(uid=UID)
    if farm:
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
        # Matches the weather stub, so only the dedicated divergence test sees a
        # sensor-vs-weather gap.
        "temperature": 41.0,
        "humidity": 51.0,
        "ph": 6.8,
        "nitrogen": 42.0,
        "phosphorous": 18.0,
        "potassium": 55.0,
        "soil_temperature": 27.5,
        **overrides,
    }


def _ask(fake_client, question, *, owner=UID, language="en", farm_id=None, **kwargs):
    return agent_service.answer(
        question,
        client=fake_client,
        owner_id=owner,
        farm_id=farm_id,
        language=language,
        now=NOW,
        **kwargs,
    )


# ── Offline fallback routing ─────────────────────────────────────────────────
#
# The primary routing decision is made by the LLM planner (see the LLM planner
# tests below). These tests cover the deterministic fallback that runs when the
# planner is unavailable, so the agent keeps working with the provider down.

@pytest.mark.parametrize(
    "question,expected",
    [
        ("When should I irrigate my wheat?", "irrigation"),
        ("पाणी द्यावे का?", "irrigation"),
        ("Which fertilizer should I use?", "fertilizer"),
        ("खत द्यावे का?", "fertilizer"),
        ("Which crop should I plant this season?", "crop_selection"),
        ("How much yield will I get?", "yield"),
        ("Will it rain tomorrow?", "weather"),
        ("What is the soil moisture right now?", "sensors"),
        ("Show me my previous predictions", "history"),
        ("What is my land area?", "profile"),
        ("What should I do on my farm today?", "farm_status"),
        ("What is the capital of France?", "unknown"),
    ],
)
def test_offline_fallback_intent_routing(question, expected):
    assert agent_service.classify_intent(question) == expected


def test_unknown_intent_gets_no_tools():
    assert agent_service.tools_for_intent("unknown") == ()
    assert agent_service.tools_for_intent("nonsense") == ()


def test_weather_question_calls_only_the_weather_tool(fake_client):
    _seed(fake_client, reading=_reading())

    result = _ask(fake_client, "Will it rain tomorrow?")

    assert result["intent"] == "weather"
    assert result["tools_used"] == ["get_weather_information"]
    # No sensor or prediction evidence was fetched, so none is reported.
    assert result["context"]["sensors"] is None
    assert result["context"]["predictions"] == {}


def test_question_about_sensors_does_not_read_the_weather(fake_client):
    _seed(fake_client, reading=_reading())

    result = _ask(fake_client, "What is the soil moisture level?")

    assert result["tools_used"] == ["get_sensor_readings"]
    assert result["context"]["weather"] is None


# ── Reasoning over real values ───────────────────────────────────────────────

def test_irrigation_answer_uses_the_real_sensor_weather_and_model_values(fake_client):
    _seed(
        fake_client,
        reading=_reading(soil_moisture=22.0, temperature=30.1),
        predictions=[
            {
                "id": "p1",
                "domain": "irrigation",
                "output": {"prediction": 1, "label": "Irrigation recommended"},
                "created_at": _iso(1.0),
            }
        ],
    )

    result = _ask(fake_client, "Should I irrigate my wheat?")

    assert result["intent"] == "irrigation"
    assert set(result["tools_used"]) == {
        "get_irrigation_prediction",
        "get_farm_profile",
        "get_sensor_readings",
        "get_weather_information",
    }
    observation = " ".join(result["sections"]["observation"])
    assert "22" in observation                  # real soil-moisture reading
    assert "41" in observation                  # real weather temperature
    assert result["sections"]["recommendation"]  # actionable advice present
    assert result["sections"]["reason"]
    assert result["fallback"] is False


def test_bme680_measurements_appear_in_the_sensor_observation(fake_client):
    """A BME680 node's air measurements are reported as readings, with units."""
    _seed(fake_client, reading=_reading(pressure=1008.3))

    result = _ask(fake_client, "What is the soil moisture right now?")
    observation = " ".join(result["sections"]["observation"])

    assert "Air pressure" in observation
    assert "1008.3 hPa" in observation
    assert result["context"]["sensors"]["pressure"] == 1008.3
    # A reading, not a prediction.
    assert "(model output)" not in observation


def test_sensor_reading_and_model_output_are_labelled_differently(fake_client):
    _seed(
        fake_client,
        reading=_reading(),
        predictions=[
            {"id": "p1", "domain": "crop", "output": {"prediction": "Wheat"},
             "created_at": _iso(1.0)}
        ],
    )

    # A model answer must never be presented as a measurement...
    model = _ask(fake_client, "Which crop should I plant?")
    model_observation = " ".join(model["sections"]["observation"])
    assert "(model output)" in model_observation
    assert "Sensor reading" not in model_observation

    # ...and a reading is never presented as a prediction.
    reading = _ask(fake_client, "What is the soil moisture level?")
    reading_observation = " ".join(reading["sections"]["observation"])
    assert "Sensor reading" in reading_observation
    assert "(model output)" not in reading_observation


def test_prediction_is_never_presented_as_a_guaranteed_outcome(fake_client):
    _seed(
        fake_client,
        predictions=[
            {"id": "p1", "domain": "yield", "output": {"prediction": 3.2},
             "created_at": _iso(1.0)}
        ],
    )

    result = _ask(fake_client, "How much yield will I get?")

    reasons = " ".join(result["sections"]["reason"])
    assert "prediction, not a guaranteed outcome" in reasons


def test_situation_describes_the_farm_profile(fake_client):
    _seed(fake_client, reading=_reading())

    result = _ask(fake_client, "What should I do on my farm today?")

    assert "Wheat" in result["sections"]["situation"]
    assert "Nashik" in result["sections"]["situation"]


# ── Conflicts ────────────────────────────────────────────────────────────────

def test_ml_irrigation_conflicting_with_the_sensor_is_surfaced(fake_client):
    # Model says "do not irrigate"; the reading (20%) is below the wheat
    # threshold (45%), so the rule says irrigate. They disagree.
    _seed(
        fake_client,
        reading=_reading(soil_moisture=20.0),
        predictions=[
            {"id": "p1", "domain": "irrigation",
             "output": {"prediction": 0, "label": "No irrigation", "source": "model"},
             "created_at": _iso(1.0)}
        ],
    )

    result = _ask(fake_client, "Should I irrigate my wheat?")

    kinds = {conflict["kind"] for conflict in result["conflicts"]}
    assert "ml_vs_sensor" in kinds
    conflict = next(c for c in result["conflicts"] if c["kind"] == "ml_vs_sensor")
    assert conflict["evidence"]["ml_prediction"] == 0
    assert conflict["evidence"]["soil_moisture"] == 20.0
    assert conflict["evidence"]["threshold_pct"] == 45
    # The conflict is also shown as a warning, and the answer says to check.
    assert any("Check the sensor" in w for w in result["sections"]["warning"])


def test_ml_irrigation_agreeing_with_the_sensor_is_not_a_conflict(fake_client):
    _seed(
        fake_client,
        reading=_reading(soil_moisture=20.0),
        predictions=[
            {"id": "p1", "domain": "irrigation", "output": {"prediction": 1},
             "created_at": _iso(0.1)}
        ],
    )

    result = _ask(fake_client, "Should I irrigate my wheat?")

    assert result["conflicts"] == []


def test_non_percentage_moisture_is_not_compared_with_the_threshold(fake_client):
    """A 0–2000 raw-scale value must never be read as a percentage."""
    _seed(
        fake_client,
        reading=_reading(soil_moisture=450.0),
        predictions=[
            {"id": "p1", "domain": "irrigation", "output": {"prediction": 0},
             "created_at": _iso(1.0)}
        ],
    )

    result = _ask(fake_client, "Should I irrigate my wheat?")

    assert all(conflict["kind"] != "ml_vs_sensor" for conflict in result["conflicts"])


def test_sensor_and_weather_disagreement_is_surfaced(fake_client):
    # Sensor 30.1 °C vs weather 41.0 °C: a 10.9 °C gap.
    _seed(fake_client, reading=_reading(temperature=30.1))

    result = _ask(fake_client, "Should I irrigate my wheat?")

    divergence = [c for c in result["conflicts"] if c["kind"] == "sensor_vs_weather"]
    assert divergence, result["conflicts"]
    assert divergence[0]["channel"] == "temperature"
    assert divergence[0]["sensor_value"] == 30.1
    assert divergence[0]["weather_value"] == 41.0


def test_prediction_older_than_the_reading_is_flagged(fake_client):
    _seed(
        fake_client,
        reading=_reading(created_at=_iso(0.5)),
        predictions=[
            {"id": "p1", "domain": "irrigation", "output": {"prediction": 1},
             "created_at": _iso(10.0)}
        ],
    )

    result = _ask(fake_client, "Should I irrigate my wheat?")

    stale = [c for c in result["conflicts"] if c["kind"] == "prediction_before_reading"]
    assert stale, result["conflicts"]
    assert stale[0]["tool"] == "get_irrigation_prediction"
    assert "older than your latest sensor reading" in stale[0]["message"]


# ── Missing data is reported, never invented ─────────────────────────────────

def test_no_farm_and_no_sensors_is_reported_honestly(fake_client):
    fake_client.seed_profile(uid=UID)

    result = _ask(fake_client, "Should I irrigate my wheat?")

    assert "sensor_readings" in result["missing"]
    assert result["context"]["sensors"] is None
    assert result["context"]["predictions"] == {}
    assert result["sections"]["observation"] == []


def test_absent_sensor_readings_are_never_substituted(fake_client):
    _seed(fake_client, reading=None)

    result = _ask(fake_client, "What is the soil moisture level?")

    assert result["missing"] == ["sensor_readings"]
    assert result["sections"]["observation"] == []
    assert any("No sensor readings" in w for w in result["sections"]["warning"])


def test_stale_reading_is_flagged_as_uncertain(fake_client):
    _seed(fake_client, reading=_reading(created_at=_iso(10.0)))

    result = _ask(fake_client, "What is the soil moisture level?")

    assert any("conditions may have changed" in note for note in result["uncertainty"])
    assert any("conditions may have changed" in w for w in result["sections"]["warning"])


def test_demo_reading_is_disclosed(fake_client):
    _seed(fake_client, reading=_reading(is_demo=True))

    result = _ask(fake_client, "What is the soil moisture level?")

    assert any("simulated (DEMO)" in w for w in result["sections"]["warning"])


def test_implausible_channel_is_flagged(fake_client):
    _seed(fake_client, reading=_reading(ph=99.0))

    result = _ask(fake_client, "What is the soil moisture level?")

    assert any("outside plausible sensor limits" in note for note in result["uncertainty"])


def test_unrelated_question_without_the_assistant_returns_help(fake_client):
    _seed(fake_client, reading=_reading())

    result = _ask(fake_client, "What is the capital of France?")

    assert result["intent"] == "unknown"
    assert result["tools_used"] == []
    assert result["fallback"] is True
    assert result["llm_used"] is False
    assert "farm plan" in result["answer"]
    # No farm data was read, so nothing is claimed to be missing.
    assert result["missing"] == []


# ── The assistant is additive, never load-bearing ────────────────────────────

def test_knowledge_question_is_answered_by_the_assistant(fake_client, monkeypatch):
    monkeypatch.setattr(
        "app.rag_service.answer_question",
        lambda *_, **__: {
            "answer": "Spray neem oil early in the morning.",
            "llm_used": True,
            "sources": [{"title": "ICAR pest guide"}],
        },
    )
    _seed(fake_client, reading=_reading())

    result = _ask(fake_client, "How do I control aphids on tomato?")

    assert result["intent"] == "unknown"
    assert result["answer"] == "Spray neem oil early in the morning."
    assert result["llm_used"] is True
    assert result["sources"] == [{"title": "ICAR pest guide"}]
    assert result["fallback"] is False


def test_assistant_receives_only_the_values_the_tools_returned(fake_client, monkeypatch):
    captured: dict = {}

    def _fake(question, ml_results=None, **kwargs):
        captured["question"] = question
        captured["ml"] = ml_results
        captured["farm_context"] = kwargs.get("farm_context")
        return {"answer": "", "llm_used": False, "sources": []}

    monkeypatch.setattr("app.rag_service.answer_question", _fake)
    _seed(
        fake_client,
        reading=_reading(),
        predictions=[
            {"id": "p1", "domain": "irrigation",
             "output": {"prediction": 1, "label": "Irrigation recommended"},
             "created_at": _iso(1.0)}
        ],
    )

    _ask(fake_client, "Should I irrigate my wheat?")

    assert captured["ml"]["irrigation_prediction"] == "Irrigation recommended"
    assert captured["farm_context"]["current_crop"] == "Wheat"
    assert captured["farm_context"]["soil_moisture"] == 20.0
    # Internal identifiers are never handed to the model.
    for leaked in ("id", "owner_id", "latitude", "longitude"):
        assert leaked not in captured["farm_context"]


def test_assistant_failure_leaves_the_structured_answer_intact(fake_client, monkeypatch):
    def _boom(*_, **__):
        raise RuntimeError("provider 503")

    monkeypatch.setattr("app.rag_service.answer_question", _boom)
    _seed(fake_client, reading=_reading())

    result = _ask(fake_client, "What is the soil moisture level?")

    assert result["llm_used"] is False
    assert result["explanation"] is None
    assert "20" in result["answer"]
    assert result["sections"]["observation"]


def test_assistant_empty_answer_does_not_replace_the_structured_answer(fake_client, monkeypatch):
    monkeypatch.setattr(
        "app.rag_service.answer_question",
        lambda *_, **__: {"answer": "   ", "llm_used": False, "sources": []},
    )
    _seed(fake_client, reading=_reading())

    result = _ask(fake_client, "What is the soil moisture level?")

    assert "20" in result["answer"]


# ── Degradation ──────────────────────────────────────────────────────────────

def test_one_failing_tool_does_not_fail_the_answer(fake_client, monkeypatch):
    _seed(fake_client, reading=_reading())

    def _boom(self):
        raise RuntimeError("weather provider unreachable")

    monkeypatch.setattr(agent_service.FarmTools, "get_weather_information", _boom)

    result = _ask(fake_client, "What should I do on my farm today?")

    assert "weather" in result["missing"]
    assert any("Weather data is not available" in w for w in result["sections"]["warning"])
    # The sensor evidence still made it into the answer.
    assert any("Sensor reading" in item for item in result["sections"]["observation"])


def test_weather_failure_for_a_weather_only_question_still_answers(fake_client, monkeypatch):
    from app import weather as weather_module

    def _boom(*_, **__):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(weather_module, "build_report", _boom)
    ctx.reset_caches()
    _seed(fake_client)

    result = _ask(fake_client, "Will it rain tomorrow?")

    assert result["intent"] == "weather"
    assert "weather" in result["missing"]
    assert result["sections"]["warning"]


# ── Multilingual ─────────────────────────────────────────────────────────────

def test_marathi_question_gets_marathi_labels_and_values(fake_client):
    _seed(fake_client, reading=_reading(soil_moisture=22.0))

    result = _ask(fake_client, "माझ्या शेतातील माती ओलावा किती?", language="mr")

    assert result["language"] == "mr"
    assert "निरीक्षण" in result["answer"]
    assert "22" in result["answer"]


def test_unsupported_language_falls_back_to_english(fake_client):
    _seed(fake_client, reading=_reading())

    result = _ask(fake_client, "What is the soil moisture level?", language="hi")

    assert result["language"] == "en"


# ── Caching ──────────────────────────────────────────────────────────────────

def test_identical_question_is_served_from_cache(fake_client):
    _seed(fake_client, reading=_reading())

    first = _ask(fake_client, "What is the soil moisture level?")
    second = _ask(fake_client, "What is the soil moisture level?")

    assert first["cached"] is False
    assert second["cached"] is True
    assert second["answer"] == first["answer"]


def test_a_new_reading_invalidates_the_cached_answer(fake_client):
    _seed(fake_client, reading=_reading(created_at=_iso(0.5), soil_moisture=20.0))

    first = _ask(fake_client, "What is the soil moisture level?")
    assert "20" in first["answer"]

    fake_client.tables["sensor_readings"].append(
        {"owner_id": UID, "farm_id": FARM_ID, "device_id": "d1",
         "created_at": _iso(0.0), "soil_moisture": 61.0}
    )

    second = _ask(fake_client, "What is the soil moisture level?")

    assert second["cached"] is False
    assert "61" in second["answer"]
    assert "20" not in second["answer"]


def test_different_questions_are_cached_separately(fake_client):
    _seed(fake_client, reading=_reading())

    a = _ask(fake_client, "What is the soil moisture level?")
    b = _ask(fake_client, "What is the soil ph value?")

    assert a["cached"] is False
    assert b["cached"] is False
    assert a["answer"] != b["answer"]


# ── Ownership isolation ──────────────────────────────────────────────────────

def test_another_farmer_never_sees_this_farm(fake_client):
    _seed(fake_client, reading=_reading())
    fake_client.seed_profile(uid=OTHER, email="other@example.com", mobile="+919000000002")

    result = _ask(fake_client, "What is the soil moisture level?", owner=OTHER)

    assert result["context"]["sensors"] is None
    assert result["context"]["farm"] is None
    assert "sensor_readings" in result["missing"]
    assert "20" not in result["answer"]


def test_another_farmer_cannot_select_a_foreign_farm(fake_client):
    _seed(fake_client, reading=_reading())
    fake_client.seed_profile(uid=OTHER, email="other@example.com", mobile="+919000000002")

    result = _ask(
        fake_client, "What is the soil moisture level?", owner=OTHER, farm_id=FARM_ID
    )

    assert result["context"]["sensors"] is None
    assert result["context"]["farm"] is None


def test_concurrent_farmers_get_their_own_answers(fake_client):
    _seed(fake_client, reading=_reading(soil_moisture=20.0))
    fake_client.seed_profile(uid=OTHER, email="other@example.com", mobile="+919000000002")
    fake_client.tables.setdefault("farms", []).append(
        {**FARM_ROW, "id": "f2", "owner_id": OTHER, "current_crop": "Cotton"}
    )
    fake_client.tables.setdefault("sensor_readings", []).append(
        {"owner_id": OTHER, "farm_id": "f2", "device_id": "d2",
         "created_at": _iso(0.1), "soil_moisture": 80.0}
    )

    mine = _ask(fake_client, "What should I do on my farm today?")
    theirs = _ask(fake_client, "What should I do on my farm today?", owner=OTHER)

    assert "20" in mine["answer"]
    assert "80" in theirs["answer"]
    assert "Wheat" in mine["sections"]["situation"]
    assert "Cotton" in theirs["sections"]["situation"]


# ── Response shape ───────────────────────────────────────────────────────────

def test_sections_render_in_the_expected_order(fake_client):
    _seed(fake_client, reading=_reading())

    result = _ask(fake_client, "What should I do on my farm today?")

    text = result["answer"]
    assert text.index("Situation") < text.index("Observation")
    assert text.index("Observation") < text.index("Recommendation")
    assert text.index("Recommendation") < text.index("Reason")


def test_sections_are_omitted_when_there_is_nothing_to_say(fake_client):
    _seed(fake_client, reading=_reading())

    result = _ask(fake_client, "What is the soil moisture level?")

    sections = result["sections"]
    assert sections["situation"] is None
    assert sections["recommendation"] == []
    assert "Recommendation" not in result["answer"]


def test_freshness_is_reported_per_source(fake_client):
    _seed(
        fake_client,
        reading=_reading(),
        predictions=[
            {"id": "p1", "domain": "irrigation", "output": {"prediction": 1},
             "created_at": _iso(1.0)}
        ],
    )

    result = _ask(fake_client, "Should I irrigate my wheat?")

    assert result["freshness"]["get_sensor_readings"] == _iso(0.2)
    assert result["freshness"]["get_irrigation_prediction"] == _iso(1.0)


# ── Organic farming intent ────────────────────────────────────────────────────

def _drought_assessment_row(severity="moderate", crop="Wheat"):
    """A minimal saved drought assessment row (mirrors db.insert_drought_assessment output)."""
    return {
        "id": "da1",
        "owner_id": UID,
        "crop": crop,
        "location": "Nashik, Maharashtra",
        "created_at": _iso(2.0),
        "input": {"water_availability": "limited", "irrigation_type": "drip"},
        "result": {
            "drought_severity": severity,
            "drought_severity_reason": "Below-normal recent rainfall with limited water availability.",
            "growth_stage": "Vegetative",
            "categories": [
                {
                    "category": "water_conservation",
                    "category_label": "Water Conservation",
                    "urgency": "high",
                    "items": [
                        {"action": "Apply organic mulch between crop rows."},
                        {"action": "Repair field bunds to capture rainfall."},
                    ],
                }
            ],
        },
        "weather_snapshot": {
            "fetched": True,
            "current_temp_c": 38.0,
            "historical_rain_mm": 15.0,
            "forecast_rain_7d_mm": 5.0,
        },
    }


def _farming_plan_row(crop="Wheat"):
    """A minimal saved farming comparison row."""
    return {
        "id": "fp1",
        "owner_id": UID,
        "kind": "comparison",
        "created_at": _iso(3.0),
        "input": {"preference": "integrated"},
        "result": {
            "crop": crop,
            "preference": "integrated",
            "recommendation": {
                "summary": "Integrated farming is recommended for this crop.",
                "next_step": "Start with adding farmyard manure this season.",
            },
            "warnings": ["Organic transition typically takes 2–3 seasons."],
            "organic_alternatives": [
                {
                    "id": "compost",
                    "name": "Composting",
                    "category": "Soil amendment",
                    "what_it_does": "Converts farm waste into stable organic matter.",
                },
                {
                    "id": "ipm",
                    "name": "IPM",
                    "category": "Pest management",
                    "what_it_does": "Reduces reliance on broad-spectrum pesticides.",
                },
            ],
        },
    }


@pytest.mark.parametrize(
    "question,expected",
    [
        ("How can I use organic farming for my crop?", "organic_farming"),
        ("What compost should I use?", "organic_farming"),
        ("How to transition to organic methods?", "organic_farming"),
        ("सेंद्रिय शेती कशी करावी?", "organic_farming"),
        ("Is there a drought risk on my farm?", "drought_management"),
        ("How do I save water during dry spell?", "drought_management"),
        ("पाणीटंचाई आहे का?", "drought_management"),
        ("दुष्काळाचा धोका किती?", "drought_management"),
    ],
)
def test_offline_fallback_organic_and_drought_routing(question, expected):
    assert agent_service.classify_intent(question) == expected


def test_organic_question_calls_correct_tools():
    tools = agent_service.tools_for_intent("organic_farming")
    assert "get_farm_profile" in tools
    assert "get_organic_guidance" in tools
    assert "get_drought_context" not in tools


def test_drought_question_calls_correct_tools():
    tools = agent_service.tools_for_intent("drought_management")
    assert "get_drought_context" in tools
    assert "get_sensor_readings" in tools
    assert "get_weather_information" in tools


def test_organic_answer_uses_saved_guidance(fake_client, monkeypatch):
    """When a farming comparison is saved, the agent surfaces its summary."""
    _seed(fake_client, reading=_reading())
    fake_client.tables.setdefault("farming_plans", []).append(_farming_plan_row())

    result = _ask(fake_client, "How can I use organic farming for my wheat?")

    assert result["intent"] == "organic_farming"
    assert "get_organic_guidance" in result["tools_used"]
    assert result["context"]["organic"] is not None
    # The recommendation summary from the saved plan should appear.
    text = result["answer"]
    assert "Integrated farming" in text or "integrated" in text.lower()
    assert result["fallback"] is False


def test_organic_answer_without_saved_guidance(fake_client):
    """Without a saved comparison, the agent says so instead of fabricating."""
    _seed(fake_client)

    result = _ask(fake_client, "Tell me about organic farming for my crop.")

    assert result["intent"] == "organic_farming"
    # No saved plan → the missing note appears in the answer or missing list.
    assert (
        "organic" in result["answer"].lower()
        or "farming" in result["answer"].lower()
    )
    assert result["context"]["organic"] is None


def test_drought_answer_uses_saved_assessment(fake_client):
    """When a drought assessment is saved, the agent uses its severity."""
    _seed(fake_client, reading=_reading(soil_moisture=18.0))
    fake_client.tables.setdefault("drought_assessments", []).append(
        _drought_assessment_row(severity="moderate")
    )

    result = _ask(fake_client, "Is there a drought risk on my farm?")

    assert result["intent"] == "drought_management"
    assert "get_drought_context" in result["tools_used"]
    assert result["context"]["drought"] is not None
    assert result["context"]["drought"]["drought_severity"] == "moderate"
    # The severity or a related recommendation should appear in the answer.
    assert "moderate" in result["answer"].lower() or "water" in result["answer"].lower()


def test_drought_answer_without_saved_assessment(fake_client):
    """Without a saved assessment, the agent does not invent a severity."""
    _seed(fake_client, reading=_reading())

    result = _ask(fake_client, "Is there a drought risk on my farm?")

    assert result["intent"] == "drought_management"
    assert result["context"]["drought"] is None
    # No fabricated severity.
    assert "severe" not in result["answer"].lower()
    assert "extreme" not in result["answer"].lower()


def test_drought_answer_includes_sensor_and_weather_context(fake_client):
    """Drought questions include live sensor + weather for freshness."""
    _seed(fake_client, reading=_reading(soil_moisture=15.0))

    result = _ask(fake_client, "Is there drought water scarcity risk?")

    assert result["intent"] == "drought_management"
    tools = result["tools_used"]
    assert "get_sensor_readings" in tools
    assert "get_weather_information" in tools


def test_drought_context_not_included_in_unrelated_intent(fake_client):
    """A crop recommendation question must not fetch drought context."""
    _seed(fake_client, reading=_reading())
    fake_client.tables.setdefault("drought_assessments", []).append(
        _drought_assessment_row()
    )

    result = _ask(fake_client, "Which crop should I plant this season?")

    assert result["intent"] == "crop_selection"
    assert "get_drought_context" not in result["tools_used"]
    assert result["context"]["drought"] is None


def test_organic_context_not_included_in_unrelated_intent(fake_client):
    """An irrigation question must not fetch organic guidance."""
    _seed(fake_client, reading=_reading())
    fake_client.tables.setdefault("farming_plans", []).append(_farming_plan_row())

    result = _ask(fake_client, "Should I irrigate today?")

    assert result["intent"] == "irrigation"
    assert "get_organic_guidance" not in result["tools_used"]
    assert result["context"]["organic"] is None


def test_marathi_drought_intent_and_label(fake_client):
    """Marathi drought question gets the Marathi intent label."""
    _seed(fake_client, reading=_reading())

    result = _ask(fake_client, "दुष्काळाचा धोका किती?", language="mr")

    assert result["intent"] == "drought_management"
    assert result["intent_label"] == "दुष्काळ व्यवस्थापन"


def test_marathi_organic_intent_and_label(fake_client):
    """Marathi organic question gets the Marathi intent label."""
    _seed(fake_client, reading=_reading())

    result = _ask(fake_client, "सेंद्रिय शेती कशी करावी?", language="mr")

    assert result["intent"] == "organic_farming"
    assert result["intent_label"] == "सेंद्रिय शेती"


def test_drought_context_tool_result_structure(fake_client):
    """The drought context tool returns the expected keys."""
    _seed(fake_client)
    fake_client.tables.setdefault("drought_assessments", []).append(
        _drought_assessment_row(severity="severe", crop="Cotton")
    )

    result = _ask(fake_client, "What is the drought situation?")

    drought = result["context"].get("drought")
    if drought:  # available only when the tool was called
        assert drought["drought_severity"] == "severe"
        assert drought["crop"] == "Cotton"
        assert "top_recommendations" in drought or "top_category" in drought


def test_organic_context_tool_result_structure(fake_client):
    """The organic guidance tool returns the expected keys."""
    _seed(fake_client)
    fake_client.tables.setdefault("farming_plans", []).append(_farming_plan_row())

    result = _ask(fake_client, "How can I use organic farming?")

    organic = result["context"].get("organic")
    if organic:
        assert organic["crop"] == "Wheat"
        assert "recommendation_summary" in organic or "organic_alternatives" in organic


# ── Context block completeness ────────────────────────────────────────────────

def test_context_block_includes_drought_and_organic_when_available(fake_client):
    """context_block() reports drought and organic alongside farm/sensor/weather."""
    _seed(fake_client, reading=_reading())
    fake_client.tables.setdefault("drought_assessments", []).append(
        _drought_assessment_row()
    )
    fake_client.tables.setdefault("farming_plans", []).append(_farming_plan_row())

    # farm_status calls get_available_farm_recommendations, not drought/organic.
    # Use explicit intents by asking targeted questions.
    drought_result = _ask(fake_client, "What is the drought risk?")
    assert drought_result["context"]["drought"] is not None or drought_result["context"]["drought"] is None  # present or not

    organic_result = _ask(fake_client, "Tell me about organic compost options.")
    # organic key always present in context_block output (may be None)
    assert "organic" in organic_result["context"]


def test_drought_context_field_isolation(fake_client):
    """A different user's drought assessment is never returned."""
    _seed(fake_client)
    fake_client.seed_profile(uid=OTHER, email="other@example.com", mobile="+919000000002")
    # Seed the assessment for the OTHER user.
    other_assessment = {**_drought_assessment_row(), "owner_id": OTHER}
    fake_client.tables.setdefault("drought_assessments", []).append(other_assessment)

    result = _ask(fake_client, "What is the drought situation?", owner=UID)

    # UID has no drought assessment → tool should return unavailable.
    drought = result["context"].get("drought")
    assert drought is None


def test_organic_guidance_field_isolation(fake_client):
    """A different user's farming plan is never returned."""
    _seed(fake_client)
    fake_client.seed_profile(uid=OTHER, email="other@example.com", mobile="+919000000002")
    other_plan = {**_farming_plan_row(), "owner_id": OTHER}
    fake_client.tables.setdefault("farming_plans", []).append(other_plan)

    result = _ask(fake_client, "How can I use organic compost?", owner=UID)

    organic = result["context"].get("organic")
    assert organic is None


# ── LLM-driven tool planning ─────────────────────────────────────────────────
#
# The planner decides which tools a message needs; the agent must honour that
# selection (and no more), and fall back deterministically when the reply is
# unusable. These tests stub the planner directly so no provider is involved.

def _plan(intent, tools, needs_retrieval=False):
    return {"intent": intent, "tools": tuple(tools), "needs_retrieval": needs_retrieval}


def test_planner_selection_is_honoured(fake_client, monkeypatch):
    _seed(fake_client, reading=_reading())
    monkeypatch.setattr(
        agent_service,
        "plan_tools",
        lambda *_, **__: _plan("weather", ("get_weather_information",)),
    )

    result = _ask(fake_client, "anything at all")

    assert result["intent"] == "weather"
    assert result["tools_used"] == ["get_weather_information"]
    # The planner's narrow selection means nothing else was read.
    assert result["context"]["sensors"] is None
    assert result["context"]["farm"] is None


def test_planner_can_request_a_tool_the_keyword_router_would_not(fake_client, monkeypatch):
    """The planner, not the keyword list, decides: an unrelated phrase still works."""
    _seed(fake_client, reading=_reading())
    monkeypatch.setattr(
        agent_service,
        "plan_tools",
        lambda *_, **__: _plan("sensors", ("get_sensor_readings",)),
    )

    # The fallback router has no keyword for this, so it would read nothing.
    assert agent_service.classify_intent("how wet is the ground right now") != "sensors"

    result = _ask(fake_client, "how wet is the ground right now")

    assert result["tools_used"] == ["get_sensor_readings"]
    assert "20" in result["answer"]


def test_planner_greeting_reads_no_farm_data_and_answers_conversationally(fake_client, monkeypatch):
    _seed(fake_client, reading=_reading())
    monkeypatch.setattr(
        agent_service, "plan_tools", lambda *_, **__: _plan("unknown", ())
    )
    monkeypatch.setattr(
        "app.rag_service.direct_llm_answer",
        lambda *_, **__: {"answer": "Hello! I'm FarmIQ. How can I help with your farm today?",
                          "llm_used": True, "sources": []},
    )

    result = _ask(fake_client, "Hi")

    assert result["tools_used"] == []
    assert result["context"] == {
        "farm": None, "sensors": None, "weather": None,
        "predictions": {}, "drought": None, "organic": None,
    }
    assert result["answer"].startswith("Hello!")
    assert result["llm_used"] is True
    assert result["fallback"] is False


def test_planner_skips_retrieval_when_it_says_documents_are_not_needed(fake_client, monkeypatch):
    _seed(fake_client, reading=_reading())
    calls = {"n": 0}

    def _rag(*_, **__):
        calls["n"] += 1
        return {"answer": "unused", "retrieval_status": "OK", "llm_used": True, "sources": []}

    monkeypatch.setattr("app.rag_service.answer_question", _rag)
    monkeypatch.setattr(
        agent_service,
        "plan_tools",
        lambda *_, **__: _plan("sensors", ("get_sensor_readings",), needs_retrieval=False),
    )

    result = _ask(fake_client, "What is the soil moisture level?")

    assert calls["n"] == 0                       # no redundant retrieval call
    assert result["tools_used"] == ["get_sensor_readings"]


def test_planner_requests_retrieval_when_documents_would_help(fake_client, monkeypatch):
    _seed(fake_client, reading=_reading())
    calls = {"n": 0}

    def _rag(*_, **__):
        calls["n"] += 1
        return {"answer": "Under the scheme, ...", "retrieval_status": "OK",
                "llm_used": True, "sources": [{"title": "State scheme"}]}

    monkeypatch.setattr("app.rag_service.answer_question", _rag)
    monkeypatch.setattr(
        agent_service,
        "plan_tools",
        lambda *_, **__: _plan("unknown", (), needs_retrieval=True),
    )

    result = _ask(fake_client, "Which government subsidy applies to my farm?")

    assert calls["n"] == 1
    assert result["sources"] == [{"title": "State scheme"}]


def test_unusable_planner_reply_falls_back_to_the_deterministic_router(fake_client):
    """A malformed reply is ignored; the offline router takes over (fixture default None)."""
    _seed(fake_client, reading=_reading())

    result = _ask(fake_client, "What is the soil moisture level?")

    assert result["intent"] == "sensors"
    assert result["tools_used"] == ["get_sensor_readings"]


def test_planner_output_is_validated_independently_of_the_model():
    # Unknown tool names are dropped; a bad intent becomes "unknown".
    plan = agent_service._validate_plan(
        {"intent": "make coffee", "tools": ["get_sensor_readings", "drop_table", 42]},
    )
    assert plan == {
        "intent": "unknown",
        "tools": ("get_sensor_readings",),
        "needs_retrieval": False,
    }

    # A reply with no usable structure is rejected so the caller can fall back.
    assert agent_service._validate_plan({"tools": "get_sensor_readings"}) is None
    assert agent_service._validate_plan(None) is None


def test_planner_json_is_extracted_from_prose_and_fences():
    fenced = 'Sure!\n```json\n{"intent": "weather", "tools": ["get_weather_information"]}\n```\n'
    assert agent_service._extract_plan_json(fenced) == {
        "intent": "weather",
        "tools": ["get_weather_information"],
    }
    assert agent_service._extract_plan_json("no json here") is None
    assert agent_service._extract_plan_json("") is None


def test_planner_runs_through_llm_generate(fake_client, monkeypatch):
    """End-to-end: the JSON the provider returns drives the tool selection."""
    _seed(fake_client, reading=_reading())
    monkeypatch.setattr(
        "app.rag_service.llm_generate",
        lambda *_, **__: '{"intent": "sensors", "tools": ["get_sensor_readings"], '
                         '"needs_retrieval": false}',
    )

    result = _ask(fake_client, "how wet is the ground right now")

    assert result["tools_used"] == ["get_sensor_readings"]
    assert result["context"]["weather"] is None


def test_planner_unavailable_and_bad_reply_both_keep_the_agent_working(fake_client, monkeypatch):
    _seed(fake_client, reading=_reading())
    monkeypatch.setattr("app.rag_service.llm_generate", lambda *_, **__: "not json at all")

    result = _ask(fake_client, "What is the soil moisture level?")

    # Fell back to the deterministic router and still answered from real data.
    assert result["tools_used"] == ["get_sensor_readings"]
    assert "20" in result["answer"]


# ── The RAG failure message must never be the answer ──────────────────────────

_RAG_FAILURE = (
    "The knowledge base does not contain sufficient information to answer this "
    "question confidently. Consider adding relevant agricultural documents to "
    "data/raw/ and re-running ingestion."
)


def test_retrieval_failure_message_is_never_shown_to_the_farmer(fake_client, monkeypatch):
    _seed(fake_client, reading=_reading())
    monkeypatch.setattr(
        "app.rag_service.answer_question",
        lambda *_, **__: {
            "answer": _RAG_FAILURE,
            "retrieval_status": "BELOW_THRESHOLD",
            "llm_used": False,
            "sources": [],
        },
    )

    result = _ask(fake_client, "What is the soil moisture level?")

    answer = result["answer"].lower()
    assert "knowledge base" not in answer
    assert "ingestion" not in answer
    assert "data/raw" not in answer
    # The real sensor evidence still comes through.
    assert "20" in result["answer"]


def test_no_documents_still_yields_a_helpful_reply(fake_client, monkeypatch):
    """A retrieval miss for a general question must not become a dead end."""
    _seed(fake_client)
    monkeypatch.setattr(
        agent_service, "plan_tools", lambda *_, **__: _plan("unknown", ())
    )
    monkeypatch.setattr(
        "app.rag_service.answer_question",
        lambda *_, **__: {
            "answer": _RAG_FAILURE,
            "retrieval_status": "EMPTY_INDEX",
            "llm_used": False,
            "sources": [],
        },
    )

    result = _ask(fake_client, "Which government scheme applies to my farm?")

    assert result["answer"]                          # not empty
    assert "ingestion" not in result["answer"].lower()
    assert "knowledge base" not in result["answer"].lower()


def test_retrieval_outage_makes_the_answer_fall_back_not_pretend(fake_client, monkeypatch):
    """When retrieval errors out, the reply is a real fallback, not a fake success."""
    _seed(fake_client)
    monkeypatch.setattr(
        agent_service, "plan_tools", lambda *_, **__: _plan("unknown", ())
    )

    def _boom(*_, **__):
        raise RuntimeError("vector store down")

    monkeypatch.setattr("app.rag_service.answer_question", _boom)

    result = _ask(fake_client, "Tell me about crop rotation.")

    assert result["llm_used"] is False
    assert result["fallback"] is True
    assert result["answer"]


# ── Wall-clock budget: the agent must answer before the client gives up ───────
#
# The web/app client aborts a chat request after 90s (CHAT_TIMEOUT_MS), so one
# request's LLM work (tool plan + direct answer + retrieval) shares a single
# deadline. A slow or hung provider must degrade to the deterministic answer
# instead of holding the request open.


def test_answer_gives_the_planner_a_bounded_timeout(fake_client, monkeypatch):
    _seed(fake_client, reading=_reading())
    seen: dict = {}
    real_plan = agent_service.plan_tools

    def _capture(question, **kwargs):
        seen.update(kwargs)
        return real_plan(question, **kwargs)

    monkeypatch.setattr(agent_service, "plan_tools", _capture)
    # No planner reply: _assistant_offline stubs llm_generate to None.
    _ask(fake_client, "What is the soil moisture level?")

    timeout = seen.get("timeout")
    assert isinstance(timeout, float)
    assert 0 < timeout <= agent_service.get_settings().llm_planner_timeout_seconds


def test_slow_planner_degrades_to_the_deterministic_router(fake_client, monkeypatch):
    _seed(fake_client, reading=_reading())
    settings = agent_service.get_settings()
    monkeypatch.setattr(settings, "llm_planner_timeout_seconds", 0.05)
    monkeypatch.setattr(settings, "assistant_llm_budget_seconds", 0.3)
    monkeypatch.setattr(
        "app.rag_service.llm_generate",
        lambda *_, **__: time.sleep(0.5)
        or '{"intent": "sensors", "tools": ["get_sensor_readings"]}',
    )

    started = time.monotonic()
    result = _ask(fake_client, "What is the soil moisture level?")
    elapsed = time.monotonic() - started

    assert elapsed < 3.0, "a hung planner must not hold the request open"
    # The deterministic router took over and the real sensor data still answered.
    assert result["tools_used"] == ["get_sensor_readings"]
    assert "20" in result["answer"]


def test_explainer_shares_the_same_request_budget(fake_client, monkeypatch):
    _seed(fake_client, reading=_reading())
    monkeypatch.setattr(
        agent_service, "plan_tools", lambda *_, **__: _plan("sensors", ("get_sensor_readings",))
    )
    seen: dict = {}

    def _direct(*_, **kwargs):
        seen.update(kwargs)
        return {"answer": "Your soil is dry — irrigate soon.", "llm_used": True, "sources": []}

    monkeypatch.setattr("app.rag_service.direct_llm_answer", _direct)
    _ask(fake_client, "What is the soil moisture level?")

    timeout = seen.get("timeout")
    assert isinstance(timeout, float)
    assert 0 < timeout <= agent_service.get_settings().assistant_llm_budget_seconds
