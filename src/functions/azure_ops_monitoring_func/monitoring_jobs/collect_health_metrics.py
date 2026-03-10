from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from ._common import (
    configure_logging,
    ensure_env_loaded,
    ensure_schema,
    get_connection,
    get_db_dsn,
    list_metrics,
    list_resources,
    parse_args_base,
    set_subscription,
    utcnow,
)


LOG = logging.getLogger("monitoring.collect_health_metrics")

TARGETS = [
    {
        "service_name": "lala",
        "resource_name": "lala",
        "resource_type": "Microsoft.Web/sites",
        "metrics": ["Requests", "Http5xx", "AverageResponseTime", "HealthCheckStatus"],
    },
    {
        "service_name": "daagn-crawler",
        "resource_name": "daagn-crawler",
        "resource_type": "Microsoft.Web/sites",
        "metrics": ["FunctionExecutionCount", "Http5xx", "AverageResponseTime", "HealthCheckStatus"],
    },
    {
        "service_name": "weather-air-func",
        "resource_name": "weather-air-func",
        "resource_type": "Microsoft.Web/sites",
        "metrics": ["FunctionExecutionCount", "Http5xx", "AverageResponseTime", "HealthCheckStatus"],
    },
    {
        "service_name": "lala-db",
        "resource_name": "lala-db",
        "resource_type": "Microsoft.DBforPostgreSQL/flexibleServers",
        "metrics": ["cpu_percent", "memory_percent", "storage_percent", "active_connections", "is_db_alive"],
    },
]


def _resource_map(subscription: str, resource_group: str) -> dict[tuple[str, str], dict[str, Any]]:
    rows = list_resources(subscription, resource_group)
    if not isinstance(rows, list):
        raise RuntimeError("Unexpected resource list response.")

    mapping: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("name") or ""), str(row.get("type") or ""))
        mapping[key] = row
    return mapping


def _parse_metrics_payload(
    payload: dict[str, Any],
    *,
    service_name: str,
    resource_id: str,
    resource_name: str,
    collected_at_utc,
) -> list[dict[str, Any]]:
    namespace = payload.get("namespace")
    rows: list[dict[str, Any]] = []
    for metric_block in payload.get("value") or []:
        metric_name = ((metric_block.get("name") or {}).get("value") or "").strip()
        unit = metric_block.get("unit")
        for ts_block in metric_block.get("timeseries") or []:
            for point in ts_block.get("data") or []:
                ts = point.get("timeStamp")
                avg = point.get("average")
                total = point.get("total")
                maximum = point.get("maximum")
                if ts is None or all(value is None for value in (avg, total, maximum)):
                    continue
                rows.append(
                    {
                        "collected_at_utc": collected_at_utc,
                        "metric_timestamp_utc": ts,
                        "service_name": service_name,
                        "resource_id": resource_id,
                        "resource_name": resource_name,
                        "metric_name": metric_name,
                        "unit": unit,
                        "average_value": avg,
                        "total_value": total,
                        "maximum_value": maximum,
                        "source_namespace": namespace,
                    }
                )
    return rows


def _fetch_metric_rows(target: dict[str, Any], resource_id: str, start_iso: str, end_iso: str) -> list[dict[str, Any]]:
    payload = list_metrics(
        resource_id,
        target["metrics"],
        start_iso,
        end_iso,
        interval="PT5M",
        aggregations=["Average", "Total", "Maximum"],
    )
    return _parse_metrics_payload(
        payload,
        service_name=target["service_name"],
        resource_id=resource_id,
        resource_name=target["resource_name"],
        collected_at_utc=utcnow(),
    )


def _write_rows(conn, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    sql = """
        INSERT INTO monitoring.health_metrics_5m (
            collected_at_utc,
            metric_timestamp_utc,
            service_name,
            resource_id,
            resource_name,
            metric_name,
            unit,
            average_value,
            total_value,
            maximum_value,
            source_namespace
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (resource_id, metric_name, metric_timestamp_utc) DO UPDATE
        SET
            collected_at_utc = EXCLUDED.collected_at_utc,
            service_name = EXCLUDED.service_name,
            resource_name = EXCLUDED.resource_name,
            unit = EXCLUDED.unit,
            average_value = EXCLUDED.average_value,
            total_value = EXCLUDED.total_value,
            maximum_value = EXCLUDED.maximum_value,
            source_namespace = EXCLUDED.source_namespace
    """
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                sql,
                (
                    row["collected_at_utc"],
                    row["metric_timestamp_utc"],
                    row["service_name"],
                    row["resource_id"],
                    row["resource_name"],
                    row["metric_name"],
                    row["unit"],
                    row["average_value"],
                    row["total_value"],
                    row["maximum_value"],
                    row["source_namespace"],
                ),
            )
    conn.commit()
    return len(rows)


def run(
    *,
    subscription: str,
    resource_group: str,
    db_dsn: str = "",
    init_schema: bool = False,
    dry_run: bool = False,
    window_minutes: int = 65,
    log_level: str = "INFO",
) -> int:
    configure_logging(log_level)
    set_subscription(subscription)

    end = utcnow()
    start = end - timedelta(minutes=max(window_minutes, 5))
    start_iso = start.isoformat()
    end_iso = end.isoformat()

    resources = _resource_map(subscription, resource_group)
    all_rows: list[dict[str, Any]] = []

    for target in TARGETS:
        key = (target["resource_name"], target["resource_type"])
        resource = resources.get(key)
        if not resource:
            LOG.warning("Target resource not found: %s (%s)", *key)
            continue

        resource_id = str(resource.get("id") or "")
        rows = _fetch_metric_rows(target, resource_id, start_iso, end_iso)
        LOG.info(
            "service=%s metrics=%d rows=%d window=%s..%s",
            target["service_name"],
            len(target["metrics"]),
            len(rows),
            start_iso,
            end_iso,
        )
        all_rows.extend(rows)

    if dry_run:
        LOG.info("Dry-run collected rows=%d", len(all_rows))
        return 0

    dsn = get_db_dsn(db_dsn)
    with get_connection(dsn) as conn:
        if init_schema:
            ensure_schema(conn)
        inserted = _write_rows(conn, all_rows)
    LOG.info("Upserted health metric rows=%d", inserted)
    return 0


def main() -> int:
    ensure_env_loaded()
    parser = parse_args_base("Collect Azure Monitor metrics into monitoring.health_metrics_5m.")
    parser.add_argument("--window-minutes", type=int, default=65, help="Lookback window in minutes.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    return run(
        subscription=args.subscription,
        resource_group=args.resource_group,
        db_dsn=args.db_dsn,
        init_schema=args.init_schema,
        dry_run=args.dry_run,
        window_minutes=args.window_minutes,
        log_level=args.log_level,
    )
