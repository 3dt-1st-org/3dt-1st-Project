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
