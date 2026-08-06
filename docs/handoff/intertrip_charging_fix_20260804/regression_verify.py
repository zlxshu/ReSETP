#!/usr/bin/env python3
"""T10 hard-gate regressions for the repaired checker.

This script calls ``check_solution`` directly.  T9's overlap result is used
only to select the required historical positive and negative witnesses; it is
not used as a substitute for the repaired checker.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import sys


os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
REPO = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "solver/src"))

from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.check import CHARGING_TRIP_OVERLAP, check_solution  # noqa: E402
from setp_solver.solution import (  # noqa: E402
    CrossSiteService,
    Route,
    Solution,
    charging_action_from_dict,
)


INSTANCE_ID = "cn-jjj-50c-01-V2-LOCATIONS"
POSITIVE_KEYS = (
    "C_seed2_budget1000",
    "C_seed1_budget100",
    "C_seed3_budget1000",
)
T9_RAW = REPO / "docs/handoff/intertrip_overlap_scan_20260804/raw_runs.csv"
T9_WITNESSES = REPO / "docs/handoff/eval_chain_carbon_consistency_20260804/solution_witnesses.json"
T10_AUTHORITY = REPO / "data/ChinaInstances/china81_finite_fleet_authority_v3_20260802"


def solution_from_payload(payload: dict[str, object]) -> Solution:
    return Solution(
        routes=[Route(**row) for row in payload["routes"]],
        charging_actions=[
            charging_action_from_dict(row)
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(**row)
            for row in payload.get("cross_site_services", [])
        ],
    )


def load_t9_solution(row: dict[str, str], cache: dict[Path, object]) -> Solution:
    source = REPO / row["source_file"]
    if source not in cache:
        cache[source] = json.loads(source.read_text(encoding="utf-8"))
    current: object = cache[source]
    for token in row["solution_locator"].split("/"):
        if token == "solution":
            if not isinstance(current, dict):
                raise TypeError("solution locator does not resolve to a run object")
            current = current["solution"]
            break
        if token.startswith("["):
            current = current[int(token[1:-1])]  # type: ignore[index]
        else:
            current = current[token]  # type: ignore[index]
    if not isinstance(current, dict):
        raise TypeError("T9 locator did not resolve to a solution payload")
    return solution_from_payload(current)


def main() -> int:
    bundle = load_china81_bundle(
        REPO,
        INSTANCE_ID,
        date="2025-02-12",
        fleet_authority=T10_AUTHORITY,
    )
    witness_data = json.loads(T9_WITNESSES.read_text(encoding="utf-8"))
    positive_rows = []
    for key in POSITIVE_KEYS:
        solution = solution_from_payload(witness_data["runs"][key]["solution"])
        violations = check_solution(solution, bundle.instance, bundle.prices)
        positive_rows.append(
            {
                "key": key,
                "violation_types": [violation.type for violation in violations],
                "charging_trip_overlap_count": sum(
                    violation.type == CHARGING_TRIP_OVERLAP
                    for violation in violations
                ),
                "pass": any(
                    violation.type == CHARGING_TRIP_OVERLAP
                    for violation in violations
                ),
            }
        )

    legal_rows = []
    t9_cache: dict[Path, object] = {}
    with T9_RAW.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if (
                row["instance_id"] != INSTANCE_ID
                or row["prefilter_pass"] != "true"
                or row["solution_status"] != "CERTIFICATE_PASS"
                or row["overlap_action_count"] != "0"
            ):
                continue
            solution = load_t9_solution(row, t9_cache)
            violations = check_solution(solution, bundle.instance, bundle.prices)
            legal_rows.append(
                {
                    "solution_locator": row["solution_locator"],
                    "violation_types": [violation.type for violation in violations],
                    "pass": not violations,
                }
            )
            if len(legal_rows) >= 20:
                break

    result = {
        "schema": "resetp.t10-intertrip-charging-fix-regression.v1",
        "positive_required": len(POSITIVE_KEYS),
        "positive_passed": sum(row["pass"] for row in positive_rows),
        "positive": positive_rows,
        "legal_required": 20,
        "legal_checked": len(legal_rows),
        "legal_passed": sum(row["pass"] for row in legal_rows),
        "legal": legal_rows,
        "status": (
            "PASS"
            if len(positive_rows) == len(POSITIVE_KEYS)
            and all(row["pass"] for row in positive_rows)
            and len(legal_rows) >= 20
            and all(row["pass"] for row in legal_rows)
            else "HALT_REGRESSION_FAILED"
        ),
    }
    (OUT / "regression_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
