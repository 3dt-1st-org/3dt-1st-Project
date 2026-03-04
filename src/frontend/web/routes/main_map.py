import math
import psycopg2
import psycopg2.extras
import requests as http_requests
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify
from dotenv import load_dotenv
from config.vault_manager import vault

load_dotenv()  # KEY_VAULT_URL을 .env에서 읽기 위해 유지

main_map_bp = Blueprint("main_map", __name__)

# DB 설정 — 모듈 임포트 시 1회만 Key Vault 조회 (요청마다 네트워크 호출 방지)
_DB_HOST = vault.get_secret("lala-db-host")
_DB_PORT = int(vault.get_secret("lala-db-port"))
_DB_NAME = vault.get_secret("lala-db-name")
_DB_USER = vault.get_secret("lala-db-user")
_DB_PASS = vault.get_secret("lala-db-password")

# ==============================================================================
# 기상청 LCC 격자 변환 (notebooks/validation/api-test.ipynb 참고)
# ==============================================================================
_RE, _GRID = 6371.00877, 5.0
_SLAT1, _SLAT2, _OLON, _OLAT, _XO, _YO = 30.0, 60.0, 126.0, 38.0, 43, 136

def _latlon_to_grid(lat: float, lon: float) -> tuple:
    DEGRAD = math.pi / 180.0
    re = _RE / _GRID
    slat1, slat2 = _SLAT1 * DEGRAD, _SLAT2 * DEGRAD
    olon, olat   = _OLON  * DEGRAD, _OLAT  * DEGRAD
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / \
         math.log(math.tan(math.pi * .25 + slat2 * .5) / math.tan(math.pi * .25 + slat1 * .5))
    sf = (math.tan(math.pi * .25 + slat1 * .5) ** sn) * math.cos(slat1) / sn
    ro = re * sf / (math.tan(math.pi * .25 + olat * .5) ** sn)
    ra = re * sf / (math.tan(math.pi * .25 + lat * DEGRAD * .5) ** sn)
    theta = (lon * DEGRAD - olon) * sn
    if theta >  math.pi: theta -= 2 * math.pi
    if theta < -math.pi: theta += 2 * math.pi
    return int(ra * math.sin(theta) + _XO + .5), int(ro - ra * math.cos(theta) + _YO + .5)

_PTY_ICON = {"0": "☀️", "1": "🌧️", "2": "🌨️", "3": "❄️",
             "5": "🌦️", "6": "🌨️", "7": "🌨️"}

# 기본 좌표 (수원시청) — 위치 권한 거부 시 fallback
_DEFAULT_LAT    = 37.2636
_DEFAULT_LNG    = 127.0286
_DEFAULT_RADIUS = 3_000   # 미터

# 기상청 초단기실황 API URL
_WEATHER_API_URL = (
    "http://apis.data.go.kr/1360000/"
    "VilageFcstInfoService_2.0/getUltraSrtNcst"
)

# ==============================================================================
# DB 연결 헬퍼
# ==============================================================================
def _get_conn():
    return psycopg2.connect(
        host=_DB_HOST,
        port=_DB_PORT,
        dbname=_DB_NAME,
        user=_DB_USER,
        password=_DB_PASS,
        sslmode="require",                 # Azure PostgreSQL 필수
        connect_timeout=5,
    )


# ==============================================================================
# /map  — 지도 페이지 서빙
# ==============================================================================
@main_map_bp.route("/map")
def map_view():
    return render_template("map/index.html")


