-- 목적: 크롤링 대상 동(수원시/용인시/평택시) 등록
-- 참고: dong_slug는 당근 URL의 in 파라미터 값(예: 망포동-4534)
--       슬러그 미입력(NULL) 행은 함수 실행 시 자동 스킵됩니다.

INSERT INTO daangn.target_dongs (city_name, dong_name, dong_slug, is_active)
VALUES
    ('수원시', '망포동', '망포동-4534', TRUE),
    ('수원시', '영통2동', NULL, TRUE),
    ('용인시', '죽전1동', NULL, TRUE),
    ('용인시', '상현동', NULL, TRUE),
    ('평택시', '비전1동', NULL, TRUE),
    ('평택시', '고덕동', NULL, TRUE)
ON CONFLICT (city_name, dong_name)
DO UPDATE SET
    dong_slug = EXCLUDED.dong_slug,
    is_active = EXCLUDED.is_active,
    updated_at = NOW();
