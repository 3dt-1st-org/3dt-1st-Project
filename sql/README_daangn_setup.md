# Daangn DB Setup

팀원 공용 실행 순서:

```bash
psql "$DB_DSN" -f sql/ddl/daangn_community_tables.sql
psql "$DB_DSN" -f sql/dml/daangn_target_dongs_seed.sql
```

또는 마이그레이션 파일 1회 실행:

```bash
psql "$DB_DSN" -f sql/migration/Script-daangn-community-260226.sql
```

중복 방지 스모크 테스트:

```bash
psql "$DB_DSN" -f tests/sql/daangn_dedup_smoke_test.sql
```

`post_cnt`, `comment_cnt`가 각각 `1`이면 중복 적재 방지가 정상입니다.

팀원 빠른 실행(권장):

```bash
./scripts/ingest/bootstrap_and_run_daangn_once.sh
```

위 스크립트가 아래를 순서대로 수행합니다.
- 로컬 DB 컨테이너 실행
- `daangn` 스키마 SQL/시드 SQL 적용
- 1회 크롤링 실행
- 게시글/댓글 적재 건수 및 댓글 샘플 조회
