from __future__ import annotations

from flask import Blueprint, Response, jsonify, render_template, request

from src.frontend.web.services.docent_api_service import (
    create_docent_audio_payload,
    create_docent_script_payload,
    create_tour_docent_payload,
)
from src.frontend.web.services.map_api_service import (
    DEFAULT_LAT,
    DEFAULT_LNG,
    DEFAULT_LIMIT,
    DEFAULT_RADIUS,
    create_places_payload,
    create_weather_payload,
)
from src.frontend.web.routes.ios_api import _WEATHER_HTTP_CACHE_CONTROL

main_map_bp = Blueprint("main_map", __name__)


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


@main_map_bp.route("/map")
def map_view():
    return render_template("map/index.html")


@main_map_bp.route("/api/weather")
def api_weather():
    try:
        lat = _parse_float_arg("lat", DEFAULT_LAT)
        lng = _parse_float_arg("lng", DEFAULT_LNG)
    except ValueError:
        return jsonify({"error": "잘못된 파라미터"}), 400

    payload, status_code = create_weather_payload(lat=lat, lng=lng)
    return jsonify(payload), status_code, {"Cache-Control": _WEATHER_HTTP_CACHE_CONTROL}


@main_map_bp.route("/api/places")
def api_places():
    try:
        lat = _parse_float_arg("lat", DEFAULT_LAT)
        lng = _parse_float_arg("lng", DEFAULT_LNG)
        radius = _parse_int_arg("radius", DEFAULT_RADIUS)
        limit = _parse_int_arg("limit", DEFAULT_LIMIT)
    except ValueError:
        return jsonify({"error": "잘못된 파라미터"}), 400

    payload, status_code = create_places_payload(
        lat=lat,
        lng=lng,
        radius=radius,
        category=(request.args.get("category", "all") or "all"),
        scope=(request.args.get("scope", "radius") or "radius"),
        city_hint=str(request.args.get("city") or ""),
        limit=limit,
    )
    return jsonify(payload), status_code


@main_map_bp.route("/api/docent/script", methods=["POST"])
def api_docent_script():
    payload = request.get_json(silent=True) or {}
    response_payload, status_code = create_docent_script_payload(payload)
    return jsonify(response_payload), status_code


@main_map_bp.route("/api/docent/audio", methods=["POST"])
def api_docent_audio():
    payload = request.get_json(silent=True) or {}
    response_payload, status_code, mime_type = create_docent_audio_payload(payload)
    if mime_type == "audio/mpeg":
        return Response(response_payload, mimetype=mime_type, status=status_code)
    return jsonify(response_payload), status_code


@main_map_bp.route("/api/docent/tour", methods=["POST"])
def api_docent_tour():
    payload = request.get_json(silent=True) or {}
    response_payload, status_code, mime_type = create_tour_docent_payload(payload)
    if mime_type == "audio/mpeg":
        return Response(response_payload, mimetype=mime_type, status=status_code)
    return jsonify(response_payload), status_code
