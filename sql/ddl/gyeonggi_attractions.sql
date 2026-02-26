-- 1. 테이블 생성 (컬럼명은 영어)
CREATE TABLE gyeonggi_attractions (
    id SERIAL PRIMARY KEY,
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

-- 2. 컬럼별 한글 코멘트 추가
COMMENT ON COLUMN gyeonggi_attractions.id IS '고유 번호 (자동 생성)';
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