-- Power BI semantic views for monitoring schema

CREATE SCHEMA IF NOT EXISTS monitoring;

DROP VIEW IF EXISTS monitoring.vw_overview_latest;
DROP VIEW IF EXISTS monitoring.vw_realtime_kpi_1m;
DROP VIEW IF EXISTS monitoring.vw_incidents_5m;
DROP VIEW IF EXISTS monitoring.vw_cost_burn_daily;
DROP VIEW IF EXISTS monitoring.vw_service_health_5m;

CREATE OR REPLACE VIEW monitoring.vw_service_health_5m AS
SELECT
    hm.metric_timestamp_utc,
    hm.service_name,
    MAX(CASE WHEN hm.metric_name IN ('Requests', 'FunctionExecutionCount') THEN hm.total_value END) AS request_or_execution_total,
    MAX(CASE WHEN hm.metric_name = 'Http5xx' THEN hm.total_value END) AS http5xx_total,
    MAX(CASE WHEN hm.metric_name = 'AverageResponseTime' THEN hm.average_value END) AS average_response_sec,
    MAX(CASE WHEN hm.metric_name = 'HealthCheckStatus' THEN hm.average_value END) AS health_check_status,
    MAX(CASE WHEN hm.metric_name = 'is_db_alive' THEN hm.average_value END) AS is_db_alive,
    MAX(CASE WHEN hm.metric_name = 'cpu_percent' THEN hm.average_value END) AS cpu_percent,
    MAX(CASE WHEN hm.metric_name = 'memory_percent' THEN hm.average_value END) AS memory_percent,
    MAX(CASE WHEN hm.metric_name = 'storage_percent' THEN hm.average_value END) AS storage_percent,
    MAX(CASE WHEN hm.metric_name = 'active_connections' THEN hm.average_value END) AS active_connections
FROM monitoring.health_metrics_5m hm
GROUP BY hm.metric_timestamp_utc, hm.service_name;

CREATE OR REPLACE VIEW monitoring.vw_realtime_kpi_1m AS
SELECT
    ks.window_end_utc,
    ks.collected_at_utc,
    ks.service_name,
    ks.category,
    ks.event_count,
    ks.http5xx_count,
    ks.error_count,
    ks.success_count,
    CASE
        WHEN ks.event_count > 0 THEN ROUND((ks.error_count::NUMERIC * 100.0) / ks.event_count::NUMERIC, 2)
        ELSE 0::NUMERIC
    END AS error_rate_pct,
    CASE
        WHEN ks.event_count > 0 THEN ROUND((ks.http5xx_count::NUMERIC * 100.0) / ks.event_count::NUMERIC, 2)
        ELSE 0::NUMERIC
    END AS http5xx_rate_pct
FROM monitoring.telemetry_kpi_stream_1m ks
WHERE LOWER(COALESCE(NULLIF(BTRIM(ks.service_name), ''), 'unknown')) <> 'unknown';

CREATE OR REPLACE VIEW monitoring.vw_overview_latest AS
WITH last_health AS (
    SELECT MAX(metric_timestamp_utc) AS as_of_utc
    FROM monitoring.health_metrics_5m
),
health_latest AS (
    SELECT sh.*
    FROM monitoring.vw_service_health_5m sh
    JOIN last_health lh ON lh.as_of_utc = sh.metric_timestamp_utc
),
last_kpi AS (
    SELECT MAX(bucket_utc) AS bucket_utc
    FROM monitoring.telemetry_kpi_5m
),
kpi_latest AS (
    SELECT tk.*
    FROM monitoring.telemetry_kpi_5m tk
    JOIN last_kpi lk ON lk.bucket_utc = tk.bucket_utc
),
last_stream AS (
    SELECT MAX(window_end_utc) AS window_end_utc
    FROM monitoring.vw_realtime_kpi_1m
),
stream_latest AS (
    SELECT ks.*
    FROM monitoring.vw_realtime_kpi_1m ks
    JOIN last_stream ls ON ls.window_end_utc = ks.window_end_utc
),
cost_latest AS (
    SELECT MAX(collected_at_utc) AS collected_at_utc
    FROM monitoring.cost_daily
),
cost_today AS (
    SELECT COALESCE(SUM(cd.cost_amount), 0::numeric) AS today_cost_krw
    FROM monitoring.cost_daily cd
    JOIN cost_latest cl ON cl.collected_at_utc = cd.collected_at_utc
    WHERE cd.currency = 'KRW'
      AND cd.usage_date = (NOW() AT TIME ZONE 'UTC')::date
),
cost_mtd AS (
    SELECT COALESCE(SUM(cd.cost_amount), 0::numeric) AS mtd_cost_krw
    FROM monitoring.cost_daily cd
    JOIN cost_latest cl ON cl.collected_at_utc = cd.collected_at_utc
    WHERE cd.currency = 'KRW'
      AND date_trunc('month', cd.usage_date::timestamp) = date_trunc('month', (NOW() AT TIME ZONE 'UTC'))
),
service_status AS (
    SELECT
        hl.service_name,
        CASE
            WHEN hl.service_name = 'lala-db' THEN
                CASE WHEN COALESCE(hl.is_db_alive, 0) >= 1 THEN 'healthy' ELSE 'degraded' END
            ELSE
                CASE WHEN COALESCE(hl.health_check_status, 0) >= 99 THEN 'healthy' ELSE 'degraded' END
        END AS service_health
    FROM health_latest hl
),
service_status_summary AS (
    SELECT
        COUNT(*) FILTER (WHERE ss.service_health = 'healthy') AS healthy_service_count,
        COUNT(*) AS total_service_count
    FROM service_status ss
),
kpi_summary AS (
    SELECT
        COALESCE(SUM(kl.failed_count), 0) AS failed_requests_5m,
        COALESCE(SUM(kl.exception_count), 0) AS exceptions_5m,
        MAX(kl.p95_duration_ms) AS max_p95_duration_ms
    FROM kpi_latest kl
),
stream_summary AS (
    SELECT
        COALESCE(SUM(sl.event_count), 0) AS stream_event_count_1m,
        COALESCE(SUM(sl.http5xx_count), 0) AS stream_http5xx_count_1m,
        COALESCE(SUM(sl.error_count), 0) AS stream_error_count_1m
    FROM stream_latest sl
)
SELECT
    lh.as_of_utc,
    lk.bucket_utc AS kpi_bucket_utc,
    ls.window_end_utc AS stream_window_end_utc,
    ct.today_cost_krw,
    cm.mtd_cost_krw,
    COALESCE(sss.healthy_service_count, 0) AS healthy_service_count,
    COALESCE(sss.total_service_count, 0) AS total_service_count,
    COALESCE(ks.failed_requests_5m, 0) AS failed_requests_5m,
    COALESCE(ks.exceptions_5m, 0) AS exceptions_5m,
    ks.max_p95_duration_ms,
    COALESCE(sts.stream_event_count_1m, 0) AS stream_event_count_1m,
    COALESCE(sts.stream_http5xx_count_1m, 0) AS stream_http5xx_count_1m,
    COALESCE(sts.stream_error_count_1m, 0) AS stream_error_count_1m,
    CASE
        WHEN ls.window_end_utc IS NOT NULL THEN GREATEST(EXTRACT(EPOCH FROM (NOW() - ls.window_end_utc)), 0)::BIGINT
        ELSE NULL::BIGINT
    END AS stream_delay_seconds
