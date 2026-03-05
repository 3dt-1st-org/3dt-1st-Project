#!/usr/bin/env python3
"""Sync iOS API base URL from Azure Key Vault into AppConfig.local.plist.

Usage:
  .venv/bin/python scripts/sync_ios_api_base_url_from_keyvault.py
  .venv/bin/python scripts/sync_ios_api_base_url_from_keyvault.py --secret lala-api-base-url
  .venv/bin/python scripts/sync_ios_api_base_url_from_keyvault.py --url https://my-flask-app.example.com --check
"""

from __future__ import annotations

import argparse
import json
import plistlib
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_SECRET_CANDIDATES = [
    "lala-ios-api-base-url",
    "lala-api-base-url",
    "lala-web-base-url",
    "frontend-api-base-url",
    "web-base-url",
    "api-base-url",
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "src/frontend/ios/LALA/LALA/Config/AppConfig.local.plist"

# Allow importing project-level modules when this script is run directly.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def _normalize_url(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("API base URL is empty.")
    if not (trimmed.startswith("https://") or trimmed.startswith("http://")):
        raise ValueError(f"API base URL must start with http:// or https://: {trimmed}")
    return trimmed.rstrip("/")


def _get_vault():
    from config.vault_manager import vault
    return vault


def _read_secret_value(secret_name: str) -> str | None:
    value = _get_vault().get_secret(secret_name)
    if value is None:
        return None

    return _normalize_url(value)


def _resolve_api_base_url(secret_name: str | None) -> tuple[str, str]:
    candidates = [secret_name] if secret_name else DEFAULT_SECRET_CANDIDATES

    for candidate in candidates:
        if candidate is None:
            continue
        value = _read_secret_value(candidate)
        if value:
            return candidate, value

    tried = ", ".join(c for c in candidates if c)
    raise RuntimeError(f"No usable API base URL secret found. Tried: {tried}")


def _suggest_secret_names() -> list[str]:
    names = _get_vault().list_secret_names()
    if not names:
        return []

    keywords = ("url", "base", "api", "web")
    ranked = [name for name in names if any(keyword in name.lower() for keyword in keywords)]
    return ranked[:10]


def _write_plist(api_base_url: str) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"API_BASE_URL": api_base_url}

    with OUTPUT_PATH.open("wb") as fp:
        plistlib.dump(payload, fp, sort_keys=True)


def _check_api_health(api_base_url: str) -> None:
    encoded = urllib.parse.urlencode(
        {
            "lat": "37.2636",
            "lng": "127.0286",
            "radius": "3000",
            "category": "all",
        }
    )
    urls = [
        f"{api_base_url}/api/places?{encoded}",
        f"{api_base_url}/api/weather?lat=37.2636&lng=127.0286",
    ]

    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=8) as response:
                status_code = response.getcode()
                if status_code != 200:
                    raise RuntimeError(f"Health check failed: {url} returned {status_code}")
                body = response.read().decode("utf-8", errors="replace").strip()
                if body:
                    json.loads(body)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Health check failed: {url} returned HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"Health check failed: {url} is unreachable ({error.reason})") from error
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Health check failed: {url} did not return JSON") from error


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync iOS API base URL into AppConfig.local.plist from Key Vault or explicit URL."
    )
    parser.add_argument(
        "--url",
        help="Explicit deployed Flask base URL (for example: https://your-app.example.com).",
    )
    parser.add_argument(
        "--secret",
        help="Key Vault secret name for API base URL. If omitted, known candidates are tried.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Call /api/places and /api/weather before writing plist.",
    )
    args = parser.parse_args()

    if args.url and args.secret:
        raise SystemExit("Use either --url or --secret, not both.")

    try:
        if args.url:
            source_name = "manual-url"
            api_base_url = _normalize_url(args.url)
        else:
            source_name, api_base_url = _resolve_api_base_url(args.secret)

        if args.check:
            _check_api_health(api_base_url)

        _write_plist(api_base_url)
    except Exception as error:
        hint = ""
        if not args.url:
            suggestions = _suggest_secret_names()
            if suggestions:
                hint = f" Candidate secrets: {', '.join(suggestions)}"
        raise SystemExit(f"Failed to sync iOS API base URL: {error}.{hint}") from error

    print(f"Synced iOS API base URL from '{source_name}' -> {OUTPUT_PATH}")
    print(f"API_BASE_URL={api_base_url}")


if __name__ == "__main__":
    main()
