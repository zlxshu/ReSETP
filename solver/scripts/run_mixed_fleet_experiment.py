#!/usr/bin/env python3
"""Run MAIN-2 mixed-fleet arms serially with paired seed identities.

Dry-run mode performs only input, arm, budget, and pairing validation.  A
non-dry run additionally requires an externally frozen Pi0 manifest and writes
one auditable package without starting parallel workers.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
import traceback
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from time import perf_counter
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence


MAX_WALL_CLOCK_SECONDS = 20.0 * 60.0
PROTECTED = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)
FORBIDDEN_OUTPUT_DIRS = (
    "solver/reports/public_v2_28_clean_ruler_20260810",
    "solver/reports/dss_step1_gate2",
    "solver/reports/endogenous_fleet_trial_20260810",
)
FLEET_AUTHORITY = Path(
    "data/ChinaInstances/"
    "china81_finite_fleet_authority_v3_20260802/fleet_caps.csv"
)
WITNESS_DIR = Path(
    "data/ChinaInstances/"
    "china81_finite_fleet_authority_v3_20260802/witnesses"
)

FLEET_PARAMETER_CLASS_IDS = {
    "fixed25": "DERIVED_FIXED_TOTAL_MULTITRIP_ZERO_SEARCH_AUTHORITY",
    "endogenous": "ENDOGENOUS_RD_RE_NO_ADDITIONAL_TOTAL_CAP",
}


@dataclass(frozen=True)
class ArmDefinition:
    arm: str
    label: str
    cap_mode: str
    initial_witness_level: str
    role: str


ARM_DEFINITIONS: Mapping[str, ArmDefinition] = {
    "endogenous": ArmDefinition(
        "endogenous",
        "内生 CV/EV 搭配（每车场 Rd/Re，无额外总量上限）",
        "endogenous_rd_re",
        "25",
        "MAIN_TREATMENT",
    ),
    "fixed25": ArmDefinition(
        "fixed25",
        "原 25% 固定车队参考",
        "fixed25",
        "25",
        "HISTORICAL_REFERENCE",
    ),
    "same_total_cap": ArmDefinition(
        "same_total_cap",
        "车型可选但沿用原 25% 总车数上限",
        "endogenous_types_fixed25_total",
        "25",
        "FLEET_SIZE_CONFOUND_CONTROL",
    ),
    "all_cv": ArmDefinition(
        "all_cv",
        "全燃油优化端点",
        "all_cv_rd",
        "0",
        "OPTIONAL_OPTIMIZED_ENDPOINT",
    ),
    "all_ev": ArmDefinition(
        "all_ev",
        "全电优化端点",
        "all_ev_re",
        "100",
        "OPTIONAL_OPTIMIZED_ENDPOINT",
    ),
}


@dataclass(frozen=True)
class PairIdentity:
    arm: str
    instance_id: str
    seed: int
    main_rng_seed: int
    wall_clock_budget_seconds: float
    objective_mode: str
    input_snapshot_sha256: str
    algorithm_protocol: str
    pair_group_id: str


@dataclass(frozen=True)
class _PreparedPopulation:
    candidates: tuple[Any, ...]
    evaluations: tuple[Any, ...]
    full_evaluation_count: int


PAIR_FIELDS = (
    "instance_id",
    "seed",
    "main_rng_seed",
    "wall_clock_budget_seconds",
    "objective_mode",
    "input_snapshot_sha256",
    "algorithm_protocol",
    "pair_group_id",
)


class PairingMismatchError(RuntimeError):
    """Raised when a supposed same-seed comparison changes a common field."""


def validate_pairing(identities: Sequence[PairIdentity]) -> None:
    if not identities:
        raise ValueError("paired validation requires at least one arm")
    reference = identities[0]
    differences: dict[str, dict[str, dict[str, Any]]] = {}
    for identity in identities[1:]:
        arm_differences = {}
        for field in PAIR_FIELDS:
            expected = getattr(reference, field)
            actual = getattr(identity, field)
            if actual != expected:
                arm_differences[field] = {
                    "expected_from_arm": reference.arm,
                    "expected": expected,
                    "actual": actual,
                }
        if arm_differences:
            differences[identity.arm] = arm_differences
    if differences:
        raise PairingMismatchError(
            "mixed-fleet paired inputs differ; refusing to run: "
            + json.dumps(differences, ensure_ascii=False, sort_keys=True)
        )


@dataclass
class _BestClock:
    wall_clock_budget_seconds: float
    best_cost: float | None = None
    time_to_best_seconds: float | None = None

    def stop(self, state: Any) -> bool:
        if state.best_cost is not None and (
            self.best_cost is None or float(state.best_cost) < self.best_cost
        ):
            self.best_cost = float(state.best_cost)
            self.time_to_best_seconds = float(state.elapsed_seconds)
        return float(state.elapsed_seconds) >= self.wall_clock_budget_seconds


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _validate_output_path(repo: Path, output: Path) -> None:
    resolved = output.resolve()
    for relative in FORBIDDEN_OUTPUT_DIRS:
        protected = (repo / relative).resolve()
        if resolved == protected or _is_relative_to(resolved, protected):
            raise ValueError(f"output may not touch active directory: {relative}")


def _authority_rows(repo: Path) -> dict[str, dict[str, dict[str, str]]]:
    path = repo / FLEET_AUTHORITY
    with path.open(newline="", encoding="utf-8") as handle:
        rows: dict[str, dict[str, dict[str, str]]] = {}
        for row in csv.DictReader(handle):
            rows.setdefault(row["instance_id"], {})[row["depot_id"]] = row
    return rows


def _validate_witness(repo: Path, instance_id: str, levels: Iterable[str]) -> None:
    path = repo / WITNESS_DIR / f"{instance_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if str(payload.get("instance_id")) != instance_id:
        raise ValueError(f"witness identity mismatch: {path}")
    for level_name in levels:
        level = payload.get("levels", {}).get(level_name)
        if not isinstance(level, dict):
            raise ValueError(f"witness has no level {level_name}: {instance_id}")
        if level.get("status") != "CERTIFIED" or level.get("violations"):
            raise ValueError(
                f"witness level is not certified: {instance_id}/{level_name}"
            )


def _input_snapshot(repo: Path, instances: Sequence[str]) -> dict[str, str]:
    paths = [repo / FLEET_AUTHORITY]
    paths.extend(repo / WITNESS_DIR / f"{instance}.json" for instance in instances)
    return {
        str(path.relative_to(repo)): _sha256(path)
        for path in sorted(paths)
    }


def _pair_identities(
    arms: Sequence[str],
    *,
    instance_id: str,
    seed: int,
    wall_clock_budget_seconds: float,
    objective_mode: str,
    input_snapshot_sha256: str,
) -> tuple[PairIdentity, ...]:
    common = {
        "instance_id": instance_id,
        "seed": int(seed),
        "main_rng_seed": int(seed),
        "wall_clock_budget_seconds": float(wall_clock_budget_seconds),
        "objective_mode": objective_mode,
        "input_snapshot_sha256": input_snapshot_sha256,
        "algorithm_protocol": "PROBLEM_HGS_SERIAL_CHAIN_CURRENT_CHECKOUT",
    }
    pair_group_id = _json_sha256(common)
    return tuple(
        PairIdentity(arm=arm, pair_group_id=pair_group_id, **common)
        for arm in arms
    )


def _load_pi0_manifest(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "resetp.formal_pi0.v1":
        raise ValueError("Pi0 manifest schema must be resetp.formal_pi0.v1")
    instances = payload.get("instances")
    if not isinstance(instances, dict):
        raise ValueError("Pi0 manifest requires an instances object")
    parsed: dict[str, dict[str, Any]] = {}
    for instance_id, record in instances.items():
        if not isinstance(record, dict) or not isinstance(record.get("values"), dict):
            raise ValueError(f"Pi0 record is malformed: {instance_id}")
        values = {str(key): float(value) for key, value in record["values"].items()}
        if not values or any(value <= 0.0 for value in values.values()):
            raise ValueError(f"Pi0 values must be positive: {instance_id}")
        value_sha256 = _json_sha256(
            [[key, float(value).hex()] for key, value in sorted(values.items())]
        )
        declared = record.get("value_sha256")
        if declared is not None and str(declared).lower() != value_sha256:
            raise ValueError(f"Pi0 value hash mismatch: {instance_id}")
        source_id = str(record.get("source_id", "")).strip()
        if not source_id:
            raise ValueError(f"Pi0 source_id is required: {instance_id}")
        parsed[str(instance_id)] = {
            "values": values,
            "value_sha256": value_sha256,
            "source_id": source_id,
        }
    return parsed


def _validate_static_inputs(args: argparse.Namespace, repo: Path) -> dict[str, Any]:
    _validate_output_path(repo, args.output_dir)
    authorities = _authority_rows(repo)
    missing = [instance for instance in args.instances if instance not in authorities]
    if missing:
        raise ValueError(f"instances absent from fleet authority: {missing}")
    required_levels = {
        ARM_DEFINITIONS[arm].initial_witness_level for arm in args.arms
    }
    for instance in args.instances:
        _validate_witness(repo, instance, required_levels)
    source_hashes = _input_snapshot(repo, args.instances)
    snapshot_sha = _json_sha256(source_hashes)
    pi0_records = None
    if args.pi0_manifest is not None:
        pi0_records = _load_pi0_manifest(args.pi0_manifest.resolve())
        missing_pi0 = [instance for instance in args.instances if instance not in pi0_records]
        if missing_pi0:
            raise ValueError(f"Pi0 manifest misses requested instances: {missing_pi0}")
        for instance in args.instances:
            expected_depots = set(authorities[instance])
            actual_depots = set(pi0_records[instance]["values"])
            if actual_depots != expected_depots:
                raise ValueError(
                    f"Pi0 depot set mismatch for {instance}: "
                    f"expected={sorted(expected_depots)}, actual={sorted(actual_depots)}"
                )
    return {
        "source_hashes": source_hashes,
        "input_snapshot_sha256": snapshot_sha,
        "pi0_records": pi0_records,
    }


def _dry_run_payload(
    args: argparse.Namespace,
    repo: Path,
    validated: Mapping[str, Any],
) -> dict[str, Any]:
    fleet_parameter_class_id = _metadata_fleet_parameter_class_id(args.arms)
    groups = []
    for instance in args.instances:
        for seed in args.seeds:
            identities = _pair_identities(
                args.arms,
                instance_id=instance,
                seed=seed,
                wall_clock_budget_seconds=args.wall_clock_seconds,
                objective_mode=args.objective_mode,
                input_snapshot_sha256=validated["input_snapshot_sha256"],
            )
            validate_pairing(identities)
            groups.append([asdict(identity) for identity in identities])
    return {
        "mode": "DRY_RUN",
        "experiment_id": "MAIN-2",
        "solver_entered": False,
        "output_directory_created": False,
        "serial_execution": True,
        "instances": list(args.instances),
        "seeds": list(args.seeds),
        "arms": {
            arm: asdict(ARM_DEFINITIONS[arm]) for arm in args.arms
        },
        "wall_clock_budget_seconds_per_run": args.wall_clock_seconds,
        "p20_limit_seconds": MAX_WALL_CLOCK_SECONDS,
        "objective_mode": args.objective_mode,
        "fleet_parameter_class_id": fleet_parameter_class_id,
        "fleet_parameter_class_ids_by_arm": {
            arm: _planned_fleet_parameter_class_id(arm) for arm in args.arms
        },
        "pareto_export_planned": args.objective_mode == "bi_objective",
        "pair_validation": "PASSED",
        "pair_fields": PAIR_FIELDS,
        "pair_groups": groups,
        "planned_run_count": len(args.instances) * len(args.seeds) * len(args.arms),
        "input_source_hashes": validated["source_hashes"],
        "input_snapshot_sha256": validated["input_snapshot_sha256"],
        "pi0_manifest": (
            None if args.pi0_manifest is None else str(args.pi0_manifest.resolve())
        ),
        "formal_launch_ready": validated["pi0_records"] is not None,
        "formal_package_files": (
            "metadata.json",
            "raw_runs.csv",
            "report.md",
            "artifact_hashes.json",
        ),
        "additional_pareto_file": "pareto_points.csv",
    }


def _witness_skeleton(repo: Path, bundle: Any, level_name: str) -> Any:
    from setp_solver.solution import Route, Solution

    path = repo / WITNESS_DIR / f"{bundle.instance_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    level = payload["levels"][level_name]
    routes = []
    for depot_id, depot in sorted(level["depots"].items()):
        for vehicle_type in ("cv", "ev"):
            for index, timed in enumerate(depot[f"{vehicle_type}_routes"], start=1):
                routes.append(
                    Route(
                        vehicle_id=(
                            f"MAIN2-{depot_id}-{vehicle_type.upper()}-{index:03d}"
                        ),
                        vehicle_type=vehicle_type,
                        home_depot_id=depot_id,
                        node_sequence=[
                            depot_id,
                            *[str(customer) for customer in timed["customers"]],
                            depot_id,
                        ],
                    )
                )
    return Solution(routes=routes)


def _witness_endpoint_solution(
    repo: Path,
    bundle: Any,
    level_name: str,
) -> Any:
    """Materialise the authority's certified homogeneous multi-trip witness."""

    from setp_solver.china81_completion import annotate_cross_site_services
    from setp_solver.search.multitrip_schedule import _curve_for_prices
    from setp_solver.solution import (
        ChargingAction,
        Route,
        Solution,
        route_trip_vehicle_id,
    )

    payload = json.loads(
        (repo / WITNESS_DIR / f"{bundle.instance_id}.json").read_text(
            encoding="utf-8"
        )
    )
    level = payload["levels"][level_name]
    curve = _curve_for_prices(bundle.prices, bundle.instance)
    routes = []
    actions = []
    for depot_id, depot in sorted(level["depots"].items()):
        for vehicle_type in ("cv", "ev"):
            by_route_id = {
                str(row["route_id"]): row
                for row in depot[f"{vehicle_type}_routes"]
            }
            for vehicle_index, chain in enumerate(
                depot[f"{vehicle_type}_cover"]["chains"],
                start=1,
            ):
                physical_id = f"{vehicle_type.upper()}_{depot_id}_{vehicle_index}"
                previous_return = 6.0 * 60.0 * 60.0
                for trip_index, route_id in enumerate(chain, start=1):
                    timed = by_route_id[str(route_id)]
                    trip_vehicle_id = route_trip_vehicle_id(
                        physical_id,
                        trip_index,
                    )
                    routes.append(
                        Route(
                            vehicle_id=trip_vehicle_id,
                            vehicle_type=vehicle_type,
                            home_depot_id=depot_id,
                            node_sequence=[
                                depot_id,
                                *[str(customer) for customer in timed["customers"]],
                                depot_id,
                            ],
                        )
                    )
                    if vehicle_type == "ev":
                        energy = float(timed["drive_energy_kwh"])
                        duration = curve.duration_seconds(0.0, energy)
                        if (
                            previous_return + duration
                            > float(timed["departure_second"]) + 1.0e-6
                        ):
                            raise ValueError(
                                "certified endpoint chain cannot recharge before "
                                f"departure: {bundle.instance_id}/{depot_id}/{route_id}"
                            )
                        actions.append(
                            ChargingAction(
                                vehicle_id=trip_vehicle_id,
                                station_id=depot_id,
                                energy_kwh=energy,
                                occupancy_minutes=duration / 60.0,
                                charge_start_second=previous_return,
                                start_energy_kwh=0.0,
                                end_energy_kwh=energy,
                                charging_curve_id=curve.curve_id,
                            )
                        )
                    previous_return = float(timed["return_second"])
    solution = Solution(routes=routes, charging_actions=actions)
    return annotate_cross_site_services(solution, bundle.customer_home_depot)


