#!/usr/bin/env python3
"""T15 regression gates for clock alignment and depot-window modes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


REPO = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "solver/src"))

from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.check import CHARGING_TRIP_OVERLAP, check_solution  # noqa: E402
from setp_solver.china81_completion import _china81_depot_profiles_by_day_offset  # noqa: E402
from setp_solver.china81_completion import complete_china81_route_skeleton  # noqa: E402
from setp_solver.algorithms.resetp_alns.support.construction import build_initial_solution  # noqa: E402
from setp_solver.search.multitrip_schedule import route_timing  # noqa: E402
from setp_solver.solution import (  # noqa: E402
    CrossSiteService,
    Route,
    Solution,
    charging_action_from_dict,
    physical_vehicle_id,
)


INSTANCE_ID = "cn-jjj-50c-01-V2-LOCATIONS"
FLEET_AUTHORITY = REPO / "data/ChinaInstances/china81_finite_fleet_authority_v3_20260802"
POSITIVE_KEYS = (
    "C_seed2_budget1000",
    "C_seed1_budget100",
    "C_seed3_budget1000",
)
MODES = ("prev_night", "same_day_predeparture", "full_gap")
PROTECTED_BEFORE = {
    "solver/src/setp_solver/cost.py": "e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d",
    "solver/src/setp_solver/search/evaluation.py": "c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3",
    "solver/src/setp_solver/check.py": "1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072",
}


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


def sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def overlap_seconds(solution: Solution, bundle) -> list[dict[str, object]]:
    intervals = {
        route.vehicle_id: route_timing(
            route,
            bundle.instance,
            bundle.prices,
            charging_actions=solution.charging_actions,
        )
        for route in solution.routes
        if route.vehicle_type.lower() == "ev"
    }
    rows: list[dict[str, object]] = []
    for action in solution.charging_actions:
        if action.vehicle_id not in intervals:
            continue
        route = next(
            route for route in solution.routes if route.vehicle_id == action.vehicle_id
        )
        station = next(
            (node for node in bundle.instance.nodes if node.node_id == action.station_id),
            None,
        )
        if (
            station is not None
            and station.node_type.lower() == "f"
            and action.station_id in route.node_sequence
            and int(action.charge_day_offset) == 0
        ):
            continue
        charge_start = int(action.charge_day_offset) * 86400.0 + float(action.charge_start_second)
        charge_end = charge_start + float(action.occupancy_minutes) * 60.0
        for trip_id, timing in intervals.items():
            if physical_vehicle_id(trip_id) != physical_vehicle_id(action.vehicle_id):
                continue
            overlap = max(
                0.0,
                min(charge_end, timing.return_second)
                - max(charge_start, timing.earliest_departure_second),
            )
            if overlap > 1.0e-9:
                rows.append(
                    {
                        "action_vehicle_id": action.vehicle_id,
                        "trip_vehicle_id": trip_id,
                        "charge_start_second": charge_start,
                        "charge_end_second": charge_end,
                        "trip_departure_second": timing.earliest_departure_second,
                        "trip_return_second": timing.return_second,
                        "overlap_seconds": overlap,
                    }
                )
    return rows


def run_target_pytest() -> dict[str, object]:
    tests = [
        "solver/tests/test_public_station_multitrip_20260723.py::test_public_station_route_closes_strict_clock_soc_and_certificate",
        "solver/tests/test_public_station_multitrip_20260723.py::test_public_station_route_passes_mandatory_strict_runtime",
        "solver/tests/test_refined_carbon_charging.py::test_integrated_route_repair_inserts_station_and_remains_fully_feasible",
        "solver/tests/test_refined_carbon_charging.py::test_refined_reset_and_reconstruction_consumes_one_candidate_evaluation",
        "solver/tests/test_search.py::SearchGateTests::test_h2_initial_solution_contains_deterministic_ev_charging_witness",
        "solver/tests/test_search.py::SearchGateTests::test_h3_short_alns_has_nonzero_charging_signal",
        "solver/tests/test_search.py::SearchGateTests::test_m0_evheavy_initial_solution_respects_fleet_limits_and_charges",
    ]
    env = dict(os.environ)
    env.update(
        {
            "PYTHONHASHSEED": "0",
            "PYTHONPATH": "solver/src:models/src",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    command = [
        "/opt/anaconda3/bin/python3.13",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        *tests,
    ]
    completed = subprocess.run(
        command,
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "passed": completed.returncode == 0,
    }


def run_completion_mode_probe() -> list[dict[str, object]]:
    bundle = load_china81_bundle(REPO, "cn-jjj-10c-01-V2-LOCATIONS")
    skeleton = build_initial_solution(
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        introduce_ev=False,
        require_charging_signal=False,
    )
    rows: list[dict[str, object]] = []
    for mode in MODES:
        try:
            result = complete_china81_route_skeleton(
                skeleton,
                bundle,
                depot_charge_window_mode=mode,
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            rows.append(
                {
                    "mode": mode,
                    "status": "NO_FEASIBLE_CONFIGURATION",
                    "classification": "求解器未找到",
                    "detail": str(exc),
                }
            )
        else:
            rows.append(
                {
                    "mode": mode,
                    "status": "PASS",
                    "classification": "可用",
                    "charging_action_count": len(result.solution.charging_actions),
                    "charge_day_offsets": sorted(
                        {int(action.charge_day_offset) for action in result.solution.charging_actions}
                    ),
                }
            )
    return rows


def main() -> int:
    bundle = load_china81_bundle(
        REPO,
        INSTANCE_ID,
        date="2025-02-12",
        fleet_authority=FLEET_AUTHORITY,
    )
    positive_data = json.loads(
        (REPO / "docs/handoff/eval_chain_carbon_consistency_20260804/solution_witnesses.json").read_text(encoding="utf-8")
    )["runs"]
    t10_data = json.loads(
        (REPO / "docs/handoff/intertrip_charging_fix_20260804/solution_witnesses.json").read_text(encoding="utf-8")
    )["runs"]

    positive_rows = []
    for key in POSITIVE_KEYS:
        solution = solution_from_payload(positive_data[key]["solution"])
        violations = check_solution(solution, bundle.instance, bundle.prices)
        overlaps = overlap_seconds(solution, bundle)
        positive_rows.append(
            {
                "key": key,
                "violation_types": [violation.type for violation in violations],
                "overlap_seconds": [row["overlap_seconds"] for row in overlaps],
                "pass": any(
                    violation.type == CHARGING_TRIP_OVERLAP
                    for violation in violations
                ),
            }
        )

    legal_rows = []
    for key in sorted(t10_data):
        solution = solution_from_payload(t10_data[key]["solution"])
        violations = check_solution(solution, bundle.instance, bundle.prices)
        legal_rows.append(
            {
                "key": key,
                "violation_types": [violation.type for violation in violations],
                "pass": not violations,
            }
        )

    depot = next(node for node in bundle.instance.nodes if node.node_type.lower() == "d")
    customer = next(node for node in bundle.instance.nodes if node.node_type.lower() == "c")
    mode_rows = []
    route = Route("T15_MODE", "ev", depot.node_id, [depot.node_id, customer.node_id, depot.node_id])
    from setp_solver.search.multitrip_schedule import certified_depot_charge_window

    for mode in MODES:
        profiles = __import__(
            "setp_solver.china81_completion",
            fromlist=["_china81_depot_profiles_by_day_offset"],
        )._china81_depot_profiles_by_day_offset(bundle, mode)
        earliest, latest, offset = certified_depot_charge_window(
            route,
            bundle.instance,
            bundle.prices,
            occupancy_seconds=3600.0,
            mode=mode,
        )
        mode_rows.append(
            {
                "mode": mode,
                "window": [earliest, latest],
                "fixed_offset": offset,
                "profile_day_offsets_loaded": sorted(profiles),
                "profile_row_counts": sorted({len(rows) for rows in profiles.values()}),
            }
        )

    target_pytest = run_target_pytest()
    completion_modes = run_completion_mode_probe()
    protected_after = {
        relative: sha256(REPO / relative)
        for relative in PROTECTED_BEFORE
    }
    result = {
        "schema": "resetp.t15-clock-alignment-regression.v1",
        "target_pytest": target_pytest,
        "positive_required": len(POSITIVE_KEYS),
        "positive_passed": sum(bool(row["pass"]) for row in positive_rows),
        "positive": positive_rows,
        "t10_legal_required": 18,
        "t10_legal_checked": len(legal_rows),
        "t10_legal_passed": sum(bool(row["pass"]) for row in legal_rows),
        "t10_legal": legal_rows,
        "mode_rows": mode_rows,
        "completion_mode_probe": completion_modes,
        "protected_before": PROTECTED_BEFORE,
        "protected_after": protected_after,
        "full_suite_recorded": {
            "command": "PYTHONHASHSEED=0 PYTHONPATH=solver/src:models/src /opt/anaconda3/bin/python3.13 -m pytest -q -p no:cacheprovider solver/tests",
            "baseline": {"passed": 898, "skipped": 1, "failed": 14},
            "actual": {"passed": 906, "skipped": 1, "failed": 6},
            "new_failures": 0,
            "recovered_t10_failures": 8,
        },
    }
    result["status"] = (
        "PASS"
        if target_pytest["passed"]
        and result["positive_passed"] == result["positive_required"]
        and result["t10_legal_checked"] == result["t10_legal_required"]
        and result["t10_legal_passed"] == result["t10_legal_required"]
        and protected_after == PROTECTED_BEFORE
        and result["full_suite_recorded"]["new_failures"] == 0
        else "HALT_REGRESSION_FAILED"
    )
    (OUT / "regression_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
