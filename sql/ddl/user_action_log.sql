-- ============================================================
-- user_action_log : 유저 행동 로그 테이블
-- 목적: 버튼 클릭·화면 조회 이벤트를 기록하여
--       DAU, 시간대별/시군별 사용량, 기능별 활용 빈도를
--       Power BI 등 BI 도구로 분석하기 위한 원본 데이터 적재
-- ============================================================

CREATE TABLE IF NOT EXISTS locallink.user_action_log (
    log_id      BIGSERIAL        PRIMARY KEY,                          -- 행 고유 번호
    session_id  VARCHAR(64)      NOT NULL,                             -- 브라우저 세션 UUID (DAU 집계용)
    action_type VARCHAR(64)      NOT NULL,                             -- 이벤트 종류 (예: click_place_card)
    latitude    DOUBLE PRECISION,                                      -- 유저 GPS 위도 (Power BI 지도용)
    longitude   DOUBLE PRECISION,                                      -- 유저 GPS 경도
    sigun_nm    VARCHAR(100),                                          -- 시/군명 (예: 수원시, 용인시)
    place_id    INTEGER,                                               -- 관련 장소 ID (없으면 NULL)
    place_name  VARCHAR(255),                                          -- 관련 장소명 (없으면 NULL)
    created_at  TIMESTAMPTZ      NOT NULL DEFAULT NOW()                -- 이벤트 발생 시각 (UTC)
);

-- BI 쿼리 가속용 인덱스
CREATE INDEX IF NOT EXISTS idx_user_action_log_created_at
    ON locallink.user_action_log (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_action_log_action_type
    ON locallink.user_action_log (action_type);

CREATE INDEX IF NOT EXISTS idx_user_action_log_session_id
    ON locallink.user_action_log (session_id);

CREATE INDEX IF NOT EXISTS idx_user_action_log_sigun_nm
    ON locallink.user_action_log (sigun_nm);

-- 컬럼 코멘트
COMMENT ON TABLE  locallink.user_action_log             IS '유저 행동 로그 원본 테이블';
COMMENT ON COLUMN locallink.user_action_log.log_id      IS '행 고유 번호 (자동 증가)';
COMMENT ON COLUMN locallink.user_action_log.session_id  IS '브라우저 세션 UUID — DAU 집계에 사용';
COMMENT ON COLUMN locallink.user_action_log.action_type IS '이벤트 종류 (click_place_card / click_tour_guide / click_daily_plan / click_docent_detail / click_category_filter / click_weather)';
COMMENT ON COLUMN locallink.user_action_log.latitude    IS '이벤트 발생 시점 유저 GPS 위도 (Power BI 지도 시각화용)';
COMMENT ON COLUMN locallink.user_action_log.longitude   IS '이벤트 발생 시점 유저 GPS 경도';
COMMENT ON COLUMN locallink.user_action_log.sigun_nm    IS '유저 위치 기준 시/군명 (예: 수원시) — 지역별 비율 분석용';
COMMENT ON COLUMN locallink.user_action_log.place_id    IS '클릭한 장소의 ID (장소 무관 이벤트는 NULL)';
COMMENT ON COLUMN locallink.user_action_log.place_name  IS '클릭한 장소명 (장소 무관 이벤트는 NULL)';
COMMENT ON COLUMN locallink.user_action_log.created_at  IS '이벤트 발생 UTC 시각 — 시간대/요일별 분석용';
