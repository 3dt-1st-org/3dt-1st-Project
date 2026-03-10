#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path


REQUIRED_NODE_INDEXES = {
    "monitoring vw_overview_latest",
    "monitoring vw_service_health_5m",
    "monitoring vw_realtime_kpi_1m",
    "monitoring vw_cost_burn_daily",
    "monitoring vw_incidents_5m",
}


def _load_diagram_layout(pbix_path: Path) -> dict:
    with zipfile.ZipFile(pbix_path, "r") as zf:
        raw = zf.read("DiagramLayout")
    text = raw.decode("utf-16-le")
    return json.loads(text)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check whether PBIX diagram model contains required monitoring views."
    )
    parser.add_argument(
        "--pbix-path",
        default="Arem Arem Azure Ops Semantic Model.pbix",
        help="PBIX path to inspect.",
    )
    args = parser.parse_args()

    pbix_path = Path(args.pbix_path)
    if not pbix_path.exists():
        raise RuntimeError(f"PBIX file not found: {pbix_path}")

    diagram = _load_diagram_layout(pbix_path)
    nodes: set[str] = set()
    for d in diagram.get("diagrams") or []:
        for node in d.get("nodes") or []:
            node_index = str(node.get("nodeIndex") or "").strip()
            if node_index:
                nodes.add(node_index)

    missing = sorted(REQUIRED_NODE_INDEXES - nodes)
    result = {
        "pbix_path": str(pbix_path),
        "missing_model_nodes": missing,
        "required_count": len(REQUIRED_NODE_INDEXES),
        "found_count": len(nodes),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
