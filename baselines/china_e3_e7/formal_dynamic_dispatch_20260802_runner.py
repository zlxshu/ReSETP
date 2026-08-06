#!/usr/bin/env python3
"""XC2 formal dynamic-dispatch experiment for paper Section 5.3.

The runner deliberately separates the immutable preregistration (``prepare``)
from the monitored formal search (``run``).  The carbon-aware and carbon-blind
arms receive the same event, search seed, frozen state, HGS population, and
iteration budget.  The carbon-blind continuation is the preregistered state
carrier so that the next matched decision still starts from one common state.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from dataclasses import asdict, replace
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Iterable, Mapping, Sequence


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROTOTYPE = (
    ROOT
    / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
)
while str(HERE) in sys.path:
    sys.path.remove(str(HERE))
for entry in (ROOT, ROOT / "solver/src", ROOT / "models/src", PROTOTYPE):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import statistics

import numpy as np
from pyvrp._pyvrp import RandomNumberGenerator
from pyvrp._pyvrp import Solution as NativeSolution
from pyvrp.crossover import ordered_crossover, selective_route_exchange
from pyvrp.diversity import broken_pairs_distance
from pyvrp.GeneticAlgorithm import GeneticAlgorithm
from pyvrp.PenaltyManager import PenaltyManager
from pyvrp.Population import Population, PopulationParams
from pyvrp.search import LocalSearch, compute_neighbours
from pyvrp.solve import SolveParams
from pyvrp.stop import MaxIterations

from baselines.algorithm_prototypes.china81_mechanism_hybrid_20260720.pyvrp_adapter import (
    _native_solution_key,
    _project_initial_solution,
    _translate_solution,
    build_pyvrp_problem,
)
from baselines.china_e3_e7.e7_o1_replanning_20260801.policy import (
    build_o1_stream,
)
from baselines.china_e3_e7.e7_trigger_policies_20260801 import run_pilot as pilot
from baselines.china_e3_e7.e7_trigger_policies_20260801.dynamic_adapter import (
    inject_full_fleet_asset_states,
)
from baselines.china_e3_e7.e7_trigger_policies_20260801.trigger_policies import (
    DynamicOrder,
    TriggerBatch,
    dynamic_stream_sha256,
)
from baselines.e7_dynamic import e7_dynamic_continuous_trigger_gate_20260714 as gate
from baselines.e7_dynamic import e7_full_mechanism_probe_20260714 as probe
from baselines.e7_dynamic import e7_formal_dynamic_value_20260714 as dynamic_search
from setp_solver.check import check_solution
from setp_solver.china81 import (
    CHINA81_HORIZON_END_SECOND,
    CHINA81_HORIZON_START_SECOND,
    China81Bundle,
    load_china81_bundle,
)
from setp_solver.china81_completion import complete_china81_route_skeleton
from setp_solver.cost import evaluate
from setp_solver.model_config import ModelConfig, model_config_scope
from setp_solver.search.dynamic_multitrip_schedule import (
    CertificateCut,
    cut_certificate_at_trigger,
    cut_dynamic_certificate_at_trigger,
    prepare_dynamic_multitrip_solution,
    reschedule_dynamic_charging,
    validate_dynamic_multitrip_certificate,
)
from setp_solver.search.multitrip_schedule import (
    MultiTripCertificate,
    prepare_multitrip_solution,
)
from setp_solver.solution import (
    ChargingAction,
    Route,
    Solution,
    physical_vehicle_id,
)


TASK_ID = "XC2"
TERMINAL_STATUS = "XC_DYNAMIC_FORMAL_COMPLETE"
INSTANCE_ID = "cn-prd-100c-02-V2-LOCATIONS"
OUTPUT_DIR = HERE / "formal_dynamic_dispatch_20260802"
FLEET_AUTHORITY = (
    ROOT / "data/ChinaInstances/china81_finite_fleet_authority_v3_20260802"
)
FLEET_EVIDENCE = HERE / "fleet_authority_v3_20260802"
MODEL_CONFIG = ModelConfig(
    strict_multitrip=True,
    depot_charger_capacity_mode="unbounded",
)
POPULATION_SIZE = 120
GENERATION_BATCH_SIZE = 40
MAX_GENERATIONS = 2000
SEEDS = tuple(range(1, 11))
ARMS = ("carbon_aware", "carbon_blind")
STATE_CARRIER_ARM = "carbon_blind"
PER_ORDER = "per_order"
FIXED_30_MINUTES = "fixed_30_minutes"
HYBRID_500KG_OR_30_MINUTES = "hybrid_500kg_or_30_minutes"
POLICIES = (PER_ORDER, FIXED_30_MINUTES, HYBRID_500KG_OR_30_MINUTES)
POLICY_LABELS = {
    PER_ORDER: "continuous_per_order",
    FIXED_30_MINUTES: "periodic_30_minutes",
    HYBRID_500KG_OR_30_MINUTES: "proposed_500kg_or_30_minutes",
}
INTERVAL_SECONDS = 30.0 * 60.0
DEMAND_THRESHOLD_KG = 500.0
SOURCE_FILES = (
    Path(__file__).resolve(),
    ROOT / "solver/src/setp_solver/china81.py",
    ROOT / "solver/src/setp_solver/china81_completion.py",
    ROOT / "solver/src/setp_solver/instance_loader.py",
    ROOT / "solver/src/setp_solver/model_config.py",
    ROOT / "solver/src/setp_solver/prices.py",
    ROOT / "solver/src/setp_solver/charging_curve.py",
    ROOT / "solver/src/setp_solver/cost.py",
    ROOT / "solver/src/setp_solver/check.py",
    ROOT / "solver/src/setp_solver/search/evaluation.py",
    ROOT / "solver/src/setp_solver/search/multitrip_schedule.py",
    ROOT / "solver/src/setp_solver/search/dynamic_multitrip_schedule.py",
    ROOT / "solver/src/setp_solver/solution.py",
    PROTOTYPE / "pyvrp_adapter.py",
    ROOT / "baselines/china_e3_e7/e7_h0_g2_foundation_20260801/stream.py",
    ROOT / "baselines/china_e3_e7/e7_o1_replanning_20260801/policy.py",
    ROOT / "baselines/china_e3_e7/e7_trigger_policies_20260801/dynamic_adapter.py",
    ROOT / "baselines/china_e3_e7/e7_trigger_policies_20260801/trigger_policies.py",
    ROOT / "baselines/china_e3_e7/e7_trigger_policies_20260801/run_pilot.py",
    ROOT / "baselines/e7_dynamic/e7_dynamic_continuous_trigger_gate_20260714.py",
    ROOT / "baselines/e7_dynamic/e7_formal_dynamic_value_20260714.py",
    ROOT / "baselines/e7_dynamic/e7_full_mechanism_probe_20260714.py",
    ROOT / "docs/handoff/paper_restructure_20260802/r2_evidence_inventory/rerun_plan.json",
    ROOT / "docs/handoff/model_change_approval_register_20260718.md",
    FLEET_AUTHORITY / "fleet_caps.csv",
    FLEET_AUTHORITY / "metadata.json",
    FLEET_AUTHORITY / "decision.json",
    FLEET_EVIDENCE / "metadata.json",
    FLEET_EVIDENCE / "decision.json",
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"refusing to write empty CSV {path}")
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fields})
    temporary.replace(path)


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _solution_payload(solution: Solution) -> dict[str, Any]:
    return asdict(solution)


def _solution_sha256(solution: Solution) -> str:
    return _canonical_sha256(_solution_payload(solution))


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _load_bundle() -> China81Bundle:
    bundle = load_china81_bundle(
        ROOT,
        INSTANCE_ID,
        fleet_authority=FLEET_AUTHORITY,
        model_config=MODEL_CONFIG,
    )
    if bundle.instance_id != INSTANCE_ID:
        raise RuntimeError("selected instance id drifted")
    if sum(node.node_type.lower() == "c" for node in bundle.instance.nodes) != 100:
        raise RuntimeError("I100 instance does not contain 100 customers")
    if float(bundle.prices.vehicle_fixed_cost) != 170.0:
        raise RuntimeError("physical-vehicle fixed cost is not c_fix=170")
    if bundle.model_config != MODEL_CONFIG.as_metadata():
        raise RuntimeError("explicit model configuration drifted")
    if Path(bundle.fleet_authority) != Path(
        "data/ChinaInstances/china81_finite_fleet_authority_v3_20260802"
    ):
        raise RuntimeError("fleet authority is not v3")
    return bundle


def _source_hashes(bundle: China81Bundle) -> dict[str, str]:
    paths = set(SOURCE_FILES)
    for relative in bundle.source_paths.values():
        source = ROOT / str(relative)
        if source.is_file():
            paths.add(source)
        elif source.is_dir():
            paths.update(
                path
                for path in source.rglob("*")
                if path.is_file()
                and not path.name.startswith("._")
                and "__pycache__" not in path.parts
            )
    result: dict[str, str] = {}
    for path in sorted(paths):
        if not path.is_file():
            raise FileNotFoundError(f"registered source is absent: {path}")
        result[str(path.relative_to(ROOT))] = _sha256(path)
    return result


def _assert_source_hashes(preregistration: Mapping[str, Any]) -> None:
    for relative, expected in preregistration["source_sha256"].items():
        path = ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"protected source disappeared: {relative}")
        observed = _sha256(path)
        if observed != expected:
            raise RuntimeError(
                f"protected source drifted: {relative}: {observed} != {expected}"
            )


def _format_second(second: float) -> str:
    value = max(0, int(round(float(second))))
    hour, remainder = divmod(value, 3600)
    minute, sec = divmod(remainder, 60)
    return f"{hour:02d}:{minute:02d}:{sec:02d}"


def _build_batches(
    events: Sequence[DynamicOrder], policy: str
) -> tuple[TriggerBatch, ...]:
    ordered = sorted(events, key=lambda item: (item.appearance_second, item.event_id))
    if policy == PER_ORDER:
        return tuple(
            _batch(policy, index, event.appearance_second, "new_information", [event])
            for index, event in enumerate(ordered, start=1)
        )
    if policy == FIXED_30_MINUTES:
        batches: list[TriggerBatch] = []
        pending: list[DynamicOrder] = []
        cursor = 0
        trigger = CHINA81_HORIZON_START_SECOND + INTERVAL_SECONDS
        while trigger <= CHINA81_HORIZON_END_SECOND:
            while cursor < len(ordered) and ordered[cursor].appearance_second <= trigger:
                pending.append(ordered[cursor])
                cursor += 1
            if pending:
                cause = (
                    "window_end"
                    if trigger == CHINA81_HORIZON_END_SECOND
                    else "fixed_interval"
                )
                batches.append(
                    _batch(policy, len(batches) + 1, trigger, cause, pending)
                )
                pending = []
            trigger += INTERVAL_SECONDS
        return tuple(batches)
    if policy != HYBRID_500KG_OR_30_MINUTES:
        raise ValueError(f"unknown policy {policy!r}")

    batches = []
    pending = []
    cursor = 0
    deadline = CHINA81_HORIZON_START_SECOND + INTERVAL_SECONDS
    while cursor < len(ordered):
        appearance = ordered[cursor].appearance_second
        while deadline < appearance:
            if pending:
                batches.append(
                    _batch(
                        policy,
                        len(batches) + 1,
                        deadline,
                        "maximum_wait",
                        pending,
                    )
                )
                pending = []
            deadline = min(deadline + INTERVAL_SECONDS, CHINA81_HORIZON_END_SECOND)
        while cursor < len(ordered) and ordered[cursor].appearance_second == appearance:
            pending.append(ordered[cursor])
            cursor += 1
        if sum(event.demand_kg for event in pending) >= DEMAND_THRESHOLD_KG:
            batches.append(
                _batch(
                    policy,
                    len(batches) + 1,
                    appearance,
                    "demand_threshold",
                    pending,
                )
            )
            pending = []
            deadline = min(
                appearance + INTERVAL_SECONDS, CHINA81_HORIZON_END_SECOND
            )
    if pending:
        trigger = min(deadline, CHINA81_HORIZON_END_SECOND)
        cause = "window_end" if trigger == CHINA81_HORIZON_END_SECOND else "maximum_wait"
        batches.append(_batch(policy, len(batches) + 1, trigger, cause, pending))
    consumed = [event_id for batch in batches for event_id in batch.event_ids]
    if sorted(consumed) != sorted(event.event_id for event in ordered):
        raise RuntimeError("hybrid policy did not consume every H0/G2 event")
    return tuple(batches)


def _batch(
    policy: str,
    index: int,
    trigger: float,
    cause: str,
    events: Sequence[DynamicOrder],
) -> TriggerBatch:
    ordered = sorted(events, key=lambda item: (item.appearance_second, item.event_id))
    return TriggerBatch(
        policy=policy,
        batch_index=index,
        trigger_second=float(trigger),
        cause=cause,
        event_ids=tuple(event.event_id for event in ordered),
        customer_ids=tuple(event.customer_id for event in ordered),
        event_types=tuple("add" for _ in ordered),
        demand_kg=sum(event.demand_kg for event in ordered),
    )


def _blind_profile(
    profile: Sequence[Mapping[str, Any]], cutoff_second: float
) -> list[dict[str, Any]]:
    """Hide only future carbon by city-specific last-observation persistence."""

    latest: dict[str, Mapping[str, Any]] = {}
    for row in sorted(
        profile,
        key=lambda item: (str(item["city"]), float(item["horizon_second_start"])),
    ):
        if float(row["horizon_second_start"]) <= float(cutoff_second) + 1e-9:
            latest[str(row["city"])] = row
    if not latest:
        raise RuntimeError("carbon-blind arm has no observed carbon row")
    result: list[dict[str, Any]] = []
    for source in profile:
        row = dict(source)
        if float(row["horizon_second_start"]) > float(cutoff_second) + 1e-9:
            observed = latest[str(row["city"])]
            row["actual_gco2_per_kwh"] = float(observed["actual_gco2_per_kwh"])
            row["forecast_gco2_per_kwh"] = float(
                observed["forecast_gco2_per_kwh"]
            )
        result.append(row)
    return result


def _profile_for_arm(
    bundle: China81Bundle, arm: str, cutoff_second: float
) -> list[dict[str, Any]]:
    if arm == "carbon_aware":
        return [dict(row) for row in bundle.time_profile]
    if arm == "carbon_blind":
        return _blind_profile(bundle.time_profile, cutoff_second)
    raise ValueError(f"unknown arm {arm!r}")


def _initial_instance_bundle(
    bundle: China81Bundle, stream: Any
) -> tuple[Any, China81Bundle, Solution]:
    withheld = {event.customer_id for event in stream.events}
    initial_instance = replace(
        bundle.instance,
        nodes=[
            replace(node, node_type="inactive", demand=0.0)
            if node.node_id in withheld
            else node
            for node in bundle.instance.nodes
        ],
    )
    owners = {
        customer_id: depot_id
        for customer_id, depot_id in bundle.customer_home_depot.items()
        if customer_id not in withheld
    }
    initial_bundle = replace(
        bundle,
        instance=initial_instance,
        customer_home_depot=owners,
    )
    routes: list[Route] = []
    for depot_id in sorted(bundle.fleet_caps_by_depot):
        groups = pilot._pack_depot(initial_bundle, depot_id)
        routes.extend(
            Route(
                vehicle_id=f"NEUTRAL-{depot_id}-{index:03d}",
                vehicle_type="cv",
                home_depot_id=depot_id,
                node_sequence=[depot_id, *customers, depot_id],
            )
            for index, customers in enumerate(groups, start=1)
        )
    return initial_instance, initial_bundle, Solution(routes=routes)


def _future_bundle(
    bundle: China81Bundle,
    effective_instance: Any,
    committed_customers: set[str],
    profile: list[dict[str, Any]],
) -> China81Bundle:
    kept_indexes = [
        index
        for index, node in enumerate(effective_instance.nodes)
        if node.node_type.lower() != "c" or node.node_id not in committed_customers
    ]
    road_profiles = None
    if effective_instance.road_profiles is not None:
        road_profiles = {
            vehicle_type: replace(
                matrices,
                distance_m=tuple(
                    tuple(matrices.distance_m[row][column] for column in kept_indexes)
                    for row in kept_indexes
                ),
                duration_s=tuple(
                    tuple(matrices.duration_s[row][column] for column in kept_indexes)
                    for row in kept_indexes
                ),
                sum_v2d_m3_s2=tuple(
                    tuple(matrices.sum_v2d_m3_s2[row][column] for column in kept_indexes)
                    for row in kept_indexes
                ),
            )
            for vehicle_type, matrices in effective_instance.road_profiles.items()
        }
    future_instance = replace(
        effective_instance,
        nodes=[effective_instance.nodes[index] for index in kept_indexes],
        distance_matrix=[
            [
                effective_instance.distance_matrix[row][column]
                for column in kept_indexes
            ]
            for row in kept_indexes
        ],
        road_profiles=road_profiles,
    )
    active_ids = {
        node.node_id
        for node in future_instance.nodes
        if node.node_type.lower() == "c"
    }
    return replace(
        bundle,
        instance=future_instance,
        time_profile=profile,
        customer_home_depot={
            customer_id: depot_id
            for customer_id, depot_id in bundle.customer_home_depot.items()
            if customer_id in active_ids
        },
    )


def _hgs_skeletons(
    bundle: China81Bundle,
    warm_start: Solution,
    *,
    seed: int,
) -> tuple[list[Solution], dict[str, Any]]:
    started = time.perf_counter()
    problem = build_pyvrp_problem(bundle, route_proxy_mode="mechanism_ev")
    data = problem.model.data()
    population_params = PopulationParams(
        min_pop_size=POPULATION_SIZE,
        generation_size=GENERATION_BATCH_SIZE,
        num_elite=4,
        num_close=5,
    )
    params = SolveParams(population=population_params)
    rng = RandomNumberGenerator(seed=int(seed))
    local_search = LocalSearch(
        data,
        rng,
        compute_neighbours(data, params.neighbourhood),
    )
    node_operators: list[str] = []
    for operator in params.node_ops:
        if operator.supports(data):
            local_search.add_node_operator(operator(data))
            node_operators.append(operator.__name__)
    route_operators: list[str] = []
    for operator in params.route_ops:
        if operator.supports(data):
            local_search.add_route_operator(operator(data))
            route_operators.append(operator.__name__)
    penalty_manager = PenaltyManager.init_from(data, params.penalty)
    population = Population(broken_pairs_distance, params.population)
    warm_native = _project_initial_solution(warm_start, data, problem)
    initial_solutions = [
        warm_native,
        *[
            NativeSolution.make_random(data, rng)
            for _ in range(POPULATION_SIZE - 1)
        ],
    ]
    crossover = (
        selective_route_exchange if data.num_vehicles > 1 else ordered_crossover
    )
    algorithm = GeneticAlgorithm(
        data,
        penalty_manager,
        rng,
        population,
        local_search,
        crossover,
        initial_solutions,
        params.genetic,
    )
    result = algorithm.run(
        MaxIterations(MAX_GENERATIONS),
        collect_stats=True,
        display=False,
        display_interval=params.display_interval,
    )
    cost_evaluator = penalty_manager.cost_evaluator()
    unique: dict[tuple[Any, ...], Any] = {}
    for native in [warm_native, *list(population), result.best]:
        if native.is_feasible():
            unique.setdefault(_native_solution_key(native), native)
    ranked_native = sorted(unique.values(), key=cost_evaluator.cost)
    selected_native = ranked_native[:POPULATION_SIZE]
    skeletons: list[Solution] = []
    translation_failures: list[str] = []
    for native in selected_native:
        try:
            skeletons.append(_translate_solution(native, problem))
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            translation_failures.append(f"{type(exc).__name__}: {exc}")
    if not skeletons:
        raise RuntimeError("HGS returned no translatable feasible route population")
    elapsed = time.perf_counter() - started
    return skeletons, {
        "engine": "PyVRP-0.12.2-HGS-with-mechanism-route-proxy",
        "search_seed": int(seed),
        "population_size": POPULATION_SIZE,
        "generation_batch_size_internal": GENERATION_BATCH_SIZE,
        "maximum_generations": MAX_GENERATIONS,
        "stop_rule": "MaxIterations(2000)_only",
        "secondary_stop_rule": None,
        "terminal_native_feasible_unique_count": len(ranked_native),
        "terminal_exact_rerank_count": len(skeletons),
        "translation_failure_count": len(translation_failures),
        "translation_failures_first_five": translation_failures[:5],
        "proxy_best_feasible": bool(result.best.is_feasible()),
        "proxy_best_cost": float(result.cost()),
        "node_operators": node_operators,
        "route_operators": route_operators,
        "wall_seconds": elapsed,
    }


def _optimize_static(
    base_bundle: China81Bundle,
    initial_bundle: China81Bundle,
    neutral_start: Solution,
    *,
    arm: str,
    seed: int,
) -> dict[str, Any]:
    profile = _profile_for_arm(
        base_bundle, arm, CHINA81_HORIZON_START_SECOND
    )
    perceived_bundle = replace(initial_bundle, time_profile=profile)
    skeletons, hgs = _hgs_skeletons(perceived_bundle, neutral_start, seed=seed)
    candidates: list[tuple[float, Solution, MultiTripCertificate, dict[str, Any]]] = []
    failures: list[str] = []
    for skeleton in [neutral_start, *skeletons]:
        try:
            completion = complete_china81_route_skeleton(
                skeleton, perceived_bundle
            )
            prepared, certificate = prepare_multitrip_solution(
                completion.solution,
                initial_bundle.instance,
                initial_bundle.prices,
            )
            violations = check_solution(
                prepared, initial_bundle.instance, initial_bundle.prices
            )
            if violations:
                raise ValueError(f"static completion violation: {violations[0]}")
            parts = evaluate(
                prepared,
                initial_bundle.instance,
                profile,
                initial_bundle.prices,
            )
            candidates.append(
                (
                    float(parts["total_cost"]),
                    prepared,
                    certificate,
                    parts,
                )
            )
        except (IndexError, KeyError, RuntimeError, TypeError, ValueError) as exc:
            failures.append(f"{type(exc).__name__}: {exc}")
    if not candidates:
        raise RuntimeError(
            "preoptimization search found no executable completion; "
            + " | ".join(failures[:3])
        )
    objective, solution, certificate, perceived_parts = min(
        candidates,
        key=lambda item: (item[0], _solution_sha256(item[1])),
    )
    actual_parts = evaluate(
        solution,
        initial_bundle.instance,
        base_bundle.time_profile,
        initial_bundle.prices,
    )
    return {
        "solution": solution,
        "certificate": certificate,
        "perceived_objective": objective,
        "perceived_parts": perceived_parts,
        "actual_parts": actual_parts,
        "hgs": {
            **hgs,
            "complete_candidate_count": len(candidates),
            "complete_candidate_failure_count": len(failures),
            "complete_candidate_failures_first_five": failures[:5],
        },
    }


def _optimize_dynamic(
    base_bundle: China81Bundle,
    construction: gate.StageConstruction,
    cut: CertificateCut,
    committed_customers: set[str],
    *,
    arm: str,
    seed: int,
    trigger_second: float,
) -> dict[str, Any]:
    profile = _profile_for_arm(base_bundle, arm, trigger_second)
    problem_bundle = _future_bundle(
        base_bundle,
        construction.effective_instance,
        committed_customers,
        profile,
    )
    skeletons, hgs = _hgs_skeletons(
        problem_bundle,
        construction.solution,
        seed=seed,
    )
    candidates: list[
        tuple[
            float,
            Solution,
            MultiTripCertificate,
            dict[str, Any],
            dict[str, Any],
        ]
    ] = []
    failures: list[str] = []
    for skeleton in [construction.solution, *skeletons]:
        try:
            prepared, certificate = prepare_dynamic_multitrip_solution(
                skeleton,
                construction.effective_instance,
                base_bundle.prices,
                asset_states=cut.asset_states,
                stage_start_second=trigger_second,
                locked_charging_actions=cut.locked_charging_actions,
            )
            prepared, certificate, charge_stats = reschedule_dynamic_charging(
                prepared,
                certificate,
                construction.effective_instance,
                profile,
                base_bundle.prices,
                asset_states=cut.asset_states,
                stage_start_second=trigger_second,
                locked_charging_actions=cut.locked_charging_actions,
                strategy="aware",
                intensity_field="forecast_gco2_per_kwh",
            )
            validate_dynamic_multitrip_certificate(
                prepared,
                certificate,
                construction.effective_instance,
                base_bundle.prices,
                asset_states=cut.asset_states,
                stage_start_second=trigger_second,
                locked_charging_actions=cut.locked_charging_actions,
            )
            parts = evaluate(
                prepared,
                construction.effective_instance,
                profile,
                base_bundle.prices,
            )
            candidates.append(
                (
                    float(parts["total_cost"]),
                    prepared,
                    certificate,
                    parts,
                    charge_stats,
                )
            )
        except (IndexError, KeyError, RuntimeError, TypeError, ValueError) as exc:
            failures.append(f"{type(exc).__name__}: {exc}")
    if not candidates:
        raise SearchNotFound(
            "full HGS population produced no executable continuation; "
            + " | ".join(failures[:3])
        )
    objective, solution, certificate, perceived_parts, charge_stats = min(
        candidates,
        key=lambda item: (item[0], _solution_sha256(item[1])),
    )
    actual_parts = evaluate(
        solution,
        construction.effective_instance,
        base_bundle.time_profile,
        base_bundle.prices,
    )
    return {
        "solution": solution,
        "certificate": certificate,
        "perceived_objective": objective,
        "perceived_parts": perceived_parts,
        "actual_parts": actual_parts,
        "charge_stats": charge_stats,
        "hgs": {
            **hgs,
            "complete_candidate_count": len(candidates),
            "complete_candidate_failure_count": len(failures),
            "complete_candidate_failures_first_five": failures[:5],
        },
    }


class SearchNotFound(RuntimeError):
    """The frozen search exhausted its budget without a feasible continuation."""


def _customer_ids(routes: Iterable[Route], instance: Any) -> set[str]:
    lookup = {node.node_id: node for node in instance.nodes}
    return {
        node_id
        for route in routes
        for node_id in route.node_sequence
        if node_id in lookup and lookup[node_id].node_type.lower() == "c"
    }


def _hard_violations(
    construction: gate.StageConstruction,
    cut: CertificateCut,
    trigger_second: float,
) -> list[dict[str, Any]]:
    instance = construction.effective_instance
    pending = _customer_ids(construction.solution.routes, instance)
    lookup = {node.node_id: node for node in instance.nodes}
    violations: list[dict[str, Any]] = []
    for customer_id in sorted(pending):
        node = lookup[customer_id]
        if float(node.demand) <= 0.0:
            violations.append(
                {
                    "constraint": "POSITIVE_DEMAND",
                    "customer_id": customer_id,
                    "observed": float(node.demand),
                    "limit": ">0",
                }
            )
            continue
        eligible = []
        for state in cut.asset_states.values():
            capacity = float(
                instance.vehicle_profile(state.vehicle_type).payload_capacity_kg
            )
            if float(node.demand) > capacity + 1e-9:
                continue
            _, travel, _ = instance.arc_metrics(
                state.home_depot_id,
                customer_id,
                state.vehicle_type,
                fallback_speed_mps=float(1.0),
            )
            earliest_arrival = max(
                float(trigger_second), float(state.available_second)
            ) + float(travel)
            eligible.append((earliest_arrival, state.physical_vehicle_id))
        if not eligible:
            violations.append(
                {
                    "constraint": "FLEET_CAPACITY_AUTHORITY",
                    "customer_id": customer_id,
                    "observed_demand_kg": float(node.demand),
                    "criterion": "no registered CV/EV asset has sufficient payload",
                }
            )
        elif min(item[0] for item in eligible) > float(node.due_time) + 1e-9:
            earliest, vehicle_id = min(eligible)
            violations.append(
                {
                    "constraint": "HARD_TIME_WINDOW_NECESSARY_CONDITION",
                    "customer_id": customer_id,
                    "earliest_direct_arrival_second": earliest,
                    "due_second": float(node.due_time),
                    "best_asset": vehicle_id,
                }
            )
    return violations


def _route_edges(solution: Solution, instance: Any) -> set[tuple[str, str]]:
    lookup = {node.node_id: node for node in instance.nodes}
    result: set[tuple[str, str]] = set()
    for route in solution.routes:
        sequence = [
            node_id
            for node_id in route.node_sequence
            if node_id in lookup
            and lookup[node_id].node_type.lower() in {"c", "d"}
        ]
        result.update(zip(sequence, sequence[1:]))
    return result


def _customer_type_map(solution: Solution, instance: Any) -> dict[str, str]:
    lookup = {node.node_id: node for node in instance.nodes}
    return {
        node_id: route.vehicle_type.lower()
        for route in solution.routes
        for node_id in route.node_sequence
        if node_id in lookup and lookup[node_id].node_type.lower() == "c"
    }


def _charging_signature(action: ChargingAction) -> tuple[Any, ...]:
    return (
        physical_vehicle_id(action.vehicle_id),
        action.station_id,
        round(float(action.energy_kwh), 6),
        round(float(action.charge_start_second), 3),
        int(action.charge_day_offset),
    )


def _change_counts(
    before: Solution, after: Solution, instance: Any
) -> dict[str, int]:
    before_edges = _route_edges(before, instance)
    after_edges = _route_edges(after, instance)
    route_changes = len(before_edges.symmetric_difference(after_edges))
    before_types = _customer_type_map(before, instance)
    after_types = _customer_type_map(after, instance)
    type_changes = sum(
        before_types.get(customer_id) != after_types.get(customer_id)
        for customer_id in set(before_types) | set(after_types)
    )
    before_actions = {_charging_signature(action) for action in before.charging_actions}
    after_actions = {_charging_signature(action) for action in after.charging_actions}
    charge_changes = len(before_actions.symmetric_difference(after_actions))
    return {
        "route_arc_change_count": route_changes,
        "vehicle_type_customer_change_count": type_changes,
        "charging_action_change_count": charge_changes,
        "actual_adjustment": int(bool(route_changes or type_changes or charge_changes)),
    }


def _physical_counts(solution: Solution) -> dict[str, int]:
    typed = {
        physical_vehicle_id(route.vehicle_id): route.vehicle_type.lower()
        for route in solution.routes
    }
    return {
        "vehicle_count": len(typed),
        "used_cv": sum(value == "cv" for value in typed.values()),
        "used_ev": sum(value == "ev" for value in typed.values()),
    }


def _state_payload(cut: CertificateCut, instance: Any) -> dict[str, Any]:
    positions = {}
    capacities = {}
    for asset_id, state in sorted(cut.asset_states.items()):
        positions[asset_id] = {
            "position": (
                state.home_depot_id
                if float(state.available_second) <= float(cut.trigger_second) + 1e-9
                else "in_progress_or_locked_charging"
            ),
            "home_depot_id": state.home_depot_id,
            "next_legal_release_second": float(state.available_second),
            "remaining_battery_kwh": float(state.remaining_battery_kwh),
        }
        capacities[asset_id] = float(
            instance.vehicle_profile(state.vehicle_type).payload_capacity_kg
        )
    return {
        "state_sha256": _canonical_sha256(
            {key: asdict(value) for key, value in sorted(cut.asset_states.items())}
        ),
        "vehicle_positions": positions,
        "next_dispatch_remaining_capacity_kg": capacities,
        "available_cv": sum(
            state.vehicle_type.lower() == "cv" for state in cut.asset_states.values()
        ),
        "available_ev": sum(
            state.vehicle_type.lower() == "ev" for state in cut.asset_states.values()
        ),
    }


def _remaining_charge_windows(
    solution: Solution,
    certificate: MultiTripCertificate,
    cut: CertificateCut,
    trigger_second: float,
) -> dict[str, float | int]:
    trip_by_route = {trip.route_id: trip for trip in certificate.trips}
    windows: list[float] = []
    for action in solution.charging_actions:
        trip = trip_by_route.get(action.vehicle_id)
        if trip is None or trip.physical_vehicle_id not in cut.asset_states:
            continue
        state = cut.asset_states[trip.physical_vehicle_id]
        duration = float(action.occupancy_minutes) * 60.0
        earliest = max(float(trigger_second), float(state.available_second))
        latest = float(trip.departure_second) - duration
        windows.append(max(0.0, latest - earliest) / 60.0)
    return {
        "event_to_horizon_minutes": max(
            0.0, (CHINA81_HORIZON_END_SECOND - float(trigger_second)) / 60.0
        ),
        "eligible_charging_window_count": len(windows),
        "remaining_charging_window_total_minutes": sum(windows),
        "remaining_charging_window_mean_minutes": (
            statistics.fmean(windows) if windows else 0.0
        ),
        "remaining_charging_window_min_minutes": min(windows) if windows else 0.0,
    }


def _save_solution(
    path: Path,
    *,
    solution: Solution,
    certificate: MultiTripCertificate,
    payload: Mapping[str, Any],
    before_open_solution: Solution | None = None,
) -> str:
    solution_hash = _solution_sha256(solution)
    body = {
        **payload,
        "solution_sha256": solution_hash,
        "solution": _solution_payload(solution),
        "certificate_sha256": _canonical_sha256(certificate.as_dict()),
        "certificate": certificate.as_dict(),
    }
    if before_open_solution is not None:
        body["before_open_solution"] = _solution_payload(before_open_solution)
        body["before_open_solution_sha256"] = _solution_sha256(before_open_solution)
    _write_json(path, body)
    return solution_hash


def _merge(
    committed_routes: Mapping[str, Route],
    committed_actions: Mapping[tuple[Any, ...], ChargingAction],
    future: Solution,
    route_history: Mapping[str, Route],
) -> Solution:
    return probe._merge_execution_plan(
        dict(committed_routes),
        dict(committed_actions),
        future,
        dict(route_history),
    )


def _run_scenario(task: tuple[str, int, str]) -> str:
    policy, stream_seed, output_text = task
    out = Path(output_text)
    if out.exists():
        raise RuntimeError(f"refusing to overwrite scenario directory {out}")
    out.mkdir(parents=True)
    started = time.perf_counter()
    with model_config_scope(MODEL_CONFIG):
        bundle = _load_bundle()
        pilot.INSTANCE_ID = INSTANCE_ID
        pilot._FULL_INSTANCE = bundle.instance
        stream = build_o1_stream(
            bundle.instance,
            instance_id=INSTANCE_ID,
            stream_seed=int(stream_seed),
        )
        if len(stream.events) != 20:
            raise RuntimeError("H0/G2 I100 stream does not contain 20 additions")
        batches = _build_batches(stream.events, policy)
        events_by_id = {event.event_id: event for event in stream.events}
        initial_instance, initial_bundle, neutral_start = _initial_instance_bundle(
            bundle, stream
        )
        preoptimizations: dict[str, dict[str, Any]] = {}
        solution_hashes: dict[str, list[str]] = {arm: [] for arm in ARMS}
        for arm in ARMS:
            result = _optimize_static(
                bundle,
                initial_bundle,
                neutral_start,
                arm=arm,
                seed=10_000 * int(stream_seed),
            )
            solution_path = out / "solutions" / arm / "preoptimization.json"
            solution_hashes[arm].append(
                _save_solution(
                    solution_path,
                    solution=result["solution"],
                    certificate=result["certificate"],
                    payload={
                        "phase": "preoptimization",
                        "arm": arm,
                        "policy": policy,
                        "stream_seed": int(stream_seed),
                        "hgs": result["hgs"],
                        "perceived_objective": result["perceived_objective"],
                        "perceived_parts": result["perceived_parts"],
                        "actual_parts": result["actual_parts"],
                    },
                )
            )
            preoptimizations[arm] = result

        current_plan: Solution = preoptimizations[STATE_CARRIER_ARM]["solution"]
        current_certificate: MultiTripCertificate = preoptimizations[
            STATE_CARRIER_ARM
        ]["certificate"]
        current_instance = initial_instance
        inherited_states = None
        inherited_locked: tuple[ChargingAction, ...] = ()
        previous_trigger: float | None = None
        committed_routes: dict[str, Route] = {}
        committed_actions: dict[tuple[Any, ...], ChargingAction] = {}
        committed_customers: set[str] = set()
        route_history = {route.vehicle_id: route for route in current_plan.routes}
        accepted_event_ids: set[str] = set()
        stage_rows: list[dict[str, Any]] = []
        event_rows: list[dict[str, Any]] = []
        paired_rows: list[dict[str, Any]] = []
        arm_adjustments = Counter({arm: 0 for arm in ARMS})
        arm_route_changes = Counter({arm: 0 for arm in ARMS})
        arm_type_changes = Counter({arm: 0 for arm in ARMS})
        arm_charge_changes = Counter({arm: 0 for arm in ARMS})
        latest_complete: dict[str, dict[str, Any]] = {}
        terminal_reason = ""
        terminal_classification = "PASS"
        attempted_batches = 0

        for offset, batch in enumerate(batches):
            attempted_batches += 1
            if previous_trigger is None:
                cut = cut_certificate_at_trigger(
                    current_plan,
                    current_certificate,
                    current_instance,
                    bundle.prices,
                    trigger_second=batch.trigger_second,
                )
                cut = replace(
                    cut,
                    asset_states=inject_full_fleet_asset_states(
                        cut.asset_states,
                        bundle.fleet_caps_by_depot,
                        available_second=batch.trigger_second,
                        unused_ev_battery_kwh=float(
                            bundle.prices.initial_ev_battery_kwh
                        ),
                    ),
                )
            else:
                cut = cut_dynamic_certificate_at_trigger(
                    current_plan,
                    current_certificate,
                    current_instance,
                    bundle.prices,
                    inherited_asset_states=inherited_states,
                    previous_stage_start_second=previous_trigger,
                    trigger_second=batch.trigger_second,
                    inherited_locked_charging_actions=inherited_locked,
                )

            locked_ids = (*cut.completed_route_ids, *cut.in_progress_route_ids)
            for route in gate._cut_routes(current_plan, locked_ids):
                committed_routes.setdefault(route.vehicle_id, route)
                committed_customers.update(
                    dynamic_search.p2.route_customers(route, current_instance)
                )
            for action in cut.locked_charging_actions:
                committed_actions.setdefault(probe.base.action_key(action), action)
            open_routes = gate._cut_routes(current_plan, cut.editable_route_ids)
            before_open = Solution(
                routes=[replace(route, node_sequence=list(route.node_sequence)) for route in open_routes],
                charging_actions=[
                    action
                    for action in current_plan.charging_actions
                    if action.vehicle_id in cut.editable_route_ids
                ],
            )
            batch_events = [events_by_id[event_id] for event_id in batch.event_ids]
            construction = gate.build_open_stage(
                open_routes,
                current_instance,
                [event.as_solver_event() for event in batch_events],
                batch.trigger_second,
                committed_customers,
                bundle.customer_home_depot,
                bundle.prices,
                stage_index=batch.batch_index,
                isolate_changed_customers=True,
            )
            hard = _hard_violations(construction, cut, batch.trigger_second)
            state = _state_payload(cut, construction.effective_instance)
            pending_ids = sorted(
                _customer_ids(
                    construction.solution.routes, construction.effective_instance
                )
            )
            node_lookup = {
                node.node_id: node for node in construction.effective_instance.nodes
            }
            minimum_slack = min(
                (
                    float(node_lookup[customer_id].due_time)
                    - float(batch.trigger_second)
                    for customer_id in pending_ids
                ),
                default=0.0,
            )
            if hard:
                terminal_classification = "HARD_INFEASIBLE"
                terminal_reason = json.dumps(
                    hard, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                for arm in ARMS:
                    stage_rows.append(
                        {
                            "policy": policy,
                            "stream_seed": int(stream_seed),
                            "arm": arm,
                            "stage": batch.batch_index,
                            "status": "HARD_INFEASIBLE",
                            "trigger_second": batch.trigger_second,
                            "trigger_time": _format_second(batch.trigger_second),
                            "trigger_cause": batch.cause,
                            "event_ids": "|".join(batch.event_ids),
                            "hard_violation_basis": terminal_reason,
                            "search_executed": False,
                            "state_sha256": state["state_sha256"],
                        }
                    )
                break

            arm_results: dict[str, dict[str, Any]] = {}
            arm_failures: dict[str, str] = {}
            for arm in ARMS:
                search_seed = (
                    1_000_000 * int(stream_seed)
                    + 10_000 * POLICIES.index(policy)
                    + 100 * batch.batch_index
                )
                try:
                    arm_results[arm] = _optimize_dynamic(
                        bundle,
                        construction,
                        cut,
                        committed_customers,
                        arm=arm,
                        seed=search_seed,
                        trigger_second=batch.trigger_second,
                    )
                except SearchNotFound as exc:
                    arm_failures[arm] = str(exc)

            if arm_failures:
                terminal_classification = "SEARCH_NOT_FOUND"
                terminal_reason = json.dumps(
                    arm_failures,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                for arm in ARMS:
                    status = (
                        "SEARCH_NOT_FOUND"
                        if arm in arm_failures
                        else "PASS_COUNTERFACTUAL_NOT_CARRIED_AFTER_PAIR_FAILURE"
                    )
                    stage_rows.append(
                        {
                            "policy": policy,
                            "stream_seed": int(stream_seed),
                            "arm": arm,
                            "stage": batch.batch_index,
                            "status": status,
                            "trigger_second": batch.trigger_second,
                            "trigger_time": _format_second(batch.trigger_second),
                            "trigger_cause": batch.cause,
                            "event_ids": "|".join(batch.event_ids),
                            "failure_reason": arm_failures.get(arm, ""),
                            "hard_violation_basis": "",
                            "search_executed": True,
                            "state_sha256": state["state_sha256"],
                        }
                    )
                break

            new_latest: dict[str, dict[str, Any]] = {}
            for arm in ARMS:
                result = arm_results[arm]
                full_solution = _merge(
                    committed_routes,
                    committed_actions,
                    result["solution"],
                    route_history,
                )
                actual_parts = evaluate(
                    full_solution,
                    construction.effective_instance,
                    bundle.time_profile,
                    bundle.prices,
                )
                changes = _change_counts(
                    before_open,
                    result["solution"],
                    construction.effective_instance,
                )
                counts = _physical_counts(full_solution)
                windows = _remaining_charge_windows(
                    result["solution"],
                    result["certificate"],
                    cut,
                    batch.trigger_second,
                )
                arm_adjustments[arm] += changes["actual_adjustment"]
                arm_route_changes[arm] += changes["route_arc_change_count"]
                arm_type_changes[arm] += changes[
                    "vehicle_type_customer_change_count"
                ]
                arm_charge_changes[arm] += changes[
                    "charging_action_change_count"
                ]
                previous_physical = {
                    physical_vehicle_id(route.vehicle_id) for route in current_plan.routes
                }
                new_physical = {
                    physical_vehicle_id(route.vehicle_id)
                    for route in result["solution"].routes
                } - previous_physical
                solution_path = (
                    out
                    / "solutions"
                    / arm
                    / f"stage_{batch.batch_index:03d}.json"
                )
                solution_hash = _save_solution(
                    solution_path,
                    solution=full_solution,
                    certificate=result["certificate"],
                    before_open_solution=before_open,
                    payload={
                        "phase": "dynamic_reoptimization",
                        "certificate_scope": "after_future_solution_only; the saved solution field is the complete merged day witness",
                        "after_future_solution": _solution_payload(result["solution"]),
                        "after_future_solution_sha256": _solution_sha256(
                            result["solution"]
                        ),
                        "arm": arm,
                        "state_carrier_arm": STATE_CARRIER_ARM,
                        "policy": policy,
                        "stream_seed": int(stream_seed),
                        "stage": batch.batch_index,
                        "event_ids": list(batch.event_ids),
                        "trigger_second": batch.trigger_second,
                        "trigger_cause": batch.cause,
                        "frozen_state_sha256": state["state_sha256"],
                        "perceived_objective": result["perceived_objective"],
                        "perceived_parts": result["perceived_parts"],
                        "actual_parts": actual_parts,
                        "change_counts": changes,
                        "physical_counts": counts,
                        "remaining_charging_windows": windows,
                        "charge_reschedule_stats": result["charge_stats"],
                        "hgs": result["hgs"],
                    },
                )
                solution_hashes[arm].append(solution_hash)
                stage_row = {
                    "policy": policy,
                    "policy_label": POLICY_LABELS[policy],
                    "stream_seed": int(stream_seed),
                    "arm": arm,
                    "stage": batch.batch_index,
                    "status": "PASS_COMPLETE_OPTIMIZATION",
                    "trigger_second": batch.trigger_second,
                    "trigger_time": _format_second(batch.trigger_second),
                    "trigger_cause": batch.cause,
                    "event_ids": "|".join(batch.event_ids),
                    "event_count": len(batch.event_ids),
                    "batch_demand_kg": batch.demand_kg,
                    "pending_service_count": len(pending_ids),
                    "pending_service_ids": "|".join(pending_ids),
                    "minimum_latest_service_slack_minutes": minimum_slack / 60.0,
                    "state_sha256": state["state_sha256"],
                    "available_cv": state["available_cv"],
                    "available_ev": state["available_ev"],
                    **counts,
                    **changes,
                    **windows,
                    "new_vehicle": bool(new_physical),
                    "new_vehicle_ids": "|".join(sorted(new_physical)),
                    "distance_m": float(actual_parts["distance_total"]),
                    "total_cost_cny": float(actual_parts["total_cost"]),
                    "total_emissions_kg": float(actual_parts["E_total"]),
                    "solution_sha256": solution_hash,
                    "hgs_population": POPULATION_SIZE,
                    "hgs_max_generations": MAX_GENERATIONS,
                    "hard_violation_basis": "",
                    "search_not_found_reason": "",
                }
                stage_rows.append(stage_row)
                for event in batch_events:
                    event_rows.append(
                        {
                            **stage_row,
                            "event_id": event.event_id,
                            "customer_id": event.customer_id,
                            "arrival_second": event.appearance_second,
                            "arrival_time": _format_second(event.appearance_second),
                            "event_type": "add",
                            "event_demand_kg": event.demand_kg,
                            "event_ready_second": event.ready_second,
                            "event_due_second": event.due_second,
                            "vehicle_positions": state["vehicle_positions"],
                            "next_dispatch_remaining_capacity_kg": state[
                                "next_dispatch_remaining_capacity_kg"
                            ],
                        }
                    )
                new_latest[arm] = {
                    "full_solution": full_solution,
                    "future_solution": result["solution"],
                    "certificate": result["certificate"],
                    "actual_parts": actual_parts,
                    "counts": counts,
                    "windows": windows,
                    "changes": changes,
                    "solution_sha256": solution_hash,
                }

            aware = new_latest["carbon_aware"]
            blind = new_latest["carbon_blind"]
            paired_rows.append(
                {
                    "policy": policy,
                    "stream_seed": int(stream_seed),
                    "stage": batch.batch_index,
                    "event_ids": "|".join(batch.event_ids),
                    "trigger_second": batch.trigger_second,
                    "state_sha256_aware": state["state_sha256"],
                    "state_sha256_blind": state["state_sha256"],
                    "same_frozen_state": True,
                    "aware_minus_blind_cost_cny": float(
                        aware["actual_parts"]["total_cost"]
                    )
                    - float(blind["actual_parts"]["total_cost"]),
                    "aware_minus_blind_emissions_kg": float(
                        aware["actual_parts"]["E_total"]
                    )
                    - float(blind["actual_parts"]["E_total"]),
                    "aware_minus_blind_distance_m": float(
                        aware["actual_parts"]["distance_total"]
                    )
                    - float(blind["actual_parts"]["distance_total"]),
                    "aware_minus_blind_vehicle_count": aware["counts"][
                        "vehicle_count"
                    ]
                    - blind["counts"]["vehicle_count"],
                    "aware_minus_blind_used_cv": aware["counts"]["used_cv"]
                    - blind["counts"]["used_cv"],
                    "aware_minus_blind_used_ev": aware["counts"]["used_ev"]
                    - blind["counts"]["used_ev"],
                    "aware_minus_blind_route_arc_changes": aware["changes"][
                        "route_arc_change_count"
                    ]
                    - blind["changes"]["route_arc_change_count"],
                    "aware_minus_blind_vehicle_type_customer_changes": aware[
                        "changes"
                    ]["vehicle_type_customer_change_count"]
                    - blind["changes"]["vehicle_type_customer_change_count"],
                    "aware_minus_blind_charging_action_changes": aware["changes"][
                        "charging_action_change_count"
                    ]
                    - blind["changes"]["charging_action_change_count"],
                    "aware_minus_blind_remaining_charging_window_minutes": aware[
                        "windows"
                    ]["remaining_charging_window_total_minutes"]
                    - blind["windows"]["remaining_charging_window_total_minutes"],
                    "aware_solution_sha256": aware["solution_sha256"],
                    "blind_solution_sha256": blind["solution_sha256"],
                }
            )
            accepted_event_ids.update(batch.event_ids)
            latest_complete = new_latest
            carrier = arm_results[STATE_CARRIER_ARM]
            inherited_states = cut.asset_states
            inherited_locked = cut.locked_charging_actions
            previous_trigger = batch.trigger_second
            current_plan = carrier["solution"]
            current_certificate = carrier["certificate"]
            current_instance = construction.effective_instance
            route_history.update(
                {route.vehicle_id: route for route in current_plan.routes}
            )

        if attempted_batches < len(batches):
            for later in batches[attempted_batches:]:
                for arm in ARMS:
                    stage_rows.append(
                        {
                            "policy": policy,
                            "stream_seed": int(stream_seed),
                            "arm": arm,
                            "stage": later.batch_index,
                            "status": "NOT_ATTEMPTED_AFTER_RETAINED_FAILURE",
                            "trigger_second": later.trigger_second,
                            "trigger_time": _format_second(later.trigger_second),
                            "trigger_cause": later.cause,
                            "event_ids": "|".join(later.event_ids),
                            "failure_reason": terminal_reason,
                        }
                    )

        seen_event_rows = {
            (str(row["event_id"]), str(row["arm"])) for row in event_rows
        }
        stage_status = {
            (int(row["stage"]), str(row["arm"])): row
            for row in stage_rows
            if row.get("stage") is not None
        }
        for batch in batches:
            for event_id in batch.event_ids:
                event = events_by_id[event_id]
                for arm in ARMS:
                    if (event_id, arm) in seen_event_rows:
                        continue
                    status_row = stage_status.get((batch.batch_index, arm), {})
                    event_rows.append(
                        {
                            "policy": policy,
                            "policy_label": POLICY_LABELS[policy],
                            "stream_seed": int(stream_seed),
                            "arm": arm,
                            "stage": batch.batch_index,
                            "status": status_row.get(
                                "status", "NOT_ATTEMPTED_AFTER_RETAINED_FAILURE"
                            ),
                            "arrival_second": event.appearance_second,
                            "arrival_time": _format_second(event.appearance_second),
                            "event_id": event.event_id,
                            "customer_id": event.customer_id,
                            "event_type": "add",
                            "event_demand_kg": event.demand_kg,
                            "trigger_second": batch.trigger_second,
                            "trigger_time": _format_second(batch.trigger_second),
                            "trigger_cause": batch.cause,
                            "pending_service_ids": "STATE_NOT_AVAILABLE",
                            "vehicle_positions": "STATE_NOT_AVAILABLE",
                            "next_dispatch_remaining_capacity_kg": "STATE_NOT_AVAILABLE",
                            "hard_violation_basis": status_row.get(
                                "hard_violation_basis", ""
                            ),
                            "search_not_found_reason": status_row.get(
                                "failure_reason", ""
                            ),
                        }
                    )

        arm_summaries: list[dict[str, Any]] = []
        for arm in ARMS:
            if arm in latest_complete:
                final = latest_complete[arm]
                parts = final["actual_parts"]
                counts = final["counts"]
                final_hash = final["solution_sha256"]
                cost = float(parts["total_cost"])
                distance = float(parts["distance_total"])
                emissions = float(parts["E_total"])
            else:
                counts = {"vehicle_count": None, "used_cv": None, "used_ev": None}
                final_hash = solution_hashes[arm][-1]
                cost = distance = emissions = None
            arm_summaries.append(
                {
                    "policy": policy,
                    "policy_label": POLICY_LABELS[policy],
                    "stream_seed": int(stream_seed),
                    "arm": arm,
                    "status": terminal_classification,
                    "generated_dynamic_orders": len(stream.events),
                    "served_dynamic_orders": len(accepted_event_ids),
                    "response_rate_pct": 100.0
                    * len(accepted_event_ids)
                    / len(stream.events),
                    "scheduled_trigger_count": len(batches),
                    "attempted_trigger_count": attempted_batches,
                    "actual_adjustment_count": int(arm_adjustments[arm]),
                    "route_arc_change_count": int(arm_route_changes[arm]),
                    "vehicle_type_customer_change_count": int(
                        arm_type_changes[arm]
                    ),
                    "charging_action_change_count": int(arm_charge_changes[arm]),
                    "vehicle_count": counts["vehicle_count"],
                    "used_cv": counts["used_cv"],
                    "used_ev": counts["used_ev"],
                    "distance_m": distance,
                    "total_cost_cny": cost,
                    "total_emissions_kg": emissions,
                    "final_solution_sha256": final_hash,
                    "all_solution_sha256": solution_hashes[arm],
                    "failure_classification": terminal_classification,
                    "failure_reason": terminal_reason,
                }
            )

        scenario = {
            "schema": "resetp.xc2.scenario.v1",
            "task_id": TASK_ID,
            "instance_id": INSTANCE_ID,
            "policy": policy,
            "stream_seed": int(stream_seed),
            "stream_sha256": dynamic_stream_sha256(stream),
            "event_count": len(stream.events),
            "scheduled_trigger_count": len(batches),
            "attempted_trigger_count": attempted_batches,
            "status": terminal_classification,
            "failure_reason": terminal_reason,
            "state_carrier_arm": STATE_CARRIER_ARM,
            "arm_summaries": arm_summaries,
            "stage_rows": stage_rows,
            "event_rows": event_rows,
            "paired_rows": paired_rows,
            "wall_seconds": time.perf_counter() - started,
        }
        _write_json(out / "scenario_result.json", scenario)
        _write_json(
            out / "done.json",
            {
                "status": "SCENARIO_COMPLETE_WITH_ALL_OUTCOMES_RETAINED",
                "policy": policy,
                "stream_seed": int(stream_seed),
                "scenario_status": terminal_classification,
                "completed_at_utc": _utc_now(),
            },
        )
    return str(out / "scenario_result.json")


def _preregister(output: Path) -> None:
    if output.exists():
        raise RuntimeError(f"refusing to overwrite existing output directory {output}")
    output.mkdir(parents=True)
    bundle = _load_bundle()
    stream = build_o1_stream(
        bundle.instance,
        instance_id=INSTANCE_ID,
        stream_seed=1,
    )
    representative_batches = _build_batches(
        stream.events, HYBRID_500KG_OR_30_MINUTES
    )
    representative_batch = representative_batches[0]
    representative_event = next(
        event
        for event in stream.events
        if event.event_id == representative_batch.event_ids[0]
    )
    source_hashes = _source_hashes(bundle)
    preregistration = {
        "schema": "resetp.xc2.preregistration.v1",
        "task_id": TASK_ID,
        "registered_at_utc": _utc_now(),
        "git_head": _git_head(),
        "instance_id": INSTANCE_ID,
        "instance_customer_count": 100,
        "h0_g2_dynamic_order_count": 20,
        "service_horizon": "06:00--22:00",
        "policies": list(POLICIES),
        "policy_definitions": {
            PER_ORDER: "reoptimize at every independent order arrival",
            FIXED_30_MINUTES: "reoptimize on the 30-minute grid when orders are pending",
            HYBRID_500KG_OR_30_MINUTES: "reoptimize when pending demand reaches 500 kg or the oldest pending batch reaches 30 minutes",
        },
        "stream_seeds": list(SEEDS),
        "paired_scenario_count": len(POLICIES) * len(SEEDS),
        "arms": list(ARMS),
        "full_optimization_in_both_arms": True,
        "paired_contract": {
            "same_event_stream": True,
            "same_stream_seed": True,
            "same_frozen_state_at_each_trigger": True,
            "same_population": POPULATION_SIZE,
            "same_maximum_generations": MAX_GENERATIONS,
            "only_treatment_difference": "future carbon signal visibility",
            "state_carrier_arm": STATE_CARRIER_ARM,
            "state_carrier_reason": "a common preregistered control trajectory is required to preserve the accepted matched-state estimand at every trigger; the aware arm remains a full optimized counterfactual continuation and is never zero-search rescored",
        },
        "carbon_blind_rule": "city-specific last-observed carbon intensity is persisted strictly after each decision time; tariff, demand, road, fleet, and all other information remain identical",
        "optimizer": {
            "engine": "PyVRP 0.12.2 HGS with ReSETP mechanism route proxy and complete terminal-population reranking",
            "population_size": POPULATION_SIZE,
            "generation_batch_size_internal": GENERATION_BATCH_SIZE,
            "maximum_generations": MAX_GENERATIONS,
            "preoptimization_stop": "MaxIterations(2000)_only",
            "dynamic_reoptimization_stop": "MaxIterations(2000)_only",
            "independent_secondary_stop_rule": None,
        },
        "model_config": MODEL_CONFIG.as_metadata(),
        "multitrip_enabled": True,
        "fixed_cost_cny": 170.0,
        "fixed_cost_basis": "unique physical_vehicle_id, not route/trip count",
        "fixed_cost_approval_id": "MC-W1-F2-DEPOT-CONCURRENCY-01",
        "depot_charging_concurrency": "unbounded",
        "public_station_concurrency": "finite_instance",
        "fleet_authority_version": "v3_20260802",
        "fleet_authority_path": str(FLEET_AUTHORITY.relative_to(ROOT)),
        "fleet_authority_evidence_path": str(FLEET_EVIDENCE.relative_to(ROOT)),
        "fleet_authority_bundle_formal_search_allowed_field": bool(
            bundle.formal_search_allowed
        ),
        "formal_search_authority": "explicit user XC2 direct-execution instruction dated 2026-08-02; the v3 bundle field records its zero-search construction provenance and is not silently upgraded",
        "information_wait_cost_cny": None,
        "monetized_waiting_cost_used": False,
        "actual_adjustment_definition": "one trigger counts as an actual adjustment iff any route arc, customer vehicle-type assignment, or charging action differs from the frozen carrier continuation",
        "hard_infeasible_definition": "only an explicit violation of positive demand, registered payload authority, or the necessary direct-arrival hard-time-window bound is labelled HARD_INFEASIBLE",
        "search_not_found_definition": "if no explicit hard contradiction is proved but the complete frozen HGS population yields no executable continuation, label SEARCH_NOT_FOUND rather than infeasible",
        "falsification_condition": (
            "The Section 5.3 claim is not supported if the registered 30 paired "
            "scenarios show neither a change in post-event remaining charging "
            "windows / available-versus-used CV-EV capacity nor a corresponding "
            "route, vehicle-type, or charging response; it is also not supported "
            "if hard infeasibility or search-not-found outcomes prevent the three "
            "registered strategies from being compared. Zero, adverse, mixed, "
            "or unstable aware-minus-blind differences are retained and do not "
            "permit seed replacement or parameter rescue."
        ),
        "representative_event": {
            "selection_timing": "before_any_formal_search",
            "selection_rule": "first event in the first registered hybrid-policy batch of seed 1",
            "policy": HYBRID_500KG_OR_30_MINUTES,
            "stream_seed": 1,
            "arm": "carbon_aware",
            "batch_index": representative_batch.batch_index,
            "trigger_second": representative_batch.trigger_second,
            "trigger_time": _format_second(representative_batch.trigger_second),
            "trigger_cause": representative_batch.cause,
            "event_id": representative_event.event_id,
            "customer_id": representative_event.customer_id,
            "arrival_second": representative_event.appearance_second,
            "arrival_time": _format_second(representative_event.appearance_second),
            "demand_kg": representative_event.demand_kg,
        },
        "source_sha256": source_hashes,
        "artifact_hash_exclusions": [
            "artifact_hashes.json",
            "._*",
            "**/__pycache__/**",
        ],
        "no_overwrite": True,
        "no_seed_replacement": True,
        "no_parameter_rescue": True,
    }
    _write_json(output / "preregistration.json", preregistration)
    prereg_hash = _sha256(output / "preregistration.json")
    _write_json(
        output / "metadata.json",
        {
            "schema": "resetp.xc2.metadata.v1",
            "task_id": TASK_ID,
            "status": "XC_DYNAMIC_FORMAL_PREREGISTERED",
            "preregistration_sha256": prereg_hash,
            "preregistration": preregistration,
            "created_at_utc": _utc_now(),
        },
    )


def _aggregate(output: Path, scenario_paths: Sequence[Path], wall_seconds: float) -> None:
    scenarios = [_read_json(path) for path in sorted(scenario_paths)]
    if len(scenarios) != 30:
        raise RuntimeError(f"expected 30 paired scenarios, found {len(scenarios)}")
    arm_rows = [row for item in scenarios for row in item["arm_summaries"]]
    stage_rows = [row for item in scenarios for row in item["stage_rows"]]
    event_rows = [row for item in scenarios for row in item["event_rows"]]
    paired_rows = [row for item in scenarios for row in item["paired_rows"]]
    _write_csv(output / "raw_runs.csv", arm_rows)
    _write_csv(output / "stage_runs.csv", stage_rows)
    _write_csv(output / "event_state_table.csv", event_rows)
    _write_csv(output / "paired_differences.csv", paired_rows or [{"status": "NO_PASSING_PAIRS"}])

    comparison: list[dict[str, Any]] = []
    for policy in POLICIES:
        for arm in ARMS:
            group = [
                row for row in arm_rows if row["policy"] == policy and row["arm"] == arm
            ]
            numeric = [row for row in group if row["total_cost_cny"] is not None]
            comparison.append(
                {
                    "policy": policy,
                    "policy_label": POLICY_LABELS[policy],
                    "arm": arm,
                    "scenario_count": len(group),
                    "complete_metric_count": len(numeric),
                    "mean_vehicle_count": _mean(numeric, "vehicle_count"),
                    "mean_actual_adjustment_count": _mean(
                        group, "actual_adjustment_count"
                    ),
                    "mean_route_arc_change_count": _mean(
                        group, "route_arc_change_count"
                    ),
                    "mean_vehicle_type_customer_change_count": _mean(
                        group, "vehicle_type_customer_change_count"
                    ),
                    "mean_charging_action_change_count": _mean(
                        group, "charging_action_change_count"
                    ),
                    "mean_distance_km": (
                        _mean(numeric, "distance_m") / 1000.0 if numeric else None
                    ),
                    "mean_total_cost_cny": _mean(numeric, "total_cost_cny"),
                    "mean_total_emissions_kg": _mean(
                        numeric, "total_emissions_kg"
                    ),
                    "mean_response_rate_pct": _mean(group, "response_rate_pct"),
                    "mean_served_dynamic_orders": _mean(
                        group, "served_dynamic_orders"
                    ),
                    "mean_used_cv": _mean(numeric, "used_cv"),
                    "mean_used_ev": _mean(numeric, "used_ev"),
                    "hard_infeasible_count": sum(
                        row["failure_classification"] == "HARD_INFEASIBLE"
                        for row in group
                    ),
                    "search_not_found_count": sum(
                        row["failure_classification"] == "SEARCH_NOT_FOUND"
                        for row in group
                    ),
                }
            )
    _write_csv(output / "strategy_comparison.csv", comparison)
    figure_status = _plot_representative(output)
    preregistration = _read_json(output / "preregistration.json")
    prereg_hash = _sha256(output / "preregistration.json")
    same_state = bool(paired_rows) and all(
        row.get("same_frozen_state") is True for row in paired_rows
    )
    statuses = Counter(item["status"] for item in scenarios)
    decision = {
        "schema": "resetp.xc2.decision.v1",
        "task_id": TASK_ID,
        "status": TERMINAL_STATUS,
        "formal_result": True,
        "paired_scenario_count": len(scenarios),
        "arm_run_count": len(arm_rows),
        "all_registered_scenarios_retained": True,
        "scenario_status_counts": dict(sorted(statuses.items())),
        "hard_infeasible_scenarios_retained": statuses.get("HARD_INFEASIBLE", 0),
        "search_not_found_scenarios_retained": statuses.get("SEARCH_NOT_FOUND", 0),
        "same_frozen_state_for_every_completed_pair": same_state,
        "preregistration_unchanged": prereg_hash
        == _read_json(output / "metadata.json")["preregistration_sha256"],
        "falsification_condition_changed_after_run": False,
        "paper_winner_selected": False,
        "strategy_ranked_by_mean_cost": False,
        "monetized_waiting_cost_used": False,
        "seed_replacement": False,
        "parameter_rescue": False,
        "representative_event_selected_post_hoc": False,
        "representative_figure_status": figure_status,
        "claim_support_assessment": _claim_assessment(stage_rows, paired_rows),
    }
    _write_json(output / "decision.json", decision)
    metadata = {
        "schema": "resetp.xc2.metadata.v1",
        "task_id": TASK_ID,
        "status": TERMINAL_STATUS,
        "completed_at_utc": _utc_now(),
        "wall_seconds": wall_seconds,
        "preregistration_sha256": prereg_hash,
        "preregistration": preregistration,
        "instance_id": INSTANCE_ID,
        "solution_count": len(
            [
                path
                for path in (output / "scenarios").rglob("*.json")
                if "solutions" in path.parts
            ]
        ),
        "scenario_result_sha256": {
            str(path.relative_to(output)): _sha256(path)
            for path in scenario_paths
        },
        "decision_summary": decision,
    }
    _write_json(output / "metadata.json", metadata)
    (output / "report.md").write_text(
        _report(preregistration, decision, comparison, event_rows, paired_rows),
        encoding="utf-8",
    )
    _write_json(
        output / "status.json",
        {
            "status": TERMINAL_STATUS,
            "completed_scenarios": 30,
            "total_scenarios": 30,
            "updated_at_utc": _utc_now(),
        },
    )
    artifacts = {
        str(path.relative_to(output)): _sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
        and path.name != "done.json"
    }
    _write_json(
        output / "artifact_hashes.json",
        {
            "schema": "resetp.xc2.artifact-hashes.v1",
            "algorithm": "sha256",
            "excluded": ["artifact_hashes.json", "done.json", "._*", "**/__pycache__/**"],
            "artifacts": artifacts,
        },
    )
    _write_json(
        output / "done.json",
        {
            "status": TERMINAL_STATUS,
            "completed_at_utc": _utc_now(),
            "decision_sha256": _sha256(output / "decision.json"),
            "artifact_hashes_sha256": _sha256(output / "artifact_hashes.json"),
            "scenario_count": 30,
        },
    )


def _mean(rows: Sequence[Mapping[str, Any]], field: str) -> float | None:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    return statistics.fmean(values) if values else None


def _claim_assessment(
    stage_rows: Sequence[Mapping[str, Any]], paired_rows: Sequence[Mapping[str, Any]]
) -> str:
    passed = [row for row in stage_rows if row.get("status") == "PASS_COMPLETE_OPTIMIZATION"]
    if not passed or not paired_rows:
        return "NOT_SUPPORTED_COMPARISON_NOT_AVAILABLE"
    window_varies = len(
        {
            round(float(row.get("remaining_charging_window_total_minutes", 0.0)), 6)
            for row in passed
        }
    ) > 1
    capacity_response = any(
        int(row.get("route_arc_change_count", 0))
        or int(row.get("vehicle_type_customer_change_count", 0))
        or int(row.get("charging_action_change_count", 0))
        for row in passed
    )
    if window_varies and capacity_response:
        return "SUPPORTED_AS_REGISTERED_MECHANISM_OBSERVATION_NO_WINNER_CLAIM"
    return "NOT_SUPPORTED_BY_REGISTERED_FALSIFICATION_CONDITION"


def _solution_from_payload(payload: Mapping[str, Any]) -> Solution:
    return Solution(
        routes=[Route(**row) for row in payload.get("routes", [])],
        charging_actions=[ChargingAction(**row) for row in payload.get("charging_actions", [])],
        cross_site_services=[],
    )


def _plot_representative(output: Path) -> str:
    prereg = _read_json(output / "preregistration.json")
    representative = prereg["representative_event"]
    scenario_dir = (
        output
        / "scenarios"
        / f"{representative['policy']}__seed{int(representative['stream_seed']):02d}"
    )
    path = (
        scenario_dir
        / "solutions"
        / representative["arm"]
        / f"stage_{int(representative['batch_index']):03d}.json"
    )
    if not path.is_file():
        return "REPRESENTATIVE_STAGE_NOT_AVAILABLE_RETAINED"
    payload = _read_json(path)
    before = _solution_from_payload(payload["before_open_solution"])
    after = _solution_from_payload(
        payload.get("after_future_solution", payload["solution"])
    )
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        return f"PLOT_DEPENDENCY_UNAVAILABLE:{exc}"
    bundle = _load_bundle()
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    event_id = representative["customer_id"]
    all_xy = np.array(
        [(float(node.x), float(node.y)) for node in nodes.values()], dtype=float
    )
    xmin, ymin = np.min(all_xy, axis=0)
    xmax, ymax = np.max(all_xy, axis=0)
    padx = max(1.0, (xmax - xmin) * 0.05)
    pady = max(1.0, (ymax - ymin) * 0.05)
    fig, axes = plt.subplots(1, 2, figsize=(13, 6), constrained_layout=True)
    for axis, solution, title in zip(
        axes,
        (before, after),
        ("(a) Before registered trigger", "(b) After full reoptimization"),
        strict=True,
    ):
        customers = [node for node in nodes.values() if node.node_type.lower() == "c"]
        depots = [node for node in nodes.values() if node.node_type.lower() == "d"]
        axis.scatter(
            [node.x for node in customers],
            [node.y for node in customers],
            s=9,
            c="#b8b8b8",
            alpha=0.55,
            zorder=1,
        )
        axis.scatter(
            [node.x for node in depots],
            [node.y for node in depots],
            s=80,
            c="#111111",
            marker="s",
            label="Depot",
            zorder=4,
        )
        colors = plt.cm.tab20(np.linspace(0, 1, max(1, len(solution.routes))))
        for index, route in enumerate(solution.routes):
            points = [nodes[node_id] for node_id in route.node_sequence if node_id in nodes]
            if len(points) < 2:
                continue
            axis.plot(
                [node.x for node in points],
                [node.y for node in points],
                color=colors[index],
                linewidth=1.2,
                linestyle="-" if route.vehicle_type.lower() == "ev" else "--",
                alpha=0.85,
                zorder=2,
            )
        if event_id in nodes:
            event = nodes[event_id]
            axis.scatter(
                [event.x],
                [event.y],
                s=180,
                c="#d62728",
                marker="*",
                edgecolors="white",
                linewidths=0.8,
                label="Preregistered event",
                zorder=5,
            )
        axis.set_xlim(xmin - padx, xmax + padx)
        axis.set_ylim(ymin - pady, ymax + pady)
        axis.set_aspect("equal", adjustable="box")
        axis.set_title(title)
        axis.set_xlabel("x")
        axis.set_ylabel("y")
        axis.grid(alpha=0.15)
    axes[0].legend(loc="best", fontsize=8)
    axes[1].legend(loc="best", fontsize=8)
    fig.suptitle(
        f"Preregistered event {representative['event_id']} at {representative['trigger_time']}"
    )
    fig.savefig(output / "representative_route_adjustment.png", dpi=240)
    plt.close(fig)
    return "PASS_PREREGISTERED_ROUTE_FIGURE"


def _report(
    prereg: Mapping[str, Any],
    decision: Mapping[str, Any],
    comparison: Sequence[Mapping[str, Any]],
    event_rows: Sequence[Mapping[str, Any]],
    paired_rows: Sequence[Mapping[str, Any]],
) -> str:
    representative = prereg["representative_event"]
    representative_rows = [
        row
        for row in event_rows
        if row.get("policy") == representative["policy"]
        and int(row.get("stream_seed", -1)) == int(representative["stream_seed"])
        and row.get("event_id") == representative["event_id"]
        and row.get("arm") == representative["arm"]
        and row.get("status") == "PASS_COMPLETE_OPTIMIZATION"
    ]
    lines = [
        "# XC2 动态发车时机正式实验（论文 5.3）",
        "",
        f"终态：`{decision['status']}`。30 个策略—种子配对场景全部进入冻结执行清单；所有硬不可行、搜索未找到和不利差值均保留。",
        "",
        "## 预注册与口径",
        "",
        f"实例为 `{INSTANCE_ID}`，每个 H0/G2 种子含 20 张独立新订单，服务日为 06:00--22:00。三策略为逐单立即、固定 30 分钟、累计 500 kg 或最多 30 分钟；实际调整次数是结果，不强制为 3。预优化和每次重优化均使用 HGS 种群 120、最大 2000 代，且没有第二套停止规则。",
        "",
        "碳感知与碳盲两臂在每个触发点共享事件、种子、冻结状态和预算；碳盲臂仅把决策时点之后的城市碳强度按最后已知值延续，其他输入不变。为使下一个触发点仍能共享状态，预注册以碳盲臂作为共同状态承载轨迹；碳感知臂每次仍保存完整搜索与完整续行解，配对差是同状态反事实差，不是零搜索重打分。",
        "",
        "固定成本按实体车辆编号计 170 元，多趟开启，车场充电并发不设上限，公共站并发仍按实例，车队上限来自 authority v3。未引入信息等待的货币成本。",
        "",
        "预注册反证条件：" + str(prereg["falsification_condition"]),
        "",
        "## 事件／状态表（预注册代表事件）",
        "",
        "| 事件 | 到达 | 类型/需求 | 触发 | 待服务 | 可用CV/EV | 实际CV/EV | 最晚服务余量(min) | 剩余充电窗总计(min) | 新增车辆 | 状态 |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---|---|",
    ]
    if representative_rows:
        row = representative_rows[0]
        lines.append(
            f"| {row['event_id']} | {row['arrival_time']} | add/{float(row['event_demand_kg']):.1f} kg | {row['trigger_time']} ({row['trigger_cause']}) | {int(row['pending_service_count'])} | {int(row['available_cv'])}/{int(row['available_ev'])} | {int(row['used_cv'])}/{int(row['used_ev'])} | {float(row['minimum_latest_service_slack_minutes']):.2f} | {float(row['remaining_charging_window_total_minutes']):.2f} | {row['new_vehicle']} | {row['status']} |"
        )
    else:
        lines.append(
            f"| {representative['event_id']} | {representative['arrival_time']} | add/{float(representative['demand_kg']):.1f} kg | {representative['trigger_time']} | NA | NA | NA | NA | NA | NA | REPRESENTATIVE_STAGE_NOT_AVAILABLE |"
        )
    lines.extend(
        [
            "",
            "判断：同一种子下三种策略面对完全相同的 20 个外生事件，但因触发时刻不同，其内生车辆状态不强制相同；每一策略—种子内的碳感知／碳盲两臂则共享同一冻结状态。`HARD_INFEASIBLE` 只用于已证明违反硬容量或硬时间窗必要条件的行，`SEARCH_NOT_FOUND` 只表示冻结的完整搜索未找到可执行续行，两者未混写。",
            "",
            "全量逐事件状态（车辆位置、下一趟剩余容量、待服务集合、窗口、运力和改变计数）在 `event_state_table.csv`；逐触发搜索状态在 `stage_runs.csv`。",
            "",
            "## 代表路线调整图",
            "",
            f"代表事件在搜索前固定为 `{representative['event_id']}`（策略 `{representative['policy']}`、seed {representative['stream_seed']}、第 {representative['batch_index']} 批、碳感知臂）。图为同坐标双面板：`representative_route_adjustment.png`；虚线为 CV 路线，实线为 EV 路线，红星为预注册事件。图状态：`{decision['representative_figure_status']}`。",
            "",
            "## 策略比较表",
            "",
            "下表只并列描述，不按平均成本给策略排名，也不挑正文赢家。",
            "",
            "| 策略 | 臂 | 完整指标场景 | 车辆数 | 实际调整次数 | 距离(km) | 总成本(元) | 排放(kg) | 响应率(%) / 服务量 | 路线/车型/充电改变 |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in comparison:
        lines.append(
            f"| {row['policy_label']} | {row['arm']} | {row['complete_metric_count']}/{row['scenario_count']} | {_fmt(row['mean_vehicle_count'])} | {_fmt(row['mean_actual_adjustment_count'])} | {_fmt(row['mean_distance_km'])} | {_fmt(row['mean_total_cost_cny'])} | {_fmt(row['mean_total_emissions_kg'])} | {_fmt(row['mean_response_rate_pct'])} / {_fmt(row['mean_served_dynamic_orders'])} | {_fmt(row['mean_route_arc_change_count'])}/{_fmt(row['mean_vehicle_type_customer_change_count'])}/{_fmt(row['mean_charging_action_change_count'])} |"
        )
    lines.extend(
        [
            "",
            "碳感知减碳是否伴随成本、距离、车型或充电改变，逐触发配对差保存在 `paired_differences.csv`。策略表不把信息等待分钟货币化。",
            "",
            "## 主张检验",
            "",
            f"按预注册反证条件的机械判定为 `{decision['claim_support_assessment']}`。该标签只回答本节登记主张是否被这些场景支持，不把构造实例升级为普遍规律，也不从平均成本选赢家。",
            "",
            "## 新歧义的保守取舍与边界",
            "",
            "三策略必须在不同触发时刻演化，因此不能同时要求‘三策略的内生车辆状态也相同’；本实验保留相同外生事件流，并只在同一策略—种子内严格匹配两碳臂的冻结状态。为满足这一点，碳盲臂承载共同历史，碳感知臂是每个决策点的完整反事实续行。故配对差识别的是同状态下未来碳信息的决策价值，不应写成两条各自滚动执行的全日政策差。",
            "",
            "PyVRP 的种群参数将 120 解释为每次生存者选择后的最小种群；内部每 40 个后代执行一次生存者选择。40 是引擎的代内批量参数，不是额外停止规则；唯一停止条件仍为 2000 次 HGS 迭代。终端种群最多取 120 个完整候选进入 ReSETP 物理机制重排。",
            "",
            "## 记录完整性",
            "",
            "`preregistration.json` 在开跑前原子写入且跑后未改；`metadata.json` 锁定源码与输入 SHA-256、git 提交、模型开关、authority、实例和代表事件。每个场景的两臂均保存预优化及逐触发完整解；各文件含 `solution_sha256`。`artifact_hashes.json` 排除 AppleDouble、`__pycache__`、自身与终态哨兵。",
        ]
    )
    return "\n".join(lines) + "\n"


def _fmt(value: Any) -> str:
    if value is None:
        return "NA"
    return f"{float(value):.3f}"


def _run(output: Path, workers: int) -> None:
    if not output.is_dir():
        raise RuntimeError("run requires an existing prepare-created output directory")
    if (output / "done.json").exists():
        raise RuntimeError("formal output already has a terminal marker")
    preregistration = _read_json(output / "preregistration.json")
    if _sha256(output / "preregistration.json") != _read_json(
        output / "metadata.json"
    )["preregistration_sha256"]:
        raise RuntimeError("preregistration changed before formal start")
    _assert_source_hashes(preregistration)
    scenarios_root = output / "scenarios"
    if scenarios_root.exists():
        raise RuntimeError("refusing pre-existing scenario directory")
    scenarios_root.mkdir()
    tasks = [
        (
            policy,
            seed,
            str(scenarios_root / f"{policy}__seed{seed:02d}"),
        )
        for policy in POLICIES
        for seed in SEEDS
    ]
    started = time.perf_counter()
    completed: list[Path] = []
    failures: list[dict[str, Any]] = []
    _write_json(
        output / "status.json",
        {
            "status": "XC_DYNAMIC_FORMAL_RUNNING",
            "completed_scenarios": 0,
            "total_scenarios": len(tasks),
            "updated_at_utc": _utc_now(),
        },
    )
    with ProcessPoolExecutor(max_workers=int(workers)) as executor:
        future_map = {
            executor.submit(_run_scenario, task): (task[0], task[1]) for task in tasks
        }
        for future in as_completed(future_map):
            policy, seed = future_map[future]
            try:
                completed.append(Path(future.result()))
            except Exception as exc:
                failures.append(
                    {
                        "policy": policy,
                        "stream_seed": seed,
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                    }
                )
            _write_json(
                output / "status.json",
                {
                    "status": "XC_DYNAMIC_FORMAL_RUNNING",
                    "completed_scenarios": len(completed),
                    "runtime_failures": failures,
                    "total_scenarios": len(tasks),
                    "updated_at_utc": _utc_now(),
                },
            )
    if failures:
        _write_json(
            output / "runtime_failures.json",
            {
                "status": "HALT_XC_DYNAMIC_RUNTIME_FAILURES_RETAINED",
                "failures": failures,
                "completed_scenarios": len(completed),
                "total_scenarios": len(tasks),
            },
        )
        _write_json(
            output / "done.json",
            {
                "status": "HALT_XC_DYNAMIC_RUNTIME_FAILURES_RETAINED",
                "completed_scenarios": len(completed),
                "runtime_failure_count": len(failures),
                "completed_at_utc": _utc_now(),
            },
        )
        raise RuntimeError(f"{len(failures)} scenario workers failed; retained")
    _aggregate(output, completed, time.perf_counter() - started)


def _preflight() -> None:
    """Cheap structural preflight; it does not create a formal result."""

    with model_config_scope(MODEL_CONFIG):
        bundle = _load_bundle()
        for seed in SEEDS:
            stream = build_o1_stream(
                bundle.instance,
                instance_id=INSTANCE_ID,
                stream_seed=seed,
            )
            if len(stream.events) != 20:
                raise RuntimeError(f"seed {seed} does not have 20 H0/G2 events")
            for policy in POLICIES:
                batches = _build_batches(stream.events, policy)
                if not batches:
                    raise RuntimeError(f"seed {seed} policy {policy} has no batch")
                consumed = [event_id for batch in batches for event_id in batch.event_ids]
                if len(consumed) != 20 or len(set(consumed)) != 20:
                    raise RuntimeError(
                        f"seed {seed} policy {policy} event ledger does not close"
                    )
        initial_instance, initial_bundle, neutral = _initial_instance_bundle(
            bundle,
            build_o1_stream(
                bundle.instance, instance_id=INSTANCE_ID, stream_seed=1
            ),
        )
        completion = complete_china81_route_skeleton(neutral, initial_bundle)
        prepared, _ = prepare_multitrip_solution(
            completion.solution, initial_instance, bundle.prices
        )
        if check_solution(prepared, initial_instance, bundle.prices):
            raise RuntimeError("neutral preflight incumbent is infeasible")
    print("PASS_XC2_STRUCTURAL_PREFLIGHT")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "preflight", "run"))
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--workers", type=int, default=6)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.command == "preflight":
        _preflight()
    elif args.command == "prepare":
        _preregister(args.output.resolve())
    else:
        if not 1 <= int(args.workers) <= 8:
            raise ValueError("workers must be between 1 and 8")
        _run(args.output.resolve(), int(args.workers))


if __name__ == "__main__":
    main()
