# Azure Ops Hybrid Realtime Runbook (Event Hub + ASA + Function)

## 1) 아키텍처
- **준실시간 배치(기존 v1 유지)**: Azure Timer Function → `monitoring.*` 테이블
  - `resource_inventory_snapshot` (1일)
  - `health_metrics_5m` (5분)
  - `telemetry_kpi_5m` (5분)
  - `cost_daily` (30분)
- **실시간 스트림(v2 추가)**: Diagnostic Settings → Event Hub(raw) → ASA(1분 집계) → Event Hub(kpi) → Function → `monitoring.telemetry_kpi_stream_1m`

핵심 포인트:
- 즉시성 이벤트는 Event Hub/ASA로 처리
- 비용/인벤토리는 원천 지연 특성상 배치 유지

## 2) 실시간 스트림 리소스 생성 / 네임스페이스 Blue-Green 전환
기본 권장(네임스페이스 전환 포함):
Bash:
```bash
./scripts/monitoring/migrate_eventhub_namespace_blue_green.sh
```

신규 프로비저닝만 필요할 때(동일 namespace 기준):
Bash:
```bash
./scripts/monitoring/provision_hybrid_eventhub_asa.sh
```

기본 생성 리소스:
- Event Hub Namespace: `monitoring-hub`
- Raw Hub: `azure-ops-raw`
- KPI Hub: `azure-ops-kpi`
- KPI Consumer Group: `ops-realtime-ingest`
- ASA Job: `asa-3dt-ops-realtime`
- SAQL: `infra/stream_analytics/azure_ops_realtime_kpi.saql`

대상 리소스 진단로그 연결:
- `lala`
- `daagn-crawler`
- `weather-air-func`
- `lala-db`

## 3) Power BI 연결 옵션
### 옵션 A) Event Hub KPI를 별도 소비층(Fabric/Function)에서 가공 후 DirectQuery 소스에 적재
- 장점: 인증 토큰/Push Dataset 의존도 낮음
- 권장: 운영 안정성 측면에서 장기 권장

### 옵션 B) ASA 출력을 Power BI로 직접 연결
- `scripts/monitoring/configure_asa_powerbi_output.sh`
- 필요값: Power BI Group/Dataset/Table + Refresh Token + 사용자 UPN/표시명

## 4) 검증
- Raw stream 유입 확인:
```bash
az eventhubs eventhub show -g 3dt-1st-team2 --namespace-name monitoring-hub -n azure-ops-raw --query messageRetentionInDays -o tsv
```
- ASA 상태 확인:
```bash
az stream-analytics job show -g 3dt-1st-team2 -n asa-3dt-ops-realtime --query jobState -o tsv
```
- KPI stream 유입 확인:
```bash
az eventhubs eventhub show -g 3dt-1st-team2 --namespace-name monitoring-hub -n azure-ops-kpi --query "countDetails" -o json
```
- DB 반영 확인:
```sql
SELECT * FROM monitoring.telemetry_kpi_stream_1m ORDER BY window_end_utc DESC LIMIT 20;
SELECT * FROM monitoring.vw_realtime_kpi_1m ORDER BY window_end_utc DESC LIMIT 20;
```

## 5) 기대 지연
- 스트림 경로: 보통 10초~2분 내 반영
- 비용 데이터: Azure 원천 지연으로 완전 실시간 불가
- 대시보드에는 `최종 수집 시각`과 `스트림 지연`(가능 시)을 함께 표기 권장
