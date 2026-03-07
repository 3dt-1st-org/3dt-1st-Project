from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.frontend.web.routes import ios_api
from src.frontend.web.routes.ios_api import _normalize_place_row
from src.frontend.web.services.map_api_service import create_places_payload, create_weather_payload


def test_create_places_payload_invalid_category():
    payload, status = create_places_payload(
        lat=37.2,
        lng=127.0,
        radius=1000,
        category="invalid",
        scope="radius",
        city_hint="",
        limit=50,
    )

    assert status == 400
    assert payload["error"] == "category must be all|attraction|restaurant|event"


def test_create_places_payload_invalid_scope():
    payload, status = create_places_payload(
        lat=37.2,
        lng=127.0,
        radius=1000,
        category="all",
        scope="invalid",
        city_hint="",
        limit=50,
    )

    assert status == 400
    assert payload["error"] == "scope must be radius|city"


def test_create_places_payload_invalid_radius():
    payload, status = create_places_payload(
        lat=37.2,
        lng=127.0,
        radius=0,
        category="all",
        scope="radius",
        city_hint="",
        limit=50,
    )

    assert status == 400
    assert payload["error"] == "radius must be positive"


def test_normalize_place_row_promotes_id_to_place_id():
    place = _normalize_place_row(
        {
            "id": "attraction-1",
            "name": "수원화성",
            "category": "attraction",
        }
    )

    assert place["place_id"] == "attraction-1"
    assert place["name"] == "수원화성"


def test_create_weather_payload_caches_duplicate_requests(monkeypatch):
    ios_api._reset_weather_cache_for_tests()
    monkeypatch.setattr(ios_api, "_WEATHER_DB_ENABLED", False)
    calls = {"weather": 0, "air": 0}

    def _fake_weather(lat: float, lng: float):
        calls["weather"] += 1
        assert lat == 37.2
        assert lng == 127.0
        return {
            "current": {"temperature_2m": 11.4, "weather_code": 1},
            "hourly": {
                "time": ["2026-03-06T13:00"],
                "temperature_2m": [10.1],
                "weather_code": [1],
            },
        }

    def _fake_air(lat: float, lng: float):
        calls["air"] += 1
        assert lat == 37.2
        assert lng == 127.0
        return {"current": {"pm10": 31, "pm2_5": 16}}

    monkeypatch.setattr(ios_api, "_fetch_open_meteo_weather", _fake_weather)
    monkeypatch.setattr(ios_api, "_fetch_open_meteo_air_quality", _fake_air)

    first_payload, first_status = create_weather_payload(lat=37.2, lng=127.0)
    second_payload, second_status = create_weather_payload(lat=37.2, lng=127.0)

    assert first_status == 200
    assert second_status == 200
    assert first_payload == second_payload
    assert calls == {"weather": 1, "air": 1}


def test_create_weather_payload_reuses_stale_dust_when_air_quality_fails(monkeypatch):
    ios_api._reset_weather_cache_for_tests()
    monkeypatch.setattr(ios_api, "_WEATHER_DB_ENABLED", False)
    calls = {"weather": 0, "air": 0}

    def _fake_weather(lat: float, lng: float):
        calls["weather"] += 1
        return {
            "current": {"temperature_2m": 9.4 + calls["weather"], "weather_code": 1},
            "hourly": {
                "time": ["2026-03-06T13:00"],
                "temperature_2m": [8.4],
                "weather_code": [1],
            },
        }

    def _good_air(lat: float, lng: float):
        calls["air"] += 1
        return {"current": {"pm10": 41, "pm2_5": 21}}

    def _bad_air(lat: float, lng: float):
        calls["air"] += 1
        raise RuntimeError("air-quality-down")

    monkeypatch.setattr(ios_api, "_fetch_open_meteo_weather", _fake_weather)
    monkeypatch.setattr(ios_api, "_fetch_open_meteo_air_quality", _good_air)

    first_payload, first_status = create_weather_payload(lat=37.2, lng=127.0)
    assert first_status == 200
    assert first_payload["dust"]["grade"] == "normal"

    cache_key = ios_api._weather_cache_key(37.2, 127.0)
    ios_api._WEATHER_CACHE[cache_key]["stored_at"] -= ios_api._WEATHER_CACHE_TTL_SEC + 1

    monkeypatch.setattr(ios_api, "_fetch_open_meteo_air_quality", _bad_air)

    second_payload, second_status = create_weather_payload(lat=37.2, lng=127.0)

    assert second_status == 200
    assert second_payload["dust"]["pm10"] == "41"
    assert second_payload["dust"]["pm25"] == "21"
    assert second_payload["dust"]["grade"] == "normal"
    assert second_payload["dust_source"] == "stale-open-meteo"
    assert calls == {"weather": 2, "air": 2}
