#!/usr/bin/env python3
"""Run XB: the five-level formal China81 fleet-electrification experiment.

The formal unit is one (fleet level, seed) pair.  Each unit runs the same
MV-HGS-SP search twice: once with the registered China81 carbon price and once
with the carbon price set to zero.  The latter is the carbon-blind baseline.
Both arms retain the same time-varying electricity tariff and physical model.

This file is additive.  It does not modify any existing solver, result, or
paper file.  The final exact decoder/checker always uses the registered v3
per-depot caps; the endpoint-only proxy shim merely allows the route-skeleton
generator to operate when one physical vehicle type has an exact cap of zero.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from datetime import UTC, datetime
import csv
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import traceback
from types import MappingProxyType
from typing import Any, Iterable


RUNNER = Path(__file__).resolve()
REPO = RUNNER.parents[2]
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
)
for path in (REPO, REPO / "solver/src", PROTOTYPE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import epochal_hgs  # type: ignore  # noqa: E402
import pyvrp_adapter  # type: ignore  # noqa: E402
import route_pool_sp  # type: ignore  # noqa: E402
from pyvrp.stop import MaxIterations, MultipleCriteria, NoImprovement  # noqa: E402

from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import exact_china81_score  # noqa: E402
from setp_solver.model_config import (  # noqa: E402
    DEPOT_CHARGER_CAPACITY_UNBOUNDED,
    ModelConfig,
    model_config_scope,
)
from setp_solver.solution import (  # noqa: E402
    Route,
    Solution,
    physical_vehicle_id,
)


TASK_ID = "XB"
TERMINAL_STATUS = "XB_FLEET_LEVELS_FORMAL_COMPLETE"
INSTANCE_ID = "cn-prd-100c-01-V2-LOCATIONS"
LEVELS = (0, 25, 50, 75, 100)
SEEDS = tuple(range(1, 11))
MAX_ITERATIONS = 2_000
MAX_NO_IMPROVEMENT = 150
HGS_VIEWS = ("cv_only", "naive_ev", "mechanism_ev")
EXACT_ELITES_PER_VIEW = 8
ARCHIVE_CANDIDATES_PER_VIEW = 24
SP_TIME_LIMIT_SECONDS = 5.0
WALLCLOCK_SAFETY_SECONDS_PER_VIEW = 86_400.0
CARBON_AWARE = "COST_PLUS_CARBON"
CARBON_BLIND = "COST_ONLY"
ARM_ORDER = (CARBON_BLIND, CARBON_AWARE)
TOL = 1.0e-9

AUTHORITY = (
    REPO
    / "data/ChinaInstances/china81_finite_fleet_authority_v3_20260802"
)
AUTHORITY_DELIVERY = (
    REPO / "baselines/china_e3_e7/fleet_authority_v3_20260802"
)
DEFAULT_OUTPUT = (
    REPO / "baselines/china_e3_e7/formal_fleet_levels_20260802"
)
MODULE_NAME = "baselines.china_e3_e7.run_formal_fleet_levels_xb_20260802"

SCIENTIFIC_HASH_EXCLUDES = {
    "artifact_hashes.json",
    "done.json",
    "progress.json",
    "status.json",
    "latest_ai_packet.json",
    "run.log",
}


RAW_FIELDS = (
    "unit_id",
    "instance_id",
    "fleet_level_percent",
    "seed",
    "status",
    "available_cv",
    "available_ev",
    "available_total",
    "aware_dispatched_cv",
    "aware_dispatched_ev",
    "aware_used_physical_vehicles",
    "aware_route_count",
    "aware_operating_cost_cny",
    "aware_full_model_cost_cny",
    "aware_system_emissions_kg",
    "aware_charging_emissions_kg",
    "aware_solution_sha256",
    "blind_dispatched_cv",
    "blind_dispatched_ev",
    "blind_used_physical_vehicles",
    "blind_route_count",
    "blind_operating_cost_cny",
    "blind_rescored_full_model_cost_cny",
    "blind_system_emissions_kg",
    "blind_charging_emissions_kg",
    "blind_solution_sha256",
    "emissions_difference_vs_blind_kg",
    "emissions_difference_vs_blind_pct",
    "operating_cost_difference_vs_blind_cny",
    "operating_cost_difference_vs_blind_pct",
    "charging_timing_change_count",
    "charging_action_unmatched_count",
    "vehicle_type_change_customer_count",
    "route_change_customer_count",
    "route_count_difference",
    "unserved_customer_count",
    "duplicate_service_count",
    "violation_count",
    "violations",
    "aware_hgs_iterations_by_view",
    "blind_hgs_iterations_by_view",
    "aware_stop_reasons_by_view",
    "blind_stop_reasons_by_view",
    "attempted_search_arm_count",
    "successful_search_arm_count",
    "complete_solution_available",
    "solution_kind",
    "failure_evidence_sha256",
    "pair_solution_sha256",
    "solution_sha256",
    "elapsed_seconds",
    "failure_reason",
)


class SourceDriftError(RuntimeError):
    """Raised when a registered source file changes after preregistration."""


def now_utc() -> str:
    return datetime.now(UTC).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(payload: Any) -> str:
    return sha256_bytes(canonical_bytes(payload))


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def write_json(path: Path, payload: Any) -> None:
    atomic_write_bytes(
        path,
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n",
    )


def write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: Iterable[str]) -> None:
    fieldnames = list(fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        newline="",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_value(row.get(field, "")) for field in fieldnames})
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if value is None:
        return ""
    return value


def git_text(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def source_paths() -> list[Path]:
    paths: set[Path] = {RUNNER}
    for root in (REPO / "solver/src/setp_solver", PROTOTYPE):
        paths.update(
            path.resolve()
            for path in root.rglob("*.py")
            if not path.name.startswith("._") and "__pycache__" not in path.parts
        )
    paths.add(
        (
            REPO
            / "baselines/china_instances/"
            "build_china81_finite_fleet_authority_v3_20260802.py"
        ).resolve()
    )
    return sorted(paths)


def source_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(REPO)): sha256_path(path)
        for path in source_paths()
    }


def source_tree_sha256(hashes: dict[str, str]) -> str:
    return canonical_sha256(hashes)


def verify_source_lock(expected: dict[str, str]) -> None:
    observed = source_hashes()
    if observed != expected:
        changed = sorted(
            path
            for path in set(observed) | set(expected)
            if observed.get(path) != expected.get(path)
        )
        raise SourceDriftError(
            "registered source SHA-256 drift: " + ", ".join(changed[:20])
        )


def authority_rows(instance_id: str = INSTANCE_ID) -> list[dict[str, str]]:
    with (AUTHORITY / "fleet_caps.csv").open(
        newline="", encoding="utf-8-sig"
    ) as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row["instance_id"] == instance_id
        ]
    if not rows:
        raise ValueError(f"v3 authority has no rows for {instance_id}")
    return sorted(rows, key=lambda row: row["depot_id"])


def allocations_by_level(
    instance_id: str = INSTANCE_ID,
) -> dict[int, dict[str, dict[str, int]]]:
    result: dict[int, dict[str, dict[str, int]]] = {level: {} for level in LEVELS}
    for row in authority_rows(instance_id):
        allocations = json.loads(row["fleet_allocation_map_metadata_only"])
        for level in LEVELS:
            values = allocations[str(level)]
            cap = {
                "num_cv": int(values["num_cv"]),
                "num_ev": int(values["num_ev"]),
                "total_fleet_cap": int(values["total_fleet_cap"]),
            }
            if cap["num_cv"] + cap["num_ev"] != cap["total_fleet_cap"]:
                raise ValueError(
                    f"v3 Hamilton allocation does not close for {row['depot_id']} level {level}"
                )
            result[level][row["depot_id"]] = cap
    totals = {
        level: sum(cap["total_fleet_cap"] for cap in by_depot.values())
        for level, by_depot in result.items()
    }
    if len(set(totals.values())) != 1:
        raise ValueError(f"v3 total fleet changes across levels: {totals}")
    return result


def model_config() -> ModelConfig:
    return ModelConfig(
        strict_multitrip=True,
        depot_charger_capacity_mode=DEPOT_CHARGER_CAPACITY_UNBOUNDED,
    )


def load_base_bundle() -> Any:
    return replace(
        load_china81_bundle(
            REPO,
            INSTANCE_ID,
            fleet_authority=AUTHORITY,
            model_config=model_config(),
        ),
        formal_search_allowed=True,
    )


def bundle_for_level(
    level: int,
    *,
    carbon_blind: bool,
) -> Any:
    allocations = allocations_by_level()[int(level)]
    base = load_base_bundle()
    caps = MappingProxyType(
        {
            depot: MappingProxyType(dict(values))
            for depot, values in sorted(allocations.items())
        }
    )
    num_cv = sum(values["num_cv"] for values in allocations.values())
    num_ev = sum(values["num_ev"] for values in allocations.values())
    prices = (
        replace(base.prices, carbon_price=0.0)
        if carbon_blind
        else base.prices
    )
    return replace(
        base,
        instance=replace(base.instance, num_cv=num_cv, num_ev=num_ev),
        prices=prices,
        fleet_caps_by_depot=caps,
        formal_search_allowed=True,
    )


def common_initial_solution(bundle: Any) -> Solution:
    observed_caps = {
        depot: {
            "num_cv": int(values["num_cv"]),
            "num_ev": int(values["num_ev"]),
            "total_fleet_cap": int(values["total_fleet_cap"]),
        }
        for depot, values in bundle.fleet_caps_by_depot.items()
    }
    matching_levels = [
        level
        for level, registered_caps in allocations_by_level().items()
        if registered_caps == observed_caps
    ]
    if len(matching_levels) != 1:
        raise RuntimeError(
            f"cannot identify one v3 Hamilton level from bundle caps: {matching_levels}"
        )
    level = matching_levels[0]
    witness_path = AUTHORITY / "witnesses" / f"{INSTANCE_ID}.json"
    witness = json.loads(witness_path.read_text(encoding="utf-8"))
    level_witness = witness["levels"][str(level)]
    if level_witness["status"] != "CERTIFIED" or level_witness["violations"]:
        raise RuntimeError(
            f"v3 initial witness is not certified for level {level}: {level_witness}"
        )
    routes: list[Route] = []
    for depot_id, depot_witness in sorted(level_witness["depots"].items()):
        for vehicle_type in ("cv", "ev"):
            for timed_route in depot_witness[f"{vehicle_type}_routes"]:
                routes.append(
                    Route(
                        vehicle_id=f"XB-INIT-{level:03d}-{len(routes) + 1:04d}",
                        vehicle_type=vehicle_type,
                        home_depot_id=depot_id,
                        node_sequence=[
                            depot_id,
                            *timed_route["customers"],
                            depot_id,
                        ],
                    )
                )
    return Solution(routes=routes)


def _proxy_only_positive_type_caps(bundle: Any) -> Any:
    """Give the route proxy one vehicle of an absent type.

    The proxy only proposes customer groups and visit order.  It does not
    certify or score the final physical solution.  The original bundle, with
    exact v3 endpoint caps, is still passed to every completion and final
    checker call.
    """

    caps = MappingProxyType(
        {
            depot: MappingProxyType(
                {
                    **dict(values),
                    "num_cv": max(1, int(values["num_cv"])),
                    "num_ev": max(1, int(values["num_ev"])),
                }
            )
            for depot, values in bundle.fleet_caps_by_depot.items()
        }
    )
    return replace(
        bundle,
        instance=replace(
            bundle.instance,
            num_cv=sum(int(values["num_cv"]) for values in caps.values()),
            num_ev=sum(int(values["num_ev"]) for values in caps.values()),
        ),
        fleet_caps_by_depot=caps,
    )


class _HgsContractPatch:
    """Bind MaxIterations(2000) OR NoImprovement(150) without editing HGS."""

    def __init__(self, no_improvement: int) -> None:
        self.no_improvement = int(no_improvement)
        self._original_max: Any = None
        self._original_builder: Any = None

    def __enter__(self) -> "_HgsContractPatch":
        self._original_max = epochal_hgs.MaxIterations
        self._original_builder = route_pool_sp.build_pyvrp_problem

        def contracted_max_iterations(max_iterations: int) -> Any:
            return MultipleCriteria(
                [
                    MaxIterations(int(max_iterations)),
                    NoImprovement(self.no_improvement),
                ]
            )

        def endpoint_capable_builder(
            bundle: Any,
            *,
            route_proxy_mode: str = "mechanism_ev",
            hard_home_depot_lock: bool = False,
        ) -> Any:
            proxy_bundle = _proxy_only_positive_type_caps(bundle)
            return pyvrp_adapter.build_pyvrp_problem(
                proxy_bundle,
                route_proxy_mode=route_proxy_mode,
                hard_home_depot_lock=hard_home_depot_lock,
            )

        epochal_hgs.MaxIterations = contracted_max_iterations
        route_pool_sp.build_pyvrp_problem = endpoint_capable_builder
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        epochal_hgs.MaxIterations = self._original_max
        route_pool_sp.build_pyvrp_problem = self._original_builder


def _run_arm(
    level: int,
    seed: int,
    arm: str,
    *,
    max_iterations: int,
    max_no_improvement: int,
) -> dict[str, Any]:
    carbon_blind = arm == CARBON_BLIND
    bundle = bundle_for_level(level, carbon_blind=carbon_blind)
    initial = common_initial_solution(bundle)
    started = time.perf_counter()
    with model_config_scope(model_config()), _HgsContractPatch(max_no_improvement):
        run = route_pool_sp.run_hgs_route_pool_recombination(
            bundle,
            initial,
            seed=int(seed),
            hgs_seconds_per_view=None,
            exact_elites_per_view=EXACT_ELITES_PER_VIEW,
            max_archive_candidates_per_view=ARCHIVE_CANDIDATES_PER_VIEW,
            sp_time_limit_seconds=SP_TIME_LIMIT_SECONDS,
            hard_home_depot_lock=False,
            max_hgs_iterations_per_view=int(max_iterations),
            wallclock_safety_seconds_per_view=WALLCLOCK_SAFETY_SECONDS_PER_VIEW,
            exact_checkpoint_interval_iterations=None,
            preserve_base_pool_recombination=False,
        )
    solution = run.completion.solution
    objective, breakdown, violations = exact_china81_score(solution, bundle)
    if violations:
        raise ValueError(
            "final exact check violations: "
            + "; ".join(
                f"{item.type}:{item.vehicle_id}:{item.node_id}:{item.detail}"
                for item in violations[:20]
            )
        )
    solution_dict = asdict(solution)
    solution_sha = canonical_sha256(solution_dict)
    used_cv, used_ev = physical_counts(solution)
    service = service_counts(solution, bundle)
    hgs_iterations = {
        view: int(epoch.stats["hgs_iterations"])
        for view, epoch in run.view_epochs.items()
    }
    if bool(run.stats.get("wallclock_safety_triggered", False)):
        raise RuntimeError(
            "technical wallclock safety triggered before the registered "
            "2000-iteration/150-no-improvement stopping rule"
        )
    if any(value > int(max_iterations) for value in hgs_iterations.values()):
        raise RuntimeError(f"HGS iteration cap exceeded: {hgs_iterations}")
    stop_reasons = {
        view: infer_stop_reason(value, max_iterations, max_no_improvement)
        for view, value in hgs_iterations.items()
    }
    return {
        "arm": arm,
        "objective": float(objective),
        "breakdown": {key: float(value) for key, value in breakdown.items()},
        "solution": solution_dict,
        "solution_sha256": solution_sha,
        "completion_activity": run.completion.activity,
        "search_stats": run.stats,
        "hgs_iterations_by_view": hgs_iterations,
        "stop_reasons_by_view": stop_reasons,
        "elapsed_seconds": time.perf_counter() - started,
        "used_cv": used_cv,
        "used_ev": used_ev,
        "used_total": used_cv + used_ev,
        "route_count": len(solution.routes),
        **service,
    }


def infer_stop_reason(
    observed_iterations: int,
    max_iterations: int,
    max_no_improvement: int,
) -> str:
    if int(observed_iterations) >= int(max_iterations):
        return "MAX_ITERATIONS"
    return f"NO_IMPROVEMENT_{int(max_no_improvement)}"


def physical_counts(solution: Solution) -> tuple[int, int]:
    counts: dict[str, set[str]] = {"cv": set(), "ev": set()}
    for route in solution.routes:
        counts[route.vehicle_type.lower()].add(
            physical_vehicle_id(route.vehicle_id)
        )
    return len(counts["cv"]), len(counts["ev"])


def expected_customer_ids(bundle: Any) -> set[str]:
    return {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }


def service_counts(solution: Solution, bundle: Any) -> dict[str, int]:
    expected = expected_customer_ids(bundle)
    served = [
        node_id
        for route in solution.routes
        for node_id in route.node_sequence
        if node_id in expected
    ]
    unique = set(served)
    return {
        "unserved_customer_count": len(expected - unique),
        "duplicate_service_count": len(served) - len(unique),
    }


def route_customer_context(
    solution: Solution,
    bundle: Any,
) -> dict[str, tuple[str, str, str]]:
    expected = expected_customer_ids(bundle)
    contexts: dict[str, tuple[str, str, str]] = {}
    for route in solution.routes:
        customers = [node for node in route.node_sequence if node in expected]
        boundary = f"@{route.home_depot_id}"
        for index, customer in enumerate(customers):
            previous = customers[index - 1] if index else boundary
            following = customers[index + 1] if index + 1 < len(customers) else boundary
            if customer in contexts:
                contexts[customer] = ("@DUPLICATE", "@DUPLICATE", "@DUPLICATE")
            else:
                contexts[customer] = (route.home_depot_id, previous, following)
    return contexts


def customer_vehicle_types(
    solution: Solution,
    bundle: Any,
) -> dict[str, str]:
    expected = expected_customer_ids(bundle)
    result: dict[str, str] = {}
    for route in solution.routes:
        for node_id in route.node_sequence:
            if node_id in expected:
                value = route.vehicle_type.lower()
                result[node_id] = (
                    value if node_id not in result else "@DUPLICATE"
                )
    return result


def charging_action_counters(
    solution: Solution,
    bundle: Any,
) -> dict[tuple[Any, ...], Counter[float]]:
    expected = expected_customer_ids(bundle)
    route_by_id = {route.vehicle_id: route for route in solution.routes}
    counters: dict[tuple[Any, ...], Counter[float]] = defaultdict(Counter)
    for action in solution.charging_actions:
        route = route_by_id.get(action.vehicle_id)
        customers = (
            tuple(node for node in route.node_sequence if node in expected)
            if route is not None
            else ("@UNBOUND",)
        )
        home_depot = route.home_depot_id if route is not None else "@UNBOUND"
        key = (
            home_depot,
            customers,
            action.station_id,
            round(float(action.energy_kwh), 9),
            round(float(action.occupancy_minutes), 9),
            int(action.charge_day_offset),
        )
        counters[key][round(float(action.charge_start_second), 9)] += 1
    return counters


def decision_layer_changes(
    blind: Solution,
    aware: Solution,
    bundle: Any,
) -> dict[str, int]:
    expected = expected_customer_ids(bundle)
    before_context = route_customer_context(blind, bundle)
    after_context = route_customer_context(aware, bundle)
    route_changes = sum(
        before_context.get(customer) != after_context.get(customer)
        for customer in expected
    )
    before_types = customer_vehicle_types(blind, bundle)
    after_types = customer_vehicle_types(aware, bundle)
    type_changes = sum(
        before_types.get(customer) != after_types.get(customer)
        for customer in expected
    )
    before_actions = charging_action_counters(blind, bundle)
    after_actions = charging_action_counters(aware, bundle)
    timing_changes = 0
    unmatched = 0
    for key in set(before_actions) | set(after_actions):
        before = before_actions.get(key, Counter())
        after = after_actions.get(key, Counter())
        matched_identity = min(sum(before.values()), sum(after.values()))
        unchanged_start = sum((before & after).values())
        timing_changes += matched_identity - unchanged_start
        unmatched += sum(before.values()) + sum(after.values()) - 2 * matched_identity
    return {
        "charging_timing_change_count": int(timing_changes),
        "charging_action_unmatched_count": int(unmatched),
        "vehicle_type_change_customer_count": int(type_changes),
        "route_change_customer_count": int(route_changes),
        "route_count_difference": len(aware.routes) - len(blind.routes),
    }


def _solution_from_dict(payload: dict[str, Any]) -> Solution:
    from setp_solver.solution import (
        ChargingAction,
        CrossSiteService,
        Route as SolutionRoute,
    )

    return Solution(
        routes=[SolutionRoute(**row) for row in payload["routes"]],
        charging_actions=[
            ChargingAction(**row) for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(**row)
            for row in payload.get("cross_site_services", [])
        ],
    )


def _operating_cost(breakdown: dict[str, Any]) -> float:
    return float(breakdown["total_cost"]) - float(breakdown["cost_carbon"])


def is_registered_infeasibility(exc: Exception) -> bool:
    if not isinstance(exc, ValueError) or isinstance(exc, SourceDriftError):
        return False
    message = str(exc)
    return message.startswith(
        (
            "China81 route skeleton cannot satisfy the registered physical fleet caps",
            "China81 route skeleton has no feasible all-CV completion",
            "final exact check violations:",
        )
    )


def infeasibility_witness(level: int, carbon_blind: bool) -> dict[str, Any]:
    bundle = bundle_for_level(int(level), carbon_blind=carbon_blind)
    attempted = common_initial_solution(bundle)
    attempted_dict = asdict(attempted)
    objective, breakdown, violations = exact_china81_score(attempted, bundle)
    return {
        "registered_initial_solution": attempted_dict,
        "registered_initial_solution_sha256": canonical_sha256(attempted_dict),
        "registered_initial_exact_objective": float(objective),
        "registered_initial_exact_breakdown": {
            key: float(value) for key, value in breakdown.items()
        },
        "registered_initial_exact_violations": [
            asdict(violation) for violation in violations
        ],
    }


def run_unit(
    level: int,
    seed: int,
    registered_source_hashes: dict[str, str],
    max_iterations: int = MAX_ITERATIONS,
    max_no_improvement: int = MAX_NO_IMPROVEMENT,
) -> dict[str, Any]:
    started = time.perf_counter()
    unit_id = f"level_{int(level):03d}__seed_{int(seed):02d}"
    try:
        verify_source_lock(registered_source_hashes)
        arms: dict[str, dict[str, Any]] = {}
        arm_failures: dict[str, dict[str, Any]] = {}
        for arm in ARM_ORDER:
            try:
                arms[arm] = _run_arm(
                    int(level),
                    int(seed),
                    arm,
                    max_iterations=int(max_iterations),
                    max_no_improvement=int(max_no_improvement),
                )
            except Exception as arm_exc:
                arm_failures[arm] = {
                    "status": (
                        "INFEASIBLE_OR_NOT_FOUND"
                        if is_registered_infeasibility(arm_exc)
                        else "TECHNICAL_ERROR"
                    ),
                    "failure_reason": f"{type(arm_exc).__name__}: {arm_exc}",
                    "traceback": traceback.format_exc(),
                }
        verify_source_lock(registered_source_hashes)
        if arm_failures:
            allocations = allocations_by_level()[int(level)]
            available_cv = sum(values["num_cv"] for values in allocations.values())
            available_ev = sum(values["num_ev"] for values in allocations.values())
            unit_status = (
                "TECHNICAL_ERROR"
                if any(
                    item["status"] == "TECHNICAL_ERROR"
                    for item in arm_failures.values()
                )
                else "INFEASIBLE_OR_NOT_FOUND"
            )
            failures = [
                f"{arm}: {item['failure_reason']}"
                for arm, item in arm_failures.items()
            ]
            witness_by_arm = {
                arm: infeasibility_witness(
                    int(level),
                    carbon_blind=(arm == CARBON_BLIND),
                )
                for arm in arm_failures
            }
            attempted_solution_hashes = {
                item["registered_initial_solution_sha256"]
                for item in witness_by_arm.values()
            }
            attempted_solution_sha = (
                next(iter(attempted_solution_hashes))
                if len(attempted_solution_hashes) == 1
                else canonical_sha256(sorted(attempted_solution_hashes))
            )
            payload = {
                "unit_id": unit_id,
                "instance_id": INSTANCE_ID,
                "fleet_level_percent": int(level),
                "seed": int(seed),
                "status": unit_status,
                "available_by_depot": allocations,
                "arms": arms,
                "arm_failures": arm_failures,
                "registered_infeasibility_witness_by_failed_arm": witness_by_arm,
                "complete_solution_available": False,
                "solution_kind": "REGISTERED_INITIAL_SOLUTION_INFEASIBILITY_WITNESS",
            }
            failure_evidence_sha = canonical_sha256(payload)
            payload["failure_evidence_sha256"] = failure_evidence_sha
            row = {
                "unit_id": unit_id,
                "instance_id": INSTANCE_ID,
                "fleet_level_percent": int(level),
                "seed": int(seed),
                "status": unit_status,
                "available_cv": available_cv,
                "available_ev": available_ev,
                "available_total": available_cv + available_ev,
                "aware_solution_sha256": arms.get(CARBON_AWARE, {}).get(
                    "solution_sha256", ""
                ),
                "blind_solution_sha256": arms.get(CARBON_BLIND, {}).get(
                    "solution_sha256", ""
                ),
                "unserved_customer_count": "",
                "duplicate_service_count": "",
                "violation_count": len(failures),
                "violations": failures,
                "attempted_search_arm_count": len(ARM_ORDER),
                "successful_search_arm_count": len(arms),
                "complete_solution_available": False,
                "solution_kind": payload["solution_kind"],
                "failure_evidence_sha256": failure_evidence_sha,
                "pair_solution_sha256": failure_evidence_sha,
                "solution_sha256": attempted_solution_sha,
                "elapsed_seconds": time.perf_counter() - started,
                "failure_reason": "; ".join(failures),
            }
            return {
                "row": row,
                "payload": payload,
                "technical_error": unit_status == "TECHNICAL_ERROR",
            }
        aware = arms[CARBON_AWARE]
        blind = arms[CARBON_BLIND]
        aware_solution = _solution_from_dict(aware["solution"])
        blind_solution = _solution_from_dict(blind["solution"])
        aware_bundle = bundle_for_level(int(level), carbon_blind=False)
        _, blind_rescored, blind_rescored_violations = exact_china81_score(
            blind_solution,
            aware_bundle,
        )
        if blind_rescored_violations:
            raise RuntimeError("carbon-blind solution failed common aware-price rescore")
        changes = decision_layer_changes(
            blind_solution,
            aware_solution,
            aware_bundle,
        )
        allocations = allocations_by_level()[int(level)]
        available_cv = sum(values["num_cv"] for values in allocations.values())
        available_ev = sum(values["num_ev"] for values in allocations.values())
        aware_breakdown = aware["breakdown"]
        blind_breakdown = blind["breakdown"]
        aware_emissions = float(aware_breakdown["E_total"])
        blind_emissions = float(blind_breakdown["E_total"])
        aware_operating = _operating_cost(aware_breakdown)
        blind_operating = _operating_cost(blind_breakdown)
        pair_scientific_payload = {
            "unit_id": unit_id,
            "instance_id": INSTANCE_ID,
            "fleet_level_percent": int(level),
            "seed": int(seed),
            "available_by_depot": allocations,
            "arms": arms,
            "blind_rescored_under_aware_prices": {
                key: float(value) for key, value in blind_rescored.items()
            },
            "decision_layer_changes": changes,
        }
        pair_sha = canonical_sha256(pair_scientific_payload)
        unserved = max(
            int(aware["unserved_customer_count"]),
            int(blind["unserved_customer_count"]),
        )
        duplicates = max(
            int(aware["duplicate_service_count"]),
            int(blind["duplicate_service_count"]),
        )
        row = {
            "unit_id": unit_id,
            "instance_id": INSTANCE_ID,
            "fleet_level_percent": int(level),
            "seed": int(seed),
            "status": "PASS",
            "available_cv": available_cv,
            "available_ev": available_ev,
            "available_total": available_cv + available_ev,
            "aware_dispatched_cv": aware["used_cv"],
            "aware_dispatched_ev": aware["used_ev"],
            "aware_used_physical_vehicles": aware["used_total"],
            "aware_route_count": aware["route_count"],
            "aware_operating_cost_cny": aware_operating,
            "aware_full_model_cost_cny": aware_breakdown["total_cost"],
            "aware_system_emissions_kg": aware_emissions,
            "aware_charging_emissions_kg": aware_breakdown["E_ev_indirect"],
            "aware_solution_sha256": aware["solution_sha256"],
            "blind_dispatched_cv": blind["used_cv"],
            "blind_dispatched_ev": blind["used_ev"],
            "blind_used_physical_vehicles": blind["used_total"],
            "blind_route_count": blind["route_count"],
            "blind_operating_cost_cny": blind_operating,
            "blind_rescored_full_model_cost_cny": blind_rescored["total_cost"],
            "blind_system_emissions_kg": blind_emissions,
            "blind_charging_emissions_kg": blind_breakdown["E_ev_indirect"],
            "blind_solution_sha256": blind["solution_sha256"],
            "emissions_difference_vs_blind_kg": aware_emissions - blind_emissions,
            "emissions_difference_vs_blind_pct": percent_change(
                aware_emissions, blind_emissions
            ),
            "operating_cost_difference_vs_blind_cny": aware_operating - blind_operating,
            "operating_cost_difference_vs_blind_pct": percent_change(
                aware_operating, blind_operating
            ),
            **changes,
            "unserved_customer_count": unserved,
            "duplicate_service_count": duplicates,
            "violation_count": 0,
            "violations": [],
            "aware_hgs_iterations_by_view": aware["hgs_iterations_by_view"],
            "blind_hgs_iterations_by_view": blind["hgs_iterations_by_view"],
            "aware_stop_reasons_by_view": aware["stop_reasons_by_view"],
            "blind_stop_reasons_by_view": blind["stop_reasons_by_view"],
            "attempted_search_arm_count": len(ARM_ORDER),
            "successful_search_arm_count": len(ARM_ORDER),
            "complete_solution_available": True,
            "solution_kind": "FULL_PAIRED_COMPLETE_SOLUTIONS",
            "failure_evidence_sha256": "",
            "pair_solution_sha256": pair_sha,
            "solution_sha256": pair_sha,
            "elapsed_seconds": time.perf_counter() - started,
            "failure_reason": "",
        }
        return {
            "row": row,
            "payload": pair_scientific_payload,
            "technical_error": False,
        }
    except Exception as exc:
        is_infeasible = is_registered_infeasibility(exc)
        status = "INFEASIBLE_OR_NOT_FOUND" if is_infeasible else "TECHNICAL_ERROR"
        failure = f"{type(exc).__name__}: {exc}"
        allocations = allocations_by_level().get(int(level), {})
        available_cv = sum(values["num_cv"] for values in allocations.values())
        available_ev = sum(values["num_ev"] for values in allocations.values())
        row = {
            "unit_id": unit_id,
            "instance_id": INSTANCE_ID,
            "fleet_level_percent": int(level),
            "seed": int(seed),
            "status": status,
            "available_cv": available_cv,
            "available_ev": available_ev,
            "available_total": available_cv + available_ev,
            "unserved_customer_count": "",
            "duplicate_service_count": "",
            "violation_count": 1,
            "violations": [failure],
            "attempted_search_arm_count": 0,
            "successful_search_arm_count": 0,
            "complete_solution_available": False,
            "solution_kind": "NO_COMPLETE_SOLUTION_UNEXPECTED_FAILURE",
            "failure_evidence_sha256": "",
            "elapsed_seconds": time.perf_counter() - started,
            "failure_reason": failure,
        }
        return {
            "row": row,
            "payload": {
                "unit_id": unit_id,
                "instance_id": INSTANCE_ID,
                "fleet_level_percent": int(level),
                "seed": int(seed),
                "status": status,
                "failure_reason": failure,
                "traceback": traceback.format_exc(),
                "available_by_depot": allocations,
            },
            "technical_error": not is_infeasible,
        }


def percent_change(candidate: float, baseline: float) -> float | None:
    if abs(float(baseline)) <= TOL:
        return None
    return 100.0 * (float(candidate) - float(baseline)) / float(baseline)


def input_hashes(bundle: Any) -> dict[str, str]:
    paths: set[Path] = set()
    for source in bundle.source_paths.values():
        path = REPO / str(source)
        if path.is_file():
            paths.add(path.resolve())
        elif path.is_dir():
            paths.update(
                candidate.resolve()
                for candidate in path.rglob("*")
                if candidate.is_file()
                and not candidate.name.startswith("._")
                and "__pycache__" not in candidate.parts
            )
    for path in AUTHORITY.rglob("*"):
        if path.is_file() and not path.name.startswith("._"):
            paths.add(path.resolve())
    return {
        str(path.relative_to(REPO)): sha256_path(path)
        for path in sorted(paths)
    }


def dependency_record() -> dict[str, Any]:
    import numpy
    import pyvrp
    import scipy

    pyvrp_binary = next(
        (
            path
            for path in Path(pyvrp.__file__).resolve().parent.glob(
                "_pyvrp*.so"
            )
        ),
        None,
    )
    return {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "numpy_version": numpy.__version__,
        "scipy_version": scipy.__version__,
        "pyvrp_version": importlib.metadata.version("pyvrp"),
        "pyvrp_module": str(Path(pyvrp.__file__).resolve()),
        "pyvrp_binary": None if pyvrp_binary is None else str(pyvrp_binary),
        "pyvrp_binary_sha256": (
            None if pyvrp_binary is None else sha256_path(pyvrp_binary)
        ),
    }


def preregistration(
    registered_source_hashes: dict[str, str],
    registered_input_hashes: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": "resetp.xb-preregistration.v1",
        "task_id": TASK_ID,
        "created_at": now_utc(),
        "immutable_after_first_search": True,
        "instance_selection": {
            "instance_id": INSTANCE_ID,
            "rule": (
                "retain the paper's registered Pearl River Delta main region; "
                "choose the -01 replicate at the unique eligible 100-customer "
                "scale; do not rank historical outcomes"
            ),
            "eligible_customer_range": [51, 149],
        },
        "formal_units": {
            "levels_percent": list(LEVELS),
            "seeds": list(SEEDS),
            "unit_count": len(LEVELS) * len(SEEDS),
            "paired_search_arms_per_unit": list(ARM_ORDER),
            "search_arm_execution_count": 2 * len(LEVELS) * len(SEEDS),
        },
        "execution_backend": {
            "kind": "independent_python_subprocesses",
            "reason": "managed macOS sandbox denies SC_SEM_NSEMS_MAX",
            "scientific_contract_change": False,
        },
        "paired_comparison": {
            "carbon_blind": (
                "same model and time-varying electricity tariff; carbon price "
                "is exactly zero in search"
            ),
            "carbon_aware": (
                "same model with the registered China81 carbon price and "
                "48-slot carbon intensity in search"
            ),
            "same_seed": True,
            "arm_order": list(ARM_ORDER),
        },
        "stopping_rule": {
            "rule": "first of maximum iterations or consecutive non-improving iterations",
            "max_iterations": MAX_ITERATIONS,
            "max_consecutive_no_improvement": MAX_NO_IMPROVEMENT,
            "scope": "each native HGS view inside each paired search arm",
            "improvement_basis": "native PyVRP view incumbent",
            "wallclock_safety_seconds_per_view": WALLCLOCK_SAFETY_SECONDS_PER_VIEW,
            "wallclock_safety_is_valid_result_stop": False,
            "wallclock_safety_action": "technical HALT; do not accept as a completed scientific run",
        },
        "fleet_contract": {
            "authority": str(AUTHORITY.relative_to(REPO)),
            "authority_delivery": str(AUTHORITY_DELIVERY.relative_to(REPO)),
            "authority_version": "china81_finite_fleet_authority_v3_20260802",
            "allocation": "Hamilton largest remainder, read verbatim from fleet_allocation_map_metadata_only",
            "total_fixed_across_levels": True,
            "strict_multitrip": True,
            "fixed_cost_billing": "once per used physical vehicle",
            "vehicle_fixed_cost_cny": 170.0,
            "depot_charger_capacity": "unbounded",
        },
        "registered_measurements": {
            "charging_timing_change_count": (
                "matched actions have identical depot/customer route, station, "
                "energy, duration and day offset but a different start second"
            ),
            "charging_action_unmatched_count": (
                "actions that cannot be matched on the registered action identity; "
                "reported separately and not relabelled as a timing change"
            ),
            "vehicle_type_change_customer_count": (
                "customers assigned to a different CV/EV type in aware versus blind"
            ),
            "route_change_customer_count": (
                "customers whose home depot, predecessor customer, or successor "
                "customer differs; stations and vehicle identifiers are ignored"
            ),
            "actual_dispatch": "unique physical_vehicle_id by CV/EV after strict multi-trip scheduling",
            "route_count": "delivery trip count, reported separately from physical vehicles",
        },
        "registered_falsifiers": [
            {
                "id": "FALSIFIER_NO_DECISION_RESPONSE",
                "condition": (
                    "carbon-aware and carbon-blind solutions show no registered "
                    "charging-time, vehicle-type, or route change in every feasible unit"
                ),
                "consequence": "the claimed decision-layer leverage is not supported",
            },
            {
                "id": "FALSIFIER_NO_CROSS_LEVEL_LAYER_SHIFT",
                "condition": (
                    "the set of decision layers with observed changes is identical "
                    "at every fleet level"
                ),
                "consequence": "the claimed shift of leverage across electrification levels is not supported",
            },
            {
                "id": "FALSIFIER_SERVICE_OR_FEASIBILITY_CONFOUND",
                "condition": (
                    "an apparent cost or emissions advantage is accompanied by "
                    "unserved, duplicate-served, or infeasible demand"
                ),
                "consequence": "that advantage cannot support the section claim",
            },
            {
                "id": "FALSIFIER_SCORE_ONLY_DIFFERENCE",
                "condition": (
                    "emissions differ only by rescoring while all registered decision "
                    "layers remain unchanged"
                ),
                "consequence": "no operational leverage layer is identified",
            },
        ],
        "retention_policy": {
            "all_units_retained": True,
            "no_retry_for_direction": True,
            "no_seed_replacement": True,
            "infeasible_units_retained": True,
            "constraints_never_relaxed_after_results": True,
        },
        "source_tree_sha256": source_tree_sha256(registered_source_hashes),
        "source_files_sha256": registered_source_hashes,
        "input_tree_sha256": source_tree_sha256(registered_input_hashes),
        "input_files_sha256": registered_input_hashes,
    }


def initial_metadata(
    prereg: dict[str, Any],
    workers: int,
) -> dict[str, Any]:
    allocations = allocations_by_level()
    return {
        "schema_version": "resetp.xb-formal-metadata.v1",
        "task_id": TASK_ID,
        "status": "RUNNING",
        "started_at": now_utc(),
        "git_commit": git_text("rev-parse", "HEAD"),
        "git_branch": git_text("rev-parse", "--abbrev-ref", "HEAD"),
        "git_status_porcelain_at_start": git_text("status", "--short"),
        "model_config": model_config().as_metadata(),
        "strict_multitrip": True,
        "fixed_cost_billing": "used_physical_vehicle_once",
        "vehicle_fixed_cost_cny": 170.0,
        "model_change_register_id": "MC-W1-F2-DEPOT-CONCURRENCY-01",
        "depot_charger_capacity_mode": DEPOT_CHARGER_CAPACITY_UNBOUNDED,
        "fleet_authority_version": "china81_finite_fleet_authority_v3_20260802",
        "fleet_authority_path": str(AUTHORITY.relative_to(REPO)),
        "fleet_authority_delivery": str(AUTHORITY_DELIVERY.relative_to(REPO)),
        "fleet_authority_total_all_81_instances": 943,
        "selected_instance": INSTANCE_ID,
        "selected_instance_allocations": allocations,
        "selected_instance_total_fleet": {
            str(level): sum(
                cap["total_fleet_cap"] for cap in allocations[level].values()
            )
            for level in LEVELS
        },
        "levels_percent": list(LEVELS),
        "seeds": list(SEEDS),
        "formal_unit_count": len(LEVELS) * len(SEEDS),
        "paired_search_arm_execution_count": 2 * len(LEVELS) * len(SEEDS),
        "algorithm": "MV-HGS-SP",
        "algorithm_views": list(HGS_VIEWS),
        "max_iterations": MAX_ITERATIONS,
        "max_consecutive_no_improvement": MAX_NO_IMPROVEMENT,
        "exact_elites_per_view": EXACT_ELITES_PER_VIEW,
        "archive_candidates_per_view": ARCHIVE_CANDIDATES_PER_VIEW,
        "sp_time_limit_seconds": SP_TIME_LIMIT_SECONDS,
        "workers": int(workers),
        "worker_backend": "independent_python_subprocesses_no_system_semaphores",
        "dependency_record": dependency_record(),
        "source_tree_sha256": prereg["source_tree_sha256"],
        "source_files_sha256": prereg["source_files_sha256"],
        "input_tree_sha256": prereg["input_tree_sha256"],
        "input_files_sha256": prereg["input_files_sha256"],
        "protected_files_not_modified": [
            "docs/paper_v2/RETIRED_paper_main.tex",
            "docs/paper_submission_final/RETIRED_paper_main.tex",
            "solver/src/setp_solver/check.py",
            "solver/src/setp_solver/search/evaluation.py",
        ],
    }


def mean_or_none(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [float(row[field]) for row in rows if row.get(field) not in (None, "")]
    return (sum(values) / len(values)) if values else None


def sum_int(rows: list[dict[str, Any]], field: str) -> int:
    return sum(int(row[field]) for row in rows if row.get(field) not in (None, ""))


def level_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for level in LEVELS:
        level_rows = [row for row in rows if int(row["fleet_level_percent"]) == level]
        passed = [row for row in level_rows if row["status"] == "PASS"]
        allocation = allocations_by_level()[level]
        violations = sorted(
            {
                str(item)
                for row in level_rows
                for item in row.get("violations", [])
            }
        )
        output.append(
            {
                "fleet_level_percent": level,
                "available_cv": sum(value["num_cv"] for value in allocation.values()),
                "available_ev": sum(value["num_ev"] for value in allocation.values()),
                "available_total": sum(value["total_fleet_cap"] for value in allocation.values()),
                "formal_run_count": len(level_rows),
                "feasible_pair_count": len(passed),
                "infeasible_or_not_found_count": sum(
                    row["status"] == "INFEASIBLE_OR_NOT_FOUND" for row in level_rows
                ),
                "technical_error_count": sum(
                    row["status"] == "TECHNICAL_ERROR" for row in level_rows
                ),
                "aware_dispatched_cv_mean": mean_or_none(passed, "aware_dispatched_cv"),
                "aware_dispatched_ev_mean": mean_or_none(passed, "aware_dispatched_ev"),
                "aware_used_physical_vehicles_mean": mean_or_none(
                    passed, "aware_used_physical_vehicles"
                ),
                "aware_route_count_mean": mean_or_none(passed, "aware_route_count"),
                "aware_operating_cost_cny_mean": mean_or_none(
                    passed, "aware_operating_cost_cny"
                ),
                "aware_system_emissions_kg_mean": mean_or_none(
                    passed, "aware_system_emissions_kg"
                ),
                "blind_dispatched_cv_mean": mean_or_none(passed, "blind_dispatched_cv"),
                "blind_dispatched_ev_mean": mean_or_none(passed, "blind_dispatched_ev"),
                "blind_used_physical_vehicles_mean": mean_or_none(
                    passed, "blind_used_physical_vehicles"
                ),
                "blind_route_count_mean": mean_or_none(passed, "blind_route_count"),
                "emissions_difference_vs_blind_kg_mean": mean_or_none(
                    passed, "emissions_difference_vs_blind_kg"
                ),
                "emissions_difference_vs_blind_pct_mean": mean_or_none(
                    passed, "emissions_difference_vs_blind_pct"
                ),
                "operating_cost_difference_vs_blind_cny_mean": mean_or_none(
                    passed, "operating_cost_difference_vs_blind_cny"
                ),
                "charging_timing_change_count_total": sum_int(
                    passed, "charging_timing_change_count"
                ),
                "charging_action_unmatched_count_total": sum_int(
                    passed, "charging_action_unmatched_count"
                ),
                "vehicle_type_change_customer_count_total": sum_int(
                    passed, "vehicle_type_change_customer_count"
                ),
                "route_change_customer_count_total": sum_int(
                    passed, "route_change_customer_count"
                ),
                "unserved_customer_count_total": sum_int(
                    passed, "unserved_customer_count"
                ),
                "duplicate_service_count_total": sum_int(
                    passed, "duplicate_service_count"
                ),
                "violation_items": violations,
            }
        )
    return output


def assessment(rows: list[dict[str, Any]]) -> dict[str, Any]:
    passed = [row for row in rows if row["status"] == "PASS"]
    layer_sets: dict[str, list[str]] = {}
    for level in LEVELS:
        level_rows = [
            row
            for row in passed
            if int(row["fleet_level_percent"]) == level
        ]
        layers = []
        if sum_int(level_rows, "charging_timing_change_count") > 0:
            layers.append("charging_timing")
        if sum_int(level_rows, "vehicle_type_change_customer_count") > 0:
            layers.append("vehicle_type")
        if sum_int(level_rows, "route_change_customer_count") > 0:
            layers.append("route")
        layer_sets[str(level)] = layers
    unique_layer_sets = {tuple(value) for value in layer_sets.values()}
    falsifiers = {
        "FALSIFIER_NO_DECISION_RESPONSE": all(not value for value in layer_sets.values()),
        "FALSIFIER_NO_CROSS_LEVEL_LAYER_SHIFT": len(unique_layer_sets) <= 1,
        "FALSIFIER_SERVICE_OR_FEASIBILITY_CONFOUND": any(
            row["status"] != "PASS"
            or int(row.get("unserved_customer_count") or 0) > 0
            or int(row.get("duplicate_service_count") or 0) > 0
            for row in rows
        ),
        "FALSIFIER_SCORE_ONLY_DIFFERENCE": any(
            abs(float(row.get("emissions_difference_vs_blind_kg") or 0.0)) > TOL
            and int(row.get("charging_timing_change_count") or 0) == 0
            and int(row.get("vehicle_type_change_customer_count") or 0) == 0
            and int(row.get("route_change_customer_count") or 0) == 0
            for row in passed
        ),
    }
    claim_supported = not any(falsifiers.values())
    return {
        "registered_layers_observed_by_level": layer_sets,
        "registered_falsifiers_triggered": falsifiers,
        "section_claim_assessment": (
            "SUPPORTED_BY_OBSERVED_LAYER_SHIFT"
            if claim_supported
            else "NOT_SUPPORTED_BY_ONE_OR_MORE_REGISTERED_FALSIFIERS"
        ),
        "claim_supported": claim_supported,
    }


def report_text(
    decision: dict[str, Any],
    summary: list[dict[str, Any]],
) -> str:
    lines = [
        "# XB 车队电动化五档正式实验（论文 5.2）",
        "",
        f"终态：`{decision['status']}`。",
        "",
        "## FACT：合同与执行",
        "",
        (
            f"正式实例为 `{INSTANCE_ID}`；五档为 0/25/50/75/100%，每档种子 1--10，"
            f"共 {decision['observed_formal_units']} 个正式配对单元。每个单元内部各运行一次碳盲与"
            f"碳感知搜索，因此搜索臂执行数为 {decision['observed_search_arm_executions']}。"
        ),
        "",
        (
            "多趟显式开启；固定成本按实际使用实体车计费，每辆 170 元；车场充电并发不设上限；"
            "逐场车队上限逐字读取 v3 authority 的 Hamilton 五档。"
        ),
        "",
        "## FACT：五档结果（每档一行）",
        "",
        (
            "| EV档位 | 可用CV/EV | 可行配对 | 实派CV/EV（碳感知均值） | 实体车/路线（均值） | "
            "相对碳盲排放差% | 充电时刻改变 | 车型改变客户 | 路线改变客户 | 不可行/未找到 | 违反项 |"
        ),
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in summary:
        violations = "；".join(row["violation_items"]) or "无"
        lines.append(
            "| {fleet_level_percent}% | {available_cv}/{available_ev} | "
            "{feasible_pair_count}/{formal_run_count} | {cv}/{ev} | {vehicles}/{routes} | "
            "{emission} | {charge} | {types} | {route_changes} | {infeasible} | {violations} |".format(
                **row,
                cv=fmt(row["aware_dispatched_cv_mean"]),
                ev=fmt(row["aware_dispatched_ev_mean"]),
                vehicles=fmt(row["aware_used_physical_vehicles_mean"]),
                routes=fmt(row["aware_route_count_mean"]),
                emission=fmt(row["emissions_difference_vs_blind_pct_mean"]),
                charge=row["charging_timing_change_count_total"],
                types=row["vehicle_type_change_customer_count_total"],
                route_changes=row["route_change_customer_count_total"],
                infeasible=row["infeasible_or_not_found_count"],
                violations=violations,
            )
        )
    triggered = [
        key
        for key, value in decision["claim_assessment"][
            "registered_falsifiers_triggered"
        ].items()
        if value
    ]
    lines.extend(
        [
            "",
            "## DECISION：预注册否定条件核对",
            "",
            (
                "预注册否定条件触发："
                + ("、".join(f"`{item}`" for item in triggered) if triggered else "无")
                + "。"
            ),
            (
                "主张判定：`"
                + decision["claim_assessment"]["section_claim_assessment"]
                + "`。该判定不影响不利结果和不可行档的保留。"
            ),
            "",
            "## 证据边界",
            "",
            (
                "`raw_runs.csv` 每个档位--种子一行；`arm_runs.csv` 展开 100 个搜索臂；"
                "`fleet_level_summary.csv` 严格五行；`solutions/` 保存每个配对单元的完整双臂解。"
                "每行的 `solution_sha256` 是该双臂完整科学载荷的规范 JSON SHA-256，双臂解另有各自哈希。"
            ),
            (
                "充电时刻改变只统计可按路线、站点、能量和时长一一匹配的动作；无法匹配的动作单列，"
                "不被改写成时刻变化。车型和路线变化按客户计数，路线数与实体车数始终分列。"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def fmt(value: Any) -> str:
    if value is None or value == "":
        return "NA"
    return f"{float(value):.6f}"


def artifact_hashes(output: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(output.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("._") or path.name in SCIENTIFIC_HASH_EXCLUDES:
            continue
        if "__pycache__" in path.parts or ".pytest_cache" in path.parts:
            continue
        result[str(path.relative_to(output))] = sha256_path(path)
    return result


def unit_path(output: Path, level: int, seed: int) -> Path:
    return output / "solutions" / f"level_{level:03d}" / f"seed_{seed:02d}.json"


def flattened_arm_rows(rows: list[dict[str, Any]], output: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        path = unit_path(
            output,
            int(row["fleet_level_percent"]),
            int(row["seed"]),
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        for arm in ARM_ORDER:
            arm_payload = payload.get("arms", {}).get(arm)
            if arm_payload is None:
                arm_failure = payload.get("arm_failures", {}).get(arm, {})
                result.append(
                    {
                        "unit_id": row["unit_id"],
                        "fleet_level_percent": row["fleet_level_percent"],
                        "seed": row["seed"],
                        "arm": arm,
                        "status": arm_failure.get("status", row["status"]),
                        "failure_reason": arm_failure.get(
                            "failure_reason", row.get("failure_reason", "")
                        ),
                    }
                )
                continue
            breakdown = arm_payload["breakdown"]
            result.append(
                {
                    "unit_id": row["unit_id"],
                    "fleet_level_percent": row["fleet_level_percent"],
                    "seed": row["seed"],
                    "arm": arm,
                    "status": "PASS",
                    "objective": arm_payload["objective"],
                    "operating_cost_cny": _operating_cost(breakdown),
                    "full_model_cost_cny": breakdown["total_cost"],
                    "system_emissions_kg": breakdown["E_total"],
                    "charging_emissions_kg": breakdown["E_ev_indirect"],
                    "used_cv": arm_payload["used_cv"],
                    "used_ev": arm_payload["used_ev"],
                    "used_physical_vehicles": arm_payload["used_total"],
                    "route_count": arm_payload["route_count"],
                    "solution_sha256": arm_payload["solution_sha256"],
                    "hgs_iterations_by_view": arm_payload["hgs_iterations_by_view"],
                    "stop_reasons_by_view": arm_payload["stop_reasons_by_view"],
                    "elapsed_seconds": arm_payload["elapsed_seconds"],
                    "failure_reason": "",
                }
            )
    return result


def progress_payload(rows: list[dict[str, Any]], total: int) -> dict[str, Any]:
    return {
        "schema_version": "resetp.xb-progress.v1",
        "status": "RUNNING",
        "updated_at": now_utc(),
        "completed_formal_units": len(rows),
        "expected_formal_units": int(total),
        "pass_count": sum(row["status"] == "PASS" for row in rows),
        "infeasible_or_not_found_count": sum(
            row["status"] == "INFEASIBLE_OR_NOT_FOUND" for row in rows
        ),
        "technical_error_count": sum(
            row["status"] == "TECHNICAL_ERROR" for row in rows
        ),
    }


def worker_receipt_path(output: Path, level: int, seed: int) -> Path:
    return output / "worker_receipts" / f"level_{level:03d}__seed_{seed:02d}.json"


def worker_log_path(output: Path, level: int, seed: int) -> Path:
    return output / "worker_logs" / f"level_{level:03d}__seed_{seed:02d}.log"


def run_subprocess_workers(
    output: Path,
    specs: list[tuple[int, int]],
    registered_source_hashes: dict[str, str],
    workers: int,
) -> Iterable[tuple[int, int, dict[str, Any]]]:
    """Yield unit results from independent Python children without semaphores."""

    prereg_path = output / "preregistration.json"
    pending = iter(specs)
    active: dict[subprocess.Popen[bytes], tuple[int, int, Any]] = {}

    def launch(level: int, seed: int) -> None:
        receipt = worker_receipt_path(output, level, seed)
        log_path = worker_log_path(output, level, seed)
        if receipt.exists() or log_path.exists():
            raise FileExistsError(
                f"refusing to overwrite worker evidence for {level}/{seed}"
            )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        receipt.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("wb")
        command = [
            sys.executable,
            "-m",
            MODULE_NAME,
            "--worker-level",
            str(level),
            "--worker-seed",
            str(seed),
            "--worker-preregistration",
            str(prereg_path),
            "--worker-result",
            str(receipt),
        ]
        process = subprocess.Popen(
            command,
            cwd=REPO,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        active[process] = (level, seed, log_handle)

    for _ in range(min(int(workers), len(specs))):
        try:
            launch(*next(pending))
        except StopIteration:
            break

    while active:
        completed = [process for process in active if process.poll() is not None]
        if not completed:
            time.sleep(0.2)
            continue
        for process in completed:
            level, seed, log_handle = active.pop(process)
            log_handle.close()
            receipt = worker_receipt_path(output, level, seed)
            if process.returncode == 0 and receipt.exists():
                result = json.loads(receipt.read_text(encoding="utf-8"))
            else:
                log_path = worker_log_path(output, level, seed)
                tail = log_path.read_text(
                    encoding="utf-8", errors="replace"
                )[-8_000:]
                failure = (
                    f"worker process exited {process.returncode} without a valid receipt"
                )
                result = {
                    "row": {
                        "unit_id": f"level_{level:03d}__seed_{seed:02d}",
                        "instance_id": INSTANCE_ID,
                        "fleet_level_percent": level,
                        "seed": seed,
                        "status": "TECHNICAL_ERROR",
                        "violation_count": 1,
                        "violations": [failure],
                        "attempted_search_arm_count": 0,
                        "successful_search_arm_count": 0,
                        "complete_solution_available": False,
                        "solution_kind": "NO_COMPLETE_SOLUTION_WORKER_EXIT",
                        "failure_reason": failure,
                    },
                    "payload": {
                        "status": "TECHNICAL_ERROR",
                        "failure_reason": failure,
                        "worker_log_tail": tail,
                    },
                    "technical_error": True,
                }
                if not receipt.exists():
                    write_json(receipt, result)
            yield level, seed, result
            try:
                launch(*next(pending))
            except StopIteration:
                pass

    verify_source_lock(registered_source_hashes)


def execute_worker(
    level: int,
    seed: int,
    preregistration_path: Path,
    result_path: Path,
    max_iterations: int,
    max_no_improvement: int,
) -> int:
    if result_path.exists():
        raise FileExistsError(f"refusing to overwrite worker receipt: {result_path}")
    prereg = json.loads(preregistration_path.read_text(encoding="utf-8"))
    registered_source_hashes = prereg["source_files_sha256"]
    result = run_unit(
        int(level),
        int(seed),
        registered_source_hashes,
        max_iterations=int(max_iterations),
        max_no_improvement=int(max_no_improvement),
    )
    write_json(result_path, result)
    print(
        json.dumps(
            {
                "unit_id": result["row"]["unit_id"],
                "status": result["row"]["status"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def execute(output: Path, workers: int) -> int:
    if output.exists():
        raise FileExistsError(
            f"refusing to overwrite or resume an existing result directory: {output}"
        )
    output.mkdir(parents=True, exist_ok=False)
    (output / "solutions").mkdir()
    (output / "worker_receipts").mkdir()
    (output / "worker_logs").mkdir()
    registered_source_hashes = source_hashes()
    base_bundle = load_base_bundle()
    registered_input_hashes = input_hashes(base_bundle)
    prereg = preregistration(
        registered_source_hashes,
        registered_input_hashes,
    )
    write_json(output / "preregistration.json", prereg)
    metadata = initial_metadata(prereg, workers)
    write_json(output / "metadata.json", metadata)
    write_json(output / "progress.json", progress_payload([], len(LEVELS) * len(SEEDS)))

    specs = [(level, seed) for level in LEVELS for seed in SEEDS]
    rows: list[dict[str, Any]] = []
    pool_broken: str | None = None
    for level, seed, result in run_subprocess_workers(
        output,
        specs,
        registered_source_hashes,
        int(workers),
    ):
        if result["row"]["status"] == "TECHNICAL_ERROR":
            pool_broken = result["row"].get("failure_reason") or "worker error"
        write_json(unit_path(output, level, seed), result["payload"])
        rows.append(result["row"])
        rows.sort(
            key=lambda row: (
                int(row["fleet_level_percent"]),
                int(row["seed"]),
            )
        )
        write_csv(output / "raw_runs.csv", rows, RAW_FIELDS)
        write_json(
            output / "progress.json",
            progress_payload(rows, len(specs)),
        )

    observed_ids = {row["unit_id"] for row in rows}
    expected_ids = {
        f"level_{level:03d}__seed_{seed:02d}"
        for level, seed in specs
    }
    technical_errors = [
        row for row in rows if row["status"] == "TECHNICAL_ERROR"
    ]
    try:
        verify_source_lock(registered_source_hashes)
        source_drift = False
        source_drift_reason = ""
    except SourceDriftError as exc:
        source_drift = True
        source_drift_reason = str(exc)

    complete_shape = (
        len(rows) == len(specs)
        and observed_ids == expected_ids
        and len(observed_ids) == len(rows)
    )
    status = (
        TERMINAL_STATUS
        if complete_shape and not technical_errors and not source_drift
        else "HALT_XB_TECHNICAL_OR_EVIDENCE_INCOMPLETE"
    )
    summary = level_summary(rows)
    write_csv(
        output / "fleet_level_summary.csv",
        summary,
        summary[0].keys(),
    )
    arm_rows = flattened_arm_rows(rows, output)
    arm_fields = sorted({key for row in arm_rows for key in row})
    write_csv(output / "arm_runs.csv", arm_rows, arm_fields)
    decision = {
        "schema_version": "resetp.xb-formal-decision.v1",
        "task_id": TASK_ID,
        "status": status,
        "completed_at": now_utc(),
        "expected_formal_units": len(specs),
        "observed_formal_units": len(rows),
        "expected_search_arm_executions": 2 * len(specs),
        "observed_search_arm_executions": sum(
            int(row.get("attempted_search_arm_count") or 0) for row in rows
        ),
        "complete_unit_identity_set": complete_shape,
        "pass_count": sum(row["status"] == "PASS" for row in rows),
        "infeasible_or_not_found_count": sum(
            row["status"] == "INFEASIBLE_OR_NOT_FOUND" for row in rows
        ),
        "technical_error_count": len(technical_errors),
        "pool_broken_reason": pool_broken,
        "source_drift": source_drift,
        "source_drift_reason": source_drift_reason,
        "all_rows_retained": len(rows) == len(specs),
        "seed_replacement_count": 0,
        "rerun_for_direction_count": 0,
        "constraint_relaxation_count": 0,
        "claim_assessment": assessment(rows),
        "five_row_summary": summary,
    }
    write_json(output / "decision.json", decision)
    write_text(output / "report.md", report_text(decision, summary))
    metadata.update(
        {
            "status": status,
            "completed_at": now_utc(),
            "observed_formal_units": len(rows),
            "observed_search_arm_executions": decision[
                "observed_search_arm_executions"
            ],
            "source_drift": source_drift,
        }
    )
    write_json(output / "metadata.json", metadata)
    hashes = artifact_hashes(output)
    if any(
        Path(relative).name.startswith("._")
        or "__pycache__" in Path(relative).parts
        or ".pytest_cache" in Path(relative).parts
        for relative in hashes
    ):
        raise RuntimeError("artifact hash exclusion contract failed")
    write_json(output / "artifact_hashes.json", hashes)
    for relative, expected in hashes.items():
        observed = sha256_path(output / relative)
        if observed != expected:
            raise RuntimeError(f"artifact hash mismatch after finalization: {relative}")
    done = {
        "schema_version": "resetp.xb-done.v1",
        "status": status,
        "completed_at": now_utc(),
        "decision_sha256": sha256_path(output / "decision.json"),
        "artifact_hashes_sha256": sha256_path(output / "artifact_hashes.json"),
    }
    write_json(output / "done.json", done)
    return 0 if status == TERMINAL_STATUS else 2


def self_test() -> int:
    allocations = allocations_by_level()
    totals = {
        level: sum(value["total_fleet_cap"] for value in by_depot.values())
        for level, by_depot in allocations.items()
    }
    assert len(set(totals.values())) == 1
    assert all(value["num_ev"] == 0 for value in allocations[0].values())
    assert all(value["num_cv"] == 0 for value in allocations[100].values())
    base = load_base_bundle()
    assert base.model_config["strict_multitrip"] is True
    assert base.model_config["depot_charger_capacity_mode"] == "unbounded"
    for level in LEVELS:
        bundle = bundle_for_level(level, carbon_blind=False)
        assert sum(bundle.instance.num_cv for _ in [0]) == sum(
            value["num_cv"] for value in allocations[level].values()
        )
        assert bundle.instance.num_cv + bundle.instance.num_ev == totals[level]
    print(
        json.dumps(
            {
                "status": "PASS_XB_SELF_TEST",
                "instance_id": INSTANCE_ID,
                "selected_instance_total_fleet": totals,
                "source_tree_sha256": source_tree_sha256(source_hashes()),
                "dependency_record": dependency_record(),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def smoke(level: int, seed: int, output: Path) -> int:
    if output.exists():
        raise FileExistsError(f"smoke output already exists: {output}")
    output.mkdir(parents=True)
    hashes = source_hashes()
    result = run_unit(
        int(level),
        int(seed),
        hashes,
        max_iterations=5,
        max_no_improvement=2,
    )
    write_json(output / "smoke.json", result)
    print(
        json.dumps(
            {
                "status": result["row"]["status"],
                "level": int(level),
                "seed": int(seed),
                "output": str(output),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result["row"]["status"] == "PASS" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--smoke-level", type=int, choices=LEVELS, default=0)
    parser.add_argument("--smoke-seed", type=int, default=1)
    parser.add_argument("--worker-level", type=int, choices=LEVELS)
    parser.add_argument("--worker-seed", type=int)
    parser.add_argument("--worker-preregistration", type=Path)
    parser.add_argument("--worker-result", type=Path)
    parser.add_argument("--worker-max-iterations", type=int, default=MAX_ITERATIONS)
    parser.add_argument(
        "--worker-max-no-improvement",
        type=int,
        default=MAX_NO_IMPROVEMENT,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()
    if args.smoke:
        return smoke(args.smoke_level, args.smoke_seed, args.output)
    worker_args = (
        args.worker_level,
        args.worker_seed,
        args.worker_preregistration,
        args.worker_result,
    )
    if any(value is not None for value in worker_args):
        if not all(value is not None for value in worker_args):
            raise ValueError("all worker arguments must be supplied together")
        return execute_worker(
            args.worker_level,
            args.worker_seed,
            args.worker_preregistration.resolve(),
            args.worker_result.resolve(),
            args.worker_max_iterations,
            args.worker_max_no_improvement,
        )
    if args.workers < 1 or args.workers > len(LEVELS) * len(SEEDS):
        raise ValueError("workers must be between 1 and 50")
    return execute(args.output.resolve(), args.workers)


if __name__ == "__main__":
    raise SystemExit(main())
