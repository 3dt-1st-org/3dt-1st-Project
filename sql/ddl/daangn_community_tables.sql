BEGIN;

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
    crawled_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_community_posts_city_dong
ON daangn.community_posts (city_name, dong_name);

CREATE INDEX IF NOT EXISTS idx_community_posts_crawled_at
ON daangn.community_posts (crawled_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_community_posts_source_url
ON daangn.community_posts (source_url);

CREATE TABLE IF NOT EXISTS daangn.community_comments (
    id BIGSERIAL PRIMARY KEY,
    comment_key TEXT NOT NULL UNIQUE,
    post_key TEXT NOT NULL REFERENCES daangn.community_posts(post_key) ON DELETE CASCADE,
    comment_body TEXT NOT NULL,
    city_name TEXT NOT NULL,
    dong_name TEXT NOT NULL,
    commented_at TIMESTAMPTZ,
    crawled_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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

CREATE TABLE IF NOT EXISTS daangn.crawl_tasks (
    task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES daangn.crawl_runs(run_id) ON DELETE CASCADE,
    city_name TEXT NOT NULL,
    dong_name TEXT NOT NULL,
    dong_slug TEXT NOT NULL,
    keyword TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'success', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    post_count INTEGER NOT NULL DEFAULT 0,
    comment_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crawl_tasks_run_id
ON daangn.crawl_tasks (run_id);

CREATE INDEX IF NOT EXISTS idx_crawl_tasks_status
ON daangn.crawl_tasks (status);

CREATE TABLE IF NOT EXISTS daangn.place_mentions_weekly (
    id BIGSERIAL PRIMARY KEY,
    place_name TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('맛집', '명소', '행사')),
    city_name TEXT NOT NULL,
    mention_count INTEGER NOT NULL DEFAULT 0,
    week_start DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (place_name, category, city_name, week_start)
);

CREATE INDEX IF NOT EXISTS idx_place_mentions_weekly_city_week
ON daangn.place_mentions_weekly (city_name, week_start DESC);

COMMIT;
