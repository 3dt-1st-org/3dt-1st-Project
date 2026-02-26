import importlib.util
import os
from pathlib import Path


def _load_function_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "functions"
        / "daangn_weekly_crawler"
        / "function_app.py"
    )
    spec = importlib.util.spec_from_file_location("daangn_function_app", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load function_app module")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    db_dsn = os.getenv("DB_DSN")
    if not db_dsn:
        raise RuntimeError("DB_DSN environment variable is required")

    limit = int(os.getenv("BACKFILL_LIMIT", "200"))
    app_module = _load_function_module()

    filled = 0
    attempted = 0

    with app_module.psycopg.connect(db_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT post_key, source_url
                FROM daangn.community_posts
                WHERE post_created_at IS NULL
                  AND source_url LIKE 'https://www.daangn.com/kr/community/%%'
                  AND source_url <> 'https://www.daangn.com/kr/community'
                ORDER BY id DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

        session = app_module.requests.Session()
        session.headers.update(
            {
                "User-Agent": os.getenv(
                    "DAANGN_USER_AGENT",
                    "Mozilla/5.0 (compatible; LocalLinkBot/1.0; +https://example.com)",
                )
            }
        )

        for post_key, source_url in rows:
            attempted += 1
            try:
                html = app_module._request_html(session, source_url)
                _title, _body, post_created_at, _comments = app_module._extract_post_payload(html)
                if not post_created_at:
                    continue

                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE daangn.community_posts
                        SET post_created_at = %s,
                            crawled_at = NOW()
                        WHERE post_key = %s
                          AND post_created_at IS NULL
                        """,
                        (post_created_at, post_key),
                    )
                    filled += cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()

    print(f"attempted={attempted}")
    print(f"filled={filled}")


if __name__ == "__main__":
    main()
