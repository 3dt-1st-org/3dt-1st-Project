#!/usr/bin/env python
"""Free city enrichment for event rows (no external paid API).

This script extracts Gyeonggi city/county from local text only.
Inputs are event title and optional context columns (e.g. inst_nm, content).
"""

from __future__ import annotations

import argparse
import re
from typing import Any

try:
    import psycopg
    from psycopg import sql

    def db_connect(dsn: str):
        return psycopg.connect(dsn)

except ModuleNotFoundError:
    import psycopg2 as psycopg
    from psycopg2 import sql

    def db_connect(dsn: str):
        return psycopg.connect(dsn)


GYEONGGI_CITIES = [
    "수원시",
    "성남시",
    "고양시",
    "용인시",
    "부천시",
    "안산시",
    "안양시",
    "남양주시",
    "화성시",
    "평택시",
    "의정부시",
    "시흥시",
    "파주시",
    "광명시",
    "김포시",
    "군포시",
    "광주시",
    "이천시",
    "양주시",
    "오산시",
    "구리시",
    "안성시",
    "포천시",
    "의왕시",
    "하남시",
    "여주시",
    "양평군",
    "동두천시",
    "과천시",
    "가평군",
    "연천군",
]

CITY_ALIASES = {
    "수원": "수원시",
    "성남": "성남시",
    "고양": "고양시",
    "용인": "용인시",
    "부천": "부천시",
    "안산": "안산시",
    "안양": "안양시",
    "남양주": "남양주시",
    "화성": "화성시",
    "평택": "평택시",
    "의정부": "의정부시",
    "시흥": "시흥시",
    "파주": "파주시",
    "광명": "광명시",
    "김포": "김포시",
    "군포": "군포시",
    "광주": "광주시",
    "이천": "이천시",
    "양주": "양주시",
    "오산": "오산시",
    "구리": "구리시",
    "안성": "안성시",
    "포천": "포천시",
    "의왕": "의왕시",
    "하남": "하남시",
    "여주": "여주시",
    "양평": "양평군",
    "동두천": "동두천시",
    "과천": "과천시",
    "가평": "가평군",
    "연천": "연천군",
}

DISTRICT_TO_CITY = {
    "장안구": "수원시",
    "권선구": "수원시",
    "팔달구": "수원시",
    "영통구": "수원시",
    "분당구": "성남시",
    "수정구": "성남시",
    "중원구": "성남시",
    "덕양구": "고양시",
    "일산동구": "고양시",
    "일산서구": "고양시",
    "처인구": "용인시",
    "기흥구": "용인시",
    "수지구": "용인시",
    "상록구": "안산시",
    "단원구": "안산시",
    "동안구": "안양시",
    "만안구": "안양시",
}

LANDMARK_TO_CITY = {
    "한국민속촌": "용인시",
    "에버랜드": "용인시",
    "화성행궁": "수원시",
    "광교": "수원시",
    "아주대": "수원시",
    "경기도박물관": "용인시",
    "백남준아트센터": "용인시",
}

