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

또는:
```bash
psql "$DB_DSN" -f sql/migration/Script-daangn-community-260226.sql
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
- `WEBSITE_TIME_ZONE`: `Korea Standard Time`
- `DB_DSN`: PostgreSQL 접속 문자열

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