FROM last_health lh
LEFT JOIN last_kpi lk ON TRUE
LEFT JOIN last_stream ls ON TRUE
LEFT JOIN cost_today ct ON TRUE
LEFT JOIN cost_mtd cm ON TRUE
LEFT JOIN service_status_summary sss ON TRUE
LEFT JOIN kpi_summary ks ON TRUE
LEFT JOIN stream_summary sts ON TRUE;

CREATE OR REPLACE VIEW monitoring.vw_cost_burn_daily AS
WITH latest_snapshot AS (
    SELECT MAX(collected_at_utc) AS collected_at_utc
    FROM monitoring.cost_daily
)
SELECT
    cd.usage_date,
    cd.service_name,
    cd.resource_type,
    cd.currency,
    cd.cost_amount,
    cd.scope_resource_group,
    cd.collected_at_utc,
    SUM(cd.cost_amount) OVER (
        PARTITION BY cd.service_name, date_trunc('month', cd.usage_date::timestamp)
        ORDER BY cd.usage_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS service_mtd_cumulative_cost
FROM monitoring.cost_daily cd
JOIN latest_snapshot ls ON ls.collected_at_utc = cd.collected_at_utc;

CREATE OR REPLACE VIEW monitoring.vw_incidents_5m AS
WITH telemetry_incidents AS (
    SELECT
        tk.bucket_utc AS incident_time_utc,
        tk.service_name,
        CASE
            WHEN tk.exception_count > 0 THEN 'error'
            WHEN tk.failed_count > 0 THEN 'warning'
            ELSE 'info'
        END AS severity,
        'telemetry'::text AS incident_type,
        tk.failed_count,
        tk.exception_count,
        tk.p95_duration_ms,
        format(
            'failed=%s exceptions=%s p95_ms=%s',
            tk.failed_count,
            tk.exception_count,
            COALESCE(tk.p95_duration_ms::text, 'null')
        ) AS message
    FROM monitoring.telemetry_kpi_5m tk
    WHERE tk.failed_count > 0 OR tk.exception_count > 0
),
health_incidents AS (
    SELECT
        sh.metric_timestamp_utc AS incident_time_utc,
        sh.service_name,
        CASE
            WHEN sh.service_name = 'lala-db' AND COALESCE(sh.is_db_alive, 0) < 1 THEN 'error'
            WHEN sh.service_name <> 'lala-db' AND COALESCE(sh.health_check_status, 0) < 99 THEN 'warning'
            ELSE 'info'
        END AS severity,
        'health'::text AS incident_type,
        0::integer AS failed_count,
        0::integer AS exception_count,
        NULL::double precision AS p95_duration_ms,
        CASE
            WHEN sh.service_name = 'lala-db' THEN format('is_db_alive=%s', COALESCE(sh.is_db_alive::text, 'null'))
            ELSE format('health_check_status=%s', COALESCE(sh.health_check_status::text, 'null'))
        END AS message
    FROM monitoring.vw_service_health_5m sh
    WHERE (sh.service_name = 'lala-db' AND COALESCE(sh.is_db_alive, 0) < 1)
       OR (sh.service_name <> 'lala-db' AND COALESCE(sh.health_check_status, 100) < 99)
)
SELECT *
FROM telemetry_incidents
UNION ALL
SELECT *
FROM health_incidents;
