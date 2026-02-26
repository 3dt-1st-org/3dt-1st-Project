# daangn_weekly_crawler

주 1회 동네생활 글을 수집해 `daangn` 스키마에 저장하는 Azure Function입니다.

## 저장 대상
- 게시글: 제목, 본문, 시, 동, 원본 URL
- 댓글: 댓글 본문, 시, 동
- 중복 방지: `post_key`, `comment_key` 유니크 키 기반

## SQL 선행 적용
```bash
psql "$DB_DSN" -f sql/ddl/daangn_community_tables.sql
psql "$DB_DSN" -f sql/dml/daangn_target_dongs_seed.sql
```

## 로컬 실행
```bash
cd src/functions/daangn_weekly_crawler
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp local.settings.sample.json local.settings.json
func start
```

## 운영 설정
- `TIMER_CRON`: 기본값 `0 0 3 * * 1` (매주 월요일 03:00)
- `WEBSITE_TIME_ZONE`: `Korea Standard Time`
- `DB_DSN`: PostgreSQL 접속 문자열

## 주의
- `daangn.target_dongs.dong_slug`가 비어 있으면 해당 동은 스킵됩니다.
- 페이지 셀렉터는 서비스 구조 변경 시 수정이 필요합니다.
