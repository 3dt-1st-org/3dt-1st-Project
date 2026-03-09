-- 실시간 날씨/환경 데이터 적재 테이블 생성 SQL
CREATE TABLE locallink.realtime_weather_conditions (
    id SERIAL PRIMARY KEY,                        -- 데이터베이스 고유 식별자 (자동 증가)
    
    -- 1. 기준 정보 (위치 및 시간)
    location VARCHAR(50) NOT NULL,                -- ASA 쿼리의 CASE 문으로 매핑된 한글 도시명 ('수원', '용인')
    record_time TIMESTAMP WITH TIME ZONE NOT NULL,-- ASA의 System.Timestamp()가 꽂히는 30분 윈도우 종료 시간
    
    -- 2. 기상청 초단기 실황 집계 데이터
    temperature DOUBLE PRECISION,                 -- ASA의 CAST(... AS float) 및 AVG() 연산 결과 대응
    precipitation_type BIGINT,                    -- ASA의 CAST(... AS bigint) 및 MAX() 연산 결과 대응 (0=없음, 1=비 등)
    wind_speed DOUBLE PRECISION,                  -- ASA의 CAST(... AS float) 및 MAX() 연산 결과 대응
    
    -- 3. 한국환경공단 미세먼지 집계 데이터
    pm10 BIGINT,                                  -- ASA의 CAST(... AS bigint) 및 MAX() 연산 결과 대응
    pm25 BIGINT,                                  -- ASA의 CAST(... AS bigint) 및 MAX() 연산 결과 대응
    
    -- 4. AI 도슨트 컨텍스트용 파생 변수
    outdoor_status VARCHAR(50),                   -- ASA의 CASE 문으로 생성된 한글 상태 텍스트 ('비/눈', '야외활동 쾌적' 등)
    is_rain_snow BIGINT,                          -- ASA 계산 플래그: 강수(비/눈) 여부 (1=참, 0=거짓)
    is_bad_dust BIGINT,                           -- ASA 계산 플래그: 미세먼지 나쁨 여부 (1=참, 0=거짓)
    is_heatwave BIGINT,                           -- ASA 계산 플래그: 폭염 여부 (1=참, 0=거짓)
    is_coldwave BIGINT,                           -- ASA 계산 플래그: 한파 여부 (1=참, 0=거짓)
    is_strong_wind BIGINT,                        -- ASA 계산 플래그: 강풍 여부 (1=참, 0=거짓)
    
    -- 5. 시스템 메타데이터
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP -- Azure에서 PostgreSQL로 데이터가 실제 INSERT된 물리적 시간
);


-- 지역명(location)을 먼저 찾고, 기록 시간(record_time)을 역순(최신순)으로 정렬해 두는 인덱스
CREATE INDEX idx_realtime_weather_ai_lookup 
ON locallink.realtime_weather_conditions (location, record_time DESC);