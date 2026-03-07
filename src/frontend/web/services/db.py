from __future__ import annotations

import os

import psycopg2


def get_db_dsn() -> str:
    db_dsn = (os.getenv("DB_DSN") or "").strip()
    if db_dsn:
        return db_dsn
    # DB_DSN 환경변수 없으면 Key Vault에서 자동 조회 (로컬 개발 시 az login 필요)
    try:
        from config.vault_manager import get_vault_manager
        return get_vault_manager().get_db_dsn()
    except Exception as e:
        raise RuntimeError(
            "DB_DSN 환경변수가 없고 Key Vault 조회도 실패했습니다. "
            "DB_DSN 환경변수를 설정하거나 Key Vault(KEY_VAULT_URL)를 구성하세요. "
            f"원인: {e}"
        ) from e


def get_db_connection():
    timeout_seconds = int(os.getenv("DB_CONNECT_TIMEOUT_SECONDS", "5"))
    return psycopg2.connect(get_db_dsn(), connect_timeout=timeout_seconds)
