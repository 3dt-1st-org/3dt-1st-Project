from __future__ import annotations

import json
import logging
from typing import Any

from psycopg2.extras import Json

from ._common import (
    configure_logging,
    ensure_env_loaded,
    ensure_schema,
    get_connection,
    get_db_dsn,
    list_resources,
    parse_args_base,
    set_subscription,
    utcnow,
)


LOG = logging.getLogger("monitoring.snapshot_resources")
TARGET_SERVICES = {"lala", "daagn-crawler", "weather-air-func", "lala-db"}


def classify_service(resource: dict[str, Any]) -> tuple[str | None, bool]:
    name = str(resource.get("name") or "").strip()
    rtype = str(resource.get("type") or "").strip().lower()

    if name in TARGET_SERVICES and rtype in {
        "microsoft.web/sites",
        "microsoft.dbforpostgresql/flexibleservers",
    }:
        return name, True
    return None, False


def fetch_resources(subscription: str, resource_group: str) -> list[dict[str, Any]]:
    rows = list_resources(subscription, resource_group)
    if not isinstance(rows, list):
        raise RuntimeError("Unexpected resource list response.")
    return rows


def write_rows(conn, rows: list[dict[str, Any]], collected_at_utc) -> int:
    sql = """
        INSERT INTO monitoring.resource_inventory_snapshot (
            collected_at_utc,
            resource_id,
            resource_name,
            resource_type,
            resource_kind,
            resource_location,
            service_name,
            in_scope,
            tags_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (collected_at_utc, resource_id) DO UPDATE
        SET
            resource_name = EXCLUDED.resource_name,
            resource_type = EXCLUDED.resource_type,
            resource_kind = EXCLUDED.resource_kind,
            resource_location = EXCLUDED.resource_location,
            service_name = EXCLUDED.service_name,
            in_scope = EXCLUDED.in_scope,
            tags_json = EXCLUDED.tags_json
    """
    written = 0
    with conn.cursor() as cur:
        for raw in rows:
            service_name, in_scope = classify_service(raw)
            cur.execute(
                sql,
                (
                    collected_at_utc,
                    raw.get("id"),
                    raw.get("name"),
                    raw.get("type"),
                    raw.get("kind"),
                    raw.get("location"),
                    service_name,
                    in_scope,
                    Json(raw.get("tags") or {}),
                ),
            )
            written += 1
    conn.commit()
    return written


def run(
    *,
    subscription: str,
    resource_group: str,
    db_dsn: str = "",
    init_schema: bool = False,
    dry_run: bool = False,
    print_json: bool = False,
    log_level: str = "INFO",
) -> int:
    configure_logging(log_level)
    set_subscription(subscription)

    collected_at_utc = utcnow()
    rows = fetch_resources(subscription, resource_group)
    in_scope_count = sum(1 for row in rows if classify_service(row)[1])
    LOG.info(
        "Fetched %d resources from resource_group=%s (in_scope=%d).",
        len(rows),
        resource_group,
        in_scope_count,
    )

    if print_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))

    if dry_run:
        return 0

    dsn = get_db_dsn(db_dsn)
    with get_connection(dsn) as conn:
        if init_schema:
            ensure_schema(conn)
        written = write_rows(conn, rows, collected_at_utc)
    LOG.info("Upserted %d inventory rows.", written)
    return 0


def main() -> int:
    ensure_env_loaded()
    parser = parse_args_base("Snapshot Azure resource inventory into monitoring schema.")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--print-json", action="store_true", help="Print fetched resources as json.")
    args = parser.parse_args()

    return run(
        subscription=args.subscription,
        resource_group=args.resource_group,
        db_dsn=args.db_dsn,
        init_schema=args.init_schema,
        dry_run=args.dry_run,
        print_json=args.print_json,
        log_level=args.log_level,
    )
