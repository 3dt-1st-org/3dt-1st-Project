#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.monitoring._common import ensure_env_loaded, get_connection, get_db_dsn


REQUIRED_VIEWS = {
    "vw_overview_latest",
    "vw_service_health_5m",
    "vw_realtime_kpi_1m",
    "vw_cost_burn_daily",
    "vw_incidents_5m",
}

REQUIRED_OVERVIEW_COLUMNS = {
    "as_of_utc",
    "kpi_bucket_utc",
    "stream_window_end_utc",
    "today_cost_krw",
    "mtd_cost_krw",
    "healthy_service_count",
    "total_service_count",
    "failed_requests_5m",
    "exceptions_5m",
    "max_p95_duration_ms",
    "stream_event_count_1m",
    "stream_http5xx_count_1m",
    "stream_error_count_1m",
    "stream_delay_seconds",
}

REQUIRED_REALTIME_COLUMNS = {
    "window_end_utc",
    "collected_at_utc",
    "service_name",
    "category",
    "event_count",
    "http5xx_count",
    "error_count",
    "success_count",
    "error_rate_pct",
    "http5xx_rate_pct",
}


@dataclass
class CheckResult:
    ok: bool
    message: str
    details: dict[str, Any]


def _fetch_set(cur, sql: str, params: tuple[Any, ...]) -> set[str]:
    cur.execute(sql, params)
    return {str(row[0]) for row in cur.fetchall()}


def _check_views(cur) -> CheckResult:
    existing = _fetch_set(
        cur,
        """
        SELECT table_name
        FROM information_schema.views
        WHERE table_schema = %s
        """,
        ("monitoring",),
    )
    missing = sorted(REQUIRED_VIEWS - existing)
    return CheckResult(
        ok=not missing,
        message="required views check",
        details={"missing_views": missing, "existing_views_count": len(existing)},
    )


def _check_columns(cur, view_name: str, required: set[str]) -> CheckResult:
    existing = _fetch_set(
        cur,
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        """,
        ("monitoring", view_name),
    )
    missing = sorted(required - existing)
    return CheckResult(
        ok=not missing,
        message=f"columns check: monitoring.{view_name}",
        details={"missing_columns": missing, "existing_columns_count": len(existing)},
    )


def _fetch_overview(cur) -> dict[str, Any] | None:
    cur.execute(
        """
        SELECT
            as_of_utc,
            kpi_bucket_utc,
            stream_window_end_utc,
            stream_event_count_1m,
            stream_http5xx_count_1m,
            stream_error_count_1m,
            stream_delay_seconds
        FROM monitoring.vw_overview_latest
        LIMIT 1
        """
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "as_of_utc": row[0],
        "kpi_bucket_utc": row[1],
        "stream_window_end_utc": row[2],
        "stream_event_count_1m": row[3],
        "stream_http5xx_count_1m": row[4],
        "stream_error_count_1m": row[5],
        "stream_delay_seconds": row[6],
    }


def _validate_overview_against_stream(cur, overview: dict[str, Any] | None) -> CheckResult:
    if overview is None:
        return CheckResult(
            ok=False,
            message="overview row check",
            details={"error": "monitoring.vw_overview_latest returned no rows"},
        )

    cur.execute(
        """
        WITH last_stream AS (
            SELECT MAX(window_end_utc) AS window_end_utc
            FROM monitoring.telemetry_kpi_stream_1m
        )
        SELECT
            ls.window_end_utc,
            COALESCE(SUM(t.event_count), 0) AS event_count,
            COALESCE(SUM(t.http5xx_count), 0) AS http5xx_count,
            COALESCE(SUM(t.error_count), 0) AS error_count
        FROM last_stream ls
        LEFT JOIN monitoring.telemetry_kpi_stream_1m t
               ON t.window_end_utc = ls.window_end_utc
        GROUP BY ls.window_end_utc
        """
    )
    row = cur.fetchone()
    expected = {
        "stream_window_end_utc": row[0] if row else None,
        "stream_event_count_1m": int(row[1]) if row and row[1] is not None else 0,
        "stream_http5xx_count_1m": int(row[2]) if row and row[2] is not None else 0,
        "stream_error_count_1m": int(row[3]) if row and row[3] is not None else 0,
    }

    mismatches: dict[str, dict[str, Any]] = {}
    for key in expected:
        actual = overview.get(key)
        if actual != expected[key]:
            mismatches[key] = {"expected": expected[key], "actual": actual}

    delay_value = overview.get("stream_delay_seconds")
    delay_ok = delay_value is None or int(delay_value) >= 0
    if not delay_ok:
        mismatches["stream_delay_seconds"] = {"expected": ">= 0 or NULL", "actual": delay_value}

    return CheckResult(
        ok=not mismatches,
        message="overview realtime aggregation check",
        details={"mismatches": mismatches, "overview": overview, "expected": expected},
    )


def _validate_stream_delay_sla(
    overview: dict[str, Any] | None, *, max_stream_delay_seconds: int
) -> CheckResult:
    if overview is None:
        return CheckResult(
            ok=False,
            message="stream delay SLA check",
            details={"error": "overview row is empty"},
        )

    delay = overview.get("stream_delay_seconds")
    if delay is None:
        return CheckResult(
            ok=False,
            message="stream delay SLA check",
            details={"error": "stream_delay_seconds is NULL"},
        )

    delay_int = int(delay)
    ok = delay_int <= max_stream_delay_seconds
    return CheckResult(
        ok=ok,
        message="stream delay SLA check",
        details={
            "delay_seconds": delay_int,
            "max_stream_delay_seconds": max_stream_delay_seconds,
            "within_sla": ok,
        },
    )


def main() -> int:
    ensure_env_loaded()
    parser = argparse.ArgumentParser(
        description="Validate realtime semantic model source views and KPI card source values."
    )
    parser.add_argument(
        "--db-dsn",
        default="",
        help="PostgreSQL DSN override. If omitted, DB_DSN env / Key Vault db-dsn is used.",
    )
    parser.add_argument(
        "--max-stream-delay-seconds",
        type=int,
        default=120,
        help="Fail when stream_delay_seconds is greater than this threshold.",
    )
    parser.add_argument("--print-json", action="store_true", help="Print check results as JSON.")
    args = parser.parse_args()

    dsn = get_db_dsn(args.db_dsn)
    checks: list[CheckResult] = []

    with get_connection(dsn) as conn:
        with conn.cursor() as cur:
            checks.append(_check_views(cur))
            checks.append(_check_columns(cur, "vw_overview_latest", REQUIRED_OVERVIEW_COLUMNS))
            checks.append(_check_columns(cur, "vw_realtime_kpi_1m", REQUIRED_REALTIME_COLUMNS))
            overview = _fetch_overview(cur)
            checks.append(_validate_overview_against_stream(cur, overview))
            checks.append(
                _validate_stream_delay_sla(
                    overview,
                    max_stream_delay_seconds=max(args.max_stream_delay_seconds, 1),
                )
            )

    payload = [
        {
            "ok": item.ok,
            "message": item.message,
            "details": item.details,
        }
        for item in checks
    ]

    if args.print_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        for item in payload:
            status = "OK" if item["ok"] else "FAIL"
            print(f"[{status}] {item['message']}")
            if item["details"]:
                print(json.dumps(item["details"], ensure_ascii=False, indent=2, default=str))

    return 0 if all(item.ok for item in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
