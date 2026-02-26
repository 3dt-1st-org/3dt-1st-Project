$ErrorActionPreference = 'Stop'

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$DbContainer = if ($env:DB_CONTAINER) { $env:DB_CONTAINER } else { "geo-ai-db" }
$DbDsn = if ($env:DB_DSN) { $env:DB_DSN } else { "postgresql://admin_user:1111@localhost:5433/postgres" }

Set-Location $RootDir

Write-Host "[1/5] Start local DB container"
docker compose -f infra/docker/docker-compose.yml up -d db | Out-Null

Write-Host "[2/5] Apply schema SQL"
Get-Content sql/ddl/daangn_community_tables.sql -Raw | docker exec -i $DbContainer psql -U admin_user -d postgres | Out-Null

Write-Host "[3/5] Apply target dongs seed SQL"
Get-Content sql/dml/daangn_target_dongs_seed.sql -Raw | docker exec -i $DbContainer psql -U admin_user -d postgres | Out-Null

Write-Host "[4/5] Run one-time crawler"
$env:DB_DSN = $DbDsn
& .\.venv\Scripts\python.exe scripts/ingest/run_daangn_crawl_once.py
if ($LASTEXITCODE -ne 0) {
    throw "Crawler run failed with exit code $LASTEXITCODE"
}

Write-Host "[5/5] Verify inserted rows"
docker exec -i $DbContainer psql -U admin_user -d postgres `
  -c "SELECT COUNT(*) AS post_cnt FROM daangn.community_posts WHERE source_url LIKE 'https://www.daangn.com/kr/community/%' AND source_url <> 'https://www.daangn.com/kr/community';" `
  -c "SELECT COUNT(*) AS comment_cnt FROM daangn.community_comments WHERE comment_key NOT LIKE 'comment_key_smoke_%';" `
  -c "SELECT p.city_name, p.dong_name, p.title, left(c.comment_body,80) AS comment_sample FROM daangn.community_comments c JOIN daangn.community_posts p ON p.post_key = c.post_key ORDER BY c.id DESC LIMIT 5;"
