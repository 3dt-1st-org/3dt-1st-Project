#!/usr/bin/env bash
set -euo pipefail

# Required tools: az
# Usage:
#   FUNCTION_APP_NAME=3dt-ops-monitoring-func ./scripts/monitoring/provision_azure_ops_function.sh

SUBSCRIPTION_ID="${AZ_SUBSCRIPTION_ID:-5bff8a75-037e-4d67-94cf-6fc62202174d}"
RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-3dt-1st-team2}"
FUNCTION_APP_NAME="${FUNCTION_APP_NAME:-3dt-ops-monitoring-func}"
STORAGE_ACCOUNT_NAME="${STORAGE_ACCOUNT_NAME:-st3dtopsmonfunc01}"
KEY_VAULT_NAME="${KEY_VAULT_NAME:-kv3dt1stteam2dev01}"
LOG_ANALYTICS_WORKSPACE_ID="${LOG_ANALYTICS_WORKSPACE_ID:-3a6ae1f6-a887-4b1f-ad70-56f270c974ca}"

MONITORING_INVENTORY_CRON="${MONITORING_INVENTORY_CRON:-0 5 0 * * *}"
MONITORING_HEALTH_CRON="${MONITORING_HEALTH_CRON:-0 */5 * * * *}"
MONITORING_LOG_KPI_CRON="${MONITORING_LOG_KPI_CRON:-20 */5 * * * *}"
MONITORING_COST_CRON="${MONITORING_COST_CRON:-0 */30 * * * *}"
MONITORING_LOG_LEVEL="${MONITORING_LOG_LEVEL:-INFO}"
MONITORING_INIT_SCHEMA="${MONITORING_INIT_SCHEMA:-0}"
COST_ROLE_SCOPE="${COST_ROLE_SCOPE:-resource-group}" # resource-group | subscription

if ! command -v az >/dev/null 2>&1; then
  echo "[ERROR] az cli is required." >&2
  exit 1
fi

az account set --subscription "$SUBSCRIPTION_ID"

LOCATION="$(az group show -n "$RESOURCE_GROUP" --query location -o tsv)"
if [[ -z "$LOCATION" ]]; then
  echo "[ERROR] Failed to resolve resource group location: $RESOURCE_GROUP" >&2
  exit 1
fi

echo "[INFO] subscription=$SUBSCRIPTION_ID resource_group=$RESOURCE_GROUP location=$LOCATION"

if ! az storage account show -n "$STORAGE_ACCOUNT_NAME" -g "$RESOURCE_GROUP" >/dev/null 2>&1; then
  echo "[INFO] Creating storage account: $STORAGE_ACCOUNT_NAME"
  az storage account create \
    --name "$STORAGE_ACCOUNT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --sku Standard_LRS \
    --kind StorageV2 \
    --min-tls-version TLS1_2 \
    --allow-blob-public-access false \
    --https-only true >/dev/null
fi

if ! az functionapp show -n "$FUNCTION_APP_NAME" -g "$RESOURCE_GROUP" >/dev/null 2>&1; then
  echo "[INFO] Creating function app: $FUNCTION_APP_NAME"
  az functionapp create \
    --name "$FUNCTION_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --storage-account "$STORAGE_ACCOUNT_NAME" \
    --consumption-plan-location "$LOCATION" \
    --os-type Linux \
    --runtime python \
    --runtime-version 3.11 \
    --functions-version 4 >/dev/null
fi

echo "[INFO] Assigning system managed identity"
az functionapp identity assign -n "$FUNCTION_APP_NAME" -g "$RESOURCE_GROUP" >/dev/null

PRINCIPAL_ID="$(az functionapp identity show -n "$FUNCTION_APP_NAME" -g "$RESOURCE_GROUP" --query principalId -o tsv)"
SUB_SCOPE="/subscriptions/$SUBSCRIPTION_ID"
RG_SCOPE="$SUB_SCOPE/resourceGroups/$RESOURCE_GROUP"
KV_SCOPE="$(az keyvault show -n "$KEY_VAULT_NAME" --query id -o tsv)"

assign_role_if_missing() {
  local role="$1"
  local scope="$2"

  local exists
  exists="$(az role assignment list \
    --assignee-object-id "$PRINCIPAL_ID" \
    --scope "$scope" \
    --role "$role" \
    --query "length([])" -o tsv)"

  if [[ "$exists" == "0" ]]; then
    echo "[INFO] Assign role '$role' on scope '$scope'"
    if ! az role assignment create \
      --assignee-object-id "$PRINCIPAL_ID" \
      --assignee-principal-type ServicePrincipal \
      --role "$role" \
      --scope "$scope" >/dev/null; then
      echo "[WARN] Failed to assign role '$role' on '$scope'. Continue." >&2
    fi
  fi
}

if [[ "$COST_ROLE_SCOPE" == "subscription" ]]; then
  COST_SCOPE="$SUB_SCOPE"
else
  COST_SCOPE="$RG_SCOPE"
fi

assign_role_if_missing "Reader" "$RG_SCOPE"
assign_role_if_missing "Monitoring Reader" "$RG_SCOPE"
assign_role_if_missing "Log Analytics Reader" "$RG_SCOPE"
assign_role_if_missing "Cost Management Reader" "$COST_SCOPE"
assign_role_if_missing "Key Vault Secrets User" "$KV_SCOPE"

DB_DSN_REFERENCE="@Microsoft.KeyVault(SecretUri=https://$KEY_VAULT_NAME.vault.azure.net/secrets/db-dsn/)"
KEY_VAULT_URL="https://$KEY_VAULT_NAME.vault.azure.net/"

echo "[INFO] Applying Function App settings"
az functionapp config appsettings set \
  --name "$FUNCTION_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --settings \
    "AZ_SUBSCRIPTION_ID=$SUBSCRIPTION_ID" \
    "AZ_RESOURCE_GROUP=$RESOURCE_GROUP" \
    "LOG_ANALYTICS_WORKSPACE_ID=$LOG_ANALYTICS_WORKSPACE_ID" \
    "KEY_VAULT_URL=$KEY_VAULT_URL" \
    "DB_DSN=$DB_DSN_REFERENCE" \
    "MONITORING_INVENTORY_CRON=$MONITORING_INVENTORY_CRON" \
    "MONITORING_HEALTH_CRON=$MONITORING_HEALTH_CRON" \
    "MONITORING_LOG_KPI_CRON=$MONITORING_LOG_KPI_CRON" \
    "MONITORING_COST_CRON=$MONITORING_COST_CRON" \
    "MONITORING_LOG_LEVEL=$MONITORING_LOG_LEVEL" \
    "MONITORING_INIT_SCHEMA=$MONITORING_INIT_SCHEMA" >/dev/null

echo "[DONE] Provisioning complete for $FUNCTION_APP_NAME"
echo "[NEXT] Deploy code with: ./scripts/monitoring/deploy_azure_ops_function.sh"
