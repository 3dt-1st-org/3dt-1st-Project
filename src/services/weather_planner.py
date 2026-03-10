import psycopg2
from psycopg2.extras import RealDictCursor
from config.vault_manager import get_vault_manager
from openai import AzureOpenAI
import json
from pathlib import Path

class WeatherTravelPlanner:
    WEATHER_STATE_CACHE = Path(__file__).resolve().parents[2] / ".weather_state_cache.json"
    
    def __init__(self, user_lat, user_lng):
        self.lat = user_lat
        self.lng = user_lng
        self.dsn = self._get_dsn()
        # 파일에서 이전 상태 로드
        self.last_weather_state = self._load_cached_state()
        self.last_alert_reasons = []

    def _get_dsn(self):
        vm = get_vault_manager()
        return (
            f"host={vm.get_secret('lala-db-host')} port=5432 "
            f"dbname={vm.get_secret('lala-db-name')} "
            f"user={vm.get_secret('lala-db-user')} "
            f"password={vm.get_secret('lala-db-password')} "
            "sslmode=require"
        )

    def _get_openai_client(self):
        """Key Vault 시크릿을 사용해 Azure OpenAI 클라이언트를 생성합니다."""
        vm = get_vault_manager()
        return AzureOpenAI(
            azure_endpoint=vm.get_secret("azure-openai-endpoint"),
            api_key=vm.get_secret("azure-openai-key"),
            api_version=vm.get_secret("azure-openai-version"),
        )

    def _get_openai_deployment_name(self):
        vm = get_vault_manager()
        return vm.get_secret("azure-openai-deployment-name")

    def _load_cached_state(self) -> str | None:
        """파일에서 이전 날씨 상태를 로드합니다."""
        if not self.WEATHER_STATE_CACHE.exists():
            return None
        try:
            with open(self.WEATHER_STATE_CACHE, 'r') as f:
                data = json.load(f)
                return data.get('state')
        except Exception as e:
            print(f"⚠️ 캐시 로드 실패: {e}")
            return None

    def _save_cached_state(self, state: str) -> None:
        """현재 날씨 상태를 파일에 저장합니다."""
        try:
            with open(self.WEATHER_STATE_CACHE, 'w') as f:
                json.dump({'state': state}, f)
        except Exception as e:
            print(f"⚠️ 캐시 저장 실패: {e}")

    @staticmethod
    def _to_int(value, default=0):
        """숫자/문자 혼합 입력을 안전하게 정수로 변환합니다."""
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_bool(value, default=False):
        """bool/int/문자 입력을 안전하게 불리언으로 변환합니다."""
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "t", "y", "yes"}:
                return True
            if normalized in {"0", "false", "f", "n", "no"}:
                return False
        return default

    def _extract_alert_flags(self, weather_row: dict) -> dict:
        """날씨 row에서 ASA 플래그(및 폴백)를 bool로 정규화합니다."""
        precip = self._to_int(weather_row.get('precipitation_type'), 0)
        temp = float(weather_row.get('temperature') or 0)
        wind = float(weather_row.get('wind_speed') or 0)
        pm10 = self._to_int(weather_row.get('pm10'), 0)
        pm25 = self._to_int(weather_row.get('pm25'), 0)

        return {
            'is_rain_snow': self._to_bool(weather_row.get('is_rain_snow'), precip > 0),
            'is_bad_dust': self._to_bool(weather_row.get('is_bad_dust'), pm10 > 80 or pm25 > 35),
            'is_heatwave': self._to_bool(weather_row.get('is_heatwave'), temp >= 33.0),
            'is_coldwave': self._to_bool(weather_row.get('is_coldwave'), temp <= -12.0),
            'is_strong_wind': self._to_bool(weather_row.get('is_strong_wind'), wind >= 4.0),
        }

    def _get_active_alert_reasons(self, weather_row: dict) -> list[str]:
        """동시에 활성화된 기상 악화 원인들을 반환합니다."""
        if not weather_row:
            return []

        flags = self._extract_alert_flags(weather_row)
        reasons = []
        if flags['is_rain_snow']:
            reasons.append('rain_alert')
        if flags['is_bad_dust']:
            reasons.append('pm_alert')
        if flags['is_coldwave'] or flags['is_strong_wind']:
            reasons.append('cold_alert')
        if flags['is_heatwave']:
            reasons.append('heat_alert')
        return reasons

    # 1. 사용자 위치 기반 시군구명 추출 (공통 메서드)
    def get_user_sigun_nm(self):
        """사용자 좌표와 가장 가까운 명소의 sigun_nm을 찾아 반환합니다."""
        query = """
            SELECT sigun_nm
            FROM locallink.tourist_spot_info
            ORDER BY ST_Distance(
                ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
            ) ASC
            LIMIT 1
        """
        with psycopg2.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (self.lng, self.lat))
                result = cur.fetchone()
                return result[0] if result else None
            
    # 2. 날씨 정보 가져오기 (중복 제거됨)
    def get_current_location_weather(self):
        """get_user_sigun_nm을 사용하여 해당 지역의 최신 날씨를 반환합니다."""
        sigun_nm = self.get_user_sigun_nm()
        if not sigun_nm:
            return None
        
        processed_nm = sigun_nm[:-1] if sigun_nm.endswith(('시', '군')) else sigun_nm

        with psycopg2.connect(self.dsn) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM locallink.realtime_weather_conditions 
                    WHERE location LIKE %s 
                    ORDER BY record_time DESC LIMIT 1
                """, (f"%{processed_nm}%",))
                return cur.fetchone()
    
    def _get_detailed_alert_type(self, weather_row: dict) -> str | None:
        """기상 수치를 분석하여 alert_type을 결정합니다."""
        if not weather_row: return None

        active_reasons = self._get_active_alert_reasons(weather_row)
        status = (weather_row.get('outdoor_status') or '').strip()
        has_asa_flags = any(
            weather_row.get(k) is not None
            for k in ('is_rain_snow', 'is_bad_dust', 'is_heatwave', 'is_coldwave', 'is_strong_wind')
        )

        # 2. 실내/실외 판단은 outdoor_status 기준으로 단일화
        #    - '외출 지양'이면 실내 추천 계열
        #    - '외출 가능'이면 실외 추천 계열
        # 3. 대표 alert_type은 기존 호환을 위해 1개만 선택 (이유 상세는 last_alert_reasons 사용)
        priority = ('rain_alert', 'cold_alert', 'heat_alert', 'pm_alert')

        if status == '외출 지양':
            for p in priority:
                if p in active_reasons:
                    return p
            # 상태와 플래그가 불일치할 때는 원인 단정 대신 중립 타입 반환
            return 'bad_weather_alert'

        if status == '외출 가능':
            return 'clear_sky_alert'

        # outdoor_status 미적재/이상값 대비 폴백
        for p in priority:
            if p in active_reasons:
                return p

        # outdoor_status가 NULL이어도 ASA 플래그가 모두 0이면 쾌적으로 판단
        if has_asa_flags and not active_reasons:
            return 'clear_sky_alert'

        if '쾌적' in status:
            return "clear_sky_alert"

        return None

    # 4. 실시간 날씨 변동 선제시 (상황 세분화)
    def check_and_propose_intervention(self, radius_m=10000):
        """
        날씨 변화를 감지하고 적절한 장소를 추천합니다.
        radius_m: 최대 추천 거리 (기본: 10km)
        """
        new_weather = self.get_current_location_weather()
        if not new_weather:
            return None

        # 수치 정교화: 소수점 단위 흔들림은 무시하고 정수 단위 변화만 감지합니다.
        # ASA 플래그가 있으면 플래그를 상태 비교에 포함합니다.
        wind_value = float(new_weather.get('wind_speed') or 0)
        temp_value = float(new_weather.get('temperature') or 0)
        pm10_value = self._to_int(new_weather.get('pm10'), 0)
        pm25_value = self._to_int(new_weather.get('pm25'), 0)

        is_rain_snow = self._to_bool(new_weather.get('is_rain_snow'), self._to_int(new_weather.get('precipitation_type'), 0) > 0)
        is_strong_wind = self._to_bool(new_weather.get('is_strong_wind'), wind_value >= 4.0)
        is_heatwave = self._to_bool(new_weather.get('is_heatwave'), temp_value >= 33.0)
        is_coldwave = self._to_bool(new_weather.get('is_coldwave'), temp_value <= -12.0)
        is_bad_dust = self._to_bool(new_weather.get('is_bad_dust'), pm10_value > 80 or pm25_value > 35)

        has_asa_flags = any(
            new_weather.get(k) is not None
            for k in ("is_rain_snow", "is_bad_dust", "is_heatwave", "is_coldwave", "is_strong_wind")
        )

        # ASA 플래그가 있으면 플래그만으로 감시해 과민 반응을 줄입니다.
        # 플래그가 없을 때는 수치를 버킷(온도 5도, 풍속 2m/s)으로 묶어 변화 감지합니다.
        if has_asa_flags:
            current_state = (
                f"{int(is_rain_snow)}_{int(is_strong_wind)}_{int(is_heatwave)}_{int(is_coldwave)}_{int(is_bad_dust)}"
            )
        else:
            temp_bucket = int(temp_value // 5)
            wind_bucket = int(wind_value // 2)
            pm10_bucket = int(pm10_value // 20)
            pm25_bucket = int(pm25_value // 10)
            current_state = (
                f"{self._to_int(new_weather.get('precipitation_type'), 0)}_{temp_bucket}_{wind_bucket}_{pm10_bucket}_{pm25_bucket}"
            )

        if self.last_weather_state == current_state:
            return None
        
        # 상태 변화 감지됨 → 파일에 저장
        self.last_weather_state = current_state
        self._save_cached_state(current_state)

        # 복수 원인 추출 (예: 비 + 미세먼지)
        self.last_alert_reasons = self._get_active_alert_reasons(new_weather)
        if not self.last_alert_reasons:
            self.last_alert_reasons = []

        # 상세 상황 판단
        alert_type = self._get_detailed_alert_type(new_weather)
        if not alert_type:
            return None

        if alert_type in ("rain_alert", "pm_alert", "cold_alert", "heat_alert", "bad_weather_alert"):
            status_map = {
                "rain_alert": "☔ 비/눈 감지",
                "pm_alert": "😷 미세먼지 나쁨 감지",
                "cold_alert": "🥶 한파/강풍 감지",
                "heat_alert": "🥵 폭염 감지",
                "bad_weather_alert": "⚠️ 외출 지양 상태 감지",
            }
            if self.last_alert_reasons:
                reason_labels = {
                    'rain_alert': '비/눈',
                    'pm_alert': '미세먼지',
                    'cold_alert': '한파/강풍',
                    'heat_alert': '폭염',
                }
                reason_text = ", ".join([reason_labels.get(r, r) for r in self.last_alert_reasons])
                print(f"⚠️ 복합 원인 감지: {reason_text} -> 실내 대피 코스 가동")
            recommendations = self._get_indoor_recommendations(radius_m)
            return recommendations, alert_type

        if alert_type == "clear_sky_alert":
            print("☀️ 상황 B: 날씨 호전 감지")
            recommendations = self._get_outdoor_recommendations(radius_m)
            return recommendations, alert_type

        return None

    def _get_indoor_recommendations(self, radius_m):
        """기상 악화 시 실내 명소와 카페를 거리순으로 조합합니다."""
        indoor_attr = self._execute_recommendation_query(radius_m, "AND is_indoor = TRUE", "attraction")
        nearby_cafes = self._execute_recommendation_query(
            radius_m,
            "AND bizcond_div_nm_info = '까페'",
            "restaurant",
        )
        combined = sorted(indoor_attr + nearby_cafes, key=lambda x: x['dist'])
        return combined[:5]

    def _get_outdoor_recommendations(self, radius_m):
        """날씨 호전 시 야외 명소를 우선 추천합니다."""
        outdoor_attr = self._execute_recommendation_query(radius_m, "AND is_indoor = FALSE", "attraction")

        if len(outdoor_attr) < 3:
            all_attr = self._execute_recommendation_query(radius_m, "", "attraction")
            seen_names = {attr['name'] for attr in outdoor_attr}
            for attr in all_attr:
                if attr['name'] not in seen_names and len(outdoor_attr) < 5:
                    outdoor_attr.append(attr)
                    seen_names.add(attr['name'])

        return sorted(outdoor_attr, key=lambda x: x['dist'])[:5]
    
    # 5. DB 쿼리 실행 공통부 (내부용)
    def _execute_recommendation_query(self, radius_m, additional_filter, table_type="attraction"):
        """
        날씨 조건에 맞는 장소를 먼저 필터링한 후, 거리 순으로 정렬하여 추천합니다.
        radius_m은 최대 거리 제한으로 사용됩니다.
        """
        with psycopg2.connect(self.dsn) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if table_type == "attraction":
                    # 날씨 조건 먼저 적용 → 거리 계산 → 가까운 순 정렬
                    query = f"""
                        SELECT t.tourist_nm as name, t.lat, t.lng, t.is_indoor, t.road_addr,
                               'attraction'::text as source_type,
                               ST_Distance(ST_SetSRID(ST_MakePoint(t.lng, t.lat), 4326)::geography, 
                                           ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) as dist
                        FROM locallink.tourist_spot_info t
                        LEFT JOIN locallink.attraction_descriptions d ON t.tourist_nm = d.attraction_name
                        WHERE ST_DWithin(
                            ST_SetSRID(ST_MakePoint(t.lng, t.lat), 4326)::geography,
                            ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                            %s
                        )
                        {additional_filter}
                        ORDER BY dist ASC LIMIT 10
                    """
                    params = (self.lng, self.lat, self.lng, self.lat, radius_m)
                else:
                    query = f"""
                        SELECT bizplc_nm as name, refine_wgs84_lat as lat, refine_wgs84_logt as lng, 
                               TRUE as is_indoor, refine_roadnm_addr as road_addr,
                               'restaurant'::text as source_type,
                               ST_Distance(ST_SetSRID(ST_MakePoint(refine_wgs84_logt, refine_wgs84_lat), 4326)::geography, 
                                           ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) as dist
                        FROM locallink.gg_restaurant_info
                        WHERE bsn_state_nm = '영업'
                          AND ST_DWithin(
                              ST_SetSRID(ST_MakePoint(refine_wgs84_logt, refine_wgs84_lat), 4326)::geography,
                              ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                              %s
                          )
                        {additional_filter}
                        ORDER BY dist ASC LIMIT 10
                    """
                    params = (self.lng, self.lat, self.lng, self.lat, radius_m)

                cur.execute(query, params)
                results = cur.fetchall()
                if results:
                    return results

                # 반경 내 후보가 없을 때만 가까운 순 폴백
                if table_type == "attraction":
                    fallback_query = f"""
                        SELECT t.tourist_nm as name, t.lat, t.lng, t.is_indoor, t.road_addr,
                               'attraction'::text as source_type,
                               ST_Distance(ST_SetSRID(ST_MakePoint(t.lng, t.lat), 4326)::geography,
                                           ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) as dist
                        FROM locallink.tourist_spot_info t
                        LEFT JOIN locallink.attraction_descriptions d ON t.tourist_nm = d.attraction_name
                        WHERE 1=1
                        {additional_filter}
                        ORDER BY dist ASC LIMIT 5
                    """
                else:
                    fallback_query = f"""
                        SELECT bizplc_nm as name, refine_wgs84_lat as lat, refine_wgs84_logt as lng,
                               TRUE as is_indoor, refine_roadnm_addr as road_addr,
                               'restaurant'::text as source_type,
                               ST_Distance(ST_SetSRID(ST_MakePoint(refine_wgs84_logt, refine_wgs84_lat), 4326)::geography,
                                           ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) as dist
                        FROM locallink.gg_restaurant_info
                        WHERE bsn_state_nm = '영업'
                        {additional_filter}
                        ORDER BY dist ASC LIMIT 5
                    """
                cur.execute(fallback_query, (self.lng, self.lat))
                return cur.fetchall()

    # 6. 도슨트용 데이터 추출
    def get_docent_material(self, name, alert_type=None, table_type="attraction"):
        """
        DB에 재료가 없으면 실시간으로 리뷰 수집기를 돌려 적재한 뒤 도슨트 재료를 반환합니다.
        """
        if table_type not in ("attraction", "restaurant"):
            raise ValueError("table_type must be 'attraction' or 'restaurant'")

        # 1. 먼저 DB 조회 시도
        res = self._query_docent_material_from_db(name, alert_type, table_type)

        # 2. 데이터가 없거나 리뷰가 부족하면 실시간 파이프라인 가동
        if not res or not res.get("reviews") or res["reviews"] == "관련 리뷰 없음":
            print(f"\n📦 [{name}] 데이터 부족 감지 -> 실시간 파이프라인 가동...")
            try:
                if table_type == "attraction":
                    from src.collectors.load_review_pipeline import run_review_pipeline
                    run_review_pipeline(name)
                else:
                    # load_restaurant_review.py의 실제 엔트리 함수명은 run_restaurant_pipeline 입니다.
                    from src.collectors.load_restaurant_review import run_restaurant_pipeline
                    sigun_nm = self.get_user_sigun_nm()
                    run_restaurant_pipeline(name, sigun_nm)

                # 3. 적재 완료 후 재조회
                res = self._query_docent_material_from_db(name, alert_type, table_type)
            except Exception as e:
                print(f"⚠️ 실시간 수집 중 오류 발생: {e}")

        # 4. 상황별 도슨트 지침 설정
        if res:
            res["instruction"] = {
                "rain_alert": "비가 내리기 시작했다는 것을 감성적으로 언급하며, 실내로 이동해 비 오는 날의 특별한 분위기를 즐기자고 친근하게 제안하세요. 갑자기 변한 날씨 때문에 추천하는 것임을 자연스럽게 표현하세요.",
                "pm_alert": "미세먼지가 나빠졌다는 것을 부드럽게 언급하며, 실내로 이동해 쾌적한 환경에서 시간을 보내자고 친근하게 제안하세요. 날씨 변화에 대응하는 것임을 자연스럽게 표현하세요.",
                "cold_alert": "기온이 급락하거나 바람이 강해 무척 춥다는 점을 언급하며, 따뜻한 실내에서 몸을 녹이자고 제안하세요. 갑자기 변한 날씨 때문에 추천하는 것임을 자연스럽게 표현하세요.",
                "heat_alert": "야외 활동을 하기엔 날씨가 너무 뜨거워졌음을 언급하며, 시원한 실내에서 열기를 식히자고 제안하세요. 갑자기 변한 날씨 때문에 추천하는 것임을 자연스럽게 표현하세요.",
                "bad_weather_alert": "현재는 야외활동을 지양하는 상태임을 부드럽게 언급하고, 특정 원인을 단정하지 말고 쾌적한 실내에서 시작하자고 친근하게 제안하세요.",
                "clear_sky_alert": "날씨가 맑아졌다는 것을 반갑게 언급하며, 야외로 나가 햇살과 풍경을 즐기자고 친근하게 제안하세요. 날씨가 좋아진 기회를 활용하자는 것을 자연스럽게 표현하세요.",
            }.get(alert_type, "이 장소의 매력을 친근하고 다정하게 소개하세요.")
            res["alert_type"] = alert_type

        return res

    def _query_docent_material_from_db(self, name, alert_type, table_type):
        """실제 DB에서 도슨트 재료를 조회하는 내부 메서드"""
        weather_keywords = {
            "rain_alert": "비, 빗소리, 창가, 실내, 운치, 젖은, 소나기",
            "pm_alert": "실내, 쾌적, 공기, 깨끗, 안심, 필터",
            "cold_alert": "따뜻, 실내, 난방, 아늑, 온기, 포근",
            "heat_alert": "시원, 냉방, 그늘, 쾌적, 휴식, 에어컨",
            "bad_weather_alert": "실내, 쾌적, 안전, 휴식, 편안",
            "clear_sky_alert": "산책, 맑음, 햇살, 야외, 풍경, 하늘, 피크닉",
        }
        keyword_pattern = weather_keywords.get(alert_type, "추천, 방문, 분위기").replace(", ", "|")

        if table_type == "attraction":
            query = """
                SELECT d.attraction_name as place_name,
                       COALESCE(d.overview, '매력적인 장소입니다.') as overview,
                       d.tags as tags,
                       (SELECT string_agg(clean_text, ' | ') FROM (
                           SELECT clean_text
                           FROM locallink.attraction_reviews
                           WHERE attraction_name = d.attraction_name
                           ORDER BY (CASE WHEN clean_text SIMILAR TO %s THEN 1 ELSE 2 END) ASC,
                                    post_date DESC
                           LIMIT 5
                       ) AS sub) as reviews
                FROM locallink.attraction_descriptions d
                WHERE d.attraction_name = %s
                LIMIT 1
            """
            params = (f"%({keyword_pattern})%", name)
        else:
            query = """
                SELECT g.bizplc_nm as place_name,
                       COALESCE(g.refine_roadnm_addr, '매력적인 장소입니다.') as overview,
                       NULL::text as tags,
                       (SELECT string_agg(clean_text, ' | ') FROM (
                           SELECT clean_text
                           FROM locallink.restaurant_reviews
                           WHERE restaurant_name = g.bizplc_nm
                           ORDER BY (CASE WHEN clean_text SIMILAR TO %s THEN 1 ELSE 2 END) ASC,
                                    post_date DESC
                           LIMIT 5
                       ) AS sub) as reviews
                FROM locallink.gg_restaurant_info g
                WHERE g.bizplc_nm = %s
                LIMIT 1
            """
            params = (f"%({keyword_pattern})%", name)

        with psycopg2.connect(self.dsn) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                res = cur.fetchone()
                if not res:
                    return None
                if not res.get("reviews"):
                    res["reviews"] = "관련 리뷰 없음"
                return res

    # 7. 여러 추천 장소를 하나의 통합 도슨트 스크립트로 생성
    def create_combined_docent_script(self, recommendations, alert_type, language="English", max_count=3):
        """
        추천된 여러 장소를 하나의 통합된 도슨트 멘트로 생성합니다.
        
        Args:
            recommendations: 추천 장소 리스트
            alert_type: 날씨 상황 타입
            language: 생성할 언어
            max_count: 최대 포함 장소 수
        
        Returns:
            {"script": "통합 도슨트 멘트", "places": [...장소 정보...]}
        """
        if not recommendations:
            return {"script": "", "places": []}
        
        # 각 장소의 재료 수집
        places_data = []
        for recommendation in recommendations[:max_count]:
            target_name = recommendation['name']
            target_type = recommendation.get('source_type', 'attraction')
            distance = recommendation.get('dist', 0)
            
            material = self.get_docent_material(target_name, alert_type, table_type=target_type)
            
            if material:
                places_data.append({
                    "name": target_name,
                    "distance": distance,
                    "type": target_type,
                    "overview": material.get('overview', ''),
                    "tags": material.get('tags', ''),
                    "reviews": material.get('reviews', '')
                })
        
        if not places_data:
            return {"script": "추천할 장소 정보를 찾을 수 없습니다.", "places": []}
        
        # 통합 스크립트 생성
        output_language = language or "English"

        # 복수 원인 텍스트(있을 때만) 생성
        multi_reason_text = ""
        if self.last_alert_reasons:
            reason_labels = {
                'rain_alert': '비/눈',
                'pm_alert': '미세먼지',
                'cold_alert': '한파/강풍',
                'heat_alert': '폭염',
            }
            reasons = [reason_labels.get(r, r) for r in self.last_alert_reasons]
            multi_reason_text = f"현재 야외활동이 어려운 이유는 {', '.join(reasons)}입니다. 이 원인들을 자연스럽게 언급해 주세요. "
        
        # 날씨 상황별 지침
        weather_instruction = {
            "rain_alert": "비가 내리기 시작했다는 것을 감성적으로 언급하며, 실내로 이동해 비 오는 날의 특별한 분위기를 즐기자고 친근하게 제안하세요.",
            "pm_alert": "미세먼지가 나빠졌다는 것을 부드럽게 언급하며, 실내로 이동해 쾌적한 환경에서 시간을 보내자고 친근하게 제안하세요.",
            "cold_alert": "기온이 급락하거나 바람이 강해 무척 춥다는 점을 언급하며, 따뜻한 실내에서 몸을 녹이자고 제안하세요. 갑자기 변한 날씨 때문에 추천하는 것임을 자연스럽게 표현하세요.",
            "heat_alert": "야외 활동을 하기엔 날씨가 너무 뜨거워졌음을 언급하며, 시원한 실내에서 열기를 식히자고 제안하세요. 갑자기 변한 날씨 때문에 추천하는 것임을 자연스럽게 표현하세요.",
            "bad_weather_alert": "야외활동을 지양하는 상태임을 부드럽게 언급하되, 특정 원인을 단정하지 말고 실내에서 편안히 시작하자고 친근하게 제안하세요.",
            "clear_sky_alert": "날씨가 맑아졌다는 것을 반갑게 언급하며, 야외로 나가 햇살과 풍경을 즐기자고 친근하게 제안하세요.",
        }.get(alert_type, "이 장소들의 매력을 친근하고 따뜻하게 소개하세요.")
        weather_instruction = multi_reason_text + weather_instruction
        
        # 장소 정보를 문자열로 정리
        places_summary = ""
        for i, place in enumerate(places_data, 1):
            distance_km = place['distance'] / 1000
            places_summary += f"\n{i}. {place['name']} (거리: {distance_km:.1f}km)\n"
            places_summary += f"   - 소개: {place['overview'][:100]}...\n"
            if place.get('reviews'):
                places_summary += f"   - 리뷰: {place['reviews'][:150]}...\n"
        
        system_prompt = f"""
        당신은 친근한 여행 가이드 'LALA'입니다.
        사용자와 함께 있는 친구처럼 자연스럽게 대화하며, 갑자기 변한 날씨 상황을 언급하고 
        여러 장소를 선택지로 제안하세요.

        스타일:
        - 반드시 {output_language}로 작성
        - 친구에게 말하듯 자연스럽고 따뜻한 톤, 존댓말 (~네요, ~같아요, ~어때요?, ~볼까요?)
        - 3-5문장으로 간결하게
        - 이모지 사용 금지

        구조:
        1) 첫 문장: 날씨 변화를 감성적으로 언급 (복합 원인이면 모두 포함)
        2) 둘째 문장: "근처에 3곳 정도 괜찮은 곳이 있는데요" 같은 도입
        3) 각 장소별로 핵심 특징 1개씩 간단히 소개 (1-2문장씩)
        4) 마지막: "어디로 가볼까요?" 같은 선택 유도

        중요:
        - 각 장소의 특징을 간결하게 언급 (장황하지 않게)
        - 명소는 소개 내용 기반, 음식점은 리뷰 기반으로 설명
        - ★ 야외활동 지양 이유가 여러 개면, 스크립트에 그 모든 이유를 자연스럽게 포함하세요 ★
          (예: "비도 많이 오고 미세먼지까지 심해서..." / "추위도 있고 바람도 강해서...")
        - 반드시 {output_language}로 작성
        
        금지사항:
        - 리뷰나 개요에 없는 구체적 정보 만들지 말 것
        - 홍보성 문구, 과장된 수식어 금지
        """

        user_prompt = f"""
        [상황]
        {weather_instruction}

        [추천 장소 {len(places_data)}곳]
        {places_summary}

        [요청]
        위 {len(places_data)}개 장소를 하나의 멘트로 자연스럽게 소개하세요.
        날씨가 변했고, 그래서 이 장소들 중 하나를 선택하면 좋겠다는 느낌으로요.
        
        ★ 매우 중요 ★
        야외활동 지양 이유가 다중으로 있다면, 스크립트에 그 이유들을 모두 자연스럽게 포함해야 합니다.
        예: "비도 오고 미세먼지도 심해서" / "강풍에 추위도 있어서" 등
        
        각 장소의 핵심만 간단히 언급하고, 사용자가 선택할 수 있도록 열린 질문으로 마무리하세요.
        """

        try:
            client = self._get_openai_client()
            response = client.chat.completions.create(
                model=self._get_openai_deployment_name(),
                messages=[
                    {"role": "system", "content": system_prompt.strip()},
                    {"role": "user", "content": user_prompt.strip()},
                ],
                temperature=0.3,
                max_tokens=300,
            )

            script = (response.choices[0].message.content or "").strip()
            if script:
                return {"script": script, "places": places_data}
        except Exception as e:
            print(f"⚠️ Azure OpenAI 통합 도슨트 생성 실패: {e}")

        # Fallback
        place_names = ", ".join([p['name'] for p in places_data])
        fallback_script = f"어, 날씨가 좀 변했네요. 근처에 {place_names} 이런 곳들이 있는데, 어디로 가볼까요?"
        return {"script": fallback_script, "places": places_data}