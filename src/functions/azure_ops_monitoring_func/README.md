# azure_ops_monitoring_func

`monitoring` 스키마 데이터마트를 자동 갱신하는 Azure Timer Function 앱입니다.

트리거:
- `monitoring_inventory_timer`: 하루 1회 리소스 인벤토리 스냅샷
- `monitoring_health_timer`: 5분 주기 헬스/성능 메트릭 수집
- `monitoring_log_kpi_timer`: 5분 주기 로그 KPI 수집
- `monitoring_cost_timer`: 30분 주기 비용 수집
- `monitoring_stream_kpi_eventhub`: Event Hub KPI 스트림(1분 집계) 적재

## 런타임 환경 변수
- `AZ_SUBSCRIPTION_ID` (기본: `5bff8a75-037e-4d67-94cf-6fc62202174d`)
- `AZ_RESOURCE_GROUP` (기본: `3dt-1st-team2`)
- `LOG_ANALYTICS_WORKSPACE_ID` (기본: `3a6ae1f6-a887-4b1f-ad70-56f270c974ca`)
- `DB_DSN` (필수, Key Vault Reference 권장)
- `KEY_VAULT_URL` (옵션, `DB_DSN` 미설정 시 fallback)

스케줄(UTC):
- `MONITORING_INVENTORY_CRON` (기본: `0 5 0 * * *`)
- `MONITORING_HEALTH_CRON` (기본: `0 */5 * * * *`)
- `MONITORING_LOG_KPI_CRON` (기본: `20 */5 * * * *`)
- `MONITORING_COST_CRON` (기본: `0 */30 * * * *`)

운영 제어:
- `MONITORING_INIT_SCHEMA` (`1`이면 실행 시 DDL 적용)
- `MONITORING_LOG_LEVEL` (`INFO`, `DEBUG` 등)

실시간 스트림(Event Hub Trigger):
- `MONITORING_EVENTHUB_KPI_ENABLED` (`1`일 때 Event Hub Trigger 등록)
- `MONITORING_EVENTHUB_KPI_NAME` (기본: `azure-ops-kpi`)
- `MONITORING_EVENTHUB_KPI_CONSUMER_GROUP` (기본: `ops-realtime-ingest`)
- `MONITORING_EVENTHUB_KPI_CONNECTION_SETTING` (기본: `EVENTHUB_KPI_CONNECTION`)
- `EVENTHUB_KPI_CONNECTION` (Event Hub namespace connection string)

## 로컬 실행
```bash
cd src/functions/azure_ops_monitoring_func
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp local.settings.sample.json local.settings.json
func start
```

## 수동 배포
```bash
./scripts/monitoring/provision_azure_ops_function.sh
./scripts/monitoring/deploy_azure_ops_function.sh
```

세부 파라미터는 각 스크립트 파일 상단의 환경변수 설명을 참고하세요.

## 주의
- Linux Function App에서는 CRON이 UTC 기준입니다.
- 잡별 advisory lock을 사용하므로 동일 잡의 중복 실행은 자동으로 스킵됩니다.
- 비용 데이터는 Azure 원천 반영 지연이 존재하므로 완전 실시간이 아닙니다.
- 실시간 이벤트 감지는 `scripts/monitoring/migrate_eventhub_namespace_blue_green.*` + `infra/stream_analytics/azure_ops_realtime_kpi.saql` 경로를 사용합니다.
