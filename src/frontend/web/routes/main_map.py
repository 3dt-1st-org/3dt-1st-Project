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

    force = request.args.get("force") == "1"
    payload, status_code = create_weather_payload(lat=lat, lng=lng, force=force)
    cache_header = "no-store" if force else _WEATHER_HTTP_CACHE_CONTROL
    return jsonify(payload), status_code, {"Cache-Control": cache_header}


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
    from flask import session
    payload = request.get_json(silent=True) or {}
    # 클라이언트가 보낸 언어를 우선 사용하고, 없을 때만 서버 세션 값으로 보완
    # (session 우선 로직은 세션이 stale 상태일 때 잘못된 언어로 고정되는 문제를 유발)
    client_lang = str(payload.get("language") or "").strip().lower()
    if client_lang not in ("ko", "en"):
        session_lang = session.get("lang", "").strip().lower()
        if session_lang in ("ko", "en"):
            payload["language"] = session_lang
    response_payload, status_code, mime_type = create_tour_docent_payload(payload)
    if mime_type == "audio/mpeg":
        return Response(response_payload, mimetype=mime_type, status=status_code)
    return jsonify(response_payload), status_code
