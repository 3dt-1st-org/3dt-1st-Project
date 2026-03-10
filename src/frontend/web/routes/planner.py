from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from src.frontend.web.services.planner_service import (
    create_daily_plan_payload,
    create_intervention_payload,
)

planner_bp = Blueprint("planner", __name__)


@planner_bp.route("/api/planner/daily-plan", methods=["POST"])
def daily_plan():
    body = request.get_json(silent=True) or {}
    try:
        lat = float(body.get("lat", 37.2636))
        lng = float(body.get("lng", 127.0286))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid parameters"}), 400

    client_lang = str(body.get("language") or "").strip().lower()
    session_lang = str(session.get("lang") or "").strip().lower()
    effective_lang = client_lang if client_lang in ("ko", "en") else session_lang
    if effective_lang not in ("ko", "en"):
        effective_lang = "ko"

    language = "English" if effective_lang == "en" else "Korean"

    payload, status = create_daily_plan_payload(lat, lng, language=language)
    return jsonify(payload), status


@planner_bp.route("/api/planner/intervention", methods=["GET"])
def intervention():
    try:
        lat = float(request.args.get("lat", 37.2636))
        lng = float(request.args.get("lng", 127.0286))
        radius = int(request.args.get("radius", 10000))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid parameters"}), 400

    payload, status = create_intervention_payload(lat, lng, radius_m=radius)
    return jsonify(payload), status
