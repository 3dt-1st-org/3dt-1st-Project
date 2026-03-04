import base64
import hashlib
import json
import logging
import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

import azure.functions as func
import psycopg
import requests
from bs4 import BeautifulSoup

LOGGER = logging.getLogger("daangn-weekly-crawler")
APP = func.FunctionApp()

DEFAULT_SCHEDULE = os.getenv("TIMER_CRON", "0 0 3 * * 1")
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "15"))
REQUEST_SLEEP_SECONDS = float(os.getenv("REQUEST_SLEEP_SECONDS", "0.3"))
TASK_QUEUE_NAME = os.getenv("DAANGN_TASK_QUEUE", "daangn-crawl-tasks")
MENTION_AGGREGATION_CRON = os.getenv("MENTION_AGGREGATION_CRON", "0 30 3 * * 1")
MENTION_LOOKBACK_DAYS = int(os.getenv("MENTION_LOOKBACK_DAYS", "7"))
NOISE_EXACT_MATCHES = {
    ",",
    ".",
    "..",
    "...",
    "ㅋ",
    "ㅋㅋ",
    "ㅋㅋㅋ",
    "ㅎ",
    "ㅎㅎ",
    "ㅠ",
    "ㅠㅠ",
    "ㅜ",
    "ㅜㅜ",
}
PLACE_SUFFIX_PATTERN = re.compile(
    r"([가-힣A-Za-z0-9][가-힣A-Za-z0-9\s]{1,28})\s*(?:이라는|라는|인)?\s*(맛집|식당|카페|횟집|명소|축제|행사)"
)
PLACE_NAME_PATTERN = re.compile(
    r"(?:추천|가볼만|방문|다녀옴|다녀왔어요|좋아요)\s*(?:장소|곳)?\s*[:\-]?\s*([가-힣A-Za-z0-9][가-힣A-Za-z0-9\s]{1,28})"
)
CATEGORY_RESTAURANT_HINTS = ("맛집", "식당", "카페", "횟집", "음식점", "먹자", "점심", "저녁")
CATEGORY_EVENT_HINTS = ("행사", "축제", "박람회", "공연", "페스티벌", "플리마켓", "전시")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _elapsed_ms(started_at: datetime) -> int:
    return int((_utc_now() - started_at).total_seconds() * 1000)


@dataclass(frozen=True)
class TargetDong:
    city_name: str
    dong_name: str
    dong_slug: str


@dataclass(frozen=True)
class CrawlTask:
    task_id: str
    run_id: str
    city_name: str
    dong_name: str
    dong_slug: str
    keyword: str


@dataclass(frozen=True)
class CommunityText:
    city_name: str
    text: str
    category_hint: str


def _normalize_url(url: str) -> str:
    return url.split("?")[0].rstrip("/")


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _is_noise_comment(comment_text: str) -> bool:
    text = comment_text.strip()
    if not text:
        return True
    if text in NOISE_EXACT_MATCHES:
        return True

    # Keep only comments that contain at least one meaningful character.
    return re.search(r"[0-9A-Za-z가-힣]", text) is None


def _get_keywords() -> list[str]:
    raw = os.getenv("DAANGN_KEYWORDS", "맛집,명소,행사")
    return [token.strip() for token in raw.split(",") if token.strip()]


def _normalize_place_name(raw: str) -> str:
    text = re.sub(r"\s+", " ", raw).strip()
    text = re.sub(r"[\"'`<>\\[\\](){}]", "", text)
    text = re.sub(r"^.*(?:에|에서|근처|부근|쪽)\s+", "", text)
    text = re.sub(r"\s*(이라는|라는|인)$", "", text).strip()
    text = re.sub(r"(입니다|이에요|네요|요)$", "", text).strip()
    return text


def _categorize_text(text: str, category_hint: str) -> str:
    merged = f"{category_hint} {text}"
    if any(keyword in merged for keyword in CATEGORY_EVENT_HINTS):
        return "행사"
    if any(keyword in merged for keyword in CATEGORY_RESTAURANT_HINTS):
        return "맛집"
    return "명소"