# ==============================================================================
# /api/weather  — 기상청 초단기실황 (T1H 기온, PTY 강수형태)
#
# Query params: lat (float), lng (float)
# ==============================================================================
@main_map_bp.route("/api/weather")
def api_weather():
    try:
        lat = float(request.args.get("lat", _DEFAULT_LAT))
        lng = float(request.args.get("lng", _DEFAULT_LNG))
    except ValueError:
        return jsonify({"error": "잘못된 파라미터"}), 400

    api_key = vault.get_secret("weather-api-key")
    if not api_key:
        return jsonify({"error": "weather-api-key 시크릿 없음"}), 503

    # 기상청 API는 ~10분 지연 → 안전하게 1시간 전 기준시 사용
    now = datetime.now() - timedelta(hours=1)
    base_date = now.strftime("%Y%m%d")
    base_time = now.strftime("%H00")
    nx, ny = _latlon_to_grid(lat, lng)

    try:
        resp = http_requests.get(
            _WEATHER_API_URL,
            params={
                "pageNo": "1", "numOfRows": "20", "dataType": "JSON",
                "base_date": base_date, "base_time": base_time,
                "nx": nx, "ny": ny, "serviceKey": api_key,
            },
            timeout=5,
        )
        resp.raise_for_status()
        body = resp.json()["response"]["body"]
        if resp.json()["response"]["header"]["resultCode"] != "00":
            return jsonify({"error": resp.json()["response"]["header"]["resultMsg"]}), 502

        items = {i["category"]: i["obsrValue"] for i in body["items"]["item"]}
        temp = items.get("T1H", "--")
        pty  = items.get("PTY", "0")
        icon = _PTY_ICON.get(str(int(float(pty))), "🌡️")
        return jsonify({"temp": temp, "icon": icon})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==============================================================================
# /api/places  — PostGIS 반경 조회 JSON API
#
# Query params:
#   lat    (float) 중심 위도         기본: 37.2636 (수원시청)
#   lng    (float) 중심 경도         기본: 127.0286
#   radius (int)   반경(미터)         기본: 3000
#   category (str) attraction | restaurant | all   기본: all
# ==============================================================================
@main_map_bp.route("/api/places")
def api_places():
    try:
        lat    = float(request.args.get("lat",    _DEFAULT_LAT))
        lng    = float(request.args.get("lng",    _DEFAULT_LNG))
        radius = int(request.args.get("radius",   _DEFAULT_RADIUS))
        category = request.args.get("category", "all")
    except ValueError:
        return jsonify({"error": "잘못된 파라미터입니다."}), 400

    results = []

    try:
        conn = _get_conn()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # ── 명소 (gyeonggi_attractions) ──────────────────────────────
        if category in ("all", "attraction"):
            cur.execute("""
                SELECT
                    id::TEXT                    AS id,
                    attraction_name             AS name,
                    latitude                    AS lat,
                    longitude                   AS lng,
                    'attraction'                AS category,
                    COALESCE(road_address, lot_address, '') AS address,
                    city_county_name            AS region,
                    ROUND(
                        ST_Distance(
                            ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                            ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
                        )::NUMERIC, 0
                    )::INT                      AS distance_m
                FROM gyeonggi_attractions
                WHERE
                    latitude  IS NOT NULL
                    AND longitude IS NOT NULL
                    AND ST_DWithin(
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                        ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography,
                        %s
                    )
                ORDER BY distance_m
                LIMIT 50
            """, (lng, lat, lng, lat, radius))
            results += [dict(row) for row in cur.fetchall()]

        # ── 음식점 (locallink.gg_restaurant_info) ─────────────────────
        if category in ("all", "restaurant"):
            cur.execute("""
                SELECT
                    MD5(bizplc_nm || COALESCE(refine_roadnm_addr,'')) AS id,
                    bizplc_nm                   AS name,
                    refine_wgs84_lat::FLOAT     AS lat,
                    refine_wgs84_logt::FLOAT    AS lng,
                    'restaurant'                AS category,
                    COALESCE(refine_roadnm_addr, refine_lotno_addr, '') AS address,
                    sigun_nm                    AS region,
                    ROUND(
                        ST_Distance(
                            ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                            ST_SetSRID(ST_MakePoint(refine_wgs84_logt::FLOAT,
                                                    refine_wgs84_lat::FLOAT), 4326)::geography
                        )::NUMERIC, 0
                    )::INT                      AS distance_m
                FROM locallink.gg_restaurant_info
                WHERE
                    refine_wgs84_lat IS NOT NULL
                    AND refine_wgs84_logt IS NOT NULL
                    AND unity_bsn_state_nm = '영업'
                    AND ST_DWithin(
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                        ST_SetSRID(ST_MakePoint(refine_wgs84_logt::FLOAT,
                                                refine_wgs84_lat::FLOAT), 4326)::geography,
                        %s
                    )
                ORDER BY distance_m
                LIMIT 50
            """, (lng, lat, lng, lat, radius))
            results += [dict(row) for row in cur.fetchall()]

        cur.close()
        conn.close()

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # 거리순 정렬 후 반환
    results.sort(key=lambda x: x.get("distance_m") or 0)
    return jsonify({"count": len(results), "places": results})

