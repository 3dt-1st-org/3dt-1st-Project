from __future__ import annotations

import copy
import hmac
import json
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import quote, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import psycopg2.extras
import requests as http_requests
from flask import Blueprint, Response, jsonify, request

from src.frontend.web.services.db import get_db_connection
from src.frontend.web.services.docent_api_service import (
    create_docent_audio_payload,
    create_docent_script_payload,
)
from src.frontend.web.services.map_api_service import (
    create_places_payload,
    create_weather_payload,
)


ios_api_bp = Blueprint("ios_api", __name__)

_DEFAULT_LAT = 37.2636
_DEFAULT_LNG = 127.0286
_DEFAULT_RADIUS = 3000
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 100

_RE, _GRID = 6371.00877, 5.0
_SLAT1, _SLAT2, _OLON, _OLAT, _XO, _YO = 30.0, 60.0, 126.0, 38.0, 43, 136

_PTY_ICON = {
    "0": "☀️",
    "1": "🌧️",
    "2": "🌨️",
    "3": "❄️",
    "5": "🌦️",
    "6": "🌨️",
    "7": "🌨️",
}

_WEATHER_API_URL = (
    "http://apis.data.go.kr/1360000/"
    "VilageFcstInfoService_2.0/getUltraSrtNcst"
)
_OPEN_METEO_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
_OPEN_METEO_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
_OPEN_METEO_TIMEOUT_SEC = 3.5
_LEGACY_WEATHER_TIMEOUT_SEC = 2.5
_WEATHER_CACHE_TTL_SEC = 180
_WEATHER_CACHE_STALE_SEC = 900
_WEATHER_CACHE_COORD_PRECISION = 3
_WEATHER_HTTP_CACHE_CONTROL = "private, max-age=180"
_DUST_GRADE_LABELS = {
    "good": "좋음",
    "normal": "보통",
    "bad": "나쁨",
    "very_bad": "매우나쁨",
    "unknown": "정보없음",
}


_VALID_PLACE_CATEGORIES = {"all", "attraction", "restaurant", "event"}
_VALID_PLACE_SCOPES = {"radius", "city"}
_VALID_DOCENT_CATEGORIES = {"attraction", "restaurant", "event"}
_VALID_LANGUAGES = {"ko", "en"}
_VALID_MODES = {"brief", "detail"}
_RESTAURANT_IMAGE_COLUMN_CANDIDATES = (
    "image_url",
    "image_urls",
    "thumbnail_url",
    "thumb_url",
    "photo_url",
    "photo_urls",
)


def _safe_float_env(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _safe_int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


_OPEN_METEO_TIMEOUT_SEC = max(1.0, min(_safe_float_env("OPEN_METEO_TIMEOUT_SEC", _OPEN_METEO_TIMEOUT_SEC), 8.0))
_LEGACY_WEATHER_TIMEOUT_SEC = max(1.0, min(_safe_float_env("LEGACY_WEATHER_TIMEOUT_SEC", _LEGACY_WEATHER_TIMEOUT_SEC), 8.0))
_WEATHER_CACHE_TTL_SEC = max(30, min(_safe_int_env("WEATHER_CACHE_TTL_SEC", _WEATHER_CACHE_TTL_SEC), 900))
_WEATHER_CACHE_STALE_SEC = max(
    _WEATHER_CACHE_TTL_SEC,
    min(_safe_int_env("WEATHER_CACHE_STALE_SEC", _WEATHER_CACHE_STALE_SEC), 3600),
)
_WEATHER_CACHE_COORD_PRECISION = max(
    2,
    min(_safe_int_env("WEATHER_CACHE_COORD_PRECISION", _WEATHER_CACHE_COORD_PRECISION), 4),
)
_WEATHER_HTTP_CACHE_CONTROL = f"private, max-age={_WEATHER_CACHE_TTL_SEC}"
_WEATHER_FETCH_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="lala-weather")
_WEATHER_CACHE_LOCK = threading.Lock()
_WEATHER_CACHE: dict[tuple[float, float], dict] = {}
_WEATHER_INFLIGHT: dict[tuple[float, float], "_InflightWeatherRequest"] = {}

# weather_air_func 배치 데이터(realtime_weather_conditions) DB 우선 조회 활성화 여부
# 장애 시 WEATHER_DB_ENABLED=false 로 즉시 우회 가능
_WEATHER_DB_ENABLED: bool = (os.getenv("WEATHER_DB_ENABLED", "true").strip().lower() != "false")

# stations.json 33개 도시: (nx, ny, DB location 한글명)
# nx/ny 는 기상청 격자 좌표 — _latlon_to_grid() 결과와 비교하여 최근접 도시 탐색에 사용
_STATION_COORD_MAP: list[tuple[int, int, str]] = [
    (60, 127, "서울"),
    (54, 124, "인천"),
    (61, 121, "수원"),
    (63, 124, "성남"),
    (61, 130, "의정부"),
    (59, 123, "안양"),
    (56, 125, "부천"),
    (58, 125, "광명"),
    (62, 114, "평택"),
    (61, 134, "동두천"),
    (57, 121, "안산"),
    (58, 128, "고양"),
    (60, 124, "과천"),
    (62, 127, "구리"),
    (64, 128, "남양주"),
    (62, 118, "오산"),
    (57, 123, "시흥"),
    (60, 122, "군포"),
    (60, 123, "의왕"),
    (64, 126, "하남"),
    (64, 119, "용인"),
    (56, 131, "파주"),
    (68, 121, "이천"),
    (65, 115, "안성"),
    (55, 128, "김포"),
    (57, 119, "화성"),
    (65, 123, "광주"),
    (61, 131, "양주"),
    (64, 134, "포천"),
    (71, 121, "여주"),
    (58, 138, "연천"),
    (69, 133, "가평"),
    (69, 125, "양평"),
]


class _InflightWeatherRequest:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.payload: dict | None = None
        self.status_code: int | None = None


def _weather_cache_key(lat: float, lng: float) -> tuple[float, float]:
    return (round(lat, _WEATHER_CACHE_COORD_PRECISION), round(lng, _WEATHER_CACHE_COORD_PRECISION))


def _read_cached_weather_entry(
    key: tuple[float, float],
    *,
    now_monotonic: float,
    allow_stale: bool,
) -> tuple[dict, int] | None:
    entry = _WEATHER_CACHE.get(key)
    if not entry:
        return None

    age = now_monotonic - float(entry.get("stored_at", 0.0))
    if age <= _WEATHER_CACHE_TTL_SEC:
        return copy.deepcopy(entry["payload"]), int(entry["status_code"])
    if allow_stale and age <= _WEATHER_CACHE_STALE_SEC:
        return copy.deepcopy(entry["payload"]), int(entry["status_code"])
    return None


