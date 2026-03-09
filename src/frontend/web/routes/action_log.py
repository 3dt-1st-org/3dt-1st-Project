from __future__ import annotations

import logging
import re

from flask import Blueprint, jsonify, request

from src.frontend.web.services.db import get_db_connection

action_log_bp = Blueprint("action_log", __name__)

# 허용 action_type 목록 — 정의되지 않은 값은 거부
_ALLOWED_ACTIONS = frozenset({
    "click_place_card",
    "click_tour_guide",
    "click_daily_plan",
    "click_docent_detail",
    "click_category_filter",
    "click_weather",
})

_SESSION_ID_RE = re.compile(r"^[0-9a-f\-]{32,36}$", re.IGNORECASE)


def _parse_float(value) -> float | None:
    """None 또는 유효하지 않은 값은 None으로 변환."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if -90 <= f <= 180 else None  # 위/경도 범위 기본 유효성


@action_log_bp.route("/api/log/action", methods=["POST"])
def log_action():
    payload = request.get_json(silent=True) or {}

    session_id = str(payload.get("session_id", "")).strip()[:64]
    action_type = str(payload.get("action_type", "")).strip()

    if not session_id or not _SESSION_ID_RE.match(session_id):
        return jsonify({"error": "invalid session_id"}), 400
    if action_type not in _ALLOWED_ACTIONS:
        return jsonify({"error": "invalid action_type"}), 400

    latitude = _parse_float(payload.get("latitude"))
    longitude = _parse_float(payload.get("longitude"))
    sigun_nm = str(payload.get("sigun_nm", "") or "").strip()[:100] or None
    place_id_raw = payload.get("place_id")
    place_id: int | None = None
    if place_id_raw is not None:
        try:
            place_id = int(place_id_raw)
        except (TypeError, ValueError):
            pass
    place_name = str(payload.get("place_name", "") or "").strip()[:255] or None

    try:
        conn = get_db_connection()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO locallink.user_action_log
                        (session_id, action_type, latitude, longitude,
                         sigun_nm, place_id, place_name)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (session_id, action_type, latitude, longitude,
                     sigun_nm, place_id, place_name),
                )
        conn.close()
    except Exception as e:
        logging.warning(f"[action_log] DB 기록 실패: {e}")
        # 로그 실패는 사용자 경험에 영향 없도록 200 반환
        return jsonify({"ok": False}), 200

    return jsonify({"ok": True}), 201
