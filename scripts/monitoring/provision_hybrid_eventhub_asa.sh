#!/usr/bin/env bash
set -euo pipefail

# Hybrid realtime pipeline (v2):
# Azure Monitor Diagnostics -> Event Hub(raw) -> ASA(1m aggregate) -> Event Hub(kpi)
#
# Usage:
#   ./scripts/monitoring/provision_hybrid_eventhub_asa.sh
#   EH_NAMESPACE_NAME=monitoring-hub ASA_JOB_NAME=asa-3dt-ops ./scripts/monitoring/provision_hybrid_eventhub_asa.sh

SUBSCRIPTION_ID="${AZ_SUBSCRIPTION_ID:-5bff8a75-037e-4d67-94cf-6fc62202174d}"
RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-3dt-1st-team2}"

EH_NAMESPACE_NAME="${EH_NAMESPACE_NAME:-monitoring-hub}"
EH_RAW_NAME="${EH_RAW_NAME:-azure-ops-raw}"
EH_KPI_NAME="${EH_KPI_NAME:-azure-ops-kpi}"
EH_RAW_CONSUMER_GROUP="${EH_RAW_CONSUMER_GROUP:-asa-realtime}"
EH_KPI_CONSUMER_GROUP="${EH_KPI_CONSUMER_GROUP:-ops-realtime-ingest}"
EH_POLICY_NAME="${EH_POLICY_NAME:-RootManageSharedAccessKey}"

ASA_JOB_NAME="${ASA_JOB_NAME:-asa-3dt-ops-realtime}"
ASA_INPUT_NAME="${ASA_INPUT_NAME:-raw-monitoring-input-v2}"
ASA_OUTPUT_NAME="${ASA_OUTPUT_NAME:-kpi-hub-v2}"
ASA_TRANSFORMATION_NAME="${ASA_TRANSFORMATION_NAME:-main-transformation}"
ASA_STREAMING_UNITS="${ASA_STREAMING_UNITS:-1}"
ASA_SAQL_FILE="${ASA_SAQL_FILE:-infra/stream_analytics/azure_ops_realtime_kpi.saql}"
ASA_START_ON_PROVISION="${ASA_START_ON_PROVISION:-1}"

if ! command -v az >/dev/null 2>&1; then
  echo "[ERROR] az cli is required." >&2
  exit 1
fi

if [[ ! -f "$ASA_SAQL_FILE" ]]; then
  echo "[ERROR] SAQL file not found: $ASA_SAQL_FILE" >&2
  exit 1
fi

az account set --subscription "$SUBSCRIPTION_ID"
LOCATION="$(az group show -n "$RESOURCE_GROUP" --query location -o tsv)"
if [[ -z "$LOCATION" ]]; then
  echo "[ERROR] Failed to resolve resource group location: $RESOURCE_GROUP" >&2
  exit 1
fi

echo "[INFO] subscription=$SUBSCRIPTION_ID resource_group=$RESOURCE_GROUP location=$LOCATION"

if ! az eventhubs namespace show -n "$EH_NAMESPACE_NAME" -g "$RESOURCE_GROUP" >/dev/null 2>&1; then
  echo "[INFO] Creating Event Hubs namespace: $EH_NAMESPACE_NAME"
  az eventhubs namespace create \
    --name "$EH_NAMESPACE_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --sku Standard \
    --enable-auto-inflate true \
    --maximum-throughput-units 4 >/dev/null
fi

ensure_eventhub() {
  local hub_name="$1"
  if ! az eventhubs eventhub show -n "$hub_name" --namespace-name "$EH_NAMESPACE_NAME" -g "$RESOURCE_GROUP" >/dev/null 2>&1; then
    echo "[INFO] Creating Event Hub: $hub_name"
    az eventhubs eventhub create \
      --name "$hub_name" \
      --namespace-name "$EH_NAMESPACE_NAME" \
      --resource-group "$RESOURCE_GROUP" \
      --partition-count 4 \
      --cleanup-policy Delete \
      --retention-time-in-hours 24 >/dev/null
  fi
}

ensure_eventhub "$EH_RAW_NAME"
ensure_eventhub "$EH_KPI_NAME"

