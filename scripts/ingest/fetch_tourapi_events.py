#!/usr/bin/env python
"""TourAPI 4.0 경기도 행사 수집 → locallink.gyeonggi_events 적재

사용법:
    python scripts/ingest/fetch_tourapi_events.py
    python scripts/ingest/fetch_tourapi_events.py --start 20260101  # 시작일 지정
    python scripts/ingest/fetch_tourapi_events.py --dry-run          # DB 미적재, 결과만 출력

소스: 한국관광공사 TourAPI 4.0
  Base URL : https://apis.data.go.kr/B551011/KorService2
  Endpoint : GET /searchFestival2
  Key Vault: tour-api-key

응답 → DB 컬럼 매핑
  title          → title
  addr1          → inst_nm (장소/주소)
  eventstartdate → begin_de (YYYY-MM-DD)
  eventenddate   → end_de   (YYYY-MM-DD)
  firstimage     → image_url
  contentid URL  → url
  createdtime    → writng_de
  mapy / mapx    → lat / lng  (gyeonggi_events 테이블에 컬럼 필요, migration 참고)
  addr1 파싱     → city
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from datetime import date, datetime
from typing import Any

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# ── 상수 ─────────────────────────────────────────────────────────────────────
BASE_URL    = "https://apis.data.go.kr/B551011/KorService2/searchFestival2"
AREA_CODE   = "31"          # 경기도
NUM_OF_ROWS = 100           # 1회 요청 최대 개수
MAX_PAGES   = 50            # 안전장치 (최대 5,000건)
MOBILE_OS   = "ETC"
MOBILE_APP  = "lala"
TABLE       = "locallink.gyeonggi_events"

# 경기도 시/군 이름 목록 (addr1에서 city 파싱용)
GYEONGGI_CITIES: list[tuple[str, str]] = [
    # (매칭 키워드, DB 저장값)
    ("수원",   "수원시"),
    ("성남",   "성남시"),
    ("고양",   "고양시"),
    ("용인",   "용인시"),
    ("부천",   "부천시"),
    ("안산",   "안산시"),
    ("안양",   "안양시"),
    ("남양주", "남양주시"),
    ("화성",   "화성시"),
    ("평택",   "평택시"),
    ("의정부", "의정부시"),
    ("시흥",   "시흥시"),
    ("파주",   "파주시"),
    ("광명",   "광명시"),
    ("김포",   "김포시"),
    ("군포",   "군포시"),
    ("광주",   "광주시"),
    ("이천",   "이천시"),
    ("양주",   "양주시"),
    ("오산",   "오산시"),
    ("구리",   "구리시"),
    ("안성",   "안성시"),
    ("포천",   "포천시"),
    ("의왕",   "의왕시"),
    ("하남",   "하남시"),
    ("여주",   "여주시"),
    ("양평",   "양평군"),
    ("동두천", "동두천시"),
    ("과천",   "과천시"),
    ("가평",   "가평군"),
    ("연천",   "연천군"),
]

# 컬럼이 이미 여기 있는지 여부 — migration을 먼저 실행해야 lat/lng 저장 가능
_HAS_LATLON_COLS: bool | None = None  # 런타임에 확인


def _extract_city(addr: str) -> str:
    """addr1 주소 문자열에서 경기도 시/군 이름을 추출합니다."""
    for keyword, city_name in GYEONGGI_CITIES:
        if keyword in addr:
            return city_name
    return "기타"


def _fmt_date(yyyymmdd: str | None) -> str | None:
    """'20260101' → '2026-01-01', 잘못된 형식이면 None 반환."""
    if not yyyymmdd:
        return None
    s = str(yyyymmdd).strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


def _safe_float(val: Any) -> float | None:
    """문자열을 float으로 변환, 실패 시 None."""
    try:
        v = float(val)
        return v if v != 0.0 else None
    except (TypeError, ValueError):
        return None


def _get_api_key() -> str:
    """Key Vault(또는 환경변수 TOUR_API_KEY)에서 TourAPI 서비스키를 가져옵니다."""
    from config.vault_manager import get_vault_manager
    v = get_vault_manager()
    key = v.get_secret("tour-api-key")
    if not key:
        raise RuntimeError(
            "TourAPI 키를 찾을 수 없습니다. "
            "Key Vault에 'tour-api-key' 시크릿이 있는지, "
            "또는 환경변수 TOUR_API_KEY가 설정됐는지 확인하세요."
        )
    return key


def _fetch_page(service_key: str, page_no: int, event_start_date: str) -> dict:
    """searchFestival2 API를 호출해 단일 페이지 결과를 반환합니다."""
    params = {
        "serviceKey":      service_key,
        "MobileOS":        MOBILE_OS,
        "MobileApp":       MOBILE_APP,
        "_type":           "json",
        "listYN":          "Y",
        "arrange":         "D",       # 수정일 내림차순
        "areaCode":        AREA_CODE,
        "eventStartDate":  event_start_date,
        "numOfRows":       NUM_OF_ROWS,
        "pageNo":          page_no,
    }
    resp = requests.get(BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _parse_items(data: dict) -> tuple[list[dict], int]:
    """API 응답 JSON에서 아이템 목록과 전체 건수를 파싱합니다."""
    try:
        body = data["response"]["body"]
        total_count = int(body.get("totalCount", 0))
        items_raw = body.get("items", {})
        if not items_raw or items_raw == "":
            return [], total_count
        items = items_raw.get("item", [])
        if isinstance(items, dict):  # 결과 1건이면 list 아닌 dict
            items = [items]
        return items, total_count
    except (KeyError, TypeError, ValueError) as e:
        logger.warning("응답 파싱 실패: %s | raw=%s", e, str(data)[:300])
        return [], 0


def _item_to_row(item: dict) -> dict:
    """API 아이템 1건을 DB INSERT용 dict로 변환합니다."""
    content_id = str(item.get("contentid", "")).strip()
    URL = (
        f"https://korean.visitkorea.or.kr/detail/ms_detail.do?cotid={content_id}"
        if content_id else ""
    )
    addr1 = str(item.get("addr1", "")).strip()
    created = str(item.get("createdtime", "")).strip()
    writng_de = _fmt_date(created[:8]) if len(created) >= 8 else None

    return {
        "inst_nm":   addr1,
        "title":     str(item.get("title", "")).strip(),
        "begin_de":  _fmt_date(str(item.get("eventstartdate", ""))),
        "end_de":    _fmt_date(str(item.get("eventenddate", ""))),
        "url":       URL,
        "image_url": str(item.get("firstimage", "")).strip() or None,
        "writng_de": writng_de,
        "city":      _extract_city(addr1),
        "lat":       _safe_float(item.get("mapy")),  # mapy = 위도(lat)
        "lng":       _safe_float(item.get("mapx")),  # mapx = 경도(lng)
    }


def _check_latlon_columns(cursor) -> bool:
    """gyeonggi_events 테이블에 lat/lng 컬럼이 있는지 확인합니다."""
    global _HAS_LATLON_COLS
    if _HAS_LATLON_COLS is not None:
        return _HAS_LATLON_COLS
    cursor.execute(
        """
        SELECT COUNT(*) FROM information_schema.columns
        WHERE table_schema = 'locallink'
          AND table_name   = 'gyeonggi_events'
          AND column_name  IN ('lat', 'lng')
        """
    )
    count = cursor.fetchone()[0]
    _HAS_LATLON_COLS = (count == 2)
    return _HAS_LATLON_COLS


def _bulk_insert(conn, rows: list[dict]) -> int:
    """rows를 TRUNCATE 후 bulk INSERT 합니다. 성공 건수 반환."""
    if not rows:
        return 0

    with conn.cursor() as cur:
        has_ll = _check_latlon_columns(cur)
        if has_ll:
            col_sql = "(inst_nm, title, begin_de, end_de, url, image_url, writng_de, city, lat, lng)"
            placeholders = "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            values = [
                (
                    r["inst_nm"], r["title"], r["begin_de"], r["end_de"],
                    r["url"], r["image_url"], r["writng_de"], r["city"],
                    r["lat"], r["lng"],
                )
                for r in rows
            ]
        else:
            logger.warning(
                "lat/lng 컬럼이 없습니다. "
                "sql/migration/Script-gyeonggi-events-lat-lng-260308.sql 을 먼저 실행하세요. "
                "좌표 없이 계속 진행합니다."
            )
            col_sql = "(inst_nm, title, begin_de, end_de, url, image_url, writng_de, city)"
            placeholders = "(%s, %s, %s, %s, %s, %s, %s, %s)"
            values = [
                (
                    r["inst_nm"], r["title"], r["begin_de"], r["end_de"],
                    r["url"], r["image_url"], r["writng_de"], r["city"],
                )
                for r in rows
            ]

        cur.execute(f"TRUNCATE {TABLE}")
        from psycopg2.extras import execute_batch
        execute_batch(
            cur,
            f"INSERT INTO {TABLE} {col_sql} VALUES {placeholders}",
            values,
            page_size=500,
        )
        conn.commit()
        return len(values)


def fetch_all_events(service_key: str, event_start_date: str) -> list[dict]:
    """경기도 행사 전체 페이지를 수집해 row dict 목록을 반환합니다."""
    all_rows: list[dict] = []
    total_count = None

    for page in range(1, MAX_PAGES + 1):
        logger.info("페이지 %d 요청 중...", page)
        try:
            data = _fetch_page(service_key, page, event_start_date)
        except requests.HTTPError as e:
            logger.error("API 요청 실패: %s", e)
            break

        items, tc = _parse_items(data)
        if total_count is None:
            total_count = tc
            logger.info("전체 행사 건수: %d건", total_count)

        if not items:
            logger.info("마지막 페이지 도달 (page=%d)", page)
            break

        all_rows.extend(_item_to_row(item) for item in items)
        logger.info("  → 누적 %d건 수집", len(all_rows))

        if len(all_rows) >= (total_count or 0):
            break

        time.sleep(0.3)  # API 과부하 방지

    return all_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="TourAPI 4.0 경기도 행사 수집 및 DB 적재")
    parser.add_argument(
        "--start",
        default=date.today().strftime("%Y%m%d"),
        help="행사 시작일 필터 (YYYYMMDD, 기본값: 오늘). "
             "과거 행사 포함 시 예: --start 20250101",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB 적재 없이 수집 결과만 출력",
    )
    args = parser.parse_args()

    logger.info("TourAPI 경기도 행사 수집 시작 (eventStartDate=%s)", args.start)

    service_key = _get_api_key()
    rows = fetch_all_events(service_key, args.start)

    if not rows:
        logger.warning("수집된 행사 데이터가 없습니다.")
        sys.exit(0)

    # city 분포 요약
    city_counts: dict[str, int] = {}
    for r in rows:
        city_counts[r["city"]] = city_counts.get(r["city"], 0) + 1
    logger.info(
        "city 분포: %s",
        ", ".join(f"{c}:{n}" for c, n in sorted(city_counts.items(), key=lambda x: -x[1])[:10]),
    )

    if args.dry_run:
        logger.info("[dry-run] DB 미적재. 샘플 3건:")
        for r in rows[:3]:
            logger.info("  %s", r)
        sys.exit(0)

    try:
        from config.vault_manager import get_vault_manager
        conn = get_vault_manager().get_db_connection()
        with conn:
            inserted = _bulk_insert(conn, rows)
        conn.close()
        logger.info("완료: %d건 적재 (TRUNCATE 후 전체 재삽입)", inserted)
    except Exception as e:
        logger.error("DB 적재 실패: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
