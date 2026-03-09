from __future__ import annotations

import html
import os
from pathlib import Path
from datetime import datetime

import requests

from config.vault_manager import get_vault_manager


VOICE_BY_LANGUAGE = {
    "English": ("en-US", "en-US-JennyNeural"),
    "Korean": ("ko-KR", "ko-KR-SunHiNeural"),
    "Japanese": ("ja-JP", "ja-JP-NanamiNeural"),
}


class SpeechSynthesisError(RuntimeError):
    pass


def _get_speech_config() -> tuple[str, str]:
    vm = get_vault_manager()

    speech_key = (vm.get_secret("azure-speech-key") or "").strip()
    speech_region = (vm.get_secret("azure-speech-region") or "").strip()

    # Fallback for local runs where env vars are already set.
    if not speech_key:
        speech_key = (os.getenv("AZURE_SPEECH_KEY") or "").strip()
    if not speech_region:
        speech_region = (os.getenv("AZURE_SPEECH_REGION") or "").strip()

    if not speech_key or not speech_region:
        raise SpeechSynthesisError("speech configuration is missing")

    return speech_key, speech_region


def synthesize_text_to_mp3_bytes(text: str, language: str = "English") -> bytes:
    script = (text or "").strip()
    if not script:
        raise SpeechSynthesisError("script is required")

    locale, voice = VOICE_BY_LANGUAGE.get(language, VOICE_BY_LANGUAGE["English"])
    speech_key, speech_region = _get_speech_config()

    endpoint = f"https://{speech_region}.tts.speech.microsoft.com/cognitiveservices/v1"
    escaped = html.escape(script)
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
            "User-Agent": "lala-daily-planner",
        },
        timeout=20,
    )

    if response.status_code != 200:
        raise SpeechSynthesisError(f"speech synthesis failed: HTTP {response.status_code}")

    return response.content


def save_text_as_mp3(
    text: str,
    language: str = "English",
    output_dir: str | Path | None = None,
    filename_prefix: str = "daily_plan",
) -> str:
    mp3_bytes = synthesize_text_to_mp3_bytes(text=text, language=language)

    if output_dir is None:
        output_dir = Path(__file__).resolve().parents[2] / "data" / "docent" / "mp3"
    else:
        output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_prefix = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in filename_prefix)
    output_path = output_dir / f"{safe_prefix}_{language.lower()}.mp3"

    output_path.write_bytes(mp3_bytes)
    return str(output_path)
