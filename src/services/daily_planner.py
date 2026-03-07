"""
DailyTravelPlanner: 하루 일정을 자동으로 계획해주는 서비스
- 오전/오후 명소(Attraction) 고정 추천
- 중복 장소 방지 및 문맥 인지형 도슨트 멘트
- DB 조회 에러 방어 로직 적용
"""

import sys
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Optional
import os
import math
import re
import concurrent.futures

# 프로젝트 루트 설정
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.weather_planner import WeatherTravelPlanner


class DailyTravelPlanner:
    """
    아침에 하루 일정을 계획해주는 플래너
    """
    
    def __init__(self, latitude: float, longitude: float):
        self.latitude = latitude
        self.longitude = longitude
        self.weather_planner = WeatherTravelPlanner(latitude, longitude)
        self.dsn = self.weather_planner.dsn
        
        # 반복 방지를 위한 상태 관리
        self.used_place_names = []  
        self._used_openers = []
        self._used_closers = []
        self.weather_mentioned = False  
        
    def create_daily_plan(self, language="English") -> Dict:
        """하루 전체 여행 일정을 생성합니다."""

        # 상태 초기화
        self.used_place_names = []
        self.weather_mentioned = False
        self._used_openers = []
        self._used_closers = []

        # 1. 위치 및 날씨 확인
        sigun = self.weather_planner.get_user_sigun_nm()
        if not sigun:
            return {"error": "위치를 확인할 수 없습니다."}

        weather = self.weather_planner.get_current_location_weather()
        if not weather:
            return {"error": "날씨 정보를 가져올 수 없습니다."}

        precipitation_type = weather.get('precipitation_type') or 0
        pm10 = weather.get('pm10') or 0
        pm25 = weather.get('pm25') or 0
        is_rainy = precipitation_type > 0
        is_bad_air = (pm10 > 80 or pm25 > 35)

        # 2. 장소 선택 (순차 — anchor 의존)
        time_slots = self._get_time_slots()
        anchor_lat = self.latitude
        anchor_lng = self.longitude
        morning_attraction_pool = self._build_morning_attraction_pool(
            sigun=sigun, is_rainy=is_rainy, is_bad_air=is_bad_air, radius_m=8000,
        )

        pending_jobs: List[Dict] = []

        for slot in time_slots:
            if slot['period'] == '오전':
                places = list(morning_attraction_pool)
            elif slot['period'] == '오후':
                places = self._rank_morning_pool_by_anchor(morning_attraction_pool, anchor_lat, anchor_lng)
            else:
                places = self._recommend_places_for_slot(
                    slot, sigun, is_rainy, is_bad_air,
                    radius_m=5000, center_lat=anchor_lat, center_lng=anchor_lng,
                )

            available_places = [p for p in places if p['name'] not in self.used_place_names]
            if not available_places:
                continue

            selected_items = []
            if slot['period'] == '저녁':
                dinner = next((p for p in available_places if p.get('itinerary_role') == 'dinner'), None)
                cafe = next((p for p in available_places if p.get('itinerary_role') == 'cafe'), None)
                if dinner: selected_items.append(dinner)
                if cafe: selected_items.append(cafe)
            else:
                selected_items = [available_places[0]]

            for selected_place in selected_items:
                self.used_place_names.append(selected_place['name'])
                alert_type = self._determine_alert_type(is_rainy, is_bad_air, slot['period'])
                place_type = selected_place.get('source_type', 'attraction')
                # weather_mentioned 상태가 순차이므로 instruction은 여기서 확정
                instruction = self._get_smart_weather_instruction(slot, is_rainy, is_bad_air, place_type)
                variation_hint = self._get_slot_style_hint(
                    slot['period'], place_type, selected_place.get('itinerary_role', '')
                )
                pending_jobs.append({
                    'slot': slot,
                    'place': selected_place,
                    'alert_type': alert_type,
                    'place_type': place_type,
                    'instruction': instruction,
                    'variation_hint': variation_hint,
                    'itinerary_role': selected_place.get('itinerary_role', ''),
                })
                if selected_place.get('lat') is not None and selected_place.get('lng') is not None:
                    anchor_lat = selected_place['lat']
                    anchor_lng = selected_place['lng']

        if not pending_jobs:
            return {
                'location': sigun,
                'weather': {
                    'outdoor_status': weather.get('outdoor_status', '정보 없음'),
                    'temperature': weather.get('temperature'),
                    'precipitation': '비/눈' if is_rainy else '없음',
                    'air_quality': '나쁨' if is_bad_air else '보통 이상',
                },
                'plan': [],
            }

        # 3. 도슨트 재료 조회 (병렬 — DB 조회 + 리뷰 없으면 크롤링 포함)
        def _fetch_material(job):
            return self._get_docent_material(
                job['place']['name'],
                job['alert_type'],
                table_type=job['place'].get('source_type', 'attraction'),
                sigun_nm=sigun,
            )

        n = len(pending_jobs)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(n, 5)) as ex:
            materials = list(ex.map(_fetch_material, pending_jobs))

        # 4. LLM 스크립트 생성 (병렬)
        def _generate_script(args):
            job, material = args
            if not material:
                return f"{job['slot']['period']}에는 {job['place']['name']}에 방문해 보시는 걸 어떨까요?"
            mat = dict(material)
            mat['instruction'] = job['instruction']
            mat['variation_hint'] = job['variation_hint']
            mat['avoid_openers'] = []
            mat['avoid_closers'] = []
            mat['place_type'] = job['place_type']
            mat['period'] = job['slot']['period']
            mat['time_range'] = job['slot']['time']
            mat['itinerary_role'] = job['itinerary_role']
            return self._create_daily_docent_script(mat, language=language)

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(n, 5)) as ex:
            scripts = list(ex.map(_generate_script, zip(pending_jobs, materials)))

        # 5. 최종 일정 조합
        daily_plan = [
            {
                'time': job['slot']['time'],
                'period': job['slot']['period'],
                'place': job['place'],
                'script': script,
            }
            for job, script in zip(pending_jobs, scripts)
        ]

        return {
            'location': sigun,
            'weather': {
                'outdoor_status': weather.get('outdoor_status', '정보 없음'),
                'temperature': weather.get('temperature'),
                'precipitation': '비/눈' if is_rainy else '없음',
                'air_quality': '나쁨' if is_bad_air else '보통 이상',
            },
            'plan': daily_plan,
        }

    def _build_morning_attraction_pool(self, sigun: str, is_rainy: bool, is_bad_air: bool, radius_m: int) -> List[Dict]:
        """오전 전용: 날씨 조건에 맞는 명소를 먼저 탐색해 후보 풀을 만듭니다."""
        if is_rainy or is_bad_air:
            return self._query_indoor_attractions(
                sigun,
                radius_m,
                center_lat=self.latitude,
                center_lng=self.longitude,
            )

        # 쾌적한 날씨는 야외 명소 우선
        outdoor = self._query_outdoor_attractions(
            sigun,
            radius_m,
            center_lat=self.latitude,
            center_lng=self.longitude,
        )
        if outdoor:
            return outdoor

        # 데이터가 없을 때만 폴백
        return self._query_mixed_attractions(
            sigun,
            radius_m,
            center_lat=self.latitude,
            center_lng=self.longitude,
        )

    def _rank_morning_pool_by_anchor(self, pool: List[Dict], anchor_lat: float, anchor_lng: float) -> List[Dict]:
        """오전에 수집한 명소 풀을 anchor(직전 추천 장소) 기준으로 가까운 순 재정렬합니다."""
        ranked: List[Dict] = []
        for place in pool:
            lat = place.get('lat')
            lng = place.get('lng')
            if lat is None or lng is None:
                continue

            p = dict(place)
            p['dist'] = self._haversine_meters(anchor_lat, anchor_lng, lat, lng)
            ranked.append(p)

        ranked.sort(key=lambda x: x.get('dist', float('inf')))
        return ranked

    def _haversine_meters(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """두 좌표 사이의 대략적인 직선거리를 미터 단위로 반환합니다."""
        r = 6371000.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lng2 - lng1)

        a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return r * c
    
    def _get_time_slots(self) -> List[Dict]:
        return [
            {'time': '09:00-11:00', 'period': '오전', 'preference': 'attraction'},
            {'time': '11:30-13:00', 'period': '점심', 'preference': 'restaurant'},
            {'time': '13:30-16:00', 'period': '오후', 'preference': 'attraction'},
            {'time': '17:30-19:00', 'period': '저녁', 'preference': 'evening_combo'},
        ]
    
    def _recommend_places_for_slot(self, slot, sigun, is_rainy, is_bad_air, radius_m, center_lat, center_lng):
        """[수정] 점심/저녁에는 음식점+음식 관련 명소, 오전/오후에는 일반 명소만"""
        # 1. 점심 식당 + 음식 관련 명소
        if slot['preference'] == 'restaurant':
            restaurants = self._query_restaurants(sigun, radius_m, category='점심음식점', center_lat=center_lat, center_lng=center_lng)
            food_spots = self._query_food_attractions(sigun, radius_m, center_lat=center_lat, center_lng=center_lng)
            for f in food_spots: f['itinerary_role'] = 'food_attraction'
            return restaurants + food_spots
        
        # 2. 저녁 콤보 (음식점 + 카페 + 음식 관련 명소)
        if slot['preference'] == 'evening_combo':
            res = self._query_restaurants(sigun, radius_m, category='저녁음식점', center_lat=center_lat, center_lng=center_lng)
            caf = self._query_restaurants(sigun, radius_m, category='저녁카페', center_lat=center_lat, center_lng=center_lng)
            food_spots = self._query_food_attractions(sigun, radius_m, center_lat=center_lat, center_lng=center_lng)
            for r in res: r['itinerary_role'] = 'dinner'
            for c in caf: c['itinerary_role'] = 'cafe'
            for f in food_spots: f['itinerary_role'] = 'food_attraction'
            return res + caf + food_spots
        
        # 3. 오전/오후 명소 (상점류 제외 필터 적용된 쿼리 호출)
        if is_rainy or is_bad_air:
            return self._query_indoor_attractions(sigun, radius_m, center_lat=center_lat, center_lng=center_lng)
        else:
            return self._query_mixed_attractions(sigun, radius_m, center_lat=center_lat, center_lng=center_lng)

    def _get_smart_weather_instruction(self, slot: Dict, is_rainy: bool, is_bad_air: bool, place_type: str = 'attraction') -> str:
        period = slot['period']
        
        # 명소인 경우 overview 활용 강조
        overview_guidance = ""
        if place_type == 'attraction':
            overview_guidance = " 장소 '소개'에 나온 역사, 배경, 특징을 자연스럽게 언급하세요."

        honorific_guidance = " 반드시 존댓말(~요체)로 말하고, 반말은 사용하지 마세요."

        # 날씨 언급은 오전 첫 멘트에서 단 1회만
        if period == '오전' and not self.weather_mentioned:
            self.weather_mentioned = True
            if is_rainy:
                return (
                    "오전 첫 안내에서만 비/눈 상황을 1문장으로 짧게 언급하고, 바로 해결 제안으로 '비를 피할 수 있는 아늑한 실내로 가보시는 건 어떠세요?'처럼 연결해 주세요."
                    + overview_guidance
                    + honorific_guidance
                )
            if is_bad_air:
                return (
                    "오전 첫 안내에서만 공기질이 좋지 않다는 점을 1문장으로 짧게 언급하고, 바로 해결 제안으로 '실내에서 쾌적하게 둘러보시는 게 어떠세요?'처럼 연결해 주세요."
                    + overview_guidance
                    + honorific_guidance
                )
            return (
                "오전 첫 안내에서만 날씨가 무난하거나 맑다는 점을 1문장으로 짧게 언급하고, 바로 해결 제안으로 '가볍게 둘러보기 좋은 코스로 시작해보시는 건 어떠세요?'처럼 연결해 주세요."
                + overview_guidance
                + honorific_guidance
            )

        # 나머지 시간대는 날씨 언급 없이 장소 중심 설명
        return "날씨 언급 없이 장소의 매력을 중심으로 자연스럽게 추천해 주세요." + overview_guidance + honorific_guidance

    # --- 데이터 조회 (에러 방지 및 필터 강화) ---

    def _execute_query(self, query: str, params: tuple) -> List[Dict]:
        """DB 결과를 안정적으로 dict 리스트로 변환합니다."""
        try:
            with psycopg2.connect(self.dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    rows = cur.fetchall()
                    columns = [desc[0] for desc in cur.description]
                    return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            print(f"⚠️ DB 조회 실패: {e}")
            return []

    def _query_restaurants(self, sigun, radius_m, category, center_lat, center_lng):
        filters = {
            '점심음식점': "AND COALESCE(g.bizcond_div_nm_info, '') NOT IN ('까페', '전통찻집', '주점', '유흥')",
            '저녁음식점': "AND COALESCE(g.bizcond_div_nm_info, '') NOT IN ('까페', '전통찻집')",
            '저녁카페': "AND COALESCE(g.bizcond_div_nm_info, '') IN ('까페', '전통찻집')"
        }
        category_filter = filters.get(category, "")
        query = f"""
            SELECT g.bizplc_nm as name,
                   g.refine_wgs84_lat as lat,
                   g.refine_wgs84_logt as lng,
                   'restaurant' as source_type,
                   ST_Distance(ST_SetSRID(ST_MakePoint(g.refine_wgs84_logt, g.refine_wgs84_lat), 4326)::geography,
                               ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) as dist
            FROM locallink.gg_restaurant_info g
            WHERE g.sigun_nm = %s AND g.bsn_state_nm = '영업' {category_filter}
              AND ST_DWithin(ST_SetSRID(ST_MakePoint(g.refine_wgs84_logt, g.refine_wgs84_lat), 4326)::geography,
                             ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)
            ORDER BY dist ASC LIMIT 10
        """
        return self._execute_query(query, (center_lng, center_lat, sigun, center_lng, center_lat, radius_m))

    def _query_indoor_attractions(self, sigun, radius_m, center_lat, center_lng):
        """[수정] 실내 명소 조회 시 상점/시장/음식 관련 제외 필터 추가"""
        query = """
            SELECT t.tourist_nm as name,
                   t.lat as lat,
                   t.lng as lng,
                   'attraction' as source_type,
                   ST_Distance(ST_SetSRID(ST_MakePoint(t.lng, t.lat), 4326)::geography,
                               ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) as dist
            FROM locallink.tourist_spot_info t
            WHERE t.sigun_nm = %s AND t.is_indoor = TRUE
              AND t.tourist_nm NOT LIKE '%%상회%%' AND t.tourist_nm NOT LIKE '%%시장%%' 
              AND t.tourist_nm NOT LIKE '%%물산%%' AND t.tourist_nm NOT LIKE '%%유통%%'
              AND t.tourist_nm NOT LIKE '%%푸드%%' AND t.tourist_nm NOT LIKE '%%음식%%'
              AND ST_DWithin(ST_SetSRID(ST_MakePoint(t.lng, t.lat), 4326)::geography,
                             ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)
            ORDER BY dist ASC LIMIT 10
        """
        return self._execute_query(query, (center_lng, center_lat, sigun, center_lng, center_lat, radius_m))

    def _query_outdoor_attractions(self, sigun, radius_m, center_lat, center_lng):
        """쾌적한 날씨에서 우선 추천할 야외 명소 조회"""
        query = """
            SELECT t.tourist_nm as name,
                   t.lat as lat,
                   t.lng as lng,
                   'attraction' as source_type,
                   ST_Distance(ST_SetSRID(ST_MakePoint(t.lng, t.lat), 4326)::geography,
                               ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) as dist
            FROM locallink.tourist_spot_info t
            WHERE t.sigun_nm = %s AND t.is_indoor = FALSE
              AND t.tourist_nm NOT LIKE '%%상회%%' AND t.tourist_nm NOT LIKE '%%시장%%'
              AND t.tourist_nm NOT LIKE '%%물산%%' AND t.tourist_nm NOT LIKE '%%유통%%'
              AND t.tourist_nm NOT LIKE '%%푸드%%' AND t.tourist_nm NOT LIKE '%%음식%%'
              AND ST_DWithin(ST_SetSRID(ST_MakePoint(t.lng, t.lat), 4326)::geography,
                             ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)
            ORDER BY dist ASC LIMIT 15
        """
        return self._execute_query(query, (center_lng, center_lat, sigun, center_lng, center_lat, radius_m))

    def _query_mixed_attractions(self, sigun, radius_m, center_lat, center_lng):
        """[수정] 명소 조회 시 상점/시장/음식 관련 제외 필터 추가"""
        query = """
            SELECT t.tourist_nm as name,
                   t.lat as lat,
                   t.lng as lng,
                   'attraction' as source_type,
                   ST_Distance(ST_SetSRID(ST_MakePoint(t.lng, t.lat), 4326)::geography,
                               ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) as dist
            FROM locallink.tourist_spot_info t
            WHERE t.sigun_nm = %s
              AND t.tourist_nm NOT LIKE '%%상회%%' AND t.tourist_nm NOT LIKE '%%시장%%'
              AND t.tourist_nm NOT LIKE '%%물산%%' AND t.tourist_nm NOT LIKE '%%유통%%'
              AND t.tourist_nm NOT LIKE '%%푸드%%' AND t.tourist_nm NOT LIKE '%%음식%%'
              AND ST_DWithin(ST_SetSRID(ST_MakePoint(t.lng, t.lat), 4326)::geography,
                             ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)
            ORDER BY dist ASC LIMIT 10
        """
        return self._execute_query(query, (center_lng, center_lat, sigun, center_lng, center_lat, radius_m))

    def _query_food_attractions(self, sigun, radius_m, center_lat, center_lng):
        """[신규] 음식 관련 명소 조회 (점심/저녁 시간대용)"""
        query = """
            SELECT t.tourist_nm as name,
                   t.lat as lat,
                   t.lng as lng,
                   'attraction' as source_type,
                   ST_Distance(ST_SetSRID(ST_MakePoint(t.lng, t.lat), 4326)::geography,
                               ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) as dist
            FROM locallink.tourist_spot_info t
            WHERE t.sigun_nm = %s
              AND (t.tourist_nm LIKE '%%상회%%' OR t.tourist_nm LIKE '%%시장%%'
                   OR t.tourist_nm LIKE '%%물산%%' OR t.tourist_nm LIKE '%%유통%%'
                   OR t.tourist_nm LIKE '%%푸드%%' OR t.tourist_nm LIKE '%%음식%%')
              AND ST_DWithin(ST_SetSRID(ST_MakePoint(t.lng, t.lat), 4326)::geography,
                             ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)
            ORDER BY dist ASC LIMIT 10
        """
        return self._execute_query(query, (center_lng, center_lat, sigun, center_lng, center_lat, radius_m))

    def _get_docent_material(self, name, alert_type, table_type, sigun_nm):
        res = self._query_docent_material_from_db(name, alert_type, table_type)
        if not res or not res.get("reviews") or res["reviews"] == "관련 리뷰 없음":
            try:
                if table_type == "attraction":
                    from src.collectors.load_review_pipeline import run_review_pipeline
                    run_review_pipeline(name)
                else:
                    from src.collectors.load_restaurant_review import run_restaurant_pipeline
                    run_restaurant_pipeline(name, sigun_nm)
                res = self._query_docent_material_from_db(name, alert_type, table_type)
            except: pass
        return res

    def _query_docent_material_from_db(self, name, alert_type, table_type):
        weather_keywords = {
            "rain_alert": "비, 빗소리, 창가, 실내, 운치",
            "pm_alert": "실내, 쾌적, 공기, 깨끗",
            "clear_sky_alert": "산책, 맑음, 햇살, 야외",
        }
        pattern = weather_keywords.get(alert_type, "추천").replace(", ", "|")
        if table_type == "attraction":
            query = """
                SELECT t.tourist_nm as place_name, COALESCE(d.overview, '매력적인 장소입니다.') as overview, d.tags,
                (SELECT string_agg(clean_text, ' | ') FROM (
                    SELECT clean_text FROM locallink.attraction_reviews WHERE attraction_name = t.tourist_nm
                    ORDER BY (CASE WHEN clean_text SIMILAR TO %s THEN 1 ELSE 2 END) ASC, post_date DESC LIMIT 5
                ) AS sub) as reviews
                FROM locallink.tourist_spot_info t LEFT JOIN locallink.attraction_descriptions d ON t.tourist_nm = d.attraction_name
                WHERE t.tourist_nm = %s LIMIT 1
            """
            params = (f"%({pattern})%", name)
        else:
            query = """
                SELECT g.bizplc_nm as place_name, COALESCE(g.refine_roadnm_addr, '로컬 맛집입니다.') as overview, NULL::text[] as tags,
                (SELECT string_agg(clean_text, ' | ') FROM (
                    SELECT clean_text FROM locallink.restaurant_reviews WHERE restaurant_name = g.bizplc_nm
                    ORDER BY (CASE WHEN clean_text SIMILAR TO %s THEN 1 ELSE 2 END) ASC, post_date DESC LIMIT 5
                ) AS sub) as reviews
                FROM locallink.gg_restaurant_info g WHERE g.bizplc_nm = %s LIMIT 1
            """
            params = (f"%({pattern})%", name)

        data = self._execute_query(query, params)
        return data[0] if data else None

    def _determine_alert_type(self, is_rainy, is_bad_air, period):
        if is_rainy: return "rain_alert"
        if is_bad_air: return "pm_alert"
        return "clear_sky_alert"

    def _get_slot_style_hint(self, period, s_type, role):
        if period == '오전': return "하루를 시작하는 활기찬 가이드, 존댓말 유지"
        if role == 'cafe': return "차분하게 쉴 수 있는 힐링 톤, 존댓말 유지"
        return "친절하고 다정한 로컬 도슨트, 존댓말 유지"

    def _extract_edges(self, script):
        if not script: return "", ""
        parts = [p.strip() for p in script.split('.') if p.strip()]
        return (parts[0][:20], parts[-1][:20]) if parts else ("", "")

    def _create_daily_docent_script(self, material: Dict, language: str = "English") -> str:
        """Daily planner 전용 프롬프트로 도슨트 스크립트를 생성합니다."""
        tags = material.get("tags")
        tags_text = ", ".join(tags) if isinstance(tags, list) and tags else (tags or "다양한 매력")
        output_language = language or "English"
        period = material.get("period", "")
        time_range = material.get("time_range", "")
        place_type = material.get("place_type", "attraction")
        itinerary_role = material.get("itinerary_role", "")

        tone_rule = ""
        if output_language.lower() == "korean":
            tone_rule = "- 존댓말(~요체)만 사용하고 반말은 절대 사용하지 마세요."
        elif output_language.lower() == "english":
            tone_rule = "- Use polite and friendly spoken English suitable for a travel guide."

        # 역할 힌트를 언어별로 분리
        role_hint_ko = "일반 명소"
        role_hint_en = "general attraction"
        
        if itinerary_role == "dinner":
            role_hint_ko = "저녁 식사 장소"
            role_hint_en = "dinner spot"
        elif itinerary_role == "cafe":
            role_hint_ko = "저녁 카페"
            role_hint_en = "evening café"
        elif itinerary_role == "food_attraction":
            role_hint_ko = "먹거리/시장형 명소"
            role_hint_en = "food market attraction"
        
        # 프롬프트에 사용될 role_hint는 한국어 버전 (프롬프트는 한국어)
        role_hint = role_hint_ko

        system_prompt = f"""
        당신은 하루 동선 추천 도슨트 '라라'입니다.
        사용자가 바로 이동 결정을 내릴 수 있도록, 사실 기반으로 짧고 정확하게 안내하세요.

        출력 규칙:
        - 반드시 {output_language}로 작성
        {tone_rule}
        - 2~3문장으로 간결하게 작성
        - 과장, 광고 문구, 이모지 금지
        - 제공된 데이터(overview/reviews/tags)에 없는 사실은 절대 만들지 마세요.

        핵심 정책:
        - 날씨 언급은 material.instruction에 명시된 경우에만 따르세요.
        - 오전 첫 멘트 외에는 날씨를 반복 언급하지 마세요.
        - {period} 시간대에 적합한 스타일로 작성하되, 장소 유형(place_type)과 역할(itinerary_role)에 맞는 힌트를 활용하여 시작하세요.
        - 명소(attraction)는 overview 중심으로 설명하고, 음식점(restaurant)은 리뷰 근거를 최소 1개 반영하세요.
        - 이전 멘트와 유사한 시작/마무리 표현은 피하세요.
        """

        user_prompt = f"""
        [일정 컨텍스트]
        - 시간대: {period}
        - 시간 범위: {time_range}
        - 일정 역할: {role_hint}

        [지침]
        - 상황 지침: {material.get('instruction', '')}
        - 문체 힌트: {material.get('variation_hint', '')}
        - 피해야 할 시작 표현: {', '.join(material.get('avoid_openers', [])) or '없음'}
        - 피해야 할 마무리 표현: {', '.join(material.get('avoid_closers', [])) or '없음'}

        [장소 데이터]
        - 장소명: {material.get('place_name', '')}
        - 유형: {place_type}
        - 태그: {tags_text}
        - 소개(overview): {material.get('overview', '')}
        - 방문자 리뷰: {material.get('reviews', '')}

        [작성 요청]
        사용자가 지금 바로 이동할 수 있도록 자연스럽고 정확한 도슨트 멘트를 작성하세요.
        """

        try:
            client = self.weather_planner._get_openai_client()
            response = client.chat.completions.create(
                model=self.weather_planner._get_openai_deployment_name(),
                messages=[
                    {"role": "system", "content": system_prompt.strip()},
                    {"role": "user", "content": user_prompt.strip()},
                ],
                temperature=0.2,
                max_tokens=240,
            )

            script = (response.choices[0].message.content or "").strip()
            if script:
                if output_language.lower() == "english" and re.search(r"[가-힣]", script):
                    # 영어 fallback: 영어 role_hint 사용, 장소명 제거
                    return (
                        f"For this {role_hint_en}, I recommend exploring the area. "
                        "It is a popular local spot and fits well with your itinerary right now."
                    )
                return script
        except Exception as e:
            print(f"⚠️ Daily 프롬프트 생성 실패: {e}")

        # Exception fallback도 한국어 제거
        if output_language.lower() == "english":
            return (
                f"For this {role_hint_en}, I recommend checking out the local area. "
                "It is a great spot to visit during your trip."
            )

        return f"{period}에는 {material.get('place_name', '이 장소')} 방문을 추천드려요. {material.get('overview', '분위기가 좋은 곳입니다.')}"


def print_daily_plan(plan_result: Dict):
    if 'error' in plan_result:
        print(f"❌ 오류: {plan_result['error']}")
        return
    
    print("\n" + "="*70)
    print(f"📍 {plan_result['location']} 하루 여행 가이드 (도슨트 라라)")
    print("="*70)
    
    w = plan_result['weather']
    # None 값 처리
    temperature = w.get('temperature') if w.get('temperature') is not None else 'N/A'
    precipitation = w.get('precipitation') if w.get('precipitation') is not None else 'N/A'
    outdoor_status = w.get('outdoor_status', '정보 없음')
    
    if temperature != 'N/A':
        temp_str = f"{temperature:.1f}°C"
    else:
        temp_str = temperature
    
    print(f"\n🌦️ 오늘 날씨: {outdoor_status} (기온: {temp_str}, 강수: {precipitation})")
    
    for idx, item in enumerate(plan_result['plan'], 1):
        print(f"\n{idx}. [{item['time']}] {item['period']}")
        print(f"   📌 장소: {item['place']['name']} ({item['place']['dist']:.0f}m)")
        print(f"   💬 라라의 추천: {item['script']}")
    print("\n" + "="*70)

if __name__ == "__main__":
    # 테스트 좌표: 수원역 인근
    planner = DailyTravelPlanner(37.2635, 127.0090)
    print_daily_plan(planner.create_daily_plan())