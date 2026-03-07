from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import psycopg2.extras
from flask import Blueprint, jsonify, render_template, request

from src.frontend.web.services.db import get_db_connection

dashboard_bp = Blueprint("dashboard", __name__)
logger = logging.getLogger(__name__)

# ── 33개 수도권 도시 좌표 (카카오맵 버블 표시용) ──────────────────────────
_CITY_COORDS: dict[str, tuple[float, float]] = {
    "서울":   (37.5665, 126.9780),
    "인천":   (37.4563, 126.7052),
    "수원":   (37.2636, 127.0286),
    "성남":   (37.4196, 127.1267),
    "의정부": (37.7381, 127.0344),
    "안양":   (37.3943, 126.9568),
    "부천":   (37.5035, 126.7660),
    "광명":   (37.4786, 126.8640),
    "평택":   (36.9921, 127.1127),
    "동두천": (37.9032, 127.0606),
    "안산":   (37.3219, 126.8309),
    "고양":   (37.6584, 126.8320),
    "과천":   (37.4291, 126.9874),
    "구리":   (37.5943, 127.1298),
    "남양주": (37.6357, 127.2159),
    "오산":   (37.1497, 127.0769),
    "시흥":   (37.3801, 126.8030),
    "군포":   (37.3616, 126.9354),
    "의왕":   (37.3447, 126.9685),
    "하남":   (37.5393, 127.2148),
    "용인":   (37.2411, 127.1775),
    "파주":   (37.7599, 126.7099),
    "이천":   (37.2723, 127.4348),
    "안성":   (36.9956, 127.2695),
    "김포":   (37.6151, 126.7156),
    "화성":   (37.1993, 126.8312),
    "광주":   (37.4295, 127.2555),
    "양주":   (37.7852, 127.0459),
    "포천":   (37.8951, 127.2002),
    "여주":   (37.2977, 127.6376),
    "연천":   (38.0961, 127.0748),
    "가평":   (37.8314, 127.5089),
    "양평":   (37.4916, 127.4874),
}

_VALID_LOCATIONS: frozenset[str] = frozenset(_CITY_COORDS.keys())

_STATUS_CATEGORY: dict[str, str] = {
    "야외활동 쾌적":    "good",
    "보통":          "fair",
    "미세먼지 나쁨":   "poor",
    "미세먼지 매우나쁨": "poor",
    "비/눈":         "rain",
}


# ── 헬퍼 ──────────────────────────────────────────────────────────────────
def _pm10_grade(val) -> str:
    if val is None:
        return "unknown"
    v = int(val)
    if v <= 30:
        return "good"
    if v <= 80:
        return "normal"
    if v <= 150:
        return "bad"
    return "very_bad"


def _pm25_grade(val) -> str:
    if val is None:
        return "unknown"
    v = int(val)
    if v <= 15:
        return "good"
    if v <= 35:
        return "normal"
    if v <= 75:
        return "bad"
    return "very_bad"


def _delta_info(current, prev) -> dict:
    if current is None or prev is None:
        return {"value": None, "str": "—", "up": None}
    delta = round(float(current) - float(prev), 1)
    if delta > 0:
        arrow = "▲"
    elif delta < 0:
        arrow = "▼"
    else:
        arrow = "—"
    return {"value": delta, "str": f"{arrow} {abs(delta)}", "up": delta > 0}


def _fmt_ts(ts) -> str:
    if ts is None:
        return "—"
    if isinstance(ts, str):
        return ts
    try:
        return ts.isoformat()
    except Exception:
        return str(ts)


# ── 라우트 ────────────────────────────────────────────────────────────────
@dashboard_bp.route("/dashboard")
def dashboard_view():
    return render_template("dashboard/index.html")