def _register_available_slots(individual: Any, bundle: Any) -> Any:
    """Register typed candidates even in the same-total-cap control arm."""

    from setp_solver.algorithms.problem_hgs.model import PhysicalVehicleDuty

    by_id = {duty.physical_vehicle_id: duty for duty in individual.duties}
    for depot_id, caps in sorted(bundle.fleet_caps_by_depot.items()):
        expected_ids = set()
        for vehicle_type, field in (("cv", "num_cv"), ("ev", "num_ev")):
            for index in range(1, int(caps[field]) + 1):
                vehicle_id = f"{vehicle_type.upper()}_{depot_id}_{index}"
                expected_ids.add(vehicle_id)
                by_id.setdefault(
                    vehicle_id,
                    PhysicalVehicleDuty(
                        physical_vehicle_id=vehicle_id,
                        vehicle_type=vehicle_type,
                        home_depot_id=depot_id,
                        trips=(),
                    ),
                )
        actual_ids = {
            duty.physical_vehicle_id
            for duty in individual.duties
            if duty.home_depot_id == depot_id
        }
        unexpected = actual_ids.difference(expected_ids)
        if unexpected:
            raise RuntimeError(
                "initial solution uses unregistered vehicles: "
                + ", ".join(sorted(unexpected))
            )
    return replace(
        individual,
        duties=tuple(by_id[vehicle_id] for vehicle_id in sorted(by_id)),
        source="main2-mixed-fleet-initial",
    )


