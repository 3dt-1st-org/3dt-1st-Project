-- Power BI Azure Ops dashboard datamart (v1)
-- Scope: lala, daagn-crawler, weather-air-func, lala-db

CREATE SCHEMA IF NOT EXISTS monitoring;

CREATE TABLE IF NOT EXISTS monitoring.resource_inventory_snapshot (
    collected_at_utc      TIMESTAMPTZ NOT NULL,
    resource_id           TEXT NOT NULL,
    resource_name         TEXT NOT NULL,
    resource_type         TEXT NOT NULL,
    resource_kind         TEXT,
    resource_location     TEXT,
    service_name          TEXT,
    in_scope              BOOLEAN NOT NULL DEFAULT FALSE,
    tags_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at_utc        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_resource_inventory_snapshot
        PRIMARY KEY (collected_at_utc, resource_id)
);

CREATE INDEX IF NOT EXISTS idx_resource_inventory_latest
    ON monitoring.resource_inventory_snapshot (resource_name, collected_at_utc DESC);

CREATE TABLE IF NOT EXISTS monitoring.health_metrics_5m (
    collected_at_utc      TIMESTAMPTZ NOT NULL,
    metric_timestamp_utc  TIMESTAMPTZ NOT NULL,
    service_name          TEXT NOT NULL,
    resource_id           TEXT NOT NULL,
    resource_name         TEXT NOT NULL,
    metric_name           TEXT NOT NULL,
    unit                  TEXT,
    average_value         DOUBLE PRECISION,
    total_value           DOUBLE PRECISION,
    maximum_value         DOUBLE PRECISION,
    source_namespace      TEXT,
    created_at_utc        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_health_metrics_5m
        UNIQUE (resource_id, metric_name, metric_timestamp_utc)
);

CREATE INDEX IF NOT EXISTS idx_health_metrics_service_time
    ON monitoring.health_metrics_5m (service_name, metric_timestamp_utc DESC);

CREATE TABLE IF NOT EXISTS monitoring.telemetry_kpi_5m (
    collected_at_utc      TIMESTAMPTZ NOT NULL,
    bucket_utc            TIMESTAMPTZ NOT NULL,
    service_name          TEXT NOT NULL,
    request_count         INTEGER NOT NULL DEFAULT 0,
    failed_count          INTEGER NOT NULL DEFAULT 0,
    p95_duration_ms       DOUBLE PRECISION,
    trace_count           INTEGER NOT NULL DEFAULT 0,
    exception_count       INTEGER NOT NULL DEFAULT 0,
    created_at_utc        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_telemetry_kpi_5m
        UNIQUE (service_name, bucket_utc)
);

CREATE INDEX IF NOT EXISTS idx_telemetry_kpi_service_time
    ON monitoring.telemetry_kpi_5m (service_name, bucket_utc DESC);

CREATE TABLE IF NOT EXISTS monitoring.telemetry_kpi_stream_1m (
    collected_at_utc      TIMESTAMPTZ NOT NULL,
    window_end_utc        TIMESTAMPTZ NOT NULL,
    service_name          TEXT NOT NULL,
    category              TEXT NOT NULL,
    event_count           INTEGER NOT NULL DEFAULT 0,
    http5xx_count         INTEGER NOT NULL DEFAULT 0,
    error_count           INTEGER NOT NULL DEFAULT 0,
    success_count         INTEGER NOT NULL DEFAULT 0,
    created_at_utc        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_telemetry_kpi_stream_1m
        UNIQUE (window_end_utc, service_name, category)
);

CREATE INDEX IF NOT EXISTS idx_telemetry_kpi_stream_1m_service_time
    ON monitoring.telemetry_kpi_stream_1m (service_name, window_end_utc DESC);

CREATE TABLE IF NOT EXISTS monitoring.cost_daily (
    collected_at_utc      TIMESTAMPTZ NOT NULL,
    usage_date            DATE NOT NULL,
    service_name          TEXT NOT NULL,
    resource_type         TEXT NOT NULL,
    currency              TEXT NOT NULL,
    cost_amount           NUMERIC(18, 6) NOT NULL,
    scope_resource_group  TEXT NOT NULL,
    created_at_utc        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cost_daily
        UNIQUE (usage_date, service_name, resource_type, currency, scope_resource_group)
);

CREATE INDEX IF NOT EXISTS idx_cost_daily_usage_date
    ON monitoring.cost_daily (usage_date DESC, service_name);