def _store_cached_weather_entry(key: tuple[float, float], payload: dict, status_code: int) -> None:
    _WEATHER_CACHE[key] = {
        "payload": copy.deepcopy(payload),
        "status_code": status_code,
        "stored_at": time.monotonic(),
    }


def _has_meaningful_dust(payload: dict | None) -> bool:
    if not payload:
        return False

    dust = payload.get("dust") or {}
    grade = str(dust.get("grade") or "").strip().lower()
    if grade and grade != "unknown":
        return True
    return dust.get("pm10") is not None or dust.get("pm25") is not None


def _merge_cached_dust(current_payload: dict, cached_payload: dict | None) -> dict:
    if _has_meaningful_dust(current_payload):
        return current_payload
    if not _has_meaningful_dust(cached_payload):
        return current_payload

    merged = copy.deepcopy(current_payload)
    merged["dust"] = copy.deepcopy((cached_payload or {}).get("dust") or {})
    cached_source = str((cached_payload or {}).get("dust_source") or "").strip()
    if cached_source:
        merged["dust_source"] = f"stale-{cached_source}"
    return merged


def _reset_weather_cache_for_tests() -> None:
    with _WEATHER_CACHE_LOCK:
        _WEATHER_CACHE.clear()
        _WEATHER_INFLIGHT.clear()


def _find_nearest_db_location(lat: float, lng: float) -> str | None:
    """요청 좌표를 기상청 격자(nx, ny)로 변환 후 _STATION_COORD_MAP에서 최근접 도시명(한글) 반환."""
    try:
        nx, ny = _latlon_to_grid(lat, lng)
        nearest_location: str | None = None
        min_dist = float("inf")
        for s_nx, s_ny, location in _STATION_COORD_MAP:
            dist = (nx - s_nx) ** 2 + (ny - s_ny) ** 2
            if dist < min_dist:
                min_dist = dist
                nearest_location = location
        return nearest_location
    except Exception:
        return None


def _fetch_weather_from_db(lat: float, lng: float) -> tuple[dict, int] | None:
    """realtime_weather_conditions 에서 최근접 도시의 최신 날씨 레코드를 읽어 payload 형식으로 반환.

    70분 이내 데이터가 없거나 DB 오류 시 None 반환 → 호출부에서 Open-Meteo 폴백.
    """
    location = _find_nearest_db_location(lat, lng)
    if not location:
        return None
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    """
                    SELECT temperature, precipitation_type, pm10, pm25
                    FROM locallink.realtime_weather_conditions
                    WHERE location = %s
                      AND record_time > NOW() - INTERVAL '70 minutes'
                    ORDER BY record_time DESC
                    LIMIT 1
                    """,
                    (location,),
                )
                row = cur.fetchone()
    except Exception:
        return None

    if not row:
        return None

    temp = _format_temp_value(row["temperature"])
    pty_str = str(int(row["precipitation_type"] or 0))
    icon = _PTY_ICON.get(pty_str, "🌡️")
    grade = _dust_grade_code(row["pm10"], row["pm25"])

    return {
        "temp": temp,
        "icon": icon,
        "dust": {
            "pm10": _format_pm_value(row["pm10"]),
            "pm25": _format_pm_value(row["pm25"]),
            "grade": grade,
            "grade_ko": _DUST_GRADE_LABELS.get(grade, _DUST_GRADE_LABELS["unknown"]),
        },
        "forecast": [],
        "source": "db",
        "dust_source": "db",
        "location": location,
    }, 200


def _latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    degrad = math.pi / 180.0
    re_val = _RE / _GRID
    slat1 = _SLAT1 * degrad
    slat2 = _SLAT2 * degrad
    olon = _OLON * degrad
    olat = _OLAT * degrad
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(
        math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    )
    sf = (math.tan(math.pi * 0.25 + slat1 * 0.5) ** sn) * math.cos(slat1) / sn
    ro = re_val * sf / (math.tan(math.pi * 0.25 + olat * 0.5) ** sn)
    ra = re_val * sf / (math.tan(math.pi * 0.25 + lat * degrad * 0.5) ** sn)
    theta = (lon * degrad - olon) * sn
    if theta > math.pi:
        theta -= 2 * math.pi
    if theta < -math.pi:
        theta += 2 * math.pi
    return int(ra * math.sin(theta) + _XO + 0.5), int(ro - ra * math.cos(theta) + _YO + 0.5)


