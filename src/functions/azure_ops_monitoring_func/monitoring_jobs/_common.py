from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[4]
DDL_FILE = ROOT_DIR / "sql" / "ddl" / "create_monitoring_powerbi_ops_tables.sql"
VIEW_DDL_FILE = ROOT_DIR / "sql" / "ddl" / "create_monitoring_powerbi_views.sql"


_LOG = logging.getLogger("monitoring.jobs.common")
_CREDENTIAL = None


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="[%(levelname)s] %(message)s",
    )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_args_base(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--subscription",
        default=os.getenv("AZ_SUBSCRIPTION_ID", "5bff8a75-037e-4d67-94cf-6fc62202174d"),
        help="Azure subscription id",
    )
    parser.add_argument(
        "--resource-group",
        default=os.getenv("AZ_RESOURCE_GROUP", "3dt-1st-team2"),
        help="Azure resource group name",
    )
    parser.add_argument(
        "--db-dsn",
        default=(os.getenv("DB_DSN") or "").strip(),
        help="PostgreSQL DSN (defaults to DB_DSN env or Key Vault db-dsn)",
    )
    parser.add_argument(
        "--init-schema",
        action="store_true",
        help="Apply monitoring schema DDL before writing records.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect and print summary without writing to DB.",
    )
    return parser


def ensure_env_loaded() -> None:
    load_dotenv()


def _az_available() -> bool:
    return shutil.which("az") is not None


def run_az(args: Iterable[str], expect_json: bool = True) -> Any:
    if not _az_available():
        raise RuntimeError("az cli is not available in this environment.")

    cmd = ["az", *args]
    if expect_json and "-o" not in cmd and "--output" not in cmd:
        cmd.extend(["-o", "json"])

    proc = subprocess.run(
        cmd,
        check=False,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or "unknown az cli error"
        raise RuntimeError(f"az command failed: {' '.join(cmd)} :: {msg}")

    out = proc.stdout.strip()
    if not expect_json:
        return out
    if not out:
        return {}
    return json.loads(out)


def set_subscription(subscription_id: str) -> None:
    if not subscription_id or not _az_available():
        return
    run_az(["account", "set", "--subscription", subscription_id], expect_json=False)


def _get_credential():
    global _CREDENTIAL
    if _CREDENTIAL is None:
        from azure.identity import DefaultAzureCredential

        _CREDENTIAL = DefaultAzureCredential(exclude_interactive_browser_credential=False)
    return _CREDENTIAL


def _azure_rest(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    scope: str = "https://management.azure.com/.default",
) -> dict[str, Any]:
    token = _get_credential().get_token(scope).token
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    response = requests.request(
        method=method.upper(),
        url=url,
        params=params,
        json=body,
        headers=headers,
        timeout=45,
    )
    if response.status_code >= 400:
        detail = response.text.strip()
        raise RuntimeError(f"Azure REST call failed: {response.status_code} {url} :: {detail}")
    if not response.text.strip():
        return {}
    return response.json()


def list_resources(subscription_id: str, resource_group: str) -> list[dict[str, Any]]:
    if _az_available():
        query = "[].{id:id,name:name,type:type,kind:kind,location:location,tags:tags}"
        rows = run_az(["resource", "list", "-g", resource_group, "--query", query], expect_json=True)
        if not isinstance(rows, list):
            raise RuntimeError("Unexpected az resource list output.")
        return rows

    url = (
        "https://management.azure.com"
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/resources"
    )
    params: dict[str, Any] | None = {"api-version": "2021-04-01"}
    rows: list[dict[str, Any]] = []

    while url:
        payload = _azure_rest("GET", url, params=params)
        params = None
        for item in payload.get("value") or []:
            rows.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "type": item.get("type"),
                    "kind": item.get("kind"),
                    "location": item.get("location"),
                    "tags": item.get("tags") or {},
                }
            )
        url = str(payload.get("nextLink") or "").strip()
    return rows


def list_metrics(
    resource_id: str,
    metric_names: list[str],
    start_iso: str,
    end_iso: str,
    *,
    interval: str = "PT5M",
    aggregations: list[str] | None = None,
) -> dict[str, Any]:
    if aggregations is None:
        aggregations = ["Average", "Total", "Maximum"]

    if _az_available():
        return run_az(
            [
                "monitor",
                "metrics",
                "list",
                "--resource",
                resource_id,
                "--metric",
                *metric_names,
                "--interval",
                interval,
                "--start-time",
                start_iso,
                "--end-time",
                end_iso,
                "--aggregation",
                *aggregations,
            ],
            expect_json=True,
        )

    url = f"https://management.azure.com{resource_id}/providers/microsoft.insights/metrics"
    params = {
        "api-version": "2023-10-01",
        "metricnames": ",".join(metric_names),
        "timespan": f"{start_iso}/{end_iso}",
        "interval": interval,
        "aggregation": ",".join(aggregations),
    }
    return _azure_rest("GET", url, params=params)


def query_log_analytics(workspace_id: str, kql: str) -> Any:
    if _az_available():
        return run_az(
            [
                "monitor",
                "log-analytics",
                "query",
                "-w",
                workspace_id,
                "--analytics-query",
                kql,
            ],
            expect_json=True,
        )

    url = f"https://api.loganalytics.azure.com/v1/workspaces/{workspace_id}/query"
    return _azure_rest(
        "POST",
        url,
        body={"query": kql},
        scope="https://api.loganalytics.io/.default",
    )


def query_cost_management(subscription_id: str, resource_group: str, body: dict[str, Any]) -> dict[str, Any]:
    if _az_available():
        url = (
            "https://management.azure.com"
            f"/subscriptions/{subscription_id}"
            f"/resourceGroups/{resource_group}"
            "/providers/Microsoft.CostManagement/query"
            "?api-version=2023-03-01"
        )
        return run_az(
            [
                "rest",
                "--method",
                "post",
                "--url",
                url,
                "--body",
                json.dumps(body),
            ],
            expect_json=True,
        )

    url = (
        "https://management.azure.com"
        f"/subscriptions/{subscription_id}"
        f"/resourceGroups/{resource_group}"
        "/providers/Microsoft.CostManagement/query"
    )
    return _azure_rest("POST", url, params={"api-version": "2023-03-01"}, body=body)


def get_db_dsn(explicit_dsn: str = "") -> str:
    if explicit_dsn.strip():
        return explicit_dsn.strip()

    env_dsn = (os.getenv("DB_DSN") or "").strip()
    if env_dsn:
        return env_dsn

    from config.vault_manager import vault  # lazy import

    secret_dsn = (vault.get_secret("db-dsn") or "").strip()
    if secret_dsn:
        return secret_dsn
    raise RuntimeError("DB_DSN is required (env or Key Vault 'db-dsn').")


def get_connection(dsn: str):
    import psycopg2

    return psycopg2.connect(dsn, connect_timeout=5)


def ensure_schema(conn) -> None:
    if not DDL_FILE.exists():
        raise RuntimeError(f"DDL file not found: {DDL_FILE}")
    if not VIEW_DDL_FILE.exists():
        raise RuntimeError(f"View DDL file not found: {VIEW_DDL_FILE}")

    sql = DDL_FILE.read_text(encoding="utf-8")
    view_sql = VIEW_DDL_FILE.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
        cur.execute(view_sql)
    conn.commit()
