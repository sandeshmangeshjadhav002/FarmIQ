"""Reverse-geocoding tests (device coordinates -> human-readable place label).

The upstream provider (Photon) is never contacted: ``app.weather._client`` is
replaced with an in-process fake, so the success path, the "no place found"
path and the provider-down path are all exercised deterministically.

This backs the farm form's "Use my current location" button. The coordinates
are the authoritative value the app stores; the label is only a convenience
that pre-fills the editable location field, so a failed lookup must never
discard the point the device already gave us.
"""
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
    """Stand-in for ``httpx.Client`` that returns a canned Photon payload."""

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


def _photon(props=None):
    """A Photon ``/reverse`` response for a farm near Nashik, Maharashtra."""
    if props is None:
        props = {
            "name": "Gangapur",
            "locality": "Gangapur",
            "district": "Nashik",
            "state": "Maharashtra",
            "country": "India",
            "postcode": "422001",
        }
    return {"type": "FeatureCollection", "features": [{"properties": props}]}


@pytest.fixture
def provider(monkeypatch):
    """Install a fake Photon client returning ``payload``."""

    def _install(payload):
        monkeypatch.setattr(weather, "_client", lambda timeout: _FakeClient(payload))

    return _install


@pytest.fixture
def provider_down(monkeypatch):
    monkeypatch.setattr(weather, "_client", lambda timeout: _DownClient())


# ─────────────────────────────────────────────────────────────────────────
# Unit level — the label builder
# ─────────────────────────────────────────────────────────────────────────

def test_place_label_prefers_settlement_and_drops_duplicates():
    # A village and its taluka often share a name; the label must not repeat it.
    label = weather._place_label(
        {
            "name": "Niphad",
            "locality": "Niphad",
            "district": "Niphad",
            "state": "Maharashtra",
            "country": "India",
        }
    )
    assert label == "Niphad, Maharashtra, India"


def test_place_label_is_empty_when_nothing_is_known():
    assert weather._place_label({}) == ""


# ─────────────────────────────────────────────────────────────────────────
# Unit level — reverse_geocode
# ─────────────────────────────────────────────────────────────────────────

def test_reverse_geocode_builds_a_readable_label(provider):
    provider(_photon())
    result = weather.reverse_geocode(19.9975, 73.7898)
    assert result["label"] == "Gangapur, Nashik, Maharashtra, India"
    assert result["village"] == "Gangapur"
    assert result["district"] == "Nashik"
    assert result["state"] == "Maharashtra"
    assert result["country"] == "India"
    assert result["postcode"] == "422001"


def test_reverse_geocode_echoes_the_requested_coordinates(provider):
    provider(_photon())
    result = weather.reverse_geocode(19.9975, 73.7898)
    # The device's point is what the farm stores — it must survive the lookup.
    assert result["latitude"] == 19.9975
    assert result["longitude"] == 73.7898


def test_reverse_geocode_returns_the_provider_attribution(provider):
    provider(_photon())
    # ODbL requires crediting the source; the frontend displays this string.
    assert "Photon" in weather.reverse_geocode(19.9975, 73.7898)["source"]
    assert "OpenStreetMap" in weather.reverse_geocode(19.9975, 73.7898)["source"]


def test_reverse_geocode_no_results_is_404(provider):
    provider({"features": []})
    with pytest.raises(Exception) as exc:
        weather.reverse_geocode(0.0, 0.0)
    assert getattr(exc.value, "status_code", None) == 404


def test_reverse_geocode_unusable_place_is_404(provider):
    # Photon can return a feature whose properties carry no usable name.
    provider(_photon(props={"osm_id": 123, "osm_type": "node"}))
    with pytest.raises(Exception) as exc:
        weather.reverse_geocode(19.9975, 73.7898)
    assert getattr(exc.value, "status_code", None) == 404


def test_reverse_geocode_provider_down_is_503_with_a_hint(provider_down):
    with pytest.raises(weather.WeatherUnavailableError) as exc:
        weather.reverse_geocode(19.9975, 73.7898)
    assert exc.value.status_code == 503
    # The message must reassure the farmer the point is not lost.
    assert "coordinates are still saved" in exc.value.detail
    assert exc.value.extra.get("hint")


def test_reverse_geocode_unreadable_response_is_503(monkeypatch):
    class _NotJson:
        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("Expecting value: line 1 column 1")

    class _BadClient(_FakeClient):
        def get(self, url, params=None):
            return _NotJson()

    monkeypatch.setattr(weather, "_client", lambda timeout: _BadClient(None))
    with pytest.raises(weather.WeatherUnavailableError) as exc:
        weather.reverse_geocode(19.9975, 73.7898)
    assert "unreadable" in exc.value.detail.lower()


# ─────────────────────────────────────────────────────────────────────────
# Endpoint — GET /api/weather/reverse
# ─────────────────────────────────────────────────────────────────────────

def test_reverse_endpoint_returns_the_label(app_client, provider):
    provider(_photon())
    r = app_client.get("/api/weather/reverse", params={"lat": 19.9975, "lon": 73.7898})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["label"] == "Gangapur, Nashik, Maharashtra, India"
    assert body["latitude"] == 19.9975
    assert body["longitude"] == 73.7898
    assert body["source"]


def test_reverse_endpoint_rejects_out_of_range_latitude(app_client, provider):
    provider(_photon())
    r = app_client.get("/api/weather/reverse", params={"lat": 123.0, "lon": 73.0})
    assert r.status_code == 422


def test_reverse_endpoint_rejects_out_of_range_longitude(app_client, provider):
    provider(_photon())
    r = app_client.get("/api/weather/reverse", params={"lat": 19.0, "lon": -181.0})
    assert r.status_code == 422


def test_reverse_endpoint_requires_both_coordinates(app_client, provider):
    provider(_photon())
    assert app_client.get("/api/weather/reverse", params={"lat": 19.0}).status_code == 422
    assert app_client.get("/api/weather/reverse").status_code == 422


def test_reverse_endpoint_unreachable_provider_is_503(app_client, provider_down):
    r = app_client.get("/api/weather/reverse", params={"lat": 19.9975, "lon": 73.7898})
    assert r.status_code == 503, r.text
    assert "coordinates are still saved" in r.json()["detail"]


def test_reverse_endpoint_unknown_place_is_404(app_client, provider):
    provider({"features": []})
    r = app_client.get("/api/weather/reverse", params={"lat": 0.0, "lon": 0.0})
    assert r.status_code == 404


def test_reverse_endpoint_disabled_is_503(app_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "weather_enabled", False)
    r = app_client.get("/api/weather/reverse", params={"lat": 19.9975, "lon": 73.7898})
    assert r.status_code == 503
    assert "disabled" in r.json()["detail"].lower()
