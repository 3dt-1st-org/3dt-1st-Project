from __future__ import annotations

import hmac
import math
import os
from datetime import datetime, timedelta
from functools import wraps

import psycopg2.extras
import requests as http_requests
from flask import Blueprint, Response, jsonify, request

from src.frontend.web.services.db import get_db_connection
from src.frontend.web.services.docent_service import generate_docent_script
from src.frontend.web.services.speech_service import SpeechSynthesisError, synthesize_speech_mp3


ios_api_bp = Blueprint("ios_api", __name__)

_DEFAULT_LAT = 37.2636
_DEFAULT_LNG = 127.0286
_DEFAULT_RADIUS = 3000
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 100

_RE, _GRID = 6371.00877, 5.0
_SLAT1, _SLAT2, _OLON, _OLAT, _XO, _YO = 30.0, 60.0, 126.0, 38.0, 43, 136

_PTY_ICON = {
    "0": "☀️",
    "1": "🌧️",
    "2": "🌨️",
    "3": "❄️",
    "5": "🌦️",
    "6": "🌨️",
    "7": "🌨️",
}

_WEATHER_API_URL = (
    "http://apis.data.go.kr/1360000/"
    "VilageFcstInfoService_2.0/getUltraSrtNcst"
)


_VALID_PLACE_CATEGORIES = {"all", "attraction", "restaurant", "event"}
_VALID_DOCENT_CATEGORIES = {"attraction", "restaurant", "event"}
_VALID_LANGUAGES = {"ko", "en"}
_VALID_MODES = {"brief", "detail"}


def _latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    degrad = math.pi / 180.0
    re_val = _RE / _GRID
    slat1 = _SLAT1 * degrad
    slat2 = _SLAT2 * degrad
    olon = _OLON * degrad
    olat = _OLAT * degrad
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(
        math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    )
    sf = (math.tan(math.pi * 0.25 + slat1 * 0.5) ** sn) * math.cos(slat1) / sn
    ro = re_val * sf / (math.tan(math.pi * 0.25 + olat * 0.5) ** sn)
    ra = re_val * sf / (math.tan(math.pi * 0.25 + lat * degrad * 0.5) ** sn)
    theta = (lon * degrad - olon) * sn
    if theta > math.pi:
        theta -= 2 * math.pi
    if theta < -math.pi:
        theta += 2 * math.pi
    return int(ra * math.sin(theta) + _XO + 0.5), int(ro - ra * math.cos(theta) + _YO + 0.5)


