-- 기존 뷰 삭제
DROP VIEW IF EXISTS locallink.v_filtered_attractions;

-- 뷰 새로 생성
CREATE VIEW locallink.v_filtered_attractions AS
SELECT 
    attraction_name,
    phone_number,
    
    -- [1] 입장료 컬럼 (슬래시 앞부분 가져오기)
    CASE 
        WHEN additional_info LIKE '%/%' THEN TRIM(SPLIT_PART(additional_info, '/', 1))
        WHEN additional_info IS NULL OR additional_info = '' THEN '정보 없음'
        ELSE additional_info -- 슬래시가 없으면 통째로 보여줌
    END AS entrance_fee,
    
    -- [2] 주차료 컬럼 (슬래시 뒷부분 가져오기)
    CASE 
        WHEN additional_info LIKE '%/%' THEN TRIM(SPLIT_PART(additional_info, '/', 2))
        WHEN additional_info IS NULL OR additional_info = '' THEN '정보 없음'
        ELSE '확인 필요' -- 슬래시가 없으면 주차 정보는 불확실함
    END AS parking_fee,
    
    road_address,
    lot_address,
    latitude,
    longitude,
    city_county_name
    
FROM locallink.gyeonggi_attractions
WHERE city_county_name IN ('수원시', '용인시', '평택시');