@dashboard_bp.route("/api/dashboard/data")
def api_dashboard_data():
    raw_loc = (request.args.get("location") or "").strip()
    # 허용된 도시명 또는 빈 문자열(전체)만 허용
    location: str = raw_loc if raw_loc in _VALID_LOCATIONS else ""

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1) 33개 도시 최신 레코드 한 방에 (지도 + 도넛 + TOP5)
        cur.execute("""
            SELECT DISTINCT ON (location)
                location, record_time, temperature, pm10, pm25,
                wind_speed, outdoor_status
            FROM locallink.realtime_weather_conditions
            ORDER BY location, record_time DESC
        """)
        all_latest = cur.fetchall()

        # 2) KPI 현재값
        if location:
            cur.execute("""
                SELECT temperature, pm10, pm25, wind_speed,
                       outdoor_status, record_time
                FROM locallink.realtime_weather_conditions
                WHERE location = %s
                ORDER BY record_time DESC
                LIMIT 1
            """, (location,))
            kpi_cur_row = cur.fetchone()

            # KPI 이전값 (직전 30분 윈도우)
            cur.execute("""
                SELECT temperature, pm10, pm25, wind_speed
                FROM locallink.realtime_weather_conditions
                WHERE location = %s
                ORDER BY record_time DESC
                LIMIT 1 OFFSET 1
            """, (location,))
            kpi_prv_row = cur.fetchone()
        else:
            # 전체 평균: 가장 최신 record_time 윈도우
            cur.execute("""
                WITH latest AS (
                    SELECT MAX(record_time) AS max_t
                    FROM locallink.realtime_weather_conditions
                )
                SELECT
                    ROUND(AVG(w.temperature)::numeric, 1) AS temperature,
                    ROUND(AVG(w.pm10)::numeric)           AS pm10,
                    ROUND(AVG(w.pm25)::numeric)           AS pm25,
                    ROUND(AVG(w.wind_speed)::numeric, 1)  AS wind_speed,
                    MAX(w.record_time)                    AS record_time
                FROM locallink.realtime_weather_conditions w
                JOIN latest ON w.record_time = latest.max_t
            """)
            kpi_cur_row = cur.fetchone()

            # 전체 평균 이전 윈도우
            cur.execute("""
                WITH second_time AS (
                    SELECT DISTINCT record_time
                    FROM locallink.realtime_weather_conditions
                    ORDER BY record_time DESC
                    LIMIT 1 OFFSET 1
                )
                SELECT
                    ROUND(AVG(w.temperature)::numeric, 1) AS temperature,
                    ROUND(AVG(w.pm10)::numeric)           AS pm10,
                    ROUND(AVG(w.pm25)::numeric)           AS pm25,
                    ROUND(AVG(w.wind_speed)::numeric, 1)  AS wind_speed
                FROM locallink.realtime_weather_conditions w
                JOIN second_time st ON w.record_time = st.record_time
            """)
            kpi_prv_row = cur.fetchone()

        # 3) 12시간 트렌드
        if location:
            cur.execute("""
                SELECT
                    record_time,
                    ROUND(temperature::numeric, 1) AS temperature,
                    pm25
                FROM locallink.realtime_weather_conditions
                WHERE location = %s
                  AND record_time >= NOW() - INTERVAL '12 hours'
                ORDER BY record_time ASC
            """, (location,))
        else:
            cur.execute("""
                SELECT
                    record_time,
                    ROUND(AVG(temperature)::numeric, 1) AS temperature,
                    ROUND(AVG(pm25)::numeric)           AS pm25
                FROM locallink.realtime_weather_conditions
                WHERE record_time >= NOW() - INTERVAL '12 hours'
                GROUP BY record_time
                ORDER BY record_time ASC
            """)
        trend_rows = cur.fetchall()

        # 4) Raw data 최근 20개
        if location:
            cur.execute("""
                SELECT location, record_time, temperature,
                       pm10, pm25, wind_speed, outdoor_status
                FROM locallink.realtime_weather_conditions
                WHERE location = %s
                ORDER BY record_time DESC
                LIMIT 20
            """, (location,))
        else:
            cur.execute("""
                SELECT location, record_time, temperature,
                       pm10, pm25, wind_speed, outdoor_status
                FROM locallink.realtime_weather_conditions
                ORDER BY record_time DESC
                LIMIT 20
            """)
        raw_rows = cur.fetchall()

        cur.close()
        conn.close()

    except Exception:
        logger.exception("Dashboard data query failed")
        return jsonify({"error": "데이터 조회 오류가 발생했습니다."}), 500

    # ── 가공 ─────────────────────────────────────────────────────────────
    kpi_cur = dict(kpi_cur_row) if kpi_cur_row else {}
    kpi_prv = dict(kpi_prv_row) if kpi_prv_row else {}

    kpi = {
        "temperature": {
            "value": kpi_cur.get("temperature"),
            "delta": _delta_info(kpi_cur.get("temperature"), kpi_prv.get("temperature")),
            "grade": "neutral",
        },
        "pm10": {
            "value": kpi_cur.get("pm10"),
            "delta": _delta_info(kpi_cur.get("pm10"), kpi_prv.get("pm10")),
            "grade": _pm10_grade(kpi_cur.get("pm10")),
        },
        "pm25": {
            "value": kpi_cur.get("pm25"),
            "delta": _delta_info(kpi_cur.get("pm25"), kpi_prv.get("pm25")),
            "grade": _pm25_grade(kpi_cur.get("pm25")),
        },
        "wind_speed": {
            "value": kpi_cur.get("wind_speed"),
            "delta": _delta_info(kpi_cur.get("wind_speed"), kpi_prv.get("wind_speed")),
            "grade": "neutral",
        },
    }

    last_refreshed = _fmt_ts(kpi_cur.get("record_time"))

    # 도넛 차트: outdoor_status 카테고리 집계
    status_counts: dict[str, int] = {"good": 0, "fair": 0, "poor": 0, "rain": 0}
    for row in all_latest:
        cat = _STATUS_CATEGORY.get(row["outdoor_status"] or "", "fair")
        status_counts[cat] += 1

    donut = {
        "labels": ["야외활동 쾌적", "보통", "미세먼지 나쁨", "비/눈"],
        "data":   [
            status_counts["good"],
            status_counts["fair"],
            status_counts["poor"],
            status_counts["rain"],
        ],
        "colors": ["#48BB78", "#ECC94B", "#FC8181", "#90CDF4"],
    }

    # TOP 5 PM10 도시
    top5 = sorted(
        [r for r in all_latest if r["pm10"] is not None],
        key=lambda r: int(r["pm10"]),
        reverse=True,
    )[:5]
    bar_top5 = [
        {
            "location": r["location"],
            "pm10":     int(r["pm10"]),
            "pm25":     int(r["pm25"]) if r["pm25"] is not None else 0,
        }
        for r in top5
    ]

    # 꺾은선 트렌드
    KST = timezone(timedelta(hours=9))
    trend = {
        "labels": [
            (row["record_time"].astimezone(KST).strftime("%H:%M")
             if hasattr(row["record_time"], "astimezone")
             else str(row["record_time"])[:16])
            for row in trend_rows
        ],
        "temperature": [
            float(r["temperature"]) if r["temperature"] is not None else None
            for r in trend_rows
        ],
        "pm25": [
            int(r["pm25"]) if r["pm25"] is not None else None
            for r in trend_rows
        ],
    }

    # 지도 버블 데이터
    map_data = []
    for row in all_latest:
        coords = _CITY_COORDS.get(row["location"])
        if not coords:
            continue
        map_data.append({
            "location":     row["location"],
            "lat":          coords[0],
            "lng":          coords[1],
            "pm10":         int(row["pm10"]) if row["pm10"] is not None else 0,
            "pm25":         int(row["pm25"]) if row["pm25"] is not None else 0,
            "temperature":  float(row["temperature"]) if row["temperature"] is not None else None,
            "wind_speed":   float(row["wind_speed"]) if row["wind_speed"] is not None else None,
            "outdoor_status": row["outdoor_status"] or "",
            "pm10_grade":   _pm10_grade(row["pm10"]),
        })

    # Raw data (timestamp → ISO string)
    raw_data = [
        {
            "location":     r["location"],
            "record_time":  _fmt_ts(r["record_time"]),
            "temperature":  float(r["temperature"]) if r["temperature"] is not None else None,
            "pm10":         int(r["pm10"]) if r["pm10"] is not None else None,
            "pm25":         int(r["pm25"]) if r["pm25"] is not None else None,
            "wind_speed":   float(r["wind_speed"]) if r["wind_speed"] is not None else None,
            "outdoor_status": r["outdoor_status"] or "",
        }
        for r in raw_rows
    ]

    return jsonify({
        "kpi":              kpi,
        "donut":            donut,
        "bar_top5":         bar_top5,
        "trend":            trend,
        "map_data":         map_data,
        "raw_data":         raw_data,
        "locations":        sorted(_VALID_LOCATIONS),
        "last_refreshed":   last_refreshed,
        "selected_location": location or "전체",
    })


