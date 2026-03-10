#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests


LOG = logging.getLogger("monitoring.powerbi_service_sync")
PBI_API_BASE = "https://api.powerbi.com/v1.0/myorg"


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or "unknown command error"
        raise RuntimeError(f"Command failed: {' '.join(cmd)} :: {msg}")
    return proc.stdout.strip()


def _get_powerbi_token() -> str:
    return _run(
        [
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
    )


def _request(method: str, path: str, token: str, **kwargs) -> requests.Response:
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    response = requests.request(method, f"{PBI_API_BASE}{path}", headers=headers, timeout=90, **kwargs)
    return response


def _get_workspace_id(token: str, workspace_name: str) -> str:
    r = _request("GET", "/groups", token)
    if r.status_code != 200:
        raise RuntimeError(f"Power BI groups 조회 실패: {r.status_code} {r.text[:300]}")
    for g in (r.json().get("value") or []):
        if str(g.get("name") or "") == workspace_name:
            gid = str(g.get("id") or "").strip()
            if gid:
                return gid
    raise RuntimeError(f"워크스페이스를 찾을 수 없습니다: {workspace_name}")


def _get_dataset(token: str, workspace_id: str, dataset_name: str) -> dict[str, Any]:
    r = _request("GET", f"/groups/{workspace_id}/datasets", token)
    if r.status_code != 200:
        raise RuntimeError(f"Dataset 목록 조회 실패: {r.status_code} {r.text[:300]}")
    for ds in (r.json().get("value") or []):
        if str(ds.get("name") or "") == dataset_name:
            return ds
    raise RuntimeError(f"Dataset을 찾을 수 없습니다: {dataset_name}")


def _import_pbix(token: str, workspace_id: str, pbix_path: Path, dataset_display_name: str) -> dict[str, Any]:
    if not pbix_path.exists():
        raise RuntimeError(f"PBIX 파일이 없습니다: {pbix_path}")
    path = (
        f"/groups/{workspace_id}/imports"
        f"?datasetDisplayName={requests.utils.quote(dataset_display_name)}"
        "&nameConflict=CreateOrOverwrite"
    )
    with pbix_path.open("rb") as f:
        files = {"file": (pbix_path.name, f, "application/octet-stream")}
        r = _request("POST", path, token, files=files)
    if r.status_code >= 400:
        raise RuntimeError(f"PBIX import 실패: {r.status_code} {r.text[:500]}")
    return r.json()


def _parse_dsn(dsn: str) -> tuple[str, str]:
    value = dsn.strip()
    if not value:
        return "", ""
    if "://" in value:
        parsed = urlparse(value)
        return unquote(parsed.username or ""), unquote(parsed.password or "")

    parts: dict[str, str] = {}
    for token in value.replace("\n", " ").split():
        if "=" not in token:
            continue
        k, v = token.split("=", 1)
        parts[k.strip().lower()] = v.strip()
    return parts.get("user") or parts.get("username") or "", parts.get("password") or ""


def _get_db_credentials_from_keyvault(key_vault_name: str, secret_name: str) -> tuple[str, str]:
    dsn = _run(
        [
            "az",
            "keyvault",
            "secret",
            "show",
            "--vault-name",
            key_vault_name,
            "--name",
            secret_name,
            "--query",
            "value",
            "-o",
            "tsv",
        ]
    )
    user, password = _parse_dsn(dsn)
    if not user or not password:
        raise RuntimeError("db-dsn에서 username/password 파싱 실패")
    return user, password


def _update_postgres_datasource_credentials(
    token: str,
    workspace_id: str,
    dataset_id: str,
    username: str,
    password: str,
) -> dict[str, Any]:
    ds_r = _request("GET", f"/groups/{workspace_id}/datasets/{dataset_id}/datasources", token)
    if ds_r.status_code != 200:
        raise RuntimeError(f"Datasource 조회 실패: {ds_r.status_code} {ds_r.text[:300]}")
    sources = ds_r.json().get("value") or []
    postgres = next(
        (s for s in sources if str(s.get("datasourceType") or "").lower() == "postgresql"),
        None,
    )
    if not postgres:
        raise RuntimeError("PostgreSql datasource를 찾지 못했습니다.")

    gateway_id = postgres["gatewayId"]
    datasource_id = postgres["datasourceId"]

    payload = {
        "credentialDetails": {
            "credentialType": "Basic",
            "credentials": json.dumps(
                {
                    "credentialData": [
                        {"name": "username", "value": username},
                        {"name": "password", "value": password},
                    ]
                },
                ensure_ascii=False,
            ),
            "encryptedConnection": "Encrypted",
            "encryptionAlgorithm": "None",
            "privacyLevel": "Organizational",
            "useEndUserOAuth2Credentials": False,
        }
    }
    patch_r = _request(
        "PATCH",
        f"/gateways/{gateway_id}/datasources/{datasource_id}",
        token,
        headers={"Content-Type": "application/json"},
        json=payload,
    )
    if patch_r.status_code >= 400:
        raise RuntimeError(f"Datasource credential 업데이트 실패: {patch_r.status_code} {patch_r.text[:400]}")

    check_r = _request("GET", f"/gateways/{gateway_id}/datasources/{datasource_id}", token)
    if check_r.status_code != 200:
        raise RuntimeError(f"Datasource credential 확인 실패: {check_r.status_code} {check_r.text[:300]}")
    return check_r.json()


def _execute_dax(token: str, workspace_id: str, dataset_id: str, dax_query: str) -> dict[str, Any]:
    body = {"queries": [{"query": dax_query}], "serializerSettings": {"includeNulls": True}}
    r = _request(
        "POST",
        f"/groups/{workspace_id}/datasets/{dataset_id}/executeQueries",
        token,
        headers={"Content-Type": "application/json"},
        json=body,
    )
    out: dict[str, Any] = {"status": r.status_code}
    try:
        payload = r.json() if r.text.strip() else {}
    except Exception:
        payload = {"raw": r.text[:500]}
    out["payload"] = payload
    return out


def _validate_model_columns(token: str, workspace_id: str, dataset_id: str) -> dict[str, Any]:
    checks = {
        "overview_table": "EVALUATE TOPN(1, 'monitoring vw_overview_latest')",
        "realtime_table": "EVALUATE TOPN(1, 'monitoring vw_realtime_kpi_1m')",
        "overview_stream_cols": (
            "EVALUATE SELECTCOLUMNS("
            "TOPN(1, 'monitoring vw_overview_latest'), "
            "\"stream_delay_seconds\", 'monitoring vw_overview_latest'[stream_delay_seconds], "
            "\"stream_event_count_1m\", 'monitoring vw_overview_latest'[stream_event_count_1m]"
            ")"
        ),
    }
    result: dict[str, Any] = {}
    for name, query in checks.items():
        result[name] = _execute_dax(token, workspace_id, dataset_id, query)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Power BI 서비스 semantic model 동기화 및 검증.")
    parser.add_argument("--workspace-name", default="AremArem-Azure-Ops")
    parser.add_argument("--dataset-name", default="3DT Azure Ops Semantic Base")
    parser.add_argument("--pbix-path", default="")
    parser.add_argument("--skip-import", action="store_true")
    parser.add_argument("--key-vault-name", default="kv3dt1stteam2dev01")
    parser.add_argument("--db-dsn-secret-name", default="db-dsn")
    parser.add_argument("--print-json", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="[%(levelname)s] %(message)s",
    )

    token = _get_powerbi_token()
    workspace_id = _get_workspace_id(token, args.workspace_name)

    import_info: dict[str, Any] | None = None
    if not args.skip_import:
        if not args.pbix_path.strip():
            raise RuntimeError("--pbix-path is required unless --skip-import is set")
        import_info = _import_pbix(
            token,
            workspace_id,
            Path(args.pbix_path),
            args.dataset_name,
        )

    dataset = _get_dataset(token, workspace_id, args.dataset_name)
    dataset_id = str(dataset["id"])

    user, password = _get_db_credentials_from_keyvault(args.key_vault_name, args.db_dsn_secret_name)
    credential_check = _update_postgres_datasource_credentials(
        token, workspace_id, dataset_id, user, password
    )
    validation = _validate_model_columns(token, workspace_id, dataset_id)

    output = {
        "workspace_name": args.workspace_name,
        "workspace_id": workspace_id,
        "dataset_name": args.dataset_name,
        "dataset_id": dataset_id,
        "import": import_info,
        "datasource_credential_check": {
            "datasourceType": credential_check.get("datasourceType"),
            "credentialType": credential_check.get("credentialType"),
            "privacyLevel": (credential_check.get("credentialDetails") or {}).get("privacyLevel"),
        },
        "model_validation": validation,
    }

    if args.print_json:
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    else:
        print(json.dumps(output, ensure_ascii=False, default=str))

    realtime_ok = (
        validation["realtime_table"]["status"] == 200
        and validation["overview_stream_cols"]["status"] == 200
    )
    return 0 if realtime_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
