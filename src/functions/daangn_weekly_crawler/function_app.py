import hashlib
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import azure.functions as func
import psycopg
import requests
from bs4 import BeautifulSoup

LOGGER = logging.getLogger("daangn-weekly-crawler")
APP = func.FunctionApp()

DEFAULT_SCHEDULE = os.getenv("TIMER_CRON", "0 0 3 * * 1")
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "15"))
REQUEST_SLEEP_SECONDS = float(os.getenv("REQUEST_SLEEP_SECONDS", "0.3"))


@dataclass(frozen=True)
class TargetDong:
    city_name: str
    dong_name: str
    dong_slug: str


def _normalize_url(url: str) -> str:
    return url.split("?")[0].rstrip("/")


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_keywords() -> list[str]:
    raw = os.getenv("DAANGN_KEYWORDS", "맛집,명소,행사")
    return [token.strip() for token in raw.split(",") if token.strip()]


def _request_html(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.text


def _extract_post_links(search_html: str) -> list[str]:
    soup = BeautifulSoup(search_html, "html.parser")
    links: set[str] = set()

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "")
        if "/kr/community/" not in href:
            continue
        if "/kr/community/s/" in href:
            continue

        if href.startswith("http"):
            url = href
        else:
            url = f"https://www.daangn.com{href}"

        links.add(_normalize_url(url))

    return sorted(links)


def _extract_text_by_selectors(soup: BeautifulSoup, selectors: Iterable[str]) -> str:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            text = node.get_text(" ", strip=True)
            if text:
                return text
    return ""


def _extract_comments(soup: BeautifulSoup) -> list[str]:
    selectors = [
        "[data-qa-id='comment-content']",
        "article section li p",
        "section li div",
    ]

    comments: list[str] = []
    seen: set[str] = set()
    for selector in selectors:
        for node in soup.select(selector):
            text = node.get_text(" ", strip=True)
            if not text or len(text) < 2:
                continue
            if text in seen:
                continue
            seen.add(text)
            comments.append(text)

        if comments:
            break

    return comments


def _extract_post_payload(post_html: str) -> tuple[str, str, list[str]]:
    soup = BeautifulSoup(post_html, "html.parser")

    title = _extract_text_by_selectors(
        soup,
        [
            "h1",
            "[data-qa-id='article-title']",
            "main h1",
        ],
    )
    body = _extract_text_by_selectors(
        soup,
        [
            "[data-qa-id='article-content']",
            "article",
            "main",
        ],
    )
    comments = _extract_comments(soup)

    return title, body, comments


def _load_target_dongs(conn: psycopg.Connection) -> list[TargetDong]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT city_name, dong_name, dong_slug
            FROM daangn.target_dongs
            WHERE is_active = TRUE
              AND dong_slug IS NOT NULL
            ORDER BY city_name, dong_name
            """
        )
        rows = cur.fetchall()

    return [TargetDong(city_name=row[0], dong_name=row[1], dong_slug=row[2]) for row in rows]


def _insert_run_start(conn: psycopg.Connection) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO daangn.crawl_runs (status)
            VALUES ('running')
            RETURNING run_id
            """
        )
        run_id = cur.fetchone()[0]
    conn.commit()
    return str(run_id)


def _finish_run(
    conn: psycopg.Connection,
    run_id: str,
    status: str,
    post_count: int,
    comment_count: int,
    error_message: str | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE daangn.crawl_runs
            SET finished_at = NOW(),
                status = %s,
                post_count = %s,
                comment_count = %s,
                error_message = %s
            WHERE run_id = %s::uuid
            """,
            (status, post_count, comment_count, error_message, run_id),
        )
    conn.commit()


def _upsert_post(
    conn: psycopg.Connection,
    post_key: str,
    source_url: str,
    title: str,
    body: str,
    city_name: str,
    dong_name: str,
    searched_keyword: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO daangn.community_posts (
                post_key,
                source_url,
                title,
                body,
                city_name,
                dong_name,
                searched_keyword,
                post_created_at,
                raw_payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, NULL)
            ON CONFLICT (post_key)
            DO UPDATE SET
                title = EXCLUDED.title,
                body = EXCLUDED.body,
                city_name = EXCLUDED.city_name,
                dong_name = EXCLUDED.dong_name,
                searched_keyword = EXCLUDED.searched_keyword,
                crawled_at = NOW()
            """,
            (post_key, source_url, title, body, city_name, dong_name, searched_keyword),
        )