def _require_api_key(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        expected = (os.getenv("IOS_API_KEY") or "").strip()
        if not expected:
            return jsonify({"error": "IOS_API_KEY is not configured"}), 503

        provided = (request.headers.get("X-API-Key") or "").strip()
        if not provided or not hmac.compare_digest(provided, expected):
            return jsonify({"error": "unauthorized"}), 401

        return fn(*args, **kwargs)

    return wrapped


def _parse_float_arg(name: str, default: float) -> float:
    raw = request.args.get(name)
    if raw is None:
        return default
    return float(raw)


def _parse_int_arg(name: str, default: int) -> int:
    raw = request.args.get(name)
    if raw is None:
        return default
    return int(raw)


def _weather_snapshot(lat: float, lng: float) -> tuple[dict[str, str], int]:
    weather_api_key = (os.getenv("WEATHER_API_KEY") or "").strip()
    if not weather_api_key:
        return {"error": "WEATHER_API_KEY is not configured"}, 503

    now = datetime.now() - timedelta(hours=1)
    base_date = now.strftime("%Y%m%d")
    base_time = now.strftime("%H00")
    nx, ny = _latlon_to_grid(lat, lng)

    try:
        response = http_requests.get(
            _WEATHER_API_URL,
            params={
                "pageNo": "1",
                "numOfRows": "20",
                "dataType": "JSON",
                "base_date": base_date,
                "base_time": base_time,
                "nx": nx,
                "ny": ny,
                "serviceKey": weather_api_key,
            },
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()

        header = payload["response"]["header"]
        if header["resultCode"] != "00":
            return {"error": header["resultMsg"]}, 502

        items = payload["response"]["body"]["items"]["item"]
        values = {item["category"]: item["obsrValue"] for item in items}
        temp = values.get("T1H", "--")
        pty = values.get("PTY", "0")
        icon = _PTY_ICON.get(str(int(float(pty))), "🌡️")
        return {"temp": str(temp), "icon": icon}, 200
    except Exception as exc:
        return {"error": str(exc)}, 500


def _fetch_places(lat: float, lng: float, radius: int, category: str, limit: int) -> list[dict]:
    results: list[dict] = []

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            if category in {"all", "attraction"}:
                cursor.execute(
                    """
                    WITH city_centers AS (
                        SELECT
                            COALESCE(sigun_nm, '') AS city_name,
                            AVG(refine_wgs84_lat::FLOAT) AS center_lat,
                            AVG(refine_wgs84_logt::FLOAT) AS center_lng
                        FROM locallink.gg_restaurant_info
                        WHERE refine_wgs84_lat IS NOT NULL
                          AND refine_wgs84_logt IS NOT NULL
                          AND refine_wgs84_lat::TEXT <> 'NaN'
                          AND refine_wgs84_logt::TEXT <> 'NaN'
                          AND COALESCE(TRIM(sigun_nm), '') <> ''
                          AND bsn_state_nm = '영업'
                        GROUP BY COALESCE(sigun_nm, '')
                    )
                    SELECT
                        MD5(COALESCE(ad.attraction_name, '') || '|' || COALESCE(ad.sigun_nm, '')) AS id,
                        COALESCE(ad.attraction_name, '관광지') AS name,
                        COALESCE(cc.center_lat, %s) AS lat,
                        COALESCE(cc.center_lng, %s) AS lng,
                        'attraction' AS category,
                        '' AS address,
                        COALESCE(ad.sigun_nm, '') AS region,
                        ROUND(
                            ST_Distance(
                                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                                ST_SetSRID(
                                    ST_MakePoint(COALESCE(cc.center_lng, %s), COALESCE(cc.center_lat, %s)),
                                    4326
                                )::geography
                            )::NUMERIC,
                            0
                        )::INT AS distance_m,
                        NULL::TEXT AS image_url,
                        TRUE AS is_approximate_location,
                        NULL::TEXT AS event_start_date,
                        NULL::TEXT AS event_end_date,
                        NULL::TEXT AS event_url
                    FROM locallink.attraction_descriptions ad
                    LEFT JOIN city_centers cc
                      ON cc.city_name = COALESCE(ad.sigun_nm, '')
                    WHERE COALESCE(TRIM(ad.attraction_name), '') <> ''
                      AND ST_DWithin(
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                        ST_SetSRID(
                            ST_MakePoint(COALESCE(cc.center_lng, %s), COALESCE(cc.center_lat, %s)),
                            4326
                        )::geography,
                        %s
                      )
                    ORDER BY distance_m
                    LIMIT %s
                    """,
                    (
                        _DEFAULT_LAT,
                        _DEFAULT_LNG,
                        lng,
                        lat,
                        _DEFAULT_LNG,
                        _DEFAULT_LAT,
                        lng,
                        lat,
                        _DEFAULT_LNG,
                        _DEFAULT_LAT,
                        radius,
                        limit,
                    ),
                )
                results.extend(dict(row) for row in cursor.fetchall())

            if category in {"all", "restaurant"}:
                cursor.execute(
                    """
                    SELECT
                        MD5(bizplc_nm || COALESCE(refine_roadnm_addr, '')) AS id,
                        bizplc_nm AS name,
                        refine_wgs84_lat::FLOAT AS lat,
                        refine_wgs84_logt::FLOAT AS lng,
                        'restaurant' AS category,
                        COALESCE(refine_roadnm_addr, refine_lotno_addr, '') AS address,
                        COALESCE(sigun_nm, '') AS region,
                        ROUND(
                            ST_Distance(
                                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                                ST_SetSRID(
                                    ST_MakePoint(refine_wgs84_logt::FLOAT, refine_wgs84_lat::FLOAT),
                                    4326
                                )::geography
                            )::NUMERIC,
                            0
                        )::INT AS distance_m,
                        NULL::TEXT AS image_url,
                        FALSE AS is_approximate_location,
                        NULL::TEXT AS event_start_date,
                        NULL::TEXT AS event_end_date,
                        NULL::TEXT AS event_url
                    FROM locallink.gg_restaurant_info
                    WHERE refine_wgs84_lat IS NOT NULL
                      AND refine_wgs84_logt IS NOT NULL
                      AND refine_wgs84_lat::TEXT <> 'NaN'
                      AND refine_wgs84_logt::TEXT <> 'NaN'
                      AND bsn_state_nm = '영업'
                      AND ST_DWithin(
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                        ST_SetSRID(
                            ST_MakePoint(refine_wgs84_logt::FLOAT, refine_wgs84_lat::FLOAT),
                            4326
                        )::geography,
                        %s
                      )
                    ORDER BY distance_m
                    LIMIT %s
                    """,
                    (lng, lat, lng, lat, radius, limit),
                )
                results.extend(dict(row) for row in cursor.fetchall())

            if category in {"all", "event"}:
                cursor.execute(
                    """
                    WITH city_centers AS (
                        SELECT
                            COALESCE(sigun_nm, '') AS city_name,
                            AVG(refine_wgs84_lat::FLOAT) AS center_lat,
                            AVG(refine_wgs84_logt::FLOAT) AS center_lng
                        FROM locallink.gg_restaurant_info
                        WHERE refine_wgs84_lat IS NOT NULL
                          AND refine_wgs84_logt IS NOT NULL
                          AND refine_wgs84_lat::TEXT <> 'NaN'
                          AND refine_wgs84_logt::TEXT <> 'NaN'
                          AND COALESCE(TRIM(sigun_nm), '') <> ''
                          AND bsn_state_nm = '영업'
                        GROUP BY COALESCE(sigun_nm, '')
                    ),
                    normalized_events AS (
                        SELECT
                            MD5(COALESCE(title, '') || '|' || COALESCE(url, '') || '|' || COALESCE(city, '')) AS id,
                            COALESCE(title, '') AS name,
                            COALESCE(inst_nm, '') AS address,
                            COALESCE(city, '') AS region,
                            COALESCE(url, '') AS event_url,
                            CASE
                                WHEN begin_de ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN begin_de::DATE
                                ELSE NULL
                            END AS event_start_date,
                            CASE
                                WHEN end_de ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN end_de::DATE
                                ELSE NULL
                            END AS event_end_date
                        FROM locallink.gyeonggi_events
                        WHERE COALESCE(TRIM(title), '') <> ''
                          AND COALESCE(TRIM(city), '') <> ''
                    )
                    SELECT
                        ne.id,
                        ne.name,
                        COALESCE(cc.center_lat, %s) AS lat,
                        COALESCE(cc.center_lng, %s) AS lng,
                        'event' AS category,
                        ne.address,
                        ne.region,
                        ROUND(
                            ST_Distance(
                                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                                ST_SetSRID(
                                    ST_MakePoint(COALESCE(cc.center_lng, %s), COALESCE(cc.center_lat, %s)),
                                    4326
                                )::geography
                            )::NUMERIC,
                            0
                        )::INT AS distance_m,
                        NULL::TEXT AS image_url,
                        TRUE AS is_approximate_location,
                        ne.event_start_date::TEXT AS event_start_date,
                        ne.event_end_date::TEXT AS event_end_date,
                        ne.event_url
                    FROM normalized_events ne
                    LEFT JOIN city_centers cc
                      ON cc.city_name = ne.region
                    WHERE (ne.event_end_date IS NULL OR ne.event_end_date >= CURRENT_DATE)
                      AND ST_DWithin(
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                        ST_SetSRID(
                            ST_MakePoint(COALESCE(cc.center_lng, %s), COALESCE(cc.center_lat, %s)),
                            4326
                        )::geography,
                        %s
                      )
                    ORDER BY distance_m
                    LIMIT %s
                    """,
                    (
                        _DEFAULT_LAT,
                        _DEFAULT_LNG,
                        lng,
                        lat,
                        _DEFAULT_LNG,
                        _DEFAULT_LAT,
                        lng,
                        lat,
                        _DEFAULT_LNG,
                        _DEFAULT_LAT,
                        radius,
                        limit,
                    ),
                )
                results.extend(dict(row) for row in cursor.fetchall())

    results.sort(key=lambda row: row.get("distance_m") or 0)
    return results[: max(limit, 1)]


@ios_api_bp.route("/api/ios/v1/places", methods=["GET"])
@_require_api_key
def api_ios_places():
    try:
        lat = _parse_float_arg("lat", _DEFAULT_LAT)
        lng = _parse_float_arg("lng", _DEFAULT_LNG)
        radius = _parse_int_arg("radius", _DEFAULT_RADIUS)
        limit = _parse_int_arg("limit", _DEFAULT_LIMIT)
    except ValueError:
        return jsonify({"error": "invalid numeric query params"}), 400

    category = (request.args.get("category", "all") or "all").strip().lower()
    if category not in _VALID_PLACE_CATEGORIES:
        return jsonify({"error": "category must be all|attraction|restaurant|event"}), 400

    if radius <= 0:
        return jsonify({"error": "radius must be positive"}), 400

    limit = min(max(limit, 1), _MAX_LIMIT)

    try:
        places = _fetch_places(lat=lat, lng=lng, radius=radius, category=category, limit=limit)
        return jsonify({"count": len(places), "places": places})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@ios_api_bp.route("/api/ios/v1/weather", methods=["GET"])
@_require_api_key
def api_ios_weather():
    try:
        lat = _parse_float_arg("lat", _DEFAULT_LAT)
        lng = _parse_float_arg("lng", _DEFAULT_LNG)
    except ValueError:
        return jsonify({"error": "invalid numeric query params"}), 400

    payload, status_code = _weather_snapshot(lat=lat, lng=lng)
    return jsonify(payload), status_code


@ios_api_bp.route("/api/ios/v1/docent/script", methods=["POST"])
@_require_api_key
def api_ios_docent_script():
    payload = request.get_json(silent=True) or {}

    place_id = str(payload.get("place_id") or "").strip()
    category = str(payload.get("category") or "").strip().lower()
    language = str(payload.get("language") or "ko").strip().lower()
    mode = str(payload.get("mode") or "brief").strip().lower()

    if category not in _VALID_DOCENT_CATEGORIES:
        return jsonify({"error": "category must be attraction|restaurant|event"}), 400
    if language not in _VALID_LANGUAGES:
        return jsonify({"error": "language must be ko|en"}), 400
    if mode not in _VALID_MODES:
        return jsonify({"error": "mode must be brief|detail"}), 400

    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                result = generate_docent_script(
                    cursor=cursor,
                    place_id=place_id,
                    category=category,
                    language=language,
                    mode=mode,
                )
            conn.commit()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify(
        {
            "place_id": result.place_id,
            "category": result.category,
            "language": result.language,
            "mode": result.mode,
            "script": result.script,
            "source": result.source,
            "generated_at": result.generated_at,
            "ttl_sec": result.ttl_sec,
        }
    )


@ios_api_bp.route("/api/ios/v1/docent/audio", methods=["POST"])
@_require_api_key
def api_ios_docent_audio():
    payload = request.get_json(silent=True) or {}

    script = str(payload.get("script") or "").strip()
    language = str(payload.get("language") or "ko").strip().lower()

    if language not in _VALID_LANGUAGES:
        return jsonify({"error": "language must be ko|en"}), 400

    try:
        audio_bytes = synthesize_speech_mp3(script=script, language=language)
    except SpeechSynthesisError as exc:
        return jsonify({"error": str(exc)}), exc.status_code
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return Response(audio_bytes, mimetype="audio/mpeg")


@ios_api_bp.route("/api/ios/v1/health", methods=["GET"])
@_require_api_key
def api_ios_health():
    db_status = "ok"
    speech_status = "ok"
    openai_status = "ok"

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
    except Exception:
        db_status = "error"

    if not (os.getenv("AZURE_SPEECH_KEY") and os.getenv("AZURE_SPEECH_REGION")):
        speech_status = "missing_config"

    if not (
        os.getenv("AZURE_OPENAI_ENDPOINT")
        and os.getenv("AZURE_OPENAI_KEY")
        and os.getenv("AZURE_OPENAI_VERSION")
        and (os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or os.getenv("AZURE_OPENAI_DEPLOYMENT"))
    ):
        openai_status = "missing_config"

    status = "ok"
    if any(value != "ok" for value in (db_status, speech_status, openai_status)):
        status = "degraded"

    return jsonify(
        {
            "status": status,
            "db": db_status,
            "speech": speech_status,
            "openai": openai_status,
        }
    )
