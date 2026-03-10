#!/usr/bin/env bash
set -euo pipefail

# Blue/Green migration for Azure Ops realtime pipeline:
#   old namespace (blue): evhns3dtopsmon01
#   new namespace (green): monitoring-hub
#
# Target pipeline:
#   Diagnostic Settings -> Event Hub(raw) -> ASA(1m KPI) -> Event Hub(kpi) -> Function -> PostgreSQL
#
# Usage:
#   ./scripts/monitoring/migrate_eventhub_namespace_blue_green.sh

SUBSCRIPTION_ID="${AZ_SUBSCRIPTION_ID:-5bff8a75-037e-4d67-94cf-6fc62202174d}"
RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-3dt-1st-team2}"

OLD_NAMESPACE_NAME="${OLD_NAMESPACE_NAME:-evhns3dtopsmon01}"
NEW_NAMESPACE_NAME="${NEW_NAMESPACE_NAME:-monitoring-hub}"
EVENTHUB_RAW_NAME="${EVENTHUB_RAW_NAME:-azure-ops-raw}"
EVENTHUB_KPI_NAME="${EVENTHUB_KPI_NAME:-azure-ops-kpi}"
EVENTHUB_POLICY_NAME="${EVENTHUB_POLICY_NAME:-RootManageSharedAccessKey}"
RAW_CONSUMER_GROUP="${RAW_CONSUMER_GROUP:-asa-realtime}"
KPI_CONSUMER_GROUP="${KPI_CONSUMER_GROUP:-ops-realtime-ingest}"

ASA_JOB_NAME="${ASA_JOB_NAME:-asa-3dt-ops-realtime}"
ASA_INPUT_V2_NAME="${ASA_INPUT_V2_NAME:-raw-monitoring-input-v2}"
ASA_OUTPUT_V2_NAME="${ASA_OUTPUT_V2_NAME:-kpi-hub-v2}"
ASA_TRANSFORMATION_NAME="${ASA_TRANSFORMATION_NAME:-main-transformation}"
ASA_STREAMING_UNITS="${ASA_STREAMING_UNITS:-1}"
ASA_SAQL_FILE="${ASA_SAQL_FILE:-infra/stream_analytics/azure_ops_realtime_kpi.saql}"
ASA_START_ON_MIGRATION="${ASA_START_ON_MIGRATION:-1}"

FUNCTION_APP_NAME="${FUNCTION_APP_NAME:-3dt-ops-monitoring-func}"
ENABLE_FUNCTION_STREAM_TRIGGER="${ENABLE_FUNCTION_STREAM_TRIGGER:-1}"

DIAG_SUFFIX="${DIAG_SUFFIX:--v2}"

if ! command -v az >/dev/null 2>&1; then
  echo "[ERROR] az cli is required." >&2
  exit 1
fi

if [[ ! -f "$ASA_SAQL_FILE" ]]; then
  echo "[ERROR] SAQL file not found: $ASA_SAQL_FILE" >&2
  exit 1
fi

az extension add --name stream-analytics --upgrade >/dev/null 2>&1 || true
az account set --subscription "$SUBSCRIPTION_ID"

LOCATION="$(az group show -n "$RESOURCE_GROUP" --query location -o tsv)"
if [[ -z "$LOCATION" ]]; then
  echo "[ERROR] Failed to resolve resource group location: $RESOURCE_GROUP" >&2
  exit 1
fi

echo "[INFO] subscription=$SUBSCRIPTION_ID resource_group=$RESOURCE_GROUP location=$LOCATION"
echo "[INFO] blue(old)=$OLD_NAMESPACE_NAME green(new)=$NEW_NAMESPACE_NAME"

ensure_namespace() {
  local namespace_name="$1"
  if ! az eventhubs namespace show -n "$namespace_name" -g "$RESOURCE_GROUP" >/dev/null 2>&1; then
    echo "[INFO] Creating Event Hubs namespace: $namespace_name"
    az eventhubs namespace create \
      --name "$namespace_name" \
      --resource-group "$RESOURCE_GROUP" \
      --location "$LOCATION" \
      --sku Standard \
      --enable-auto-inflate true \
      --maximum-throughput-units 4 >/dev/null
  fi
}