def _insert_comments(
    conn: psycopg.Connection,
    post_key: str,
    comments: list[str],
    city_name: str,
    dong_name: str,
) -> int:
    inserted = 0
    with conn.cursor() as cur:
        for comment in comments:
            comment_key = _hash_key(f"{post_key}:{comment.strip()}")
            cur.execute(
                """
                INSERT INTO daangn.community_comments (
                    comment_key,
                    post_key,
                    comment_body,
                    city_name,
                    dong_name,
                    commented_at,
                    raw_payload
                )
                VALUES (%s, %s, %s, %s, %s, NULL, NULL)
                ON CONFLICT (comment_key) DO NOTHING
                """,
                (comment_key, post_key, comment, city_name, dong_name),
            )
            inserted += cur.rowcount

    return inserted


def _crawl_once(conn: psycopg.Connection) -> tuple[int, int]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": os.getenv(
                "DAANGN_USER_AGENT",
                "Mozilla/5.0 (compatible; LocalLinkBot/1.0; +https://example.com)",
            )
        }
    )

    total_posts = 0
    total_comments = 0

    keywords = _get_keywords()
    max_posts_per_dong = int(os.getenv("MAX_POSTS_PER_DONG", "30"))

    target_dongs = _load_target_dongs(conn)
    LOGGER.info("Loaded %d active target dongs.", len(target_dongs))

    for target in target_dongs:
        for keyword in keywords:
            search_url = (
                "https://www.daangn.com/kr/community/s/"
                f"?in={target.dong_slug}&search={keyword}"
            )

            try:
                search_html = _request_html(session, search_url)
            except Exception as exc:
                LOGGER.warning("Search request failed for %s: %s", search_url, exc)
                continue

            post_links = _extract_post_links(search_html)[:max_posts_per_dong]
            LOGGER.info(
                "Target %s/%s keyword=%s links=%d",
                target.city_name,
                target.dong_name,
                keyword,
                len(post_links),
            )

            for post_url in post_links:
                try:
                    post_html = _request_html(session, post_url)
                    title, body, comments = _extract_post_payload(post_html)
                    if not title and not body:
                        continue

                    post_key = _hash_key(_normalize_url(post_url))
                    _upsert_post(
                        conn=conn,
                        post_key=post_key,
                        source_url=post_url,
                        title=title or "(no-title)",
                        body=body,
                        city_name=target.city_name,
                        dong_name=target.dong_name,
                        searched_keyword=keyword,
                    )
                    total_posts += 1
                    total_comments += _insert_comments(
                        conn=conn,
                        post_key=post_key,
                        comments=comments,
                        city_name=target.city_name,
                        dong_name=target.dong_name,
                    )
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    LOGGER.warning("Failed to process %s: %s", post_url, exc)
                time.sleep(REQUEST_SLEEP_SECONDS)

    return total_posts, total_comments


@APP.schedule(
    schedule=DEFAULT_SCHEDULE,
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def daangn_weekly_crawler(timer: func.TimerRequest) -> None:
    _ = timer
    started_at = datetime.now(timezone.utc).isoformat()
    LOGGER.info("Daangn weekly crawler started at %s", started_at)

    db_dsn = os.getenv("DB_DSN")
    if not db_dsn:
        raise RuntimeError("DB_DSN is required.")

    with psycopg.connect(db_dsn) as conn:
        run_id = _insert_run_start(conn)
        post_count = 0
        comment_count = 0

        try:
            post_count, comment_count = _crawl_once(conn)
            _finish_run(
                conn=conn,
                run_id=run_id,
                status="success",
                post_count=post_count,
                comment_count=comment_count,
                error_message=None,
            )
        except Exception as exc:
            conn.rollback()
            _finish_run(
                conn=conn,
                run_id=run_id,
                status="failed",
                post_count=post_count,
                comment_count=comment_count,
                error_message=str(exc)[:1000],
            )
            raise

    LOGGER.info(
        "Daangn weekly crawler completed. posts=%d comments=%d",
        post_count,
        comment_count,
    )
