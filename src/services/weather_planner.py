import psycopg2
from psycopg2.extras import RealDictCursor
from config.vault_manager import get_vault_manager
from openai import AzureOpenAI

class WeatherTravelPlanner:
    def __init__(self, user_lat, user_lng):
        self.lat = user_lat
        self.lng = user_lng
        self.dsn = self._get_dsn()
        self.last_weather_state = None

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

    # 3. 아침 전체 계획 생성
    def get_morning_itinerary(self, radius_m=10000):
        weather = self.get_current_location_weather()
        if not weather: return []
        
        # None 값 처리
        precipitation_type = weather.get('precipitation_type') or 0
        pm10 = weather.get('pm10', 0) or 0
        is_bad = (precipitation_type > 0) or (pm10 > 80)
        indoor_filter = "AND is_indoor = TRUE" if is_bad else ""
        
        return self._execute_recommendation_query(radius_m, indoor_filter, table_type="attraction")

    # 4. 실시간 날씨 변동 선제시 (상황 세분화)
    def check_and_propose_intervention(self, radius_m=10000):
        """
        날씨 변화를 감지하고 적절한 장소를 추천합니다.
        radius_m: 최대 추천 거리 (기본: 10km)
        """
        new_weather = self.get_current_location_weather()
        if not new_weather: return None

        # None 값 처리: precipitation_type이 None이면 0으로 취급
        precipitation_type = new_weather.get('precipitation_type') or 0
        outdoor_status = new_weather.get('outdoor_status', '')
        pm10 = new_weather.get('pm10', 0) or 0

        # 변동 감지 (이전 상태와 비교)
        current_state = f"{precipitation_type}_{outdoor_status}"
        if self.last_weather_state == current_state:
            return None 

        self.last_weather_state = current_state
        
        # 상황 A-a: 비 감지 (실내 대피)
        if precipitation_type > 0:
            print("☔ 상황 A-a: 비 감지")
            indoor_attr = self._execute_recommendation_query(radius_m, "AND is_indoor = TRUE", "attraction")
            # 비 오는 날은 일반 음식점 제외, 카페만 추천
            nearby_cafes = self._execute_recommendation_query(
                radius_m,
                "AND bizcond_div_nm_info = '까페'",
                "restaurant"
            )
            combined = sorted(indoor_attr + nearby_cafes, key=lambda x: x['dist'])
            return combined[:5], "rain_alert"

        # 상황 A-b: 미세먼지 나쁨 감지 (실내 대피)
        elif '미세먼지 나쁨' in outdoor_status:
            print("😷 상황 A-b: 미세먼지 나쁨 감지")
            indoor_attr = self._execute_recommendation_query(radius_m, "AND is_indoor = TRUE", "attraction")
            nearby_cafes = self._execute_recommendation_query(radius_m, "", "restaurant")
            combined = sorted(indoor_attr + nearby_cafes, key=lambda x: x['dist'])
            return combined[:5], "pm_alert"

        # 상황 B: 기상 호전 (야외활동 가능)
        elif outdoor_status == '야외활동 쾌적':
            print("☀️ 상황 B: 날씨 호전 감지")
            # 야외 명소 우선 조회
            outdoor_attr = self._execute_recommendation_query(radius_m, "AND is_indoor = FALSE", "attraction")
            # 야외 명소가 부족하면 전체 명소도 포함
            if len(outdoor_attr) < 3:
                all_attr = self._execute_recommendation_query(radius_m, "", "attraction")
                # 중복 제거하면서 병합
                seen_names = {attr['name'] for attr in outdoor_attr}
                for attr in all_attr:
                    if attr['name'] not in seen_names and len(outdoor_attr) < 5:
                        outdoor_attr.append(attr)
                        seen_names.add(attr['name'])
            # 거리순 정렬
            combined = sorted(outdoor_attr, key=lambda x: x['dist'])
            return combined[:5], "clear_sky_alert"

        return None
    
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
                        WHERE 1=1
                        {additional_filter}
                        ORDER BY dist ASC LIMIT 10
                    """
                else:
                    query = f"""
                        SELECT bizplc_nm as name, refine_wgs84_lat as lat, refine_wgs84_logt as lng, 
                               TRUE as is_indoor, refine_roadnm_addr as road_addr,
                               'restaurant'::text as source_type,
                               ST_Distance(ST_SetSRID(ST_MakePoint(refine_wgs84_logt, refine_wgs84_lat), 4326)::geography, 
                                           ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) as dist
                        FROM locallink.gg_restaurant_info
                        WHERE bsn_state_nm = '영업'
                        {additional_filter}
                        ORDER BY dist ASC LIMIT 10
                    """
                cur.execute(query, (self.lng, self.lat))
                results = cur.fetchall()
                
                # 결과에서 최대 거리 제한 적용 (너무 먼 곳 제외)
                filtered = [r for r in results if r['dist'] <= radius_m]
                return filtered if filtered else results[:5]  # 조건에 맞는 게 없으면 가까운 순 5개

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
                "clear_sky_alert": "날씨가 맑아졌다는 것을 반갑게 언급하며, 야외로 나가 햇살과 풍경을 즐기자고 친근하게 제안하세요. 날씨가 좋아진 기회를 활용하자는 것을 자연스럽게 표현하세요.",
            }.get(alert_type, "이 장소의 매력을 친근하고 따뜻하게 소개하세요.")
            res["alert_type"] = alert_type

        return res

    def _query_docent_material_from_db(self, name, alert_type, table_type):
        """실제 DB에서 도슨트 재료를 조회하는 내부 메서드"""
        weather_keywords = {
            "rain_alert": "비, 빗소리, 창가, 실내, 운치, 젖은, 소나기",
            "pm_alert": "실내, 쾌적, 공기, 깨끗, 안심, 필터",
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

    # 7. Azure OpenAI 기반 도슨트 스크립트 생성
    def create_docent_script(self, material, language="English"):
        """
        추출된 데이터를 바탕으로 Azure OpenAI가 사용자에게 제공할 도슨트 멘트를 생성합니다.
        language 예시: Korean, English, Japanese
        """
        tags = material.get("tags")
        tags_text = ", ".join(tags) if isinstance(tags, list) and tags else (tags or "다양한 매력")
        output_language = language or "English"

        system_prompt = f"""
        당신은 친근한 여행 가이드 '라라'입니다.
        사용자와 함께 있는 친구처럼 자연스럽게 대화하며, 갑자기 변한 날씨 상황을 언급하고 그에 맞는 장소를 추천하세요.

        스타일:
        - 반드시 {output_language}로 작성
        - 친구에게 말하듯 자연스럽고 따뜻한 톤이되, 존댓말 (~네요, ~같아요, ~어때요?, ~볼까요?)
        - 2-3문장으로 간결하게
        - 이모지 사용 금지

        구조:
        1) 첫 문장: 날씨 변화를 감성적으로 언급 (예: "어, 비가 내리기 시작하네요", "날씨가 갑자기 맑아졌네요", "미세먼지가 좀 나빠진 것 같아요")
        2) 둘째 문장: 그래서 여기로 이동/방문하면 좋을 것 같다는 자연스러운 제안 + 소개(overview) 또는 리뷰에서 뽑은 구체적 근거 1개
        3) 셋째 문장(선택): 부드러운 행동 제안
        4) 마지막 문장은 사용자가 행동으로 옮길 수 있도록 유도 (예: "한번 가볼까요?", "들어가서 분위기 한번 느껴볼까요?")

        중요:
        - 명소(관광지)의 경우: 반드시 '소개'에 나온 장소의 배경, 역사, 특징을 활용하여 설명하세요
        - 음식점의 경우: 리뷰에 나온 실제 방문자 경험을 중심으로 설명하세요
        - 반드시 {output_language}로 작성하세요

        금지사항:
        - 리뷰나 개요에 없는 구체적 정보(메뉴명, 국가명, 가격, 시설명 등) 절대 만들지 말 것
        - 홍보성 문구, 과장된 수식어 금지
        - 형식적인 멘트 금지 ("~를 추천드립니다", "방문해보세요" 같은 딱딱한 표현 피하기)
            """

        user_prompt = f"""
        [상황]
        {material.get('instruction', '이 장소의 매력을 친근하고 따뜻하게 소개하세요.')}

        [추천 장소]
        - 이름: {material.get('place_name', '')}
        - 특징: {tags_text}
        - 소개: {material.get('overview', '')}
        - 실제 방문자 리뷰: {material.get('reviews', '')}

        [요청]
        사용자에게 바로 말해줄 도슨트 멘트를 작성하세요.
        날씨가 갑자기 변했고, 그래서 이 장소를 추천하는 거예요.
        친구처럼 자연스럽게, "어, 비 오네? 그럼 여기 가볼까?" 같은 느낌으로요.
        
        **명소인 경우**: '소개'에 나온 장소의 배경이나 특징을 자연스럽게 언급하세요.
        **음식점인 경우**: 리뷰에서 언급된 실제 특징 1개를 꼭 포함하세요.
        """

        try:
            client = self._get_openai_client()
            response = client.chat.completions.create(
                model=self._get_openai_deployment_name(),
                messages=[
                    {"role": "system", "content": system_prompt.strip()},
                    {"role": "user", "content": user_prompt.strip()},
                ],
                temperature=0.2,
                max_tokens=220,
            )

            script = (response.choices[0].message.content or "").strip()
            if script:
                return script
        except Exception as e:
            print(f"⚠️ Azure OpenAI 도슨트 생성 실패: {e}")

        # Fallback: 모델 호출 실패 시 최소 안내문 반환
        return (
            f"어, 날씨가 좀 변했네요. "
            f"그럼 {material.get('place_name', '이 장소')} 가보는 건 어때요? "
            f"{material.get('overview', '분위기 괜찮을 것 같아요.')} "
            "한번 가볼까요?"
        )

    # 8. 여러 추천 장소에 대한 도슨트 멘트 일괄 생성
    def create_multiple_docent_scripts(self, recommendations, alert_type, language="English", max_count=3):
        """
        추천된 여러 장소에 대해 도슨트 멘트를 일괄 생성하여 반환합니다.
        
        Args:
            recommendations: 추천 장소 리스트 (각 항목은 name, source_type, dist 포함)
            alert_type: 날씨 상황 타입 (rain_alert, pm_alert, clear_sky_alert)
            language: 생성할 언어 (English, Korean, Japanese)
            max_count: 최대 생성 개수 (기본: 3)
        
        Returns:
            도슨트 멘트가 포함된 장소 정보 리스트
            [{"name": "장소명", "distance": 거리, "type": "attraction/restaurant", "script": "도슨트 멘트"}, ...]
        """
        if not recommendations:
            return []
        
        results = []
        for recommendation in recommendations[:max_count]:
            target_name = recommendation['name']
            target_type = recommendation.get('source_type', 'attraction')
            distance = recommendation.get('dist', 0)
            
            # 도슨트 재료 추출
            material = self.get_docent_material(target_name, alert_type, table_type=target_type)
            
            if material:
                # 도슨트 멘트 생성
                script = self.create_docent_script(material, language=language)
                
                results.append({
                    "name": target_name,
                    "distance": distance,
                    "type": target_type,
                    "script": script,
                    "material": material  # 추가 정보가 필요한 경우를 위해
                })
            else:
                # 재료 추출 실패 시 기본 정보만 반환
                results.append({
                    "name": target_name,
                    "distance": distance,
                    "type": target_type,
                    "script": f"{target_name}에 대한 정보를 찾을 수 없습니다.",
                    "material": None
                })
        
        return results

    # 9. 여러 추천 장소를 하나의 통합 도슨트 스크립트로 생성
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
        
        # 날씨 상황별 지침
        weather_instruction = {
            "rain_alert": "비가 내리기 시작했다는 것을 감성적으로 언급하며, 실내로 이동해 비 오는 날의 특별한 분위기를 즐기자고 친근하게 제안하세요.",
            "pm_alert": "미세먼지가 나빠졌다는 것을 부드럽게 언급하며, 실내로 이동해 쾌적한 환경에서 시간을 보내자고 친근하게 제안하세요.",
            "clear_sky_alert": "날씨가 맑아졌다는 것을 반갑게 언급하며, 야외로 나가 햇살과 풍경을 즐기자고 친근하게 제안하세요.",
        }.get(alert_type, "이 장소들의 매력을 친근하고 따뜻하게 소개하세요.")
        
        # 장소 정보를 문자열로 정리
        places_summary = ""
        for i, place in enumerate(places_data, 1):
            distance_km = place['distance'] / 1000
            places_summary += f"\n{i}. {place['name']} (거리: {distance_km:.1f}km)\n"
            places_summary += f"   - 소개: {place['overview'][:100]}...\n"
            if place.get('reviews'):
                places_summary += f"   - 리뷰: {place['reviews'][:150]}...\n"
        
        system_prompt = f"""
        당신은 친근한 여행 가이드 '라라'입니다.
        사용자와 함께 있는 친구처럼 자연스럽게 대화하며, 갑자기 변한 날씨 상황을 언급하고 
        여러 장소를 선택지로 제안하세요.

        스타일:
        - 반드시 {output_language}로 작성
        - 친구에게 말하듯 자연스럽고 따뜻한 톤이되, 존댓말 (~네요, ~같아요, ~어때요?, ~볼까요?)
        - 3-5문장으로 간결하게
        - 이모지 사용 금지

        구조:
        1) 첫 문장: 날씨 변화를 감성적으로 언급
        2) 둘째 문장: "근처에 3곳 정도 괜찮은 곳이 있는데요" 같은 도입
        3) 각 장소별로 핵심 특징 1개씩 간단히 소개 (1-2문장씩)
        4) 마지막: "어디로 가볼까요?" 같은 선택 유도

        중요:
        - 각 장소의 특징을 간결하게 언급 (장황하지 않게)
        - 명소는 소개 내용 기반, 음식점은 리뷰 기반으로 설명
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