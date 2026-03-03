import os
import math
import psycopg2
import psycopg2.extras
from flask import Blueprint, render_template, request, jsonify

main_map_bp = Blueprint("main_map", __name__)

# ==============================================================================
# DB 연결 헬퍼
# ==============================================================================
def _get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "postgres"),
        user=os.getenv("DB_USER", "admin_user"),
        password=os.getenv("DB_PASSWORD", ""),
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
        lat    = float(request.args.get("lat",    37.2636))
        lng    = float(request.args.get("lng",    127.0286))
        radius = int(request.args.get("radius",   3000))
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

