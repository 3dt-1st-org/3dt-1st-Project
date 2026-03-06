-- =============================================================================
-- 선제적 추천 매칭 쿼리: PostGIS + pgvector 하이브리드 (관광지 전용)
-- is_indoor 컬럼: GPT-4o-mini 일괄 분류 결과 저장 (classify_tourist_indoor.py)
--   TRUE=실내, FALSE=실외, NULL=판단불가(악천후에도 항상 통과)
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
--   :query_vector  VECTOR   -- 사용자 검색어 임베딩 (예: '[0.12, -0.34, ...]'::vector)
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
        -- 악천후: is_indoor=FALSE(실외)만 제외, TRUE(실내)·NULL(판단불가) 통과
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
            THEN ac.is_indoor IS NOT FALSE
            ELSE TRUE
        END
),

-- 3. 관광지 후보에 리뷰 임베딩 조인 (벡터 유사도용)
AttractionWithEmbedding AS (
    SELECT
        ac.*,
        -- AttractionFiltered 에서 날씨 필터 완료된 후보만 사용
        -- 리뷰 임베딩 중 사용자 쿼리와 가장 유사한 것 선택
        -- <=> 코사인 거리 사용: 값 범위 [0, 2], 정규화 용이
        -- NULLIF: zero-norm 벡터 → NaN 반환 방어 (NULL로 변환)
        NULLIF(MIN(ar.embedding <=> :query_vector::vector), 'NaN'::float)  AS vector_distance,
        COUNT(ar.id)                                      AS review_count,
        -- 대표 리뷰 스니펫 (최신 1건)
        (
            SELECT ar2.description
            FROM   locallink.attraction_reviews ar2
            WHERE  ar2.attraction_name = ac.place_name
            ORDER  BY ar2.post_date DESC NULLS LAST
            LIMIT  1
        )                                                 AS review_snippet
    FROM   AttractionFiltered ac
    LEFT   JOIN locallink.attraction_reviews ar
           ON  ar.attraction_name = ac.place_name
           AND ar.embedding IS NOT NULL
    GROUP  BY
        ac.place_name, ac.place_name_en, ac.road_address, ac.road_address_en,
        ac.sigun_nm, ac.lat, ac.lng, ac.is_indoor, ac.place_type, ac.distance_meters
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
    ROUND(vector_distance::numeric, 4)                   AS similarity_score,
    review_count,
    review_snippet
FROM   AttractionWithEmbedding
ORDER BY
    -- [하이브리드 정렬] 거리 × 시맨틱 감쇄 공식
    --
    -- 설계 원칙: 벡터 유사도가 높을수록 거리 패널티를 줄여 순위를 올림
    --   score = dist_norm × (1 - similarity × boost)
    --   similarity = 1 - cosine_dist/2   → [0, 1]
    --   boost_factor = 0.8
    --
    -- 예시 (radius=10km):
    --   수원화성(1m, cosine=0.58): 0.0001 × (1 - 0.71×0.8) = 0.0001×0.432 ≈ 0.0000432
    --   → 리뷰 없는 관광지(vector NULL): dist_norm 그대로 (거리 순 정렬)
    --
    -- ※ zero-norm 벡터 → NaN 방어: NULLIF로 NULL 변환 후 처리
    CASE WHEN vector_distance IS NOT NULL
         THEN (distance_meters / :radius_m)
              * (1.0 - GREATEST(0.0, 1.0 - vector_distance / 2.0) * 0.8)
         ELSE (distance_meters / :radius_m)
    END ASC
LIMIT  :top_k;
