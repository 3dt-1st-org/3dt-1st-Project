-- 중복 적재 방지 스모크 테스트
-- 실행 순서:
-- 1) 아래 INSERT 블록을 두 번 실행
-- 2) 마지막 COUNT 결과가 1/1 인지 확인

INSERT INTO daangn.community_posts (
    post_key, source_url, title, body, city_name, dong_name, searched_keyword
) VALUES (
    'post_key_smoke_1',
    'https://www.daangn.com/kr/community/posts/smoke-1',
    '맛집 추천',
    '망포동 횟집 추천해요',
    '수원시',
    '망포동',
    '맛집'
)
ON CONFLICT (post_key) DO NOTHING;

INSERT INTO daangn.community_comments (
    comment_key, post_key, comment_body, city_name, dong_name
) VALUES (
    'comment_key_smoke_1',
    'post_key_smoke_1',
    '어풍당당 좋아요',
    '수원시',
    '망포동'
)
ON CONFLICT (comment_key) DO NOTHING;

SELECT COUNT(*) AS post_cnt
FROM daangn.community_posts
WHERE post_key = 'post_key_smoke_1';

SELECT COUNT(*) AS comment_cnt
FROM daangn.community_comments
WHERE comment_key = 'comment_key_smoke_1';
