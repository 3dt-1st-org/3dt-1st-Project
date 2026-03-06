from __future__ import annotations

from typing import Any

import psycopg2.extras

from src.frontend.web.services.db import get_db_connection
from src.frontend.web.services.docent_service import generate_docent_script
from src.frontend.web.services.speech_service import SpeechSynthesisError, synthesize_speech_mp3

VALID_DOCENT_CATEGORIES = {"attraction", "restaurant", "event"}
VALID_LANGUAGES = {"ko", "en"}
VALID_MODES = {"brief", "detail"}


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
