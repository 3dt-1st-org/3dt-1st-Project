-- 1. 스키마 및 확장 재확인
CREATE SCHEMA IF NOT EXISTS locallink;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;

-- 기존 테스트 테이블이 있다면 삭제 (초기화)
DROP TABLE IF EXISTS locallink.reviews;
DROP TABLE IF EXISTS locallink.locations;

-- 2. 명소 테이블 생성 (PostGIS 적용)
CREATE TABLE locallink.locations (
    id SERIAL PRIMARY KEY,
    name_ko VARCHAR(100) NOT NULL,
    geom GEOGRAPHY(Point, 4326),  --[PostGIS 핵심] 위경도를 기반으로 실제 지구 곡률을 반영하는 공간 데이터 타입
    geofence_radius_m INT NOT NULL
);

-- 3. 명소 리뷰 테이블 생성 (pgvector 적용 - RAG 도슨트용)
CREATE TABLE locallink.reviews (
    id SERIAL PRIMARY KEY,
    location_id INT REFERENCES locallink.locations(id),
    review_text TEXT NOT NULL,
    embedding VECTOR(3) -- [pgvector 핵심] 텍스트의 의미를 담는 벡터 (실제 OpenAI 연동 시 1536 차원 사용, 테스트용으로 3차원 설정)
);

-- 4. 기초 시드 데이터 삽입 (명소)
-- 주의: ST_MakePoint는 (경도, 위도) 순서로 입력해야 합니다. (X, Y 좌표계)
INSERT INTO locallink.locations (name_ko, geom, geofence_radius_m) VALUES 
('광화문 광장', ST_SetSRID(ST_MakePoint(126.976900, 37.575900), 4326)::geography, 100),
('경복궁 근정전', ST_SetSRID(ST_MakePoint(126.977041, 37.579617), 4326)::geography, 150);

-- 5. 기초 시드 데이터 삽입 (리뷰 및 가상 임베딩)
INSERT INTO locallink.reviews (location_id, review_text, embedding) VALUES 
(1, '이순신 장군 동상 앞에서 사진 찍기 너무 좋아요. 야경이 특히 멋집니다.', '[0.1, 0.8, 0.2]'),
(1, '광장이 넓어져서 산책하기 좋습니다. 아이들과 오기 좋아요.', '[0.9, 0.1, 0.1]'),
(2, '조선 왕실의 위엄이 느껴집니다. 한복 입고 가면 무료입장이라 더 좋아요.', '[0.2, 0.2, 0.9]'),
(2, '근정전 처마의 단청이 정말 아름다워요. 외국인 친구가 감탄했습니다.', '[0.3, 0.3, 0.8]');


-- 아래의 attraction_reviews 테이블의 레퍼런스가 되는 테이블을 임시로 생성 (혜민님꺼 참고)
CREATE TABLE gyeonggi_attractions (
    attraction_name TEXT NOT NULL,
    phone_number TEXT,
    additional_info TEXT,
    base_date DATE,
    road_address TEXT,
    lot_address TEXT,
    zip_code VARCHAR(10),
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    city_county_name VARCHAR(50)
);
COMMENT ON COLUMN gyeonggi_attractions.attraction_name IS '명소명';
COMMENT ON COLUMN gyeonggi_attractions.phone_number IS '전화번호';
COMMENT ON COLUMN gyeonggi_attractions.additional_info IS '부가정보 (이용료, 주차료 등)';
COMMENT ON COLUMN gyeonggi_attractions.base_date IS '데이터 기준 일자';
COMMENT ON COLUMN gyeonggi_attractions.road_address IS '정제 도로명 주소';
COMMENT ON COLUMN gyeonggi_attractions.lot_address IS '정제 지번 주소';
COMMENT ON COLUMN gyeonggi_attractions.zip_code IS '정제 우편번호';
COMMENT ON COLUMN gyeonggi_attractions.latitude IS '정제 WGS84 위도';
COMMENT ON COLUMN gyeonggi_attractions.longitude IS '정제 WGS84 경도';
COMMENT ON COLUMN gyeonggi_attractions.city_county_name IS '시군명';


CREATE TABLE locallink.attraction_reviews (
    id SERIAL PRIMARY KEY,
    attraction_name INT REFERENCES gyeonggi_attractions(attraction_name) ON DELETE CASCADE,
    title TEXT,                  -- 블로그 제목 (원본)
    description TEXT,            -- 블로그 요약 내용 (원본)
    post_date DATE,              -- 리뷰 작성 일자
    post_link TEXT,              -- 블로그 링크
    clean_text TEXT,             -- HTML 태그 제거 및 정제된 텍스트
    extracted_keywords TEXT,     -- NLP로 추출된 형용사/명사 (예: "조용한, 아늑한, 커피, 뷰")
    embedding VECTOR(1536),      -- 정제된 텍스트를 OpenAI 등으로 변환한 벡터 (추후 사용)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE locallink.attraction_reviews IS '관광지별 블로그 리뷰 데이터 및 벡터 정보';