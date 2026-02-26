CREATE TABLE locallink.gyeonggi_card_spending_stats (
    ta_ymd         CHAR(8),
    city           VARCHAR(50),
    cty_rgn_no     VARCHAR(20),
    admi_cty_no    VARCHAR(20),
    card_tpbuz_cd  VARCHAR(20),
    card_tpbuz_nm_1 VARCHAR(100),
    card_tpbuz_nm_2 VARCHAR(100),
    hour           SMALLINT,
    sex            VARCHAR(10),
    age            SMALLINT,
    day            SMALLINT,
    amt            NUMERIC,
    cnt            BIGINT
);

COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.ta_ymd IS '기준일자(YYYYMMDD)';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.city IS '시명(예: 수원시)';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.cty_rgn_no IS '시군지역번호';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.admi_cty_no IS '행정시군번호';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.card_tpbuz_cd IS '카드업종코드';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.card_tpbuz_nm_1 IS '카드업종명(대분류)';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.card_tpbuz_nm_2 IS '카드업종명(중분류/세분류)';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.hour IS '시간(0~23)';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.sex IS '성별';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.age IS '연령';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.day IS '요일(데이터 기준 코드)';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.amt IS '이용금액';
COMMENT ON COLUMN locallink.gyeonggi_card_spending_stats.cnt IS '이용건수';
