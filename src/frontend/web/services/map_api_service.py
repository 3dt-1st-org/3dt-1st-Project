from __future__ import annotations

from typing import Any

import psycopg2.extras

from src.frontend.web.services.db import get_db_connection

DEFAULT_LAT = 37.2636
DEFAULT_LNG = 127.0286
DEFAULT_RADIUS = 10000
DEFAULT_LIMIT = 50
MAX_LIMIT = 100

VALID_PLACE_CATEGORIES = {"all", "attraction", "restaurant", "event"}
VALID_PLACE_SCOPES = {"radius", "city"}


VALID_PLACE_LANGUAGES = {"ko", "en"}


def _apply_language(places: list[dict[str, Any]], language: str) -> None:
    """language='en'이면 각 place의 name/address 필드를 영어 값으로 교체 (in-place).
    한국어 원본은 name_ko로 보존하여 JS에서 restaurant_names(bizplc_nm) 매칭에 사용할 수 있도록 한다.
    """
    if language != "en":
        return
    for place in places:
        if place.get("name_en"):
            place["name_ko"] = place["name"]  # 한국어 원본 보존 (restaurant_names lookup용)
            place["name"] = place["name_en"]
        if place.get("address_en"):
            place["address"] = place["address_en"]


def create_places_payload(
    *,
    lat: float,
    lng: float,
    radius: int,
    category: str,
    scope: str,
    city_hint: str,
    limit: int,
    language: str = "ko",
) -> tuple[dict[str, Any], int]:
    category = (category or "all").strip().lower()
    if category not in VALID_PLACE_CATEGORIES:
        return {"error": "category must be all|attraction|restaurant|event"}, 400

    scope = (scope or "radius").strip().lower()
    if scope not in VALID_PLACE_SCOPES:
        return {"error": "scope must be radius|city"}, 400

    if radius <= 0:
        return {"error": "radius must be positive"}, 400

    language = (language or "ko").strip().lower()
    if language not in VALID_PLACE_LANGUAGES:
        language = "ko"

    bounded_limit = min(max(limit, 1), MAX_LIMIT)

    # Avoid import-time cycle: map_data_api uses this service for route handling.
    from src.frontend.web.routes import map_data_api as map_helpers

    try:
        if scope == "city":
            resolved_city = city_hint.strip()
            if not resolved_city:
                with get_db_connection() as conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                        resolved_city = (
                            map_helpers._resolve_city_from_coordinate(
                                cursor=cursor,
                                lat=lat,
                                lng=lng,
                            )
                            or ""
                        )

            if not resolved_city:
                return {
                    "count": 0,
                    "places": [],
                    "scope": "city",
                    "city": None,
                }, 200

            places = map_helpers._fetch_places_by_city(
                lat=lat,
                lng=lng,
                city=resolved_city,
                category=category,
                limit=bounded_limit,
            )
            _apply_language(places, language)
            return {
                "count": len(places),
                "places": places,
                "scope": "city",
                "city": resolved_city,
            }, 200

        places = map_helpers._fetch_places(
            lat=lat,
            lng=lng,
            radius=radius,
            category=category,
            limit=bounded_limit,
        )
        _apply_language(places, language)
        return {
            "count": len(places),
            "places": places,
            "scope": "radius",
            "city": None,
        }, 200
    except Exception as exc:
        return {"error": str(exc)}, 500


def create_weather_payload(*, lat: float, lng: float, force: bool = False) -> tuple[dict[str, Any], int]:
    from src.frontend.web.routes import map_data_api as map_helpers

    return map_helpers._weather_snapshot(lat=lat, lng=lng, force=force)
