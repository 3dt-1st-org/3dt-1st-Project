#!/usr/bin/env python
"""K-Term API로 locallink.tourist_spot_info.tourist_nm 영문명 보강.

Usage:
    python scripts/ingest/enrich_attraction_names_en.py \\
        --dsn "host=... dbname=... user=... password=... sslmode=require" \\
        [--batch-size 50] \\
        [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# ── 프로젝트 루트 sys.path 등록 ───────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.api.kterm_client import translate  # noqa: E402

try:
    import psycopg
    def db_connect(dsn: str):
        return psycopg.connect(dsn)
except ModuleNotFoundError:
    import psycopg2 as psycopg
    def db_connect(dsn: str):
        return psycopg.connect(dsn)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

TABLE = "locallink.tourist_spot_info"
SRC_COL = "tourist_nm"
TGT_COL = "tourist_nm_en"


def ensure_column(cursor) -> None:
    """영문명 컬럼이 없으면 추가."""
    cursor.execute(
        f"""
        ALTER TABLE {TABLE}
        ADD COLUMN IF NOT EXISTS {TGT_COL} TEXT;
        """
    )
    logger.info("컬럼 확인 완료: %s.%s", TABLE, TGT_COL)


def fetch_pending(cursor, batch_size: int) -> list[str]:
    """아직 영문명이 없는 고유 명소명 조회."""
    cursor.execute(
        f"""
        SELECT DISTINCT {SRC_COL}
        FROM   {TABLE}
        WHERE  {SRC_COL} IS NOT NULL
          AND  ({TGT_COL} IS NULL OR {TGT_COL} = '')
        ORDER  BY {SRC_COL}
        LIMIT  %s;
        """,
        (batch_size,),
    )
    return [row[0] for row in cursor.fetchall()]


def update_name(cursor, name: str, name_en: str) -> int:
    """해당 이름을 가진 모든 행 업데이트. 갱신 행 수 반환."""
    cursor.execute(
        f"""
        UPDATE {TABLE}
        SET    {TGT_COL} = %s
        WHERE  {SRC_COL} = %s
          AND  ({TGT_COL} IS NULL OR {TGT_COL} = '');
        """,
        (name_en, name),
    )
    return cursor.rowcount


def run(dsn: str, batch_size: int, dry_run: bool) -> None:
    conn = db_connect(dsn)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            ensure_column(cur)
            conn.commit()

            names = fetch_pending(cur, batch_size)

        if not names:
            logger.info("보강할 명소명 없음 — 종료.")
            return

        logger.info("대상 명소 %d 건 처리 시작.", len(names))

        total_updated = 0
        total_skipped = 0

        for i, name in enumerate(names, 1):
            from src.api import kterm_client
            if kterm_client._DAILY_LIMIT_EXCEEDED:
                logger.warning("일일 한도 초과 — 나머지 %d 건 중단.", len(names) - i + 1)
                break

            name_en = translate(name)

            if name_en:
                if dry_run:
                    logger.info("[DRY-RUN] %s → %s", name, name_en)
                else:
                    with conn.cursor() as cur:
                        updated = update_name(cur, name, name_en)
                    conn.commit()
                    total_updated += updated
                    logger.info("[%d/%d] ✔ %s → %s (%d행 갱신)", i, len(names), name, name_en, updated)
            else:
                total_skipped += 1
                logger.info("[%d/%d] — %s (번역 결과 없음)", i, len(names), name)

        logger.info(
            "완료 — 갱신: %d행 / 건너뜀: %d건",
            total_updated,
            total_skipped,
        )

    except Exception:
        conn.rollback()
        logger.exception("오류 발생 — 롤백 완료.")
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="명소 한국어명 → 영문명 보강 (K-Term API)")
    parser.add_argument("--dsn", required=True, help="PostgreSQL DSN")
    parser.add_argument("--batch-size", type=int, default=100, help="처리 건수 (기본 100)")
    parser.add_argument("--dry-run", action="store_true", help="DB에 쓰지 않고 결과만 출력")
    args = parser.parse_args()

    run(args.dsn, args.batch_size, args.dry_run)


if __name__ == "__main__":
    main()
