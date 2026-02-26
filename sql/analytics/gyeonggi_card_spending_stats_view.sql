CREATE OR REPLACE VIEW locallink.vw_gyeonggi_card_spending_stats AS
SELECT
    ta_ymd,
    city,
    card_tpbuz_nm_1,
    card_tpbuz_nm_2,
    CASE hour
        WHEN 1 THEN '00:00~06:59'
        WHEN 2 THEN '07:00~08:59'
        WHEN 3 THEN '09:00~10:59'
        WHEN 4 THEN '11:00~12:59'
        WHEN 5 THEN '13:00~14:59'
        WHEN 6 THEN '15:00~16:59'
        WHEN 7 THEN '17:00~18:59'
        WHEN 8 THEN '19:00~20:59'
        WHEN 9 THEN '21:00~22:59'
        WHEN 10 THEN '23:00~23:59'
        ELSE 'UNKNOWN'
    END AS hour_label,
    CASE sex
        WHEN 'M' THEN '남성'
        WHEN 'F' THEN '여성'
        ELSE '미상'
    END AS sex_label,
    CASE age
        WHEN 1 THEN '0'
        WHEN 2 THEN '10'
        WHEN 3 THEN '20'
        WHEN 4 THEN '30'
        WHEN 5 THEN '40'
        WHEN 6 THEN '50'
        WHEN 7 THEN '60'
        WHEN 8 THEN '70'
        WHEN 9 THEN '80'
        WHEN 10 THEN '90'
        WHEN 11 THEN '100'
        ELSE '미상'
    END AS age_label,
    CASE day
        WHEN 1 THEN '월요일'
        WHEN 2 THEN '화요일'
        WHEN 3 THEN '수요일'
        WHEN 4 THEN '목요일'
        WHEN 5 THEN '금요일'
        WHEN 6 THEN '토요일'
        WHEN 7 THEN '일요일'
        ELSE '미상'
    END AS day_label,
    amt,
    cnt
FROM locallink.gyeonggi_card_spending_stats
ORDER BY ta_ymd;

COMMENT ON VIEW locallink.vw_gyeonggi_card_spending_stats IS '경기도 카드소비 데이터 가독성 뷰(hour/sex/age/day 라벨 포함)';
COMMENT ON COLUMN locallink.vw_gyeonggi_card_spending_stats.ta_ymd IS '기준년월일(date 타입)';
COMMENT ON COLUMN locallink.vw_gyeonggi_card_spending_stats.city IS '시군명';
COMMENT ON COLUMN locallink.vw_gyeonggi_card_spending_stats.card_tpbuz_nm_1 IS '카드사_업종대분류명';
COMMENT ON COLUMN locallink.vw_gyeonggi_card_spending_stats.card_tpbuz_nm_2 IS '카드사_업종중분류명';
COMMENT ON COLUMN locallink.vw_gyeonggi_card_spending_stats.hour_label IS '시간대 라벨(참고: 01~10 코드 구간)';
COMMENT ON COLUMN locallink.vw_gyeonggi_card_spending_stats.sex_label IS '성별 라벨(M/F 코드 해석)';
COMMENT ON COLUMN locallink.vw_gyeonggi_card_spending_stats.age_label IS '연령대(ex:50대)';
COMMENT ON COLUMN locallink.vw_gyeonggi_card_spending_stats.day_label IS '요일 라벨(01~07 코드 해석)';
COMMENT ON COLUMN locallink.vw_gyeonggi_card_spending_stats.amt IS '매출금액';
COMMENT ON COLUMN locallink.vw_gyeonggi_card_spending_stats.cnt IS '매출건수';
