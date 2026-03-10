from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from ._common import (
    configure_logging,
    ensure_env_loaded,
    ensure_schema,
    get_connection,
    get_db_dsn,
    parse_args_base,
    query_log_analytics,
    set_subscription,
    utcnow,
)


LOG = logging.getLogger("monitoring.collect_log_kpi")


def _parse_bucket(ts: str) -> datetime:
    value = ts.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_table_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]

    tables = payload.get("tables") or []
    if not tables:
        return []

    table = tables[0]
    columns = [str(col.get("name") or "") for col in table.get("columns") or []]
    rows: list[dict[str, Any]] = []
    for values in table.get("rows") or []:
        row = {columns[idx]: values[idx] for idx in range(min(len(columns), len(values)))}
        rows.append(row)
    return rows


def _query_requests(workspace_id: str, lookback_minutes: int) -> list[dict[str, Any]]:
    kql = (
        f"AppRequests | where TimeGenerated >= ago({lookback_minutes}m) "
        "| summarize request_count=count(), failed_count=countif(Success==false), "
        "p95_duration_ms=percentile(DurationMs,95) "
        "by service_name=tostring(AppRoleName), bucket=bin(TimeGenerated, 5m)"
    )
    payload = query_log_analytics(workspace_id, kql)
    return _extract_table_rows(payload)


def _query_count_table(workspace_id: str, lookback_minutes: int, table: str, field_name: str) -> list[dict[str, Any]]:
    kql = (
        f"{table} | where TimeGenerated >= ago({lookback_minutes}m) "
        f"| summarize {field_name}=count() by service_name=tostring(AppRoleName), bucket=bin(TimeGenerated, 5m)"
    )
    try:
        payload = query_log_analytics(workspace_id, kql)
    except RuntimeError as exc:
        LOG.warning("Skipping table=%s due to query error: %s", table, exc)
        return []
    return _extract_table_rows(payload)


def _merge_kpi_rows(
    request_rows: list[dict[str, Any]],
    trace_rows: list[dict[str, Any]],
    exception_rows: list[dict[str, Any]],
    *,
    collected_at_utc,
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "request_count": 0,
            "failed_count": 0,
            "p95_duration_ms": None,
            "trace_count": 0,
            "exception_count": 0,
        }
    )

    for row in request_rows:
        service = str(row.get("service_name") or "").strip()
        bucket = str(row.get("bucket") or "").strip()
        if not service or not bucket:
            continue
        key = (service, bucket)
        merged[key]["request_count"] = int(row.get("request_count") or 0)
        merged[key]["failed_count"] = int(row.get("failed_count") or 0)
        merged[key]["p95_duration_ms"] = row.get("p95_duration_ms")

    for row in trace_rows:
        service = str(row.get("service_name") or "").strip()
        bucket = str(row.get("bucket") or "").strip()
        if not service or not bucket:
            continue
        key = (service, bucket)
        merged[key]["trace_count"] = int(row.get("trace_count") or 0)

    for row in exception_rows:
        service = str(row.get("service_name") or "").strip()
        bucket = str(row.get("bucket") or "").strip()
        if not service or not bucket:
            continue
        key = (service, bucket)
        merged[key]["exception_count"] = int(row.get("exception_count") or 0)

    output: list[dict[str, Any]] = []
    for (service, bucket), values in merged.items():
        output.append(
            {
                "collected_at_utc": collected_at_utc,
                "bucket_utc": bucket,
                "service_name": service,
                "request_count": values["request_count"],
                "failed_count": values["failed_count"],
                "p95_duration_ms": values["p95_duration_ms"],
                "trace_count": values["trace_count"],
                "exception_count": values["exception_count"],
            }
        )
    return output


def _write_rows(conn, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    sql = """
        INSERT INTO monitoring.telemetry_kpi_5m (
            collected_at_utc,
            bucket_utc,
            service_name,
            request_count,
            failed_count,
            p95_duration_ms,
            trace_count,
            exception_count
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (service_name, bucket_utc) DO UPDATE
        SET
            collected_at_utc = EXCLUDED.collected_at_utc,
            request_count = EXCLUDED.request_count,
            failed_count = EXCLUDED.failed_count,
            p95_duration_ms = EXCLUDED.p95_duration_ms,
            trace_count = EXCLUDED.trace_count,
            exception_count = EXCLUDED.exception_count
    """
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                sql,
                (
                    row["collected_at_utc"],
                    row["bucket_utc"],
                    row["service_name"],
                    row["request_count"],
                    row["failed_count"],
                    row["p95_duration_ms"],
                    row["trace_count"],
                    row["exception_count"],
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
    workspace_id: str = "",
    lookback_minutes: int = 120,
    log_level: str = "INFO",
) -> int:
    configure_logging(log_level)
    set_subscription(subscription)

    effective_workspace = workspace_id or os.getenv(
        "LOG_ANALYTICS_WORKSPACE_ID",
        "3a6ae1f6-a887-4b1f-ad70-56f270c974ca",
    )
    effective_lookback = max(lookback_minutes, 10)
    collected_at = utcnow()

    req_rows = _query_requests(effective_workspace, effective_lookback)
    trace_rows = _query_count_table(effective_workspace, effective_lookback, "AppTraces", "trace_count")
    exc_rows = _query_count_table(effective_workspace, effective_lookback, "AppExceptions", "exception_count")
    merged_rows = _merge_kpi_rows(req_rows, trace_rows, exc_rows, collected_at_utc=collected_at)

    min_bucket = collected_at - timedelta(minutes=effective_lookback + 10)
    filtered_rows = []
    for row in merged_rows:
        try:
            if _parse_bucket(str(row["bucket_utc"])) >= min_bucket:
                filtered_rows.append(row)
        except Exception:
            LOG.warning("Skipping row with invalid bucket: %s", row)

    LOG.info(
        "KPI rows merged=%d filtered=%d (requests=%d traces=%d exceptions=%d)",
        len(merged_rows),
        len(filtered_rows),
        len(req_rows),
        len(trace_rows),
        len(exc_rows),
    )

    if dry_run:
        return 0

    dsn = get_db_dsn(db_dsn)
    with get_connection(dsn) as conn:
        if init_schema:
            ensure_schema(conn)
        inserted = _write_rows(conn, filtered_rows)
    LOG.info("Upserted telemetry KPI rows=%d", inserted)
    return 0


def main() -> int:
    ensure_env_loaded()
    parser = parse_args_base("Collect Log Analytics KPI into monitoring.telemetry_kpi_5m.")
    parser.add_argument(
        "--workspace-id",
        default=os.getenv(
            "LOG_ANALYTICS_WORKSPACE_ID",
            "3a6ae1f6-a887-4b1f-ad70-56f270c974ca",
        ),
        help="Log Analytics workspace id (customerId).",
    )
    parser.add_argument("--lookback-minutes", type=int, default=120)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    return run(
        subscription=args.subscription,
        resource_group=args.resource_group,
        db_dsn=args.db_dsn,
        init_schema=args.init_schema,
        dry_run=args.dry_run,
        workspace_id=args.workspace_id,
        lookback_minutes=args.lookback_minutes,
        log_level=args.log_level,
    )
