import logging
import os
import subprocess
from pathlib import Path


LOG = logging.getLogger("daangn-bootstrap")


def _load_env() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _run(cmd: list[str], cwd: Path, stdin_text: str | None = None) -> None:
    LOG.info("RUN: %s", " ".join(cmd))
    completed = subprocess.run(
        cmd,
        cwd=str(cwd),
        input=stdin_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.stdout:
        LOG.info(completed.stdout.strip())
    if completed.stderr:
        LOG.warning(completed.stderr.strip())

    if completed.returncode != 0:
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(cmd)}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    _load_env()

    root_dir = Path(__file__).resolve().parents[2]
    db_container = os.getenv("DB_CONTAINER", "geo-ai-db")
    postgres_user = os.getenv("POSTGRES_USER", "admin_user")
    postgres_db = os.getenv("POSTGRES_DB", "postgres")
    db_dsn = os.getenv("DB_DSN")

    if not db_dsn:
        raise RuntimeError("DB_DSN is required (.env or environment variable).")

    LOG.info("[1/5] Start local DB container")
    _run(["docker", "compose", "-f", "infra/docker/docker-compose.yml", "up", "-d", "db"], root_dir)

    LOG.info("[2/5] Apply schema SQL")
    schema_sql = (root_dir / "sql/ddl/daangn_community_tables.sql").read_text(encoding="utf-8")
    _run(
        ["docker", "exec", "-i", db_container, "psql", "-U", postgres_user, "-d", postgres_db],
        root_dir,
        stdin_text=schema_sql,
    )

    LOG.info("[3/5] Apply target dongs seed SQL")
    seed_sql = (root_dir / "sql/dml/daangn_target_dongs_seed.sql").read_text(encoding="utf-8")
    _run(
        ["docker", "exec", "-i", db_container, "psql", "-U", postgres_user, "-d", postgres_db],
        root_dir,
        stdin_text=seed_sql,
    )

    LOG.info("[4/5] Run one-time crawler")
    _run(["./.venv/bin/python", "scripts/ingest/run_daangn_crawl_once.py"], root_dir)

    LOG.info("[5/5] Verify inserted rows")
    _run(
        [
            "docker",
            "exec",
            "-i",
            db_container,
            "psql",
            "-U",
            postgres_user,
            "-d",
            postgres_db,
            "-c",
            "SELECT COUNT(*) AS post_cnt FROM daangn.community_posts WHERE source_url LIKE 'https://www.daangn.com/kr/community/%' AND source_url <> 'https://www.daangn.com/kr/community';",
            "-c",
            "SELECT COUNT(*) AS comment_cnt FROM daangn.community_comments WHERE comment_key NOT LIKE 'comment_key_smoke_%';",
            "-c",
            "SELECT p.city_name, p.dong_name, p.title, left(c.comment_body,80) AS comment_sample FROM daangn.community_comments c JOIN daangn.community_posts p ON p.post_key = c.post_key ORDER BY c.id DESC LIMIT 5;",
        ],
        root_dir,
    )


if __name__ == "__main__":
    main()
