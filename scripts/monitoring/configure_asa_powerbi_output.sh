#!/usr/bin/env bash
set -euo pipefail

# Configure ASA output to Power BI (replaces current output with same name).
# Required env vars:
#   AZ_RESOURCE_GROUP, ASA_JOB_NAME, ASA_OUTPUT_NAME,
#   PBI_GROUP_ID, PBI_GROUP_NAME, PBI_DATASET, PBI_TABLE,
#   PBI_REFRESH_TOKEN, PBI_TOKEN_USER_PRINCIPAL_NAME, PBI_TOKEN_USER_DISPLAY_NAME

RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-3dt-1st-team2}"
ASA_JOB_NAME="${ASA_JOB_NAME:-asa-3dt-ops-realtime}"
ASA_OUTPUT_NAME="${ASA_OUTPUT_NAME:-kpi-hub-v2}"

: "${PBI_GROUP_ID:?PBI_GROUP_ID is required}"
: "${PBI_GROUP_NAME:?PBI_GROUP_NAME is required}"
: "${PBI_DATASET:?PBI_DATASET is required}"
: "${PBI_TABLE:?PBI_TABLE is required}"
: "${PBI_REFRESH_TOKEN:?PBI_REFRESH_TOKEN is required}"
: "${PBI_TOKEN_USER_PRINCIPAL_NAME:?PBI_TOKEN_USER_PRINCIPAL_NAME is required}"
: "${PBI_TOKEN_USER_DISPLAY_NAME:?PBI_TOKEN_USER_DISPLAY_NAME is required}"

TMP_JSON="$(mktemp)"
trap 'rm -f "$TMP_JSON"' EXIT

cat > "$TMP_JSON" <<JSON
{
  "type": "PowerBI",
  "properties": {
    "groupId": "$PBI_GROUP_ID",
    "groupName": "$PBI_GROUP_NAME",
    "dataset": "$PBI_DATASET",
    "table": "$PBI_TABLE",
    "refreshToken": "$PBI_REFRESH_TOKEN",
    "tokenUserPrincipalName": "$PBI_TOKEN_USER_PRINCIPAL_NAME",
    "tokenUserDisplayName": "$PBI_TOKEN_USER_DISPLAY_NAME"
  }
}
JSON

az stream-analytics output create \
  --job-name "$ASA_JOB_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --name "$ASA_OUTPUT_NAME" \
  --datasource "@$TMP_JSON" >/dev/null

echo "[DONE] ASA output '$ASA_OUTPUT_NAME' updated to Power BI datasource"
