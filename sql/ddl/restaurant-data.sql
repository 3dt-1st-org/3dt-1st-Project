-- 1. 스키마 생성 (존재하지 않을 경우)
--CREATE SCHEMA IF NOT EXISTS locallink;

-- 2. 테이블 생성 (16개 핵심 컬럼 최적화)
CREATE TABLE locallink.gg_restaurant_info (
    bizplc_nm VARCHAR(200),               -- 사업장명
    refine_roadnm_addr TEXT,             -- 소재지도로명주소
    refine_lotno_addr TEXT,              -- 소재지지번주소
    refine_wgs84_lat NUMERIC(15, 10),    -- 위도
    refine_wgs84_logt NUMERIC(15, 10),   -- 경도
    unity_bsn_state_nm VARCHAR(50),      -- 통합영업상태명
    bsn_state_nm VARCHAR(50),            -- 영업상태명
    suspnbiz_begin_de DATE,              -- 휴업시작일자
    suspnbiz_end_de DATE,                -- 휴업종료일자
    reopenbiz_de DATE,                   -- 재개업일자
    locplc_faclt_telno VARCHAR(50),      -- 소재지시설전화번호
    bizcond_div_nm_info VARCHAR(100),    -- 업태구분명정보
    x_crdnt_vl NUMERIC(20, 10),          -- X좌표값
    y_crdnt_vl NUMERIC(20, 10),          -- Y좌표값
    sanittn_bizcond_nm VARCHAR(100),     -- 위생업태명
    sigun_nm VARCHAR(50)                 -- 시군명
);

-- 3. 컬럼 코멘트 등록 (메타데이터 관리)
COMMENT ON TABLE locallink.gg_restaurant_info IS '경기도 수원/용인/평택 일반음식점 핵심 정보';

COMMENT ON COLUMN locallink.gg_restaurant_info.bizplc_nm IS '사업장명';
COMMENT ON COLUMN locallink.gg_restaurant_info.refine_roadnm_addr IS '소재지도로명주소';
COMMENT ON COLUMN locallink.gg_restaurant_info.refine_lotno_addr IS '소재지지번주소';
COMMENT ON COLUMN locallink.gg_restaurant_info.refine_wgs84_lat IS '위도';
COMMENT ON COLUMN locallink.gg_restaurant_info.refine_wgs84_logt IS '경도';
COMMENT ON COLUMN locallink.gg_restaurant_info.unity_bsn_state_nm IS '통합영업상태명';
COMMENT ON COLUMN locallink.gg_restaurant_info.bsn_state_nm IS '영업상태명';
COMMENT ON COLUMN locallink.gg_restaurant_info.suspnbiz_begin_de IS '휴업시작일자';
COMMENT ON COLUMN locallink.gg_restaurant_info.suspnbiz_end_de IS '휴업종료일자';
COMMENT ON COLUMN locallink.gg_restaurant_info.reopenbiz_de IS '재개업일자';
COMMENT ON COLUMN locallink.gg_restaurant_info.locplc_faclt_telno IS '소재지시설전화번호';
COMMENT ON COLUMN locallink.gg_restaurant_info.bizcond_div_nm_info IS '업태구분명정보';
COMMENT ON COLUMN locallink.gg_restaurant_info.x_crdnt_vl IS 'X좌표값';
COMMENT ON COLUMN locallink.gg_restaurant_info.y_crdnt_vl IS 'Y좌표값';
COMMENT ON COLUMN locallink.gg_restaurant_info.sanittn_bizcond_nm IS '위생업태명';
COMMENT ON COLUMN locallink.gg_restaurant_info.sigun_nm IS '시군명';

-- 4. 인덱스 설계 (검색 성능 최적화)
CREATE INDEX idx_ll_restaurant_sigun ON locallink.gg_restaurant_info(sigun_nm);
CREATE INDEX idx_ll_restaurant_status ON locallink.gg_restaurant_info(unity_bsn_state_nm);