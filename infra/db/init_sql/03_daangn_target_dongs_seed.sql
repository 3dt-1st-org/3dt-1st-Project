-- 샘플 대상 동. 실제 운영 전 dong_slug를 모두 채워주세요.
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