def _arm_bundle(repo: Path, instance_id: str, arm: str) -> Any:
    from setp_solver.china81 import (
        ENDOGENOUS_FLEET_PARAMETERS,
        FIXED_25_PERCENT_FLEET_PARAMETERS,
        load_china81_bundle,
    )

    fixed = load_china81_bundle(
        repo,
        instance_id,
        fleet_parameters=FIXED_25_PERCENT_FLEET_PARAMETERS,
    )
    if arm == "fixed25":
        return fixed
    endogenous = load_china81_bundle(
        repo,
        instance_id,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
    )
    if arm == "endogenous":
        return endogenous

    caps = {}
    for depot_id, row in endogenous.fleet_caps_by_depot.items():
        rd = int(row["num_cv"])
        re = int(row["num_ev"])
        if arm == "same_total_cap":
            values = {
                "num_cv": rd,
                "num_ev": re,
                "total_fleet_cap": int(
                    fixed.fleet_caps_by_depot[depot_id]["total_fleet_cap"]
                ),
            }
        elif arm == "all_cv":
            values = {"num_cv": rd, "num_ev": 0, "total_fleet_cap": rd}
        elif arm == "all_ev":
            values = {"num_cv": 0, "num_ev": re, "total_fleet_cap": re}
        else:  # pragma: no cover - argparse prevents this branch.
            raise ValueError(f"unknown arm: {arm}")
        caps[depot_id] = MappingProxyType(values)
    return replace(
        endogenous,
        instance=replace(
            endogenous.instance,
            num_cv=sum(int(row["num_cv"]) for row in caps.values()),
            num_ev=sum(int(row["num_ev"]) for row in caps.values()),
        ),
        fleet_caps_by_depot=MappingProxyType(caps),
        fleet_parameter_class_id=ARM_DEFINITIONS[arm].cap_mode,
        has_additional_total_fleet_cap=(arm == "same_total_cap"),
    )


