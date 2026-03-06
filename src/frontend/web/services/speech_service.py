from __future__ import annotations

import html
import os

import requests


class SpeechSynthesisError(RuntimeError):
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


def _voice_name(language: str) -> str:
    if language == "en":
        return "en-US-JennyNeural"
    return "ko-KR-SunHiNeural"


def _voice_locale(language: str) -> str:
    if language == "en":
        return "en-US"
    return "ko-KR"


def synthesize_speech_mp3(script: str, language: str) -> bytes:
    text = script.strip()
    if not text:
        raise SpeechSynthesisError("script is required", status_code=400)
    if len(text) > 6000:
        raise SpeechSynthesisError("script is too long", status_code=400)

    speech_key = (os.getenv("AZURE_SPEECH_KEY") or "").strip()
    speech_region = (os.getenv("AZURE_SPEECH_REGION") or "").strip()

    if not speech_key or not speech_region:
        raise SpeechSynthesisError("speech configuration is missing", status_code=503)

    endpoint = f"https://{speech_region}.tts.speech.microsoft.com/cognitiveservices/v1"

    escaped = html.escape(text)
    voice = _voice_name(language)
    locale = _voice_locale(language)
    ssml = (
        f"<speak version='1.0' xml:lang='{locale}'>"
        f"<voice xml:lang='{locale}' name='{voice}'>{escaped}</voice>"
        "</speak>"
    )

    response = requests.post(
        endpoint,
        data=ssml.encode("utf-8"),
        headers={
            "Ocp-Apim-Subscription-Key": speech_key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
            "User-Agent": "lala-ios-docent-api",
        },
        timeout=20,
    )

    if response.status_code != 200:
        raise SpeechSynthesisError(
            f"speech synthesis failed: HTTP {response.status_code}",
            status_code=503,
        )

    return response.content
