# Power BI Azure Ops Dashboard Runbook (v1)

## 1) 목적
- Azure 리소스 헬스/성능/비용 데이터를 `monitoring.*` 데이터마트에 적재하고
- Power BI DirectQuery로 `Overview / Service Health / Cost & Burn / Incidents` 페이지를 구성한다.
- 실시간 이벤트 감지가 필요하면 Event Hub + ASA 하이브리드 레이어를 추가한다.

하이브리드 실시간 운영 런북:
- `docs/azure-ops-hybrid-realtime-runbook-2026-03-09.md`

대상 서비스:
- `lala`
- `daagn-crawler`
- `weather-air-func`
- `lala-db`

## 2) 사전 조건
- `az login` 완료 (Power BI Pro 계정)
- 구독 접근 가능: `5bff8a75-037e-4d67-94cf-6fc62202174d`
- DB 접근 가능: `DB_DSN` 환경변수 또는 Key Vault `db-dsn` 시크릿
- Python 의존성 설치

```bash
pip install -r requirements.txt
```

## 3) 스키마 생성
```bash
psql "$DB_DSN" -f sql/ddl/create_monitoring_powerbi_ops_tables.sql
```

또는 첫 실행에서 자동 생성:
```bash
python scripts/monitoring/run_monitoring_pipeline.py --init-schema
```

## 4) 수집 스크립트

리소스 인벤토리:
```bash
python scripts/monitoring/snapshot_resources.py
```

헬스/성능 메트릭(5분):
```bash
python scripts/monitoring/collect_health_metrics.py --window-minutes 65
```

로그 KPI(5분 버킷):
```bash
python scripts/monitoring/collect_log_kpi.py --lookback-minutes 120
```

비용 데이터(30분):
```bash
python scripts/monitoring/collect_cost.py
```

일괄 실행:
```bash
python scripts/monitoring/run_monitoring_pipeline.py
```

## 5) 자동 실행 배포 (Azure Timer Function v1)
권장 운영은 `src/functions/azure_ops_monitoring_func`를 Azure Function App으로 배포하는 방식이다.

### 5-1) Azure 리소스/권한 구성
```bash
./scripts/monitoring/provision_azure_ops_function.sh
```

기본값:
- Function App: `3dt-ops-monitoring-func`
- Subscription: `5bff8a75-037e-4d67-94cf-6fc62202174d`
- Resource Group: `3dt-1st-team2`
- Key Vault: `kv3dt1stteam2dev01`

이 스크립트는 다음을 포함한다:
- Function App 생성(Python 3.11 / Linux Consumption)
- Managed Identity 활성화
- 역할 할당 (`Reader`, `Monitoring Reader`, `Log Analytics Reader`, `Cost Management Reader`, `Key Vault Secrets User`)
- 필수 App Settings 설정 (`DB_DSN` Key Vault Reference 포함)

### 5-2) 코드 배포
```bash
./scripts/monitoring/deploy_azure_ops_function.sh
```

### 5-3) 트리거 스케줄(UTC)
- Inventory: `0 5 0 * * *` (하루 1회)
- Health: `0 */5 * * * *` (5분)
- Log KPI: `20 */5 * * * *` (5분)
- Cost: `0 */30 * * * *` (30분)

## 5-4) 로컬 대안 (cron)
```cron
# resource inventory once/day
5 0 * * * cd /repo && /usr/bin/python3 scripts/monitoring/snapshot_resources.py

# health and telemetry every 5 minutes
*/5 * * * * cd /repo && /usr/bin/python3 scripts/monitoring/collect_health_metrics.py
*/5 * * * * cd /repo && /usr/bin/python3 scripts/monitoring/collect_log_kpi.py

# cost every 30 minutes
*/30 * * * * cd /repo && /usr/bin/python3 scripts/monitoring/collect_cost.py
```

## 6) Power BI 자동화

워크스페이스 생성:
```bash
python scripts/monitoring/powerbi_automation.py --action ensure-workspace --workspace-name "3DT-Azure-Ops"
```

PBIX import:
```bash
python scripts/monitoring/powerbi_automation.py \
  --action import-pbix \
  --workspace-name "3DT-Azure-Ops" \
  --pbix-path "/absolute/path/3dt-azure-ops-template.pbix" \
  --dataset-display-name "3DT-Azure-Ops"
```

데이터셋 리프레시 트리거:
```bash
python scripts/monitoring/powerbi_automation.py --action refresh-datasets --workspace-name "3DT-Azure-Ops"
```

