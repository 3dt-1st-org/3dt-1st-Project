-- locallink 스키마 안에 행사 데이터를 담을 테이블 생성 
CREATE TABLE locallink.event_info (
    CITY VARCHAR(50),
    INST_NM VARCHAR(100),
    TITLE VARCHAR(200),
    BEGIN_DE VARCHAR(50),
    END_DE VARCHAR(50)
);


-- 1. 전체 개수 확인 (897개가 나와야 합니다)
SELECT COUNT(*) FROM locallink.event_info;

-- 2. LLM이 분류한 도시별 데이터 분포 확인
SELECT CITY, COUNT(*) 
FROM locallink.event_info 
GROUP BY CITY 
ORDER BY COUNT(*) DESC;