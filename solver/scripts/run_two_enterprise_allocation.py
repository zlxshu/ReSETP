#!/usr/bin/env python3
"""Allocate the paper's two-enterprise joint cost with Shapley values."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from coalition_accounting_adapter import (
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
        "coalition_value_rows": coalition_value_rows(costs),
        "allocation": asdict(allocation),
    }
    args.output_json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
