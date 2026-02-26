-- 트랜잭션 시작 (안전하게 처리)
BEGIN;

-- 1. 경기도박물관 (입장료 무료 / 주차 유료)
UPDATE locallink.gyeonggi_attractions 
SET additional_info = '무료 / 유료' 
WHERE attraction_name = '경기도박물관';

-- 2. 농촌테마파크 (입장료 무료 / 주차 유료)
UPDATE locallink.gyeonggi_attractions 
SET additional_info = '무료 / 유료' 
WHERE attraction_name = '농촌테마파크';

-- 3. 에버랜드 (입장료 유료 / 주차 무료,유료 혼합)
UPDATE locallink.gyeonggi_attractions 
SET additional_info = '유료 / 무료, 유료 혼합' 
WHERE attraction_name = '에버랜드';

-- 4. 한국민속촌 (둘 다 유료)
UPDATE locallink.gyeonggi_attractions 
SET additional_info = '유료 / 유료' 
WHERE attraction_name = '한국민속촌';

-- 5. 양지파인리조트 (입장료 유료 / 주차 무료)
UPDATE locallink.gyeonggi_attractions 
SET additional_info = '유료 / 무료' 
WHERE attraction_name = '양지파인리조트';

-- 6. 대장금파크 (입장료 유료 / 주차 무료)
UPDATE locallink.gyeonggi_attractions 
SET additional_info = '유료 / 무료' 
WHERE attraction_name = '대장금파크';

-- 7. 평택호관광단지 (둘 다 무료)
UPDATE locallink.gyeonggi_attractions 
SET additional_info = '무료 / 무료' 
WHERE attraction_name = '평택호관광단지';

-- 8. 수원화성 (둘 다 유료)
UPDATE locallink.gyeonggi_attractions 
SET additional_info = '유료 / 유료' 
WHERE attraction_name = '수원화성';

-- 9. 경기도어린이박물관 (둘 다 유료)
UPDATE locallink.gyeonggi_attractions 
SET additional_info = '유료 / 유료' 
WHERE attraction_name = '경기도어린이박물관';

-- 10. 백남준 아트센터 (입장료 무료 / 주차 유료)
UPDATE locallink.gyeonggi_attractions 
SET additional_info = '무료 / 유료' 
WHERE attraction_name = '백남준 아트센터';

-- 11. 와우정사 (둘 다 무료)
UPDATE locallink.gyeonggi_attractions 
SET additional_info = '무료 / 무료' 
WHERE attraction_name = '와우정사';

-- 12. 바람새마을 (둘 다 무료)
UPDATE locallink.gyeonggi_attractions 
SET additional_info = '무료 / 무료' 
WHERE attraction_name = '바람새마을';

-- 변경사항 저장
COMMIT;