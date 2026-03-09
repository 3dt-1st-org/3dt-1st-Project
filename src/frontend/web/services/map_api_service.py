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


def create_places_payload(
    *,
    lat: float,
    lng: float,
    radius: int,
    category: str,
    scope: str,
    city_hint: str,
    limit: int,
) -> tuple[dict[str, Any], int]:
    category = (category or "all").strip().lower()
    if category not in VALID_PLACE_CATEGORIES:
        return {"error": "category must be all|attraction|restaurant|event"}, 400

    scope = (scope or "radius").strip().lower()
    if scope not in VALID_PLACE_SCOPES:
        return {"error": "scope must be radius|city"}, 400

    if radius <= 0:
        return {"error": "radius must be positive"}, 400

    bounded_limit = min(max(limit, 1), MAX_LIMIT)

    # Avoid import-time cycle: ios_api imports this service for route handling.
    from src.frontend.web.routes import ios_api as ios_helpers

    try:
        if scope == "city":
            resolved_city = city_hint.strip()
            if not resolved_city:
                with get_db_connection() as conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                        resolved_city = (
                            ios_helpers._resolve_city_from_coordinate(
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

            places = ios_helpers._fetch_places_by_city(
                lat=lat,
                lng=lng,
                city=resolved_city,
                category=category,
                limit=bounded_limit,
            )
            return {
                "count": len(places),
                "places": places,
                "scope": "city",
                "city": resolved_city,
            }, 200

        places = ios_helpers._fetch_places(
            lat=lat,
            lng=lng,
            radius=radius,
            category=category,
            limit=bounded_limit,
        )
        return {
            "count": len(places),
            "places": places,
            "scope": "radius",
            "city": None,
        }, 200
    except Exception as exc:
        return {"error": str(exc)}, 500


def create_weather_payload(*, lat: float, lng: float, force: bool = False) -> tuple[dict[str, Any], int]:
    from src.frontend.web.routes import ios_api as ios_helpers

    return ios_helpers._weather_snapshot(lat=lat, lng=lng, force=force)
