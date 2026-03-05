-- 테이블 생성
CREATE TABLE locallink.attraction_descriptions (
    attraction_name  VARCHAR(255) NOT NULL,
    overview         TEXT,
    history          TEXT,
    source_url       TEXT,
    crawled_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    use_time         TEXT,
    closed_days      TEXT,
    parking          TEXT,
    pet_allowed      TEXT
);

-- 컬럼 코멘트
COMMENT ON TABLE  locallink.attraction_descriptions              IS '관광 명소 위키백과 수집 데이터';
COMMENT ON COLUMN locallink.attraction_descriptions.attraction_name IS '명소 이름 (gyeonggi_attractions.attraction_name 참조)';
COMMENT ON COLUMN locallink.attraction_descriptions.overview     IS '명소 개요 (위키백과 요약, 최대 1000자)';
COMMENT ON COLUMN locallink.attraction_descriptions.history      IS '명소 역사/유래 (위키백과 역사 섹션 또는 본문 발췌)';
COMMENT ON COLUMN locallink.attraction_descriptions.source_url   IS '데이터 출처 URL (위키백과 전체 URL)';
COMMENT ON COLUMN locallink.attraction_descriptions.crawled_at   IS '마지막 크롤링 일시 (NULL이면 위키 데이터 없음)';
COMMENT ON COLUMN locallink.attraction_descriptions.created_at   IS '레코드 최초 생성 일시';
COMMENT ON COLUMN locallink.attraction_descriptions.use_time     IS '이용 시간 정보';
COMMENT ON COLUMN locallink.attraction_descriptions.closed_days  IS '휴무일 정보';
COMMENT ON COLUMN locallink.attraction_descriptions.parking      IS '주차 가능 여부 및 주차 정보';
COMMENT ON COLUMN locallink.attraction_descriptions.pet_allowed  IS '반려동물 동반 가능 여부';
