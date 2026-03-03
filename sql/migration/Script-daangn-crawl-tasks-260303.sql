BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS daangn;

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

COMMIT;
