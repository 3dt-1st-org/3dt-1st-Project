BEGIN;

ALTER TABLE IF EXISTS daangn.community_posts
DROP COLUMN IF EXISTS raw_payload;

ALTER TABLE IF EXISTS daangn.community_comments
DROP COLUMN IF EXISTS raw_payload;

COMMIT;
