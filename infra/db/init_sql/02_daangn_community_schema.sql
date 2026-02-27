-- daangn 커뮤니티 크롤링 스키마 초기화
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS daangn;

CREATE TABLE IF NOT EXISTS daangn.target_dongs (
    id BIGSERIAL PRIMARY KEY,
    city_name TEXT NOT NULL,
    dong_name TEXT NOT NULL,
    dong_slug TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (city_name, dong_name)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_target_dongs_slug
ON daangn.target_dongs (dong_slug)
WHERE dong_slug IS NOT NULL;

CREATE TABLE IF NOT EXISTS daangn.community_posts (
    id BIGSERIAL PRIMARY KEY,
    post_key TEXT NOT NULL UNIQUE,
    source_url TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    city_name TEXT NOT NULL,
    dong_name TEXT NOT NULL,
    searched_keyword TEXT NOT NULL,
    post_created_at TIMESTAMPTZ,
    crawled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_payload JSONB
);

CREATE INDEX IF NOT EXISTS idx_community_posts_city_dong
ON daangn.community_posts (city_name, dong_name);

CREATE INDEX IF NOT EXISTS idx_community_posts_crawled_at
ON daangn.community_posts (crawled_at DESC);

CREATE TABLE IF NOT EXISTS daangn.community_comments (
    id BIGSERIAL PRIMARY KEY,
    comment_key TEXT NOT NULL UNIQUE,
    post_key TEXT NOT NULL REFERENCES daangn.community_posts(post_key) ON DELETE CASCADE,
    comment_body TEXT NOT NULL,
    city_name TEXT NOT NULL,
    dong_name TEXT NOT NULL,
    commented_at TIMESTAMPTZ,
    crawled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_payload JSONB
);

CREATE INDEX IF NOT EXISTS idx_community_comments_post_key
ON daangn.community_comments (post_key);

CREATE TABLE IF NOT EXISTS daangn.crawl_runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    post_count INTEGER NOT NULL DEFAULT 0,
    comment_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);
