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


def test_api_places_event_name_en_uses_title_en(client, monkeypatch):
    """행사 장소의 name_en 필드가 title_en(영문 번역) 값을 우선하여 반환해야 한다."""
    sample_event_with_translation = {
        "id": "event-translated",
        "name": "경기 벚꽃 축제",
        "name_en": "Gyeonggi Cherry Blossom Festival",
        "lat": 37.26,
        "lng": 127.02,
        "category": "event",
        "address": "경기도 수원시",
        "address_en": "Suwon-si, Gyeonggi-do",
        "region": "수원시",
        "region_en": "Suwon-si",
        "distance_m": 500,
        "image_url": None,
        "is_approximate_location": False,
        "event_start_date": "2026-03-15",
        "event_end_date": "2026-03-31",
        "event_url": "https://example.com/cherry",
        "is_ongoing": True,
    }

    def _fake_places_payload(**_kwargs):
        return {"count": 1, "places": [sample_event_with_translation], "scope": "city", "city": "수원시"}, 200

    monkeypatch.setattr(
        "src.frontend.web.routes.main_map.create_places_payload",
        _fake_places_payload,
    )

    response = client.get("/api/places?category=event&scope=city")
    assert response.status_code == 200
    payload = response.get_json()
    place = payload["places"][0]

    # name_en은 영어 번역 제목이어야 한다 (한국어 name과 달라야 함)
    assert place["name"] == "경기 벚꽃 축제"
    assert place["name_en"] == "Gyeonggi Cherry Blossom Festival"
    assert place["name_en"] != place["name"]


def test_api_places_event_name_en_falls_back_to_name(client, monkeypatch):
    """title_en이 없는 행사는 name_en이 name(한국어 제목)과 동일해야 한다."""
    sample_event_no_translation = {
        "id": "event-no-translation",
        "name": "미번역 행사",
        "name_en": "미번역 행사",
        "lat": 37.26,
        "lng": 127.02,
        "category": "event",
        "address": "경기도",
        "address_en": "Gyeonggi-do",
        "region": "수원시",
        "region_en": "Suwon-si",
        "distance_m": 1200,
        "image_url": None,
        "is_approximate_location": True,
        "event_start_date": None,
        "event_end_date": None,
        "event_url": "",
        "is_ongoing": True,
    }

    def _fake_places_payload(**_kwargs):
        return {"count": 1, "places": [sample_event_no_translation], "scope": "city", "city": "수원시"}, 200

    monkeypatch.setattr(
        "src.frontend.web.routes.main_map.create_places_payload",
        _fake_places_payload,
    )

    response = client.get("/api/places?category=event&scope=city")
    assert response.status_code == 200
    place = response.get_json()["places"][0]

    # title_en이 없으면 name_en은 name과 동일해도 됨 (한국어 fallback)
    assert place["name_en"] is not None
    assert place["name_en"] == place["name"]


# ---------------------------------------------------------------------------
# Tour docent language priority tests
# ---------------------------------------------------------------------------

def test_tour_docent_client_language_overrides_session(client, monkeypatch):
    """JS에서 보낸 language 값이 Flask session["lang"] 보다 우선해야 한다.

    재현 시나리오:
    - 사용자가 영어로 전환 → session["lang"] = "en"
    - 사용자가 한국어로 전환 → localStorage = "ko", 하지만 session이 아직 "en"일 수 있음
    - JS가 language="ko" 를 페이로드에 담아 전송할 때 "ko" 가 사용돼야 함
    """
    received_language = {}

    def _fake_tour_payload(payload):
        received_language["lang"] = payload.get("language")
        return {"restaurant_names": ["맛집A"], "script": "대본", "source": "llm", "language": payload.get("language")}, 200, "application/json"

    monkeypatch.setattr(
        "src.frontend.web.routes.main_map.create_tour_docent_payload",
        _fake_tour_payload,
    )

    with client.session_transaction() as sess:
        sess["lang"] = "en"  # 세션은 영어로 남아있음

    response = client.post(
        "/api/docent/tour",
        json={"lat": 37.5, "lng": 127.0, "language": "ko"},  # JS는 한국어 전송
        content_type="application/json",
    )
    assert response.status_code == 200
    assert received_language["lang"] == "ko", (
        "Client-sent language='ko' should take priority over session lang='en'"
    )


def test_tour_docent_session_lang_used_as_fallback(client, monkeypatch):
    """language 미전송 시 session["lang"]이 fallback으로 사용돼야 한다."""
    received_language = {}

    def _fake_tour_payload(payload):
        received_language["lang"] = payload.get("language")
        return {"restaurant_names": ["맛집A"], "script": "script", "source": "llm", "language": payload.get("language")}, 200, "application/json"

    monkeypatch.setattr(
        "src.frontend.web.routes.main_map.create_tour_docent_payload",
        _fake_tour_payload,
    )

    with client.session_transaction() as sess:
        sess["lang"] = "en"

    response = client.post(
        "/api/docent/tour",
        json={"lat": 37.5, "lng": 127.0},  # language 미전송
        content_type="application/json",
    )
    assert response.status_code == 200
    assert received_language["lang"] == "en", (
        "Session lang should be used as fallback when client does not send language"
    )

