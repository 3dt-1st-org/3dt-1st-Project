BEGIN;

CREATE SCHEMA IF NOT EXISTS daangn;

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
