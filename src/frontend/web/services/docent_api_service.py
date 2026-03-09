from __future__ import annotations

from typing import Any

import psycopg2.extras

from src.frontend.web.services.db import get_db_connection
from src.frontend.web.services.docent_service import generate_docent_script
from src.frontend.web.services.speech_service import SpeechSynthesisError, synthesize_speech_mp3

VALID_DOCENT_CATEGORIES = {"attraction", "restaurant", "event"}
VALID_LANGUAGES = {"ko", "en"}
VALID_MODES = {"brief", "detail"}
_TOUR_TOP_N = 10


def create_docent_script_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    place_id = str(payload.get("place_id") or "").strip()
    category = str(payload.get("category") or "").strip().lower()
    language = str(payload.get("language") or "ko").strip().lower()
    mode = str(payload.get("mode") or "brief").strip().lower()

    if category not in VALID_DOCENT_CATEGORIES:
        return {"error": "category must be attraction|restaurant|event"}, 400
    if language not in VALID_LANGUAGES:
        return {"error": "language must be ko|en"}, 400
    if mode not in VALID_MODES:
        return {"error": "mode must be brief|detail"}, 400

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
        return {"error": str(exc)}, 400
    except Exception as exc:
        return {"error": str(exc)}, 500

    return {
        "place_id": result.place_id,
        "category": result.category,
        "language": result.language,
        "mode": result.mode,
        "script": result.script,
        "source": result.source,
        "generated_at": result.generated_at,
        "ttl_sec": result.ttl_sec,
    }, 200


def create_docent_audio_payload(payload: dict[str, Any]) -> tuple[bytes | dict[str, Any], int, str]:
    script = str(payload.get("script") or "").strip()
    language = str(payload.get("language") or "ko").strip().lower()

    if language not in VALID_LANGUAGES:
        return {"error": "language must be ko|en"}, 400, "application/json"
    if not script:
        return {"error": "script is required"}, 400, "application/json"

    try:
        audio_bytes = synthesize_speech_mp3(script=script, language=language)
    except SpeechSynthesisError as exc:
        return {"error": str(exc)}, exc.status_code, "application/json"
    except Exception as exc:
        return {"error": str(exc)}, 500, "application/json"

    return audio_bytes, 200, "audio/mpeg"


def create_tour_docent_payload(
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | bytes, int, str]:
    """POST /api/docent/tour 처리.

    Request body:
      lat, lng          float  (필수 — 현재 지도 중심)
      radius            int    (선택, 기본 20000)
      city              str    (선택)
      language          str    (ko|en, 기본 ko)
      with_audio        bool   (선택, 기본 false)

    Response (with_audio=false): application/json  {script, restaurant_names, source}
    Response (with_audio=true):  audio/mpeg  MP3 bytes (script/names in X- headers)
    """
    try:
        lat = float(payload.get("lat") or 0)
        lng = float(payload.get("lng") or 0)
    except (TypeError, ValueError):
        return {"error": "lat, lng must be numeric"}, 400, "application/json"

    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return {"error": "lat/lng out of range"}, 400, "application/json"

    radius = int(payload.get("radius") or 20000)
    city   = str(payload.get("city") or "").strip()
    language = str(payload.get("language") or "ko").strip().lower()
    with_audio = bool(payload.get("with_audio", False))

    if language not in VALID_LANGUAGES:
        return {"error": "language must be ko|en"}, 400, "application/json"

    # 1) 주변 맛집 목록 조회
    from src.frontend.web.services.map_api_service import create_places_payload
    places_payload, places_status = create_places_payload(
        lat=lat,
        lng=lng,
        radius=radius,
        category="restaurant",
        scope="city" if city else "radius",
        city_hint=city,
        limit=_TOUR_TOP_N * 3,   # 랭킹 여유분 확보
    )
    if places_status != 200:
        return {"error": places_payload.get("error", "places lookup failed")}, 502, "application/json"

    places = places_payload.get("places") or []
    if not places:
        return {"error": "주변 맛집 데이터가 없습니다."}, 404, "application/json"

    _seen: set[str] = set()
    candidate_names: list[str] = []
    for p in places:
        _name = p.get("name") or p.get("name_en") or ""
        if _name and _name not in _seen:
            _seen.add(_name)
            candidate_names.append(_name)
    if not candidate_names:
        return {"error": "식당 이름을 가져오지 못했습니다."}, 404, "application/json"

    # 2) 투어 도슨트 생성
    try:
        from src.services.restaurant_docent import generate_restaurant_tour_docent
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                result = generate_restaurant_tour_docent(
                    restaurant_names=candidate_names,
                    cursor=cursor,
                    language=language,
                    with_audio=with_audio,
                    auto_rank=True,
                )
            conn.commit()
    except ValueError as exc:
        return {"error": str(exc)}, 400, "application/json"
    except Exception as exc:
        return {"error": str(exc)}, 500, "application/json"

    if with_audio and result.audio_bytes:
        return result.audio_bytes, 200, "audio/mpeg"

    return {
        "restaurant_names": result.restaurant_names,
        "language": result.language,
        "script": result.script,
        "source": result.source,
        "restaurant_count": result.restaurant_count,
    }, 200, "application/json"
