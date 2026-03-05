#!/usr/bin/env python
"""도로명주소 영문 변환 일괄 보강 (주소기반산업지원서비스 영문주소 API).

대상 테이블:
  1. locallink.tourist_spot_info   road_addr         → road_addr_en         (약 200건)
  2. locallink.gg_restaurant_info  refine_roadnm_addr → refine_roadnm_addr_en (약 27,604건)

동작 방식:
  - 미처리 고유 주소를 DB에서 한 번에 로드
  - ThreadPoolExecutor로 병렬 API 호출 (기본 5 workers)
  - 동일 원문 주소는 캐시로 재사용 (API 중복 호출 방지)
  - 1,000건 단위 배치 UPDATE

Usage:
    python scripts/ingest/enrich_addresses_en.py \\
        --dsn "host=... dbname=... user=... password=... sslmode=require" \\
        [--table tourist|restaurant|all]  (기본 all) \\
        [--workers 5] \\
        [--commit-size 1000] \\
        [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.api.juso_client import translate_address  # noqa: E402

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

# ── 테이블 설정 ───────────────────────────────────────────────────────────────
TARGETS = {
    "tourist": {
        "table":   "locallink.tourist_spot_info",
        "src_col": "road_addr",
        "tgt_col": "road_addr_en",
    },
    "restaurant": {
        "table":   "locallink.gg_restaurant_info",
        "src_col": "refine_roadnm_addr",
        "tgt_col": "refine_roadnm_addr_en",
    },
}


def ensure_column(cursor, table: str, col: str) -> None:
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} TEXT;")
    logger.info("컬럼 확인: %s.%s", table, col)


def fetch_pending(cursor, table: str, src_col: str, tgt_col: str) -> list[str]:
    """미처리 고유 주소 목록 반환 (NaN·빈값 제외)."""
    cursor.execute(f"""
        SELECT DISTINCT {src_col}
        FROM   {table}
        WHERE  {src_col} IS NOT NULL
          AND  {src_col} != 'NaN'
          AND  LENGTH(TRIM({src_col})) > 5
          AND  ({tgt_col} IS NULL OR {tgt_col} = '')
        ORDER  BY {src_col};
    """)
    return [row[0] for row in cursor.fetchall()]


def translate_all(addresses: list[str], workers: int) -> dict[str, str | None]:
    """병렬 API 호출로 {원문주소: 영문주소} 캐시 dict 반환."""
    cache: dict[str, str | None] = {}
    total = len(addresses)
    done = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(translate_address, addr): addr for addr in addresses}
        for future in as_completed(futures):
            addr = futures[future]
            try:
                cache[addr] = future.result()
            except Exception as exc:
                logger.debug("번역 실패 (%s): %s", addr, exc)
                cache[addr] = None
            done += 1
            if done % 500 == 0 or done == total:
                logger.info("API 호출 진행: %d / %d (%.0f%%)", done, total, done / total * 100)

    return cache


def batch_update(conn, table: str, src_col: str, tgt_col: str,
                 cache: dict[str, str | None], commit_size: int) -> int:
    """캐시에서 영문주소가 있는 것만 배치 UPDATE, 갱신 행수 반환."""
    SQL = (
        f"UPDATE {table} SET {tgt_col} = %s "
        f"WHERE {src_col} = %s "
        f"AND ({tgt_col} IS NULL OR {tgt_col} = '');"
    )
    params = [(en, ko) for ko, en in cache.items() if en]
    total_updated = 0

    for i in range(0, len(params), commit_size):
        chunk = params[i: i + commit_size]
        with conn.cursor() as cur:
            cur.executemany(SQL, chunk)
            total_updated += cur.rowcount
        conn.commit()

    return total_updated


def run_target(conn, cfg: dict, workers: int, commit_size: int, dry_run: bool) -> None:
    table, src_col, tgt_col = cfg["table"], cfg["src_col"], cfg["tgt_col"]

    with conn.cursor() as cur:
        ensure_column(cur, table, tgt_col)
    conn.commit()

    with conn.cursor() as cur:
        addresses = fetch_pending(cur, table, src_col, tgt_col)

    if not addresses:
        logger.info("[%s] 처리할 주소 없음 — 건너뜀", table)
        return

    total = len(addresses)
    logger.info("[%s] 총 %d 건 영문주소 변환 시작 (workers=%d)...", table, total, workers)

    t0 = time.time()
    cache = translate_all(addresses, workers)

    hit  = sum(1 for v in cache.values() if v)
    miss = total - hit
    logger.info("[%s] 번역 완료: 성공 %d건 / 실패(None) %d건 (%.1f초)",
                table, hit, miss, time.time() - t0)

    if dry_run:
        shown = [(ko, en) for ko, en in cache.items() if en][:10]
        for ko, en in shown:
            logger.info("[DRY-RUN] %-60s  ->  %s", ko, en)
        if miss:
            failed = [(ko, en) for ko, en in cache.items() if not en][:3]
            for ko, _ in failed:
                logger.info("[DRY-RUN] 번역실패: %s", ko)
        return

    updated = batch_update(conn, table, src_col, tgt_col, cache, commit_size)
    logger.info("[%s] 완료 — 갱신: %d행 / 소요: %.1f초", table, updated, time.time() - t0)


def run(dsn: str, tables: list[str], workers: int, commit_size: int, dry_run: bool) -> None:
    conn = db_connect(dsn)
    conn.autocommit = False
    try:
        for key in tables:
            run_target(conn, TARGETS[key], workers, commit_size, dry_run)
    except Exception:
        conn.rollback()
        logger.exception("오류 발생 — 롤백 완료.")
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="도로명주소 한국어 → 영문 보강 (주소기반산업지원서비스 API)"
    )
    parser.add_argument("--dsn", required=True, help="PostgreSQL DSN")
    parser.add_argument(
        "--table", choices=["tourist", "restaurant", "all"], default="all",
        help="처리할 테이블 (기본 all)",
    )
    parser.add_argument("--workers", type=int, default=5, help="병렬 API 호출 수 (기본 5)")
    parser.add_argument("--commit-size", type=int, default=1000, help="DB 커밋 단위 (기본 1000)")
    parser.add_argument("--dry-run", action="store_true", help="DB에 쓰지 않고 10건만 출력")
    args = parser.parse_args()

    tables = ["tourist", "restaurant"] if args.table == "all" else [args.table]
    run(args.dsn, tables, args.workers, args.commit_size, args.dry_run)


if __name__ == "__main__":
    main()
