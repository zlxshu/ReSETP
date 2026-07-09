"""Search adapters that connect algorithms only through cost.py and check.py.

Exports are lazy to avoid circular imports with the independent ALNS package
(``setp_solver.algorithms.resetp_alns``).
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "BIG_M",
    "EvalBudget",
    "EvaluationContext",
    "FleetLimits",
    "SearchBundle",
    "CandidateRunResult",
    "CandidateSmokeReport",
    "build_initial_solution",
    "dependency_status",
    "fleet_probe_diagnostic",
    "infer_fleet_limits",
    "introduce_ev_routes",
    "load_search_bundle",
    "penalized_obj",
    "random_key_to_solution",
    "repair_route_charging",
    "run_candidate",
    "run_independent_profit_baselines",
    "run_z1_smoke",
    "solve_charging",
    "solution_to_random_key",
    "vehicle_type_semantics_report",
]


def __getattr__(name: str) -> Any:
    if name in {"SearchBundle", "load_search_bundle"}:
        from .bundle import SearchBundle, load_search_bundle

        return {"SearchBundle": SearchBundle, "load_search_bundle": load_search_bundle}[name]
    if name in {
        "CandidateRunResult",
        "CandidateSmokeReport",
        "dependency_status",
        "random_key_to_solution",
        "run_candidate",
        "run_z1_smoke",
        "solution_to_random_key",
    }:
        from . import candidates as _candidates

        return getattr(_candidates, name)
    if name in {"repair_route_charging", "solve_charging"}:
        from .charging import repair_route_charging, solve_charging

        return {"repair_route_charging": repair_route_charging, "solve_charging": solve_charging}[name]
    if name in {"build_initial_solution", "introduce_ev_routes"}:
        from .construction import build_initial_solution, introduce_ev_routes

        return {"build_initial_solution": build_initial_solution, "introduce_ev_routes": introduce_ev_routes}[name]
    if name in {"BIG_M", "EvalBudget", "EvaluationContext", "penalized_obj"}:
        from .evaluation import BIG_M, EvalBudget, EvaluationContext, penalized_obj

        return {
            "BIG_M": BIG_M,
            "EvalBudget": EvalBudget,
            "EvaluationContext": EvaluationContext,
            "penalized_obj": penalized_obj,
        }[name]
    if name == "run_independent_profit_baselines":
        from .fairness import run_independent_profit_baselines

        return run_independent_profit_baselines
    if name in {"FleetLimits", "fleet_probe_diagnostic", "infer_fleet_limits", "vehicle_type_semantics_report"}:
        from .fleet import FleetLimits, fleet_probe_diagnostic, infer_fleet_limits, vehicle_type_semantics_report

        return {
            "FleetLimits": FleetLimits,
            "fleet_probe_diagnostic": fleet_probe_diagnostic,
            "infer_fleet_limits": infer_fleet_limits,
            "vehicle_type_semantics_report": vehicle_type_semantics_report,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