ensure_eventhub() {
  local namespace_name="$1"
  local hub_name="$2"
  if ! az eventhubs eventhub show \
    --name "$hub_name" \
    --namespace-name "$namespace_name" \
    --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    echo "[INFO] Creating Event Hub '$hub_name' in namespace '$namespace_name'"
    az eventhubs eventhub create \
      --name "$hub_name" \
      --namespace-name "$namespace_name" \
      --resource-group "$RESOURCE_GROUP" \
      --partition-count 4 \
      --cleanup-policy Delete \
      --retention-time-in-hours 24 >/dev/null
  fi
}

ensure_consumer_group() {
  local namespace_name="$1"
  local hub_name="$2"
  local cg_name="$3"
  if ! az eventhubs eventhub consumer-group show \
    --name "$cg_name" \
    --eventhub-name "$hub_name" \
    --namespace-name "$namespace_name" \
    --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
    echo "[INFO] Creating consumer group '$cg_name' on '$hub_name'"
    az eventhubs eventhub consumer-group create \
      --name "$cg_name" \
      --eventhub-name "$hub_name" \
      --namespace-name "$namespace_name" \
      --resource-group "$RESOURCE_GROUP" >/dev/null
  fi
}

ensure_namespace "$NEW_NAMESPACE_NAME"
ensure_eventhub "$NEW_NAMESPACE_NAME" "$EVENTHUB_RAW_NAME"
ensure_eventhub "$NEW_NAMESPACE_NAME" "$EVENTHUB_KPI_NAME"
ensure_consumer_group "$NEW_NAMESPACE_NAME" "$EVENTHUB_RAW_NAME" "$RAW_CONSUMER_GROUP"
ensure_consumer_group "$NEW_NAMESPACE_NAME" "$EVENTHUB_KPI_NAME" "$KPI_CONSUMER_GROUP"

EH_RULE_ID="$(az eventhubs namespace authorization-rule show \
  --namespace-name "$NEW_NAMESPACE_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --name "$EVENTHUB_POLICY_NAME" \
  --query id -o tsv)"

EH_POLICY_KEY="$(az eventhubs namespace authorization-rule keys list \
  --namespace-name "$NEW_NAMESPACE_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --name "$EVENTHUB_POLICY_NAME" \
  --query primaryKey -o tsv)"

EH_CONNECTION_STRING="$(az eventhubs namespace authorization-rule keys list \
  --namespace-name "$NEW_NAMESPACE_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --name "$EVENTHUB_POLICY_NAME" \
  --query primaryConnectionString -o tsv)"

if [[ -z "$EH_CONNECTION_STRING" ]]; then
  echo "[ERROR] Failed to resolve namespace connection string for '$NEW_NAMESPACE_NAME'." >&2
  exit 1
fi

configure_diagnostic() {
  local resource_id="$1"
  local diag_name="$2"

  if ! az resource show --ids "$resource_id" >/dev/null 2>&1; then
    echo "[WARN] Resource not found, skip diagnostic setting: $resource_id"
    return
  fi

  echo "[INFO] Upserting diagnostic setting: $diag_name"
  az monitor diagnostic-settings create \
    --name "$diag_name" \
    --resource "$resource_id" \
    --event-hub "$EVENTHUB_RAW_NAME" \
    --event-hub-rule "$EH_RULE_ID" \
    --logs '[{"categoryGroup":"allLogs","enabled":true}]' \
    --metrics '[{"category":"AllMetrics","enabled":true}]' >/dev/null
}

configure_diagnostic \
  "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Web/sites/lala" \
  "diag-ops-raw-lala${DIAG_SUFFIX}"
configure_diagnostic \
  "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Web/sites/daagn-crawler" \
  "diag-ops-raw-daagn-crawler${DIAG_SUFFIX}"
configure_diagnostic \
  "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Web/sites/weather-air-func" \
  "diag-ops-raw-weather-air-func${DIAG_SUFFIX}"
configure_diagnostic \
  "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.DBforPostgreSQL/flexibleServers/lala-db" \
  "diag-ops-raw-lala-db${DIAG_SUFFIX}"

if ! az stream-analytics job show -n "$ASA_JOB_NAME" -g "$RESOURCE_GROUP" >/dev/null 2>&1; then
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