@dashboard_bp.route("/api/dashboard/narrative", methods=["POST"])
def api_dashboard_narrative():
    body = request.get_json(silent=True) or {}
    kpi      = body.get("kpi") or {}
    bar_top5 = body.get("bar_top5") or []
    donut    = body.get("donut") or {}
    location = (body.get("selected_location") or "전체").strip()

    temp_val  = (kpi.get("temperature") or {}).get("value")
    pm10_val  = (kpi.get("pm10") or {}).get("value")
    pm25_val  = (kpi.get("pm25") or {}).get("value")
    temp_delta_str = (kpi.get("temperature") or {}).get("delta", {}).get("str", "")

    def _fallback() -> str:
        parts = []
        if bar_top5:
            t = bar_top5[0]
            parts.append(f"현재 PM10 농도가 가장 높은 지역은 {t['location']}({t['pm10']}㎍/㎥)입니다.")
        if temp_val is not None:
            td = f" ({temp_delta_str})" if temp_delta_str and temp_delta_str != "—" else ""
            parts.append(f"선택 지역의 현재 기온은 {temp_val}°C{td}입니다.")
        if pm10_val is not None:
            grade_ko = {"good": "좋음", "normal": "보통", "bad": "나쁨", "very_bad": "매우나쁨"}.get(
                _pm10_grade(pm10_val), "보통"
            )
            parts.append(f"PM10 {pm10_val}㎍/㎥(상태: {grade_ko}), PM2.5 {pm25_val}㎍/㎥입니다.")
        donut_data = donut.get("data") or []
        if len(donut_data) >= 1:
            total = sum(donut_data) or 1
            good_pct = round(donut_data[0] / total * 100)
            parts.append(f"수도권 {total}개 도시 중 {donut_data[0]}개({good_pct}%)가 야외활동 쾌적 상태입니다.")
        return " ".join(parts) if parts else "현재 수도권 대기 데이터를 불러오는 중입니다."

    try:
        from config.vault_manager import get_vault_manager
        from openai import AzureOpenAI

        vm = get_vault_manager()
        endpoint   = vm.get_secret("azure-openai-endpoint")
        key        = vm.get_secret("azure-openai-key")
        version    = vm.get_secret("azure-openai-version")
        deployment = vm.get_secret("azure-openai-deployment-name")

        if not all([endpoint, key, version, deployment]):
            raise ValueError("Azure OpenAI 시크릿 누락")

        # 검증 후 str 타입 보장
        endpoint   = str(endpoint)
        key        = str(key)
        version    = str(version)
        deployment = str(deployment)

        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=key,
            api_version=version,
            timeout=5.0,
        )

        top5_str = ", ".join(
            f'{b["location"]}({b["pm10"]}㎍/㎥)' for b in bar_top5
        )
        donut_data = donut.get("data") or []
        good_cnt = donut_data[0] if donut_data else 0
        poor_cnt = donut_data[2] if len(donut_data) > 2 else 0
        total_cnt = sum(donut_data) if donut_data else 0

        summary = (
            f"선택 지역: {location}\n"
            f"현재 기온: {temp_val}°C ({temp_delta_str})\n"
            f"PM10: {pm10_val}㎍/㎥ / PM2.5: {pm25_val}㎍/㎥\n"
            f"PM10 상위 5개 도시: {top5_str}\n"
            f"수도권 {total_cnt}개 도시 중 야외활동 쾌적: {good_cnt}개, 미세먼지 나쁨: {poor_cnt}개"
        )

        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 수도권 실시간 날씨·대기질 대시보드의 AI 브리핑 도우미입니다. "
                        "주어진 데이터를 바탕으로 2~3문장의 자연스러운 한국어 브리핑을 작성하세요. "
                        "수치를 구체적으로 언급하고 야외활동 권장 여부를 포함해 주세요."
                    ),
                },
                {
                    "role": "user",
                    "content": f"다음 데이터를 분석하여 브리핑 문장을 작성해 주세요:\n{summary}",
                },
            ],
            max_tokens=200,
            temperature=0.4,
        )
        raw_content = response.choices[0].message.content
        narrative = raw_content.strip() if raw_content else _fallback()
    except Exception:
        logger.info("Azure OpenAI narrative 생성 불가, fallback 사용")
        narrative = _fallback()

    return jsonify({"narrative": narrative})
