-- 1. 카드 데이터 요약 뷰 (시군구 + 업종별 합계)
CREATE MATERIALIZED VIEW locallink.v_card_stats_summary ASSELECT city, card_tpbuz_nm_2 as category, SUM(amt) as total_amtFROM locallink.gyeonggi_card_spending_statsGROUP BY city, card_tpbuz_nm_2;
-- 2. 당근 데이터 요약 뷰 (식당별 전체 언급량 합계)
CREATE MATERIALIZED VIEW daangn.v_daangn_stats_summary ASSELECT place_name, city_name, SUM(mention_count) as total_mentionFROM daangn.place_mentions_weeklyGROUP BY place_name, city_name;
-- 3. 검색 성능 향상을 위한 인덱스 추가
CREATE INDEX idx_v_card_city_cat ON locallink.v_card_stats_summary(city, category);CREATE INDEX idx_v_daangn_name_city ON daangn.v_daangn_stats_summary(place_name, city_name);