def _require_api_key(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        expected = (os.getenv("IOS_API_KEY") or "").strip()
        if not expected:
            return jsonify({"error": "IOS_API_KEY is not configured"}), 503

        provided = (request.headers.get("X-API-Key") or "").strip()
        if not provided or not hmac.compare_digest(provided, expected):
            return jsonify({"error": "unauthorized"}), 401

        return fn(*args, **kwargs)

    return wrapped


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


def _weather_snapshot(lat: float, lng: float) -> tuple[dict, int]:
    key = _weather_cache_key(lat, lng)
    now_monotonic = time.monotonic()
    cached_stale_payload: dict | None = None

    with _WEATHER_CACHE_LOCK:
        cached = _read_cached_weather_entry(key, now_monotonic=now_monotonic, allow_stale=False)
        if cached is not None:
            return cached

        stale = _read_cached_weather_entry(key, now_monotonic=now_monotonic, allow_stale=True)
        if stale is not None:
            cached_stale_payload = stale[0]

        inflight = _WEATHER_INFLIGHT.get(key)
        owns_fetch = inflight is None
        if owns_fetch:
            inflight = _InflightWeatherRequest()
            _WEATHER_INFLIGHT[key] = inflight

    if not owns_fetch:
        inflight.event.wait(timeout=max(_OPEN_METEO_TIMEOUT_SEC * 2.0, 2.0) + 1.0)
        if inflight.payload is not None and inflight.status_code is not None:
            return copy.deepcopy(inflight.payload), inflight.status_code

        with _WEATHER_CACHE_LOCK:
            stale = _read_cached_weather_entry(key, now_monotonic=time.monotonic(), allow_stale=True)
        if stale is not None:
            return stale

    # ── DB 우선 조회 (weather_air_func 배치 데이터) ────────────────────────
    if _WEATHER_DB_ENABLED:
        _db_result = _fetch_weather_from_db(lat, lng)
        if _db_result is not None:
            _db_payload, _db_status = _db_result
            with _WEATHER_CACHE_LOCK:
                _store_cached_weather_entry(key, _db_payload, _db_status)
                _current_inflight = _WEATHER_INFLIGHT.pop(key, None)
                if _current_inflight is not None:
                    _current_inflight.payload = copy.deepcopy(_db_payload)
                    _current_inflight.status_code = _db_status
                    _current_inflight.event.set()
            return copy.deepcopy(_db_payload), _db_status
    # ────────────────────────────────────────────────────────────────────────

    try:
        payload, status_code = _compute_weather_snapshot(lat=lat, lng=lng)
    except Exception as exc:
        payload, status_code = {"error": str(exc)}, 502

    with _WEATHER_CACHE_LOCK:
        stale = _read_cached_weather_entry(key, now_monotonic=time.monotonic(), allow_stale=True)
        if status_code == 200:
            payload = _merge_cached_dust(payload, cached_stale_payload)
            _store_cached_weather_entry(key, payload, status_code)
        elif stale is not None:
            payload, status_code = stale

        if owns_fetch:
            current_inflight = _WEATHER_INFLIGHT.pop(key, None)
            if current_inflight is not None:
                current_inflight.payload = copy.deepcopy(payload)
                current_inflight.status_code = status_code
                current_inflight.event.set()

    return payload, status_code


def _compute_weather_snapshot(lat: float, lng: float) -> tuple[dict, int]:
    try:
        weather_future = _WEATHER_FETCH_EXECUTOR.submit(_fetch_open_meteo_weather, lat, lng)
        air_quality_future = _WEATHER_FETCH_EXECUTOR.submit(_fetch_open_meteo_air_quality, lat, lng)

        weather_payload = weather_future.result(timeout=_OPEN_METEO_TIMEOUT_SEC + 0.5)

        current = weather_payload.get("current") or {}

        temp = _format_temp_value(current.get("temperature_2m"))
        icon = _wmo_weather_icon(current.get("weather_code"))
        forecast = _build_weather_forecast_payload(weather_payload=weather_payload)

        dust = {
            "pm10": None,
            "pm25": None,
            "grade": "unknown",
            "grade_ko": _DUST_GRADE_LABELS["unknown"],
        }
        dust_source = "none"
        try:
            air_payload = air_quality_future.result(timeout=_OPEN_METEO_TIMEOUT_SEC + 0.5)
            dust = _build_current_dust_payload(air_payload=air_payload)
            dust_source = "open-meteo"
        except Exception:
            dust_source = "unavailable"

        return {
            "temp": temp,
            "icon": icon,
            "dust": dust,
            "forecast": forecast,
            "source": "open-meteo",
            "dust_source": dust_source,
        }, 200
    except Exception as primary_exc:
        legacy_payload, legacy_status = _legacy_weather_snapshot(lat=lat, lng=lng)
        if legacy_status == 200:
            legacy_payload["dust"] = {
                "pm10": None,
                "pm25": None,
                "grade": "unknown",
                "grade_ko": _DUST_GRADE_LABELS["unknown"],
            }
            legacy_payload["forecast"] = []
            legacy_payload["source"] = "kma-fallback"
            legacy_payload["dust_source"] = "none"
            return legacy_payload, 200

        return {
            "error": str(primary_exc),
            "fallback_error": legacy_payload.get("error"),
        }, 502


def _fetch_open_meteo_weather(lat: float, lng: float) -> dict:
    response = http_requests.get(
        _OPEN_METEO_WEATHER_URL,
        params={
            "latitude": lat,
            "longitude": lng,
            "current": "temperature_2m,weather_code",
            "hourly": "temperature_2m,weather_code",
            "forecast_days": 3,
            "timezone": "Asia/Seoul",
        },
        timeout=_OPEN_METEO_TIMEOUT_SEC,
    )
    response.raise_for_status()
    return response.json()


def _fetch_open_meteo_air_quality(lat: float, lng: float) -> dict:
    response = http_requests.get(
        _OPEN_METEO_AIR_QUALITY_URL,
        params={
            "latitude": lat,
            "longitude": lng,
            "current": "pm10,pm2_5",
            "timezone": "Asia/Seoul",
        },
        timeout=_OPEN_METEO_TIMEOUT_SEC,
    )
    response.raise_for_status()
    return response.json()


def _legacy_weather_snapshot(lat: float, lng: float) -> tuple[dict, int]:
    weather_api_key = (os.getenv("WEATHER_API_KEY") or "").strip()
    if not weather_api_key:
        return {"error": "WEATHER_API_KEY is not configured"}, 503

    now = datetime.now() - timedelta(hours=1)
    base_date = now.strftime("%Y%m%d")
    base_time = now.strftime("%H00")
    nx, ny = _latlon_to_grid(lat, lng)

    try:
        response = http_requests.get(
            _WEATHER_API_URL,
            params={
                "pageNo": "1",
                "numOfRows": "20",
                "dataType": "JSON",
                "base_date": base_date,
                "base_time": base_time,
                "nx": nx,
                "ny": ny,
                "serviceKey": weather_api_key,
            },
            timeout=_LEGACY_WEATHER_TIMEOUT_SEC,
        )
        response.raise_for_status()
        payload = response.json()

        header = payload["response"]["header"]
        if header["resultCode"] != "00":
            return {"error": header["resultMsg"]}, 502

        items = payload["response"]["body"]["items"]["item"]
        values = {item["category"]: item["obsrValue"] for item in items}
        temp = values.get("T1H", "--")
        pty = values.get("PTY", "0")
        icon = _PTY_ICON.get(str(int(float(pty))), "🌡️")
        return {"temp": str(temp), "icon": icon}, 200
    except Exception as exc:
        return {"error": str(exc)}, 500


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _format_temp_value(value) -> str:
    number = _safe_float(value)
    if number is None:
        return "--"
    rounded = round(number)
    if abs(number - rounded) < 0.05:
        return str(int(rounded))
    return f"{number:.1f}"


def _format_pm_value(value) -> str | None:
    number = _safe_float(value)
    if number is None:
        return None
    return str(int(round(number)))


def _wmo_weather_icon(code_value) -> str:
    code_number = _safe_float(code_value)
    if code_number is None:
        return "🌡️"
    code = int(round(code_number))

    if code == 0:
        return "☀️"
    if code in {1, 2}:
        return "⛅"
    if code == 3:
        return "☁️"
    if code in {45, 48}:
        return "🌫️"
    if code in {51, 53, 55, 56, 57}:
        return "🌦️"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "🌧️"
    if code in {71, 73, 75, 77, 85, 86}:
        return "🌨️"
    if code in {95, 96, 99}:
        return "⛈️"
    return "🌡️"


def _dust_grade_code(pm10_value, pm25_value) -> str:
    pm10 = _safe_float(pm10_value)
    pm25 = _safe_float(pm25_value)

    if pm10 is None and pm25 is None:
        return "unknown"

    # Korean guideline levels:
    # PM10: good <= 30, normal <= 80, bad <= 150
    # PM2.5: good <= 15, normal <= 35, bad <= 75
    pm10_level = 0
    if pm10 is not None:
        if pm10 > 150:
            pm10_level = 3
        elif pm10 > 80:
            pm10_level = 2
        elif pm10 > 30:
            pm10_level = 1

    pm25_level = 0
    if pm25 is not None:
        if pm25 > 75:
            pm25_level = 3
        elif pm25 > 35:
            pm25_level = 2
        elif pm25 > 15:
            pm25_level = 1

    level = max(pm10_level, pm25_level)
    return ["good", "normal", "bad", "very_bad"][level]


def _build_current_dust_payload(air_payload: dict) -> dict:
    current = air_payload.get("current") or {}
    pm10 = current.get("pm10")
    pm25 = current.get("pm2_5")
    grade = _dust_grade_code(pm10, pm25)

    return {
        "pm10": _format_pm_value(pm10),
        "pm25": _format_pm_value(pm25),
        "grade": grade,
        "grade_ko": _DUST_GRADE_LABELS.get(grade, _DUST_GRADE_LABELS["unknown"]),
    }


def _build_weather_forecast_payload(weather_payload: dict) -> list[dict]:
    hourly = weather_payload.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    codes = hourly.get("weather_code") or []
    if not times:
        return []

    try:
        now_local = datetime.now(ZoneInfo("Asia/Seoul")).replace(tzinfo=None)
    except Exception:
        now_local = datetime.now(timezone.utc).astimezone(
            timezone(timedelta(hours=9))
        ).replace(tzinfo=None)

    forecast: list[dict] = []
    future_count = 0
    upper_bound = min(len(times), len(temps), len(codes))
    for idx in range(upper_bound):
        try:
            forecast_time = datetime.fromisoformat(str(times[idx]))
            if forecast_time.tzinfo is not None:
                forecast_time = forecast_time.astimezone(ZoneInfo("Asia/Seoul")).replace(tzinfo=None)
        except Exception:
            continue

        if forecast_time <= now_local:
            continue
        if future_count % 3 != 0:
            future_count += 1
            continue

        forecast.append(
            {
                "time": str(times[idx]),
                "temp": _format_temp_value(temps[idx]),
                "icon": _wmo_weather_icon(codes[idx]),
            }
        )
        future_count += 1
        if len(forecast) >= 12:
            break
    return forecast


def _restaurant_image_expr(cursor) -> str:
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'locallink'
          AND table_name = 'gg_restaurant_info'
          AND column_name = ANY(%s)
        ORDER BY array_position(%s, column_name)
        LIMIT 1
        """,
        (list(_RESTAURANT_IMAGE_COLUMN_CANDIDATES), list(_RESTAURANT_IMAGE_COLUMN_CANDIDATES)),
    )
    row = cursor.fetchone()
    if not row:
        return "NULL::TEXT"
    column_name = row[0]
    if column_name not in _RESTAURANT_IMAGE_COLUMN_CANDIDATES:
        return "NULL::TEXT"
    return f"COALESCE(NULLIF(TRIM({column_name}::TEXT), ''), NULL)"


def _normalize_image_url(raw) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    parsed_candidates: list[str] = []
    if text.startswith("["):
        try:
            parsed_json = json.loads(text)
            if isinstance(parsed_json, list):
                parsed_candidates = [str(item).strip() for item in parsed_json if str(item).strip()]
        except Exception:
            parsed_candidates = []

    if text.startswith("{") and text.endswith("}"):
        body = text[1:-1]
        parsed_candidates.extend(
            segment.strip().strip('"').strip("'")
            for segment in body.split(",")
            if segment.strip().strip('"').strip("'")
        )

    if not parsed_candidates:
        matches = re.findall(r"https?://[^\"'\]\}\s,]+", text)
        if matches:
            parsed_candidates.extend(matches)

    if not parsed_candidates:
        for separator in (",", ";", "|", "\n"):
            if separator in text:
                candidate = text.split(separator)[0].strip().strip('"').strip("'")
                if candidate:
                    parsed_candidates.append(candidate)
                break

    if not parsed_candidates:
        parsed_candidates = [text]

    candidate = parsed_candidates[0]
    if not candidate.lower().startswith(("http://", "https://")):
        return None

    try:
        split = urlsplit(candidate)
        encoded_path = quote(split.path, safe="/:%")
        encoded_query = quote(split.query, safe="=&%:/?+-_.,")
        return urlunsplit((split.scheme, split.netloc, encoded_path, encoded_query, split.fragment))
    except Exception:
        return candidate


def _normalize_place_row(row: dict) -> dict:
    def _clean_text(value, default: str = "") -> str:
        if value is None:
            return default
        text = str(value).strip()
        return text or default

    row["place_id"] = _clean_text(row.get("place_id") or row.get("id"))
    row["name"] = _clean_text(row.get("name"), "이름 없음")
    row["name_en"] = _clean_text(row.get("name_en"), row["name"])
    row["address"] = _clean_text(row.get("address"))
    row["address_en"] = _clean_text(row.get("address_en"), row["address"])
    row["region"] = _clean_text(row.get("region"))
    row["region_en"] = _clean_text(row.get("region_en"), row["region"])
    row["image_url"] = _normalize_image_url(row.get("image_url"))
    return row


def _city_aliases(raw_city: str) -> list[str]:
    city = re.sub(r"\s+", "", (raw_city or "").strip())
    if not city:
        return []
    aliases = {city}
    if city.endswith(("시", "군", "구")) and len(city) > 1:
        aliases.add(city[:-1])
    else:
        aliases.add(f"{city}시")
    return [alias for alias in aliases if alias]


def _resolve_city_from_coordinate(cursor, lat: float, lng: float) -> str | None:
    cursor.execute(
        """
        SELECT COALESCE(TRIM(sigun_nm), '') AS city
        FROM locallink.gg_restaurant_info
        WHERE refine_wgs84_lat IS NOT NULL
          AND refine_wgs84_logt IS NOT NULL
          AND refine_wgs84_lat::TEXT <> 'NaN'
          AND refine_wgs84_logt::TEXT <> 'NaN'
          AND COALESCE(TRIM(sigun_nm), '') <> ''
          AND bsn_state_nm = '영업'
        ORDER BY
          ST_Distance(
            ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
            ST_SetSRID(ST_MakePoint(refine_wgs84_logt::FLOAT, refine_wgs84_lat::FLOAT), 4326)::geography
          ) ASC
        LIMIT 1
        """,
        (lng, lat),
    )
    row = cursor.fetchone()
    if not row:
        return None
    city = str(row["city"] or "").strip()
    if not city:
        return None
    return city


def _fetch_places_by_city(
    lat: float,
    lng: float,
    city: str,
    category: str,
    limit: int,
) -> list[dict]:
    city_aliases = _city_aliases(city)
    if not city_aliases:
        return []

    results: list[dict] = []
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            normalized_city_expr = "REPLACE(COALESCE(TRIM(sigun_nm), ''), ' ', '')"
            normalized_event_city_expr = "REPLACE(COALESCE(TRIM(city), ''), ' ', '')"

            if category in {"all", "attraction"}:
                cursor.execute(
                    f"""
                    WITH city_centers AS (
                        SELECT
                            COALESCE(sigun_nm, '') AS city_name,
                            AVG(refine_wgs84_lat::FLOAT) AS center_lat,
                            AVG(refine_wgs84_logt::FLOAT) AS center_lng
                        FROM locallink.gg_restaurant_info
                        WHERE refine_wgs84_lat IS NOT NULL
                          AND refine_wgs84_logt IS NOT NULL
                          AND refine_wgs84_lat::TEXT <> 'NaN'
                          AND refine_wgs84_logt::TEXT <> 'NaN'
                          AND COALESCE(TRIM(sigun_nm), '') <> ''
                          AND bsn_state_nm = '영업'
                        GROUP BY COALESCE(sigun_nm, '')
                    ),
                    attraction_source AS (
                        SELECT
                            ad.attraction_name,
                            ad.sigun_nm,
                            ad.image_urls,
                            tsp.tourist_nm_en,
                            tsp.road_addr,
                            tsp.road_addr_en,
                            tsp.spot_lat,
                            tsp.spot_lng
                        FROM locallink.attraction_descriptions ad
                        LEFT JOIN LATERAL (
                            SELECT
                                NULLIF(TRIM(tourist_nm_en), '') AS tourist_nm_en,
                                NULLIF(TRIM(road_addr), '') AS road_addr,
                                NULLIF(TRIM(road_addr_en), '') AS road_addr_en,
                                CASE
                                    WHEN lat IS NOT NULL AND lng IS NOT NULL THEN lat::FLOAT
                                    ELSE NULL
                                END AS spot_lat,
                                CASE
                                    WHEN lat IS NOT NULL AND lng IS NOT NULL THEN lng::FLOAT
                                    ELSE NULL
                                END AS spot_lng
                            FROM locallink.tourist_spot_info tsp
                            WHERE COALESCE(TRIM(tsp.tourist_nm), '') = COALESCE(TRIM(ad.attraction_name), '')
                              AND REPLACE(COALESCE(TRIM(tsp.sigun_nm), ''), ' ', '') = REPLACE(COALESCE(TRIM(ad.sigun_nm), ''), ' ', '')
                            ORDER BY CASE WHEN tsp.lat IS NOT NULL AND tsp.lng IS NOT NULL THEN 0 ELSE 1 END
                            LIMIT 1
                        ) tsp ON TRUE
                        WHERE COALESCE(TRIM(ad.attraction_name), '') <> ''
                          AND REPLACE(COALESCE(TRIM(ad.sigun_nm), ''), ' ', '') = ANY(%s)
                    )
                    SELECT
                        MD5(COALESCE(src.attraction_name, '') || '|' || COALESCE(src.sigun_nm, '')) AS id,
                        COALESCE(src.attraction_name, '관광지') AS name,
                        COALESCE(src.tourist_nm_en, src.attraction_name, 'Attraction') AS name_en,
                        COALESCE(src.spot_lat, cc.center_lat, %s) AS lat,
                        COALESCE(src.spot_lng, cc.center_lng, %s) AS lng,
                        'attraction' AS category,
                        COALESCE(src.road_addr, '') AS address,
                        COALESCE(src.road_addr_en, src.road_addr, '') AS address_en,
                        COALESCE(src.sigun_nm, '') AS region,
                        COALESCE(src.sigun_nm, '') AS region_en,
                        ROUND(
                            ST_Distance(
                                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                                ST_SetSRID(
                                    ST_MakePoint(COALESCE(src.spot_lng, cc.center_lng, %s), COALESCE(src.spot_lat, cc.center_lat, %s)),
                                    4326
                                )::geography
                            )::NUMERIC,
                            0
                        )::INT AS distance_m,
                        COALESCE(NULLIF(TRIM(src.image_urls), ''), NULL) AS image_url,
                        (src.spot_lat IS NULL OR src.spot_lng IS NULL) AS is_approximate_location,
                        NULL::TEXT AS event_start_date,
                        NULL::TEXT AS event_end_date,
                        NULL::TEXT AS event_url
                    FROM attraction_source src
                    LEFT JOIN city_centers cc
                      ON cc.city_name = COALESCE(src.sigun_nm, '')
                    WHERE COALESCE(TRIM(src.attraction_name), '') <> ''
                    ORDER BY distance_m, name
                    LIMIT %s
                    """,
                    (
                        city_aliases,
                        _DEFAULT_LAT,
                        _DEFAULT_LNG,
                        lng,
                        lat,
                        _DEFAULT_LNG,
                        _DEFAULT_LAT,
                        limit,
                    ),
                )
                results.extend(_normalize_place_row(dict(row)) for row in cursor.fetchall())

            if category in {"all", "restaurant"}:
                restaurant_image_expr = _restaurant_image_expr(cursor)
                cursor.execute(
                    f"""
                    SELECT
                        MD5(bizplc_nm || COALESCE(refine_roadnm_addr, '')) AS id,
                        bizplc_nm AS name,
                        COALESCE(NULLIF(TRIM(bizplc_nm_en), ''), bizplc_nm) AS name_en,
                        refine_wgs84_lat::FLOAT AS lat,
                        refine_wgs84_logt::FLOAT AS lng,
                        'restaurant' AS category,
                        COALESCE(refine_roadnm_addr, refine_lotno_addr, '') AS address,
                        COALESCE(NULLIF(TRIM(refine_roadnm_addr_en), ''), COALESCE(refine_roadnm_addr, refine_lotno_addr, '')) AS address_en,
                        COALESCE(sigun_nm, '') AS region,
                        COALESCE(sigun_nm, '') AS region_en,
                        ROUND(
                            ST_Distance(
                                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                                ST_SetSRID(
                                    ST_MakePoint(refine_wgs84_logt::FLOAT, refine_wgs84_lat::FLOAT),
                                    4326
                                )::geography
                            )::NUMERIC,
                            0
                        )::INT AS distance_m,
                        {restaurant_image_expr} AS image_url,
                        FALSE AS is_approximate_location,
                        NULL::TEXT AS event_start_date,
                        NULL::TEXT AS event_end_date,
                        NULL::TEXT AS event_url
                    FROM locallink.gg_restaurant_info
                    WHERE refine_wgs84_lat IS NOT NULL
                      AND refine_wgs84_logt IS NOT NULL
                      AND refine_wgs84_lat::TEXT <> 'NaN'
                      AND refine_wgs84_logt::TEXT <> 'NaN'
                      AND bsn_state_nm = '영업'
                      AND {normalized_city_expr} = ANY(%s)
                    ORDER BY distance_m
                    LIMIT %s
                    """,
                    (lng, lat, city_aliases, limit),
                )
                results.extend(_normalize_place_row(dict(row)) for row in cursor.fetchall())

            if category in {"all", "event"}:
                cursor.execute(
                    f"""
                    WITH city_centers AS (
                        SELECT
                            COALESCE(sigun_nm, '') AS city_name,
                            AVG(refine_wgs84_lat::FLOAT) AS center_lat,
                            AVG(refine_wgs84_logt::FLOAT) AS center_lng
                        FROM locallink.gg_restaurant_info
                        WHERE refine_wgs84_lat IS NOT NULL
                          AND refine_wgs84_logt IS NOT NULL
                          AND refine_wgs84_lat::TEXT <> 'NaN'
                          AND refine_wgs84_logt::TEXT <> 'NaN'
                          AND COALESCE(TRIM(sigun_nm), '') <> ''
                          AND bsn_state_nm = '영업'
                        GROUP BY COALESCE(sigun_nm, '')
                    ),
                    normalized_events AS (
                        SELECT
                            MD5(COALESCE(title, '') || '|' || COALESCE(url, '') || '|' || COALESCE(city, '')) AS id,
                            COALESCE(title, '') AS name,
                            COALESCE(NULLIF(TRIM(title_en), ''), COALESCE(title, '')) AS name_en,
                            COALESCE(inst_nm, '') AS address,
                            COALESCE(inst_nm, '') AS address_en,
                            COALESCE(city, '') AS region,
                            COALESCE(city, '') AS region_en,
                            COALESCE(url, '') AS event_url,
                            COALESCE(NULLIF(TRIM(image_url), ''), NULL) AS image_url,
                            CASE
                                WHEN begin_de ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$' THEN begin_de::DATE
                                ELSE NULL
                            END AS event_start_date,
                            CASE
                                WHEN end_de ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$' THEN end_de::DATE
                                ELSE NULL
                            END AS event_end_date
                        FROM locallink.gyeonggi_events
                        WHERE COALESCE(TRIM(title), '') <> ''
                          AND COALESCE(TRIM(city), '') <> ''
                          AND {normalized_event_city_expr} = ANY(%s)
                    )
                    SELECT
                        ne.id,
                        ne.name,
                        ne.name_en,
                        COALESCE(cc.center_lat, %s) AS lat,
                        COALESCE(cc.center_lng, %s) AS lng,
                        'event' AS category,
                        ne.address,
                        ne.address_en,
                        ne.region,
                        ne.region_en,
                        ROUND(
                            ST_Distance(
                                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                                ST_SetSRID(
                                    ST_MakePoint(COALESCE(cc.center_lng, %s), COALESCE(cc.center_lat, %s)),
                                    4326
                                )::geography
                            )::NUMERIC,
                            0
                        )::INT AS distance_m,
                        ne.image_url AS image_url,
                        TRUE AS is_approximate_location,
                        ne.event_start_date::TEXT AS event_start_date,
                        ne.event_end_date::TEXT AS event_end_date,
                        ne.event_url
                    FROM normalized_events ne
                    LEFT JOIN city_centers cc
                      ON REPLACE(COALESCE(TRIM(cc.city_name), ''), ' ', '') = REPLACE(COALESCE(TRIM(ne.region), ''), ' ', '')
                    WHERE (ne.event_end_date IS NULL OR ne.event_end_date >= CURRENT_DATE)
                    ORDER BY distance_m, ne.event_start_date NULLS LAST
                    LIMIT %s
                    """,
                    (
                        city_aliases,
                        _DEFAULT_LAT,
                        _DEFAULT_LNG,
                        lng,
                        lat,
                        _DEFAULT_LNG,
                        _DEFAULT_LAT,
                        limit,
                    ),
                )
                results.extend(_normalize_place_row(dict(row)) for row in cursor.fetchall())

    results.sort(key=lambda row: row.get("distance_m") or 0)
    if category == "all":
        return results
    return results[: max(limit, 1)]


def _fetch_places(lat: float, lng: float, radius: int, category: str, limit: int) -> list[dict]:
    results: list[dict] = []

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            if category in {"all", "attraction"}:
                cursor.execute(
                    """
                    WITH city_centers AS (
                        SELECT
                            COALESCE(sigun_nm, '') AS city_name,
                            AVG(refine_wgs84_lat::FLOAT) AS center_lat,
                            AVG(refine_wgs84_logt::FLOAT) AS center_lng
                        FROM locallink.gg_restaurant_info
                        WHERE refine_wgs84_lat IS NOT NULL
                          AND refine_wgs84_logt IS NOT NULL
                          AND refine_wgs84_lat::TEXT <> 'NaN'
                          AND refine_wgs84_logt::TEXT <> 'NaN'
                          AND COALESCE(TRIM(sigun_nm), '') <> ''
                          AND bsn_state_nm = '영업'
                        GROUP BY COALESCE(sigun_nm, '')
                    ),
                    attraction_source AS (
                        SELECT
                            ad.attraction_name,
                            ad.sigun_nm,
                            ad.image_urls,
                            tsp.tourist_nm_en,
                            tsp.road_addr,
                            tsp.road_addr_en,
                            tsp.spot_lat,
                            tsp.spot_lng
                        FROM locallink.attraction_descriptions ad
                        LEFT JOIN LATERAL (
                            SELECT
                                NULLIF(TRIM(tourist_nm_en), '') AS tourist_nm_en,
                                NULLIF(TRIM(road_addr), '') AS road_addr,
                                NULLIF(TRIM(road_addr_en), '') AS road_addr_en,
                                CASE
                                    WHEN lat IS NOT NULL AND lng IS NOT NULL THEN lat::FLOAT
                                    ELSE NULL
                                END AS spot_lat,
                                CASE
                                    WHEN lat IS NOT NULL AND lng IS NOT NULL THEN lng::FLOAT
                                    ELSE NULL
                                END AS spot_lng
                            FROM locallink.tourist_spot_info tsp
                            WHERE COALESCE(TRIM(tsp.tourist_nm), '') = COALESCE(TRIM(ad.attraction_name), '')
                              AND REPLACE(COALESCE(TRIM(tsp.sigun_nm), ''), ' ', '') = REPLACE(COALESCE(TRIM(ad.sigun_nm), ''), ' ', '')
                            ORDER BY CASE WHEN tsp.lat IS NOT NULL AND tsp.lng IS NOT NULL THEN 0 ELSE 1 END
                            LIMIT 1
                        ) tsp ON TRUE
                    )
                    SELECT
                        MD5(COALESCE(src.attraction_name, '') || '|' || COALESCE(src.sigun_nm, '')) AS id,
                        COALESCE(src.attraction_name, '관광지') AS name,
                        COALESCE(src.tourist_nm_en, src.attraction_name, 'Attraction') AS name_en,
                        COALESCE(src.spot_lat, cc.center_lat, %s) AS lat,
                        COALESCE(src.spot_lng, cc.center_lng, %s) AS lng,
                        'attraction' AS category,
                        COALESCE(src.road_addr, '') AS address,
                        COALESCE(src.road_addr_en, src.road_addr, '') AS address_en,
                        COALESCE(src.sigun_nm, '') AS region,
                        COALESCE(src.sigun_nm, '') AS region_en,
                        ROUND(
                            ST_Distance(
                                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                                ST_SetSRID(
                                    ST_MakePoint(COALESCE(src.spot_lng, cc.center_lng, %s), COALESCE(src.spot_lat, cc.center_lat, %s)),
                                    4326
                                )::geography
                            )::NUMERIC,
                            0
                        )::INT AS distance_m,
                        COALESCE(NULLIF(TRIM(src.image_urls), ''), NULL) AS image_url,
                        (src.spot_lat IS NULL OR src.spot_lng IS NULL) AS is_approximate_location,
                        NULL::TEXT AS event_start_date,
                        NULL::TEXT AS event_end_date,
                        NULL::TEXT AS event_url
                    FROM attraction_source src
                    LEFT JOIN city_centers cc
                      ON cc.city_name = COALESCE(src.sigun_nm, '')
                    WHERE COALESCE(TRIM(src.attraction_name), '') <> ''
                      AND ST_DWithin(
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                        ST_SetSRID(
                            ST_MakePoint(COALESCE(src.spot_lng, cc.center_lng, %s), COALESCE(src.spot_lat, cc.center_lat, %s)),
                            4326
                        )::geography,
                        %s
                      )
                    ORDER BY distance_m
                    LIMIT %s
                    """,
                    (
                        _DEFAULT_LAT,
                        _DEFAULT_LNG,
                        lng,
                        lat,
                        _DEFAULT_LNG,
                        _DEFAULT_LAT,
                        lng,
                        lat,
                        _DEFAULT_LNG,
                        _DEFAULT_LAT,
                        radius,
                        limit,
                    ),
                )
                results.extend(_normalize_place_row(dict(row)) for row in cursor.fetchall())

            if category in {"all", "restaurant"}:
                restaurant_image_expr = _restaurant_image_expr(cursor)
                cursor.execute(
                    f"""
                    SELECT
                        MD5(bizplc_nm || COALESCE(refine_roadnm_addr, '')) AS id,
                        bizplc_nm AS name,
                        COALESCE(NULLIF(TRIM(bizplc_nm_en), ''), bizplc_nm) AS name_en,
                        refine_wgs84_lat::FLOAT AS lat,
                        refine_wgs84_logt::FLOAT AS lng,
                        'restaurant' AS category,
                        COALESCE(refine_roadnm_addr, refine_lotno_addr, '') AS address,
                        COALESCE(NULLIF(TRIM(refine_roadnm_addr_en), ''), COALESCE(refine_roadnm_addr, refine_lotno_addr, '')) AS address_en,
                        COALESCE(sigun_nm, '') AS region,
                        COALESCE(sigun_nm, '') AS region_en,
                        ROUND(
                            ST_Distance(
                                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                                ST_SetSRID(
                                    ST_MakePoint(refine_wgs84_logt::FLOAT, refine_wgs84_lat::FLOAT),
                                    4326
                                )::geography
                        )::NUMERIC,
                            0
                        )::INT AS distance_m,
                        {restaurant_image_expr} AS image_url,
                        FALSE AS is_approximate_location,
                        NULL::TEXT AS event_start_date,
                        NULL::TEXT AS event_end_date,
                        NULL::TEXT AS event_url
                    FROM locallink.gg_restaurant_info
                    WHERE refine_wgs84_lat IS NOT NULL
                      AND refine_wgs84_logt IS NOT NULL
                      AND refine_wgs84_lat::TEXT <> 'NaN'
                      AND refine_wgs84_logt::TEXT <> 'NaN'
                      AND bsn_state_nm = '영업'
                      AND ST_DWithin(
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                        ST_SetSRID(
                            ST_MakePoint(refine_wgs84_logt::FLOAT, refine_wgs84_lat::FLOAT),
                            4326
                        )::geography,
                        %s
                      )
                    ORDER BY distance_m
                    LIMIT %s
                    """,
                    (lng, lat, lng, lat, radius, limit),
                )
                results.extend(_normalize_place_row(dict(row)) for row in cursor.fetchall())

            if category in {"all", "event"}:
                cursor.execute(
                    """
                    WITH city_centers AS (
                        SELECT
                            COALESCE(sigun_nm, '') AS city_name,
                            AVG(refine_wgs84_lat::FLOAT) AS center_lat,
                            AVG(refine_wgs84_logt::FLOAT) AS center_lng
                        FROM locallink.gg_restaurant_info
                        WHERE refine_wgs84_lat IS NOT NULL
                          AND refine_wgs84_logt IS NOT NULL
                          AND refine_wgs84_lat::TEXT <> 'NaN'
                          AND refine_wgs84_logt::TEXT <> 'NaN'
                          AND COALESCE(TRIM(sigun_nm), '') <> ''
                          AND bsn_state_nm = '영업'
                        GROUP BY COALESCE(sigun_nm, '')
                    ),
                    normalized_events AS (
                        SELECT
                            MD5(COALESCE(title, '') || '|' || COALESCE(url, '') || '|' || COALESCE(city, '')) AS id,
                            COALESCE(title, '') AS name,
                            COALESCE(NULLIF(TRIM(title_en), ''), COALESCE(title, '')) AS name_en,
                            COALESCE(inst_nm, '') AS address,
                            COALESCE(inst_nm, '') AS address_en,
                            COALESCE(city, '') AS region,
                            COALESCE(city, '') AS region_en,
                            COALESCE(url, '') AS event_url,
                            COALESCE(NULLIF(TRIM(image_url), ''), NULL) AS image_url,
                            CASE
                                WHEN begin_de ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN begin_de::DATE
                                ELSE NULL
                            END AS event_start_date,
                            CASE
                                WHEN end_de ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN end_de::DATE
                                ELSE NULL
                            END AS event_end_date
                        FROM locallink.gyeonggi_events
                        WHERE COALESCE(TRIM(title), '') <> ''
                          AND COALESCE(TRIM(city), '') <> ''
                    )
                    SELECT
                        ne.id,
                        ne.name,
                        ne.name_en,
                        COALESCE(cc.center_lat, %s) AS lat,
                        COALESCE(cc.center_lng, %s) AS lng,
                        'event' AS category,
                        ne.address,
                        ne.address_en,
                        ne.region,
                        ne.region_en,
                        ROUND(
                            ST_Distance(
                                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                                ST_SetSRID(
                                    ST_MakePoint(COALESCE(cc.center_lng, %s), COALESCE(cc.center_lat, %s)),
                                    4326
                                )::geography
                            )::NUMERIC,
                            0
                        )::INT AS distance_m,
                        ne.image_url AS image_url,
                        TRUE AS is_approximate_location,
                        ne.event_start_date::TEXT AS event_start_date,
                        ne.event_end_date::TEXT AS event_end_date,
                        ne.event_url
                    FROM normalized_events ne
                    LEFT JOIN city_centers cc
                      ON cc.city_name = ne.region
                    WHERE (ne.event_end_date IS NULL OR ne.event_end_date >= CURRENT_DATE)
                      AND ST_DWithin(
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                        ST_SetSRID(
                            ST_MakePoint(COALESCE(cc.center_lng, %s), COALESCE(cc.center_lat, %s)),
                            4326
                        )::geography,
                        %s
                      )
                    ORDER BY distance_m
                    LIMIT %s
                    """,
                    (
                        _DEFAULT_LAT,
                        _DEFAULT_LNG,
                        lng,
                        lat,
                        _DEFAULT_LNG,
                        _DEFAULT_LAT,
                        lng,
                        lat,
                        _DEFAULT_LNG,
                        _DEFAULT_LAT,
                        radius,
                        limit,
                    ),
                )
                results.extend(_normalize_place_row(dict(row)) for row in cursor.fetchall())

    results.sort(key=lambda row: row.get("distance_m") or 0)
    if category == "all":
        return results
    return results[: max(limit, 1)]


@ios_api_bp.route("/api/ios/v1/places", methods=["GET"])
@_require_api_key
def api_ios_places():
    try:
        lat = _parse_float_arg("lat", _DEFAULT_LAT)
        lng = _parse_float_arg("lng", _DEFAULT_LNG)
        radius = _parse_int_arg("radius", _DEFAULT_RADIUS)
        limit = _parse_int_arg("limit", _DEFAULT_LIMIT)
    except ValueError:
        return jsonify({"error": "invalid numeric query params"}), 400

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


@ios_api_bp.route("/api/ios/v1/weather", methods=["GET"])
@_require_api_key
def api_ios_weather():
    try:
        lat = _parse_float_arg("lat", _DEFAULT_LAT)
        lng = _parse_float_arg("lng", _DEFAULT_LNG)
    except ValueError:
        return jsonify({"error": "invalid numeric query params"}), 400

    payload, status_code = create_weather_payload(lat=lat, lng=lng)
    return jsonify(payload), status_code, {"Cache-Control": _WEATHER_HTTP_CACHE_CONTROL}


@ios_api_bp.route("/api/ios/v1/docent/script", methods=["POST"])
@_require_api_key
def api_ios_docent_script():
    payload = request.get_json(silent=True) or {}
    response_payload, status_code = create_docent_script_payload(payload)
    return jsonify(response_payload), status_code


@ios_api_bp.route("/api/ios/v1/docent/audio", methods=["POST"])
@_require_api_key
def api_ios_docent_audio():
    payload = request.get_json(silent=True) or {}
    response_payload, status_code, mime_type = create_docent_audio_payload(payload)
    if mime_type == "audio/mpeg":
        return Response(response_payload, mimetype=mime_type, status=status_code)
    return jsonify(response_payload), status_code


@ios_api_bp.route("/api/ios/v1/health", methods=["GET"])
@_require_api_key
def api_ios_health():
    db_status = "ok"
    speech_status = "ok"
    openai_status = "ok"

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
    except Exception:
        db_status = "error"

    if not (os.getenv("AZURE_SPEECH_KEY") and os.getenv("AZURE_SPEECH_REGION")):
        speech_status = "missing_config"

    if not (
        os.getenv("AZURE_OPENAI_ENDPOINT")
        and os.getenv("AZURE_OPENAI_KEY")
        and os.getenv("AZURE_OPENAI_VERSION")
        and (os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or os.getenv("AZURE_OPENAI_DEPLOYMENT"))
    ):
        openai_status = "missing_config"

    status = "ok"
    if any(value != "ok" for value in (db_status, speech_status, openai_status)):
        status = "degraded"

    return jsonify(
        {
            "status": status,
            "db": db_status,
            "speech": speech_status,
            "openai": openai_status,
        }
    )
