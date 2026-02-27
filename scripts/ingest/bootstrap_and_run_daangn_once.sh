#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DB_CONTAINER="${DB_CONTAINER:-geo-ai-db}"
DB_DSN="${DB_DSN:-}"
POSTGRES_USER="${POSTGRES_USER:-admin_user}"
POSTGRES_DB="${POSTGRES_DB:-postgres}"

if [[ -z "$DB_DSN" ]]; then
  echo "ERROR: DB_DSN is not set."
  exit 1
fi

if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  echo "ERROR: POSTGRES_PASSWORD is not set."
  exit 1
fi

cd "$ROOT_DIR"

echo "[1/5] Start local DB container"
docker compose -f infra/docker/docker-compose.yml up -d db

echo "[2/5] Apply schema SQL"
cat sql/ddl/daangn_community_tables.sql | docker exec -i "$DB_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null

echo "[3/5] Apply target dongs seed SQL"
cat sql/dml/daangn_target_dongs_seed.sql | docker exec -i "$DB_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null

echo "[4/5] Run one-time crawler"
DB_DSN="$DB_DSN" ./.venv/bin/python scripts/ingest/run_daangn_crawl_once.py

echo "[5/5] Verify inserted rows"
docker exec -i "$DB_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT COUNT(*) AS post_cnt FROM daangn.community_posts WHERE source_url LIKE 'https://www.daangn.com/kr/community/%' AND source_url <> 'https://www.daangn.com/kr/community';" \
  -c "SELECT COUNT(*) AS comment_cnt FROM daangn.community_comments WHERE comment_key NOT LIKE 'comment_key_smoke_%';" \
  -c "SELECT p.city_name, p.dong_name, p.title, left(c.comment_body,80) AS comment_sample FROM daangn.community_comments c JOIN daangn.community_posts p ON p.post_key = c.post_key ORDER BY c.id DESC LIMIT 5;"
