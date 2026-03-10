#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.functions.azure_ops_monitoring_func.monitoring_jobs.collect_log_kpi import (  # noqa: E402
    _merge_kpi_rows,
    main,
    run,
)


if __name__ == "__main__":
    raise SystemExit(main())