if ! az eventhubs eventhub consumer-group show \
  --name "$EH_RAW_CONSUMER_GROUP" \
  --eventhub-name "$EH_RAW_NAME" \
  --namespace-name "$EH_NAMESPACE_NAME" \
  --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  echo "[INFO] Creating Event Hub consumer group (raw): $EH_RAW_CONSUMER_GROUP"
  az eventhubs eventhub consumer-group create \
    --name "$EH_RAW_CONSUMER_GROUP" \
    --eventhub-name "$EH_RAW_NAME" \
    --namespace-name "$EH_NAMESPACE_NAME" \
    --resource-group "$RESOURCE_GROUP" >/dev/null
fi

if ! az eventhubs eventhub consumer-group show \
  --name "$EH_KPI_CONSUMER_GROUP" \
  --eventhub-name "$EH_KPI_NAME" \
  --namespace-name "$EH_NAMESPACE_NAME" \
  --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  echo "[INFO] Creating Event Hub consumer group (kpi): $EH_KPI_CONSUMER_GROUP"
  az eventhubs eventhub consumer-group create \
    --name "$EH_KPI_CONSUMER_GROUP" \
    --eventhub-name "$EH_KPI_NAME" \
    --namespace-name "$EH_NAMESPACE_NAME" \
    --resource-group "$RESOURCE_GROUP" >/dev/null
fi

EH_RULE_ID="$(az eventhubs namespace authorization-rule show \
  --namespace-name "$EH_NAMESPACE_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --name "$EH_POLICY_NAME" \
  --query id -o tsv)"

EH_POLICY_KEY="$(az eventhubs namespace authorization-rule keys list \
  --namespace-name "$EH_NAMESPACE_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --name "$EH_POLICY_NAME" \
  --query primaryKey -o tsv)"

configure_diagnostic_to_eventhub() {
  local resource_id="$1"
  local diag_name="$2"

  if ! az resource show --ids "$resource_id" >/dev/null 2>&1; then
    echo "[WARN] Resource not found, skipping diagnostics: $resource_id"
    return
  fi

  echo "[INFO] Configure diagnostics: $diag_name"
  az monitor diagnostic-settings create \
    --name "$diag_name" \
    --resource "$resource_id" \
    --event-hub "$EH_RAW_NAME" \
    --event-hub-rule "$EH_RULE_ID" \
    --logs '[{"categoryGroup":"allLogs","enabled":true}]' \
    --metrics '[{"category":"AllMetrics","enabled":true}]' >/dev/null
}

configure_diagnostic_to_eventhub \
  "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Web/sites/lala" \
  "diag-ops-raw-lala"

configure_diagnostic_to_eventhub \
  "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Web/sites/daagn-crawler" \
  "diag-ops-raw-daagn-crawler"

configure_diagnostic_to_eventhub \
  "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Web/sites/weather-air-func" \
  "diag-ops-raw-weather-air-func"

configure_diagnostic_to_eventhub \
  "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.DBforPostgreSQL/flexibleServers/lala-db" \
  "diag-ops-raw-lala-db"

az extension add --name stream-analytics --upgrade >/dev/null 2>&1 || true

if ! az stream-analytics job show --name "$ASA_JOB_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  echo "[INFO] Creating Stream Analytics job: $ASA_JOB_NAME"
  az stream-analytics job create \
    --name "$ASA_JOB_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --compatibility-level 1.2 \
    --data-locale en-US \
    --functions '[]' \
    --inputs '[]' \
    --outputs '[]' \
    --output-error-policy Drop \
    --out-of-order-policy Adjust \
    --order-max-delay 60 \
    --arrival-max-delay 15 >/dev/null
fi

wait_for_asa_state() {
  local expected_state="$1"
  local max_retry="${2:-24}"
  local delay_seconds="${3:-5}"

  local current_state=""
  for ((i = 0; i < max_retry; i++)); do
    current_state="$(az stream-analytics job show --name "$ASA_JOB_NAME" --resource-group "$RESOURCE_GROUP" --query jobState -o tsv)"
    if [[ "$current_state" == "$expected_state" ]]; then
      return 0
    fi
    sleep "$delay_seconds"
  done

  echo "[ERROR] Timeout waiting ASA state='$expected_state' (current='$current_state')." >&2
  return 1
}

