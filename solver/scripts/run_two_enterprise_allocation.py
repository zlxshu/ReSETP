#!/usr/bin/env python3
"""Run the frozen two-enterprise pyCoopGame accounting adapter."""

from __future__ import annotations

import argparse
import hashlib
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_json", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument("--repo-root", type=Path, required=True)
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
        "run_kind": "probe",
        "formal_reuse_allowed": False,
        "coalition_value_rows": coalition_value_rows(costs),
        "allocation": asdict(allocation),
        "provenance": {
            "snapshot_path": str(SOURCE_RELATIVE_PATH),
            "snapshot_sha256": _sha256(
                args.repo_root.resolve() / SOURCE_RELATIVE_PATH
            ),
            "source_commit": allocation.source_commit,
            "pandas_version": pandas.__version__,
            "python_version": platform.python_version(),
            "input_json_sha256": _sha256(args.input_json.resolve()),
            "input_hashes": payload["input_hashes"],
        },
    }
    args.output_json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
