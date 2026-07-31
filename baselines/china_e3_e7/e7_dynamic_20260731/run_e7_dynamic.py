#!/usr/bin/env python3
"""Run the preregistered China81 E7 dynamic-demand experiment.

This file is an adapter around the already audited strict dynamic execution
framework.  It does not modify the frozen solver, route-pool, or epochal-HGS
search semantics.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from dataclasses import asdict, replace
from datetime import UTC, datetime
import hashlib
import importlib.util
import json
import math
import multiprocessing
import os
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import time
from types import ModuleType
from typing import Any, Mapping, Sequence


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for candidate in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from baselines.e7_dynamic import e7_full_mechanism_probe_20260714 as probe
from setp_solver.check import check_solution
from setp_solver.instance_loader import Instance, Node, RoadProfileMatrices
from setp_solver.search.bundle import SearchBundle
from setp_solver.search.dynamic import DynamicEvent, RollingParameters
from setp_solver.search.multitrip_schedule import (
    prepare_multitrip_solution,
    validate_multitrip_certificate,
)
from setp_solver.solution import Solution, physical_vehicle_id


TASK_ID = "E7-DYNAMIC-20260731"
ARMS = (
    "STATIC_FIXED_RECOURSE",
    "FULL_ROLLING",
    "NO_COOPERATION",
    "CARBON_BLIND",
)
SCALES = ("50c", "100c", "150c")
INSTANCE_BY_SCALE = {
    "50c": "cn-prd-50c-01-V2-LOCATIONS",
    "100c": "cn-prd-100c-02-V2-LOCATIONS",
    "150c": "cn-prd-150c-01-V2-LOCATIONS",
}
EVENT_ROOT = (
    ROOT
    / "baselines/china_e3_e7/mechanism_foundation_20260730/inputs/e7_events"
)
E3_ROOT = ROOT / "baselines/china_e3_e7/e3_zone_joint_20260731"
FOUNDATION_150 = (
    ROOT
    / "baselines/china_e3_e7/mechanism_foundation_20260730/inputs/e6"
    / "cn-prd-150c-01-V2-LOCATIONS__mismatch00"
)
PYTHON = ROOT / "build/python_envs/pyvrp-hgs-0.12.2/bin/python"
REQUIRED_THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}
PROTECTED = {
    ROOT / "solver/src/setp_solver/cost.py":
        "2717b4b4de39bb4c2a9a1bda602f4420cb3e3b1e87faa83678dfa64f88fc80be",
    ROOT / "solver/src/setp_solver/check.py":
        "9c81e254e05591667c8225965bb9d0ba4e8bbfc53eb0f8c61ffdb4325a1403a8",
    ROOT / "solver/src/setp_solver/search/evaluation.py":
        "c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3",
    ROOT / "solver/src/setp_solver/profit.py":
        "216c4f16f2e26f1c2840fa272adbf1e3ccb056c3de9403dd15b71fa5edfef1dc",
    ROOT
    / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
    / "route_pool_sp.py":
        "976ef21d4952b3c488300de9a8d3e351411305d26f1e2601ca17c15185d462c1",
    ROOT
    / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
    / "epochal_hgs.py":
        "655fa347b52a3e8ac20c5da6213c84b09ac90f96c1513ca95554753aad3f8a91",
}
SOURCE_FILES = (
    Path(__file__).resolve(),
    Path(probe.__file__).resolve(),
    Path(probe.base.__file__).resolve(),
    Path(probe.base.gate.__file__).resolve(),
    ROOT / "solver/src/setp_solver/search/dynamic.py",
    ROOT / "solver/src/setp_solver/search/dynamic_multitrip_schedule.py",
    ROOT / "solver/src/setp_solver/search/multitrip_schedule.py",
    *PROTECTED.keys(),
)
TOL = 1.0e-6


_E3: ModuleType | None = None
_BASE_CHINA_BUNDLE: Any = None
_BASE_INSTANCE: Instance | None = None
_ALIAS_BY_NODE_ID: dict[str, str] = {}
_CURRENT_SCALE = ""
_CURRENT_ALGORITHM_SEED = 0
_CURRENT_STREAM_SEED = 0
_TRACE_MODE = False
_LAST_SEARCH_TRACES: list[dict[str, Any]] = []
_ORIGINAL_CONTROLLED_STAGE = probe._controlled_stage
_ORIGINAL_SEARCH_STAGE = probe.base.search_stage
_ORIGINAL_TIMING_VARIANT = probe._timing_variant_for_strategy
_ORIGINAL_INSTANCE_AFTER_EVENTS = probe.base.gate._instance_after_events


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def is_real_artifact(path: Path) -> bool:
    if not path.is_file():
        return False
    relative_parts = path.relative_to(HERE).parts
    return (
        not path.name.startswith("._")
        and "__pycache__" not in relative_parts
        and ".pytest_cache" not in relative_parts
    )


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def atomic_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row}) if rows else ["status"]
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def append_progress(payload: Mapping[str, Any]) -> None:
    path = HERE / "progress.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {"at_utc": now_iso(), **dict(payload)},
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )
        handle.flush()


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def e3_module() -> ModuleType:
    global _E3
    if _E3 is None:
        runner = load_module(
            "_e7_current_e3_runner",
            E3_ROOT / "run_e3_zone_joint.py",
        )
        _E3 = runner.load_e3()
    return _E3


def verify_thread_environment() -> dict[str, str]:
    observed = {key: os.environ.get(key, "") for key in REQUIRED_THREAD_ENV}
    if observed != REQUIRED_THREAD_ENV:
        raise RuntimeError(f"HALT_THREAD_ENVIRONMENT:{observed}")
    return observed


def verify_protected() -> dict[str, str]:
    observed = {relative(path): sha256(path) for path in PROTECTED}
    expected = {relative(path): digest for path, digest in PROTECTED.items()}
    if observed != expected:
        raise RuntimeError(
            "HALT_PROTECTED_HASH_DRIFT:"
            + json.dumps(
                {
                    key: {"expected": expected[key], "observed": observed[key]}
                    for key in expected
                    if expected[key] != observed[key]
                },
                sort_keys=True,
            )
        )
    return observed


def source_hashes() -> dict[str, str]:
    return {
        relative(path): sha256(path)
        for path in sorted(set(SOURCE_FILES))
    }


def event_path(scale: str, stream_seed: int) -> Path:
    return (
        EVENT_ROOT
        / INSTANCE_BY_SCALE[scale]
        / f"stream_seed{int(stream_seed)}.json"
    )


def stream_for_algorithm_seed(seed: int) -> int:
    return 1 + ((int(seed) - 1) % 5)


def base_owner_path(scale: str) -> Path:
    instance_id = INSTANCE_BY_SCALE[scale]
    if scale in {"50c", "100c"}:
        return E3_ROOT / "inputs" / instance_id / "JOINT" / "responsibility_map.json"
    return FOUNDATION_150 / "responsibility_map.json"


def nominal_plan_path(scale: str, seed: int) -> Path:
    instance_id = INSTANCE_BY_SCALE[scale]
    if scale in {"50c", "100c"}:
        return (
            E3_ROOT
            / "formal/plans"
            / f"{instance_id}__seed{int(seed):02d}__JOINT.json"
        )
    return FOUNDATION_150 / "initial_solution.json"


def load_event_payload(scale: str, stream_seed: int) -> dict[str, Any]:
    path = event_path(scale, stream_seed)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "resetp.china81.e7.events.v1":
        raise RuntimeError(f"HALT_EVENT_SCHEMA:{path}")
    if payload.get("instance_id") != INSTANCE_BY_SCALE[scale]:
        raise RuntimeError(f"HALT_EVENT_INSTANCE:{path}")
    if int(payload.get("stream_seed", -1)) != int(stream_seed):
        raise RuntimeError(f"HALT_EVENT_SEED:{path}")
    return payload


def build_owner_inputs() -> dict[str, Any]:
    e3 = e3_module()
    rows: list[dict[str, Any]] = []
    for scale in SCALES:
        bundle = e3.load_bundle(INSTANCE_BY_SCALE[scale])
        node_by_id = {node.node_id: node for node in bundle.instance.nodes}
        base_payload = json.loads(base_owner_path(scale).read_text(encoding="utf-8"))
        base_mapping = {
            str(key): str(value)
            for key, value in base_payload["mapping"].items()
        }
        for stream_seed in range(1, 6):
            events = load_event_payload(scale, stream_seed)["events"]
            mapping = dict(base_mapping)
            donor_clones = 0
            for row in events:
                if row["event_type"] != "add":
                    continue
                donor_id = str(row["donor_customer_id"])
                donor = node_by_id.get(donor_id)
                if donor is None or donor_id not in base_mapping:
                    raise RuntimeError(
                        f"HALT_ADD_DONOR_OWNER:{scale}:{stream_seed}:{donor_id}"
                    )
                exact = (
                    abs(float(row["x"]) - float(donor.x)) <= 1.0e-12
                    and abs(float(row["y"]) - float(donor.y)) <= 1.0e-12
                    and abs(float(row["new_demand"]) - float(donor.demand))
                    <= 1.0e-12
                    and abs(
                        float(row["new_service_time"])
                        - float(donor.service_time)
                    )
                    <= 1.0e-12
                )
                if not exact:
                    raise RuntimeError(
                        f"HALT_ADD_NOT_EXACT_DONOR_CLONE:"
                        f"{scale}:{stream_seed}:{row['event_id']}"
                    )
                mapping[str(row["customer_id"])] = base_mapping[donor_id]
                donor_clones += 1
            payload = {
                "schema": "resetp.china81.e7.derived-owners.v1",
                "task_id": TASK_ID,
                "scale": scale,
                "instance_id": INSTANCE_BY_SCALE[scale],
                "stream_seed": stream_seed,
                "derivation": "base ZONE responsibility; add inherits exact donor owner",
                "base_owner_path": relative(base_owner_path(scale)),
                "base_owner_sha256": sha256(base_owner_path(scale)),
                "event_path": relative(event_path(scale, stream_seed)),
                "event_sha256": sha256(event_path(scale, stream_seed)),
                "mapping": mapping,
            }
            payload["mapping_sha256"] = canonical_sha256(mapping)
            output = (
                HERE
                / "inputs/owners"
                / INSTANCE_BY_SCALE[scale]
                / f"stream_seed{stream_seed}.json"
            )
            if output.exists():
                existing = json.loads(output.read_text(encoding="utf-8"))
                if existing != payload:
                    raise RuntimeError(f"HALT_DERIVED_OWNER_DRIFT:{output}")
            else:
                atomic_json(output, payload)
            rows.append(
                {
                    "scale": scale,
                    "stream_seed": stream_seed,
                    "owner_count": len(mapping),
                    "added_owner_count": donor_clones,
                    "owner_path": relative(output),
                    "owner_sha256": sha256(output),
                }
            )
    atomic_csv(HERE / "inputs/owner_manifest.csv", rows)
    return {"stream_count": len(rows), "rows": rows}


def owner_input_path(scale: str, stream_seed: int) -> Path:
    return (
        HERE
        / "inputs/owners"
        / INSTANCE_BY_SCALE[scale]
        / f"stream_seed{int(stream_seed)}.json"
    )


def load_owners(scale: str, stream_seed: int) -> dict[str, str]:
    payload = json.loads(
        owner_input_path(scale, stream_seed).read_text(encoding="utf-8")
    )
    mapping = {str(key): str(value) for key, value in payload["mapping"].items()}
    if canonical_sha256(mapping) != payload["mapping_sha256"]:
        raise RuntimeError("HALT_DERIVED_OWNER_HASH_DRIFT")
    return mapping


def solution_from_plan(scale: str, seed: int) -> Solution:
    payload = json.loads(
        nominal_plan_path(scale, seed).read_text(encoding="utf-8")
    )
    if scale in {"50c", "100c"}:
        if payload.get("arm") != "JOINT" or int(payload.get("seed", -1)) != int(seed):
            raise RuntimeError(f"HALT_NOMINAL_PLAN_ID:{scale}:{seed}")
        payload = payload["solution"]
    return e3_module().solution_from_payload(payload)


def current_sources(
    condition: str,
    network: str = "50c",
) -> tuple[dict[str, Any], dict[int, list[dict[str, Any]]]]:
    del condition
    global _BASE_CHINA_BUNDLE, _BASE_INSTANCE, _ALIAS_BY_NODE_ID
    scale = str(network)
    if scale not in SCALES:
        raise ValueError(f"unknown scale {scale}")
    bundle = e3_module().load_bundle(INSTANCE_BY_SCALE[scale])
    solution = solution_from_plan(scale, _CURRENT_ALGORITHM_SEED)
    prepared, certificate = prepare_multitrip_solution(
        solution,
        bundle.instance,
        bundle.prices,
    )
    validate_multitrip_certificate(
        certificate,
        list(prepared.routes),
        bundle.prices,
    )
    _BASE_CHINA_BUNDLE = bundle
    _BASE_INSTANCE = bundle.instance
    _ALIAS_BY_NODE_ID = {
        node.node_id: node.node_id for node in bundle.instance.nodes
    }
    search_bundle = SearchBundle(
        bundle_dir=nominal_plan_path(scale, _CURRENT_ALGORITHM_SEED).parent,
        instance=bundle.instance,
        carbon_profile=list(bundle.time_profile),
    )
    sources = {
        "case": f"{INSTANCE_BY_SCALE[scale]}__seed{_CURRENT_ALGORITHM_SEED}",
        "bundle": search_bundle,
        "prices": bundle.prices,
        "solution": prepared,
        "certificate": certificate,
        "solution_path": nominal_plan_path(scale, _CURRENT_ALGORITHM_SEED),
        "certificate_path": nominal_plan_path(scale, _CURRENT_ALGORITHM_SEED),
        "instance_path": Path(bundle.source_paths["instance_json"]),
    }
    return sources, {0: list(bundle.time_profile)}


def current_stream(
    stream_seed: int,
    condition: str,
    network: str = "50c",
) -> tuple[list[DynamicEvent], dict[str, str], Path, Path]:
    del condition
    scale = str(network)
    payload = load_event_payload(scale, stream_seed)
    events = [DynamicEvent(**row) for row in payload["events"]]
    return (
        events,
        load_owners(scale, stream_seed),
        event_path(scale, stream_seed),
        owner_input_path(scale, stream_seed),
    )


def validated_batches(
    network: str,
    stream_seed: int,
    events: Sequence[DynamicEvent],
) -> list[dict[str, Any]]:
    payload = load_event_payload(str(network), stream_seed)
    params = RollingParameters(**payload["rolling_parameters"])
    batches = [
        batch
        for batch in probe.base._build_trigger_batches(list(events), params)
        if batch["events"]
    ]
    observed = [
        event.event_id
        for batch in batches
        for event in batch["events"]
    ]
    expected = [str(row["event_id"]) for row in payload["events"]]
    if sorted(observed) != sorted(expected) or len(observed) != len(set(observed)):
        raise RuntimeError(
            f"HALT_EVENT_TRIGGER_PARTITION:{network}:{stream_seed}"
        )
    return batches


def _base_alias(node_id: str) -> str:
    alias = _ALIAS_BY_NODE_ID.get(node_id)
    if alias is None:
        raise RuntimeError(f"HALT_MISSING_ROAD_ALIAS:{node_id}")
    return alias


def exact_instance_after_events(
    instance: Instance,
    events: list[DynamicEvent],
    trigger_time: float,
    already_served: set[str],
    frozen_nodes: dict[str, Node] | None = None,
) -> Instance:
    """Apply events while cloning exact same-location China81 road profiles."""

    if _BASE_INSTANCE is None:
        raise RuntimeError("HALT_BASE_INSTANCE_NOT_BOUND")
    base = _BASE_INSTANCE
    base_nodes = {node.node_id: node for node in base.nodes}
    nodes_by_id = {node.node_id: node for node in instance.nodes}
    removed: set[str] = set()
    for event in sorted(
        events,
        key=lambda item: (float(item.t_appear), str(item.event_id)),
    ):
        if float(event.t_appear) > float(trigger_time) + 1.0e-9:
            continue
        event_type = event.event_type.lower()
        if event_type == "add":
            donor = base_nodes.get(str(event.donor_customer_id))
            if donor is None:
                raise RuntimeError(
                    f"HALT_ADD_DONOR_NOT_IN_BASE:{event.donor_customer_id}"
                )
            if (
                abs(float(event.x) - float(donor.x)) > 1.0e-12
                or abs(float(event.y) - float(donor.y)) > 1.0e-12
            ):
                raise RuntimeError(
                    f"HALT_EUCLIDEAN_FALLBACK_FORBIDDEN:{event.customer_id}"
                )
            _ALIAS_BY_NODE_ID[event.customer_id] = donor.node_id
            nodes_by_id[event.customer_id] = Node(
                node_id=event.customer_id,
                node_type="c",
                x=float(event.x),
                y=float(event.y),
                demand=float(event.new_demand),
                ready_time=float(event.new_ready_time),
                due_time=float(event.new_due_time),
                service_time=(
                    float(event.new_service_time)
                    if event.new_service_time is not None
                    else float(donor.service_time)
                ),
                city=donor.city,
            )
            removed.discard(event.customer_id)
        elif event_type == "cancel":
            if event.customer_id not in already_served:
                removed.add(event.customer_id)
        elif event_type in {"demand_change", "change"}:
            node = nodes_by_id.get(event.customer_id)
            if node is not None and event.customer_id not in already_served:
                nodes_by_id[event.customer_id] = replace(
                    node,
                    demand=float(event.new_demand),
                )
        elif event_type == "time_window_change":
            node = nodes_by_id.get(event.customer_id)
            if node is not None and event.customer_id not in already_served:
                nodes_by_id[event.customer_id] = replace(
                    node,
                    ready_time=float(event.new_ready_time),
                    due_time=float(event.new_due_time),
                )
        else:
            raise RuntimeError(f"HALT_UNSUPPORTED_EVENT:{event.event_type}")
    nodes = [
        node
        for node_id, node in nodes_by_id.items()
        if node_id not in removed
    ]
    if frozen_nodes:
        nodes = [frozen_nodes.get(node.node_id, node) for node in nodes]
    base_index = base.node_index
    aliases = [_base_alias(node.node_id) for node in nodes]
    matrix = [
        [
            float(base.distance(left_alias, right_alias))
            for right_alias in aliases
        ]
        for left_alias in aliases
    ]
    road_profiles = None
    if base.road_profiles is not None:
        road_profiles = {
            profile: RoadProfileMatrices(
                distance_m=tuple(
                    tuple(
                        float(matrices.distance_m[base_index[left]][base_index[right]])
                        for right in aliases
                    )
                    for left in aliases
                ),
                duration_s=tuple(
                    tuple(
                        float(matrices.duration_s[base_index[left]][base_index[right]])
                        for right in aliases
                    )
                    for left in aliases
                ),
                sum_v2d_m3_s2=tuple(
                    tuple(
                        float(matrices.sum_v2d_m3_s2[base_index[left]][base_index[right]])
                        for right in aliases
                    )
                    for left in aliases
                ),
            )
            for profile, matrices in base.road_profiles.items()
        }
    return Instance(
        nodes=nodes,
        distance_matrix=matrix,
        diesel_l_per_meter=instance.diesel_l_per_meter,
        ev_kwh_per_meter=instance.ev_kwh_per_meter,
        unit_distance_cost_per_meter=instance.unit_distance_cost_per_meter,
        num_cv=instance.num_cv,
        num_ev=instance.num_ev,
        road_profiles=road_profiles,
        vehicle_parameters=base.vehicle_parameters,
        demand_mass_per_unit_kg=base.demand_mass_per_unit_kg,
    )


def traced_search_stage(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if not _TRACE_MODE:
        return _ORIGINAL_SEARCH_STAGE(*args, **kwargs)
    budget_class = probe.base.EvalBudget
    original_record = budget_class.record
    original_exact = probe.base.exact_candidate
    current_evaluation = 0
    observations: dict[int, float | None] = {}
    best = math.inf
    improvement_rows: list[dict[str, Any]] = []

    def record(budget: Any) -> Any:
        nonlocal current_evaluation
        result = original_record(budget)
        current_evaluation = int(budget.count)
        observations.setdefault(current_evaluation, None)
        return result

    def exact(*exact_args: Any, **exact_kwargs: Any) -> Any:
        nonlocal best
        try:
            result = original_exact(*exact_args, **exact_kwargs)
        except ValueError:
            observations[current_evaluation] = None
            raise
        objective = float(result[2])
        observations[current_evaluation] = objective
        improved = objective < best - 1.0e-9
        if improved:
            best = objective
            improvement_rows.append(
                {
                    "evaluation": current_evaluation,
                    "objective": objective,
                }
            )
        return result

    budget_class.record = record
    probe.base.exact_candidate = exact
    try:
        result = _ORIGINAL_SEARCH_STAGE(*args, **kwargs)
    finally:
        budget_class.record = original_record
        probe.base.exact_candidate = original_exact
    cap = int(kwargs["evaluations"])
    trace = [
        {
            "evaluation": index,
            "complete_objective": observations.get(index),
        }
        for index in range(1, cap + 1)
    ]
    result["convergence_trace"] = trace
    result["strict_improvements"] = improvement_rows
    result["last_strict_improvement_evaluation"] = (
        int(improvement_rows[-1]["evaluation"])
        if improvement_rows
        else 0
    )
    _LAST_SEARCH_TRACES.append(
        {
            "search_seed": int(result["search_seed"]),
            "cap": cap,
            "last_strict_improvement_evaluation":
                result["last_strict_improvement_evaluation"],
            "strict_improvements": improvement_rows,
            "trace": trace,
        }
    )
    return result


def static_fixed_stage(
    construction: Any,
    sources: Mapping[str, Any],
    profiles: Mapping[int, list[dict[str, Any]]],
    cut: Any,
    owners: dict[str, str],
    committed_profit: Mapping[str, float],
    *,
    trigger: float,
    seed: int,
    stage_new_customer_ids: Sequence[str],
) -> dict[str, Any]:
    del seed
    prepared, certificate, type_trials = (
        probe.base.gate.prepare_stage_with_singleton_type_choices(
            construction,
            sources["prices"],
            asset_states=cut.asset_states,
            stage_start_second=trigger,
            locked_charging_actions=cut.locked_charging_actions,
        )
    )
    timing_pair = probe._dynamic_timing_pair(
        prepared,
        certificate,
        construction,
        sources,
        profiles,
        cut,
        trigger=trigger,
    )
    solution = timing_pair["aware_solution"]
    certificate = timing_pair["aware_certificate"]
    timing = timing_pair["aware_stats"]
    cost = float(
        probe.base.evaluate_parts(
            solution.routes,
            solution.charging_actions,
            construction.effective_instance,
            sources,
        )["total_cost"]
    )
    profits = probe._profit_values(
        solution,
        construction.effective_instance,
        sources,
        owners,
        prior_profit=committed_profit,
    )
    ratios = {depot: 1.0 for depot in profits}
    structure_hash = canonical_sha256(
        probe.base.solution_to_dict(construction.solution)
    )
    return {
        "initial_solution": prepared,
        "initial_certificate": certificate,
        "initial_search_structure": construction.solution,
        "initial_cost": cost,
        "solution": solution,
        "certificate": certificate,
        "search_structure": construction.solution,
        "future_cost": cost,
        "initial_feasible": True,
        "type_trials": type_trials,
        "changed_count": 0,
        "feasible_count": 1,
        "feasible_cross_candidate_count": 0,
        "forced_cross_attempt_count": 0,
        "accepted_count": 0,
        "best_gate_rejection_count": 0,
        "existing_cross_operator_id": "none_static_fixed_recourse",
        "existing_cross_scheduled_slots": [],
        "existing_cross_scheduled_call_count": 0,
        "existing_cross_actual_call_count": 0,
        "existing_cross_pair_removal_count": 0,
        "existing_cross_forced_insertion_count": 0,
        "existing_cross_within_depot_reinsert_count": 0,
        "existing_cross_candidate_build_count": 0,
        "existing_cross_changed_candidate_count": 0,
        "existing_cross_dynamic_feasible_count": 0,
        "existing_cross_gate_rejection_count": 0,
        "existing_cross_accepted_count": 0,
        "existing_cross_best_improved_count": 0,
        "existing_cross_moved_customer_ids": [],
        "existing_cross_rejections": {},
        "exact_check_count": 1,
        "dynamic_rejections": {},
        "evaluations": 0,
        "elapsed_seconds": 0.0,
        "operator_pairs": [],
        "search_seed": 0,
        "timing": timing,
        "timing_comparison": timing_pair["comparison"],
        "charging_strategy": "aware",
        "same_state_baseline_cost": cost,
        "same_state_baseline_profit": profits,
        "selected_future_profit": profits,
        "profit_margins": {depot: 0.0 for depot in profits},
        "profit_ratios": ratios,
        "minimum_profit_margin": 0.0,
        "minimum_profit_ratio": 1.0,
        "same_state_cost_saving_pct": 0.0,
        "shadow_evaluations": 0,
        "shadow_search_seed": 0,
        "same_state_baseline_start_source": "fixed_route_event_recourse",
        "same_state_baseline_allowed_cross_ids": [],
        "main_search_seed": 0,
        "second_start_sha256": structure_hash,
        "baseline_output_sha256": structure_hash,
        "stage_new_customer_ids": list(stage_new_customer_ids),
        "stage_new_customer_count": len(stage_new_customer_ids),
        "shadow_existing_cross_actual_call_count": 0,
    }


def controlled_stage_dispatch(
    arm: str,
    construction: Any,
    sources: Mapping[str, Any],
    profiles: Mapping[int, list[dict[str, Any]]],
    cut: Any,
    owners: dict[str, str],
    committed_customers: set[str],
    committed_profit: Mapping[str, float],
    *,
    trigger: float,
    seed: int,
    evaluations: int,
    stage_new_customer_ids: Sequence[str],
) -> dict[str, Any]:
    stage_number = int(seed) % 1000
    effective_seed = _CURRENT_ALGORITHM_SEED * 1000 + stage_number
    started = time.perf_counter()
    if arm == "STATIC_FIXED_RECOURSE":
        result = static_fixed_stage(
            construction,
            sources,
            profiles,
            cut,
            owners,
            committed_profit,
            trigger=trigger,
            seed=effective_seed,
            stage_new_customer_ids=stage_new_customer_ids,
        )
    elif arm == "FULL_ROLLING":
        result = _ORIGINAL_CONTROLLED_STAGE(
            "full",
            construction,
            sources,
            profiles,
            cut,
            owners,
            committed_customers,
            committed_profit,
            trigger=trigger,
            seed=effective_seed,
            evaluations=evaluations,
            stage_new_customer_ids=stage_new_customer_ids,
        )
    elif arm == "NO_COOPERATION":
        result = _ORIGINAL_CONTROLLED_STAGE(
            "no_cooperation",
            construction,
            sources,
            profiles,
            cut,
            owners,
            committed_customers,
            committed_profit,
            trigger=trigger,
            seed=effective_seed,
            evaluations=evaluations,
            stage_new_customer_ids=stage_new_customer_ids,
        )
    elif arm == "CARBON_BLIND":
        probe._timing_variant_for_strategy = lambda _strategy: "immediate"
        try:
            result = _ORIGINAL_CONTROLLED_STAGE(
                "full",
                construction,
                sources,
                profiles,
                cut,
                owners,
                committed_customers,
                committed_profit,
                trigger=trigger,
                seed=effective_seed,
                evaluations=evaluations,
                stage_new_customer_ids=stage_new_customer_ids,
            )
        finally:
            probe._timing_variant_for_strategy = _ORIGINAL_TIMING_VARIANT
        result["charging_strategy"] = "naive"
    else:
        raise ValueError(f"unknown arm {arm}")
    actual = int(result["evaluations"]) + int(result["shadow_evaluations"])
    if actual > 2 * int(evaluations):
        raise RuntimeError(
            f"HALT_STAGE_BUDGET_OVERRUN:{arm}:{actual}>{2 * int(evaluations)}"
        )
    print(
        json.dumps(
            {
                "task": (
                    f"{_CURRENT_SCALE}/seed{_CURRENT_ALGORITHM_SEED:02d}/"
                    f"{arm}"
                ),
                "stage": stage_number,
                "status": "PASS_STAGE",
                "elapsed_seconds": time.perf_counter() - started,
                "actual_evaluations": actual,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return result


def install_adapter() -> None:
    probe.ARMS = ARMS
    probe._sources_for_day = current_sources
    probe._stream_for_condition = current_stream
    probe._validated_multinetwork_trigger_batches = validated_batches
    probe.base.gate._instance_after_events = exact_instance_after_events
    probe.base.search_stage = traced_search_stage
    probe._controlled_stage = controlled_stage_dispatch


def initial_cross_ids(
    solution: Solution,
    instance: Instance,
    owners: Mapping[str, str],
) -> list[str]:
    return sorted(
        probe.base._cross_site_ids_for_routes(
            solution.routes,
            instance,
            owners,
        )
    )


def task_path(scale: str, seed: int, arm: str) -> Path:
    return (
        HERE
        / "formal"
        / scale
        / "tasks"
        / f"{INSTANCE_BY_SCALE[scale]}__seed{seed:02d}__{arm}.json"
    )


def run_task(
    scale: str,
    seed: int,
    arm: str,
    *,
    per_pass_cap: int,
    max_stages: int,
    trace_mode: bool = False,
) -> dict[str, Any]:
    global _CURRENT_SCALE, _CURRENT_ALGORITHM_SEED, _CURRENT_STREAM_SEED
    global _TRACE_MODE, _LAST_SEARCH_TRACES
    verify_thread_environment()
    verify_protected()
    install_adapter()
    _CURRENT_SCALE = scale
    _CURRENT_ALGORITHM_SEED = int(seed)
    _CURRENT_STREAM_SEED = stream_for_algorithm_seed(seed)
    _TRACE_MODE = bool(trace_mode)
    _LAST_SEARCH_TRACES = []
    sources, profiles = current_sources(f"seed{seed}", scale)
    owners = load_owners(scale, _CURRENT_STREAM_SEED)
    nominal_solution, _, nominal_timing = probe._initial_plan(
        "full",
        sources,
        profiles,
    )
    nominal_ledger = probe._profit_closure(
        nominal_solution,
        sources["bundle"].instance,
        sources,
        owners,
    )
    started = time.perf_counter()
    before = resource.getrusage(resource.RUSAGE_SELF)
    payload = probe.run_probe_arm(
        arm,
        condition=f"seed{seed}",
        stream_seed=_CURRENT_STREAM_SEED,
        evaluations=int(per_pass_cap),
        max_stages=int(max_stages),
        network=scale,
    )
    elapsed = time.perf_counter() - started
    after = resource.getrusage(resource.RUSAGE_SELF)
    full_solution = probe.base.solution_from_dict(payload["full_day_solution"])
    physical_vehicles = sorted(
        {
            physical_vehicle_id(route.vehicle_id)
            for route in full_solution.routes
        }
    )
    total_evaluations = sum(
        int(row["main_evaluations"]) + int(row["shadow_evaluations"])
        for row in payload["rows"]
    )
    stage_cap = 2 * int(per_pass_cap)
    if any(
        int(row["main_evaluations"]) + int(row["shadow_evaluations"])
        > stage_cap
        for row in payload["rows"]
    ):
        raise RuntimeError("HALT_ACTUAL_EVALUATIONS_ABOVE_STAGE_CAP")
    final_cross = set(payload["full_day_execution"]["cross_site_customer_ids"])
    initial_cross = set(
        initial_cross_ids(
            nominal_solution,
            sources["bundle"].instance,
            owners,
        )
    )
    stage_profit_ledgers = [
        json.loads(row["running_depot_profit_json"])
        for row in payload["rows"]
    ]
    initial_profit = nominal_ledger["depot_profit"]
    profit_shift = any(
        abs(float(ledger.get(depot, 0.0)) - float(initial_profit.get(depot, 0.0)))
        > TOL
        for ledger in stage_profit_ledgers
        for depot in set(ledger) | set(initial_profit)
    )
    moved_after_event = sum(
        int(row["aware_vs_immediate_moved_action_count"])
        for row in payload["rows"]
    )
    result = {
        "schema": "resetp.china81.e7.task.v1",
        "task_id": TASK_ID,
        "status": "PASS",
        "created_at_utc": now_iso(),
        "scale": scale,
        "instance_id": INSTANCE_BY_SCALE[scale],
        "algorithm_seed": int(seed),
        "stream_seed": _CURRENT_STREAM_SEED,
        "arm": arm,
        "per_search_pass_cap": int(per_pass_cap),
        "per_stage_total_cap": stage_cap,
        "stage_count": int(payload["stages"]),
        "actual_evaluations": total_evaluations,
        "nominal_total_cost": float(nominal_ledger["total_cost"]),
        "nominal_total_profit": float(nominal_ledger["total_profit"]),
        "nominal_depot_profit": initial_profit,
        "nominal_timing": nominal_timing,
        "initial_cross_site_customer_ids": sorted(initial_cross),
        "final_total_cost": float(payload["final_running"]["total_cost"]),
        "final_total_profit": float(payload["final_running"]["total_profit"]),
        "final_depot_profit": payload["final_running"]["depot_profit"],
        "final_actual_emissions_kg": float(
            payload["final_running"]["total_actual_emissions_kg"]
        ),
        "final_actual_charging_emissions_kg": float(
            payload["final_running"]["actual_charging_emissions_kg"]
        ),
        "final_charging_energy_kwh": sum(
            float(action.energy_kwh)
            for action in full_solution.charging_actions
        ),
        "vehicle_count": len(physical_vehicles),
        "physical_vehicle_ids": physical_vehicles,
        "wall_seconds": elapsed,
        "cpu_user_seconds": after.ru_utime - before.ru_utime,
        "cpu_system_seconds": after.ru_stime - before.ru_stime,
        "event_path": relative(event_path(scale, _CURRENT_STREAM_SEED)),
        "event_sha256": sha256(event_path(scale, _CURRENT_STREAM_SEED)),
        "owner_path": relative(
            owner_input_path(scale, _CURRENT_STREAM_SEED)
        ),
        "owner_sha256": sha256(
            owner_input_path(scale, _CURRENT_STREAM_SEED)
        ),
        "nominal_plan_path": relative(nominal_plan_path(scale, seed)),
        "nominal_plan_sha256": sha256(nominal_plan_path(scale, seed)),
        "cross_depot_reassignment_after_event": bool(final_cross - initial_cross),
        "new_cross_site_customer_ids": sorted(final_cross - initial_cross),
        "member_profit_shift_after_event": profit_shift,
        "carbon_aware_charging_shift_after_event": moved_after_event > 0,
        "moved_charge_actions_after_event": moved_after_event,
        "payload": payload,
        "convergence_search_traces": list(_LAST_SEARCH_TRACES),
        "protected_hashes": verify_protected(),
    }
    result["result_sha256"] = canonical_sha256(result)
    _TRACE_MODE = False
    return result


def worker(args: tuple[str, int, str, int, int]) -> dict[str, Any]:
    scale, seed, arm, per_pass_cap, max_stages = args
    output = task_path(scale, seed, arm)
    if output.exists():
        existing = json.loads(output.read_text(encoding="utf-8"))
        if (
            existing.get("status") == "PASS"
            and int(existing.get("per_search_pass_cap", -1)) == per_pass_cap
            and existing.get("protected_hashes") == verify_protected()
        ):
            return existing
        raise RuntimeError(f"HALT_STALE_TASK:{output}")
    result = run_task(
        scale,
        seed,
        arm,
        per_pass_cap=per_pass_cap,
        max_stages=max_stages,
    )
    atomic_json(output, result)
    return result


def preflight(workers: int) -> dict[str, Any]:
    if workers < 1 or workers > 2:
        raise RuntimeError("HALT_WORKERS_MUST_BE_1_OR_2")
    if Path(sys.executable).resolve() != PYTHON.resolve():
        raise RuntimeError(
            f"HALT_WRONG_PYTHON:{sys.executable}!={PYTHON}"
        )
    environment = verify_thread_environment()
    protected = verify_protected()
    owner_manifest = build_owner_inputs()
    event_rows: list[dict[str, Any]] = []
    total_events = 0
    for scale in SCALES:
        for stream_seed in range(1, 6):
            path = event_path(scale, stream_seed)
            payload = load_event_payload(scale, stream_seed)
            events = payload["events"]
            total_events += len(events)
            counts = defaultdict(int)
            for row in events:
                counts[str(row["event_type"])] += 1
            event_rows.append(
                {
                    "scale": scale,
                    "instance_id": INSTANCE_BY_SCALE[scale],
                    "stream_seed": stream_seed,
                    "event_count": len(events),
                    "add_count": counts["add"],
                    "cancel_count": counts["cancel"],
                    "demand_change_count": counts["demand_change"],
                    "path": relative(path),
                    "file_sha256": sha256(path),
                    "canonical_sha256": canonical_sha256(payload),
                }
            )
    atomic_csv(HERE / "inputs/event_manifest.csv", event_rows)
    load_average = os.getloadavg()
    memory = subprocess.run(
        ["vm_stat"],
        check=False,
        text=True,
        capture_output=True,
    ).stdout
    result = {
        "schema": "resetp.china81.e7.preflight.v1",
        "task_id": TASK_ID,
        "status": "PASS_PREFLIGHT",
        "created_at_utc": now_iso(),
        "python_executable": sys.executable,
        "workers": workers,
        "thread_environment": environment,
        "load_average": load_average,
        "vm_stat": memory,
        "event_streams_found": len(event_rows),
        "event_count": total_events,
        "owner_streams_built": owner_manifest["stream_count"],
        "protected_hashes": protected,
        "source_hashes": source_hashes(),
        "search_evaluations": 0,
    }
    result["preflight_sha256"] = canonical_sha256(result)
    atomic_json(HERE / "preflight.json", result)
    append_progress(
        {
            "phase": "preflight",
            "status": "PASS",
            "event_streams_found": len(event_rows),
        }
    )
    return result


def round_up_hundred(value: int) -> int:
    return max(100, int(math.ceil(int(value) / 100.0) * 100))


def run_probe() -> dict[str, Any]:
    verify_protected()
    if not (HERE / "preflight.json").is_file():
        raise RuntimeError("HALT_PREFLIGHT_MISSING")
    attempts: list[dict[str, Any]] = []
    for cap in (800, 1600):
        result = run_task(
            "50c",
            1,
            "FULL_ROLLING",
            per_pass_cap=cap,
            max_stages=1,
            trace_mode=True,
        )
        traces = result["convergence_search_traces"]
        if len(traces) != 2:
            raise RuntimeError(
                f"HALT_PROBE_EXPECTED_TWO_SEARCH_PASSES:{len(traces)}"
            )
        last_values = [
            int(row["last_strict_improvement_evaluation"])
            for row in traces
        ]
        latest = max(last_values)
        attempt = {
            "per_pass_long_cap": cap,
            "per_stage_long_cap": 2 * cap,
            "last_shadow_improvement_evaluation": last_values[0],
            "last_main_improvement_evaluation": last_values[1],
            "latest_improvement_evaluation": latest,
            "result_sha256": result["result_sha256"],
            "convergence_search_traces": traces,
        }
        attempts.append(attempt)
        atomic_json(HERE / "probe" / f"cap_{cap}.json", result)
        if latest <= int(0.9 * cap):
            selected_per_pass = round_up_hundred(latest)
            break
        if cap == 1600:
            halt = {
                "schema": "resetp.china81.e7.budget-lock.v1",
                "status": "HALT_NEEDS_LONGER_BUDGET_DECISION",
                "attempts": attempts,
            }
            atomic_json(HERE / "budget_lock.json", halt)
            raise RuntimeError("HALT_NEEDS_LONGER_BUDGET_DECISION")
    else:
        raise AssertionError("unreachable")
    lock = {
        "schema": "resetp.china81.e7.budget-lock.v1",
        "task_id": TASK_ID,
        "status": "PASS_BUDGET_SELECTED",
        "created_at_utc": now_iso(),
        "budget_semantics": "UPPER_CAP_NOT_QUOTA",
        "selection_rule": (
            "later shadow/main last strict improvement, rounded up to 100"
        ),
        "attempts": attempts,
        "selected_per_search_pass_cap": selected_per_pass,
        "selected_total_stage_cap": 2 * selected_per_pass,
        "protected_hashes": verify_protected(),
    }
    lock["budget_lock_sha256"] = canonical_sha256(lock)
    atomic_json(HERE / "budget_lock.json", lock)
    append_progress(
        {
            "phase": "probe",
            "status": "PASS",
            "selected_per_search_pass_cap": selected_per_pass,
            "selected_total_stage_cap": 2 * selected_per_pass,
        }
    )
    return lock


def load_budget_lock() -> dict[str, Any]:
    path = HERE / "budget_lock.json"
    if not path.is_file():
        raise RuntimeError("HALT_BUDGET_LOCK_MISSING")
    lock = json.loads(path.read_text(encoding="utf-8"))
    if lock.get("status") != "PASS_BUDGET_SELECTED":
        raise RuntimeError(f"HALT_BUDGET_NOT_SELECTED:{lock.get('status')}")
    return lock


def run_formal(scale: str, workers: int) -> dict[str, Any]:
    if scale not in SCALES:
        raise ValueError(scale)
    if workers < 1 or workers > 2:
        raise RuntimeError("HALT_WORKERS_MUST_BE_1_OR_2")
    verify_thread_environment()
    verify_protected()
    lock = load_budget_lock()
    cap = int(lock["selected_per_search_pass_cap"])
    specs = [
        (scale, seed, arm, cap, 99)
        for seed in range(1, 11)
        for arm in ARMS
    ]
    append_progress(
        {
            "phase": f"formal-{scale}",
            "status": "START",
            "unit_count": len(specs),
            "workers": workers,
            "per_search_pass_cap": cap,
        }
    )
    completed = 0
    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=ctx,
    ) as executor:
        futures = {executor.submit(worker, spec): spec for spec in specs}
        for future in as_completed(futures):
            spec = futures[future]
            try:
                result = future.result()
            except Exception:
                for pending in futures:
                    pending.cancel()
                append_progress(
                    {
                        "phase": f"formal-{scale}",
                        "status": "HALT",
                        "failed_spec": list(spec),
                    }
                )
                raise
            completed += 1
            append_progress(
                {
                    "phase": f"formal-{scale}",
                    "status": "PASS_UNIT",
                    "completed": completed,
                    "total": len(specs),
                    "seed": result["algorithm_seed"],
                    "arm": result["arm"],
                    "wall_seconds": result["wall_seconds"],
                }
            )
            print(
                f"[{scale}] {completed}/{len(specs)} "
                f"seed={result['algorithm_seed']} arm={result['arm']} "
                f"cost={result['final_total_cost']:.6f}",
                flush=True,
            )
    marker = {
        "schema": "resetp.china81.e7.scale-complete.v1",
        "task_id": TASK_ID,
        "status": f"COMPLETE_{scale}",
        "created_at_utc": now_iso(),
        "scale": scale,
        "instance_id": INSTANCE_BY_SCALE[scale],
        "task_count": len(specs),
        "per_search_pass_cap": cap,
        "per_stage_total_cap": 2 * cap,
        "protected_hashes": verify_protected(),
    }
    marker["marker_sha256"] = canonical_sha256(marker)
    atomic_json(HERE / "formal" / scale / "scale_complete.json", marker)
    append_progress(
        {
            "phase": f"formal-{scale}",
            "status": "COMPLETE",
            "unit_count": len(specs),
        }
    )
    return marker


def task_results() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scale in SCALES:
        for seed in range(1, 11):
            for arm in ARMS:
                path = task_path(scale, seed, arm)
                if not path.is_file():
                    continue
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("status") != "PASS":
                    raise RuntimeError(f"HALT_NONPASS_TASK:{path}")
                rows.append(payload)
    return rows


def raw_row(task: Mapping[str, Any]) -> dict[str, Any]:
    charging_energy = float(task["final_charging_energy_kwh"])
    weighted = (
        1000.0
        * float(task["final_actual_charging_emissions_kg"])
        / charging_energy
        if charging_energy > TOL
        else None
    )
    nominal = float(task["nominal_total_cost"])
    final = float(task["final_total_cost"])
    return {
        "instance_id": task["instance_id"],
        "scale": task["scale"],
        "seed": task["algorithm_seed"],
        "stream_seed": task["stream_seed"],
        "arm": task["arm"],
        "nominal_total_cost_cny": nominal,
        "final_total_cost_cny": final,
        "cost_change_vs_nominal_pct": 100.0 * (final - nominal) / nominal,
        "vehicle_count": task["vehicle_count"],
        "wall_seconds": task["wall_seconds"],
        "actual_evaluations": task["actual_evaluations"],
        "per_stage_budget_cap": task["per_stage_total_cap"],
        "stage_count": task["stage_count"],
        "final_total_profit_cny": task["final_total_profit"],
        "final_actual_emissions_kg": task["final_actual_emissions_kg"],
        "final_actual_charging_emissions_kg":
            task["final_actual_charging_emissions_kg"],
        "charging_weighted_carbon_gco2_per_kwh": weighted,
        "cross_depot_reassignment_after_event":
            task["cross_depot_reassignment_after_event"],
        "new_cross_site_customer_count": len(
            task["new_cross_site_customer_ids"]
        ),
        "member_profit_shift_after_event": task["member_profit_shift_after_event"],
        "carbon_aware_charging_shift_after_event":
            task["carbon_aware_charging_shift_after_event"],
        "moved_charge_actions_after_event":
            task["moved_charge_actions_after_event"],
        "event_sha256": task["event_sha256"],
        "nominal_plan_sha256": task["nominal_plan_sha256"],
        "result_sha256": task["result_sha256"],
        "status": task["status"],
    }


def paired_metrics(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    indexed = {
        (str(row["scale"]), int(row["seed"]), str(row["arm"])): row
        for row in rows
    }
    output: list[dict[str, Any]] = []
    for scale in SCALES:
        for seed in range(1, 11):
            static = indexed[(scale, seed, "STATIC_FIXED_RECOURSE")]
            full = indexed[(scale, seed, "FULL_ROLLING")]
            nominal = float(static["nominal_total_cost_cny"])
            static_cost = float(static["final_total_cost_cny"])
            full_cost = float(full["final_total_cost_cny"])
            loss = static_cost - nominal
            output.append(
                {
                    "scale": scale,
                    "instance_id": static["instance_id"],
                    "seed": seed,
                    "stream_seed": static["stream_seed"],
                    "nominal_cost_cny": nominal,
                    "static_actual_cost_cny": static_cost,
                    "full_dynamic_cost_cny": full_cost,
                    "static_degradation_pct":
                        100.0 * loss / nominal,
                    "dynamic_saving_vs_static_pct":
                        100.0 * (static_cost - full_cost) / static_cost,
                    "dynamic_recovery_pct": (
                        100.0 * (static_cost - full_cost) / loss
                        if abs(loss) > TOL
                        else None
                    ),
                }
            )
    return output


def aggregate_table(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["scale"]), str(row["arm"]))].append(row)
    output: list[dict[str, Any]] = []
    for scale in SCALES:
        for arm in ARMS:
            group = grouped[(scale, arm)]
            costs = [float(row["final_total_cost_cny"]) for row in group]
            best = min(costs)
            avg = statistics.fmean(costs)
            output.append(
                {
                    "scale": scale,
                    "instance_id": INSTANCE_BY_SCALE[scale],
                    "arm": arm,
                    "runs": len(group),
                    "Best_cny": best,
                    "Avg_cny": avg,
                    "Gap_pct": 100.0 * (avg - best) / best,
                    "Avg_vehicle_count": statistics.fmean(
                        float(row["vehicle_count"]) for row in group
                    ),
                    "Avg_time_seconds": statistics.fmean(
                        float(row["wall_seconds"]) for row in group
                    ),
                    "Avg_actual_evaluations": statistics.fmean(
                        float(row["actual_evaluations"]) for row in group
                    ),
                    "Max_actual_evaluations": max(
                        int(row["actual_evaluations"]) for row in group
                    ),
                    "cross_reassignment_runs": sum(
                        bool(row["cross_depot_reassignment_after_event"])
                        for row in group
                    ),
                    "profit_shift_runs": sum(
                        bool(row["member_profit_shift_after_event"])
                        for row in group
                    ),
                    "charging_shift_runs": sum(
                        bool(row["carbon_aware_charging_shift_after_event"])
                        for row in group
                    ),
                }
            )
    return output


def write_interim_tables() -> dict[str, Any]:
    tasks = task_results()
    rows = [raw_row(task) for task in tasks]
    atomic_csv(HERE / "raw_runs.csv", rows)
    paired = (
        paired_metrics(rows)
        if len(rows) == len(SCALES) * 10 * len(ARMS)
        else []
    )
    if paired:
        atomic_csv(HERE / "paired_dynamic_metrics.csv", paired)
    table = aggregate_table(rows)
    atomic_csv(HERE / "table_instance_arm.csv", table)
    return {"raw_rows": rows, "paired_rows": paired, "table_rows": table}


def collect_hashes(*, exclude_done: bool = True) -> dict[str, str]:
    excluded = {"artifact_hashes.json"}
    if exclude_done:
        excluded.add("done.json")
    return {
        str(path.relative_to(HERE)): sha256(path)
        for path in sorted(HERE.rglob("*"))
        if is_real_artifact(path) and path.name not in excluded
    }


def render_report(
    table: Sequence[Mapping[str, Any]],
    paired: Sequence[Mapping[str, Any]],
    mechanism: Mapping[str, Any],
) -> str:
    static_mean = statistics.fmean(
        float(row["static_degradation_pct"]) for row in paired
    )
    saving_mean = statistics.fmean(
        float(row["dynamic_saving_vs_static_pct"]) for row in paired
    )
    recoveries = [
        float(row["dynamic_recovery_pct"])
        for row in paired
        if row["dynamic_recovery_pct"] not in {None, ""}
    ]
    recovery_mean = statistics.fmean(recoveries) if recoveries else math.nan
    lines = [
        "# E7 动态需求压力测试",
        "",
        "结论：`COMPLETE`。以下数字来自 3 个冻结算例、每臂每算例 10 次；",
        "原始后见 B1 已按预注册显式替换为因果 `STATIC_FIXED_RECOURSE`，",
        "因此回答的是静态路线政策受扰后的实际代价，而不是终局全知下界。",
        "",
        "## 结果表",
        "",
        "| 规模 | 臂 | Best | Avg | Gap% | 车辆数 | 时间(s) | 实际评价数 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in table:
        lines.append(
            f"| {row['scale']} | {row['arm']} | "
            f"{float(row['Best_cny']):.3f} | "
            f"{float(row['Avg_cny']):.3f} | "
            f"{float(row['Gap_pct']):.3f} | "
            f"{float(row['Avg_vehicle_count']):.2f} | "
            f"{float(row['Avg_time_seconds']):.2f} | "
            f"{float(row['Avg_actual_evaluations']):.1f} |"
        )
    lines.extend(
        [
            "",
            "逐种子等权平均下，静态固定路线受扰后的成本相对扰动前方案变化"
            f" {static_mean:.6f}%；完整滚动相对静态实际成本节省"
            f" {saving_mean:.6f}%，对应挽回静态扰动损失"
            f" {recovery_mean:.6f}%。",
            "",
            "## 三机制参与",
            "",
            f"事件后跨场责任重新分配：`{str(bool(mechanism['cross_depot_reassignment'])).lower()}`；"
            f"发生于 {mechanism['cross_reassignment_cell_count']} 个 FULL_ROLLING 单元。",
            f"成员收益格局变化：`{str(bool(mechanism['member_profit_shift'])).lower()}`；"
            f"发生于 {mechanism['profit_shift_cell_count']} 个 FULL_ROLLING 单元。",
            f"碳感知充电时刻调整：`{str(bool(mechanism['carbon_aware_charging_shift'])).lower()}`；"
            f"发生于 {mechanism['charging_shift_cell_count']} 个 FULL_ROLLING 单元。",
            "",
            "## 全文脉络与正文可用表述",
            "",
            "E3 表明联合配送在当前分区基础上只保留 1.482937% 的等权成本空间，"
            "且伴随里程和碳排上升；E6 表明无转移支付的参与保障使 20/20 单元"
            "全部回退到独立方案，协同收益完全放弃；E4 则表明固定路线的碳感知"
            "充电可使充电排放下降 54.9704%，但电费上升 134.8798%、系统总成本"
            "上升 1.8454%。E7 在不可撤回执行与订单变化下检验这三项结论是否仍"
            "同时进入决策，不能把三个独立复算堆叠成动态机制结论。",
            "",
            "正文建议：在 50c、100c 和 150c 三个冻结压力算例上，每臂运行 10 次。"
            f"订单扰动使固定路线政策的实际成本平均变化 {static_mean:.2f}%，"
            f"严格滚动重规划相对该静态实际方案平均节省 {saving_mean:.2f}%，"
            f"相当于挽回 {recovery_mean:.2f}% 的扰动损失。"
            "协同重分配、成员收益和碳感知充电的事件后参与情况按表中实测记录，"
            "未发生的机制不作有效性主张。",
            "",
            "## 口径与边界",
            "",
            "50c/100c 复用 E3 已封存 JOINT 解；150c 没有当前 E3 封存 JOINT 结果，"
            "只使用 foundation 的冻结 common initial solution，因此 150c 是压力"
            "稳健性证据，不是 E3 的 150c 扩展。STATIC_FIXED_RECOURSE 不运行路线"
            "搜索；其实际评价数低于共同 cap 是结构语义所致，不是漏跑。新增节点"
            "只克隆同实例 donor 的冻结有向道路与 CV/EV profile，未使用欧氏回退。",
            "",
        ]
    )
    return "\n".join(lines)


def finalize() -> dict[str, Any]:
    verify_protected()
    for scale in SCALES:
        marker = HERE / "formal" / scale / "scale_complete.json"
        if not marker.is_file():
            raise RuntimeError(f"HALT_SCALE_INCOMPLETE:{scale}")
    tables = write_interim_tables()
    rows = tables["raw_rows"]
    paired = tables["paired_rows"]
    if len(rows) != 3 * 10 * 4 or len(paired) != 30:
        raise RuntimeError(
            f"HALT_MATRIX_INCOMPLETE:raw={len(rows)} paired={len(paired)}"
        )
    full_rows = [row for row in rows if row["arm"] == "FULL_ROLLING"]
    carbon_rows = {
        (row["scale"], int(row["seed"])): row
        for row in rows
        if row["arm"] == "CARBON_BLIND"
    }
    carbon_pair_improvements = []
    for row in full_rows:
        blind = carbon_rows[(row["scale"], int(row["seed"]))]
        aware_value = row["charging_weighted_carbon_gco2_per_kwh"]
        blind_value = blind["charging_weighted_carbon_gco2_per_kwh"]
        if aware_value is not None and blind_value is not None:
            carbon_pair_improvements.append(
                float(aware_value) < float(blind_value) - TOL
            )
    mechanism = {
        "cross_depot_reassignment": any(
            bool(row["cross_depot_reassignment_after_event"])
            for row in full_rows
        ),
        "member_profit_shift": any(
            bool(row["member_profit_shift_after_event"])
            for row in full_rows
        ),
        "carbon_aware_charging_shift": (
            any(
                bool(row["carbon_aware_charging_shift_after_event"])
                for row in full_rows
            )
            and any(carbon_pair_improvements)
        ),
        "cross_reassignment_cell_count": sum(
            bool(row["cross_depot_reassignment_after_event"])
            for row in full_rows
        ),
        "profit_shift_cell_count": sum(
            bool(row["member_profit_shift_after_event"])
            for row in full_rows
        ),
        "charging_shift_cell_count": sum(
            bool(row["carbon_aware_charging_shift_after_event"])
            for row in full_rows
        ),
        "aware_lower_than_blind_cell_count": sum(carbon_pair_improvements),
    }
    static_degradation = statistics.fmean(
        float(row["static_degradation_pct"]) for row in paired
    )
    dynamic_saving = statistics.fmean(
        float(row["dynamic_saving_vs_static_pct"]) for row in paired
    )
    recoveries = [
        float(row["dynamic_recovery_pct"])
        for row in paired
        if row["dynamic_recovery_pct"] is not None
    ]
    dynamic_recovery = statistics.fmean(recoveries) if recoveries else None
    report_text = render_report(
        tables["table_rows"],
        paired,
        mechanism,
    )
    (HERE / "report.md").write_text(report_text, encoding="utf-8")
    lock = load_budget_lock()
    metadata = {
        "schema": "resetp.china81.e7.metadata.v1",
        "task_id": TASK_ID,
        "status": "COMPLETE",
        "created_at_utc": now_iso(),
        "instances": [INSTANCE_BY_SCALE[scale] for scale in SCALES],
        "arms": list(ARMS),
        "seeds": list(range(1, 11)),
        "event_streams_found": 15,
        "budget_lock": lock,
        "workers_maximum": 2,
        "thread_environment": REQUIRED_THREAD_ENV,
        "python_executable": sys.executable,
        "protected_hashes": verify_protected(),
        "source_hashes": source_hashes(),
        "matrix_rows": len(rows),
        "paired_rows": len(paired),
        "mechanism_participation": mechanism,
    }
    metadata["metadata_sha256"] = canonical_sha256(metadata)
    atomic_json(HERE / "metadata.json", metadata)
    decision = {
        "schema": "resetp.china81.e7.decision.v1",
        "task_id": TASK_ID,
        "status": "COMPLETE",
        "verdict": "VALID_DYNAMIC_PRESSURE_RESULT",
        "static_degradation_pct": static_degradation,
        "dynamic_saving_vs_static_pct": dynamic_saving,
        "dynamic_recovery_pct": dynamic_recovery,
        "mechanism_participation": mechanism,
        "claim_boundary": (
            "150c is stress evidence from a frozen common initial solution, "
            "not a sealed E3 JOINT extension"
        ),
    }
    decision["decision_sha256"] = canonical_sha256(decision)
    atomic_json(HERE / "decision.json", decision)
    hashes = {
        "schema": "resetp.china81.e7.artifact-hashes.v1",
        "task_id": TASK_ID,
        "excluded": [
            "artifact_hashes.json",
            "done.json",
            "._*",
            "__pycache__",
            ".pytest_cache"
        ],
        "files": collect_hashes(),
    }
    hashes["manifest_sha256"] = canonical_sha256(hashes["files"])
    atomic_json(HERE / "artifact_hashes.json", hashes)
    append_progress({"phase": "finalize", "status": "PASS"})
    return {
        "metadata": metadata,
        "decision": decision,
        "artifact_hashes": hashes,
    }


def write_done() -> dict[str, Any]:
    """Write the authoritative completion marker. This must be called last."""

    decision_path = HERE / "decision.json"
    hashes_path = HERE / "artifact_hashes.json"
    if not decision_path.is_file() or not hashes_path.is_file():
        raise RuntimeError("HALT_FINAL_ARTIFACTS_MISSING")
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    lock = load_budget_lock()
    done = {
        "status": "COMPLETE",
        "arms": list(ARMS),
        "event_streams_found": 15,
        "instances_completed": [
            INSTANCE_BY_SCALE[scale] for scale in SCALES
        ],
        "seeds": 10,
        "budget_cap": int(lock["selected_total_stage_cap"]),
        "static_degradation_pct": decision["static_degradation_pct"],
        "dynamic_recovery_pct": decision["dynamic_recovery_pct"],
        "mechanism_participation": {
            "cross_depot_reassignment": bool(
                decision["mechanism_participation"][
                    "cross_depot_reassignment"
                ]
            ),
            "member_profit_shift": bool(
                decision["mechanism_participation"]["member_profit_shift"]
            ),
            "carbon_aware_charging_shift": bool(
                decision["mechanism_participation"][
                    "carbon_aware_charging_shift"
                ]
            ),
        },
        "decision_sha256": sha256(decision_path),
        "artifact_hashes_sha256": sha256(hashes_path),
    }
    done["done_sha256"] = canonical_sha256(done)
    atomic_json(HERE / "done.json", done)
    return done


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    preflight_parser = sub.add_parser("preflight")
    preflight_parser.add_argument("--workers", type=int, default=2)
    sub.add_parser("probe")
    formal_parser = sub.add_parser("formal")
    formal_parser.add_argument("--scale", choices=SCALES, required=True)
    formal_parser.add_argument("--workers", type=int, default=2)
    sub.add_parser("tables")
    sub.add_parser("finalize")
    sub.add_parser("write-done")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "preflight":
        print(json.dumps(preflight(args.workers), ensure_ascii=False, indent=2))
    elif args.command == "probe":
        print(json.dumps(run_probe(), ensure_ascii=False, indent=2))
    elif args.command == "formal":
        print(
            json.dumps(
                run_formal(args.scale, args.workers),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "tables":
        summary = write_interim_tables()
        print(
            json.dumps(
                {key: len(value) for key, value in summary.items()},
                indent=2,
            )
        )
    elif args.command == "finalize":
        output = finalize()
        print(json.dumps(output["decision"], ensure_ascii=False, indent=2))
    elif args.command == "write-done":
        print(json.dumps(write_done(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