def _planned_fleet_parameter_class_id(arm: str) -> str:
    if arm in FLEET_PARAMETER_CLASS_IDS:
        return FLEET_PARAMETER_CLASS_IDS[arm]
    return ARM_DEFINITIONS[arm].cap_mode


def _metadata_fleet_parameter_class_id(arms: Sequence[str]) -> str | list[str]:
    class_ids = list(
        dict.fromkeys(_planned_fleet_parameter_class_id(arm) for arm in arms)
    )
    return class_ids[0] if len(class_ids) == 1 else class_ids


def _arm_setup(
    repo: Path,
    instance_id: str,
    arm: str,
    pi0_record: Mapping[str, Any],
) -> tuple[Any, Any, Any]:
    from setp_solver.algorithms.problem_hgs.evaluation import (
        DutyEvaluationContext,
        FrozenMappingIdentity,
        mapping_sha256,
    )
    from setp_solver.algorithms.problem_hgs.model import DutyIndividual
    from setp_solver.china81_completion import complete_china81_route_skeleton
    from setp_solver.search.multitrip_schedule import (
        DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
    )

    bundle = _arm_bundle(repo, instance_id, arm)
    level_name = ARM_DEFINITIONS[arm].initial_witness_level
    if arm in {"all_cv", "all_ev"}:
        completed = _witness_endpoint_solution(repo, bundle, level_name)
    else:
        skeleton = _witness_skeleton(repo, bundle, level_name)
        completed = complete_china81_route_skeleton(skeleton, bundle).solution
    initial = _register_available_slots(DutyIndividual.from_solution(completed), bundle)
    pi0 = dict(pi0_record["values"])
    if set(pi0) != set(bundle.fleet_caps_by_depot):
        raise ValueError(f"Pi0 depot set differs from bundle: {instance_id}")
    runtime_sha = mapping_sha256(pi0)
    if runtime_sha != pi0_record["value_sha256"]:
        raise ValueError(f"Pi0 runtime hash differs from manifest: {instance_id}")
    context = DutyEvaluationContext(
        bundle=bundle,
        independent_profit=pi0,
        independent_profit_identity=FrozenMappingIdentity(
            source_id=str(pi0_record["source_id"]),
            value_sha256=runtime_sha,
            externally_frozen=True,
        ),
        prior_profit={depot_id: 0.0 for depot_id in pi0},
        theta=1.0,
        carbon_quota_kg=0.0,
        depot_charge_window_mode=DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
        fairness_enabled=True,
    )
    return bundle, initial, context


def _prepare_population(
    initial: Any,
    context: Any,
    *,
    seed: int,
    wall_clock_budget_seconds: float,
    objective_mode: str,
    population_mode: str,
) -> tuple[Any, float]:
    from run_problem_hgs_private_technical import (
        _parameters,
        _policy,
        _prepare_population as _prepare_reference_population,
    )
    from setp_solver.algorithms.problem_hgs.evaluation import DutyFullEvaluator
    from setp_solver.algorithms.problem_hgs.initialization import (
        build_initial_population,
    )
    from setp_solver.algorithms.problem_hgs.kernel_proposals import (
        IndependentKernelDutyRouteProposalEngine,
    )

    started = perf_counter()
    evaluator = DutyFullEvaluator(context)
    policy = _policy(evaluator)
    parameters = _parameters(
        random_seed=seed,
        population_mode=population_mode,
        crossover_mode="fast_only",
        objective_mode=objective_mode,
    )
    full_calls_before = evaluator.full_calls
    if population_mode == "technical_two_parent":
        (
            candidates,
            _initial_evaluation,
            _reverse,
            _attempts,
            _selected,
            evaluations,
        ) = _prepare_reference_population(
            initial,
            evaluator,
            policy,
            parameters,
            require_distinct_selection=False,
        )
        built = _PreparedPopulation(
            candidates=tuple(candidates),
            evaluations=tuple(evaluations),
            full_evaluation_count=evaluator.full_calls - full_calls_before,
        )
    else:
        route_engine = IndependentKernelDutyRouteProposalEngine(
            context,
            initial,
            random_seed=seed,
            stream_role="main2_initialization",
        )
        population = build_initial_population(
            initial,
            evaluator=evaluator,
            charging_policy=policy,
            route_engine=route_engine,
            requested_size=parameters.population.min_pop_size,
            random_seed=seed,
            max_random_attempts=None,
            stop_requested=lambda: (
                perf_counter() - started >= wall_clock_budget_seconds
            ),
        )
        built = _PreparedPopulation(
            candidates=tuple(population.candidates),
            evaluations=tuple(population.evaluations),
            full_evaluation_count=evaluator.full_calls - full_calls_before,
        )
    if not built.candidates:
        raise RuntimeError("initial population construction returned no candidate")
    return built, perf_counter() - started


