from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.frontend.web.services.docent_api_service import (
    create_docent_audio_payload,
    create_docent_script_payload,
)
from src.frontend.web.services.speech_service import SpeechSynthesisError


def test_docent_script_payload_invalid_category():
    payload, status = create_docent_script_payload(
        {
            "place_id": "x",
            "category": "invalid",
            "language": "ko",
            "mode": "brief",
        }
    )

    assert status == 400
    assert payload["error"] == "category must be attraction|restaurant|event"


def test_docent_audio_payload_invalid_language():
    payload, status, mime_type = create_docent_audio_payload(
        {"script": "hello", "language": "ja"}
    )

    assert status == 400
    assert mime_type == "application/json"
    assert payload["error"] == "language must be ko|en"


def test_docent_audio_payload_requires_script():
    payload, status, mime_type = create_docent_audio_payload(
        {"script": "   ", "language": "ko"}
    )

    assert status == 400
    assert mime_type == "application/json"
    assert payload["error"] == "script is required"


def test_docent_audio_payload_speech_failure(monkeypatch):
    def _raise_speech_error(script: str, language: str):
        raise SpeechSynthesisError("speech configuration is missing", status_code=503)

    monkeypatch.setattr(
        "src.frontend.web.services.docent_api_service.synthesize_speech_mp3",
        _raise_speech_error,
    )

    payload, status, mime_type = create_docent_audio_payload(
        {"script": "hello", "language": "en"}
    )

    assert status == 503
    assert mime_type == "application/json"
    assert payload["error"] == "speech configuration is missing"


def test_docent_audio_payload_success(monkeypatch):
    monkeypatch.setattr(
        "src.frontend.web.services.docent_api_service.synthesize_speech_mp3",
        lambda script, language: b"audio-bytes",
    )

    payload, status, mime_type = create_docent_audio_payload(
        {"script": "hello", "language": "en"}
    )

    assert status == 200
    assert mime_type == "audio/mpeg"
    assert payload == b"audio-bytes"
