from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from ._common import configure_logging, ensure_schema, get_connection, get_db_dsn, utcnow


LOG = logging.getLogger("monitoring.ingest_stream_kpi")


def _parse_utc_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_int(value: Any, *, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(str(value)))
        except (TypeError, ValueError):
            return default


def _decode_payload(raw_payload: Any) -> list[dict[str, Any]]:
    if raw_payload is None:
        return []

    if isinstance(raw_payload, dict):
        return [raw_payload]
    if isinstance(raw_payload, list):
        return [item for item in raw_payload if isinstance(item, dict)]

    if isinstance(raw_payload, (bytes, bytearray)):
        text = raw_payload.decode("utf-8", errors="replace").strip()
    else:
        text = str(raw_payload).strip()

    if not text:
        return []

    parsed_rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            parsed_rows.append(value)
        elif isinstance(value, list):
            parsed_rows.extend([item for item in value if isinstance(item, dict)])
    return parsed_rows


def _normalize_rows(raw_rows: list[dict[str, Any]], *, collected_at_utc: datetime) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in raw_rows:
        window_end_utc = _parse_utc_timestamp(
            row.get("window_end_utc")
            or row.get("window_end")
            or row.get("event_time")
            or row.get("time")
        )
        if window_end_utc is None:
            LOG.warning("Skip stream KPI row without valid window timestamp: %s", row)
            continue

        service_name = str(row.get("service_name") or "").strip() or "unknown"
        category = str(row.get("category") or "").strip() or "unknown"

        normalized.append(
            {
                "collected_at_utc": collected_at_utc,
                "window_end_utc": window_end_utc,
                "service_name": service_name,
                "category": category,
                "event_count": _to_int(row.get("event_count")),
                "http5xx_count": _to_int(row.get("http5xx_count")),
                "error_count": _to_int(row.get("error_count")),
                "success_count": _to_int(row.get("success_count")),
            }
        )
    return normalized


def _upsert_rows(conn, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    sql = """
        INSERT INTO monitoring.telemetry_kpi_stream_1m (
            collected_at_utc,
            window_end_utc,
            service_name,
            category,
            event_count,
            http5xx_count,
            error_count,
            success_count
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (window_end_utc, service_name, category) DO UPDATE
        SET
            collected_at_utc = EXCLUDED.collected_at_utc,
            event_count = EXCLUDED.event_count,
            http5xx_count = EXCLUDED.http5xx_count,
            error_count = EXCLUDED.error_count,
            success_count = EXCLUDED.success_count
    """
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                sql,
                (
                    row["collected_at_utc"],
                    row["window_end_utc"],
                    row["service_name"],
                    row["category"],
                    row["event_count"],
                    row["http5xx_count"],
                    row["error_count"],
                    row["success_count"],
                ),
            )
    conn.commit()
    return len(rows)


def run(
    *,
    db_dsn: str,
    raw_payload: Any,
    init_schema: bool = False,
    dry_run: bool = False,
    log_level: str = "INFO",
) -> int:
    configure_logging(log_level)
    collected_at = utcnow()

    parsed = _decode_payload(raw_payload)
    rows = _normalize_rows(parsed, collected_at_utc=collected_at)
    if dry_run:
        LOG.info("Dry-run: parsed=%d normalized=%d", len(parsed), len(rows))
        return 0

    dsn = get_db_dsn(db_dsn)
    with get_connection(dsn) as conn:
        if init_schema:
            ensure_schema(conn)
        upserted = _upsert_rows(conn, rows)
    LOG.info("Upserted stream KPI rows=%d", upserted)
    return upserted
