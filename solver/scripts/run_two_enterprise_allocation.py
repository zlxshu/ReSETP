#!/usr/bin/env python3
"""Run the frozen two-enterprise pyCoopGame accounting adapter."""

from __future__ import annotations

import argparse
import json
import platform
from dataclasses import asdict
from pathlib import Path

import pandas

from coalition_accounting_adapter import (
    SOURCE_RELATIVE_PATH,
    TwoEnterpriseCoalitionCosts,
    TwoEnterpriseParticipationInputs,
    allocate_two_enterprise_costs,
    coalition_value_rows,
)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_json", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument(
        "--run-kind",
        choices=("probe", "formal"),
        default="probe",
    )
    args = parser.parse_args()
    payload = json.loads(args.input_json.read_text(encoding="utf-8"))
    costs = TwoEnterpriseCoalitionCosts(**payload["costs"])
    participation = TwoEnterpriseParticipationInputs(**payload["participation"])
    allocation = allocate_two_enterprise_costs(
        costs,
        participation,
        repo_root=args.repo_root.resolve(),
    )
    result = {
        "schema": "resetp.two_enterprise_shapley.v1",
        "run_kind": args.run_kind,
        "formal_reuse_allowed": args.run_kind == "formal",
        "coalition_value_rows": coalition_value_rows(costs),
        "allocation": asdict(allocation),
        "provenance": {
            "snapshot_path": str(SOURCE_RELATIVE_PATH),
            "pandas_version": pandas.__version__,
            "python_version": platform.python_version(),
        },
    }
    args.output_json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