CITY_PATTERN = re.compile(
    "|".join(re.escape(name) for name in sorted(GYEONGGI_CITIES, key=len, reverse=True))
)
ALIAS_PATTERN = re.compile(
    "|".join(re.escape(name) for name in sorted(CITY_ALIASES.keys(), key=len, reverse=True))
)
DISTRICT_PATTERN = re.compile(
    "|".join(re.escape(name) for name in sorted(DISTRICT_TO_CITY.keys(), key=len, reverse=True))
)
LANDMARK_PATTERN = re.compile(
    "|".join(re.escape(name) for name in sorted(LANDMARK_TO_CITY.keys(), key=len, reverse=True))
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Free city enrichment from local text")
    parser.add_argument("--db-dsn", required=True, help="PostgreSQL DSN")
    parser.add_argument("--schema", default="locallink", help="Target schema")
    parser.add_argument("--table", default="gyeonggi_events", help="Target table")
    parser.add_argument("--id-col", default="id", help="Primary key column")
    parser.add_argument("--title-col", default="title", help="Title column")
    parser.add_argument("--city-col", default="city", help="City column to update")
    parser.add_argument(
        "--context-cols",
        default="",
        help="Comma-separated extra text columns, e.g. inst_nm,content",
    )
    parser.add_argument(
        "--where",
        default="coalesce(nullif(trim(city), ''), '기타') = '기타'",
        help="Filter condition for rows to enrich",
    )
    parser.add_argument("--limit", type=int, default=200, help="Max rows to process")
    parser.add_argument("--dry-run", action="store_true", help="Only print results")
    return parser.parse_args()


def fetch_targets(
    conn: Any,
    schema: str,
    table: str,
    id_col: str,
    title_col: str,
    context_cols: list[str],
    where_sql: str,
    limit: int,
) -> list[tuple[Any, str, str]]:
    select_cols = [sql.Identifier(id_col), sql.Identifier(title_col)] + [
        sql.Identifier(c) for c in context_cols
    ]

    query = sql.SQL(
        """
        SELECT {select_cols}
        FROM {schema}.{table}
        WHERE {where_sql}
        ORDER BY {id_col}
        LIMIT %s
        """
    ).format(
        select_cols=sql.SQL(", ").join(select_cols),
        schema=sql.Identifier(schema),
        table=sql.Identifier(table),
        where_sql=sql.SQL(where_sql),
        id_col=sql.Identifier(id_col),
    )

    rows: list[tuple[Any, str, str]] = []
    with conn.cursor() as cur:
        cur.execute(query, (limit,))
        for row in cur.fetchall():
            row_id = row[0]
            title = str(row[1] or "")
            extras = " ".join(str(v) for v in row[2:] if v)
            combined = f"{title} {extras}".strip()
            rows.append((row_id, title, combined))
    return rows


def pick_most_frequent(candidates: list[str]) -> str | None:
    if not candidates:
        return None
    counts: dict[str, int] = {}
    for c in candidates:
        counts[c] = counts.get(c, 0) + 1
    return max(counts.items(), key=lambda x: x[1])[0]


def extract_city(text: str) -> str | None:
    if not text:
        return None

    direct = CITY_PATTERN.findall(text)
    if direct:
        return pick_most_frequent(direct)

    alias_matches = [CITY_ALIASES[a] for a in ALIAS_PATTERN.findall(text)]
    if alias_matches:
        return pick_most_frequent(alias_matches)

    district_matches = [DISTRICT_TO_CITY[d] for d in DISTRICT_PATTERN.findall(text)]
    if district_matches:
        return pick_most_frequent(district_matches)

    landmark_matches = [LANDMARK_TO_CITY[m] for m in LANDMARK_PATTERN.findall(text)]
    if landmark_matches:
        return pick_most_frequent(landmark_matches)

    return None


def update_city(
    conn: Any,
    schema: str,
    table: str,
    id_col: str,
    city_col: str,
    updates: list[tuple[str, Any]],
) -> int:
    query = sql.SQL(
        """
        UPDATE {schema}.{table}
        SET {city_col} = %s
        WHERE {id_col} = %s
        """
    ).format(
        schema=sql.Identifier(schema),
        table=sql.Identifier(table),
        city_col=sql.Identifier(city_col),
        id_col=sql.Identifier(id_col),
    )

    updated = 0
    with conn.cursor() as cur:
        for city, row_id in updates:
            cur.execute(query, (city, row_id))
            updated += cur.rowcount
    conn.commit()
    return updated


def main() -> None:
    args = parse_args()
    context_cols = [c.strip() for c in args.context_cols.split(",") if c.strip()]

    with db_connect(args.db_dsn) as conn:
        targets = fetch_targets(
            conn=conn,
            schema=args.schema,
            table=args.table,
            id_col=args.id_col,
            title_col=args.title_col,
            context_cols=context_cols,
            where_sql=args.where,
            limit=args.limit,
        )

        if not targets:
            print("No target rows found")
            return

        updates: list[tuple[str, Any]] = []
        unresolved = 0

        for row_id, title, combined_text in targets:
            city = extract_city(combined_text)
            if city:
                updates.append((city, row_id))
                print(f"[ok] id={row_id} city={city} title={title}")
            else:
                unresolved += 1
                print(f"[unresolved] id={row_id} title={title}")

        if args.dry_run:
            print(
                f"Dry run done. matched={len(updates)} unresolved={unresolved} checked={len(targets)}"
            )
            return

        updated = update_city(
            conn=conn,
            schema=args.schema,
            table=args.table,
            id_col=args.id_col,
            city_col=args.city_col,
            updates=updates,
        )

    print(
        f"Done. updated_rows={updated}, unresolved={unresolved}, checked_rows={len(targets)}"
    )


if __name__ == "__main__":
    main()
