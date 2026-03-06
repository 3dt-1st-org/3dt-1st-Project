-- =============================================================================
-- 선제적 추천 매칭 쿼리: PostGIS + pgvector 하이브리드 (관광지 전용)
-- is_indoor 컬럼: GPT-4o-mini 일괄 분류 결과 저장 (classify_tourist_indoor.py)
--   TRUE=실내 → 악천후 통과 / FALSE=실외·NULL=판단불가 → 악천후 제외
-- 음식점은 별도 추천 알고리즘으로 분리 예정
-- =============================================================================
-- 대상 테이블 (실제 스키마 기준):
--   locallink.tourist_spot_info       -- 관광지 (lat, lng, tourist_nm, is_indoor)
--   locallink.attraction_reviews      -- 리뷰 + 임베딩 (embedding vector)
--   locallink.realtime_weather_conditions -- 실시간 날씨 (outdoor_status, pm10, pm25)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 메인 하이브리드 매칭 쿼리
-- -----------------------------------------------------------------------------
-- 파라미터 (백엔드에서 바인딩):
--   :city          VARCHAR  -- 사용자 위치 도시 (예: '수원')
--   :user_lng      FLOAT    -- 사용자 경도 (예: 126.9990)
--   :user_lat      FLOAT    -- 사용자 위도 (예: 37.2665)
--   :radius_m      INT      -- 반경 미터 (예: 5000)
--   :top_k         INT      -- 최종 후보 수 (예: 3)
-- -----------------------------------------------------------------------------

WITH

-- 1. 사용자 위치 도시의 최신 날씨
CurrentWeather AS (
    SELECT
        outdoor_status,
        temperature,
        pm10,
        pm25,
        precipitation_type
    FROM   locallink.realtime_weather_conditions
    WHERE  location = :city            -- 파라미터 바인딩
    ORDER  BY record_time DESC
    LIMIT  1
),

-- 2. 관광지 후보: 반경 필터
-- is_indoor: GPT 사전 분류 컬럼 직접 참조 (리뷰 키워드 의존 제거)
AttractionCandidates AS (
    SELECT
        t.tourist_nm                                      AS place_name,
        t.tourist_nm_en                                   AS place_name_en,
        t.road_addr                                       AS road_address,
        t.road_addr_en                                    AS road_address_en,
        t.sigun_nm,
        t.lat,
        t.lng,
        t.is_indoor,                                      -- GPT 분류 결과 직접 참조
        'attraction'                                      AS place_type,
        -- PostGIS 거리 계산 (미터)
        ST_Distance(
            ST_SetSRID(ST_MakePoint(:user_lng, :user_lat), 4326)::geography,
            ST_SetSRID(ST_MakePoint(t.lng::float, t.lat::float), 4326)::geography
        )                                                 AS distance_meters
    FROM   locallink.tourist_spot_info t
    WHERE
        t.lat  IS NOT NULL
        AND t.lng  IS NOT NULL
        -- [반경 필터] (날씨 필터보다 먼저 적용해 후보군 사전 축소)
        AND ST_DWithin(
            ST_SetSRID(ST_MakePoint(:user_lng, :user_lat), 4326)::geography,
            ST_SetSRID(ST_MakePoint(t.lng::float, t.lat::float), 4326)::geography,
            :radius_m
        )
),

-- 2-b. 날씨 조건 적용
AttractionFiltered AS (
    SELECT ac.*
    FROM   AttractionCandidates ac
    CROSS  JOIN CurrentWeather cw
    WHERE
        -- 악천후: is_indoor=TRUE(실내)만 통과, FALSE(실외)·NULL(판단불가) 제외
        -- 쾌적: 실내외 모두 통과
        CASE
            WHEN (
                cw.outdoor_status IN ('비/눈', '미세먼지 나쁨', '폭염', '한파', '대기 나쁨')
                OR cw.precipitation_type IN (1, 2, 3)
                OR cw.pm10  > 80
                OR cw.pm25  > 35
                OR cw.temperature > 33
                OR cw.temperature < -10
            )
            THEN ac.is_indoor = TRUE
            ELSE TRUE
        END
),

-- 3. 대표 리뷰 스니펫 조인
AttractionWithReview AS (
    SELECT
        ac.*,
        (
            SELECT ar.description
            FROM   locallink.attraction_reviews ar
            WHERE  ar.attraction_name = ac.place_name
            ORDER  BY ar.post_date DESC NULLS LAST
            LIMIT  1
        )                                                 AS review_snippet
    FROM   AttractionFiltered ac
)

-- 4. 최종 정렬 및 상위 K개 반환
-- (음식점은 별도 알고리즘으로 분리)
SELECT
    place_name,
    place_name_en,
    road_address,
    road_address_en,
    sigun_nm,
    place_type,
    is_indoor,
    ROUND(distance_meters::numeric, 0)                   AS distance_m,
    review_snippet
FROM   AttractionWithReview
ORDER BY distance_meters ASC
LIMIT  :top_k;
