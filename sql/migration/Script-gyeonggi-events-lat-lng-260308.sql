-- Migration: gyeonggi_events 테이블에 TourAPI 좌표 및 content_id 컬럼 추가
-- 작성일: 2026-03-08
-- 목적 : TourAPI 4.0 searchFestival2 수집 데이터 저장용 컬럼 추가
--        lat / lng  - 행사 장소 좌표 (WGS84)
--        content_id - 한국관광공사 콘텐츠 ID (향후 upsert 키로 사용 가능)
-- 선행 조건: locallink.gyeonggi_events 테이블이 존재해야 합니다.

ALTER TABLE locallink.gyeonggi_events
    ADD COLUMN IF NOT EXISTS lat        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS lng        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS content_id TEXT;

-- content_id 에 UNIQUE 인덱스 (NOT NULL 행만 대상)
CREATE UNIQUE INDEX IF NOT EXISTS idx_gyeonggi_events_content_id
    ON locallink.gyeonggi_events (content_id)
    WHERE content_id IS NOT NULL;

COMMENT ON COLUMN locallink.gyeonggi_events.lat IS
    'WGS84 위도 (TourAPI mapy). 경기도 행사 수집 스크립트가 채웁니다.';
COMMENT ON COLUMN locallink.gyeonggi_events.lng IS
    'WGS84 경도 (TourAPI mapx). 경기도 행사 수집 스크립트가 채웁니다.';
COMMENT ON COLUMN locallink.gyeonggi_events.content_id IS
    '한국관광공사 TourAPI contentid. visitkorea.or.kr 상세 URL 생성에 활용.';
