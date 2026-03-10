#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.monitoring._common import ensure_env_loaded


LOG = logging.getLogger("monitoring.run_pipeline")

STEP_SCRIPTS = [
    "snapshot_resources.py",
    "collect_health_metrics.py",
    "collect_log_kpi.py",
    "collect_cost.py",
]


def _run_step(script_name: str, common_args: list[str]) -> None:
    cmd = [sys.executable, str(Path(__file__).resolve().parent / script_name), *common_args]
    LOG.info("Running %s", script_name)
    proc = subprocess.run(cmd, cwd=ROOT_DIR, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{script_name} failed with exit code {proc.returncode}")


def main() -> int:
    ensure_env_loaded()
    parser = argparse.ArgumentParser(description="Run monitoring collectors sequentially.")
    parser.add_argument(
        "--subscription",
        default="5bff8a75-037e-4d67-94cf-6fc62202174d",
        help="Azure subscription id",
    )
    parser.add_argument(
        "--resource-group",
        default="3dt-1st-team2",
        help="Azure resource group",
    )
    parser.add_argument(
        "--db-dsn",
        default="",
        help="PostgreSQL DSN override",
    )
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--init-schema", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="[%(levelname)s] %(message)s",
    )

    common_args = [
        "--subscription",
        args.subscription,
        "--resource-group",
        args.resource_group,
        "--log-level",
        args.log_level,
    ]
    if args.db_dsn:
        common_args.extend(["--db-dsn", args.db_dsn])
    if args.init_schema:
        common_args.append("--init-schema")
    if args.dry_run:
        common_args.append("--dry-run")

    for script_name in STEP_SCRIPTS:
        _run_step(script_name, common_args)
    LOG.info("All monitoring collection steps completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
