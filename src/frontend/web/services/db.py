from __future__ import annotations

import os

import psycopg2


def get_db_dsn() -> str:
    db_dsn = (os.getenv("DB_DSN") or "").strip()
    if not db_dsn:
        raise RuntimeError("DB_DSN is required.")
    return db_dsn


def get_db_connection():
    timeout_seconds = int(os.getenv("DB_CONNECT_TIMEOUT_SECONDS", "5"))
    return psycopg2.connect(get_db_dsn(), connect_timeout=timeout_seconds)
