BEGIN;

WITH ranked_posts AS (
    SELECT
        post_key,
        source_url,
        ROW_NUMBER() OVER (
            PARTITION BY source_url
            ORDER BY crawled_at DESC, id DESC
        ) AS rn,
        FIRST_VALUE(post_key) OVER (
            PARTITION BY source_url
            ORDER BY crawled_at DESC, id DESC
        ) AS keep_post_key
    FROM daangn.community_posts
),
duplicate_posts AS (
    SELECT post_key, keep_post_key
    FROM ranked_posts
    WHERE rn > 1
      AND post_key <> keep_post_key
)
UPDATE daangn.community_comments c
SET post_key = d.keep_post_key
FROM duplicate_posts d
WHERE c.post_key = d.post_key;

WITH ranked_posts AS (
    SELECT
        post_key,
        source_url,
        ROW_NUMBER() OVER (
            PARTITION BY source_url
            ORDER BY crawled_at DESC, id DESC
        ) AS rn
    FROM daangn.community_posts
)
DELETE FROM daangn.community_posts p
USING ranked_posts r
WHERE p.post_key = r.post_key
  AND r.rn > 1;

CREATE UNIQUE INDEX IF NOT EXISTS uq_community_posts_source_url
ON daangn.community_posts (source_url);

COMMIT;
