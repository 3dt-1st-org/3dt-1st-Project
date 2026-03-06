BEGIN;

CREATE SCHEMA IF NOT EXISTS locallink;

CREATE TABLE IF NOT EXISTS locallink.docent_script_cache (
    id BIGSERIAL PRIMARY KEY,
    place_id TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('attraction', 'restaurant', 'event')),
    language TEXT NOT NULL CHECK (language IN ('ko', 'en')),
    mode TEXT NOT NULL CHECK (mode IN ('brief', 'detail')),
    script TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('llm', 'fallback', 'cache')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    UNIQUE (place_id, category, language, mode)
);

CREATE INDEX IF NOT EXISTS idx_docent_script_cache_expires_at
ON locallink.docent_script_cache (expires_at);

COMMIT;
