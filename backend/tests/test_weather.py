"""Weather auto-fill tests (feature 1).

The upstream provider is never contacted: ``app.weather._client`` is replaced
with an in-process fake, so the success path and the provider-down path are
both exercised deterministically.
"""
from datetime import date, timedelta

import httpx
import pytest

from app import weather
from app.config import get_settings


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    """Stand-in for ``httpx.Client`` that returns a canned Open-Meteo payload."""

    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None):
        return _FakeResponse(self._payload)


class _DownClient:
    """Stand-in for ``httpx.Client`` whose requests always fail."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None):
        raise httpx.ConnectError("provider unreachable")


@pytest.fixture
def provider_down(monkeypatch):
    monkeypatch.setattr(weather, "_client", lambda timeout: _DownClient())


def _payload():
    today = date(2026, 10, 26)
    past = [(today - timedelta(days=3 - i)).isoformat() for i in range(3)]
    future = [(today + timedelta(days=i + 1)).isoformat() for i in range(2)]
    return {
        "timezone": "Asia/Kolkata",
        "current": {
            "time": "2026-10-26T10:00",
            "temperature_2m": 28.4,
            "relative_humidity_2m": 71.0,
            "precipitation": 0.0,
            "rain": 0.0,
        },
        "daily": {
            "time": past + future,
            "precipitation_sum": [5.0, 5.0, 5.0, 1.0, 1.0],
            "rain_sum": [4.0, 4.0, 4.0, 0.5, 0.5],
        },
    }


@pytest.fixture
def provider_up(monkeypatch):
    monkeypatch.setattr(weather, "_client", lambda timeout: _FakeClient(_payload()))


# ─────────────────────────────────────────────────────────────────────────
# Success path — the three rainfall concepts stay separate
# ─────────────────────────────────────────────────────────────────────────

def test_current_observation_is_autofilled_from_now(app_client, provider_up):
    r = app_client.get("/api/weather/current", params={"lat": 19.07, "lon": 72.87})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["source"] == "Open-Meteo"
    assert body["current"]["label"] == "Current observation"
    assert body["current"]["temperature_c"] == 28.4
    assert body["current"]["humidity_pct"] == 71.0

    assert body["autofill"]["temperature"]["value"] == 28.4
    assert body["autofill"]["temperature"]["origin"] == "current observation"
    assert body["autofill"]["temperature"]["is_cumulative"] is False
    assert body["autofill"]["humidity"]["origin"] == "current observation"


def test_historical_and_forecast_rainfall_are_reported_separately(app_client, provider_up):
    body = app_client.get("/api/weather/current", params={"lat": 19.07, "lon": 72.87}).json()

    historical = body["historical_rainfall"]
    forecast = body["forecast_rainfall"]

    assert historical["total_mm"] == 15.0          # 3 past days x 5 mm
    assert historical["days"] == 3
    assert historical["label"] == "Historical rainfall (already fallen, cumulative)"
    assert forecast["total_mm"] == 2.0             # 2 coming days x 1 mm
    assert forecast["days"] == 2
    assert forecast["label"] == "Forecast rainfall (not yet fallen)"
    assert historical["label"] != forecast["label"]


def test_rainfall_autofill_uses_history_never_the_forecast(app_client, provider_up):
    body = app_client.get("/api/weather/current", params={"lat": 19.07, "lon": 72.87}).json()

    rainfall = body["autofill"]["rainfall"]
    assert rainfall["is_cumulative"] is True
    assert rainfall["origin"] == "historical accumulation"
    assert rainfall["value"] == 15.0, "current/forecast rain must not be used as seasonal rainfall"
    assert rainfall["value"] != body["forecast_rainfall"]["total_mm"]
    assert "note" in rainfall


# ─────────────────────────────────────────────────────────────────────────
# Failure paths — the app must stay usable
# ─────────────────────────────────────────────────────────────────────────

def test_provider_down_returns_503_with_a_manual_entry_hint(app_client, provider_down):
    r = app_client.get("/api/weather/current", params={"lat": 19.07, "lon": 72.87})
    assert r.status_code == 503, r.text
    body = r.json()
    assert "unavailable" in body["detail"].lower()
    assert "manual" in body["hint"].lower()


def test_geocoding_failure_returns_503(app_client, provider_down):
    r = app_client.get("/api/weather/current", params={"location": "Nashik"})
    assert r.status_code == 503, r.text
    assert "lookup service" in r.json()["detail"].lower()


def test_location_is_required(app_client, provider_down):
    r = app_client.get("/api/weather/current")
    assert r.status_code == 400
    assert "location" in r.json()["detail"].lower()


def test_unreadable_provider_response_returns_503(app_client, monkeypatch):
    class _NotJson:
        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("Expecting value: line 1 column 1")

    class _BadClient(_FakeClient):
        def get(self, url, params=None):
            return _NotJson()

    monkeypatch.setattr(weather, "_client", lambda timeout: _BadClient(None))
    r = app_client.get("/api/weather/current", params={"lat": 19.07, "lon": 72.87})
    assert r.status_code == 503
    assert "unreadable" in r.json()["detail"].lower()


def test_disabled_weather_returns_503(app_client, monkeypatch):
    monkeypatch.setenv("WEATHER_ENABLED", "false")
    get_settings.cache_clear()
    r = app_client.get("/api/weather/current", params={"lat": 19.07, "lon": 72.87})
    assert r.status_code == 503
    assert "disabled" in r.json()["detail"].lower()