def _service_fields(individual: Any, bundle: Any) -> dict[str, float | int]:
    served = {
        customer
        for duty in individual.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }
    customer_nodes = {
        node.node_id: node
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    served_demand = sum(float(customer_nodes[item].demand) for item in served)
    total_demand = sum(float(node.demand) for node in customer_nodes.values())
    return {
        "customers_served": len(served),
        "customers_total": len(customer_nodes),
        "customer_completion_ratio": (
            len(served) / len(customer_nodes) if customer_nodes else 1.0
        ),
        "demand_served": served_demand,
        "demand_total": total_demand,
        "demand_completion_ratio": (
            served_demand / total_demand if total_demand else 1.0
        ),
    }


def _fleet_fields(individual: Any) -> dict[str, int]:
    used = [duty for duty in individual.duties if duty.trips]
    return {
        "used_cv_vehicles": sum(duty.vehicle_type == "cv" for duty in used),
        "used_ev_vehicles": sum(duty.vehicle_type == "ev" for duty in used),
        "used_total_vehicles": len(used),
        "cv_trips": sum(
            len(duty.trips) for duty in used if duty.vehicle_type == "cv"
        ),
        "ev_trips": sum(
            len(duty.trips) for duty in used if duty.vehicle_type == "ev"
        ),
        "total_trips": sum(len(duty.trips) for duty in used),
    }


def _fleet_use_by_depot(individual: Any, bundle: Any) -> dict[str, dict[str, int]]:
    rows = {}
    for depot_id, caps in sorted(bundle.fleet_caps_by_depot.items()):
        duties = [
            duty
            for duty in individual.duties
            if duty.home_depot_id == depot_id and duty.trips
        ]
        used_cv = sum(duty.vehicle_type == "cv" for duty in duties)
        used_ev = sum(duty.vehicle_type == "ev" for duty in duties)
        cv_trips = sum(
            len(duty.trips) for duty in duties if duty.vehicle_type == "cv"
        )
        ev_trips = sum(
            len(duty.trips) for duty in duties if duty.vehicle_type == "ev"
        )
        rows[depot_id] = {
            "cv_cap": int(caps["num_cv"]),
            "ev_cap": int(caps["num_ev"]),
            "total_cap": int(caps["total_fleet_cap"]),
            "used_cv": used_cv,
            "used_ev": used_ev,
            "used_total": used_cv + used_ev,
            "cv_trips": cv_trips,
            "ev_trips": ev_trips,
            "total_trips": cv_trips + ev_trips,
            "cv_cap_slack": int(caps["num_cv"]) - used_cv,
            "ev_cap_slack": int(caps["num_ev"]) - used_ev,
            "total_cap_slack": int(caps["total_fleet_cap"])
            - used_cv
            - used_ev,
        }
    return rows


def _point_row(
    *,
    instance_id: str,
    seed: int,
    arm: str,
    pair_group_id: str,
    point_index: int,
    individual: Any,
    evaluation: Any,
) -> dict[str, Any]:
    row = {
        "instance_id": instance_id,
        "seed": int(seed),
        "arm": arm,
        "pair_group_id": pair_group_id,
        "point_index": int(point_index),
        "individual_fingerprint": individual.fingerprint,
        "total_cost_cny": float(evaluation.total_cost),
        "direct_emissions_kg": float(evaluation.breakdown["E_cv_direct"]),
        "indirect_emissions_kg": float(evaluation.breakdown["E_ev_indirect"]),
        "total_emissions_kg": float(evaluation.breakdown["E_total"]),
        "feasible": bool(evaluation.feasible),
    }
    row.update(_fleet_fields(individual))
    for key, value in sorted(evaluation.breakdown.items()):
        row[f"breakdown__{key}"] = value
    return row


def _run_one(
    *,
    repo: Path,
    instance_id: str,
    arm: str,
    seed: int,
    wall_clock_budget_seconds: float,
    objective_mode: str,
    population_mode: str,
    pair_identity: PairIdentity,
    pi0_record: Mapping[str, Any],
    run_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from run_problem_hgs_private_technical import _parameters, _policy
    from setp_solver.algorithms.problem_hgs.evaluation import DutyFullEvaluator
    from setp_solver.algorithms.problem_hgs.kernel_proposals import (
        IndependentKernelDutyRouteProposalEngine,
    )
    from setp_solver.algorithms.problem_hgs.runner import (
        FrozenPopulationIdentity,
        population_sha256,
        run_integrated_problem_hgs,
    )

    bundle, initial, context = _arm_setup(
        repo,
        instance_id,
        arm,
        pi0_record,
    )
    built, initialization_wall_seconds = _prepare_population(
        initial,
        context,
        seed=seed,
        wall_clock_budget_seconds=wall_clock_budget_seconds,
        objective_mode=objective_mode,
        population_mode=population_mode,
    )
    evaluator = DutyFullEvaluator(context)
    policy = _policy(evaluator)
    parameters = _parameters(
        random_seed=seed,
        population_mode=population_mode,
        crossover_mode="fast_only",
        objective_mode=objective_mode,
    )
    route_engine = IndependentKernelDutyRouteProposalEngine(
        context,
        initial,
        random_seed=seed,
        stream_role="main2_main_route",
    )
    population_identity = FrozenPopulationIdentity(
        source_id=f"main2-{instance_id}-{arm}-seed-{seed}",
        value_sha256=population_sha256(built.candidates),
    )
    runtime_identity = replace(
        pair_identity,
        seed=int(parameters.random_seed),
        main_rng_seed=int(seed),
    )
    validate_pairing((pair_identity, runtime_identity))
    clock = _BestClock(float(wall_clock_budget_seconds))
    result = run_integrated_problem_hgs(
        built.candidates,
        evaluator=evaluator,
        charging_policy=policy,
        parameters=parameters,
        initial_population_identity=population_identity,
        stop=clock.stop,
        arm=arm,
        route_engine=route_engine,
        trajectory_sink=lambda _rows: None,
        retain_trajectory=False,
        initial_evaluations=built.evaluations,
        initialization_full_evaluation_count=built.full_evaluation_count,
        initialization_wall_seconds=initialization_wall_seconds,
    )
    selected_individual = result.best
    selected_evaluation = result.best_evaluation
    if result.cost_priority_point is not None:
        selected_individual = result.cost_priority_point.individual
        selected_evaluation = result.cost_priority_point.evaluation
    accounting = result.accounting.to_dict()
    row: dict[str, Any] = {
        "instance_id": instance_id,
        "seed": int(seed),
        "arm": arm,
        "arm_label": ARM_DEFINITIONS[arm].label,
        "arm_role": ARM_DEFINITIONS[arm].role,
        "pair_group_id": pair_identity.pair_group_id,
        "run_status": result.termination_status,
        "objective_mode": objective_mode,
        "wall_clock_budget_seconds": float(wall_clock_budget_seconds),
        "fleet_parameter_class_id": bundle.fleet_parameter_class_id,
        "initial_population_sha256": population_identity.value_sha256,
        "evaluation_context_sha256": evaluator.context_sha256,
        "search_configuration_sha256": result.provenance.search_configuration_sha256,
        "pi0_source_id": pi0_record["source_id"],
        "pi0_value_sha256": pi0_record["value_sha256"],
        "total_cost_cny": float(selected_evaluation.total_cost),
        "direct_emissions_kg": float(
            selected_evaluation.breakdown["E_cv_direct"]
        ),
        "indirect_emissions_kg": float(
            selected_evaluation.breakdown["E_ev_indirect"]
        ),
        "total_emissions_kg": float(selected_evaluation.breakdown["E_total"]),
        "feasible": bool(selected_evaluation.feasible),
        "violation_count": len(selected_evaluation.violations),
        "pareto_point_count": len(result.non_dominated_set),
        "cost_priority_fingerprint": (
            None
            if result.cost_priority_point is None
            else result.cost_priority_point.individual.fingerprint
        ),
        "emissions_priority_fingerprint": (
            None
            if result.emissions_priority_point is None
            else result.emissions_priority_point.individual.fingerprint
        ),
        "completed_generations": int(result.iterations),
        "initialization_wall_seconds": float(
            accounting["initialization_wall_seconds"]
        ),
        "search_wall_seconds": float(accounting["run_wall_seconds"]),
        "total_algorithm_wall_seconds": float(
            accounting["total_algorithm_wall_seconds"]
        ),
        "time_to_best_cost_seconds": clock.time_to_best_seconds,
        "fleet_caps_by_depot_json": json.dumps(
            {key: dict(value) for key, value in bundle.fleet_caps_by_depot.items()},
            ensure_ascii=False,
            sort_keys=True,
        ),
        "error_type": result.termination_error_type,
        "error": result.termination_error,
    }
    row.update(_service_fields(selected_individual, bundle))
    row.update(_fleet_fields(selected_individual))
    row["fleet_use_by_depot_json"] = json.dumps(
        _fleet_use_by_depot(selected_individual, bundle),
        ensure_ascii=False,
        sort_keys=True,
    )
    for key, value in sorted(selected_evaluation.breakdown.items()):
        row[f"breakdown__{key}"] = value

    point_rows = []
    records = list(result.non_dominated_set)
    if not records:
        point_rows.append(
            _point_row(
                instance_id=instance_id,
                seed=seed,
                arm=arm,
                pair_group_id=pair_identity.pair_group_id,
                point_index=0,
                individual=selected_individual,
                evaluation=selected_evaluation,
            )
        )
    else:
        for index, point in enumerate(records):
            point_row = _point_row(
                instance_id=instance_id,
                seed=seed,
                arm=arm,
                pair_group_id=pair_identity.pair_group_id,
                point_index=index,
                individual=point.individual,
                evaluation=point.evaluation,
            )
            point_row.update(_service_fields(point.individual, bundle))
            point_row["fleet_use_by_depot_json"] = json.dumps(
                _fleet_use_by_depot(point.individual, bundle),
                ensure_ascii=False,
                sort_keys=True,
            )
            point_rows.append(point_row)

    run_dir.mkdir(parents=True)
    _write_json(
        run_dir / "result.json",
        {
            "row": row,
            "selected_solution": asdict(selected_individual),
            "selected_evaluation": {
                "breakdown": dict(selected_evaluation.breakdown),
                "feasible": selected_evaluation.feasible,
                "violations": [asdict(item) for item in selected_evaluation.violations],
            },
            "pareto_front": [point.to_dict() for point in records],
            "accounting": accounting,
            "provenance": asdict(result.provenance),
        },
    )
    return row, point_rows


def _failure_row(identity: PairIdentity, error: Exception) -> dict[str, Any]:
    return {
        "instance_id": identity.instance_id,
        "seed": identity.seed,
        "arm": identity.arm,
        "arm_label": ARM_DEFINITIONS[identity.arm].label,
        "arm_role": ARM_DEFINITIONS[identity.arm].role,
        "pair_group_id": identity.pair_group_id,
        "run_status": "FAILED",
        "objective_mode": identity.objective_mode,
        "wall_clock_budget_seconds": identity.wall_clock_budget_seconds,
        "fleet_parameter_class_id": _planned_fleet_parameter_class_id(
            identity.arm
        ),
        "error_type": type(error).__name__,
        "error": str(error),
        "traceback": traceback.format_exc(),
    }


def _ordered_fields(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    preferred = [
        "instance_id",
        "seed",
        "arm",
        "arm_label",
        "arm_role",
        "pair_group_id",
        "run_status",
        "objective_mode",
        "wall_clock_budget_seconds",
        "fleet_parameter_class_id",
        "total_cost_cny",
        "direct_emissions_kg",
        "indirect_emissions_kg",
        "total_emissions_kg",
        "customers_served",
        "customers_total",
        "customer_completion_ratio",
        "demand_served",
        "demand_total",
        "demand_completion_ratio",
        "used_cv_vehicles",
        "used_ev_vehicles",
        "used_total_vehicles",
        "cv_trips",
        "ev_trips",
        "total_trips",
        "fleet_use_by_depot_json",
        "pareto_point_count",
    ]
    available = set().union(*(row.keys() for row in rows)) if rows else set()
    return [*preferred, *sorted(available.difference(preferred))]


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = _ordered_fields(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _successful(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in rows if row.get("total_cost_cny") not in (None, "")]


def render_report(rows: Sequence[Mapping[str, Any]]) -> str:
    successful = _successful(rows)
    arms = [
        arm for arm in ARM_DEFINITIONS if any(row.get("arm") == arm for row in rows)
    ]
    lines = [
        "# MAIN-2 混合车队实验运行报告",
        "",
        "所有算例、种子和实验臂按请求顺序串行运行；同一算例—种子组使用相同随机种子、输入快照、双目标口径和墙钟预算。实验臂自身的车队可行域不同，这是处理因素，不被伪装成相同评价上下文。",
        "",
        "## 各臂 Best / Avg",
        "",
        "| 实验臂 | 完成运行 | Best 成本 | Avg 成本 | Avg 总排放 | Avg 油/电车 | Avg 油/电趟 | Avg 服务客户 | Avg 需求完成度 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in arms:
        arm_rows = [row for row in successful if row["arm"] == arm]
        if not arm_rows:
            lines.append(f"| {arm} | 0 | — | — | — | — | — | — | — |")
            continue
        lines.append(
            "| {arm} | {count} | {best:.6f} | {avg:.6f} | {emissions:.6f} | "
            "{cv:.3f}/{ev:.3f} | {cvt:.3f}/{evt:.3f} | {customers:.3f} | "
            "{demand:.6%} |".format(
                arm=arm,
                count=len(arm_rows),
                best=min(float(row["total_cost_cny"]) for row in arm_rows),
                avg=statistics.mean(float(row["total_cost_cny"]) for row in arm_rows),
                emissions=statistics.mean(
                    float(row["total_emissions_kg"]) for row in arm_rows
                ),
                cv=statistics.mean(float(row["used_cv_vehicles"]) for row in arm_rows),
                ev=statistics.mean(float(row["used_ev_vehicles"]) for row in arm_rows),
                cvt=statistics.mean(float(row["cv_trips"]) for row in arm_rows),
                evt=statistics.mean(float(row["ev_trips"]) for row in arm_rows),
                customers=statistics.mean(
                    float(row["customers_served"]) for row in arm_rows
                ),
                demand=statistics.mean(
                    float(row["demand_completion_ratio"]) for row in arm_rows
                ),
            )
        )
    lines.extend(
        [
            "",
            "## 同种子配对差",
            "",
            "下表只汇总两边都完成的同一算例、同一种子；差值为前者减后者。服务量差同时保留，不能用少服务解释降本或减排。",
            "",
            "| 配对 | 对数 | Avg 成本差 | Avg 总排放差 | Avg 服务客户差 | Avg 需求完成度差 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    by_key = {
        (str(row["instance_id"]), int(row["seed"]), str(row["arm"])): row
        for row in successful
    }
    comparisons = (
        ("endogenous", "fixed25"),
        ("same_total_cap", "fixed25"),
        ("endogenous", "same_total_cap"),
        ("all_ev", "all_cv"),
    )
    for left, right in comparisons:
        if left not in arms or right not in arms:
            continue
        pairs = []
        for instance_id, seed, arm in sorted(by_key):
            if arm != left:
                continue
            right_row = by_key.get((instance_id, seed, right))
            if right_row is not None:
                pairs.append((by_key[(instance_id, seed, left)], right_row))
        if not pairs:
            lines.append(f"| {left} − {right} | 0 | — | — | — | — |")
            continue
        lines.append(
            f"| {left} − {right} | {len(pairs)} | "
            f"{statistics.mean(float(a['total_cost_cny']) - float(b['total_cost_cny']) for a, b in pairs):.6f} | "
            f"{statistics.mean(float(a['total_emissions_kg']) - float(b['total_emissions_kg']) for a, b in pairs):.6f} | "
            f"{statistics.mean(float(a['customers_served']) - float(b['customers_served']) for a, b in pairs):.6f} | "
            f"{statistics.mean(float(a['demand_completion_ratio']) - float(b['demand_completion_ratio']) for a, b in pairs):.6%} |"
        )
    failed = [row for row in rows if row.get("run_status") == "FAILED"]
    lines.extend(["", "## 完整性", ""])
    lines.append(
        f"完成 {len(successful)} 次，失败 {len(failed)} 次。"
        "失败原文保留在 `raw_runs.csv`；非支配点逐点保存在 `pareto_points.csv`。"
    )
    return "\n".join(lines) + "\n"


def _artifact_hashes(output: Path) -> dict[str, str]:
    return {
        str(path.relative_to(output)): _sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--instances", nargs="+", required=True)
    parser.add_argument(
        "--arms",
        nargs="+",
        choices=tuple(ARM_DEFINITIONS),
    )
    parser.add_argument(
        "--fleet-parameters",
        choices=tuple(FLEET_PARAMETER_CLASS_IDS),
    )
    parser.add_argument("--seeds", type=int, nargs="+", required=True)
    parser.add_argument("--wall-clock-seconds", type=float, required=True)
    parser.add_argument(
        "--objective-mode",
        choices=("single_objective", "bi_objective"),
        default="bi_objective",
    )
    parser.add_argument(
        "--population-mode",
        choices=("technical_two_parent", "copied_hgs_defaults"),
        default="copied_hgs_defaults",
    )
    parser.add_argument("--pi0-manifest", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    fleet_parameters_was_explicit = args.fleet_parameters is not None
    if args.fleet_parameters is None:
        args.fleet_parameters = "fixed25"
    if args.arms is None:
        args.arms = [args.fleet_parameters]
    elif fleet_parameters_was_explicit and args.arms != [args.fleet_parameters]:
        parser.error(
            "--fleet-parameters selects its matching direct fleet arm; "
            "omit --arms or pass the same single arm"
        )
    if not 0.0 < args.wall_clock_seconds <= MAX_WALL_CLOCK_SECONDS:
        parser.error(
            f"--wall-clock-seconds must be in (0, {MAX_WALL_CLOCK_SECONDS:g}]"
        )
    for label, values in (
        ("--instances", args.instances),
        ("--arms", args.arms),
        ("--seeds", args.seeds),
    ):
        if len(set(values)) != len(values):
            parser.error(f"{label} cannot contain duplicates")
    if not args.dry_run and args.pi0_manifest is None:
        parser.error("non-dry MAIN-2 requires --pi0-manifest (P28 frozen values)")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    repo = Path(__file__).resolve().parents[2]
    validated = _validate_static_inputs(args, repo)
    if args.dry_run:
        print(
            json.dumps(
                _dry_run_payload(args, repo, validated),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
        )
        return 0

    from run_public_v2_28_clean_ruler import _prepare_independent_imports

    _prepare_independent_imports()
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    output.mkdir(parents=True)
    protected_before = {path: _sha256(repo / path) for path in PROTECTED}
    from run_problem_hgs_private_technical import (
        _effective_population_metadata,
        _parameters,
    )

    pair_groups = []
    rows: list[dict[str, Any]] = []
    pareto_rows: list[dict[str, Any]] = []
    metadata = {
        "status": "RUNNING",
        "experiment_id": "MAIN-2",
        "instances": list(args.instances),
        "arms": list(args.arms),
        "arm_definitions": {
            arm: asdict(ARM_DEFINITIONS[arm]) for arm in args.arms
        },
        "seeds": list(args.seeds),
        "wall_clock_budget_seconds_per_run": args.wall_clock_seconds,
        "budget_semantics": "initial population construction plus search wall clock",
        "objective_mode": args.objective_mode,
        "effective_population": _effective_population_metadata(
            args.population_mode,
            _parameters(
                population_mode=args.population_mode,
                objective_mode=args.objective_mode,
            ).population,
        ),
        "fleet_parameter_class_id": _metadata_fleet_parameter_class_id(args.arms),
        "fleet_parameter_class_ids_by_arm": {
            arm: _planned_fleet_parameter_class_id(arm) for arm in args.arms
        },
        "serial_execution": True,
        "pair_fields": PAIR_FIELDS,
        "input_source_hashes": validated["source_hashes"],
        "input_snapshot_sha256": validated["input_snapshot_sha256"],
        "pi0_manifest": str(args.pi0_manifest.resolve()),
        "pi0_manifest_sha256": _sha256(args.pi0_manifest.resolve()),
        "protected_hashes_before": protected_before,
        "command_argv": list(sys.argv if argv is None else argv),
    }
    _write_json(output / "metadata.json", metadata)
    pi0_records = validated["pi0_records"]
    assert pi0_records is not None
    for instance_id in args.instances:
        for seed in args.seeds:
            identities = _pair_identities(
                args.arms,
                instance_id=instance_id,
                seed=seed,
                wall_clock_budget_seconds=args.wall_clock_seconds,
                objective_mode=args.objective_mode,
                input_snapshot_sha256=validated["input_snapshot_sha256"],
            )
            validate_pairing(identities)
            pair_groups.append([asdict(identity) for identity in identities])
            by_arm = {identity.arm: identity for identity in identities}
            for arm in args.arms:
                run_dir = output / "runs" / instance_id / arm / f"seed_{seed}"
                try:
                    row, points = _run_one(
                        repo=repo,
                        instance_id=instance_id,
                        arm=arm,
                        seed=seed,
                        wall_clock_budget_seconds=args.wall_clock_seconds,
                        objective_mode=args.objective_mode,
                        population_mode=args.population_mode,
                        pair_identity=by_arm[arm],
                        pi0_record=pi0_records[instance_id],
                        run_dir=run_dir,
                    )
                except Exception as error:  # Preserve exact per-run failure.
                    row = _failure_row(by_arm[arm], error)
                    points = []
                    run_dir.mkdir(parents=True, exist_ok=True)
                    _write_json(run_dir / "failure.json", row)
                rows.append(row)
                pareto_rows.extend(points)

    protected_after = {path: _sha256(repo / path) for path in PROTECTED}
    if protected_after != protected_before:
        raise RuntimeError("a protected source file changed during MAIN-2")
    _write_csv(output / "raw_runs.csv", rows)
    _write_csv(output / "pareto_points.csv", pareto_rows)
    (output / "report.md").write_text(render_report(rows), encoding="utf-8")
    metadata.update(
        {
            "status": (
                "COMPLETED_WITH_FAILURES"
                if any(row.get("run_status") == "FAILED" for row in rows)
                else "COMPLETED"
            ),
            "pair_validation": "PASSED",
            "pair_groups": pair_groups,
            "planned_run_count": len(args.instances)
            * len(args.seeds)
            * len(args.arms),
            "recorded_run_count": len(rows),
            "pareto_point_count": len(pareto_rows),
            "protected_hashes_after": protected_after,
        }
    )
    _write_json(output / "metadata.json", metadata)
    _write_json(output / "artifact_hashes.json", _artifact_hashes(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
