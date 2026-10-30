"""Tests for the centralised farm data aggregator (app.farm_context_manager).

These exercise the *service* directly against the fake Supabase client, so no
network or real credentials are needed. The weather lookup is injected, which
also lets the cache be asserted precisely.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import farm_context_manager as ctx

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
UID = "u1"
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
    "current_crop": "Soybean",
    "irrigation_type": "drip",
    "latitude": 19.9975,
    "longitude": 73.7898,
    "created_at": _iso(24 * 30),
}


@pytest.fixture(autouse=True)
def _clean_cache_and_ml(monkeypatch):
    """Fresh weather cache + a stubbed ML adapter for every test."""
    ctx.reset_caches()

    class _StubAdapter:
        def status(self):
            return {"crop": {"preprocessing": True, "model": True, "model_path": "crop/model.joblib"}}

    monkeypatch.setattr("ml.adapter.get_adapter", lambda: _StubAdapter())
    yield
    ctx.reset_caches()


def _seed(fake_client, *, farm=True, reading=None, predictions=None):
    fake_client.seed_profile(uid=UID)
    if farm:
        fake_client.tables.setdefault("farms", []).append(dict(FARM_ROW))
    if reading is not None:
        reading = {"owner_id": UID, "farm_id": FARM_ID, "device_id": "d1", **reading}
        fake_client.tables.setdefault("sensor_readings", []).append(reading)
    for row in predictions or []:
        fake_client.tables.setdefault("predictions", []).append({"owner_id": UID, **row})


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
        "forecast_rainfall": {"total_mm": 3.0},
        "historical_rainfall": {"total_mm": 142.5},
    }


# ── Full context ─────────────────────────────────────────────────────────────

def test_builds_full_context_from_real_rows(fake_client):
    _seed(
        fake_client,
        reading={
            "created_at": _iso(0.2),
            "soil_moisture": 24.0,
            "temperature": 30.1,
            "humidity": 51.0,
            "ph": 6.8,
            "nitrogen": 42.0,
            "phosphorous": 18.0,
            "potassium": 55.0,
            "soil_temperature": 27.5,
        },
        predictions=[{"id": "p1", "domain": "crop", "source": "model",
                      "input": {"N": 42}, "output": {"prediction": "Soybean"},
                      "created_at": _iso(1.0)}],
    )

    context = ctx.build_context(
        fake_client, UID, weather_fetcher=_weather_ok, now=NOW
    )

    assert context["farm"]["current_crop"] == "Soybean"
    assert context["farm"]["meta"]["source"] == "farms"
    assert context["sensors"]["soil_moisture"] == 24.0
    assert context["sensors"]["freshness"] == ctx.FRESH
    assert context["weather"]["temperature_c"] == 31.4
    assert context["weather"]["historical_rain_30d_mm"] == 142.5
    assert context["ml"]["latest"]["crop"]["prediction"] == "Soybean"
    assert context["ml"]["models"]["crop"]["model"] is True
    # Only the three prediction domains that were never seeded are reported
    # missing — farm, sensors and weather are all present.
    assert context["missing"] == [
        "prediction:fertilizer",
        "prediction:yield",
        "prediction:irrigation",
    ]
    assert context["warnings"] == []


# ── Missing data is reported, never invented ─────────────────────────────────

def test_missing_sensor_readings_are_reported_not_invented(fake_client):
    _seed(fake_client, reading=None)

    context = ctx.build_context(
        fake_client, UID, weather_fetcher=_weather_ok, now=NOW
    )

    assert context["sensors"] is None
    assert "sensor_readings" in context["missing"]
    # No fabricated channel values anywhere in the context.
    assert "soil_moisture" not in context["missing"]


def test_absent_channels_are_listed(fake_client):
    _seed(fake_client, reading={"created_at": _iso(0.1), "soil_moisture": 22.0})

    context = ctx.build_context(
        fake_client, UID, weather_fetcher=_weather_ok, now=NOW
    )

    sensors = context["sensors"]
    assert sensors["soil_moisture"] == 22.0
    assert "temperature" in sensors["missing_channels"]
    assert "ph" in sensors["missing_channels"]
    assert "sensor:temperature" in context["missing"]


def test_implausible_value_is_flagged_not_hidden(fake_client):
    _seed(fake_client, reading={"created_at": _iso(0.1), "soil_moisture": 22.0, "ph": 99.0})

    context = ctx.build_context(
        fake_client, UID, weather_fetcher=_weather_ok, now=NOW
    )

    assert context["sensors"]["invalid_channels"] == ["ph"]


def test_bme680_pressure_is_context_but_not_a_required_channel(fake_client):
    """A BME680 node's pressure reaches the context; soil-only probes are not
    penalised for not having it, so it is never a "missing channel"."""
    _seed(
        fake_client,
        reading={"created_at": _iso(0.1), "temperature": 28.4, "pressure": 1008.3},
    )

    context = ctx.build_context(
        fake_client, UID, weather_fetcher=_weather_ok, now=NOW
    )

    sensors = context["sensors"]
    assert sensors["pressure"] == 1008.3
    assert "pressure" not in sensors["missing_channels"]
    assert "sensor:pressure" not in context["missing"]

    # ...and a reading that has no pressure is not reported as missing one.
    ctx.reset_caches()
    fake_client.tables["sensor_readings"] = [
        {"owner_id": UID, "farm_id": FARM_ID, "device_id": "d1",
         "created_at": _iso(0.1), "soil_moisture": 30.0}
    ]
    plain = ctx.build_context(fake_client, UID, weather_fetcher=_weather_ok, now=NOW)
    assert "pressure" not in plain["sensors"]["missing_channels"]


# ── Freshness ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "hours_ago,expected",
    [(0.2, ctx.FRESH), (2.0, ctx.STALE), (10.0, ctx.OFFLINE)],
)
def test_reading_freshness_verdicts(fake_client, hours_ago, expected):
    _seed(fake_client, reading={"created_at": _iso(hours_ago), "soil_moisture": 20.0})

    context = ctx.build_context(
        fake_client, UID, weather_fetcher=_weather_ok, now=NOW
    )

    assert context["sensors"]["freshness"] == expected
    if expected != ctx.FRESH:
        assert any("sensor_readings" in m for m in context["missing"])


def test_demo_reading_is_marked_as_simulated(fake_client):
    _seed(fake_client, reading={"created_at": _iso(0.1), "soil_moisture": 20.0, "is_demo": True})

    context = ctx.build_context(
        fake_client, UID, weather_fetcher=_weather_ok, now=NOW
    )

    assert context["sensors"]["is_demo"] is True
    assert context["sensors"]["meta"]["source"] == "demo_simulator"


# ── Graceful degradation ─────────────────────────────────────────────────────

def test_weather_failure_degrades_without_raising(fake_client):
    _seed(fake_client, reading={"created_at": _iso(0.1), "soil_moisture": 20.0})

    def _boom(*_, **__):
        raise RuntimeError("upstream down")

    context = ctx.build_context(fake_client, UID, weather_fetcher=_boom, now=NOW)

    assert context["weather"] is None
    assert "weather_unavailable" in context["warnings"]
    assert "weather" in context["missing"]
    # The rest of the context still works.
    assert context["sensors"]["soil_moisture"] == 20.0


def test_weather_can_be_skipped(fake_client):
    _seed(fake_client, reading={"created_at": _iso(0.1), "soil_moisture": 20.0})

    context = ctx.build_context(fake_client, UID, include_weather=False, now=NOW)

    assert context["weather"] is None
    assert "weather" in context["missing"]


# ── Caching ──────────────────────────────────────────────────────────────────

def test_weather_is_cached_across_calls(fake_client):
    _seed(fake_client, reading={"created_at": _iso(0.1), "soil_moisture": 20.0})
    calls = {"n": 0}

    def _counted(*_, **__):
        calls["n"] += 1
        return _weather_ok()

    ctx.build_context(fake_client, UID, weather_fetcher=_counted, now=NOW)
    ctx.build_context(fake_client, UID, weather_fetcher=_counted, now=NOW)

    assert calls["n"] == 1


# ── Ownership isolation ──────────────────────────────────────────────────────

def test_another_owner_cannot_read_the_farm(fake_client):
    _seed(fake_client, reading=None)
    fake_client.seed_profile(uid="u2", email="other@example.com", mobile="+919000000002")

    context = ctx.build_context(
        fake_client, "u2", farm_id=FARM_ID, include_weather=False, now=NOW
    )

    assert context["farm"] is None
    assert "farm_profile" in context["missing"]


# ── LLM-facing flattening ────────────────────────────────────────────────────

def test_prompt_context_omits_ids_and_coordinates(fake_client):
    _seed(
        fake_client,
        reading={"created_at": _iso(0.1), "soil_moisture": 24.0, "ph": 6.8},
    )

    context = ctx.build_context(fake_client, UID, weather_fetcher=_weather_ok, now=NOW)
    flat = ctx.to_prompt_context(context)

    assert flat["current_crop"] == "Soybean"
    assert flat["soil_moisture"] == 24.0
    assert flat["weather_temperature_c"] == 31.4
    # Sensitive / internal keys never reach the prompt.
    for leaked in ("id", "owner_id", "latitude", "longitude", "meta", "device_id"):
        assert leaked not in flat


def test_prompt_context_is_none_when_nothing_is_known(fake_client):
    fake_client.seed_profile(uid="u3", email="empty@example.com", mobile="+919000000003")

    context = ctx.build_context(
        fake_client, "u3", include_weather=False, now=NOW
    )

    assert ctx.to_prompt_context(context) is None
