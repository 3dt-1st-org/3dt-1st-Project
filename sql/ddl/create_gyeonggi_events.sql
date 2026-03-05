-- [Issue #58] 경기문화재단 행사 데이터 최종 테이블 생성 DDL by. 강신석(2026-03-04)

-- 1. 기존 테이블 초기화
DROP TABLE IF EXISTS locallink.gyeonggi_events;

-- 2. 최종 테이블 구조 생성
CREATE TABLE locallink.gyeonggi_events (
    inst_nm text,
    title text,
    begin_de text,
    end_de text,
    url text,
    image_url text,
    writng_de text,
    city text
);

-- 3. 데이터 적재 후 검증용 쿼리 (실행 결과 확인용)
-- SELECT COUNT(*) FROM locallink.gyeonggi_events;
-- SELECT city, COUNT(*) FROM locallink.gyeonggi_events GROUP BY city ORDER BY 2 DESC;