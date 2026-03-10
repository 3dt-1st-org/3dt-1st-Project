from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from ._common import (
    configure_logging,
    ensure_env_loaded,
    ensure_schema,
    get_connection,
    get_db_dsn,
    parse_args_base,
    query_cost_management,
    set_subscription,
    utcnow,
)


LOG = logging.getLogger("monitoring.collect_cost")


def _query_cost_daily(subscription_id: str, resource_group: str) -> dict[str, Any]:
    body = {
        "type": "ActualCost",
        "timeframe": "MonthToDate",
        "dataset": {
            "granularity": "Daily",
            "aggregation": {"totalCost": {"name": "PreTaxCost", "function": "Sum"}},
            "grouping": [
                {"type": "Dimension", "name": "ServiceName"},
                {"type": "Dimension", "name": "ResourceType"},
            ],
        },
    }
    return query_cost_management(subscription_id, resource_group, body)


def _rows_from_cost_payload(payload: dict[str, Any], resource_group: str, collected_at_utc) -> list[dict[str, Any]]:
    properties = payload.get("properties") or {}
    columns = properties.get("columns") or []
    rows = properties.get("rows") or []
    if not columns:
        return []

    column_names = [str(col.get("name") or "") for col in columns]
    col_idx = {name: idx for idx, name in enumerate(column_names)}
    required = {"PreTaxCost", "UsageDate", "Currency"}
    missing = [name for name in required if name not in col_idx]
    if missing:
        raise RuntimeError(f"Cost payload missing required columns: {', '.join(missing)}")

    def _value(row: list[Any], name: str, default: Any = None) -> Any:
        idx = col_idx.get(name)
        if idx is None or idx >= len(row):
            return default
        value = row[idx]
        return default if value is None else value

    result: list[dict[str, Any]] = []
    for raw in rows:
        try:
            cost = Decimal(str(_value(raw, "PreTaxCost", 0)))
            usage_date_raw = int(_value(raw, "UsageDate"))
            usage_date = datetime.strptime(str(usage_date_raw), "%Y%m%d").date()
            service_name = str(_value(raw, "ServiceName", "unknown"))
            resource_type = str(_value(raw, "ResourceType", "unknown"))
            currency = str(_value(raw, "Currency", "KRW"))
        except Exception as exc:
            LOG.warning("Skipping malformed cost row=%s error=%s", raw, exc)
            continue

        result.append(
            {
                "collected_at_utc": collected_at_utc,
                "usage_date": usage_date,
                "service_name": service_name,
                "resource_type": resource_type,
                "currency": currency,
                "cost_amount": cost,
                "scope_resource_group": resource_group,
            }
        )
    return result


def _write_rows(conn, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    sql = """
        INSERT INTO monitoring.cost_daily (
            collected_at_utc,
            usage_date,
            service_name,
            resource_type,
            currency,
            cost_amount,
            scope_resource_group
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (usage_date, service_name, resource_type, currency, scope_resource_group) DO UPDATE
        SET
            collected_at_utc = EXCLUDED.collected_at_utc,
            cost_amount = EXCLUDED.cost_amount
    """
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                sql,
                (
                    row["collected_at_utc"],
                    row["usage_date"],
                    row["service_name"],
                    row["resource_type"],
                    row["currency"],
                    row["cost_amount"],
                    row["scope_resource_group"],
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
    log_level: str = "INFO",
) -> int:
    configure_logging(log_level)
    set_subscription(subscription)

    payload = _query_cost_daily(subscription, resource_group)
    rows = _rows_from_cost_payload(payload, resource_group, utcnow())
    LOG.info("Parsed cost rows=%d", len(rows))

    if dry_run:
        return 0

    dsn = get_db_dsn(db_dsn)
    with get_connection(dsn) as conn:
        if init_schema:
            ensure_schema(conn)
        inserted = _write_rows(conn, rows)
    LOG.info("Upserted cost rows=%d", inserted)
    return 0


def main() -> int:
    ensure_env_loaded()
    parser = parse_args_base("Collect Cost Management data into monitoring.cost_daily.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    return run(
        subscription=args.subscription,
        resource_group=args.resource_group,
        db_dsn=args.db_dsn,
        init_schema=args.init_schema,
        dry_run=args.dry_run,
        log_level=args.log_level,
    )
