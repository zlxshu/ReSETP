#!/usr/bin/env python3
"""T7 validation runner: the frozen T5 matrix with the T7 wiring repair."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[3]
T5_PATH = REPO / "docs/handoff/carbon_objective_probe_20260804/probe_driver.py"
T7_OUT = Path(__file__).resolve().parent


def load_t5_module():
    spec = importlib.util.spec_from_file_location("t5_carbon_probe", T5_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load probe module from {T5_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


t5 = load_t5_module()
t5.OUT = T7_OUT
t5.TASK_ID = "T7-EVAL-CHAIN-CARBON-CONSISTENCY"
t5.SCHEMA = "resetp.t7-eval-chain-carbon-consistency-runner.v1"
t5.MARKER = "TECHNICAL_FIX_VALIDATION"
t5.PREREGISTRATION = T7_OUT / "preregistration.json"

_original_run_one = t5.run_one
_extra_fields = (
    "search_side_objective_cny",
    "search_side_operating_cost_cny",
    "search_side_charging_emissions_kg",
    "search_side_charging_cost_cny",
    "final_evaluation_charging_emissions_kg",
    "final_evaluation_charging_cost_cny",
)


def _solution_from_payload(payload):
    from setp_solver.solution import (
        CrossSiteService,
        Route,
        Solution,
        charging_action_from_dict,
    )

    return Solution(
        routes=[Route(**item) for item in payload["routes"]],
        charging_actions=[
            charging_action_from_dict(item)
            for item in payload["charging_actions"]
        ],
        cross_site_services=[
            CrossSiteService(**item)
            for item in payload["cross_site_services"]
        ],
    )


def run_one_with_chain_fields(**kwargs):
    row, trace, slots, witness = _original_run_one(**kwargs)
    solution = _solution_from_payload(witness["solution"])
    search_objective, search_breakdown, search_violations = (
        t5.exact_china81_score(solution, kwargs["search_bundle"])
    )
    if search_violations:
        raise RuntimeError(
            f"{witness['run_id']} search-side recheck failed: "
            f"{search_violations!r}"
        )
    row = dict(row)
    row.update(
        {
            "search_side_objective_cny": float(search_objective),
            "search_side_operating_cost_cny": float(
                search_objective - search_breakdown["cost_carbon"]
            ),
            "search_side_charging_emissions_kg": float(
                search_breakdown["E_ev_indirect"]
            ),
            "search_side_charging_cost_cny": float(
                search_breakdown["cost_elec"]
            ),
            "final_evaluation_charging_emissions_kg": float(
                row["charging_emissions_kg"]
            ),
            "final_evaluation_charging_cost_cny": float(
                row["charging_cost_cny"]
            ),
        }
    )
    return row, trace, slots, witness


t5.run_one = run_one_with_chain_fields
t5.RUN_FIELDS = tuple(t5.RUN_FIELDS) + _extra_fields


if __name__ == "__main__":
    sys.argv = [str(Path(__file__)), "--run"]
    raise SystemExit(t5.main())
