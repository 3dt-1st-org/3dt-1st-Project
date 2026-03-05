#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

import psycopg2


REQUIRED_TABLE_COLUMNS = {
    ("locallink", "gg_restaurant_info"): {
        "bizplc_nm",
        "refine_roadnm_addr",
        "refine_lotno_addr",
        "refine_wgs84_lat",
        "refine_wgs84_logt",
        "bsn_state_nm",
        "sigun_nm",
    },
    ("locallink", "gyeonggi_events"): {
        "inst_nm",
        "title",
        "begin_de",
        "end_de",
        "url",
        "city",
    },
    ("locallink", "attraction_descriptions"): {
        "attraction_name",
        "overview",
        "history",
        "use_time",
        "parking",
        "closed_days",
        "pet_allowed",
        "sigun_nm",
    },
}

OPTIONAL_TABLES = [
    ("locallink", "docent_script_cache"),
]


def _print(msg: str) -> None:
    print(msg)


def _get_dsn() -> str:
    dsn = (os.getenv("DB_DSN") or "").strip()
    if not dsn:
        raise RuntimeError("DB_DSN is required")
    return dsn


def _table_exists(cur, schema: str, table: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (f"{schema}.{table}",))
    row = cur.fetchone()
    return bool(row and row[0])


def _get_columns(cur, schema: str, table: str) -> set[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        """,
        (schema, table),
    )
    return {row[0] for row in cur.fetchall()}


def main() -> int:
    try:
        dsn = _get_dsn()
    except Exception as exc:
        _print(f"FAIL: {exc}")
        return 1

    try:
        conn = psycopg2.connect(dsn, connect_timeout=5)
    except Exception as exc:
        _print(f"FAIL: DB connect error: {exc}")
        return 1

    ok = True
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT extname FROM pg_extension WHERE extname = 'postgis'")
            has_postgis = bool(cur.fetchone())
            if has_postgis:
                _print("PASS: postgis extension is installed")
            else:
                _print("FAIL: postgis extension is missing")
                ok = False

            for (schema, table), required_cols in REQUIRED_TABLE_COLUMNS.items():
                fqtn = f"{schema}.{table}"
                if not _table_exists(cur, schema, table):
                    _print(f"FAIL: table missing -> {fqtn}")
                    ok = False
                    continue

                existing = _get_columns(cur, schema, table)
                missing = sorted(required_cols - existing)
                if missing:
                    _print(f"FAIL: missing columns in {fqtn} -> {', '.join(missing)}")
                    ok = False
                else:
                    _print(f"PASS: {fqtn} required columns OK")

            for schema, table in OPTIONAL_TABLES:
                fqtn = f"{schema}.{table}"
                exists = _table_exists(cur, schema, table)
                if exists:
                    _print(f"PASS: optional table exists -> {fqtn}")
                else:
                    _print(f"WARN: optional table missing -> {fqtn}")

    conn.close()
    if ok:
        _print("SCHEMA CHECK: PASS")
        return 0

    _print("SCHEMA CHECK: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