INPUT_JSON="$TMP_DIR/asa_input_v2.json"
cat > "$INPUT_JSON" <<JSON
{
  "type": "Stream",
  "datasource": {
    "type": "Microsoft.ServiceBus/EventHub",
    "properties": {
      "serviceBusNamespace": "$NEW_NAMESPACE_NAME",
      "eventHubName": "$EVENTHUB_RAW_NAME",
      "consumerGroupName": "$RAW_CONSUMER_GROUP",
      "sharedAccessPolicyName": "$EVENTHUB_POLICY_NAME",
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

OUTPUT_DATASOURCE_JSON="$TMP_DIR/asa_output_v2_datasource.json"
cat > "$OUTPUT_DATASOURCE_JSON" <<JSON
{
  "type": "Microsoft.ServiceBus/EventHub",
  "properties": {
    "serviceBusNamespace": "$NEW_NAMESPACE_NAME",
    "eventHubName": "$EVENTHUB_KPI_NAME",
    "sharedAccessPolicyName": "$EVENTHUB_POLICY_NAME",
    "sharedAccessPolicyKey": "$EH_POLICY_KEY"
  }
}
JSON

OUTPUT_SERIALIZATION_JSON="$TMP_DIR/asa_output_v2_serialization.json"
cat > "$OUTPUT_SERIALIZATION_JSON" <<'JSON'
{
  "type": "Json",
  "properties": {
    "format": "LineSeparated",
    "encoding": "UTF8"
  }
}
JSON

echo "[INFO] Upserting ASA input/output/transformation with v2 objects"
az stream-analytics input create \
  --job-name "$ASA_JOB_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --name "$ASA_INPUT_V2_NAME" \
  --properties "@$INPUT_JSON" >/dev/null

az stream-analytics output create \
  --job-name "$ASA_JOB_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --name "$ASA_OUTPUT_V2_NAME" \
  --datasource "@$OUTPUT_DATASOURCE_JSON" \
  --serialization "@$OUTPUT_SERIALIZATION_JSON" >/dev/null

SAQL_QUERY="$(sed \
  -e "s/\\[raw-monitoring-input\\]/[$ASA_INPUT_V2_NAME]/g" \
  -e "s/\\[realtime-kpi-output\\]/[$ASA_OUTPUT_V2_NAME]/g" \
  "$ASA_SAQL_FILE")"

az stream-analytics transformation create \
  --job-name "$ASA_JOB_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --name "$ASA_TRANSFORMATION_NAME" \
  --streaming-units "$ASA_STREAMING_UNITS" \
  --saql "$SAQL_QUERY" >/dev/null

ASA_STATE="$(az stream-analytics job show --name "$ASA_JOB_NAME" --resource-group "$RESOURCE_GROUP" --query jobState -o tsv)"
if [[ "$ASA_START_ON_MIGRATION" == "1" && "$ASA_STATE" != "Running" ]]; then
  echo "[INFO] Starting ASA job"
  az stream-analytics job start \
    --name "$ASA_JOB_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --output-start-mode JobStartTime >/dev/null
fi

if az functionapp show -n "$FUNCTION_APP_NAME" -g "$RESOURCE_GROUP" >/dev/null 2>&1; then
  echo "[INFO] Updating Function App Event Hub settings: $FUNCTION_APP_NAME"
  az functionapp config appsettings set \
    --name "$FUNCTION_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --settings \
      "EVENTHUB_KPI_CONNECTION=$EH_CONNECTION_STRING" \
      "MONITORING_EVENTHUB_KPI_ENABLED=$ENABLE_FUNCTION_STREAM_TRIGGER" \
      "MONITORING_EVENTHUB_KPI_NAME=$EVENTHUB_KPI_NAME" \
      "MONITORING_EVENTHUB_KPI_CONSUMER_GROUP=$KPI_CONSUMER_GROUP" >/dev/null
else
  echo "[WARN] Function app '$FUNCTION_APP_NAME' not found. Skip Event Hub app settings."
fi

echo "[DONE] Blue/Green migration applied."
echo "  New namespace        : $NEW_NAMESPACE_NAME"
echo "  Raw hub              : $EVENTHUB_RAW_NAME"
echo "  KPI hub              : $EVENTHUB_KPI_NAME"
echo "  ASA input(v2)        : $ASA_INPUT_V2_NAME"
echo "  ASA output(v2)       : $ASA_OUTPUT_V2_NAME"
echo "  Function app         : $FUNCTION_APP_NAME"
echo "[NOTE] Old namespace/resources are kept for blue/green rollback."
