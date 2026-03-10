#!/usr/bin/env bash
set -euo pipefail

# Required tools: func, az
# Usage:
#   FUNCTION_APP_NAME=3dt-ops-monitoring-func ./scripts/monitoring/deploy_azure_ops_function.sh

FUNCTION_APP_NAME="${FUNCTION_APP_NAME:-3dt-ops-monitoring-func}"
FUNCTION_PROJECT_DIR="${FUNCTION_PROJECT_DIR:-src/functions/azure_ops_monitoring_func}"

if ! command -v func >/dev/null 2>&1; then
  echo "[ERROR] Azure Functions Core Tools (func) is required." >&2
  exit 1
fi

if ! command -v az >/dev/null 2>&1; then
  echo "[ERROR] az cli is required." >&2
  exit 1
fi

if [[ ! -f "$FUNCTION_PROJECT_DIR/function_app.py" ]]; then
  echo "[ERROR] function_app.py not found under $FUNCTION_PROJECT_DIR" >&2
  exit 1
fi

pushd "$FUNCTION_PROJECT_DIR" >/dev/null
func azure functionapp publish "$FUNCTION_APP_NAME" --python
popd >/dev/null

echo "[DONE] Deployed $FUNCTION_APP_NAME from $FUNCTION_PROJECT_DIR"
