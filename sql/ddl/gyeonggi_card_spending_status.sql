CREATE TABLE IF NOT EXISTS locallink.gyeonggi_card_spending_stats (
    ta_ymd         CHAR(8),
    city           VARCHAR(50),
    card_tpbuz_nm_1 VARCHAR(100),
    card_tpbuz_nm_2 VARCHAR(100),
    hour           SMALLINT,
    sex            VARCHAR(10),
    age            SMALLINT,
    day            SMALLINT,
    amt            NUMERIC,
    cnt            BIGINT
);

COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.ta_ymd IS '기준년월일(참고: 카드 매출이 발생한 시간적 범위)';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.city IS '시군명(파일명에서 추출한 값)';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.card_tpbuz_nm_1 IS '카드사_업종대분류명(참고: 카드사 업종 분류 기준(대분류))';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.card_tpbuz_nm_2 IS '카드사_업종중분류명(참고: 카드사 업종 분류 기준(중분류))';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.hour IS '시간대(01:00:00~06:59, 02:07:00~08:59, 03:09:00~10:59, 04:11:00~12:59, 05:13:00~14:59, 06:15:00~16:59, 07:17:00~18:59, 08:19:00~20:59, 09:21:00~22:59, 10:23:00~23:59)';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.sex IS '성별(M:남성, F:여성)';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.age IS '연령별(01:0-9세, 02:10-19세, 03:20-29세, 04:30-39세, 05:40-49세, 06:50-59세, 07:60-69세, 08:70-79세, 09:80-89세, 10:90-99세, 11:100세 이상)';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.day IS '요일(01:월요일, 02:화요일, 03:수요일, 04:목요일, 05:금요일, 06:토요일, 07:일요일, 참고: 카드 매출 발생 요일 기준)';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.amt IS '매출금액(참고: 카드 매출 발생 요일 기준 매출금액의 합)';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.cnt IS '매출건수(참고: 카드 매출 발생 요일 기준 매출건수의 합)';
