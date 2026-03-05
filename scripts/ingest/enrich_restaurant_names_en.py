#!/usr/bin/env python
"""locallink.gg_restaurant_info.bizplc_nm 영문명 보강 (로컬 로마자 변환 전용).

K-Term API 미사용 - 29,000+ 건을 빠르게 처리하기 위해
  1. 전체 고유 상호명 + 업태를 DB에서 한 번에 로드
  2. Python에서 로마자 변환 (네트워크 없음, 매우 빠름)
  3. 1,000건 단위 executemany 배치 UPDATE

변환 형식: 상호명 로마자 (업종 영어)
  예)  할머니네집, 한식  ->  Halmeoninejip (Korean Restaurant)
       스타벅스,  까페   ->  Seutabeogseu (Cafe)

Usage:
    python scripts/ingest/enrich_restaurant_names_en.py \
        --dsn "host=... dbname=... user=... password=... sslmode=require" \
        [--commit-size 1000] \
        [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.api.kterm_client import romanize_restaurant_fallback  # noqa: E402

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

TABLE   = "locallink.gg_restaurant_info"
SRC_COL = "bizplc_nm"
TGT_COL = "bizplc_nm_en"
BIZ_COL = "bizcond_div_nm_info"


def ensure_column(cursor) -> None:
    cursor.execute(
        f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS {TGT_COL} TEXT;"
    )
    logger.info("컬럼 확인 완료: %s.%s", TABLE, TGT_COL)


def fetch_all_pending(cursor) -> list:
    """미처리 고유 상호명 전체를 (bizplc_nm, bizcond_div_nm_info) 로 로드."""
    cursor.execute(
        f"""
        SELECT DISTINCT ON ({SRC_COL})
               {SRC_COL},
               NULLIF(TRIM({BIZ_COL}), '')
        FROM   {TABLE}
        WHERE  {SRC_COL} IS NOT NULL
          AND  ({TGT_COL} IS NULL OR {TGT_COL} = '')
        ORDER  BY {SRC_COL};
        """
    )
    return [(row[0], row[1]) for row in cursor.fetchall()]


def run(dsn: str, commit_size: int, dry_run: bool) -> None:
    conn = db_connect(dsn)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            ensure_column(cur)
            conn.commit()
            logger.info("미처리 상호명 로드 중...")
            rows = fetch_all_pending(cur)

        if not rows:
            logger.info("보강할 음식점 없음 - 종료.")
            return

        total = len(rows)
        logger.info("총 %d 건 로마자 변환 시작 (API 호출 없음)...", total)

        t0 = time.time()

        # 1단계: Python 로컬 변환 (매우 빠름)
        converted = []   # (name_en, name) - UPDATE 파라미터 순서
        for name, biz_type in rows:
            name_en = romanize_restaurant_fallback(name, biz_type)
            converted.append((name_en, name))

        elapsed_conv = time.time() - t0
        logger.info("변환 완료: %d 건 (%.1f초)", total, elapsed_conv)

        if dry_run:
            for name_en, name in converted[:20]:
                logger.info("[DRY-RUN] %s  ->  %s", name, name_en)
            if total > 20:
                logger.info("... 외 %d 건 (--dry-run: 처음 20건만 표시)", total - 20)
            return

        # 2단계: 배치 UPDATE
        SQL = (
            f"UPDATE {TABLE} "
            f"SET {TGT_COL} = %s "
            f"WHERE {SRC_COL} = %s "
            f"AND ({TGT_COL} IS NULL OR {TGT_COL} = '');"
        )

        total_updated = 0
        for chunk_start in range(0, total, commit_size):
            chunk = converted[chunk_start : chunk_start + commit_size]
            with conn.cursor() as cur:
                cur.executemany(SQL, chunk)
                total_updated += cur.rowcount
            conn.commit()
            done = min(chunk_start + commit_size, total)
            logger.info("진행: %d / %d (%.0f%%)", done, total, done / total * 100)

        elapsed_total = time.time() - t0
        logger.info(
            "완료 - 갱신: %d행 / 소요: %.1f초 (초당 %.0f건)",
            total_updated, elapsed_total, total_updated / max(elapsed_total, 1),
        )

    except Exception:
        conn.rollback()
        logger.exception("오류 발생 - 롤백 완료.")
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="음식점명 한국어 -> 로마자 영문명 보강 (로컬 변환, API 미사용)"
    )
    parser.add_argument("--dsn", required=True, help="PostgreSQL DSN")
    parser.add_argument(
        "--commit-size", type=int, default=1000,
        help="한 번에 커밋할 행 수 (기본 1000)",
    )
    parser.add_argument("--dry-run", action="store_true", help="DB에 쓰지 않고 처음 20건만 출력")
    args = parser.parse_args()

    run(args.dsn, args.commit_size, args.dry_run)


if __name__ == "__main__":
    main()