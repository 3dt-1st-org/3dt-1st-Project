#!/usr/bin/env python3
"""
2025년 경기도 행사 데이터를 2026년 날짜(같은 달의 N번째 주, 같은 요일)로 변환하여 추가 적재합니다.

알고리즘:
  - 2025-MM-DD → 해당 달의 N번째 주, K요일(0=월요일) 추출
  - 2026년 동일 (달, N번째 주, K요일) → 새 날짜 계산
  - duration(end-begin 일수)은 동일하게 유지
  - title 내 "2025" 문자열을 "2026"으로 교체
  - 기존 데이터 유지 (TRUNCATE 없이 INSERT만 수행)
"""

import sys
import logging
from pathlib import Path
from datetime import date, timedelta

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from config.vault_manager import get_vault_manager
from psycopg2.extras import execute_batch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

TABLE = "locallink.gyeonggi_events"


def _nth_week_weekday(d: date) -> tuple[int, int]:
    """날짜 d가 해당 달의 몇 번째 주(nth)인지, 무슨 요일(weekday, 0=월)인지 반환."""
    nth = (d.day - 1) // 7 + 1
    return nth, d.weekday()


def _nth_weekday_of_month(year: int, month: int, nth: int, weekday: int) -> date | None:
    """year년 month월에서 nth번째 weekday 날짜를 반환. 해당 달에 없으면 None."""
    first = date(year, month, 1)
    delta = (weekday - first.weekday()) % 7
    first_occ = first + timedelta(days=delta)
    result = first_occ + timedelta(weeks=nth - 1)
    if result.month != month:
        return None
    return result


def _convert_date_to_2026(d: date) -> date | None:
    """2025년 날짜를 2026년 동일 패턴(같은 달, N번째 주의 K요일)으로 변환.
    해당 달에 N번째 주가 없으면(예: 5번째 주 없음) 마지막(4번째) 주로 대체.
    """
    nth, weekday = _nth_week_weekday(d)
    result = _nth_weekday_of_month(2026, d.month, nth, weekday)
    if result is None and nth > 1:
        # 5번째 주가 없는 달 → 4번째 주로 fallback
        result = _nth_weekday_of_month(2026, d.month, nth - 1, weekday)
    return result


def _check_latlon_columns(cur) -> bool:
    cur.execute(
        """
        SELECT COUNT(*) FROM information_schema.columns
        WHERE table_schema = 'locallink'
          AND table_name   = 'gyeonggi_events'
          AND column_name  IN ('lat', 'lng')
        """
    )
    return cur.fetchone()[0] == 2


def main():
    logger.info("=== 2025→2026 행사 날짜 변환 적재 시작 ===")
    conn = get_vault_manager().get_db_connection()
    try:
        with conn.cursor() as cur:
            # 이미 2026 데이터가 있으면 경고 후 계속 (중복 방지는 별도 처리)
            cur.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE begin_de LIKE '2026-%'")
            existing_2026 = cur.fetchone()[0]
            if existing_2026 > 0:
                logger.warning(
                    "이미 2026년 행사 데이터가 %d건 존재합니다. "
                    "중복 적재가 발생할 수 있습니다. 계속 진행합니다.",
                    existing_2026,
                )

            # lat/lng 컬럼 존재 여부 확인
            has_latlon = _check_latlon_columns(cur)
            logger.info("lat/lng 컬럼 존재: %s", has_latlon)

            # 2025년 행사 전체 조회
            if has_latlon:
                cur.execute(
                    f"SELECT inst_nm, title, begin_de, end_de, url, image_url, writng_de, city, lat, lng "
                    f"FROM {TABLE} WHERE begin_de LIKE '2025-%'"
                )
            else:
                cur.execute(
                    f"SELECT inst_nm, title, begin_de, end_de, url, image_url, writng_de, city "
                    f"FROM {TABLE} WHERE begin_de LIKE '2025-%'"
                )

            rows = cur.fetchall()
            logger.info("2025년 행사 %d건 조회", len(rows))

            if not rows:
                logger.warning("2025년 행사 데이터가 없습니다. 종료.")
                return

            new_rows: list[tuple] = []
            skipped = 0

            for row in rows:
                if has_latlon:
                    inst_nm, title, begin_str, end_str, url, image_url, writng_de, city, lat, lng = row
                else:
                    inst_nm, title, begin_str, end_str, url, image_url, writng_de, city = row
                    lat, lng = None, None

                if not begin_str:
                    skipped += 1
                    continue

                try:
                    begin_2025 = date.fromisoformat(begin_str)
                    end_2025 = date.fromisoformat(end_str) if end_str else begin_2025
                except ValueError:
                    logger.warning(
                        "날짜 파싱 실패: begin=%s end=%s (title=%s)", begin_str, end_str, title
                    )
                    skipped += 1
                    continue

                # 2026년 날짜 변환
                new_begin = _convert_date_to_2026(begin_2025)
                if new_begin is None:
                    logger.warning("2026 날짜 변환 실패: %s (title=%s)", begin_str, title)
                    skipped += 1
                    continue

                duration_days = (end_2025 - begin_2025).days
                new_end = new_begin + timedelta(days=duration_days)

                # 제목 내 연도 교체 (2025 → 2026)
                new_title = title.replace("2025", "2026") if title else title

                logger.debug(
                    "[%s] %s → %s  (duration=%d일)",
                    title, begin_2025, new_begin, duration_days,
                )

                if has_latlon:
                    new_rows.append((
                        inst_nm, new_title,
                        new_begin.isoformat(), new_end.isoformat(),
                        url, image_url, writng_de, city, lat, lng,
                    ))
                else:
                    new_rows.append((
                        inst_nm, new_title,
                        new_begin.isoformat(), new_end.isoformat(),
                        url, image_url, writng_de, city,
                    ))

            logger.info("변환 완료: %d건 INSERT 예정, %d건 스킵", len(new_rows), skipped)

            if not new_rows:
                logger.warning("INSERT할 데이터가 없습니다. 종료.")
                return

            if has_latlon:
                col_sql = "(inst_nm, title, begin_de, end_de, url, image_url, writng_de, city, lat, lng)"
                placeholders = "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            else:
                col_sql = "(inst_nm, title, begin_de, end_de, url, image_url, writng_de, city)"
                placeholders = "(%s, %s, %s, %s, %s, %s, %s, %s)"

            execute_batch(
                cur,
                f"INSERT INTO {TABLE} {col_sql} VALUES {placeholders}",
                new_rows,
                page_size=500,
            )
            conn.commit()
            logger.info("✅ 2026년 행사 %d건 INSERT 완료", len(new_rows))

            # 검증 쿼리
            cur.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE begin_de LIKE '2026-%'")
            logger.info("현재 2026년 행사 총 %d건", cur.fetchone()[0])

    finally:
        conn.close()


if __name__ == "__main__":
    main()
