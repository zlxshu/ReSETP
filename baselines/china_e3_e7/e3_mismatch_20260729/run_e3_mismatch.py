#!/usr/bin/env python3
"""E3 responsibility-mismatch experiment with fail-closed gates and evidence.

The workflow is intentionally phase separated:

1. replay D3 only on the current multi-depot applicability domain;
2. freeze deterministic mismatch assignments and common initial solutions;
3. select a non-starved complete-evaluation budget without serialising costs;
4. run the primary exhibit, then the multi-depot stability panel;
5. independently recompute every saved solution and seal the evidence bundle.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import multiprocessing as mp
import os
import platform
import resource
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from time import perf_counter
from types import MappingProxyType
from typing import Any

REPO = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path = [
    entry
    for entry in sys.path
    if Path(entry or ".").resolve() != SCRIPT_DIR
]
for path in (PROTOTYPE, REPO / "solver/src", REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from epochal_hgs import HgsExactEpoch
from pyvrp.solve import SolveParams
from pyvrp_adapter import build_pyvrp_problem
from route_pool_sp import (
    _route_pool_records,
    _solve_set_partitioning,
    run_hgs_route_pool_recombination,
)
from setp_solver.check import check_solution
from setp_solver.china81 import China81Bundle, load_china81_bundle
from setp_solver.china81_completion import (
    China81CompletionResult,
    annotate_cross_site_services,
    complete_china81_route_skeleton,
    exact_china81_score,
)
from setp_solver.cost import evaluate
from setp_solver.solution import (
    ChargingAction,
    Route,
    Solution,
    physical_vehicle_id,
)

from baselines.china_instances.build_china81_finite_fleet_authority_v1_20260723 import (
    _pack_depot,
)

TASK_ID = "E3-RESPONSIBILITY-MISMATCH-01"
MAIN_INSTANCE = "cn-prd-50c-01-V2-LOCATIONS"
MAIN_INTENSITIES = (0, 25, 50)
STABILITY_INTENSITIES = (0, 50)
MAIN_SEEDS = tuple(range(1, 11))
STABILITY_SEEDS = (1, 2, 3)
PILOT_SEEDS = (1, 2, 3)
ARMS = {"LOCK": True, "FREE": False}
VIEW_MODES = ("cv_only", "naive_ev", "mechanism_ev")
MAX_HGS_ITERATIONS_PER_VIEW = 5_000
EXACT_ELITES_PER_VIEW = 8
MIP_TIME_LIMIT_SECONDS = 5.0
INITIAL_BUDGET_TIERS = (32, 56, 80)
UPWARD_BUDGET_STEP = 80
STARVATION_RATIO_THRESHOLD = 0.5
STARVED_UNIT_FRACTION_MAX = 0.20
MAX_WORKERS = 4
DISPLAY_COST_PERCENT_DIGITS = 2
REQUIRED_THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}

STATIC = (
    REPO
    / "data/ChinaInstances/"
    "china81_stage2_static_inputs_corrected_v3_20260723"
)
MATRICES = (
    REPO
    / "data/ChinaInstances/"
    "china81_local_directed_matrices_corrected_v10_20260723"
)
PARAMETERS = (
    REPO
    / "data/ChinaInstances/"
    "china81_runtime_parameter_authority_v4_20260723"
)
GATE1 = (
    REPO
    / "baselines/china_e3_e7/"
    "e3e6_gates_01_20260729/gate1_d2a"
)
APPROVAL = (
    REPO
    / "docs/handoff/model_change_approval_register_20260718.md"
)
PYVRP_ADAPTER = PROTOTYPE / "pyvrp_adapter.py"
EPOCHAL_HGS = PROTOTYPE / "epochal_hgs.py"
ROUTE_POOL_SP = PROTOTYPE / "route_pool_sp.py"
CHINA81 = REPO / "solver/src/setp_solver/china81.py"
CHINA81_COMPLETION = (
    REPO / "solver/src/setp_solver/china81_completion.py"
)
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
)
SOURCE_FILES = (
    Path(__file__).resolve(),
    PYVRP_ADAPTER,
    EPOCHAL_HGS,
    ROUTE_POOL_SP,
    CHINA81,
    CHINA81_COMPLETION,
    *PROTECTED,
)
AUTHORITY_HASH_MANIFESTS = (
    STATIC / "artifact_hashes.json",
    MATRICES / "artifact_hashes.json",
    PARAMETERS / "artifact_hashes.json",
    GATE1 / "artifact_hashes.json",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(REPO.resolve()))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def source_hashes() -> dict[str, str]:
    paths = (*SOURCE_FILES, *AUTHORITY_HASH_MANIFESTS)
    return {relative(path): sha256(path) for path in paths}


def require_thread_lock() -> None:
    mismatches = {
        key: os.environ.get(key)
        for key, value in REQUIRED_THREAD_ENV.items()
        if os.environ.get(key) != value
    }
    if mismatches:
        raise RuntimeError(f"HALT_SINGLE_THREAD_ENVIRONMENT:{mismatches}")


def require_approval() -> None:
    text = APPROVAL.read_text(encoding="utf-8")
    required = (
        "APPROVED_BY_USER_20260728",
        "D2-A",
        "D3-A",
        "D4-A",
        "L/S > 0.5",
    )
    missing = [token for token in required if token not in text]
    if missing:
        raise RuntimeError(f"HALT_APPROVAL_TOKENS_MISSING:{missing}")


def require_source_lock() -> dict[str, str]:
    preregistration = read_json(OUT / "pre_registration.json")
    expected = preregistration["source_hashes"]
    current = source_hashes()
    if current != expected:
        raise RuntimeError("HALT_PROTECTED_OR_RESEARCH_SOURCE_HASH_DRIFT")
    return current


def load_bundle(instance_id: str) -> China81Bundle:
    return load_china81_bundle(
        REPO,
        instance_id,
        static_input_authority=STATIC,
        road_matrix_authority=MATRICES,
        runtime_parameter_authority=PARAMETERS,
        fleet_authority=GATE1,
    )


def with_responsibility(
    bundle: China81Bundle,
    mapping: dict[str, str],
) -> China81Bundle:
    return replace(
        bundle,
        customer_home_depot=MappingProxyType(dict(mapping)),
    )


def solution_payload(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [
            {
                "vehicle_id": route.vehicle_id,
                "vehicle_type": route.vehicle_type,
                "home_depot_id": route.home_depot_id,
                "node_sequence": list(route.node_sequence),
            }
            for route in solution.routes
        ],
        "charging_actions": [
            {
                "vehicle_id": action.vehicle_id,
                "station_id": action.station_id,
                "energy_kwh": float(action.energy_kwh),
                "occupancy_minutes": float(action.occupancy_minutes),
                "charge_start_second": float(
                    action.charge_start_second
                ),
                "charge_day_offset": int(action.charge_day_offset),
                "start_energy_kwh": action.start_energy_kwh,
                "end_energy_kwh": action.end_energy_kwh,
                "charging_curve_id": action.charging_curve_id,
            }
            for action in solution.charging_actions
        ],
        "cross_site_services": [
            {
                "customer_id": service.customer_id,
                "served_by_depot_id": service.served_by_depot_id,
            }
            for service in solution.cross_site_services
        ],
    }


def solution_from_payload(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id=row["vehicle_id"],
                vehicle_type=row["vehicle_type"],
                home_depot_id=row["home_depot_id"],
                node_sequence=list(row["node_sequence"]),
            )
            for row in payload["routes"]
        ],
        charging_actions=[
            ChargingAction(
                vehicle_id=row["vehicle_id"],
                station_id=row["station_id"],
                energy_kwh=float(row["energy_kwh"]),
                occupancy_minutes=float(row["occupancy_minutes"]),
                charge_start_second=float(row["charge_start_second"]),
                charge_day_offset=int(row["charge_day_offset"]),
                start_energy_kwh=row.get("start_energy_kwh"),
                end_energy_kwh=row.get("end_energy_kwh"),
                charging_curve_id=row.get("charging_curve_id"),
            )
            for row in payload.get("charging_actions", [])
        ],
    )


def all_instance_ids() -> list[str]:
    return sorted(row["instance_id"] for row in read_csv(GATE1 / "raw_runs.csv"))


def verify_control_encoding(bundle: China81Bundle, data: Any) -> None:
    depots = list(data.depots())
    depot_index = {
        depot.name: index for index, depot in enumerate(depots)
    }
    if data.num_load_dimensions != 1 + len(depots):
        raise RuntimeError("HALT_D3_SEARCH_SPACE_LOCK_DIMENSIONS")
    for client in data.clients():
        owner = bundle.customer_home_depot[client.name]
        dimensions = list(client.delivery[1:])
        if sum(dimensions) != 1 or dimensions[depot_index[owner]] != 1:
            raise RuntimeError("HALT_D3_SEARCH_SPACE_OWNER_ONE_HOT")
    for vehicle_type in data.vehicle_types():
        home = depots[vehicle_type.start_depot].name
        if vehicle_type.start_depot != vehicle_type.end_depot:
            raise RuntimeError("HALT_D3_SEARCH_SPACE_OPEN_ROUTE")
        for depot_id, index in depot_index.items():
            admitted = vehicle_type.capacity[1 + index] > 0
            if admitted != (depot_id == home):
                raise RuntimeError("HALT_D3_SEARCH_SPACE_VEHICLE_CAPACITY")


def source_guard_evidence() -> dict[str, Any]:
    epochal = EPOCHAL_HGS.read_text(encoding="utf-8")
    pool = ROUTE_POOL_SP.read_text(encoding="utf-8")
    complete_tokens = (
        "problem.hard_home_depot_lock",
        "completion.solution.cross_site_services",
        "common_completion.solution.cross_site_services",
        "proxy_best_completion.solution.cross_site_services",
    )
    pool_tokens = (
        "if hard_home_depot_lock and any(",
        "if hard_home_depot_lock:",
        "bundle.customer_home_depot[customer_id]",
        "record.route.home_depot_id",
    )
    evidence = {
        "search_space_guard_runtime_replayed": True,
        "complete_candidate_guard_tokens": {
            token: token in epochal for token in complete_tokens
        },
        "route_pool_guard_tokens": {
            token: token in pool for token in pool_tokens
        },
        "complete_candidate_guard_pass": all(
            token in epochal for token in complete_tokens
        ),
        "route_pool_guard_pass": all(
            token in pool for token in pool_tokens
        ),
        "final_certificate_guard_behaviorally_replayed": False,
    }
    if not all(
        (
            evidence["complete_candidate_guard_pass"],
            evidence["route_pool_guard_pass"],
        )
    ):
        raise RuntimeError(f"HALT_D3_CURRENT_SOURCE_GUARD:{evidence}")
    return evidence


def enforce_final_certificate_guard(
    *,
    hard_lock: bool,
    solution: Solution,
    context: str,
) -> None:
    if hard_lock and solution.cross_site_services:
        raise RuntimeError(f"HALT_LOCK_FINAL_CERTIFICATE:{context}")


def load_gate1_witness(instance_id: str) -> Solution:
    payload = read_json(GATE1 / "witnesses" / f"{instance_id}.json")
    return solution_from_payload(
        {"routes": payload["routes"], "charging_actions": []}
    )


def write_stage_hashes(stage: Path) -> None:
    artifacts: dict[str, str] = {}
    for path in sorted(stage.rglob("*")):
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
            and "__pycache__" not in path.parts
            and ".pytest_cache" not in path.parts
            and not any(
                part.endswith(".monitor") for part in path.parts
            )
            and not path.name.endswith(".tmp")
        ):
            artifacts[str(path.relative_to(stage))] = sha256(path)
    write_json(
        stage / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": [
                "artifact_hashes.json",
                "._*",
                "__pycache__",
                ".pytest_cache",
                "*.tmp",
                ".monitor",
            ],
            "artifacts": artifacts,
        },
    )


def gate2_replay() -> dict[str, Any]:
    require_approval()
    stage = OUT / "gate2_d3"
    if (stage / "decision.json").is_file():
        decision = read_json(stage / "decision.json")
        if decision.get("verdict") != "PASS_D3_MULTI_DEPOT_CURRENT_SOURCE":
            raise RuntimeError("existing D3 gate is not PASS")
        metadata = read_json(stage / "metadata.json")
        if metadata.get("source_hashes") == source_hashes():
            return decision
    stage.mkdir(parents=True, exist_ok=True)
    guards = source_guard_evidence()
    params = SolveParams()
    eligible_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    replay_rows: list[dict[str, Any]] = []
    for instance_id in all_instance_ids():
        bundle = load_bundle(instance_id)
        depots = sorted(
            node.node_id
            for node in bundle.instance.nodes
            if node.node_type.lower() == "d"
        )
        if len(depots) < 2:
            excluded_rows.append(
                {
                    "instance_id": instance_id,
                    "depot_count": len(depots),
                    "exclusion_reason": (
                        "SINGLE_DEPOT_NO_CROSS_DEPOT_APPLICABILITY"
                    ),
                }
            )
            continue
        eligible_rows.append(
            {"instance_id": instance_id, "depot_count": len(depots)}
        )
        control = build_pyvrp_problem(
            bundle, hard_home_depot_lock=True
        )
        treatment = build_pyvrp_problem(
            bundle, hard_home_depot_lock=False
        )
        control_data = control.model.data()
        treatment_data = treatment.model.data()
        verify_control_encoding(bundle, control_data)
        if treatment_data.num_load_dimensions != 1:
            raise RuntimeError(f"HALT_D3_TREATMENT_LOCK:{instance_id}")
        active = [
            operator.__name__
            for operator in params.node_ops
            if operator.supports(treatment_data)
        ]
        if "Exchange11" not in active:
            raise RuntimeError(f"HALT_D3_EXCHANGE11:{instance_id}")
        witness = annotate_cross_site_services(
            load_gate1_witness(instance_id),
            bundle.customer_home_depot,
        )
        _, _, violations = exact_china81_score(witness, bundle)
        if violations or witness.cross_site_services:
            raise RuntimeError(f"HALT_D3_CONTROL_WITNESS:{instance_id}")
        customer_id = min(bundle.customer_home_depot)
        owner = bundle.customer_home_depot[customer_id]
        wrong_depot = next(item for item in depots if item != owner)
        adversarial = annotate_cross_site_services(
            Solution(
                routes=[
                    Route(
                        vehicle_id="D3-ADVERSARIAL-CV",
                        vehicle_type="cv",
                        home_depot_id=wrong_depot,
                        node_sequence=[
                            wrong_depot,
                            customer_id,
                            wrong_depot,
                        ],
                    )
                ]
            ),
            bundle.customer_home_depot,
        )
        if len(adversarial.cross_site_services) != 1:
            raise RuntimeError(f"HALT_D3_FREE_CONSTRUCT:{instance_id}")
        try:
            enforce_final_certificate_guard(
                hard_lock=True,
                solution=adversarial,
                context=f"D3-PROBE:{instance_id}",
            )
        except RuntimeError as exc:
            if not str(exc).startswith("HALT_LOCK_FINAL_CERTIFICATE:"):
                raise
        else:
            raise RuntimeError(f"HALT_D3_FINAL_GUARD:{instance_id}")
        enforce_final_certificate_guard(
            hard_lock=False,
            solution=adversarial,
            context=f"D3-PROBE:{instance_id}",
        )
        completion = China81CompletionResult(
            solution=adversarial,
            objective=0.0,
            breakdown={},
            activity={"source": "zero_search_adversarial_probe"},
        )
        epoch = HgsExactEpoch(
            elite_skeletons=(),
            elite_completions=(completion,),
            proxy_best_completion=completion,
            elapsed_seconds=0.0,
            stats={},
            archive_completions=(completion,),
            base_archive_completions=(),
        )
        epochs = {"zero_search_probe": epoch}
        locked_records = _route_pool_records(
            bundle, epochs, hard_home_depot_lock=True
        )
        free_records = _route_pool_records(
            bundle, epochs, hard_home_depot_lock=False
        )
        if locked_records or len(free_records) != 1:
            raise RuntimeError(f"HALT_D3_ROUTE_POOL_FILTER:{instance_id}")
        mip_solution, mip_stats = _solve_set_partitioning(
            bundle,
            free_records,
            time_limit_seconds=0.01,
            hard_home_depot_lock=True,
        )
        if (
            mip_solution is not None
            or mip_stats["status_class"] != "NO_COLUMNS"
        ):
            raise RuntimeError(f"HALT_D3_MIP_FILTER:{instance_id}")
        replay_rows.append(
            {
                "instance_id": instance_id,
                "depot_count": len(depots),
                "search_space_hard_lock": "PASS",
                "complete_candidate_guard": "PASS",
                "route_pool_first_filter_locked_records": 0,
                "route_pool_open_free_records": 1,
                "route_pool_mip_second_filter": "PASS_NO_COLUMNS",
                "final_certificate_guard": "PASS",
                "lock_cross_site_service_count": 0,
                "free_constructed_cross_site_service_count": 1,
                "search_evaluations": 0,
                "status": "PASS",
            }
        )
    if len(replay_rows) != 45 or len(excluded_rows) != 36:
        raise RuntimeError(
            "HALT_D3_APPLICABILITY_COUNTS:"
            f"{len(replay_rows)}/{len(excluded_rows)}"
        )
    guards["final_certificate_guard_behaviorally_replayed"] = True
    write_csv(stage / "raw_runs.csv", replay_rows)
    write_csv(stage / "eligible_multi_depot_instances.csv", eligible_rows)
    write_csv(stage / "excluded_single_depot_instances.csv", excluded_rows)
    decision = {
        "schema": "resetp.e3-mismatch.d3-gate.v1",
        "task_id": TASK_ID,
        "verdict": "PASS_D3_MULTI_DEPOT_CURRENT_SOURCE",
        "applicability_domain": "MULTI_DEPOT_ONLY",
        "eligible_multi_depot_instances": len(replay_rows),
        "excluded_single_depot_instances": len(excluded_rows),
        "four_layer_guards": guards,
        "lock_cross_site_zero_all": True,
        "free_cross_site_constructible_all": True,
        "current_source_replay": True,
        "old_pass_reused": False,
        "search_evaluations": 0,
    }
    write_json(stage / "decision.json", decision)
    write_json(
        stage / "metadata.json",
        {
            "schema": "resetp.e3-mismatch.d3-gate.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "python": sys.version,
            "platform": platform.platform(),
            "source_hashes": source_hashes(),
            "worker_count": 1,
            "protected_files_modified": False,
            "search_evaluations": 0,
        },
    )
    excluded_list = "\n".join(
        f"- `{row['instance_id']}`" for row in excluded_rows
    )
    (stage / "report.md").write_text(
        "# 门二 D3：多车场适用域当前源码重放\n\n"
        "**结论：PASS_D3_MULTI_DEPOT_CURRENT_SOURCE。** "
        "本次按用户更正只在 45 个多车场实例上重放，未复用旧 PASS。"
        "搜索空间硬锁、完整候选守卫、路线池初筛与 MIP 二次过滤、"
        "最终证书守卫四层均通过；LOCK 为 0 跨场，FREE 在每个适用"
        "实例均可构造跨场服务。当前源码哈希见 `metadata.json`。\n\n"
        "36 个单车场实例不含跨场拓扑，按适用域排除，不计作失败：\n\n"
        f"{excluded_list}\n",
        encoding="utf-8",
    )
    write_stage_hashes(stage)
    return decision


def allocation_counts(
    original: dict[str, str],
    target: int,
) -> dict[str, int]:
    depots = sorted(set(original.values()))
    counts = {
        depot: sum(owner == depot for owner in original.values())
        for depot in depots
    }
    exact = {
        depot: Decimal(target) * Decimal(counts[depot]) / Decimal(
            len(original)
        )
        for depot in depots
    }
    allocated = {
        depot: int(exact[depot])
        for depot in depots
    }
    remaining = target - sum(allocated.values())
    order = sorted(
        depots,
        key=lambda depot: (
            -(exact[depot] - Decimal(allocated[depot])),
            depot,
        ),
    )
    for depot in order[:remaining]:
        allocated[depot] += 1
    return allocated


def mismatch_mapping(
    bundle: China81Bundle,
    intensity: int,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    original = dict(bundle.customer_home_depot)
    depots = sorted(set(original.values()))
    if len(depots) != 2:
        raise RuntimeError("mismatch experiment requires exactly two depots")
    target = int(
        (
            Decimal(len(original))
            * Decimal(intensity)
            / Decimal(100)
        ).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    )
    allocations = allocation_counts(original, target)
    mapping = dict(original)
    rows: list[dict[str, Any]] = []
    selected: set[str] = set()
    for depot in depots:
        candidates = sorted(
            (
                customer_id
                for customer_id, owner in original.items()
                if owner == depot
            ),
            key=lambda customer_id: hashlib.sha256(
                (
                    f"{TASK_ID}|{bundle.instance_id}|"
                    f"{intensity}|{depot}|{customer_id}"
                ).encode()
            ).hexdigest(),
        )
        selected.update(candidates[: allocations[depot]])
    for customer_id in sorted(original):
        owner = original[customer_id]
        rank_hash = hashlib.sha256(
            (
                f"{TASK_ID}|{bundle.instance_id}|"
                f"{intensity}|{owner}|{customer_id}"
            ).encode()
        ).hexdigest()
        reassigned = customer_id in selected
        assigned = (
            next(depot for depot in depots if depot != owner)
            if reassigned
            else owner
        )
        mapping[customer_id] = assigned
        rows.append(
            {
                "instance_id": bundle.instance_id,
                "mismatch_intensity_nominal_pct": intensity,
                "customer_id": customer_id,
                "original_nearest_registered_depot": owner,
                "assigned_responsibility_depot": assigned,
                "reassigned": reassigned,
                "result_blind_rank_sha256": rank_hash,
            }
        )
    if sum(mapping[key] != original[key] for key in original) != target:
        raise RuntimeError("mismatch allocation target not met")
    return mapping, rows


def build_common_initial(
    bundle: China81Bundle,
) -> tuple[Solution, dict[str, Any]]:
    routes: list[Route] = []
    route_counts: dict[str, int] = {}
    for depot_id in sorted(set(bundle.customer_home_depot.values())):
        packed = _pack_depot(bundle, depot_id)
        route_counts[depot_id] = len(packed)
        caps = bundle.fleet_caps_by_depot[depot_id]
        total_cap = int(caps["num_cv"]) + int(caps["num_ev"])
        if len(packed) > total_cap:
            raise RuntimeError(
                "HALT_MISMATCH_COMMON_INITIAL_EXCEEDS_D2A_TOTAL_CAP:"
                f"{bundle.instance_id}:{depot_id}:"
                f"{len(packed)}>{total_cap}"
            )
        for index, customers in enumerate(packed, start=1):
            routes.append(
                Route(
                    vehicle_id=f"INIT-{depot_id}-CV-{index:03d}",
                    vehicle_type="cv",
                    home_depot_id=depot_id,
                    node_sequence=[
                        depot_id,
                        *customers,
                        depot_id,
                    ],
                )
            )
    completion = complete_china81_route_skeleton(
        Solution(routes=routes),
        bundle,
    )
    solution = completion.solution
    objective, breakdown, violations = exact_china81_score(
        solution, bundle
    )
    independent_violations = check_solution(
        solution, bundle.instance, bundle.prices
    )
    independent = evaluate(
        solution,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    if violations or independent_violations or solution.cross_site_services:
        raise RuntimeError(
            "HALT_MISMATCH_COMMON_INITIAL_INFEASIBLE:"
            f"{bundle.instance_id}:{len(violations)}:"
            f"{len(independent_violations)}"
        )
    if not math.isclose(
        float(independent["total_cost"]),
        float(objective),
        rel_tol=1e-12,
        abs_tol=1e-9,
    ):
        raise RuntimeError("HALT_COMMON_INITIAL_OBJECTIVE_MISMATCH")
    return solution, {
        "objective_for_integrity_only": float(objective),
        "breakdown_for_integrity_only": breakdown,
        "route_counts_by_depot": route_counts,
        "completion_activity": completion.activity,
        "violation_count": 0,
        "cross_site_service_count": 0,
    }


def input_key(instance_id: str, intensity: int) -> str:
    return f"{instance_id}__mismatch{intensity:02d}"


def input_dir(instance_id: str, intensity: int) -> Path:
    return OUT / "inputs" / input_key(instance_id, intensity)


def build_preregistration() -> dict[str, Any]:
    gate = gate2_replay()
    if gate["verdict"] != "PASS_D3_MULTI_DEPOT_CURRENT_SOURCE":
        raise RuntimeError("HALT_UPSTREAM_GATE2")
    prereg_path = OUT / "pre_registration.json"
    if prereg_path.is_file():
        require_source_lock()
        return read_json(prereg_path)
    eligible = [
        row["instance_id"]
        for row in read_csv(
            OUT / "gate2_d3/eligible_multi_depot_instances.csv"
        )
    ]
    if MAIN_INSTANCE not in eligible:
        raise RuntimeError("main exhibit is not in multi-depot domain")
    assignment_rows: list[dict[str, Any]] = []
    input_rows: list[dict[str, Any]] = []
    for instance_id in eligible:
        intensities = (
            MAIN_INTENSITIES
            if instance_id == MAIN_INSTANCE
            else STABILITY_INTENSITIES
        )
        base = load_bundle(instance_id)
        for intensity in intensities:
            mapping, rows = mismatch_mapping(base, intensity)
            assignment_rows.extend(rows)
            bundle = with_responsibility(base, mapping)
            initial, audit = build_common_initial(bundle)
            folder = input_dir(instance_id, intensity)
            folder.mkdir(parents=True, exist_ok=True)
            responsibility_payload = {
                "schema": "resetp.e3-mismatch.responsibility-map.v1",
                "task_id": TASK_ID,
                "instance_id": instance_id,
                "mismatch_intensity_nominal_pct": intensity,
                "mapping": mapping,
                "mapping_sha256": canonical_sha256(mapping),
                "selection_rule": (
                    "within each original registered nearest-depot stratum, "
                    "rank customers by SHA-256 of the frozen task/instance/"
                    "intensity/depot/customer key; allocate the globally "
                    "rounded target proportionally by largest remainder and "
                    "assign selected customers to the only other depot"
                ),
            }
            initial_payload = solution_payload(initial)
            write_json(folder / "responsibility_map.json", responsibility_payload)
            write_json(folder / "initial_solution.json", initial_payload)
            write_json(
                folder / "input_certificate.json",
                {
                    "schema": "resetp.e3-mismatch.input-certificate.v1",
                    "responsibility_map_sha256": canonical_sha256(
                        responsibility_payload
                    ),
                    "initial_solution_sha256": canonical_sha256(
                        initial_payload
                    ),
                    "independent_initial_audit": audit,
                    "shared_by_all_seeds_and_both_arms": True,
                },
            )
            input_rows.append(
                {
                    "instance_id": instance_id,
                    "mismatch_intensity_nominal_pct": intensity,
                    "reassigned_customer_count": sum(
                        row["reassigned"] for row in rows
                    ),
                    "customer_count": len(rows),
                    "actual_reassigned_pct": (
                        100.0
                        * sum(row["reassigned"] for row in rows)
                        / len(rows)
                    ),
                    "responsibility_map_sha256": canonical_sha256(
                        responsibility_payload
                    ),
                    "initial_solution_sha256": canonical_sha256(
                        initial_payload
                    ),
                    "initial_violation_count": 0,
                    "status": "PASS",
                }
            )
    write_csv(OUT / "mismatch_assignment.csv", assignment_rows)
    write_csv(OUT / "input_manifest.csv", input_rows)
    assignment_sha = sha256(OUT / "mismatch_assignment.csv")
    write_json(
        OUT / "mismatch_assignment_hash_lock.json",
        {
            "schema": "resetp.e3-mismatch.assignment-lock.v1",
            "sha256": assignment_sha,
            "rows": len(assignment_rows),
            "generated_before_pilot_or_formal_results": True,
            "shared_by_all_seeds": True,
            "result_dependent_adjustment_forbidden": True,
        },
    )
    task_specs: dict[str, dict[str, Any]] = {}
    for intensity in MAIN_INTENSITIES:
        for seed in MAIN_SEEDS:
            for arm in ARMS:
                key = (
                    f"{MAIN_INSTANCE}__m{intensity:02d}__"
                    f"seed{seed:02d}__{arm}"
                )
                task_specs[key] = {
                    "task_id": key,
                    "instance_id": MAIN_INSTANCE,
                    "mismatch_intensity_nominal_pct": intensity,
                    "seed": seed,
                    "arm": arm,
                    "primary_exhibit": True,
                    "stability_panel": (
                        intensity in STABILITY_INTENSITIES
                        and seed in STABILITY_SEEDS
                    ),
                }
    for instance_id in eligible:
        for intensity in STABILITY_INTENSITIES:
            for seed in STABILITY_SEEDS:
                for arm in ARMS:
                    key = (
                        f"{instance_id}__m{intensity:02d}__"
                        f"seed{seed:02d}__{arm}"
                    )
                    if key not in task_specs:
                        task_specs[key] = {
                            "task_id": key,
                            "instance_id": instance_id,
                            "mismatch_intensity_nominal_pct": intensity,
                            "seed": seed,
                            "arm": arm,
                            "primary_exhibit": False,
                            "stability_panel": True,
                        }
    task_rows = sorted(task_specs.values(), key=lambda row: row["task_id"])
    write_csv(OUT / "task_manifest.csv", task_rows)
    preregistration = {
        "schema": "resetp.e3-mismatch.preregistration.v1",
        "task_id": TASK_ID,
        "registered_at_utc": datetime.now(UTC).isoformat(),
        "registered_before_pilot_and_formal_cost_results": True,
        "supersedes_for_this_task": (
            "81-instance E3 design in "
            "e3_result_release_preregistration_v1_20260724.json"
        ),
        "primary_exhibit": {
            "instance_id": MAIN_INSTANCE,
            "description": "Pearl River Delta 50 customers, Guangzhou and Shenzhen depots",
            "mismatch_intensities_nominal_pct": list(MAIN_INTENSITIES),
            "seeds": list(MAIN_SEEDS),
        },
        "stability_panel": {
            "eligible_multi_depot_instances": len(eligible),
            "mismatch_intensities_nominal_pct": list(
                STABILITY_INTENSITIES
            ),
            "seeds": list(STABILITY_SEEDS),
            "reporting": "direction consistency only",
        },
        "arms": {
            "LOCK": "hard lock to the frozen responsibility map",
            "FREE": "reciprocal cross-depot service permitted",
        },
        "paired_controls": [
            "same instance",
            "same mismatch responsibility map",
            "same initial solution",
            "same seed",
            "same selected complete-candidate evaluation budget",
            "single-thread task",
            "wallclock only as a safety fuse",
        ],
        "budget_pilot": {
            "result_blind": True,
            "pilot_instance": MAIN_INSTANCE,
            "intensities": list(MAIN_INTENSITIES),
            "seeds": list(PILOT_SEEDS),
            "initial_tiers_ascending": list(INITIAL_BUDGET_TIERS),
            "if_all_fail": "160, 240, ... in increments of 80",
            "last_improvement_fraction_starved_if_gt": (
                STARVATION_RATIO_THRESHOLD
            ),
            "arm_starved_if_unit_fraction_gt": (
                STARVED_UNIT_FRACTION_MAX
            ),
            "selection": (
                "smallest tier passing both arms; if arm-specific minima "
                "differ, use the larger"
            ),
            "arm_cost_differences_visible_to_selector": False,
        },
        "endpoints": {
            "primary": "FREE relative to LOCK total cost percent",
            "secondary": [
                "cross-depot served-customer count",
                "service completion rate",
                "total emissions",
                "minimum physical vehicle count",
            ],
        },
        "result_blind_writing": {
            "positive": "report effect size and mismatch-level trend",
            "near_zero": (
                "state that cross-depot cooperation adds no benefit within "
                "the observed mismatch-intensity interval"
            ),
            "negative": "report honestly and analyse the trade-off",
            "near_zero_definition": (
                "primary paired percent difference rounds to 0.00 at the "
                "pre-registered display precision and feasibility/service "
                "does not worsen"
            ),
            "no_p_values": True,
        },
        "mismatch_assignment_csv_sha256": assignment_sha,
        "source_hashes": source_hashes(),
        "protected_files": [relative(path) for path in PROTECTED],
        "formal_unique_task_count": len(task_rows),
        "max_workers": MAX_WORKERS,
    }
    write_json(prereg_path, preregistration)
    return preregistration


def budget_configuration(
    budget: int,
) -> tuple[int, dict[str, int | None]]:
    if budget in INITIAL_BUDGET_TIERS:
        archive_limit = {32: 8, 56: 16, 80: 24}[budget]
        return archive_limit, {mode: None for mode in VIEW_MODES}
    if budget < 160 or budget % UPWARD_BUDGET_STEP != 0:
        raise ValueError(f"unsupported preregistered budget tier: {budget}")
    extra = budget - 80
    base, remainder = divmod(extra, len(VIEW_MODES))
    checkpoint_counts = {
        mode: base + (index < remainder)
        for index, mode in enumerate(VIEW_MODES)
    }
    intervals: dict[str, int | None] = {}
    for mode, count in checkpoint_counts.items():
        if count == 0:
            intervals[mode] = None
            continue
        if count > MAX_HGS_ITERATIONS_PER_VIEW:
            raise RuntimeError("HALT_UPWARD_BUDGET_EXCEEDS_HGS_TRACE")
        interval = MAX_HGS_ITERATIONS_PER_VIEW // count
        if MAX_HGS_ITERATIONS_PER_VIEW // interval != count:
            raise RuntimeError("cannot represent exact checkpoint count")
        intervals[mode] = interval
    expected = 80 + sum(
        0
        if interval is None
        else MAX_HGS_ITERATIONS_PER_VIEW // interval
        for interval in intervals.values()
    )
    if expected != budget:
        raise RuntimeError(f"budget configuration mismatch: {expected}")
    return 24, intervals


def load_frozen_input(
    instance_id: str,
    intensity: int,
) -> tuple[China81Bundle, Solution, dict[str, Any]]:
    folder = input_dir(instance_id, intensity)
    responsibility = read_json(folder / "responsibility_map.json")
    initial_payload = read_json(folder / "initial_solution.json")
    certificate = read_json(folder / "input_certificate.json")
    if canonical_sha256(responsibility) != certificate[
        "responsibility_map_sha256"
    ]:
        raise RuntimeError("HALT_RESPONSIBILITY_INPUT_HASH_DRIFT")
    if canonical_sha256(initial_payload) != certificate[
        "initial_solution_sha256"
    ]:
        raise RuntimeError("HALT_INITIAL_INPUT_HASH_DRIFT")
    base = load_bundle(instance_id)
    bundle = with_responsibility(base, responsibility["mapping"])
    initial = solution_from_payload(initial_payload)
    return bundle, initial, certificate


def run_search(
    bundle: China81Bundle,
    initial: Solution,
    *,
    seed: int,
    hard_lock: bool,
    budget: int,
) -> tuple[Any, float, float, float]:
    archive_limit, checkpoint_intervals = budget_configuration(budget)
    customer_count = len(bundle.customer_home_depot)
    safety_seconds = max(180.0, 2.0 * customer_count)
    before = resource.getrusage(resource.RUSAGE_SELF)
    started = perf_counter()
    run = run_hgs_route_pool_recombination(
        bundle,
        initial,
        seed=seed,
        hgs_seconds_per_view=None,
        exact_elites_per_view=EXACT_ELITES_PER_VIEW,
        max_archive_candidates_per_view=archive_limit,
        sp_time_limit_seconds=MIP_TIME_LIMIT_SECONDS,
        hard_home_depot_lock=hard_lock,
        max_hgs_iterations_per_view=MAX_HGS_ITERATIONS_PER_VIEW,
        wallclock_safety_seconds_per_view=safety_seconds,
        exact_checkpoint_interval_iterations=checkpoint_intervals,
    )
    wall = perf_counter() - started
    after = resource.getrusage(resource.RUSAGE_SELF)
    cpu_user = after.ru_utime - before.ru_utime
    cpu_system = after.ru_stime - before.ru_stime
    if run.stats["wallclock_safety_triggered"]:
        raise RuntimeError("HALT_WALLCLOCK_SAFETY_FUSE")
    if (
        run.stats["complete_candidate_evaluation_attempts"] != budget
        or not run.stats["complete_candidate_budget_exactly_consumed"]
    ):
        raise RuntimeError("HALT_COMPLETE_CANDIDATE_BUDGET_MISMATCH")
    return run, wall, cpu_user, cpu_system


def pilot_task(args: tuple[int, int, str, int]) -> dict[str, Any]:
    budget, intensity, arm, seed = args
    require_thread_lock()
    require_source_lock()
    bundle, initial, certificate = load_frozen_input(
        MAIN_INSTANCE, intensity
    )
    run, wall, cpu_user, cpu_system = run_search(
        bundle,
        initial,
        seed=seed,
        hard_lock=ARMS[arm],
        budget=budget,
    )
    last = int(run.stats["last_strict_improvement_evaluation"])
    total = int(run.stats["complete_candidate_evaluation_attempts"])
    fraction = last / total
    return {
        "record_type": "result_blind_budget_pilot",
        "budget": budget,
        "instance_id": MAIN_INSTANCE,
        "mismatch_intensity_nominal_pct": intensity,
        "seed": seed,
        "arm": arm,
        "last_strict_improvement_evaluation_L": last,
        "total_complete_evaluations_S": total,
        "last_improvement_fraction_L_over_S": fraction,
        "starved_L_over_S_gt_0_5": (
            fraction > STARVATION_RATIO_THRESHOLD
        ),
        "wallclock_seconds": wall,
        "cpu_user_seconds": cpu_user,
        "cpu_system_seconds": cpu_system,
        "cpu_total_seconds": cpu_user + cpu_system,
        "initial_solution_sha256": certificate[
            "initial_solution_sha256"
        ],
        "objective_values_recorded": False,
        "arm_cost_difference_computed": False,
        "status": "PASS",
    }


def run_pilot(workers: int) -> dict[str, Any]:
    build_preregistration()
    require_thread_lock()
    require_source_lock()
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError("pilot workers must be between 1 and 4")
    stage = OUT / "pilot"
    stage.mkdir(parents=True, exist_ok=True)
    decision_path = stage / "decision.json"
    if decision_path.is_file():
        decision = read_json(decision_path)
        if decision.get("verdict") != "PASS_RESULT_BLIND_NON_STARVED_BUDGET":
            raise RuntimeError("existing pilot is not PASS")
        return decision
    rows: list[dict[str, Any]] = []
    budget = INITIAL_BUDGET_TIERS[0]
    while True:
        tasks = [
            (budget, intensity, arm, seed)
            for intensity in MAIN_INTENSITIES
            for seed in PILOT_SEEDS
            for arm in ARMS
        ]
        context = mp.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
        ) as executor:
            futures = {
                executor.submit(pilot_task, task): task for task in tasks
            }
            tier_rows = [
                future.result() for future in as_completed(futures)
            ]
        tier_rows.sort(
            key=lambda row: (
                row["mismatch_intensity_nominal_pct"],
                row["seed"],
                row["arm"],
            )
        )
        rows.extend(tier_rows)
        write_csv(stage / "raw_runs.csv", rows)
        arm_summary: dict[str, Any] = {}
        for arm in ARMS:
            selected = [row for row in tier_rows if row["arm"] == arm]
            starved = sum(
                bool(row["starved_L_over_S_gt_0_5"])
                for row in selected
            )
            arm_summary[arm] = {
                "units": len(selected),
                "starved_units": starved,
                "starved_fraction": starved / len(selected),
                "passes": (
                    starved / len(selected)
                    <= STARVED_UNIT_FRACTION_MAX
                ),
            }
        write_json(
            stage / "progress.json",
            {
                "latest_budget": budget,
                "arm_summary": arm_summary,
                "objective_values_recorded": False,
                "arm_cost_difference_computed": False,
            },
        )
        if all(summary["passes"] for summary in arm_summary.values()):
            break
        if budget < 80:
            budget = {32: 56, 56: 80}[budget]
        else:
            budget += UPWARD_BUDGET_STEP
    decision = {
        "schema": "resetp.e3-mismatch.pilot.decision.v1",
        "verdict": "PASS_RESULT_BLIND_NON_STARVED_BUDGET",
        "selected_complete_candidate_budget": budget,
        "selected_arm_summary": arm_summary,
        "tiers_run": sorted({int(row["budget"]) for row in rows}),
        "selection_used_only": [
            "L",
            "S",
            "L/S",
            "wallclock safety state",
            "task completion state",
        ],
        "objective_values_recorded": False,
        "arm_cost_difference_computed": False,
        "same_budget_for_both_arms": True,
    }
    write_json(decision_path, decision)
    write_json(
        stage / "metadata.json",
        {
            "schema": "resetp.e3-mismatch.pilot.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "python": sys.version,
            "platform": platform.platform(),
            "worker_count": workers,
            "single_thread_per_task": True,
            "source_hashes": source_hashes(),
        },
    )
    (stage / "report.md").write_text(
        "# E3 结果盲防饥饿 pilot\n\n"
        f"预算选择结果为 {budget} 次完整候选评价。选择器只读取 L、S、"
        "L/S、墙钟熔断和完成状态；未序列化目标值，未计算任何臂间成本"
        "差异。逐档逐臂判据见 `raw_runs.csv` 和 `decision.json`。\n",
        encoding="utf-8",
    )
    write_json(
        stage / "done.json",
        {
            "status": "complete",
            "verdict": decision["verdict"],
            "selected_budget": budget,
        },
    )
    write_stage_hashes(stage)
    return decision


def formal_task(args: dict[str, Any]) -> dict[str, Any]:
    require_thread_lock()
    hashes = require_source_lock()
    pilot = read_json(OUT / "pilot/decision.json")
    budget = int(pilot["selected_complete_candidate_budget"])
    task_id = args["task_id"]
    task_dir = OUT / "tasks" / task_id
    decision_path = task_dir / "decision.json"
    if decision_path.is_file():
        decision = read_json(decision_path)
        if decision.get("verdict") != "PASS_E3_MISMATCH_TASK":
            raise RuntimeError(f"existing task is not PASS: {task_id}")
        if read_json(task_dir / "metadata.json")["source_hashes"] != hashes:
            raise RuntimeError(f"HALT_TASK_SOURCE_DRIFT:{task_id}")
        return decision["raw_row"]
    bundle, initial, input_certificate = load_frozen_input(
        args["instance_id"],
        int(args["mismatch_intensity_nominal_pct"]),
    )
    hard_lock = ARMS[args["arm"]]
    run, wall, cpu_user, cpu_system = run_search(
        bundle,
        initial,
        seed=int(args["seed"]),
        hard_lock=hard_lock,
        budget=budget,
    )
    solution = annotate_cross_site_services(
        run.solution,
        bundle.customer_home_depot,
    )
    objective, breakdown, violations = exact_china81_score(
        solution, bundle
    )
    independent_violations = check_solution(
        solution, bundle.instance, bundle.prices
    )
    independent = evaluate(
        solution,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    if violations or independent_violations:
        raise RuntimeError(f"HALT_FORMAL_INFEASIBLE:{task_id}")
    if not math.isclose(
        float(independent["total_cost"]),
        float(objective),
        rel_tol=1e-12,
        abs_tol=1e-9,
    ):
        raise RuntimeError(f"HALT_FORMAL_OBJECTIVE_MISMATCH:{task_id}")
    enforce_final_certificate_guard(
        hard_lock=hard_lock,
        solution=solution,
        context=task_id,
    )
    customer_ids = set(bundle.customer_home_depot)
    served = [
        node_id
        for route in solution.routes
        for node_id in route.node_sequence
        if node_id in customer_ids
    ]
    if len(served) != len(customer_ids) or set(served) != customer_ids:
        raise RuntimeError(f"HALT_SERVICE_COMPLETION:{task_id}")
    physical_vehicle_count = len(
        {
            physical_vehicle_id(route.vehicle_id)
            for route in solution.routes
        }
    )
    solution_data = solution_payload(solution)
    independent_payload = {
        "objective": float(independent["total_cost"]),
        "breakdown": independent,
        "violation_count": len(independent_violations),
        "served_customer_count": len(served),
        "unique_served_customer_count": len(set(served)),
    }
    row = {
        "record_type": "formal_run",
        "task_id": task_id,
        "instance_id": args["instance_id"],
        "region": bundle.region,
        "customer_count": len(customer_ids),
        "mismatch_intensity_nominal_pct": int(
            args["mismatch_intensity_nominal_pct"]
        ),
        "seed": int(args["seed"]),
        "arm": args["arm"],
        "hard_home_depot_lock": hard_lock,
        "primary_exhibit": bool(args["primary_exhibit"]),
        "stability_panel": bool(args["stability_panel"]),
        "complete_candidate_budget": budget,
        "complete_candidate_attempts": int(
            run.stats["complete_candidate_evaluation_attempts"]
        ),
        "last_strict_improvement_evaluation_L": int(
            run.stats["last_strict_improvement_evaluation"]
        ),
        "total_complete_evaluations_S": int(
            run.stats["complete_candidate_evaluation_attempts"]
        ),
        "last_improvement_fraction_L_over_S": float(
            run.stats["last_strict_improvement_fraction"]
        ),
        "wallclock_seconds": wall,
        "cpu_user_seconds": cpu_user,
        "cpu_system_seconds": cpu_system,
        "cpu_total_seconds": cpu_user + cpu_system,
        "total_cost": float(objective),
        "cross_site_service_count": len(solution.cross_site_services),
        "service_completion_rate_pct": 100.0,
        "total_emissions_kg": float(breakdown["E_total"]),
        "minimum_physical_vehicle_count": physical_vehicle_count,
        "route_count": len(solution.routes),
        "violation_count": 0,
        "initial_solution_sha256": input_certificate[
            "initial_solution_sha256"
        ],
        "responsibility_map_sha256": input_certificate[
            "responsibility_map_sha256"
        ],
        "solution_sha256": canonical_sha256(solution_data),
        "independent_recompute_sha256": canonical_sha256(
            independent_payload
        ),
        "source_hash": canonical_sha256(hashes),
        "status": "PASS",
    }
    certificate = {
        "schema": "resetp.e3-mismatch.task-certificate.v1",
        "task_id": task_id,
        "source_hashes": hashes,
        "input_certificate": input_certificate,
        "run_stats": run.stats,
        "independent_recompute": independent_payload,
        "raw_row": row,
    }
    task_dir.mkdir(parents=True, exist_ok=False)
    write_json(task_dir / "solution_witness.json", solution_data)
    write_json(task_dir / "certificate.json", certificate)
    write_csv(task_dir / "raw_runs.csv", [row])
    write_json(
        task_dir / "metadata.json",
        {
            "schema": "resetp.e3-mismatch.task-metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "python": sys.version,
            "platform": platform.platform(),
            "source_hashes": hashes,
            "single_thread": True,
        },
    )
    decision = {
        "schema": "resetp.e3-mismatch.task-decision.v1",
        "verdict": "PASS_E3_MISMATCH_TASK",
        "raw_row": row,
    }
    write_json(decision_path, decision)
    write_stage_hashes(task_dir)
    return row


def completed_formal_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    tasks_root = OUT / "tasks"
    if not tasks_root.is_dir():
        return rows
    for path in sorted(tasks_root.glob("*/decision.json")):
        decision = read_json(path)
        if decision.get("verdict") != "PASS_E3_MISMATCH_TASK":
            raise RuntimeError(f"non-PASS task found: {path.parent.name}")
        rows.append(decision["raw_row"])
    return rows


def run_formal(workers: int) -> None:
    build_preregistration()
    run_pilot(workers)
    require_thread_lock()
    require_source_lock()
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError("formal workers must be between 1 and 4")
    task_rows = read_csv(OUT / "task_manifest.csv")
    for row in task_rows:
        row["mismatch_intensity_nominal_pct"] = int(
            row["mismatch_intensity_nominal_pct"]
        )
        row["seed"] = int(row["seed"])
        row["primary_exhibit"] = row["primary_exhibit"] == "True"
        row["stability_panel"] = row["stability_panel"] == "True"
    existing = {
        row["task_id"]: row for row in completed_formal_rows()
    }
    pending = [row for row in task_rows if row["task_id"] not in existing]
    total = len(task_rows)
    write_json(
        OUT / "progress.json",
        {
            "status": "RUNNING",
            "completed_unique_tasks": len(existing),
            "total_unique_tasks": total,
            "remaining_unique_tasks": len(pending),
            "phase": "primary_exhibit_first",
        },
    )
    phases = (
        (
            "primary_exhibit",
            sorted(
                (
                    row
                    for row in pending
                    if bool(row["primary_exhibit"])
                ),
                key=lambda row: row["task_id"],
            ),
        ),
        (
            "multi_depot_stability",
            sorted(
                (
                    row
                    for row in pending
                    if not bool(row["primary_exhibit"])
                ),
                key=lambda row: row["task_id"],
            ),
        ),
    )
    context = mp.get_context("spawn")
    for phase, phase_rows in phases:
        if not phase_rows:
            continue
        if phase == "multi_depot_stability":
            main_complete = sum(
                bool(item["primary_exhibit"])
                for item in existing.values()
            )
            if main_complete != 60:
                raise RuntimeError(
                    "HALT_STABILITY_BEFORE_PRIMARY_EXHIBIT_COMPLETE"
                )
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
        ) as executor:
            futures = {
                executor.submit(formal_task, row): row
                for row in phase_rows
            }
            for future in as_completed(futures):
                row = future.result()
                existing[row["task_id"]] = row
                current = sorted(
                    existing.values(),
                    key=lambda item: item["task_id"],
                )
                write_csv(OUT / "raw_runs.csv", current)
                complete = len(current)
                main_complete = sum(
                    bool(item["primary_exhibit"])
                    for item in current
                )
                write_json(
                    OUT / "progress.json",
                    {
                        "status": "RUNNING",
                        "completed_unique_tasks": complete,
                        "total_unique_tasks": total,
                        "remaining_unique_tasks": total - complete,
                        "primary_exhibit_completed": main_complete,
                        "primary_exhibit_total": 60,
                        "phase": phase,
                    },
                )
    finalize()


def classify_effect(value: float) -> str:
    displayed = round(value, DISPLAY_COST_PERCENT_DIGITS)
    if displayed > 0:
        return "POSITIVE"
    if displayed < 0:
        return "NEGATIVE"
    return "NEAR_ZERO"


def pair_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int, int], dict[str, dict[str, Any]]] = {}
    for row in rows:
        key = (
            row["instance_id"],
            int(row["mismatch_intensity_nominal_pct"]),
            int(row["seed"]),
        )
        grouped.setdefault(key, {})[row["arm"]] = row
    paired: list[dict[str, Any]] = []
    for (instance_id, intensity, seed), arms in sorted(grouped.items()):
        if set(arms) != set(ARMS):
            raise RuntimeError(f"HALT_MISSING_PAIR:{instance_id}:{seed}")
        lock = arms["LOCK"]
        free = arms["FREE"]
        relative = (
            100.0
            * (float(free["total_cost"]) - float(lock["total_cost"]))
            / float(lock["total_cost"])
        )
        reduction = -relative
        paired.append(
            {
                "instance_id": instance_id,
                "region": lock["region"],
                "customer_count": int(lock["customer_count"]),
                "mismatch_intensity_nominal_pct": intensity,
                "seed": seed,
                "primary_exhibit": bool(lock["primary_exhibit"]),
                "stability_panel": bool(lock["stability_panel"]),
                "lock_total_cost": float(lock["total_cost"]),
                "free_total_cost": float(free["total_cost"]),
                "free_relative_to_lock_cost_pct": relative,
                "cost_reduction_pct_positive_is_benefit": reduction,
                "effect_direction": classify_effect(reduction),
                "lock_cross_site_service_count": int(
                    lock["cross_site_service_count"]
                ),
                "free_cross_site_service_count": int(
                    free["cross_site_service_count"]
                ),
                "lock_service_completion_rate_pct": float(
                    lock["service_completion_rate_pct"]
                ),
                "free_service_completion_rate_pct": float(
                    free["service_completion_rate_pct"]
                ),
                "lock_total_emissions_kg": float(
                    lock["total_emissions_kg"]
                ),
                "free_total_emissions_kg": float(
                    free["total_emissions_kg"]
                ),
                "lock_minimum_physical_vehicle_count": int(
                    lock["minimum_physical_vehicle_count"]
                ),
                "free_minimum_physical_vehicle_count": int(
                    free["minimum_physical_vehicle_count"]
                ),
                "status": "PASS",
            }
        )
    return paired


def mean(values: list[float]) -> float:
    if not values:
        raise ValueError("mean of empty values")
    return sum(values) / len(values)


def finalize() -> dict[str, Any]:
    prereg = build_preregistration()
    require_source_lock()
    task_manifest = read_csv(OUT / "task_manifest.csv")
    rows = completed_formal_rows()
    if len(rows) != len(task_manifest):
        raise RuntimeError(
            f"HALT_FORMAL_INCOMPLETE:{len(rows)}/{len(task_manifest)}"
        )
    rows.sort(key=lambda row: row["task_id"])
    write_csv(OUT / "raw_runs.csv", rows)
    paired = pair_rows(rows)
    write_csv(OUT / "paired_results.csv", paired)
    main_pairs = [row for row in paired if row["primary_exhibit"]]
    main_summary: list[dict[str, Any]] = []
    for intensity in MAIN_INTENSITIES:
        selected = [
            row
            for row in main_pairs
            if row["mismatch_intensity_nominal_pct"] == intensity
        ]
        if len(selected) != len(MAIN_SEEDS):
            raise RuntimeError("HALT_MAIN_EXHIBIT_PAIR_COUNT")
        reductions = [
            float(row["cost_reduction_pct_positive_is_benefit"])
            for row in selected
        ]
        main_summary.append(
            {
                "mismatch_intensity_nominal_pct": intensity,
                "paired_seeds": len(selected),
                "mean_lock_total_cost": mean(
                    [float(row["lock_total_cost"]) for row in selected]
                ),
                "mean_free_total_cost": mean(
                    [float(row["free_total_cost"]) for row in selected]
                ),
                "mean_free_relative_to_lock_cost_pct": mean(
                    [
                        float(row["free_relative_to_lock_cost_pct"])
                        for row in selected
                    ]
                ),
                "mean_cost_reduction_pct_positive_is_benefit": mean(
                    reductions
                ),
                "effect_direction": classify_effect(mean(reductions)),
                "mean_free_cross_site_service_count": mean(
                    [
                        float(row["free_cross_site_service_count"])
                        for row in selected
                    ]
                ),
                "lock_cross_site_zero_all": all(
                    int(row["lock_cross_site_service_count"]) == 0
                    for row in selected
                ),
                "service_completion_rate_pct_both_arms": 100.0,
                "mean_lock_total_emissions_kg": mean(
                    [
                        float(row["lock_total_emissions_kg"])
                        for row in selected
                    ]
                ),
                "mean_free_total_emissions_kg": mean(
                    [
                        float(row["free_total_emissions_kg"])
                        for row in selected
                    ]
                ),
                "mean_lock_minimum_physical_vehicle_count": mean(
                    [
                        float(
                            row[
                                "lock_minimum_physical_vehicle_count"
                            ]
                        )
                        for row in selected
                    ]
                ),
                "mean_free_minimum_physical_vehicle_count": mean(
                    [
                        float(
                            row[
                                "free_minimum_physical_vehicle_count"
                            ]
                        )
                        for row in selected
                    ]
                ),
            }
        )
    write_csv(OUT / "main_exhibit_summary.csv", main_summary)
    stability_pairs = [row for row in paired if row["stability_panel"]]
    cell_groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in stability_pairs:
        cell_groups.setdefault(
            (
                row["instance_id"],
                int(row["mismatch_intensity_nominal_pct"]),
            ),
            [],
        ).append(row)
    main_direction = {
        int(row["mismatch_intensity_nominal_pct"]): row[
            "effect_direction"
        ]
        for row in main_summary
        if int(row["mismatch_intensity_nominal_pct"])
        in STABILITY_INTENSITIES
    }
    stability_cells: list[dict[str, Any]] = []
    for (instance_id, intensity), selected in sorted(
        cell_groups.items()
    ):
        if len(selected) != len(STABILITY_SEEDS):
            raise RuntimeError("HALT_STABILITY_SEED_COUNT")
        reduction = mean(
            [
                float(row["cost_reduction_pct_positive_is_benefit"])
                for row in selected
            ]
        )
        direction = classify_effect(reduction)
        stability_cells.append(
            {
                "instance_id": instance_id,
                "region": selected[0]["region"],
                "customer_count": selected[0]["customer_count"],
                "mismatch_intensity_nominal_pct": intensity,
                "paired_seeds": len(selected),
                "mean_cost_reduction_pct_positive_is_benefit": reduction,
                "effect_direction": direction,
                "matches_main_exhibit_direction": (
                    direction == main_direction[intensity]
                ),
            }
        )
    write_csv(OUT / "stability_direction_cells.csv", stability_cells)
    stability_summary: list[dict[str, Any]] = []
    for intensity in STABILITY_INTENSITIES:
        selected = [
            row
            for row in stability_cells
            if int(row["mismatch_intensity_nominal_pct"]) == intensity
        ]
        stability_summary.append(
            {
                "mismatch_intensity_nominal_pct": intensity,
                "multi_depot_instances": len(selected),
                "main_exhibit_direction": main_direction[intensity],
                "positive_cells": sum(
                    row["effect_direction"] == "POSITIVE"
                    for row in selected
                ),
                "near_zero_cells": sum(
                    row["effect_direction"] == "NEAR_ZERO"
                    for row in selected
                ),
                "negative_cells": sum(
                    row["effect_direction"] == "NEGATIVE"
                    for row in selected
                ),
                "direction_matches_main_count": sum(
                    bool(row["matches_main_exhibit_direction"])
                    for row in selected
                ),
                "direction_matches_main_fraction": (
                    sum(
                        bool(row["matches_main_exhibit_direction"])
                        for row in selected
                    )
                    / len(selected)
                ),
                "reporting_scope": "DIRECTION_CONSISTENCY_ONLY",
            }
        )
    write_csv(OUT / "stability_direction_summary.csv", stability_summary)
    overall_reduction = mean(
        [
            float(row["cost_reduction_pct_positive_is_benefit"])
            for row in main_pairs
        ]
    )
    overall_direction = classify_effect(overall_reduction)
    decision = {
        "schema": "resetp.e3-mismatch.decision.v1",
        "task_id": TASK_ID,
        "verdict": f"PASS_COMPLETE_{overall_direction}",
        "gate2_verdict": read_json(
            OUT / "gate2_d3/decision.json"
        )["verdict"],
        "selected_complete_candidate_budget": read_json(
            OUT / "pilot/decision.json"
        )["selected_complete_candidate_budget"],
        "formal_unique_tasks": len(rows),
        "primary_exhibit_pairs": len(main_pairs),
        "stability_pairs": len(stability_pairs),
        "stability_cells": len(stability_cells),
        "overall_primary_exhibit_cost_reduction_pct": overall_reduction,
        "overall_result_blind_direction": overall_direction,
        "no_rows_deleted": True,
        "no_subset_selected_by_result": True,
        "all_solutions_independently_recomputed": True,
        "all_violation_counts_zero": all(
            int(row["violation_count"]) == 0 for row in rows
        ),
        "lock_cross_site_zero_all": all(
            int(row["cross_site_service_count"]) == 0
            for row in rows
            if row["arm"] == "LOCK"
        ),
        "protected_file_hashes": {
            relative(path): sha256(path) for path in PROTECTED
        },
        "statistical_tests": "NONE_DESCRIPTIVE_ONLY",
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.e3-mismatch.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "python": sys.version,
            "platform": platform.platform(),
            "source_hashes": source_hashes(),
            "mismatch_assignment_csv_sha256": prereg[
                "mismatch_assignment_csv_sha256"
            ],
            "worker_limit": MAX_WORKERS,
            "single_thread_per_task": True,
            "wallclock_role": "SAFETY_FUSE_ONLY",
            "cpu_recording": "resource.RUSAGE_SELF user/system/total",
        },
    )
    lines = [
        "# E3 责任错配与跨场协同",
        "",
        (
            f"**结论：{decision['verdict']}。** 门二在 45 个多车场实例"
            "的适用域内通过，36 个单车场实例按预注册排除；完整排除清单"
            "见 `gate2_d3/excluded_single_depot_instances.csv`。"
        ),
        "",
        (
            "主展品为 `cn-prd-50c-01-V2-LOCATIONS`，覆盖 0%、25%、"
            "50% 三档和种子 1--10。主要终点按正值代表 FREE 降本报告："
        ),
        "",
    ]
    for row in main_summary:
        lines.append(
            f"- {row['mismatch_intensity_nominal_pct']}%："
            f"{row['mean_cost_reduction_pct_positive_is_benefit']:.6f}%"
            f"（{row['effect_direction']}），FREE 平均跨场服务"
            f"{row['mean_free_cross_site_service_count']:.3f} 个客户。"
        )
    lines.extend(["", f"三档合并描述性平均降本为 {overall_reduction:.6f}%。"])
    if overall_direction == "NEAR_ZERO":
        lines.append(
            "按跑前写死的显示精度规则，该错配强度区间内跨场协同"
            "无额外收益；全部档位、种子和稳定性单元仍完整保留。"
        )
    elif overall_direction == "NEGATIVE":
        lines.append(
            "FREE 的主终点为负向结果；本报告如实保留，并仅从排放、"
            "车辆和跨场服务结构分析权衡。"
        )
    else:
        lines.append(
            "主终点为正向结果；效应量和三档趋势均按上述固定口径报告。"
        )
    lines.extend(
        [
            "",
            (
                "稳定性检验覆盖 45 个多车场实例、0%/50% 两档、种子 "
                "1--3；只报告方向一致性，不作主结论或显著性检验。"
                "逐实例方向见 `stability_direction_cells.csv`。"
            ),
            "",
            (
                "全部解均由 `check_solution` 与 `evaluate` 独立复算，"
                "违约为 0；LOCK 最终证书跨场服务为 0。受保护文件未修改，"
                "当前哈希见 `decision.json` 与 `metadata.json`。"
            ),
        ]
    )
    (OUT / "report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    write_json(
        OUT / "progress.json",
        {
            "status": "COMPLETE",
            "completed_unique_tasks": len(rows),
            "total_unique_tasks": len(rows),
            "remaining_unique_tasks": 0,
        },
    )
    write_json(
        OUT / "done.json",
        {
            "schema": "resetp.e3-mismatch.done.v1",
            "status": "complete",
            "verdict": decision["verdict"],
            "formal_unique_tasks": len(rows),
            "completed_at_utc": datetime.now(UTC).isoformat(),
        },
    )
    write_stage_hashes(OUT)
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("gate2")
    subparsers.add_parser("preregister")
    pilot_parser = subparsers.add_parser("pilot")
    pilot_parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    formal_parser = subparsers.add_parser("formal")
    formal_parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    subparsers.add_parser("finalize")
    args = parser.parse_args()
    if args.command == "gate2":
        result = gate2_replay()
    elif args.command == "preregister":
        result = build_preregistration()
    elif args.command == "pilot":
        result = run_pilot(args.workers)
    elif args.command == "formal":
        run_formal(args.workers)
        result = read_json(OUT / "decision.json")
    elif args.command == "finalize":
        result = finalize()
    else:
        raise AssertionError(args.command)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
