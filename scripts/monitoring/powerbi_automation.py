#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


LOG = logging.getLogger("monitoring.powerbi_automation")
PBI_API_BASE = "https://api.powerbi.com/v1.0/myorg"


def _get_powerbi_token() -> str:
    cmd = [
        "az",
        "account",
        "get-access-token",
        "--resource",
        "https://analysis.windows.net/powerbi/api",
        "--query",
        "accessToken",
        "-o",
        "tsv",
    ]
    proc = subprocess.run(cmd, check=False, text=True, capture_output=True)
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"Failed to get Power BI token: {msg}")
    token = proc.stdout.strip()
    if not token:
        raise RuntimeError("Power BI access token is empty.")
    return token


def _request(method: str, path: str, token: str, **kwargs) -> Any:
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    response = requests.request(method, f"{PBI_API_BASE}{path}", headers=headers, timeout=60, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(
            f"Power BI API error {response.status_code} for {method} {path}: {response.text[:500]}"
        )
    if response.text.strip():
        return response.json()
    return {}


def list_groups(token: str) -> list[dict[str, Any]]:
    data = _request("GET", "/groups", token)
    groups = data.get("value") or []
    return groups


def ensure_workspace(token: str, workspace_name: str) -> dict[str, Any]:
    for group in list_groups(token):
        if str(group.get("name") or "") == workspace_name:
            LOG.info("Workspace already exists: %s (%s)", workspace_name, group.get("id"))
            return group

    payload = {"name": workspace_name}
    created = _request("POST", "/groups?workspaceV2=true", token, json=payload)
    LOG.info("Workspace created: %s (%s)", workspace_name, created.get("id"))
    return created


def import_pbix(token: str, workspace_id: str, pbix_path: Path, dataset_display_name: str) -> dict[str, Any]:
    if not pbix_path.exists():
        raise RuntimeError(f"PBIX file not found: {pbix_path}")
    path = (
        f"/groups/{workspace_id}/imports"
        f"?datasetDisplayName={quote(dataset_display_name)}"
        "&nameConflict=CreateOrOverwrite"
    )
    with pbix_path.open("rb") as f:
        files = {"file": (pbix_path.name, f, "application/octet-stream")}
        return _request("POST", path, token, files=files)


def list_datasets(token: str, workspace_id: str) -> list[dict[str, Any]]:
    data = _request("GET", f"/groups/{workspace_id}/datasets", token)
    return data.get("value") or []


def refresh_datasets(token: str, workspace_id: str) -> int:
    datasets = list_datasets(token, workspace_id)
    count = 0
    for ds in datasets:
        dataset_id = ds.get("id")
        if not dataset_id:
            continue
        _request("POST", f"/groups/{workspace_id}/datasets/{dataset_id}/refreshes", token, json={})
        LOG.info("Triggered refresh dataset=%s name=%s", dataset_id, ds.get("name"))
        count += 1
    return count


def _workspace_id_from_name(token: str, name: str) -> str:
    for group in list_groups(token):
        if str(group.get("name") or "") == name:
            gid = str(group.get("id") or "").strip()
            if gid:
                return gid
    raise RuntimeError(f"Workspace not found: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Power BI workspace/import/refresh automation.")
    parser.add_argument("--workspace-name", default="3DT-Azure-Ops")
    parser.add_argument("--workspace-id", default="")
    parser.add_argument("--pbix-path", default="")
    parser.add_argument("--dataset-display-name", default="3DT-Azure-Ops")
    parser.add_argument(
        "--action",
        required=True,
        choices=[
            "list-groups",
            "ensure-workspace",
            "import-pbix",
            "refresh-datasets",
            "list-datasets",
        ],
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="[%(levelname)s] %(message)s",
    )
    token = _get_powerbi_token()

    if args.action == "list-groups":
        groups = list_groups(token)
        print(json.dumps(groups, ensure_ascii=False, indent=2))
        return 0

    if args.action == "ensure-workspace":
        group = ensure_workspace(token, args.workspace_name)
        print(json.dumps(group, ensure_ascii=False, indent=2))
        return 0

    workspace_id = args.workspace_id.strip()
    if not workspace_id:
        workspace_id = _workspace_id_from_name(token, args.workspace_name)

    if args.action == "list-datasets":
        datasets = list_datasets(token, workspace_id)
        print(json.dumps(datasets, ensure_ascii=False, indent=2))
        return 0

    if args.action == "import-pbix":
        if not args.pbix_path:
            raise RuntimeError("--pbix-path is required for import-pbix")
        result = import_pbix(token, workspace_id, Path(args.pbix_path), args.dataset_display_name)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.action == "refresh-datasets":
        count = refresh_datasets(token, workspace_id)
        LOG.info("Triggered refresh for %d datasets.", count)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

