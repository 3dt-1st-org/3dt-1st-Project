-- 실시간 날씨/환경 데이터 적재 테이블 생성 SQL
CREATE TABLE locallink.realtime_weather_conditions (
    id SERIAL PRIMARY KEY,                        -- 데이터베이스 고유 식별자 (자동 증가)

    -- 1. 기준 정보 (위치 및 시간)
    location VARCHAR(50) NOT NULL,                -- ASA 쿼리의 CASE 문으로 매핑된 한글 도시명 ('수원', '용인')
    record_time TIMESTAMP WITH TIME ZONE NOT NULL,-- ASA의 System.Timestamp()가 꽂히는 30분 윈도우 종료 시간

    -- 2. 기상청 초단기 실황 집계 데이터
    temperature DOUBLE PRECISION,                 -- AVG() 연산 결과
    precipitation_type BIGINT,                    -- MAX() 연산 결과 (0=없음, 1=비, 2=비/눈, 3=눈, 4=소나기)
    wind_speed DOUBLE PRECISION,                  -- MAX() 연산 결과

    -- 3. 한국환경공단 미세먼지 집계 데이터
    pm10 BIGINT,
    pm25 BIGINT,

    -- 4. AI 도슨트 컨텍스트용 파생 플래그 (0=해당없음, 1=해당)
    -- outdoor_status 문자열 컬럼은 제거됨. 아래 플래그로 코드에서 직접 계산.
    outdoor_status VARCHAR(50),                   -- (deprecated) 값 미입력, 하위 호환을 위해 컬럼만 유지
    is_rain_snow   BIGINT,                        -- 비/눈 여부
    is_bad_dust    BIGINT,                        -- 미세먼지 나쁨 여부
    is_heatwave    BIGINT,                        -- 폭염 여부
    is_coldwave    BIGINT,                        -- 한파 여부
    is_strong_wind BIGINT,                        -- 강풍 여부

    -- 5. 시스템 메타데이터
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);


-- 지역명(location)을 먼저 찾고, 기록 시간(record_time)을 역순(최신순)으로 정렬해 두는 인덱스
CREATE INDEX idx_realtime_weather_ai_lookup 
ON locallink.realtime_weather_conditions (location, record_time DESC);