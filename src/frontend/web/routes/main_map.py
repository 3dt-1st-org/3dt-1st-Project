import math
import os
from datetime import datetime, timedelta

import psycopg2.extras
import requests as http_requests
from dotenv import load_dotenv
from flask import Blueprint, jsonify, render_template, request

from src.frontend.web.services.db import get_db_connection

load_dotenv()

main_map_bp = Blueprint("main_map", __name__)

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

_DEFAULT_LAT = 37.2636
_DEFAULT_LNG = 127.0286
_DEFAULT_RADIUS = 3000

_WEATHER_API_URL = (
    "http://apis.data.go.kr/1360000/"
    "VilageFcstInfoService_2.0/getUltraSrtNcst"
)


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


@main_map_bp.route("/map")
def map_view():
    return render_template("map/index.html")


@main_map_bp.route("/api/weather")
def api_weather():
    try:
        lat = float(request.args.get("lat", _DEFAULT_LAT))
        lng = float(request.args.get("lng", _DEFAULT_LNG))
    except ValueError:
        return jsonify({"error": "잘못된 파라미터"}), 400

    api_key = (os.getenv("WEATHER_API_KEY") or "").strip()
    if not api_key:
        return jsonify({"error": "WEATHER_API_KEY가 설정되지 않았습니다."}), 503

    now = datetime.now() - timedelta(hours=1)
    base_date = now.strftime("%Y%m%d")
    base_time = now.strftime("%H00")
    nx, ny = _latlon_to_grid(lat, lng)

    try:
        resp = http_requests.get(
            _WEATHER_API_URL,
            params={
                "pageNo": "1",
                "numOfRows": "20",
                "dataType": "JSON",
                "base_date": base_date,
                "base_time": base_time,
                "nx": nx,
                "ny": ny,
                "serviceKey": api_key,
            },
            timeout=5,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload["response"]["header"]["resultCode"] != "00":
            return jsonify({"error": payload["response"]["header"]["resultMsg"]}), 502

        items = {
            item["category"]: item["obsrValue"]
            for item in payload["response"]["body"]["items"]["item"]
        }
        temp = items.get("T1H", "--")
        pty = items.get("PTY", "0")
        icon = _PTY_ICON.get(str(int(float(pty))), "🌡️")
        return jsonify({"temp": temp, "icon": icon})

    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@main_map_bp.route("/api/places")
def api_places():
    try:
        lat = float(request.args.get("lat", _DEFAULT_LAT))
        lng = float(request.args.get("lng", _DEFAULT_LNG))
        radius = int(request.args.get("radius", _DEFAULT_RADIUS))
        category = request.args.get("category", "all")
    except ValueError:
        return jsonify({"error": "잘못된 파라미터입니다."}), 400

    results = []

    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                if category in ("all", "attraction"):
                    cur.execute(
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
                        )
                        SELECT
                            MD5(COALESCE(ad.attraction_name, '') || '|' || COALESCE(ad.sigun_nm, '')) AS id,
                            COALESCE(ad.attraction_name, '관광지') AS name,
                            COALESCE(cc.center_lat, %s) AS lat,
                            COALESCE(cc.center_lng, %s) AS lng,
                            'attraction' AS category,
                            '' AS address,
                            COALESCE(ad.sigun_nm, '') AS region,
                            ROUND(
                                ST_Distance(
                                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                                    ST_SetSRID(
                                        ST_MakePoint(COALESCE(cc.center_lng, %s), COALESCE(cc.center_lat, %s)),
                                        4326
                                    )::geography
                                )::NUMERIC,
                                0
                            )::INT AS distance_m
                        FROM locallink.attraction_descriptions ad
                        LEFT JOIN city_centers cc
                          ON cc.city_name = COALESCE(ad.sigun_nm, '')
                        WHERE COALESCE(TRIM(ad.attraction_name), '') <> ''
                          AND ST_DWithin(
                            ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                            ST_SetSRID(
                                ST_MakePoint(COALESCE(cc.center_lng, %s), COALESCE(cc.center_lat, %s)),
                                4326
                            )::geography,
                            %s
                          )
                        ORDER BY distance_m
                        LIMIT 50
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
                        ),
                    )
                    results.extend(dict(row) for row in cur.fetchall())

                if category in ("all", "restaurant"):
                    cur.execute(
                        """
                        SELECT
                            MD5(bizplc_nm || COALESCE(refine_roadnm_addr, '')) AS id,
                            bizplc_nm AS name,
                            refine_wgs84_lat::FLOAT AS lat,
                            refine_wgs84_logt::FLOAT AS lng,
                            'restaurant' AS category,
                            COALESCE(refine_roadnm_addr, refine_lotno_addr, '') AS address,
                            sigun_nm AS region,
                            ROUND(
                                ST_Distance(
                                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                                    ST_SetSRID(
                                        ST_MakePoint(refine_wgs84_logt::FLOAT, refine_wgs84_lat::FLOAT),
                                        4326
                                    )::geography
                                )::NUMERIC,
                                0
                            )::INT AS distance_m
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
                        LIMIT 50
                        """,
                        (lng, lat, lng, lat, radius),
                    )
                    results.extend(dict(row) for row in cur.fetchall())

    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    results.sort(key=lambda item: item.get("distance_m") or 0)
    return jsonify({"count": len(results), "places": results})
