from __future__ import annotations

import concurrent.futures
from typing import Any

# ── 모듈 레벨 싱글턴 (last_weather_state 유지 필수) ──────────────────────
_intervention_manager: "_WeatherInterventionManager | None" = None


def _get_intervention_manager(lat: float, lng: float) -> "_WeatherInterventionManager":
    """같은 위치라면 인스턴스를 재사용해 last_weather_state를 보존한다."""
    global _intervention_manager
    if _intervention_manager is None:
        _intervention_manager = _WeatherInterventionManager(lat, lng)
    return _intervention_manager


class _WeatherInterventionManager:
    def __init__(self, lat: float, lng: float) -> None:
        from src.services.weather_planner import WeatherTravelPlanner
        self._planner = WeatherTravelPlanner(lat, lng)

    def get_intervention(self, lat: float, lng: float, radius_m: int = 10000):
        """날씨 변화가 감지되면 (places, type)를 반환, 없으면 None."""
        # 좌표가 크게 변하면 동일 planner 재사용 (last_weather_state 유지)
        self._planner.lat = lat
        self._planner.lng = lng
        return self._planner.check_and_propose_intervention(radius_m=radius_m)


# ── 하루 일정 ─────────────────────────────────────────────────────────────

def create_daily_plan_payload(
    lat: float,
    lng: float,
    language: str = "English",
    timeout_sec: int = 30,
) -> tuple[dict[str, Any], int]:
    """
    DailyTravelPlanner.create_daily_plan()을 최대 timeout_sec 초 안에 실행한다.
    도슨트 없는 슬롯은 script="" 로 허용한다.
    """
    def _run():
        from src.services.daily_planner import DailyTravelPlanner
        planner = DailyTravelPlanner(lat, lng)
        return planner.create_daily_plan(language=language)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run)
            result = future.result(timeout=timeout_sec)
    except concurrent.futures.TimeoutError:
        return {"error": "planner timed out"}, 504
    except Exception as exc:
        return {"error": str(exc)}, 500

    if "error" in result:
        return {"error": result["error"]}, 500

    # plan 항목 정규화: script 키 누락 방지
    for item in result.get("plan", []):
        item.setdefault("script", "")
        place = item.get("place") or {}
        item["place"] = {
            "name": place.get("name") or place.get("tourist_nm", ""),
            "lat": place.get("lat"),
            "lng": place.get("lng"),
            "road_addr": place.get("road_addr", ""),
            "source_type": place.get("source_type", "attraction"),
            "itinerary_role": place.get("itinerary_role", ""),
        }

    return result, 200


# ── 날씨 개입 개요 ──────────────────────────────────────────────────────────

def create_intervention_payload(
    lat: float,
    lng: float,
    radius_m: int = 10000,
) -> tuple[dict[str, Any], int]:
    try:
        manager = _get_intervention_manager(lat, lng)
        result = manager.get_intervention(lat, lng, radius_m=radius_m)
    except Exception as exc:
        return {"error": str(exc)}, 500

    if result is None:
        return {"intervention": None}, 200

    places, alert_type = result
    serialized = []
    for p in places:
        serialized.append({
            "name": p.get("name", ""),
            "lat": p.get("lat"),
            "lng": p.get("lng"),
            "dist": p.get("dist"),
            "road_addr": p.get("road_addr", ""),
            "source_type": p.get("source_type", "attraction"),
        })

    return {"intervention": {"type": alert_type, "places": serialized}}, 200
