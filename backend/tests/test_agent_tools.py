"""Tests for the agent's tool layer (app.agent_tools).

These exercise the tools directly against the fake Supabase client, so no
network or real credentials are needed. The weather lookup is injected, which
also keeps the assertions deterministic.

The scenarios covered here are the data-availability ones from the agent spec:
all sources present, some ML predictions missing, sensors offline/absent, and a
weather failure — plus owner isolation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import farm_context_manager as ctx
from app.agent_tools import PREDICTION_DOMAINS, TOOL_NAMES, FarmTools, ToolArgumentError

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
            "temperature_c": 31.4,
            "humidity_pct": 48.0,
            "precipitation_mm": 0.0,
        },
        "forecast_rainfall": {"total_mm": 3.0, "daily": []},
        "historical_rainfall": {"total_mm": 142.5},
    }


@pytest.fixture(autouse=True)
def _fresh_caches(monkeypatch):
    """Fresh weather cache and a stubbed ML adapter for every test."""
    ctx.reset_caches()

    class _StubAdapter:
        def status(self):
            return {"crop": {"model": True}}

    monkeypatch.setattr("ml.adapter.get_adapter", lambda: _StubAdapter())
    yield
    ctx.reset_caches()


@pytest.fixture(autouse=True)
def _weather(monkeypatch):
    """Default to a working weather provider; individual tests can override."""
    from app import weather as weather_module

    monkeypatch.setattr(weather_module, "build_report", _weather_ok)


def _seed(fake_client, *, farm=True, reading=None, predictions=None, assessment=None):
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
    if assessment is not None:
        fake_client.tables.setdefault("drought_assessments", []).append(
            {"owner_id": UID, **assessment}
        )


def _tools(fake_client, owner=UID, **kwargs):
    return FarmTools(fake_client, owner, now=NOW, **kwargs)


def _full_reading(**overrides):
    return {
        "created_at": _iso(0.2),
        "soil_moisture": 20.0,
        "temperature": 30.1,
        "humidity": 51.0,
        "ph": 6.8,
        "nitrogen": 42.0,
        "phosphorous": 18.0,
        "potassium": 55.0,
        "soil_temperature": 27.5,
        **overrides,
    }


# ── Tool name contract ───────────────────────────────────────────────────────

def test_all_nine_tools_exist():
    assert TOOL_NAMES == (
        "get_farm_profile",
        "get_sensor_readings",
        "get_weather_information",
        "get_crop_prediction",
        "get_fertilizer_prediction",
        "get_irrigation_prediction",
        "get_yield_prediction",
        "get_farm_history",
        "get_available_farm_recommendations",
        "get_drought_context",
        "get_organic_guidance",
    )
    # Every advertised name must be callable.
    tools = FarmTools(object(), UID)
    for name in TOOL_NAMES:
        assert callable(getattr(tools, name))


def test_unknown_tool_is_rejected_not_guessed(fake_client):
    with pytest.raises(ToolArgumentError):
        _tools(fake_client).call("get_everything")


def test_missing_owner_is_rejected(fake_client):
    with pytest.raises(ToolArgumentError):
        FarmTools(fake_client, "")


# ── get_farm_profile ─────────────────────────────────────────────────────────

def test_farm_profile_returns_whitelisted_fields_only(fake_client):
    _seed(fake_client)

    result = _tools(fake_client).get_farm_profile()

    assert result["available"] is True
    data = result["data"]
    assert data["current_crop"] == "Wheat"
    assert data["location"] == "Nashik, Maharashtra"
    # Coordinates and ownership never leave the database layer.
    for leaked in ("latitude", "longitude", "owner_id", "meta"):
        assert leaked not in data
    assert result["as_of"] == FARM_ROW["created_at"]


def test_farm_profile_absent_is_reported_not_invented(fake_client):
    fake_client.seed_profile(uid=OTHER, email="empty@example.com", mobile="+919000000002")

    result = _tools(fake_client, OTHER).get_farm_profile()

    assert result["available"] is False
    assert result["data"] is None
    assert result["note"]


def test_growth_stage_comes_from_the_latest_assessment(fake_client):
    _seed(fake_client, assessment={"id": "a1", "growth_stage": "flowering", "created_at": _iso(3)})

    data = _tools(fake_client).get_farm_profile()["data"]

    assert data["growth_stage"] == "flowering"
    assert data["growth_stage_source"] == "latest drought assessment"


def test_growth_stage_is_absent_when_no_assessment_exists(fake_client):
    _seed(fake_client)

    data = _tools(fake_client).get_farm_profile()["data"]

    assert "growth_stage" not in data


# ── get_sensor_readings ──────────────────────────────────────────────────────

def test_sensor_readings_report_values_and_freshness(fake_client):
    _seed(fake_client, reading=_full_reading())

    result = _tools(fake_client).get_sensor_readings()

    assert result["available"] is True
    data = result["data"]
    assert data["soil_moisture"] == 20.0
    assert data["ph"] == 6.8
    assert data["freshness"] == ctx.FRESH
    assert data["missing_channels"] == []
    assert result["as_of"] == _iso(0.2)


def test_absent_channels_are_listed(fake_client):
    _seed(fake_client, reading={"created_at": _iso(0.1), "soil_moisture": 22.0})

    data = _tools(fake_client).get_sensor_readings()["data"]

    assert "temperature" in data["missing_channels"]
    assert "ph" in data["missing_channels"]
    assert "temperature" not in data  # never fabricated


def test_offline_sensors_are_marked_stale(fake_client):
    _seed(fake_client, reading={"created_at": _iso(10.0), "soil_moisture": 22.0})

    data = _tools(fake_client).get_sensor_readings()["data"]

    assert data["freshness"] == ctx.OFFLINE
    assert data["age_hours"] >= 9


def test_no_sensor_readings_is_reported_not_invented(fake_client):
    _seed(fake_client, reading=None)

    result = _tools(fake_client).get_sensor_readings()

    assert result["available"] is False
    assert result["data"] is None


def test_demo_reading_keeps_its_provenance(fake_client):
    _seed(fake_client, reading={"created_at": _iso(0.1), "soil_moisture": 22.0, "is_demo": True})

    data = _tools(fake_client).get_sensor_readings()["data"]

    assert data["is_demo"] is True


# ── get_weather_information ──────────────────────────────────────────────────

def test_weather_tool_returns_current_and_forecast_rain(fake_client):
    _seed(fake_client)

    result = _tools(fake_client).get_weather_information()

    assert result["available"] is True
    data = result["data"]
    assert data["temperature_c"] == 31.4
    assert data["forecast_rain_7d_mm"] == 3.0
    assert data["historical_rain_30d_mm"] == 142.5
    assert data["location"] == "Nashik, Maharashtra"


def test_weather_failure_degrades_without_raising(fake_client, monkeypatch):
    from app import weather as weather_module

    def _boom(*_, **__):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(weather_module, "build_report", _boom)
    ctx.reset_caches()
    _seed(fake_client)

    result = _tools(fake_client).get_weather_information()

    assert result["available"] is False
    assert result["data"] is None
    assert result["note"]


def test_weather_absent_without_a_farm(fake_client):
    fake_client.seed_profile(uid=UID)

    result = _tools(fake_client).get_weather_information()

    assert result["available"] is False


# ── Prediction tools ─────────────────────────────────────────────────────────

def test_crop_prediction_reads_the_voice_domain_alias(fake_client):
    """The voice assistant stores ``crop_recommendation``; the tool must find it."""
    _seed(
        fake_client,
        predictions=[
            {
                "id": "p1",
                "domain": "crop_recommendation",
                "output": {"prediction": "Wheat", "label": "Wheat"},
                "created_at": _iso(2.0),
            }
        ],
    )

    result = _tools(fake_client).get_crop_prediction()

    assert result["available"] is True
    assert result["data"]["prediction"] == "Wheat"
    assert result["as_of"] == _iso(2.0)


def test_absent_prediction_is_reported_not_invented(fake_client):
    _seed(fake_client)

    for tool in ("get_crop_prediction", "get_fertilizer_prediction", "get_yield_prediction"):
        result = _tools(fake_client).call(tool)
        assert result["available"] is False
        assert result["data"] is None


def test_irrigation_tool_keeps_model_and_rule_baseline_separate(fake_client):
    _seed(
        fake_client,
        reading=_full_reading(soil_moisture=20.0),
        predictions=[
            {
                "id": "p1",
                "domain": "irrigation",
                "source": "baseline",
                "output": {"prediction": 1, "label": "Irrigation recommended"},
                "created_at": _iso(1.0),
            }
        ],
    )

    data = _tools(fake_client).get_irrigation_prediction()["data"]

    assert data["ml_prediction"]["prediction"] == 1
    assert data["ml_prediction"]["source"] == "baseline"
    # The rule engine's own action is a separate, labelled field.
    assert data["rule_based_baseline"]["priority"] in ("critical", "high")
    assert "Irrigate" in data["rule_based_baseline"]["action"]


def test_irrigation_tool_falls_back_to_the_rule_engine(fake_client):
    _seed(fake_client, reading=_full_reading(soil_moisture=20.0))

    result = _tools(fake_client).get_irrigation_prediction()

    assert result["available"] is True
    assert result["data"]["ml_prediction"] is None
    assert result["data"]["rule_based_baseline"] is not None


def test_irrigation_tool_unavailable_without_any_basis(fake_client):
    _seed(fake_client, reading=None)

    result = _tools(fake_client).get_irrigation_prediction()

    assert result["available"] is False


# ── get_farm_history ─────────────────────────────────────────────────────────

def test_history_returns_newest_first_and_honours_the_limit(fake_client):
    _seed(
        fake_client,
        predictions=[
            {"id": f"p{i}", "domain": "crop", "output": {"prediction": f"C{i}"},
             "created_at": _iso(float(i))}
            for i in range(1, 6)
        ],
    )

    data = _tools(fake_client).get_farm_history(limit=3)["data"]

    assert data["count"] == 3
    assert [item["prediction"] for item in data["items"]] == ["C1", "C2", "C3"]


def test_history_filters_by_domain(fake_client):
    _seed(
        fake_client,
        predictions=[
            {"id": "p1", "domain": "crop", "output": {"prediction": "Wheat"}, "created_at": _iso(1)},
            {"id": "p2", "domain": "yield", "output": {"prediction": 3.1}, "created_at": _iso(2)},
        ],
    )

    data = _tools(fake_client).get_farm_history(domain="yield")["data"]

    assert data["count"] == 1
    assert data["items"][0]["domain"] == "yield"


@pytest.mark.parametrize("domain", ["potato", "", "crop;drop table"])
def test_history_rejects_an_unknown_domain(fake_client, domain):
    _seed(fake_client)
    with pytest.raises(ToolArgumentError):
        _tools(fake_client).get_farm_history(domain=domain)


@pytest.mark.parametrize("limit", [0, -1, 999, "5", True, 1.5])
def test_history_rejects_an_invalid_limit(fake_client, limit):
    _seed(fake_client)
    with pytest.raises(ToolArgumentError):
        _tools(fake_client).get_farm_history(limit=limit)


def test_prediction_domains_are_the_four_models():
    assert set(PREDICTION_DOMAINS) == {"crop", "fertilizer", "yield", "irrigation"}


# ── get_available_farm_recommendations ───────────────────────────────────────

def test_recommendations_derive_from_the_existing_plan(fake_client):
    _seed(fake_client, reading=_full_reading(soil_moisture=20.0))

    result = _tools(fake_client).get_available_farm_recommendations()

    assert result["available"] is True
    categories = {action["category"] for action in result["data"]["actions"]}
    assert "irrigation" in categories
    # Data-quality items are real but are not farm actions for the agent to
    # present as advice; they are filtered by the caller, not fabricated here.
    assert result["data"]["actions"][0]["priority"] == "high"


def test_recommendations_unavailable_without_any_data(fake_client):
    fake_client.seed_profile(uid=OTHER, email="empty@example.com", mobile="+919000000002")

    result = _tools(fake_client, OTHER).get_available_farm_recommendations()

    # No farm and no readings means the only derivable item is a data-quality
    # one, so there is nothing actionable to report.
    assert result["data"] is None or all(
        action["category"] == "data_quality" for action in result["data"]["actions"]
    )


# ── Ownership isolation ──────────────────────────────────────────────────────

def test_another_owner_reads_nothing(fake_client):
    _seed(fake_client, reading=_full_reading())
    fake_client.seed_profile(uid=OTHER, email="other@example.com", mobile="+919000000002")

    tools = _tools(fake_client, OTHER)

    assert tools.get_farm_profile()["available"] is False
    assert tools.get_sensor_readings()["available"] is False
    assert tools.get_crop_prediction()["available"] is False


def test_another_owner_cannot_select_a_foreign_farm(fake_client):
    _seed(fake_client, reading=_full_reading())
    fake_client.seed_profile(uid=OTHER, email="other@example.com", mobile="+919000000002")

    result = _tools(fake_client, OTHER, farm_id=FARM_ID).get_farm_profile()

    assert result["available"] is False


# ── LLM-facing context and freshness index ───────────────────────────────────

def test_llm_context_uses_the_audited_whitelist(fake_client):
    _seed(fake_client, reading=_full_reading())

    context = _tools(fake_client).llm_context()

    assert context["current_crop"] == "Wheat"
    assert context["soil_moisture"] == 20.0
    assert context["latest_reading_source"] == "device"
    for leaked in ("id", "owner_id", "latitude", "longitude", "device_id"):
        assert leaked not in context


def test_llm_context_is_none_without_any_real_data(fake_client):
    fake_client.seed_profile(uid=OTHER, email="empty@example.com", mobile="+919000000002")

    assert _tools(fake_client, OTHER).llm_context() is None


def test_freshness_index_labels_every_source(fake_client):
    _seed(
        fake_client,
        reading=_full_reading(),
        predictions=[{"id": "p1", "domain": "crop", "output": {"prediction": "Wheat"},
                      "created_at": _iso(1.0)}],
    )

    index = _tools(fake_client).freshness_index()

    assert index["farm"] == FARM_ROW["created_at"]
    assert index["sensors"] == _iso(0.2)
    assert index["weather"] == NOW.isoformat()
    assert index["predictions"]["crop"] == _iso(1.0)
    assert index["generated_at"] == NOW.isoformat()
