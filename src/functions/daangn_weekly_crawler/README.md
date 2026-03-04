# daangn_weekly_crawler

주 1회 동네생활 글을 수집해 `daangn` 스키마에 저장하는 Azure Function입니다.

구조:
- `daangn_weekly_crawler`(Timer): 대상 동/키워드별 작업을 큐에 등록
- `daangn_crawl_worker`(Queue): 작업 1건(동+키워드) 단위로 실제 크롤링/적재
- `daangn_place_mentions_aggregator`(Timer): 최근 데이터에서 장소명/카테고리/시별 언급 수 주간 집계

## 저장 대상
- 게시글: 제목, 본문, 시, 동, 원본 URL
- 댓글: 댓글 본문, 시, 동
- 중복 방지: `post_key`, `comment_key` 유니크 키 기반

## SQL 선행 적용
```bash
psql "$DB_DSN" -f sql/ddl/daangn_community_tables.sql
psql "$DB_DSN" -f sql/dml/daangn_target_dongs_seed.sql
```

또는:
```bash
psql "$DB_DSN" -f sql/migration/Script-daangn-community-260226.sql
psql "$DB_DSN" -f sql/migration/Script-daangn-crawl-tasks-260303.sql
psql "$DB_DSN" -f sql/migration/Script-daangn-place-mentions-weekly-260304.sql
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

## Azure Functions 배포
- Function 프로젝트 루트: `src/functions/daangn_weekly_crawler`
- 현재 디렉터리에 `function_app.py`, `host.json`, `requirements.txt`가 있어 Python v2 모델 배포 가능 상태입니다.
- 배포 예시:
```bash
cd src/functions/daangn_weekly_crawler
func azure functionapp publish <YOUR_FUNCTION_APP_NAME> --python
```

## 운영 설정
- `TIMER_CRON`: 기본값 `0 0 3 * * 1` (매주 월요일 03:00)
- `DAANGN_TASK_QUEUE`: 큐 이름(기본 `daangn-crawl-tasks`)
- `MENTION_AGGREGATION_CRON`: 장소 언급 집계 실행 주기(기본 `0 30 3 * * 1`)
- `MENTION_LOOKBACK_DAYS`: 장소 언급 집계 대상 기간(일, 기본 `7`)
- `MENTION_USE_LLM`: 장소 추출에 LLM 사용 여부 (`1`/`0`)
- `MENTION_LLM_MAX_ROWS`: LLM 입력 최대 행 수 (비용 제한)
- `MENTION_LLM_BATCH_SIZE`: LLM 배치 크기
- `MENTION_LLM_TEXT_LIMIT`: 텍스트 자르기 길이
- `DB_DSN`: PostgreSQL 접속 문자열
- `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`, `AZURE_OPENAI_DEPLOYMENT_NAME`, `AZURE_OPENAI_VERSION`
- `MAX_POSTS_PER_DONG`: 동/키워드당 최대 게시글 수 (기본 5)
- `MAX_TOTAL_POSTS_PER_RUN`: 1회 실행당 최대 게시글 수 (기본 60)

## Key Vault 권장 설정
- 운영 환경에서는 `DB_DSN`을 코드/파일에 하드코딩하지 않고 Azure Key Vault에서 주입합니다.
- Function App의 Managed Identity를 활성화하고 Key Vault `Secrets User` 권한을 부여합니다.
- App Setting 예시:
  - `DB_DSN = @Microsoft.KeyVault(SecretUri=https://<keyvault-name>.vault.azure.net/secrets/db-dsn/)`

## 로컬 실행 시 필수 환경변수
- `DB_DSN`
- `POSTGRES_PASSWORD` (docker compose postgres 컨테이너 기동 시 필요)

## 주의
- `daangn.target_dongs.dong_slug`가 비어 있으면 해당 동은 스킵됩니다.
- 페이지 셀렉터는 서비스 구조 변경 시 수정이 필요합니다.
- 중복 적재는 `post_key`, `comment_key` 유니크 키로 차단됩니다.
- Linux Function App은 `WEBSITE_TIME_ZONE`이 적용되지 않으므로 `TIMER_CRON`을 UTC 기준으로 설정해야 합니다.