def _extract_places_from_text(text: str) -> list[str]:
    candidates: list[str] = []
    for match in PLACE_SUFFIX_PATTERN.finditer(text):
        candidates.append(match.group(1))
    for match in PLACE_NAME_PATTERN.finditer(text):
        candidates.append(match.group(1))

    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        name = _normalize_place_name(candidate)
        if len(name) < 2 or len(name) > 30:
            continue
        if name.lower() in {"저기", "여기", "거기", "이곳", "그곳"}:
            continue
        if name in seen:
            continue
        seen.add(name)
        normalized.append(name)
    return normalized


def _request_html(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.content.decode("utf-8", errors="replace")


def _extract_post_links(search_html: str) -> list[str]:
    soup = BeautifulSoup(search_html, "html.parser")
    links: set[str] = set()

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "")
        if "/kr/community/" not in href:
            continue
        if "/kr/community/s/" in href:
            continue
        if href.rstrip("/") == "/kr/community":
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


def _extract_comments_from_inline_json(post_html: str) -> list[dict[str, Any]]:
    pattern = re.compile(
        r'"createdSortedComments":(\[.*?\]),"recentSortedComments":',
        re.DOTALL,
    )
    match = pattern.search(post_html)
    if not match:
        return []

    try:
        comments_data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []

    def flatten(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = []
        for item in items:
            content = (item.get("content") or "").strip()
            if content:
                parsed.append(
                    {
                        "comment_id": str(item.get("id") or ""),
                        "content": content,
                        "created_at": item.get("createdAt"),
                    }
                )

            sub_items = item.get("subComments") or []
            if isinstance(sub_items, list) and sub_items:
                parsed.extend(flatten(sub_items))
        return parsed

    return flatten(comments_data)


def _extract_post_payload(post_html: str) -> tuple[str, str, Optional[str], list[dict[str, Any]]]:
    pattern = re.compile(
        r'"title":"((?:\\.|[^"\\])*)","content":"((?:\\.|[^"\\])*)","status":"NORMAL","createdAt":"([^"]+)"',
        re.DOTALL,
    )
    match = pattern.search(post_html)
    comments_from_json = _extract_comments_from_inline_json(post_html)

    if match:
        title = json.loads(f'"{match.group(1)}"')
        body = json.loads(f'"{match.group(2)}"')
        post_created_at = match.group(3)
        return title, body, post_created_at, comments_from_json

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
    comments = comments_from_json
    if not comments:
        comments = [{"comment_id": "", "content": c, "created_at": None} for c in _extract_comments(soup)]

    return title, body, None, comments


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
    error_message: Optional[str],
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


def _create_crawl_task(
    conn: psycopg.Connection,
    run_id: str,
    target: TargetDong,
    keyword: str,
) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO daangn.crawl_tasks (
                run_id,
                city_name,
                dong_name,
                dong_slug,
                keyword,
                status
            )
            VALUES (%s::uuid, %s, %s, %s, %s, 'pending')
            RETURNING task_id
            """,
            (run_id, target.city_name, target.dong_name, target.dong_slug, keyword),
        )
        task_id = cur.fetchone()[0]
    conn.commit()
    return str(task_id)


def _load_task(conn: psycopg.Connection, task_id: str) -> Optional[CrawlTask]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                task_id::text,
                run_id::text,
                city_name,
                dong_name,
                dong_slug,
                keyword
            FROM daangn.crawl_tasks
            WHERE task_id = %s::uuid
            """,
            (task_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return CrawlTask(
        task_id=row[0],
        run_id=row[1],
        city_name=row[2],
        dong_name=row[3],
        dong_slug=row[4],
        keyword=row[5],
    )


def _load_task_status(conn: psycopg.Connection, task_id: str) -> Optional[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT status
            FROM daangn.crawl_tasks
            WHERE task_id = %s::uuid
            """,
            (task_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return str(row[0])


def _mark_task_running(conn: psycopg.Connection, task_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE daangn.crawl_tasks
            SET status = 'running',
                attempts = attempts + 1,
                started_at = NOW(),
                updated_at = NOW()
            WHERE task_id = %s::uuid
            """,
            (task_id,),
        )
    conn.commit()


def _mark_task_success(conn: psycopg.Connection, task_id: str, post_count: int, comment_count: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE daangn.crawl_tasks
            SET status = 'success',
                post_count = %s,
                comment_count = %s,
                finished_at = NOW(),
                updated_at = NOW(),
                error_message = NULL
            WHERE task_id = %s::uuid
            """,
            (post_count, comment_count, task_id),
        )
    conn.commit()


def _mark_task_failed(conn: psycopg.Connection, task_id: str, error_message: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE daangn.crawl_tasks
            SET status = 'failed',
                finished_at = NOW(),
                updated_at = NOW(),
                error_message = %s
            WHERE task_id = %s::uuid
            """,
            (error_message[:1000], task_id),
        )
    conn.commit()


def _refresh_run_status(conn: psycopg.Connection, run_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) AS total_tasks,
                COUNT(*) FILTER (WHERE status IN ('success', 'failed')) AS finished_tasks,
                COUNT(*) FILTER (WHERE status = 'failed') AS failed_tasks,
                COALESCE(SUM(post_count) FILTER (WHERE status = 'success'), 0) AS post_count,
                COALESCE(SUM(comment_count) FILTER (WHERE status = 'success'), 0) AS comment_count
            FROM daangn.crawl_tasks
            WHERE run_id = %s::uuid
            """,
            (run_id,),
        )
        row = cur.fetchone()

        total_tasks = int(row[0] or 0)
        finished_tasks = int(row[1] or 0)
        failed_tasks = int(row[2] or 0)
        post_count = int(row[3] or 0)
        comment_count = int(row[4] or 0)

        if total_tasks == 0:
            cur.execute(
                """
                UPDATE daangn.crawl_runs
                SET status = 'success',
                    finished_at = NOW(),
                    post_count = 0,
                    comment_count = 0,
                    error_message = NULL
                WHERE run_id = %s::uuid
                """,
                (run_id,),
            )
        elif finished_tasks >= total_tasks:
            status = "failed" if failed_tasks > 0 else "success"
            error_message = f"{failed_tasks} task(s) failed" if failed_tasks > 0 else None
            cur.execute(
                """
                UPDATE daangn.crawl_runs
                SET status = %s,
                    finished_at = NOW(),
                    post_count = %s,
                    comment_count = %s,
                    error_message = %s
                WHERE run_id = %s::uuid
                """,
                (status, post_count, comment_count, error_message, run_id),
            )
        else:
            cur.execute(
                """
                UPDATE daangn.crawl_runs
                SET status = 'running',
                    post_count = %s,
                    comment_count = %s
                WHERE run_id = %s::uuid
                """,
                (post_count, comment_count, run_id),
            )
    conn.commit()


def _enqueue_task_message(task_id: str, run_id: str) -> None:
    connection_string = os.getenv("AzureWebJobsStorage")
    if not connection_string:
        raise RuntimeError("AzureWebJobsStorage is required to enqueue crawl tasks.")

    # Imported lazily so local unit tests that mock azure.functions do not require queue SDK.
    from azure.storage.queue import QueueClient  # type: ignore

    queue_client = QueueClient.from_connection_string(connection_string, TASK_QUEUE_NAME)
    try:
        queue_client.create_queue()
    except Exception:
        pass

    raw_payload = json.dumps({"task_id": task_id, "run_id": run_id})
    encoded_payload = base64.b64encode(raw_payload.encode("utf-8")).decode("utf-8")
    queue_client.send_message(encoded_payload)


def _decode_queue_body(message: func.QueueMessage) -> dict[str, Any]:
    payload = message.get_body()
    if isinstance(payload, bytes):
        raw = payload.decode("utf-8", errors="replace")
    else:
        raw = str(payload)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        decoded_raw = base64.b64decode(raw).decode("utf-8", errors="replace")
        data = json.loads(decoded_raw)
    if not isinstance(data, dict):
        raise ValueError("Queue payload must be a JSON object.")
    return data


def _get_week_start_utc(now: datetime) -> date:
    current = now.date()
    return current - timedelta(days=current.weekday())


def _load_recent_community_texts(conn: psycopg.Connection, lookback_days: int) -> list[CommunityText]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT city_name, title || ' ' || COALESCE(body, ''), searched_keyword
            FROM daangn.community_posts
            WHERE COALESCE(post_created_at, crawled_at) >= NOW() - (%s::int * INTERVAL '1 day')

            UNION ALL

            SELECT city_name, comment_body, ''
            FROM daangn.community_comments
            WHERE COALESCE(commented_at, crawled_at) >= NOW() - (%s::int * INTERVAL '1 day')
            """,
            (lookback_days, lookback_days),
        )
        rows = cur.fetchall()

    return [
        CommunityText(
            city_name=str(row[0]),
            text=str(row[1] or "").strip(),
            category_hint=str(row[2] or "").strip(),
        )
        for row in rows
        if str(row[1] or "").strip()
    ]


def _aggregate_place_mentions(
    rows: list[CommunityText],
) -> Counter[tuple[str, str, str]]:
    counter: Counter[tuple[str, str, str]] = Counter()
    for row in rows:
        category = _categorize_text(row.text, row.category_hint)
        places = _extract_places_from_text(row.text)
        for place_name in places:
            counter[(place_name, category, row.city_name)] += 1
    return counter


def _upsert_place_mentions_weekly(
    conn: psycopg.Connection,
    week_start: date,
    mention_counter: Counter[tuple[str, str, str]],
) -> int:
    affected = 0
    with conn.cursor() as cur:
        for (place_name, category, city_name), mention_count in mention_counter.items():
            cur.execute(
                """
                INSERT INTO daangn.place_mentions_weekly (
                    place_name,
                    category,
                    city_name,
                    mention_count,
                    week_start
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (place_name, category, city_name, week_start)
                DO UPDATE SET
                    mention_count = EXCLUDED.mention_count,
                    updated_at = NOW()
                """,
                (place_name, category, city_name, int(mention_count), week_start),
            )
            affected += cur.rowcount
    conn.commit()
    return affected


def _upsert_post(
    conn: psycopg.Connection,
    post_key: str,
    source_url: str,
    title: str,
    body: str,
    post_created_at: Optional[str],
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
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL)
            ON CONFLICT (post_key)
            DO UPDATE SET
                title = EXCLUDED.title,
                body = EXCLUDED.body,
                city_name = EXCLUDED.city_name,
                dong_name = EXCLUDED.dong_name,
                searched_keyword = EXCLUDED.searched_keyword,
                post_created_at = COALESCE(EXCLUDED.post_created_at, daangn.community_posts.post_created_at),
                crawled_at = NOW()
            """,
            (post_key, source_url, title, body, city_name, dong_name, searched_keyword, post_created_at),
        )


def _insert_comments(
    conn: psycopg.Connection,
    post_key: str,
    comments: list[dict[str, Any]],
    city_name: str,
    dong_name: str,
) -> int:
    inserted = 0
    with conn.cursor() as cur:
        for comment in comments:
            comment_text = str(comment.get("content") or "").strip()
            if _is_noise_comment(comment_text):
                continue

            comment_id = str(comment.get("comment_id") or "").strip()
            key_source = f"{post_key}:{comment_id}" if comment_id else f"{post_key}:{comment_text}"
            comment_key = _hash_key(key_source)
            commented_at = comment.get("created_at")

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
                VALUES (%s, %s, %s, %s, %s, %s, NULL)
                ON CONFLICT (comment_key) DO NOTHING
                """,
                (comment_key, post_key, comment_text, city_name, dong_name, commented_at),
            )
            inserted += cur.rowcount

    return inserted


