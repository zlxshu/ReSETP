"""Search adapters that connect algorithms only through cost.py and check.py."""

from .bundle import SearchBundle, load_search_bundle
from .candidates import (
    CandidateRunResult,
    CandidateSmokeReport,
    dependency_status,
    random_key_to_solution,
    run_candidate,
    run_z1_smoke,
    solution_to_random_key,
)
from .charging import repair_route_charging, solve_charging
from .construction import build_initial_solution, introduce_ev_routes
from .evaluation import BIG_M, EvalBudget, EvaluationContext, penalized_obj
from .fairness import run_independent_profit_baselines
from .fleet import FleetLimits, fleet_probe_diagnostic, infer_fleet_limits, vehicle_type_semantics_report

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