ASA_PRE_UPDATE_STATE="$(az stream-analytics job show --name "$ASA_JOB_NAME" --resource-group "$RESOURCE_GROUP" --query jobState -o tsv)"
if [[ "$ASA_PRE_UPDATE_STATE" != "Created" && "$ASA_PRE_UPDATE_STATE" != "Stopped" && "$ASA_PRE_UPDATE_STATE" != "Failed" ]]; then
  echo "[INFO] Stopping ASA job for update (current state: $ASA_PRE_UPDATE_STATE)"
  az stream-analytics job stop --name "$ASA_JOB_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null || true
  wait_for_asa_state "Stopped"
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

INPUT_JSON="$TMP_DIR/asa_input.json"
cat > "$INPUT_JSON" <<JSON
{
  "type": "Stream",
  "datasource": {
    "type": "Microsoft.ServiceBus/EventHub",
    "properties": {
      "serviceBusNamespace": "$EH_NAMESPACE_NAME",
      "eventHubName": "$EH_RAW_NAME",
      "consumerGroupName": "$EH_RAW_CONSUMER_GROUP",
      "sharedAccessPolicyName": "$EH_POLICY_NAME",
      "sharedAccessPolicyKey": "$EH_POLICY_KEY"
    }
  },
  "serialization": {
    "type": "Json",
    "properties": {
      "encoding": "UTF8"
    }
  }
}
JSON

OUTPUT_DATASOURCE_JSON="$TMP_DIR/asa_output_datasource.json"
cat > "$OUTPUT_DATASOURCE_JSON" <<JSON
{
  "type": "Microsoft.ServiceBus/EventHub",
  "properties": {
    "serviceBusNamespace": "$EH_NAMESPACE_NAME",
    "eventHubName": "$EH_KPI_NAME",
    "sharedAccessPolicyName": "$EH_POLICY_NAME",
    "sharedAccessPolicyKey": "$EH_POLICY_KEY"
  }
}
JSON

OUTPUT_SERIALIZATION_JSON="$TMP_DIR/asa_output_serialization.json"
cat > "$OUTPUT_SERIALIZATION_JSON" <<'JSON'
{
  "type": "Json",
  "properties": {
    "format": "LineSeparated",
    "encoding": "UTF8"
  }
}
JSON

echo "[INFO] Upserting ASA input/output/transformation"
az stream-analytics input create \
  --job-name "$ASA_JOB_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --name "$ASA_INPUT_NAME" \
  --properties "@$INPUT_JSON" >/dev/null

az stream-analytics output create \
  --job-name "$ASA_JOB_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --name "$ASA_OUTPUT_NAME" \
  --datasource "@$OUTPUT_DATASOURCE_JSON" \
  --serialization "@$OUTPUT_SERIALIZATION_JSON" >/dev/null

SAQL_QUERY="$(sed \
  -e "s/\\[raw-monitoring-input\\]/[$ASA_INPUT_NAME]/g" \
  -e "s/\\[realtime-kpi-output\\]/[$ASA_OUTPUT_NAME]/g" \
  "$ASA_SAQL_FILE")"
az stream-analytics transformation create \
  --job-name "$ASA_JOB_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --name "$ASA_TRANSFORMATION_NAME" \
  --streaming-units "$ASA_STREAMING_UNITS" \
  --saql "$SAQL_QUERY" >/dev/null

ASA_STATE="$(az stream-analytics job show --name "$ASA_JOB_NAME" --resource-group "$RESOURCE_GROUP" --query jobState -o tsv)"
if [[ "$ASA_START_ON_PROVISION" == "1" && "$ASA_STATE" != "Running" ]]; then
  echo "[INFO] Starting ASA job"
  az stream-analytics job start \
    --name "$ASA_JOB_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --output-start-mode JobStartTime >/dev/null
fi

echo "[DONE] Hybrid realtime pipeline provisioned"
echo "  Event Hub namespace : $EH_NAMESPACE_NAME"
echo "  Raw stream hub      : $EH_RAW_NAME"
echo "  KPI stream hub      : $EH_KPI_NAME"
echo "  ASA job             : $ASA_JOB_NAME"
echo "[NEXT] Connect '$EH_KPI_NAME' to downstream consumer (Power BI push/Fabric/Function ingestion)."