서비스 반영 일괄(Import + PostgreSQL 자격증명 적용 + 모델 검증):
```bash
python scripts/monitoring/powerbi_service_sync.py \
  --workspace-name "AremArem-Azure-Ops" \
  --dataset-name "3DT Azure Ops Semantic Base" \
  --pbix-path "/absolute/path/Arem Arem Azure Ops Semantic Model.pbix" \
  --print-json
```

참고:
- 스크립트 종료코드 `0`: 실시간 테이블/컬럼까지 모델 반영 완료
- 스크립트 종료코드 `2`: 기본 모델은 연결되었지만 `vw_realtime_kpi_1m` 또는 `stream_*` 컬럼 미반영

## 7) 검증 쿼리
```sql
SELECT COUNT(*) FROM monitoring.resource_inventory_snapshot;
SELECT COUNT(*) FROM monitoring.health_metrics_5m;
SELECT COUNT(*) FROM monitoring.telemetry_kpi_5m;
SELECT COUNT(*) FROM monitoring.telemetry_kpi_stream_1m;
SELECT COUNT(*) FROM monitoring.cost_daily;
```

Power BI 모델 연결용 뷰:
```sql
SELECT * FROM monitoring.vw_overview_latest;
SELECT * FROM monitoring.vw_service_health_5m;
SELECT * FROM monitoring.vw_realtime_kpi_1m;
SELECT * FROM monitoring.vw_cost_burn_daily;
SELECT * FROM monitoring.vw_incidents_5m;
```

원천 스키마/카드 지표 자동 검증:
```bash
python scripts/monitoring/validate_realtime_semantic_model.py --print-json
```

지연 SLA(예: 120초) 포함 검증:
```bash
python scripts/monitoring/validate_realtime_semantic_model.py --max-stream-delay-seconds 120 --print-json
```

PBIX 모델(로컬 파일) 뷰 반영 확인:
```bash
python scripts/monitoring/check_pbix_model_views.py --pbix-path "Arem Arem Azure Ops Semantic Model.pbix"
```

최근 데이터 확인:
```sql
SELECT * FROM monitoring.health_metrics_5m
ORDER BY metric_timestamp_utc DESC
LIMIT 20;
```

## 8) PBIX 1회 생성 (수동)
- 현재 환경(Codex CLI/macOS)에서는 유효한 `.pbix` 바이너리를 직접 생성할 수 없다.
- 대신 아래 순서로 1회만 Desktop에서 생성 후, 이후 import/refresh는 자동화한다.

1. Power BI Desktop에서 새 파일 생성
2. PostgreSQL 연결로 `lala-db` 접속
3. 다음 5개 뷰를 DirectQuery로 추가
   - `monitoring.vw_overview_latest`
   - `monitoring.vw_service_health_5m`
   - `monitoring.vw_realtime_kpi_1m`
   - `monitoring.vw_cost_burn_daily`
   - `monitoring.vw_incidents_5m`
4. 파일을 `3dt-azure-ops-template.pbix`로 저장
5. 저장한 파일을 아래 명령으로 워크스페이스에 import

```bash
python scripts/monitoring/powerbi_automation.py \
  --action import-pbix \
  --workspace-name "3DT-Azure-Ops" \
  --pbix-path "/absolute/path/3dt-azure-ops-template.pbix" \
  --dataset-display-name "3DT-Azure-Ops"
```

## 9) 주의 사항
- 비용 데이터는 본질적으로 완전 실시간이 아니다. 대시보드에 `최신 수집 시각`을 반드시 표기한다.
- `PBIX` 시각 레이아웃은 수동 1회 설계 후, 배포/리프레시만 자동화한다.
- 민감 정보(`DB_DSN`, 키/토큰)는 저장소에 커밋하지 않는다.

## 10) 실시간 카드 바인딩 (권장)
`Overview` 페이지 카드/텍스트를 아래 컬럼에 직접 바인딩한다.
- `monitoring.vw_overview_latest.stream_window_end_utc` : 실시간 마지막 윈도우 시각
- `monitoring.vw_overview_latest.stream_delay_seconds` : 실시간 지연(초)
- `monitoring.vw_overview_latest.stream_event_count_1m` : 최근 1분 이벤트 수
- `monitoring.vw_overview_latest.stream_http5xx_count_1m` : 최근 1분 5xx 수
- `monitoring.vw_overview_latest.stream_error_count_1m` : 최근 1분 에러 수
