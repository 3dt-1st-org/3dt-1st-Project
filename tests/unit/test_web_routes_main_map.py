from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.frontend.web.app import create_app


@pytest.fixture()
def client():
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def test_api_places_event_and_ios_compatible_fields(client, monkeypatch):
    sample_place = {
        "id": "event-1",
        "name": "행사 샘플",
        "name_en": "Event Sample",
        "lat": 37.26,
        "lng": 127.02,
        "category": "event",
        "address": "경기도 수원시",
        "address_en": "Suwon-si, Gyeonggi-do",
        "region": "수원시",
        "region_en": "Suwon-si",
        "distance_m": 900,
        "image_url": "https://example.com/image.jpg",
        "is_approximate_location": True,
        "event_start_date": "2026-03-01",
        "event_end_date": "2026-03-30",
        "event_url": "https://example.com/event",
    }

    def _fake_places_payload(**_kwargs):
        return {
            "count": 1,
            "places": [sample_place],
            "scope": "city",
            "city": "수원시",
        }, 200

    monkeypatch.setattr(
        "src.frontend.web.routes.main_map.create_places_payload",
        _fake_places_payload,
    )

    response = client.get("/api/places?category=event&scope=city")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["count"] == 1
    assert payload["scope"] == "city"
    place = payload["places"][0]
    assert place["category"] == "event"
    assert place["name_en"] == "Event Sample"
    assert place["address_en"] == "Suwon-si, Gyeonggi-do"
    assert place["region_en"] == "Suwon-si"
    assert place["image_url"].startswith("https://")
    assert place["is_approximate_location"] is True
    assert place["event_start_date"] == "2026-03-01"
    assert place["event_end_date"] == "2026-03-30"
    assert place["event_url"] == "https://example.com/event"


def test_api_weather_returns_extended_shape(client, monkeypatch):
    def _fake_weather_payload(**_kwargs):
        return {
            "temp": "11",
            "icon": "⛅",
            "dust": {
                "pm10": "37",
                "pm25": "26",
                "grade": "normal",
                "grade_ko": "보통",
            },
            "forecast": [{"time": "2026-03-06T21:00", "temp": "8", "icon": "🌧️"}],
            "source": "open-meteo",
            "dust_source": "open-meteo",
        }, 200

    monkeypatch.setattr(
        "src.frontend.web.routes.main_map.create_weather_payload",
        _fake_weather_payload,
    )

    response = client.get("/api/weather")
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["temp"] == "11"
    assert payload["icon"] == "⛅"
    assert payload["dust"]["grade"] == "normal"
    assert isinstance(payload["forecast"], list)
    assert payload["source"] == "open-meteo"
    assert response.headers["Cache-Control"].startswith("private, max-age=")


def test_api_docent_script_returns_ios_shape(client, monkeypatch):
    def _fake_script_payload(_input):
        return {
            "place_id": "event-1",
            "category": "event",
            "language": "ko",
            "mode": "brief",
            "script": "안내 스크립트",
            "source": "llm",
            "generated_at": "2026-03-06T00:00:00+00:00",
            "ttl_sec": 604800,
        }, 200

    monkeypatch.setattr(
        "src.frontend.web.routes.main_map.create_docent_script_payload",
        _fake_script_payload,
    )

    response = client.post(
        "/api/docent/script",
        data=json.dumps(
            {
                "place_id": "event-1",
                "category": "event",
                "language": "ko",
                "mode": "brief",
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["place_id"] == "event-1"
    assert payload["script"] == "안내 스크립트"
    assert payload["source"] == "llm"


def test_api_docent_audio_returns_mpeg(client, monkeypatch):
    monkeypatch.setattr(
        "src.frontend.web.routes.main_map.create_docent_audio_payload",
        lambda _input: (b"fake-mp3", 200, "audio/mpeg"),
    )

    response = client.post(
        "/api/docent/audio",
        data=json.dumps({"script": "hello", "language": "en"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.mimetype == "audio/mpeg"
    assert response.data == b"fake-mp3"


def test_api_docent_audio_validation_error(client, monkeypatch):
    monkeypatch.setattr(
        "src.frontend.web.routes.main_map.create_docent_audio_payload",
        lambda _input: ({"error": "language must be ko|en"}, 400, "application/json"),
    )

    response = client.post(
        "/api/docent/audio",
        data=json.dumps({"script": "hello", "language": "ja"}),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "language must be ko|en"