def _crawl_target_keyword(
    conn: psycopg.Connection,
    target: TargetDong,
    keyword: str,
    max_posts: int,
) -> tuple[int, int]:
    stage_started_at = _utc_now()
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": os.getenv(
                "DAANGN_USER_AGENT",
                "Mozilla/5.0 (compatible; LocalLinkBot/1.0; +https://example.com)",
            )
        }
    )

    search_url = (
        "https://www.daangn.com/kr/community/s/"
        f"?in={target.dong_slug}&search={keyword}"
    )

    total_posts = 0
    total_comments = 0

    try:
        search_html = _request_html(session, search_url)
    except Exception as exc:
        LOGGER.exception(
            "crawl_stage=search_failed city=%s dong=%s keyword=%s url=%s elapsed_ms=%d",
            target.city_name,
            target.dong_name,
            keyword,
            search_url,
            _elapsed_ms(stage_started_at),
        )
        return 0, 0

    post_links = _extract_post_links(search_html)[:max_posts]
    LOGGER.info(
        "crawl_stage=search_done city=%s dong=%s keyword=%s links=%d elapsed_ms=%d",
        target.city_name,
        target.dong_name,
        keyword,
        len(post_links),
        _elapsed_ms(stage_started_at),
    )

    for idx, post_url in enumerate(post_links, start=1):
        post_started_at = _utc_now()
        LOGGER.info(
            "crawl_stage=post_start city=%s dong=%s keyword=%s index=%d total=%d url=%s",
            target.city_name,
            target.dong_name,
            keyword,
            idx,
            len(post_links),
            post_url,
        )
        try:
            post_html = _request_html(session, post_url)
            title, body, post_created_at, comments = _extract_post_payload(post_html)
            if not title and not body:
                LOGGER.info(
                    "crawl_stage=post_skipped_empty city=%s dong=%s keyword=%s index=%d url=%s elapsed_ms=%d",
                    target.city_name,
                    target.dong_name,
                    keyword,
                    idx,
                    post_url,
                    _elapsed_ms(post_started_at),
                )
                continue

            post_key = _hash_key(
                f"{target.city_name}:{target.dong_name}:{_normalize_url(post_url)}"
            )
            _upsert_post(
                conn=conn,
                post_key=post_key,
                source_url=post_url,
                title=title or "(no-title)",
                body=body,
                post_created_at=post_created_at,
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
            LOGGER.info(
                "crawl_stage=post_done city=%s dong=%s keyword=%s index=%d url=%s posts_total=%d comments_total=%d elapsed_ms=%d",
                target.city_name,
                target.dong_name,
                keyword,
                idx,
                post_url,
                total_posts,
                total_comments,
                _elapsed_ms(post_started_at),
            )
        except Exception as exc:
            conn.rollback()
            LOGGER.exception(
                "crawl_stage=post_failed city=%s dong=%s keyword=%s index=%d url=%s elapsed_ms=%d",
                target.city_name,
                target.dong_name,
                keyword,
                idx,
                post_url,
                _elapsed_ms(post_started_at),
            )
        time.sleep(REQUEST_SLEEP_SECONDS)

    LOGGER.info(
        "crawl_stage=target_keyword_done city=%s dong=%s keyword=%s posts=%d comments=%d elapsed_ms=%d",
        target.city_name,
        target.dong_name,
        keyword,
        total_posts,
        total_comments,
        _elapsed_ms(stage_started_at),
    )
    return total_posts, total_comments


@APP.schedule(
    schedule=DEFAULT_SCHEDULE,
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def daangn_weekly_crawler(timer: func.TimerRequest) -> None:
    _ = timer
    started_at = _utc_now()
    LOGGER.info("run_stage=scheduler_start started_at=%s", started_at.isoformat())

    db_dsn = os.getenv("DB_DSN")
    if not db_dsn:
        raise RuntimeError("DB_DSN is required.")

    keywords = _get_keywords()
    if not keywords:
        LOGGER.warning("DAANGN_KEYWORDS is empty. Run skipped.")
        return

    with psycopg.connect(db_dsn) as conn:
        run_id = _insert_run_start(conn)
        task_count = 0
        targets = _load_target_dongs(conn)
        LOGGER.info(
            "run_stage=target_loaded run_id=%s targets=%d keywords=%d",
            run_id,
            len(targets),
            len(keywords),
        )
        for target in targets:
            for keyword in keywords:
                task_id = _create_crawl_task(conn, run_id, target, keyword)
                _enqueue_task_message(task_id=task_id, run_id=run_id)
                task_count += 1
                LOGGER.info(
                    "run_stage=task_enqueued run_id=%s task_id=%s city=%s dong=%s keyword=%s count=%d",
                    run_id,
                    task_id,
                    target.city_name,
                    target.dong_name,
                    keyword,
                    task_count,
                )

        if task_count == 0:
            _finish_run(
                conn=conn,
                run_id=run_id,
                status="success",
                post_count=0,
                comment_count=0,
                error_message=None,
            )
            LOGGER.info("No active targets. run_id=%s", run_id)
            return

    LOGGER.info(
        "run_stage=scheduler_done run_id=%s task_count=%d elapsed_ms=%d",
        run_id,
        task_count,
        _elapsed_ms(started_at),
    )


@APP.queue_trigger(
    arg_name="queue_message",
    queue_name=TASK_QUEUE_NAME,
    connection="AzureWebJobsStorage",
)
def daangn_crawl_worker(queue_message: func.QueueMessage) -> None:
    worker_started_at = _utc_now()
    db_dsn = os.getenv("DB_DSN")
    if not db_dsn:
        raise RuntimeError("DB_DSN is required.")

    payload = _decode_queue_body(queue_message)
    task_id = str(payload.get("task_id") or "").strip()
    if not task_id:
        raise RuntimeError("queue payload must include task_id")
    LOGGER.info("task_stage=worker_start task_id=%s", task_id)

    max_posts_per_dong = int(os.getenv("MAX_POSTS_PER_DONG", "5"))

    with psycopg.connect(db_dsn) as conn:
        task = _load_task(conn, task_id)
        if not task:
            LOGGER.warning("Task not found. task_id=%s", task_id)
            return

        status = _load_task_status(conn, task_id)
        if status in {"success", "failed"}:
            LOGGER.info("Task already completed. task_id=%s status=%s", task_id, status)
            _refresh_run_status(conn, task.run_id)
            return

        _mark_task_running(conn, task_id)
        LOGGER.info(
            "task_stage=running task_id=%s run_id=%s city=%s dong=%s keyword=%s",
            task_id,
            task.run_id,
            task.city_name,
            task.dong_name,
            task.keyword,
        )
        try:
            post_count, comment_count = _crawl_target_keyword(
                conn=conn,
                target=TargetDong(
                    city_name=task.city_name,
                    dong_name=task.dong_name,
                    dong_slug=task.dong_slug,
                ),
                keyword=task.keyword,
                max_posts=max_posts_per_dong,
            )
            _mark_task_success(conn, task_id, post_count, comment_count)
            LOGGER.info(
                "task_stage=success task_id=%s run_id=%s city=%s dong=%s keyword=%s posts=%d comments=%d elapsed_ms=%d",
                task_id,
                task.run_id,
                task.city_name,
                task.dong_name,
                task.keyword,
                post_count,
                comment_count,
                _elapsed_ms(worker_started_at),
            )
        except Exception as exc:
            conn.rollback()
            _mark_task_failed(conn, task_id, str(exc))
            LOGGER.exception(
                "task_stage=failed task_id=%s run_id=%s elapsed_ms=%d",
                task_id,
                task.run_id,
                _elapsed_ms(worker_started_at),
            )
        finally:
            _refresh_run_status(conn, task.run_id)
            LOGGER.info(
                "task_stage=worker_done task_id=%s run_id=%s elapsed_ms=%d",
                task_id,
                task.run_id,
                _elapsed_ms(worker_started_at),
            )


@APP.schedule(
    schedule=MENTION_AGGREGATION_CRON,
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def daangn_place_mentions_aggregator(timer: func.TimerRequest) -> None:
    _ = timer
    started_at = _utc_now()
    db_dsn = os.getenv("DB_DSN")
    if not db_dsn:
        raise RuntimeError("DB_DSN is required.")

    lookback_days = max(MENTION_LOOKBACK_DAYS, 1)
    week_start = _get_week_start_utc(started_at)
    LOGGER.info(
        "mention_stage=start week_start=%s lookback_days=%d",
        week_start.isoformat(),
        lookback_days,
    )

    with psycopg.connect(db_dsn) as conn:
        rows = _load_recent_community_texts(conn, lookback_days)
        mention_counter = _aggregate_place_mentions(rows)
        affected = _upsert_place_mentions_weekly(conn, week_start, mention_counter)

    LOGGER.info(
        "mention_stage=done week_start=%s source_rows=%d entities=%d affected_rows=%d elapsed_ms=%d",
        week_start.isoformat(),
        len(rows),
        len(mention_counter),
        affected,
        _elapsed_ms(started_at),
    )
