-- 1. 기존 테이블 삭제 (깔끔한 재시작을 위해)
DROP TABLE IF EXISTS tourist_spot_info;

-- 2. 테이블 생성
CREATE TABLE locallink.tourist_spot_info (
    tourist_nm        VARCHAR(255) NOT NULL, -- 관광정보명
    tel_no            VARCHAR(50),           -- 전화번호
    base_date         DATE,                  -- 데이터기준일자
    road_addr         TEXT,                  -- 정제도로명주소
    lot_addr          TEXT,                  -- 정제지번주소
    zip_code          VARCHAR(20),           -- 정제우편번호
    lat               NUMERIC(20, 10),       -- 정제WGS84위도
    lng               NUMERIC(20, 10),       -- 정제WGS84경도
    sigun_nm          VARCHAR(50)            -- 시군명
);

-- 3. 한글 코멘트 등록
COMMENT ON TABLE tourist_spot_info IS '관광지 정보 마스터 테이블';

COMMENT ON COLUMN tourist_spot_info.tourist_nm IS '관광정보명';
COMMENT ON COLUMN tourist_spot_info.tel_no     IS '전화번호';
COMMENT ON COLUMN tourist_spot_info.base_date  IS '데이터기준일자';
COMMENT ON COLUMN tourist_spot_info.road_addr  IS '정제도로명주소';
COMMENT ON COLUMN tourist_spot_info.lot_addr   IS '정제지번주소';
COMMENT ON COLUMN tourist_spot_info.zip_code   IS '정제우편번호';
COMMENT ON COLUMN tourist_spot_info.lat        IS '정제WGS84위도';
COMMENT ON COLUMN tourist_spot_info.lng        IS '정제WGS84경도';
COMMENT ON COLUMN tourist_spot_info.sigun_nm   IS '시군명';


-- 데이터 정제
DELETE FROM locallink.tourist_spot_info
WHERE sigun_nm NOT IN ('수원시', '평택시', '용인시');

DELETE FROM locallink.tourist_spot_info
WHERE tourist_nm='용인농촌테마파크와 연꽃단지  (용인8경 중 제4경)';

-- 중복행 확인
SELECT tourist_nm, COUNT(*)
FROM locallink.tourist_spot_info
GROUP BY tourist_nm
HAVING COUNT(*) > 1;
---- 총 14개 행이 2번씩 중복됨

-- 중복행 삭제 
DELETE FROM locallink.tourist_spot_info a
USING locallink.tourist_spot_info b
WHERE a.tourist_nm = b.tourist_nm;