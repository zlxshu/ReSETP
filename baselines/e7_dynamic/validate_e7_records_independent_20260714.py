#!/usr/bin/env python3
"""Independent record-layer audit for the frozen E7 formal experiment.

This audit deliberately does not import the formal E7 runner, its gate module,
or its helper functions.  It reconstructs trigger batches and event effects
from the frozen input files, then checks the saved record tables against that
independent reconstruction.

The audit independently reconstructs records, event effects, locked work and
the twenty inherited vehicle states.  It intentionally shares the repository's
bottom-level cost evaluator, strict scheduling checker, data classes and the
initial-certificate execution ledger.  It is therefore an independent replay
of the experiment records, not a second implementation of the physical model.
The only remaining evidence boundary is that the elapsed wall-clock field was
written by the experiment process itself.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping, Sequence

from setp_solver.cost import evaluate
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.certificate_execution import build_certificate_execution_ledger
from setp_solver.search.dynamic_multitrip_schedule import (
    DynamicAssetState,
    validate_dynamic_multitrip_certificate,
)
from setp_solver.search.metaheuristic_baselines import solution_from_dict
from setp_solver.search.multitrip_schedule import MultiTripCertificate, ScheduledTrip
from setp_solver.solution import ChargingAction, Route, Solution


EXPECTED_STREAMS = (1, 2, 3, 4, 5)
EXPECTED_ARMS = ("cooperative", "independent")
EXPECTED_STAGE_COUNTS = {1: 7, 2: 8, 3: 7, 4: 7, 5: 7}
EXPECTED_EVALUATIONS_PER_STAGE = 400
EXPECTED_SESSION_COUNT = 10
EXPECTED_PAIR_COUNT = 5
EXPECTED_RAW_STAGE_COUNT = 72
EXPECTED_TOTAL_EVALUATIONS = 28_800
EXPECTED_EVENT_COUNT = 55
EXPECTED_EVENT_TYPES = {"add": 22, "cancel": 11, "demand_change": 22}
Q_BAR = 8
DELTA_T_SECONDS = 10_800.0
TOL = 1e-6
COST_ABS_TOL = 1e-6
COST_REL_TOL = 1e-9
DAY_SECONDS = 86_400.0

BASE_BUNDLE = (
    "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713/assets/"
    "L-main-threeshift-100c-01/bundle"
)
DONOR_BUNDLE = (
    "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713/assets/"
    "L-main-threeshift-200c-01/bundle"
)
EVENT_ROOT = "baselines/e7_dynamic/e7_v2_20260714/event_streams"
EVENT_GENERATOR_PATH = "baselines/e7_dynamic/generate_e7_event_streams_20260714.py"
EVENT_METADATA_PATH = f"{EVENT_ROOT}/metadata.json"
EVENT_MANIFEST_PATH = f"{EVENT_ROOT}/manifest.json"
EVENT_DECISION_PATH = f"{EVENT_ROOT}/decision.json"
OWNERSHIP_ROOT = "baselines/e3_ablation/e3_ownership_class_design_v4_20260713"
GEOGRAPHIC_OWNERS_PATH = (
    f"{OWNERSHIP_ROOT}/ownership_maps/"
    "L-main-threeshift-100c-01__geographic.csv"
)
GEOGRAPHIC_OWNERS_SHA256 = "224661a81d2e79b34a649b124596af0764894bea836f05327e1ce99dd66d2202"
OWNERSHIP_GENERATOR_PATH = "baselines/e3_ablation/e3_ownership_class_design_20260713.py"
OWNERSHIP_GENERATOR_SHA256 = "c76ac22d9874283c24c2837ca0949829121afc5e81943bea4ad6e55a1d34b0a7"
OWNERSHIP_METADATA_PATH = f"{OWNERSHIP_ROOT}/metadata.json"
OWNERSHIP_ARTIFACT_HASHES_PATH = f"{OWNERSHIP_ROOT}/artifact_hashes.json"
CONTRACT_ID = "E7_PAIRED_DYNAMIC_VALUE_V4_UNIQUE_EVENT_ROUTE_IDS"
INITIAL_SOLUTION_PATH = (
    "baselines/e6_fairness/e6_participation_formal_20260714/solutions/"
    "L-main-threeshift-100c-01__geographic__seed1__independent.json"
)
INITIAL_SOLUTION_SHA256 = "47884212a50d96e09b335f2ceb4f72a7314f52c9852c95f8cc0a5eb2a5e505a6"
INITIAL_CERTIFICATE_PATH = (
    "baselines/e6_fairness/e6_participation_formal_20260714/certificates/"
    "L-main-threeshift-100c-01__geographic__seed1__independent.json"
)
INITIAL_CERTIFICATE_SHA256 = "97e019daafc6e0f8e6d7642db7fce674a3dd15a2627ac6f08332f2bef80d01be"
E3_ARTIFACT_HASHES_PATH = "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713/artifact_hashes.json"
BASE_BUNDLE_HASH_KEYS = {
    "carbon_profile.csv": "assets/L-main-threeshift-100c-01/bundle/carbon_profile.csv",
    "distance_matrix.npy": "assets/L-main-threeshift-100c-01/bundle/distance_matrix.npy",
    "instance.json": "assets/L-main-threeshift-100c-01/bundle/instance.json",
    "scenario_manifest.json": "assets/L-main-threeshift-100c-01/bundle/scenario_manifest.json",
}
DONOR_BUNDLE_HASH_KEYS = {
    "carbon_profile.csv": "assets/L-main-threeshift-200c-01/bundle/carbon_profile.csv",
    "distance_matrix.npy": "assets/L-main-threeshift-200c-01/bundle/distance_matrix.npy",
    "instance.json": "assets/L-main-threeshift-200c-01/bundle/instance.json",
    "scenario_manifest.json": "assets/L-main-threeshift-200c-01/bundle/scenario_manifest.json",
}
CRITICAL_TRACKED_PATHS = (
    "baselines/e7_dynamic/e7_formal_dynamic_value_20260714.py",
    EVENT_GENERATOR_PATH,
    EVENT_METADATA_PATH,
    EVENT_MANIFEST_PATH,
    EVENT_DECISION_PATH,
    GEOGRAPHIC_OWNERS_PATH,
    OWNERSHIP_GENERATOR_PATH,
    OWNERSHIP_METADATA_PATH,
    OWNERSHIP_ARTIFACT_HASHES_PATH,
    "baselines/e7_dynamic/e7_dynamic_continuous_trigger_gate_20260714.py",
    "baselines/e7_dynamic/e7_p2_single_event_probe_20260714.py",
    "baselines/e3_ablation/e3_v3_runner.py",
    "baselines/e3_ablation/e3_multitrip_structure_gate.py",
    "baselines/e2_alns/e2_final_closure.py",
    "solver/src/setp_solver/algorithms/resetp_alns/kernel/alns_core.py",
    "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
    "solver/src/setp_solver/algorithms/resetp_alns/operators/carbon_operators.py",
    "solver/src/setp_solver/algorithms/resetp_alns/operators/feasible_repair.py",
    "solver/src/setp_solver/algorithms/resetp_alns/operators/local_search.py",
    "solver/src/setp_solver/algorithms/resetp_alns/operators/repair_scoring.py",
    "solver/src/setp_solver/algorithms/resetp_alns/operators/strong_bridge.py",
    "solver/src/setp_solver/algorithms/resetp_alns/support/charging.py",
    "solver/src/setp_solver/algorithms/resetp_alns/support/construction.py",
    "solver/src/setp_solver/algorithms/resetp_alns/support/elite_archive.py",
    "solver/src/setp_solver/algorithms/resetp_alns/support/fleet.py",
    "solver/src/setp_solver/algorithms/resetp_alns/support/fleet_charge_corepair.py",
    "solver/src/setp_solver/algorithms/resetp_alns/support/global_order_repack.py",
    "solver/src/setp_solver/algorithms/resetp_alns/support/route_pool.py",
    "solver/src/setp_solver/algorithms/resetp_alns/support/timing.py",
    "solver/src/setp_solver/algorithms/resetp_alns/runtime/__init__.py",
    "solver/src/setp_solver/algorithms/resetp_alns/runtime/accept.py",
    "solver/src/setp_solver/algorithms/resetp_alns/runtime/outcome.py",
    "solver/src/setp_solver/algorithms/resetp_alns/runtime/select.py",
    "solver/src/setp_solver/algorithms/resetp_alns/naming.py",
    "solver/src/setp_solver/search/dynamic_multitrip_schedule.py",
    "solver/src/setp_solver/search/dynamic.py",
    "solver/src/setp_solver/search/certificate_execution.py",
    "solver/src/setp_solver/search/execution_accounting.py",
    "solver/src/setp_solver/search/multitrip_schedule.py",
    "solver/src/setp_solver/search/metaheuristic_baselines.py",
    "solver/src/setp_solver/search/e3_multitrip_runtime.py",
    "solver/src/setp_solver/search/charging.py",
    "solver/src/setp_solver/search/fairness.py",
    "solver/src/setp_solver/search/formal_runner.py",
    "solver/src/setp_solver/search/submission_contract.py",
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
    "solver/src/setp_solver/prices.py",
    "solver/src/setp_solver/search/bundle.py",
    "solver/src/setp_solver/instance_loader.py",
    "solver/src/setp_solver/solution.py",
    "solver/src/setp_solver/profit.py",
    INITIAL_SOLUTION_PATH,
    INITIAL_CERTIFICATE_PATH,
    f"{BASE_BUNDLE}/carbon_profile.csv",
    f"{BASE_BUNDLE}/instance.json",
    f"{BASE_BUNDLE}/scenario_manifest.json",
    f"{DONOR_BUNDLE}/carbon_profile.csv",
    f"{DONOR_BUNDLE}/instance.json",
    f"{DONOR_BUNDLE}/scenario_manifest.json",
    E3_ARTIFACT_HASHES_PATH,
)
EXPECTED_OPERATOR_PAIRS = (
    "random_customer_removal+greedy_insert_repair",
    "random_customer_removal+regret2_insert_repair",
    "random_customer_removal+regret3_insert_repair",
    "worst_customer_removal+greedy_insert_repair",
    "worst_customer_removal+regret2_insert_repair",
    "worst_customer_removal+regret3_insert_repair",
    "shaw_related_removal+greedy_insert_repair",
    "shaw_related_removal+regret2_insert_repair",
    "shaw_related_removal+regret3_insert_repair",
    "whole_route_removal+greedy_insert_repair",
    "whole_route_removal+regret2_insert_repair",
    "whole_route_removal+regret3_insert_repair",
    "route_segment_removal+greedy_insert_repair",
    "route_segment_removal+regret2_insert_repair",
    "route_segment_removal+regret3_insert_repair",
    "vehicle_type_swap+greedy_insert_repair",
    "vehicle_type_swap+regret2_insert_repair",
    "vehicle_type_swap+regret3_insert_repair",
)
EXPECTED_OPERATOR_PAIRS_SHA256 = "dab1315a90b47a413c8f3e1c7d0933eaa06e3970161b8a2d1939fb6a30d5bdcf"
COST_BREAKDOWN_FIELDS = frozenset({
    "E_cv_direct",
    "E_ev_indirect",
    "E_total",
    "carbon_quota_kg",
    "cost_carbon",
    "cost_elec",
    "cost_fix",
    "cost_fuel",
    "cost_km",
    "cost_occ",
    "cost_transship",
    "depot_charging_kwh",
    "distance_cv",
    "distance_ev",
    "distance_total",
    "electricity_kwh",
    "ev_drive_kwh",
    "fuel_liters",
    "n_veh_cv",
    "n_veh_ev",
    "station_charging_kwh",
    "total_cost",
})
LOCKED_ACTION_FIELDS = frozenset({
    "vehicle_id",
    "station_id",
    "energy_kwh",
    "occupancy_minutes",
    "charge_start_second",
    "charge_day_offset",
})


class AuditFailure(RuntimeError):
    """The first mechanically false statement in the saved evidence."""


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AuditFailure(label)


def close(left: Any, right: Any, tolerance: float = TOL) -> bool:
    try:
        a = float(left)
        b = float(right)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(a) or not math.isfinite(b):
        return False
    return abs(a - b) <= tolerance * max(1.0, abs(a), abs(b))


def truth(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def split_ids(value: Any) -> list[str]:
    return [item for item in str(value or "").split(";") if item]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def git_blob(repo_root: Path, commit: str, relative_path: str) -> bytes:
    """Read one exact file version from the commit named by the run record."""

    require(
        len(commit) == 40 and all(character in "0123456789abcdef" for character in commit.lower()),
        f"invalid source commit: {commit!r}",
    )
    try:
        return subprocess.check_output(
            ["git", "show", f"{commit}:{relative_path}"],
            cwd=repo_root,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace").strip()
        raise AuditFailure(
            f"source commit does not contain {relative_path}: {detail}"
        ) from error


def validate_commit_bound_file(
    repo_root: Path,
    commit: str,
    relative_path: str,
    *,
    actual_path: Path | None = None,
) -> None:
    """Require the file actually read now to equal the run's recorded commit."""

    current_path = actual_path or (repo_root / relative_path)
    require(current_path.is_file(), f"commit-bound input is missing: {current_path}")
    committed = git_blob(repo_root, commit, relative_path)
    actual = current_path.read_bytes()
    require(
        actual == committed,
        (
            f"commit-bound file differs from {commit}: {relative_path}; "
            f"actual={sha256_bytes(actual)}, committed={sha256_bytes(committed)}"
        ),
    )


def validate_source_binding(
    repo_root: Path,
    metadata: Mapping[str, Any],
) -> None:
    """Bind the run record to exact code, frozen events and bundle inputs."""

    commit = str(metadata["source_commit"])
    require(
        metadata["run_start_commit"] == commit == metadata["artifact_write_commit"],
        "run/source/write commit equality",
    )
    tracked = list(CRITICAL_TRACKED_PATHS)
    tracked.append(f"{EVENT_ROOT}/raw_runs.csv")
    for seed in EXPECTED_STREAMS:
        tracked.extend((
            f"{EVENT_ROOT}/stream_seed{seed}.events.json",
            f"{EVENT_ROOT}/stream_seed{seed}.owners.csv",
        ))
    for relative_path in tracked:
        validate_commit_bound_file(repo_root, commit, relative_path)

    manifest = read_json(repo_root / E3_ARTIFACT_HASHES_PATH)
    for bundle_name, bundle_path, hash_keys in (
        ("base", BASE_BUNDLE, BASE_BUNDLE_HASH_KEYS),
        ("donor", DONOR_BUNDLE, DONOR_BUNDLE_HASH_KEYS),
    ):
        for filename, manifest_key in hash_keys.items():
            require(manifest_key in manifest, f"{bundle_name} bundle hash is absent: {manifest_key}")
            actual_path = repo_root / bundle_path / filename
            require(actual_path.is_file(), f"{bundle_name} bundle file is missing: {filename}")
            require(
                sha256_file(actual_path) == manifest[manifest_key],
                f"{bundle_name} bundle frozen hash: {filename}",
            )


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def metric_close(
    left: Any,
    right: Any,
    *,
    abs_tol: float = COST_ABS_TOL,
    rel_tol: float = COST_REL_TOL,
) -> bool:
    """Strict numeric comparison used for cost and emissions evidence."""

    try:
        a = float(left)
        b = float(right)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(a) or not math.isfinite(b):
        return False
    absolute_error = abs(a - b)
    relative_error = absolute_error / max(1.0, abs(a), abs(b))
    return absolute_error <= abs_tol and relative_error <= rel_tol


def require_metric_close(left: Any, right: Any, label: str) -> None:
    require(metric_close(left, right), f"{label}: {left!r} != {right!r}")


def validate_formal_metadata_contract(
    metadata: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> None:
    require(metadata["contract_id"] == CONTRACT_ID, "formal contract id")
    require(metadata["scope"] == "formal", "formal scope")
    require(tuple(metadata["arms"]) == EXPECTED_ARMS, "formal arm list")
    require(tuple(metadata["streams"]) == EXPECTED_STREAMS, "formal stream list")
    require(metadata["maximum_stages"] is None, "formal maximum stages must be unlimited")
    require_metric_close(metadata["delta_t"], DELTA_T_SECONDS, "formal delta_t")
    require_metric_close(
        metadata["delta_t_seconds"],
        DELTA_T_SECONDS,
        "formal delta_t_seconds",
    )
    require_metric_close(
        metadata["delta_t"],
        metadata["delta_t_seconds"],
        "formal two delta_t fields",
    )
    require(int(metadata["failure_count"]) == 0, "formal metadata failure count")
    require(
        int(metadata["failure_count"]) == int(decision["failure_count"]),
        "metadata/decision failure count",
    )


def validate_operator_pairs(value: Any, label: str) -> None:
    observed = tuple(split_ids(value))
    require(len(observed) == 18, f"{label} operator-pair count")
    require(observed == EXPECTED_OPERATOR_PAIRS, f"{label} frozen operator-pair menu")
    require(
        canonical_sha256(list(observed)) == EXPECTED_OPERATOR_PAIRS_SHA256,
        f"{label} operator-pair fingerprint",
    )


def validate_event_numeric_contract(event: Mapping[str, Any], label: str) -> None:
    event_type = str(event["event_type"]).lower()
    require(event_type in EXPECTED_EVENT_TYPES, f"{label} unsupported event type")
    numeric_fields = (
        "seed",
        "t_appear",
        "x",
        "y",
        "old_demand",
        "new_demand",
        "delta_demand",
        "old_ready_time",
        "old_due_time",
        "new_ready_time",
        "new_due_time",
    )
    for field in numeric_fields:
        try:
            value = float(event[field])
        except (KeyError, TypeError, ValueError) as error:
            raise AuditFailure(f"{label} {field} is not numeric") from error
        require(math.isfinite(value), f"{label} {field} is not finite")
    service_time = event.get("new_service_time")
    if service_time is not None:
        try:
            service_value = float(service_time)
        except (TypeError, ValueError) as error:
            raise AuditFailure(f"{label} service time is not numeric") from error
        require(math.isfinite(service_value), f"{label} service time is not finite")
    require(float(event["t_appear"]) >= 0.0, f"{label} appearance time is negative")
    require(
        float(event["old_due_time"]) >= float(event["old_ready_time"]),
        f"{label} old time window is inverted",
    )
    require(
        float(event["new_due_time"]) >= float(event["new_ready_time"]),
        f"{label} new time window is inverted",
    )
    require_metric_close(
        float(event["new_demand"]) - float(event["old_demand"]),
        event["delta_demand"],
        f"{label} demand change",
    )
    if event_type == "add":
        require_metric_close(event["old_demand"], 0.0, f"{label} add old demand")
        require(float(event["new_demand"]) > 0.0, f"{label} add demand is not positive")
        require(
            service_time is not None and float(service_time) > 0.0,
            f"{label} add service time is not positive",
        )
    elif event_type == "cancel":
        require(float(event["old_demand"]) > 0.0, f"{label} cancel old demand is not positive")
        require_metric_close(event["new_demand"], 0.0, f"{label} cancel new demand")
    else:
        require(float(event["old_demand"]) > 0.0, f"{label} change old demand is not positive")
        require(float(event["new_demand"]) > 0.0, f"{label} changed demand is not positive")


def validate_owner_population(
    owners: Mapping[str, str],
    events: Sequence[Mapping[str, Any]],
    original_customer_ids: set[str],
    label: str,
) -> None:
    added_customer_ids = {
        str(event["customer_id"])
        for event in events
        if str(event["event_type"]).lower() == "add"
    }
    require(len(original_customer_ids) == 221, f"{label} original owner population")
    require(len(added_customer_ids) == 22, f"{label} added owner population")
    require(
        original_customer_ids.isdisjoint(added_customer_ids),
        f"{label} added customer reuses original ID",
    )
    require(
        all(owner in {"D0", "D1"} for owner in owners.values()),
        f"{label} invalid owner",
    )
    expected = original_customer_ids | added_customer_ids
    require(
        set(owners) == expected,
        (
            f"{label} owner population; "
            f"missing={sorted(expected - set(owners))}, "
            f"extra={sorted(set(owners) - expected)}"
        ),
    )


def nearest_owner_from_coordinates(
    x: float,
    y: float,
    depots: Sequence[Node],
) -> str:
    require(
        [depot.node_id for depot in sorted(depots, key=lambda item: item.node_id)]
        == ["D0", "D1"],
        "owner rule requires exactly D0 and D1",
    )
    return min(
        depots,
        key=lambda depot: (
            (float(x) - float(depot.x)) ** 2
            + (float(y) - float(depot.y)) ** 2,
            str(depot.node_id),
        ),
    ).node_id


def validate_owner_and_donor_provenance(
    repo_root: Path,
    owners: Mapping[str, str],
    events: Sequence[Mapping[str, Any]],
    base_instance: Instance,
    label: str,
) -> dict[str, Any]:
    """Rebuild every original and added-customer owner from frozen sources."""

    event_metadata = read_json(repo_root / EVENT_METADATA_PATH)
    event_manifest = read_json(repo_root / EVENT_MANIFEST_PATH)
    ownership_metadata = read_json(repo_root / OWNERSHIP_METADATA_PATH)
    ownership_hashes = read_json(repo_root / OWNERSHIP_ARTIFACT_HASHES_PATH)
    geographic_path = repo_root / GEOGRAPHIC_OWNERS_PATH
    ownership_generator = repo_root / OWNERSHIP_GENERATOR_PATH
    event_generator = repo_root / EVENT_GENERATOR_PATH

    require(event_metadata["contract_id"] == "E7_EVENT_STREAM_FREEZE_V3_SERVICE_TIME", f"{label} event generation contract")
    require(event_manifest["contract_id"] == event_metadata["contract_id"], f"{label} event manifest contract")
    require(event_metadata["generator_script"] == EVENT_GENERATOR_PATH, f"{label} event generator path")
    require(
        event_metadata["generator_script_sha256"] == sha256_file(event_generator),
        f"{label} event generator hash",
    )
    require(event_metadata["base_ownership_map"] == GEOGRAPHIC_OWNERS_PATH, f"{label} base owner path")
    require(event_metadata["base_ownership_sha256"] == GEOGRAPHIC_OWNERS_SHA256, f"{label} base owner contract hash")
    require(sha256_file(geographic_path) == GEOGRAPHIC_OWNERS_SHA256, f"{label} base owner file hash")
    require(
        event_metadata["new_customer_owner_rule"]
        == "nearest D0/D1 by Euclidean squared distance; depot id breaks an exact tie",
        f"{label} new-customer owner rule",
    )
    require(event_metadata["donor_bundle"] == DONOR_BUNDLE, f"{label} donor bundle path")
    require(
        event_metadata["donor_rule"]
        == (
            "exact coordinate, demand, ready time, due time, and service time inherited from an unused customer "
            "in the frozen E3 200c sister bundle; no field is clamped"
        ),
        f"{label} donor inheritance rule",
    )
    require(ownership_metadata["schema"] == "setp.e3.ownership_class_design.v4", f"{label} owner schema")
    require(ownership_metadata["generator"] == OWNERSHIP_GENERATOR_PATH, f"{label} owner generator path")
    require(
        ownership_metadata["generator_sha256"] == OWNERSHIP_GENERATOR_SHA256,
        f"{label} owner generator contract hash",
    )
    require(
        sha256_file(ownership_generator) == OWNERSHIP_GENERATOR_SHA256,
        f"{label} owner generator file hash",
    )
    require(
        ownership_hashes[GEOGRAPHIC_OWNERS_PATH] == GEOGRAPHIC_OWNERS_SHA256,
        f"{label} owner artifact hash",
    )
    require(
        ownership_hashes[OWNERSHIP_GENERATOR_PATH] == OWNERSHIP_GENERATOR_SHA256,
        f"{label} owner generator artifact hash",
    )

    frozen_rows = read_csv(geographic_path)
    frozen = {row["customer_id"]: row["owner_depot_id"] for row in frozen_rows}
    require(len(frozen) == len(frozen_rows) == 221, f"{label} frozen owner row count")
    original_ids = _customer_ids(base_instance)
    require(set(frozen) == original_ids, f"{label} frozen owner customer set")
    depots = sorted(
        (node for node in base_instance.nodes if node.node_type.lower() == "d"),
        key=lambda node: node.node_id,
    )
    for customer_id in sorted(original_ids):
        nearest = min(
            depots,
            key=lambda depot: (
                float(base_instance.distance(depot.node_id, customer_id)),
                str(depot.node_id),
            ),
        ).node_id
        require(frozen[customer_id] == nearest, f"{label} frozen owner value for {customer_id}")
        require(owners[customer_id] == frozen[customer_id], f"{label} stream owner value for {customer_id}")

    donor_instance = load_search_bundle(repo_root / DONOR_BUNDLE).instance
    require(
        sha256_file(repo_root / DONOR_BUNDLE / "instance.json")
        == event_metadata["donor_instance_sha256"],
        f"{label} donor instance hash",
    )
    donors = {
        node.node_id: node
        for node in donor_instance.nodes
        if node.node_type.lower() == "c"
    }
    add_events = [
        event for event in events if str(event["event_type"]).lower() == "add"
    ]
    donor_ids: list[str] = []
    for event in add_events:
        event_id = str(event["event_id"])
        customer_id = str(event["customer_id"])
        donor_id = str(event["donor_customer_id"])
        donor_ids.append(donor_id)
        require(event["donor_instance_id"] == "L-main-threeshift-200c-01", f"{label} add {event_id} donor instance id")
        require(donor_id in donors, f"{label} add {event_id} donor customer id")
        require(event["source"] == "frozen_e3_sister_bundle_overlay", f"{label} add {event_id} source marker")
        for field in ("demand_source", "time_window_source", "service_time_source"):
            require(event[field] == "frozen_sister_bundle_exact", f"{label} add {event_id} {field}")
        donor = donors[donor_id]
        inherited = {
            "x": donor.x,
            "y": donor.y,
            "new_demand": donor.demand,
            "old_ready_time": donor.ready_time,
            "old_due_time": donor.due_time,
            "new_ready_time": donor.ready_time,
            "new_due_time": donor.due_time,
            "new_service_time": donor.service_time,
        }
        for field, expected in inherited.items():
            require_metric_close(event[field], expected, f"{label} add {event_id} inherited {field}")
        recomputed_owner = nearest_owner_from_coordinates(
            float(event["x"]),
            float(event["y"]),
            depots,
        )
        require(owners[customer_id] == recomputed_owner, f"{label} add {event_id} recomputed owner")
    require(len(add_events) == len(set(donor_ids)) == 22, f"{label} unique donor count")
    return {
        "geographic_owner_source": GEOGRAPHIC_OWNERS_PATH,
        "ownership_generator": OWNERSHIP_GENERATOR_PATH,
        "event_generator": EVENT_GENERATOR_PATH,
        "donor_bundle": DONOR_BUNDLE,
        "original_owner_count": len(original_ids),
        "inherited_add_count": len(add_events),
    }


def certificate_from_dict(payload: Mapping[str, Any]) -> MultiTripCertificate:
    return MultiTripCertificate(
        contract_id=str(payload["contract_id"]),
        status=str(payload["status"]),
        vehicle_counts={str(key): int(value) for key, value in payload["vehicle_counts"].items()},
        trips=tuple(ScheduledTrip(**row) for row in payload["trips"]),
        recharge_mode=str(payload["recharge_mode"]),
        depot_charge_power_kw=float(payload["depot_charge_power_kw"]),
        first_trip_charge_day_offset=int(payload.get("first_trip_charge_day_offset", -1)),
    )


def formal_prices() -> Any:
    """Build the frozen E7 price object without calling an experiment wrapper."""

    return replace(
        DEFAULT_PRICES,
        B_battery_kwh=280.0,
        initial_ev_battery_kwh=0.0,
        cross_site_cost=0.0,
        carbon_price=0.0,
    )


def absolute_charge_start(action: ChargingAction) -> float:
    return float(action.charge_start_second) + int(action.charge_day_offset) * DAY_SECONDS


def full_action_key(action: ChargingAction) -> tuple[Any, ...]:
    return (
        action.vehicle_id,
        action.station_id,
        float(action.energy_kwh),
        float(action.occupancy_minutes),
        float(action.charge_start_second),
        int(action.charge_day_offset),
    )


def billing_action_key(action: ChargingAction) -> tuple[Any, ...]:
    """Match the formal record's once-only charging ledger key."""

    return (
        action.vehicle_id,
        action.station_id,
        round(float(action.charge_start_second), 9),
        round(float(action.energy_kwh), 9),
    )


def deduplicate_locked_actions(
    actions: Sequence[ChargingAction],
    *,
    first_stage: bool,
) -> tuple[ChargingAction, ...]:
    unique: dict[tuple[Any, ...], ChargingAction] = {}
    for action in actions:
        key = full_action_key(action)
        unique.setdefault(key, action)
    values = list(unique.values())
    if first_stage:
        values.sort(
            key=lambda action: (
                absolute_charge_start(action),
                action.vehicle_id,
                action.station_id,
            )
        )
    else:
        values.sort(
            key=lambda action: (
                int(action.charge_day_offset),
                float(action.charge_start_second),
                action.station_id,
                action.vehicle_id,
            )
        )
    return tuple(values)


def _trip_state(trip: ScheduledTrip, trigger: float) -> str:
    if float(trigger) < float(trip.departure_second):
        return "not_started"
    if float(trigger) < float(trip.return_second):
        return "in_progress"
    return "completed"


def _routes_for_ids(solution: Solution, route_ids: Sequence[str]) -> tuple[Route, ...]:
    by_id = {route.vehicle_id: route for route in solution.routes}
    require(len(by_id) == len(solution.routes), "solution route IDs are not unique")
    missing = sorted(set(route_ids) - set(by_id))
    require(not missing, f"certificate cut references missing routes: {missing}")
    return tuple(by_id[route_id] for route_id in route_ids)


def _validate_asset_shape(states: Mapping[str, DynamicAssetState]) -> None:
    require(len(states) == 20, "independently reconstructed asset count")
    composition = Counter(
        (state.vehicle_type, state.home_depot_id)
        for state in states.values()
    )
    require(
        composition
        == Counter({
            ("cv", "D0"): 5,
            ("cv", "D1"): 5,
            ("ev", "D0"): 5,
            ("ev", "D1"): 5,
        }),
        f"independently reconstructed fleet composition: {dict(composition)}",
    )


def derive_initial_cut(
    solution: Solution,
    certificate: MultiTripCertificate,
    instance: Instance,
    prices: Any,
    trigger: float,
) -> IndependentCut:
    """Independently cut the sealed initial certificate at the first trigger."""

    ledger = build_certificate_execution_ledger(solution, certificate, instance, prices)
    completed: list[str] = []
    in_progress: list[str] = []
    editable: list[str] = []
    for route_id, execution in ledger.routes.items():
        if trigger < execution.departure_second:
            editable.append(route_id)
        elif trigger < execution.return_second:
            in_progress.append(route_id)
        else:
            completed.append(route_id)

    trip_by_route = {trip.route_id: trip for trip in certificate.trips}
    require(len(trip_by_route) == len(certificate.trips), "initial certificate route IDs are not unique")
    actions_by_asset: dict[str, list[ChargingAction]] = {}
    locked: list[ChargingAction] = []
    for action in solution.charging_actions:
        require(action.vehicle_id in trip_by_route, f"initial charge detached from {action.vehicle_id}")
        asset_id = trip_by_route[action.vehicle_id].physical_vehicle_id
        actions_by_asset.setdefault(asset_id, []).append(action)
        if absolute_charge_start(action) <= trigger:
            locked.append(action)

    battery_cap = float(prices.B_battery_kwh)
    initial_battery = float(prices.initial_ev_battery_kwh)
    states: dict[str, DynamicAssetState] = {}
    for asset_id, asset in ledger.assets.items():
        chain = [ledger.routes[route_id] for route_id in asset.route_ids]
        started = [item for item in chain if trigger >= item.departure_second]
        running = [item for item in chain if item.departure_second <= trigger < item.return_second]
        available = max(
            [float(trigger), *[float(item.return_second) for item in running]]
        )
        for action in actions_by_asset.get(asset_id, []):
            start = absolute_charge_start(action)
            end = start + float(action.occupancy_minutes) * 60.0
            if start <= trigger < end:
                available = max(available, end)
        if asset.vehicle_type == "ev":
            battery = initial_battery - sum(float(item.drive_energy_kwh) for item in started)
            battery += sum(
                float(action.energy_kwh)
                for action in actions_by_asset.get(asset_id, [])
                if absolute_charge_start(action) <= trigger
            )
            require(-TOL <= battery <= battery_cap + TOL, f"initial asset {asset_id} battery range")
            battery = min(battery_cap, max(0.0, battery))
        else:
            battery = 0.0
        next_trip = max((item.trip_index for item in started), default=0) + 1
        states[asset_id] = DynamicAssetState(
            physical_vehicle_id=asset_id,
            vehicle_type=asset.vehicle_type,
            home_depot_id=asset.home_depot_id,
            available_second=float(available),
            remaining_battery_kwh=float(battery),
            next_trip_index=int(next_trip),
        )
    _validate_asset_shape(states)
    completed_ids = tuple(sorted(completed))
    in_progress_ids = tuple(sorted(in_progress))
    editable_ids = tuple(sorted(editable))
    locked_ids = (*completed_ids, *in_progress_ids)
    return IndependentCut(
        completed_route_ids=completed_ids,
        in_progress_route_ids=in_progress_ids,
        editable_route_ids=editable_ids,
        locked_routes=_routes_for_ids(solution, locked_ids),
        locked_charging_actions=deduplicate_locked_actions(locked, first_stage=True),
        asset_states=states,
    )


def derive_later_cut(
    solution: Solution,
    certificate: MultiTripCertificate,
    instance: Instance,
    prices: Any,
    *,
    inherited_states: Mapping[str, DynamicAssetState],
    previous_trigger: float,
    inherited_locked_actions: Sequence[ChargingAction],
    trigger: float,
) -> IndependentCut:
    """Independently cut one already-certified dynamic continuation."""

    require(trigger >= previous_trigger - TOL, "later trigger precedes previous trigger")
    validate_dynamic_multitrip_certificate(
        solution,
        certificate,
        instance,
        prices,
        asset_states=inherited_states,
        stage_start_second=previous_trigger,
        locked_charging_actions=inherited_locked_actions,
    )
    trip_by_route = {trip.route_id: trip for trip in certificate.trips}
    require(len(trip_by_route) == len(certificate.trips), "dynamic certificate route IDs are not unique")
    require(set(trip_by_route) == {route.vehicle_id for route in solution.routes}, "dynamic certificate route coverage")
    completed = tuple(sorted(trip.route_id for trip in certificate.trips if _trip_state(trip, trigger) == "completed"))
    in_progress = tuple(sorted(trip.route_id for trip in certificate.trips if _trip_state(trip, trigger) == "in_progress"))
    editable = tuple(sorted(trip.route_id for trip in certificate.trips if _trip_state(trip, trigger) == "not_started"))

    actions_by_asset: dict[str, list[ChargingAction]] = {}
    newly_locked: list[ChargingAction] = []
    for action in solution.charging_actions:
        require(action.vehicle_id in trip_by_route, f"dynamic charge detached from {action.vehicle_id}")
        asset_id = trip_by_route[action.vehicle_id].physical_vehicle_id
        actions_by_asset.setdefault(asset_id, []).append(action)
        if absolute_charge_start(action) <= trigger:
            newly_locked.append(action)

    battery_cap = float(prices.B_battery_kwh)
    states: dict[str, DynamicAssetState] = {}
    for asset_id, inherited in inherited_states.items():
        chain = [trip for trip in certificate.trips if trip.physical_vehicle_id == asset_id]
        started = [trip for trip in chain if _trip_state(trip, trigger) != "not_started"]
        running = [trip for trip in chain if _trip_state(trip, trigger) == "in_progress"]
        available = max(
            [float(trigger), float(inherited.available_second), *[float(trip.return_second) for trip in running]]
        )
        for action in actions_by_asset.get(asset_id, []):
            start = absolute_charge_start(action)
            end = start + float(action.occupancy_minutes) * 60.0
            if start <= trigger < end:
                available = max(available, end)
        if inherited.vehicle_type == "ev":
            battery = float(inherited.remaining_battery_kwh)
            battery -= sum(
                float(trip.start_battery_kwh or 0.0) - float(trip.end_battery_kwh or 0.0)
                for trip in started
            )
            battery += sum(
                float(action.energy_kwh)
                for action in actions_by_asset.get(asset_id, [])
                if absolute_charge_start(action) <= trigger
            )
            require(-TOL <= battery <= battery_cap + TOL, f"dynamic asset {asset_id} battery range")
            battery = min(battery_cap, max(0.0, battery))
        else:
            battery = 0.0
        next_trip = max(
            int(inherited.next_trip_index),
            max((int(trip.trip_index) + 1 for trip in started), default=int(inherited.next_trip_index)),
        )
        states[asset_id] = DynamicAssetState(
            physical_vehicle_id=asset_id,
            vehicle_type=inherited.vehicle_type,
            home_depot_id=inherited.home_depot_id,
            available_second=float(available),
            remaining_battery_kwh=float(battery),
            next_trip_index=int(next_trip),
        )
    _validate_asset_shape(states)
    return IndependentCut(
        completed_route_ids=completed,
        in_progress_route_ids=in_progress,
        editable_route_ids=editable,
        locked_routes=_routes_for_ids(solution, (*completed, *in_progress)),
        locked_charging_actions=deduplicate_locked_actions(
            [*inherited_locked_actions, *newly_locked],
            first_stage=False,
        ),
        asset_states=states,
    )


def assert_asset_states_match(
    expected: Mapping[str, DynamicAssetState],
    recorded: Mapping[str, Mapping[str, Any]],
    label: str,
) -> None:
    require(set(expected) == set(recorded), f"{label} asset IDs")
    for asset_id, state in expected.items():
        row = recorded[asset_id]
        require(row["physical_vehicle_id"] == state.physical_vehicle_id, f"{label} {asset_id} physical id")
        require(row["vehicle_type"] == state.vehicle_type, f"{label} {asset_id} type")
        require(row["home_depot_id"] == state.home_depot_id, f"{label} {asset_id} home")
        require_metric_close(row["available_second"], state.available_second, f"{label} {asset_id} available")
        require_metric_close(row["remaining_battery_kwh"], state.remaining_battery_kwh, f"{label} {asset_id} battery")
        require(int(row["next_trip_index"]) == int(state.next_trip_index), f"{label} {asset_id} next trip")


def evaluate_direct(
    solution: Solution,
    instance: Instance,
    carbon_profile: Sequence[Mapping[str, Any]],
    prices: Any,
) -> dict[str, Any]:
    return evaluate(
        solution,
        instance,
        list(carbon_profile),
        prices,
        carbon_quota_kg=0.0,
    )


def add_numeric_parts(target: dict[str, float], part: Mapping[str, Any]) -> None:
    for key, value in part.items():
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            target[key] = target.get(key, 0.0) + float(value)


def assert_cost_breakdown(
    recorded: Mapping[str, Any],
    recomputed: Mapping[str, Any],
    label: str,
) -> None:
    require(
        set(recorded) == COST_BREAKDOWN_FIELDS,
        (
            f"{label} cost fields; missing={sorted(COST_BREAKDOWN_FIELDS - set(recorded))}, "
            f"extra={sorted(set(recorded) - COST_BREAKDOWN_FIELDS)}"
        ),
    )
    require(
        COST_BREAKDOWN_FIELDS <= set(recomputed),
        f"{label} recomputation lacks fields {sorted(COST_BREAKDOWN_FIELDS - set(recomputed))}",
    )
    for key in sorted(COST_BREAKDOWN_FIELDS):
        require_metric_close(recorded[key], recomputed[key], f"{label} {key}")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def safe_recorded_path(repo_root: Path, recorded: str) -> Path:
    root = repo_root.resolve()
    candidate = (root / recorded).resolve()
    require(candidate.is_relative_to(root), f"recorded path escapes repository: {recorded}")
    require(candidate.is_file(), f"recorded file is missing: {recorded}")
    return candidate


def expected_session_paths(
    repo_root: Path,
    run_dir: Path,
    stream_seed: int,
    arm: str,
) -> dict[str, str]:
    require(arm in EXPECTED_ARMS, f"unexpected arm: {arm}")
    relative_run = run_dir.resolve().relative_to(repo_root.resolve())
    prefix = str(relative_run)
    return {
        "event_path": f"{EVENT_ROOT}/stream_seed{stream_seed}.events.json",
        "owner_path": f"{EVENT_ROOT}/stream_seed{stream_seed}.owners.csv",
        "initial_solution_path": INITIAL_SOLUTION_PATH,
        "initial_certificate_path": INITIAL_CERTIFICATE_PATH,
        "final_solution_path": f"{prefix}/solutions/stream{stream_seed}__{arm}.json",
        "final_certificate_path": f"{prefix}/certificates/stream{stream_seed}__{arm}.json",
        "stage_evidence_path": f"{prefix}/stage_evidence/stream{stream_seed}__{arm}.json",
    }


def assert_session_paths(
    repo_root: Path,
    run_dir: Path,
    stream_seed: int,
    arm: str,
    summary: Mapping[str, Any],
) -> None:
    for field, expected in expected_session_paths(
        repo_root, run_dir, stream_seed, arm
    ).items():
        require(
            summary[field] == expected,
            f"stream {stream_seed} {arm} exact {field}: {summary[field]!r} != {expected!r}",
        )


def assert_locked_actions_match(
    expected_actions: Sequence[ChargingAction],
    recorded_actions: Sequence[Mapping[str, Any]],
    recorded_sha256: str,
    label: str,
) -> None:
    expected = [asdict(action) for action in expected_actions]
    require(
        all(set(action) == LOCKED_ACTION_FIELDS for action in recorded_actions),
        f"{label} locked charging action fields",
    )
    full_keys = [
        (
            action["vehicle_id"],
            action["station_id"],
            float(action["energy_kwh"]),
            float(action["occupancy_minutes"]),
            float(action["charge_start_second"]),
            int(action["charge_day_offset"]),
        )
        for action in recorded_actions
    ]
    require(len(full_keys) == len(set(full_keys)), f"{label} duplicate locked charging action")
    require(list(recorded_actions) == expected, f"{label} locked charging actions")
    require(recorded_sha256 == canonical_sha256(expected), f"{label} locked charging hash")


def unique_index(
    rows: Sequence[Mapping[str, Any]],
    key_names: Sequence[str],
    label: str,
) -> dict[tuple[Any, ...], Mapping[str, Any]]:
    result: dict[tuple[Any, ...], Mapping[str, Any]] = {}
    for row in rows:
        key = tuple(row[name] for name in key_names)
        require(key not in result, f"duplicate {label}: {key}")
        result[key] = row
    return result


@dataclass(frozen=True)
class TriggerBatch:
    stage: int
    trigger_second: float
    trigger_reason: str
    events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class EventApplication:
    instance: Instance
    applied_event_ids: tuple[str, ...]
    ignored_locked_event_ids: tuple[str, ...]
    outcomes: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class SessionReplay:
    stream_seed: int
    arm: str
    stage_count: int
    final_workload: dict[str, dict[str, Any]]
    final_workload_sha256: str
    final_customer_count: int
    final_total_demand: float
    locked_cancel_count: int
    locked_change_count: int
    removed_cancel_count: int
    applied_change_count: int
    applied_event_count: int
    ignored_locked_event_count: int
    final_cross_site_customer_ids: tuple[str, ...]
    final_dynamic_added_cross_site_customer_ids: tuple[str, ...]
    final_total_cost: float
    final_total_emissions: float


@dataclass(frozen=True)
class IndependentCut:
    completed_route_ids: tuple[str, ...]
    in_progress_route_ids: tuple[str, ...]
    editable_route_ids: tuple[str, ...]
    locked_routes: tuple[Route, ...]
    locked_charging_actions: tuple[ChargingAction, ...]
    asset_states: dict[str, DynamicAssetState]


def derive_trigger_batches(
    events: Sequence[Mapping[str, Any]],
    *,
    q_bar: int = Q_BAR,
    delta_t_seconds: float = DELTA_T_SECONDS,
) -> list[TriggerBatch]:
    """Reproduce the q-bar/time batching without importing dynamic.py."""

    require(q_bar > 0, "q_bar must be positive")
    require(delta_t_seconds > 0.0, "delta_t_seconds must be positive")
    normalized = [dict(event) for event in events]
    ids = [str(event["event_id"]) for event in normalized]
    require(len(ids) == len(set(ids)), "event IDs must be unique")
    for event in normalized:
        require(math.isfinite(float(event["t_appear"])), "event appearance time must be finite")
        require(float(event["t_appear"]) >= 0.0, "event appearance time must be nonnegative")
    ordered = sorted(
        normalized,
        key=lambda event: (float(event["t_appear"]), str(event["event_id"])),
    )
    result: list[TriggerBatch] = []
    cursor = 0
    last_trigger = 0.0
    stage = 1
    while cursor < len(ordered):
        deadline = last_trigger + float(delta_t_seconds)
        batch: list[dict[str, Any]] = []
        reached_qbar = False
        while cursor < len(ordered) and float(ordered[cursor]["t_appear"]) <= deadline:
            batch.append(ordered[cursor])
            cursor += 1
            if len(batch) >= q_bar:
                trigger = float(batch[-1]["t_appear"])
                result.append(TriggerBatch(stage, trigger, "q_bar", tuple(batch)))
                last_trigger = trigger
                stage += 1
                reached_qbar = True
                break
        if reached_qbar:
            continue
        if batch:
            result.append(TriggerBatch(stage, deadline, "delta_t", tuple(batch)))
            stage += 1
        last_trigger = deadline
    return result


def _node_map(instance: Instance) -> dict[str, Node]:
    return {node.node_id: node for node in instance.nodes}


def _customer_ids(instance: Instance) -> set[str]:
    return {node.node_id for node in instance.nodes if node.node_type.lower() == "c"}


def _route_customers(route: Mapping[str, Any], instance: Instance) -> list[str]:
    lookup = _node_map(instance)
    unknown = [node_id for node_id in route["node_sequence"] if node_id not in lookup]
    require(not unknown, f"route {route.get('vehicle_id')} contains unknown nodes: {unknown}")
    return [
        node_id
        for node_id in route["node_sequence"]
        if lookup[node_id].node_type.lower() == "c"
    ]


def rebuild_instance(source: Instance, nodes: Sequence[Node]) -> Instance:
    """Rebuild distances without importing dynamic._rebuild_instance_matrix."""

    source_index = source.node_index
    matrix: list[list[float]] = []
    for left in nodes:
        row: list[float] = []
        for right in nodes:
            if left.node_id in source_index and right.node_id in source_index:
                row.append(float(source.distance(left.node_id, right.node_id)))
            else:
                row.append(math.hypot(float(left.x) - float(right.x), float(left.y) - float(right.y)))
        matrix.append(row)
    return Instance(
        nodes=list(nodes),
        distance_matrix=matrix,
        diesel_l_per_meter=source.diesel_l_per_meter,
        ev_kwh_per_meter=source.ev_kwh_per_meter,
        unit_distance_cost_per_meter=source.unit_distance_cost_per_meter,
        num_cv=source.num_cv,
        num_ev=source.num_ev,
    )


def _event_old_values_match(event: Mapping[str, Any], node: Node) -> bool:
    return (
        close(event["x"], node.x)
        and close(event["y"], node.y)
        and close(event["old_demand"], node.demand)
        and close(event["old_ready_time"], node.ready_time)
        and close(event["old_due_time"], node.due_time)
    )


def apply_event_batch(
    source: Instance,
    events: Sequence[Mapping[str, Any]],
    committed_customer_ids: set[str],
) -> EventApplication:
    """Apply one frozen batch using the paper's departure-lock boundary."""

    nodes = list(source.nodes)
    applied: list[str] = []
    ignored: list[str] = []
    outcomes: list[dict[str, Any]] = []
    for event in sorted(
        (dict(item) for item in events),
        key=lambda item: (float(item["t_appear"]), str(item["event_id"])),
    ):
        event_id = str(event["event_id"])
        event_type = str(event["event_type"]).lower()
        customer_id = str(event["customer_id"])
        lookup = {node.node_id: node for node in nodes}
        locked = customer_id in committed_customer_ids

        if event_type == "add":
            require(customer_id not in lookup, f"add event {event_id} reuses customer {customer_id}")
            require(not locked, f"add event {event_id} is unexpectedly locked")
            service = event.get("new_service_time")
            require(service is not None and float(service) > 0.0, f"add event {event_id} lacks service time")
            require(close(event["old_demand"], 0.0), f"add event {event_id} old demand is not zero")
            nodes.append(
                Node(
                    node_id=customer_id,
                    node_type="c",
                    x=float(event["x"]),
                    y=float(event["y"]),
                    demand=float(event["new_demand"]),
                    ready_time=float(event["new_ready_time"]),
                    due_time=float(event["new_due_time"]),
                    service_time=float(service),
                )
            )
            applied.append(event_id)
            outcomes.append({"event_id": event_id, "event_type": event_type, "outcome": "added"})
            continue

        require(customer_id in lookup, f"event {event_id} targets missing customer {customer_id}")
        node = lookup[customer_id]
        require(_event_old_values_match(event, node), f"event {event_id} old values do not match current instance")
        require(
            close(float(event["new_demand"]) - float(event["old_demand"]), event["delta_demand"]),
            f"event {event_id} demand delta does not close",
        )

        if locked:
            require(event_type in {"cancel", "demand_change", "change", "time_window_change"}, f"locked event {event_id} has unsupported type")
            ignored.append(event_id)
            outcomes.append({"event_id": event_id, "event_type": event_type, "outcome": "locked_original_honored"})
            continue

        if event_type == "cancel":
            require(close(event["new_demand"], 0.0), f"cancel event {event_id} new demand is not zero")
            nodes = [item for item in nodes if item.node_id != customer_id]
            outcomes.append({"event_id": event_id, "event_type": event_type, "outcome": "removed_before_departure"})
        elif event_type in {"demand_change", "change"}:
            require(float(event["new_demand"]) > 0.0, f"change event {event_id} has nonpositive demand")
            nodes = [
                replace(item, demand=float(event["new_demand"])) if item.node_id == customer_id else item
                for item in nodes
            ]
            outcomes.append({"event_id": event_id, "event_type": event_type, "outcome": "demand_changed_before_departure"})
        elif event_type == "time_window_change":
            require(float(event["new_due_time"]) >= float(event["new_ready_time"]), f"time-window event {event_id} is inverted")
            nodes = [
                replace(
                    item,
                    ready_time=float(event["new_ready_time"]),
                    due_time=float(event["new_due_time"]),
                )
                if item.node_id == customer_id
                else item
                for item in nodes
            ]
            outcomes.append({"event_id": event_id, "event_type": event_type, "outcome": "window_changed_before_departure"})
        else:
            raise AuditFailure(f"unsupported event type {event_type!r}")
        applied.append(event_id)

    require(not (set(applied) & set(ignored)), "event is both applied and ignored")
    expected = {str(event["event_id"]) for event in events}
    require(set(applied) | set(ignored) == expected, "applied and ignored events do not partition batch")
    require(
        all(
            str(event["event_type"]).lower() != "add" or str(event["event_id"]) not in ignored
            for event in events
        ),
        "add event was ignored",
    )
    return EventApplication(
        instance=rebuild_instance(source, nodes),
        applied_event_ids=tuple(applied),
        ignored_locked_event_ids=tuple(ignored),
        outcomes=tuple(outcomes),
    )


def validate_event_stream(
    repo_root: Path,
    seed: int,
) -> tuple[list[dict[str, Any]], dict[str, str], list[TriggerBatch]]:
    event_root = repo_root / EVENT_ROOT
    events = read_json(event_root / f"stream_seed{seed}.events.json")
    require(isinstance(events, list), f"stream {seed} event file is not a list")
    require(len(events) == EXPECTED_EVENT_COUNT, f"stream {seed} event count")
    for event in events:
        validate_event_numeric_contract(
            event,
            f"stream {seed} event {event.get('event_id', '<missing>')}",
        )
    counts = {
        event_type: sum(str(event["event_type"]).lower() == event_type for event in events)
        for event_type in EXPECTED_EVENT_TYPES
    }
    require(counts == EXPECTED_EVENT_TYPES, f"stream {seed} event composition")
    require(all(int(event["seed"]) == seed for event in events), f"stream {seed} embedded seed")
    require(len({str(event["customer_id"]) for event in events}) == len(events), f"stream {seed} reused event customer")

    owner_rows = read_csv(event_root / f"stream_seed{seed}.owners.csv")
    owners = {row["customer_id"]: row["owner_depot_id"] for row in owner_rows}
    require(len(owners) == len(owner_rows), f"stream {seed} duplicate owner row")
    base_instance = load_search_bundle(repo_root / BASE_BUNDLE).instance
    original_customer_ids = _customer_ids(base_instance)
    validate_owner_population(
        owners,
        events,
        original_customer_ids,
        f"stream {seed}",
    )
    validate_owner_and_donor_provenance(
        repo_root,
        owners,
        events,
        base_instance,
        f"stream {seed}",
    )

    batches = derive_trigger_batches(events)
    require(len(batches) == EXPECTED_STAGE_COUNTS[seed], f"stream {seed} independently derived stage count")

    all_index_rows = read_csv(event_root / "raw_runs.csv")
    index_rows = [row for row in all_index_rows if int(row["seed"]) == seed]
    require(len(index_rows) == EXPECTED_EVENT_COUNT, f"stream {seed} frozen index count")
    index_by_id = unique_index(index_rows, ("event_id",), f"stream {seed} event index")
    trigger_by_event = {
        str(event["event_id"]): batch.trigger_second
        for batch in batches
        for event in batch.events
    }
    for event in events:
        event_id = str(event["event_id"])
        row = index_by_id[(event_id,)]
        require(row["event_type"] == event["event_type"], f"stream {seed} event {event_id} type/index")
        require(row["customer_id"] == event["customer_id"], f"stream {seed} event {event_id} customer/index")
        require(close(row["t_appear"], event["t_appear"]), f"stream {seed} event {event_id} appearance/index")
        require(close(row["trigger_second"], trigger_by_event[event_id]), f"stream {seed} event {event_id} trigger/index")
        require(row["status"] == "PASS", f"stream {seed} event {event_id} frozen status")
        require(int(row["search_evaluations"]) == 0, f"stream {seed} event {event_id} generation search count")
        require(truth(row["owner_rule_verified"]), f"stream {seed} event {event_id} owner rule")
        if str(event["event_type"]).lower() == "add":
            require(truth(row["donor_fields_inherited_exactly"]), f"stream {seed} add {event_id} donor fields")
            require(row["owner_depot_id"] == owners[event["customer_id"]], f"stream {seed} add {event_id} owner/index")
            require(row["donor_instance_id"] == event["donor_instance_id"], f"stream {seed} add {event_id} donor instance/index")
            require(row["donor_customer_id"] == event["donor_customer_id"], f"stream {seed} add {event_id} donor customer/index")
            require(row["service_time_source"] == event["service_time_source"], f"stream {seed} add {event_id} service source/index")
            require(close(row["x"], event["x"]), f"stream {seed} add {event_id} x/index")
            require(close(row["y"], event["y"]), f"stream {seed} add {event_id} y/index")
            require(close(row["new_demand"], event["new_demand"]), f"stream {seed} add {event_id} demand/index")
            require(close(row["new_ready_time"], event["new_ready_time"]), f"stream {seed} add {event_id} ready/index")
            require(close(row["new_due_time"], event["new_due_time"]), f"stream {seed} add {event_id} due/index")
            require(close(row["donor_service_time"], event["new_service_time"]), f"stream {seed} add {event_id} donor service/index")
            require(close(row["new_service_time"], event["new_service_time"]), f"stream {seed} add {event_id} service/index")
        else:
            require(truth(row["modifiable_in_both_fixed_seed1_plans"]), f"stream {seed} event {event_id} departure gate")
            require(float(row["minimum_uncommitted_margin_seconds"]) >= 60.0 - TOL, f"stream {seed} event {event_id} departure margin")
    return [dict(event) for event in events], owners, batches


def validate_search_counts(row: Mapping[str, Any], expected_evaluations: int) -> None:
    evaluations = int(row["evaluations"])
    changed = int(row["changed_candidate_count"])
    exact = int(row["search_exact_check_count"])
    executable = int(row["executable_candidate_count"])
    accepted = int(row["accepted_candidate_count"])
    rejection_payload = json.loads(str(row["search_rejection_counts_json"]))
    require(isinstance(rejection_payload, dict), "search rejection record is not an object")
    rejection_total = 0
    for key, value in rejection_payload.items():
        require(isinstance(key, str) and key, "search rejection has empty label")
        require(int(value) >= 0, f"search rejection {key} is negative")
        rejection_total += int(value)
    require(expected_evaluations >= 0, "expected evaluation budget is negative")
    require(evaluations == expected_evaluations, "stage evaluation budget")
    require(evaluations >= 0, "stage evaluations are negative")
    require(0 <= changed <= evaluations, "changed candidate count outside evaluation budget")
    require(0 <= exact <= evaluations, "exact-check count outside evaluation budget")
    require(0 <= executable <= exact, "executable candidate count outside exact checks")
    require(0 <= rejection_total <= exact, "rejection count outside exact checks")
    require(changed == exact, "changed candidates do not equal exact checks")
    require(exact == executable + rejection_total, "exact checks do not close to executable plus rejected")
    require(0 <= accepted <= executable, "accepted candidate count is outside executable count")


def validate_stage_timing(
    row: Mapping[str, Any],
    batch: TriggerBatch,
    next_batch: TriggerBatch | None,
) -> None:
    require(close(row["trigger_second"], batch.trigger_second), "stage trigger time")
    require(row["trigger_reason"] == batch.trigger_reason, "stage trigger reason")
    elapsed = float(row["elapsed_seconds"])
    require(math.isfinite(elapsed) and elapsed >= 0.0, "stage elapsed time")
    if next_batch is None:
        require(row["next_trigger_second"] in {"", None}, "last stage has a next trigger")
        require(row["available_compute_seconds"] in {"", None}, "last stage has an available window")
        require(row["completed_before_next_trigger"] in {"", None}, "last stage has a completion flag")
        return
    available = next_batch.trigger_second - batch.trigger_second
    require(available >= 0.0, "next trigger precedes current trigger")
    require(close(row["next_trigger_second"], next_batch.trigger_second), "next trigger time")
    require(close(row["available_compute_seconds"], available), "available compute window")
    require(elapsed <= available + TOL, "stage did not finish before next trigger")
    require(truth(row["completed_before_next_trigger"]), "stage completion flag")


def workload_ledger(instance: Instance) -> dict[str, dict[str, Any]]:
    return {
        node.node_id: {
            "demand": float(node.demand),
            "ready_time": float(node.ready_time),
            "due_time": float(node.due_time),
            "service_time": float(node.service_time),
        }
        for node in sorted(instance.nodes, key=lambda item: item.node_id)
        if node.node_type.lower() == "c"
    }


def _cross_site_services(
    routes: Sequence[Mapping[str, Any]],
    instance: Instance,
    owners: Mapping[str, str],
) -> tuple[dict[str, str], ...]:
    values: list[dict[str, str]] = []
    for route in routes:
        for customer_id in _route_customers(route, instance):
            require(customer_id in owners, f"customer {customer_id} has no owner")
            if owners[customer_id] != route["home_depot_id"]:
                values.append({
                    "customer_id": customer_id,
                    "served_by_depot_id": str(route["home_depot_id"]),
                })
    ids = [item["customer_id"] for item in values]
    require(len(ids) == len(set(ids)), "cross-site customer occurs more than once")
    return tuple(sorted(values, key=lambda item: (item["customer_id"], item["served_by_depot_id"])))


def _cross_site_ids(
    routes: Sequence[Mapping[str, Any]],
    instance: Instance,
    owners: Mapping[str, str],
) -> tuple[str, ...]:
    return tuple(
        item["customer_id"]
        for item in _cross_site_services(routes, instance, owners)
    )


def assert_stage_identity(
    stage_payload: Mapping[str, Any],
    raw: Mapping[str, Any],
    batch: TriggerBatch,
    stream_seed: int,
    arm: str,
    stage: int,
) -> None:
    label = f"stream {stream_seed} {arm} stage {stage}"
    require(stage_payload["arm"] == arm, f"{label} evidence arm")
    require(int(stage_payload["stream_seed"]) == stream_seed, f"{label} evidence stream")
    require(int(stage_payload["stage"]) == stage, f"{label} evidence stage")
    require_metric_close(stage_payload["trigger_second"], batch.trigger_second, f"{label} evidence trigger")
    require(raw["arm"] == arm, f"{label} raw arm")
    require(int(raw["stream_seed"]) == stream_seed, f"{label} raw stream")
    require(int(raw["stage"]) == stage, f"{label} raw stage")


def assert_dynamic_cross_site_fields(
    stage_payload: Mapping[str, Any],
    raw: Mapping[str, Any],
    dynamic_added_customer_ids: set[str],
    dynamic_cross_site_ids: Sequence[str],
    label: str,
) -> None:
    expected_dynamic = sorted(dynamic_added_customer_ids)
    expected_cross_site = sorted(dynamic_cross_site_ids)
    require(
        stage_payload["dynamic_added_customer_ids"] == expected_dynamic,
        f"{label} dynamic-added customer IDs",
    )
    require(
        stage_payload["dynamic_added_cross_site_customer_ids"] == expected_cross_site,
        f"{label} dynamic cross-site IDs",
    )
    require(
        int(raw["dynamic_added_customer_count"]) == len(expected_dynamic),
        f"{label} dynamic-added customer count",
    )
    require(
        int(raw["dynamic_added_cross_site_customer_count"]) == len(expected_cross_site),
        f"{label} dynamic cross-site count",
    )
    require(
        split_ids(raw["dynamic_added_cross_site_customer_ids"]) == expected_cross_site,
        f"{label} raw dynamic cross-site IDs",
    )


def assert_cross_site_annotation(
    recorded: Sequence[Mapping[str, Any]],
    expected: Sequence[Mapping[str, Any]],
    label: str,
) -> None:
    require(list(recorded) == list(expected), f"{label} cross-site annotation")


def validate_shared_start_contract(
    repo_root: Path,
    summary: Mapping[str, Any],
    base_instance: Instance,
    owners: Mapping[str, str],
) -> None:
    require(summary["initial_solution_path"] == INITIAL_SOLUTION_PATH, "fixed initial solution path")
    require(summary["initial_solution_sha256"] == INITIAL_SOLUTION_SHA256, "fixed initial solution hash")
    require(summary["initial_certificate_path"] == INITIAL_CERTIFICATE_PATH, "fixed initial certificate path")
    require(summary["initial_certificate_sha256"] == INITIAL_CERTIFICATE_SHA256, "fixed initial certificate hash")
    solution_path = safe_recorded_path(repo_root, INITIAL_SOLUTION_PATH)
    certificate_path = safe_recorded_path(repo_root, INITIAL_CERTIFICATE_PATH)
    require(sha256_file(solution_path) == INITIAL_SOLUTION_SHA256, "fixed initial solution bytes")
    require(sha256_file(certificate_path) == INITIAL_CERTIFICATE_SHA256, "fixed initial certificate bytes")
    solution_payload = read_json(solution_path)
    require(solution_payload.get("cross_site_services", []) == [], "fixed initial solution cross-site annotation")
    require(
        not _cross_site_services(solution_payload["routes"], base_instance, owners),
        "fixed initial solution recomputed cross-site service",
    )
    require(int(summary["initial_cross_site_customer_count"]) == 0, "fixed initial cross-site count")


def replay_session_records(
    *,
    repo_root: Path,
    run_dir: Path,
    stream_seed: int,
    arm: str,
    batches: Sequence[TriggerBatch],
    owners: Mapping[str, str],
    summary: Mapping[str, str],
    raw_by_key: Mapping[tuple[int, str, int], Mapping[str, str]],
    base_instance: Instance,
    carbon_profile: Sequence[Mapping[str, Any]],
    prices: Any,
) -> SessionReplay:
    assert_session_paths(repo_root, run_dir, stream_seed, arm, summary)
    validate_shared_start_contract(repo_root, summary, base_instance, owners)
    evidence_path = safe_recorded_path(repo_root, summary["stage_evidence_path"])
    require(sha256_file(evidence_path) == summary["stage_evidence_sha256"], f"stream {stream_seed} {arm} evidence file hash")
    evidence = read_json(evidence_path)
    require(len(evidence) == len(batches), f"stream {stream_seed} {arm} evidence stage count")

    initial_solution_path = safe_recorded_path(repo_root, summary["initial_solution_path"])
    initial_certificate_path = safe_recorded_path(repo_root, summary["initial_certificate_path"])
    current_solution = solution_from_dict(read_json(initial_solution_path))
    current_certificate = certificate_from_dict(read_json(initial_certificate_path))
    current_instance = base_instance
    initial_parts = evaluate_direct(current_solution, current_instance, carbon_profile, prices)
    require_metric_close(summary["initial_total_cost"], initial_parts["total_cost"], f"stream {stream_seed} {arm} initial total cost")
    require_metric_close(summary["initial_total_emissions"], initial_parts["E_total"], f"stream {stream_seed} {arm} initial emissions")
    require(int(summary["initial_route_count"]) == len(current_solution.routes), f"stream {stream_seed} {arm} initial route count")
    require(int(summary["initial_charging_action_count"]) == len(current_solution.charging_actions), f"stream {stream_seed} {arm} initial charge count")

    committed: set[str] = set()
    booked_route_ids: set[str] = set()
    booked_route_payloads: dict[str, dict[str, Any]] = {}
    booked_action_keys: set[tuple[Any, ...]] = set()
    billing_key_payloads: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    committed_parts: dict[str, float] = {}
    inherited_states: dict[str, DynamicAssetState] | None = None
    inherited_locked_actions: tuple[ChargingAction, ...] = ()
    previous_trigger: float | None = None
    locked_cancel_count = locked_change_count = 0
    removed_cancel_count = applied_change_count = 0
    applied_event_count = ignored_locked_event_count = 0
    dynamic_added_customer_ids: set[str] = set()
    committed_cross_site_customer_ids: set[str] = set()
    committed_dynamic_added_cross_site_ids: set[str] = set()

    for index, (batch, stage_payload) in enumerate(zip(batches, evidence), start=1):
        raw = raw_by_key[(stream_seed, arm, index)]
        expected_ids = [str(event["event_id"]) for event in batch.events]
        expected_types = [str(event["event_type"]) for event in batch.events]
        assert_stage_identity(stage_payload, raw, batch, stream_seed, arm, index)
        require(split_ids(raw["event_ids"]) == expected_ids, f"stream {stream_seed} {arm} stage {index} event ids")
        require(split_ids(raw["event_types"]) == expected_types, f"stream {stream_seed} {arm} stage {index} event types")
        require(int(raw["event_count"]) == len(batch.events), f"stream {stream_seed} {arm} stage {index} event count")
        validate_stage_timing(raw, batch, batches[index] if index < len(batches) else None)
        validate_search_counts(raw, EXPECTED_EVALUATIONS_PER_STAGE)
        validate_operator_pairs(raw["operator_pairs"], f"stream {stream_seed} {arm} stage {index}")
        require(int(raw["stage_search_seed"]) == stream_seed * 1000 + index, f"stream {stream_seed} {arm} stage {index} search seed")
        require(truth(raw["customer_accounting_pass"]), f"stream {stream_seed} {arm} stage {index} accounting flag")
        rejection_payload = json.loads(raw["search_rejection_counts_json"])
        duplicate_route_rejections = sum(
            int(value)
            for key, value in rejection_payload.items()
            if "route" in key.lower() and ("duplicate" in key.lower() or "not unique" in key.lower())
        )
        require(duplicate_route_rejections == 0, f"stream {stream_seed} {arm} stage {index} duplicate-route rejection")

        if index == 1:
            cut = derive_initial_cut(
                current_solution,
                current_certificate,
                current_instance,
                prices,
                batch.trigger_second,
            )
        else:
            require(inherited_states is not None and previous_trigger is not None, f"stream {stream_seed} {arm} stage {index} missing inherited state")
            cut = derive_later_cut(
                current_solution,
                current_certificate,
                current_instance,
                prices,
                inherited_states=inherited_states,
                previous_trigger=previous_trigger,
                inherited_locked_actions=inherited_locked_actions,
                trigger=batch.trigger_second,
            )

        label = f"stream {stream_seed} {arm} stage {index}"
        require(tuple(stage_payload["completed_route_ids"]) == cut.completed_route_ids, f"{label} completed route IDs")
        require(tuple(stage_payload["in_progress_route_ids"]) == cut.in_progress_route_ids, f"{label} in-progress route IDs")
        require(tuple(stage_payload["editable_route_ids"]) == cut.editable_route_ids, f"{label} editable route IDs")
        expected_locked_routes = [asdict(route) for route in cut.locked_routes]
        require(stage_payload["locked_routes"] == expected_locked_routes, f"{label} locked routes")
        require(stage_payload["locked_routes_sha256"] == canonical_sha256(expected_locked_routes), f"{label} locked route hash")
        assert_locked_actions_match(
            cut.locked_charging_actions,
            stage_payload["locked_charging_actions"],
            stage_payload["locked_charging_actions_sha256"],
            label,
        )
        require(raw["locked_routes_sha256"] == stage_payload["locked_routes_sha256"], f"{label} raw/evidence locked routes")
        require(raw["locked_charging_actions_sha256"] == stage_payload["locked_charging_actions_sha256"], f"{label} raw/evidence locked charging")
        assert_asset_states_match(cut.asset_states, stage_payload["asset_states"], label)

        new_locked_routes: list[Route] = []
        for route in cut.locked_routes:
            payload = asdict(route)
            route_id = route.vehicle_id
            previous_payload = booked_route_payloads.get(route_id)
            require(previous_payload is None or previous_payload == payload, f"{label} committed route ID changed payload: {route_id}")
            if route_id not in booked_route_ids:
                new_locked_routes.append(route)
                booked_route_ids.add(route_id)
                booked_route_payloads[route_id] = payload
                committed.update(_route_customers(payload, current_instance))
                new_cross_site = set(
                    _cross_site_ids((payload,), current_instance, owners)
                )
                committed_cross_site_customer_ids.update(new_cross_site)
                committed_dynamic_added_cross_site_ids.update(
                    new_cross_site & dynamic_added_customer_ids
                )
        if new_locked_routes:
            add_numeric_parts(
                committed_parts,
                evaluate_direct(
                    Solution(routes=new_locked_routes, charging_actions=[]),
                    current_instance,
                    carbon_profile,
                    prices,
                ),
            )

        new_locked_actions: list[ChargingAction] = []
        for action in cut.locked_charging_actions:
            billing_key = billing_action_key(action)
            full_key = full_action_key(action)
            prior_full = billing_key_payloads.get(billing_key)
            require(prior_full is None or prior_full == full_key, f"{label} ambiguous charging billing key")
            billing_key_payloads[billing_key] = full_key
            if billing_key not in booked_action_keys:
                new_locked_actions.append(action)
                booked_action_keys.add(billing_key)
        if new_locked_actions:
            add_numeric_parts(
                committed_parts,
                evaluate_direct(
                    Solution(routes=[], charging_actions=new_locked_actions),
                    current_instance,
                    carbon_profile,
                    prices,
                ),
            )

        require(int(raw["committed_route_count"]) == len(booked_route_ids), f"stream {stream_seed} {arm} stage {index} committed route count")
        require(len(stage_payload["asset_states"]) == 20, f"stream {stream_seed} {arm} stage {index} evidence asset count")
        require(int(raw["asset_state_count"]) == 20, f"stream {stream_seed} {arm} stage {index} raw asset count")
        require(stage_payload["asset_states_sha256"] == canonical_sha256(stage_payload["asset_states"]), f"stream {stream_seed} {arm} stage {index} asset-state hash")
        require(raw["asset_states_sha256"] == stage_payload["asset_states_sha256"], f"stream {stream_seed} {arm} stage {index} raw/evidence asset-state hash")
        recorded_committed = set(stage_payload["committed_customer_ids"])
        require(committed == recorded_committed, f"stream {stream_seed} {arm} stage {index} committed customer reconstruction")

        application = apply_event_batch(current_instance, batch.events, committed)
        require(split_ids(raw["applied_event_ids"]) == list(application.applied_event_ids), f"stream {stream_seed} {arm} stage {index} applied events")
        require(split_ids(raw["ignored_locked_event_ids"]) == list(application.ignored_locked_event_ids), f"stream {stream_seed} {arm} stage {index} locked events")
        applied_event_count += len(application.applied_event_ids)
        ignored_locked_event_count += len(application.ignored_locked_event_ids)
        applied_set = set(application.applied_event_ids)
        dynamic_added_customer_ids.update(
            str(event["customer_id"])
            for event in batch.events
            if str(event["event_id"]) in applied_set
            and str(event["event_type"]).lower() == "add"
        )
        for outcome in application.outcomes:
            if outcome["outcome"] == "locked_original_honored" and outcome["event_type"] == "cancel":
                locked_cancel_count += 1
            elif outcome["outcome"] == "locked_original_honored":
                locked_change_count += 1
            elif outcome["outcome"] == "removed_before_departure":
                removed_cancel_count += 1
            elif outcome["outcome"] in {"demand_changed_before_departure", "window_changed_before_departure"}:
                applied_change_count += 1

        current_instance = application.instance
        stage_solution = solution_from_dict(stage_payload["solution"])
        stage_certificate = certificate_from_dict(stage_payload["certificate"])
        validate_dynamic_multitrip_certificate(
            stage_solution,
            stage_certificate,
            current_instance,
            prices,
            asset_states=cut.asset_states,
            stage_start_second=batch.trigger_second,
            locked_charging_actions=cut.locked_charging_actions,
        )
        require(stage_certificate.status == "PASS", f"{label} independently replayed certificate status")
        require(stage_payload["certificate_status"] == "PASS", f"{label} evidence certificate status")
        require(stage_payload["certificate_vehicle_counts"] == stage_payload["certificate"]["vehicle_counts"], f"{label} certificate vehicle counts")

        active = _customer_ids(current_instance)
        future_routes = stage_payload["solution"]["routes"]
        flat_future = [
            customer_id
            for route in future_routes
            for customer_id in _route_customers(route, current_instance)
        ]
        require(len(flat_future) == len(set(flat_future)), f"stream {stream_seed} {arm} stage {index} duplicate future customer")
        future = set(flat_future)
        require(committed.isdisjoint(future), f"stream {stream_seed} {arm} stage {index} committed/future overlap")
        require(committed | future == active, f"stream {stream_seed} {arm} stage {index} customer coverage")

        expected_sets = {
            "active_customer_ids": sorted(active),
            "committed_customer_ids": sorted(committed),
            "future_customer_ids": sorted(future),
        }
        for field, expected in expected_sets.items():
            require(stage_payload[field] == expected, f"stream {stream_seed} {arm} stage {index} {field}")
            require(stage_payload[f"{field}_sha256"] == canonical_sha256(expected), f"stream {stream_seed} {arm} stage {index} {field} hash")
            require(raw[f"{field}_sha256"] == stage_payload[f"{field}_sha256"], f"stream {stream_seed} {arm} stage {index} raw/evidence {field}")
        require(int(raw["active_customer_count"]) == len(active), f"stream {stream_seed} {arm} stage {index} active count")
        require(int(raw["committed_customer_count"]) == len(committed), f"stream {stream_seed} {arm} stage {index} committed count")
        require(int(raw["future_customer_count"]) == len(future), f"stream {stream_seed} {arm} stage {index} future count")
        require(int(raw["future_route_count"]) == len(future_routes), f"stream {stream_seed} {arm} stage {index} future route count")

        cross_site_services = _cross_site_services(future_routes, current_instance, owners)
        cross_site = tuple(item["customer_id"] for item in cross_site_services)
        assert_cross_site_annotation(
            stage_payload["solution"]["cross_site_services"],
            list(cross_site_services),
            f"stream {stream_seed} {arm} stage {index}",
        )
        require(int(raw["cross_site_customer_count"]) == len(cross_site), f"stream {stream_seed} {arm} stage {index} cross-site count")
        stage_dynamic_cross_site = tuple(sorted(
            committed_dynamic_added_cross_site_ids
            | (set(cross_site) & dynamic_added_customer_ids)
        ))
        assert_dynamic_cross_site_fields(
            stage_payload,
            raw,
            dynamic_added_customer_ids,
            stage_dynamic_cross_site,
            f"stream {stream_seed} {arm} stage {index}",
        )
        if arm == "independent":
            require(
                not cross_site and not committed_cross_site_customer_ids,
                f"stream {stream_seed} independent stage {index} crossed depot",
            )

        require(stage_payload["solution_sha256"] == canonical_sha256(stage_payload["solution"]), f"stream {stream_seed} {arm} stage {index} solution hash")
        require(stage_payload["certificate_sha256"] == canonical_sha256(stage_payload["certificate"]), f"stream {stream_seed} {arm} stage {index} certificate hash")
        require(raw["stage_solution_sha256"] == stage_payload["solution_sha256"], f"stream {stream_seed} {arm} stage {index} raw solution hash")
        require(raw["stage_certificate_sha256"] == stage_payload["certificate_sha256"], f"stream {stream_seed} {arm} stage {index} raw certificate hash")
        require(raw["stage_certificate_status"] == "PASS", f"stream {stream_seed} {arm} stage {index} certificate status flag")

        future_parts = evaluate_direct(stage_solution, current_instance, carbon_profile, prices)
        running_parts = dict(committed_parts)
        add_numeric_parts(running_parts, future_parts)
        assert_cost_breakdown(stage_payload["cost_breakdown"], running_parts, f"{label} cost breakdown")
        require_metric_close(raw["future_cost"], future_parts["total_cost"], f"{label} future cost")
        require_metric_close(raw["running_total_cost"], running_parts["total_cost"], f"{label} running total cost")

        inherited_states = dict(cut.asset_states)
        inherited_locked_actions = tuple(cut.locked_charging_actions)
        previous_trigger = batch.trigger_second
        current_solution = stage_solution
        current_certificate = stage_certificate

    final_workload = workload_ledger(current_instance)
    final_routes = evidence[-1]["solution"]["routes"]
    final_cross_site = _cross_site_ids(final_routes, current_instance, owners)
    final_dynamic_cross_site = tuple(sorted(
        committed_dynamic_added_cross_site_ids
        | (set(final_cross_site) & dynamic_added_customer_ids)
    ))
    final_solution_payload = read_json(safe_recorded_path(repo_root, summary["final_solution_path"]))
    final_certificate_payload = read_json(safe_recorded_path(repo_root, summary["final_certificate_path"]))
    require(final_solution_payload == evidence[-1]["solution"], f"stream {stream_seed} {arm} final solution/evidence")
    require(final_certificate_payload == evidence[-1]["certificate"], f"stream {stream_seed} {arm} final certificate/evidence")
    remaining_actions = [
        action
        for action in current_solution.charging_actions
        if billing_action_key(action) not in booked_action_keys
    ]
    final_parts = dict(committed_parts)
    add_numeric_parts(
        final_parts,
        evaluate_direct(
            Solution(
                routes=list(current_solution.routes),
                charging_actions=remaining_actions,
                cross_site_services=list(current_solution.cross_site_services),
            ),
            current_instance,
            carbon_profile,
            prices,
        ),
    )
    require_metric_close(summary["final_total_cost"], final_parts["total_cost"], f"stream {stream_seed} {arm} final total cost")
    require_metric_close(summary["final_total_emissions"], final_parts["E_total"], f"stream {stream_seed} {arm} final emissions")
    require(
        int(summary["final_cross_site_customer_count"]) == len(final_cross_site),
        f"stream {stream_seed} {arm} final cross-site count",
    )
    require(
        int(summary["final_dynamic_added_cross_site_customer_count"])
        == len(final_dynamic_cross_site),
        f"stream {stream_seed} {arm} final dynamic cross-site count",
    )
    require(
        split_ids(summary["final_dynamic_added_cross_site_customer_ids"])
        == list(final_dynamic_cross_site),
        f"stream {stream_seed} {arm} final dynamic cross-site IDs",
    )
    return SessionReplay(
        stream_seed=stream_seed,
        arm=arm,
        stage_count=len(batches),
        final_workload=final_workload,
        final_workload_sha256=canonical_sha256(final_workload),
        final_customer_count=len(final_workload),
        final_total_demand=sum(item["demand"] for item in final_workload.values()),
        locked_cancel_count=locked_cancel_count,
        locked_change_count=locked_change_count,
        removed_cancel_count=removed_cancel_count,
        applied_change_count=applied_change_count,
        applied_event_count=applied_event_count,
        ignored_locked_event_count=ignored_locked_event_count,
        final_cross_site_customer_ids=final_cross_site,
        final_dynamic_added_cross_site_customer_ids=final_dynamic_cross_site,
        final_total_cost=float(final_parts["total_cost"]),
        final_total_emissions=float(final_parts["E_total"]),
    )


def verify_recorded_file(repo_root: Path, row: Mapping[str, str], path_key: str, hash_key: str) -> None:
    path = safe_recorded_path(repo_root, row[path_key])
    require(sha256_file(path) == row[hash_key], f"recorded hash mismatch: {row[path_key]}")


def validate_decision_event_counts(
    decision: Mapping[str, Any],
    raw_rows: Sequence[Mapping[str, Any]],
    replayed: Mapping[tuple[int, str], SessionReplay] | None = None,
) -> tuple[int, int]:
    applied = sum(len(split_ids(row["applied_event_ids"])) for row in raw_rows)
    ignored = sum(len(split_ids(row["ignored_locked_event_ids"])) for row in raw_rows)
    require(int(decision["applied_event_count"]) == applied, "decision applied-event count")
    require(int(decision["locked_late_event_count"]) == ignored, "decision locked-event count")
    expected_per_arm = EXPECTED_EVENT_COUNT * len(EXPECTED_STREAMS)
    for arm in EXPECTED_ARMS:
        arm_total = sum(
            int(row["event_count"])
            for row in raw_rows
            if row["arm"] == arm
        )
        require(arm_total == expected_per_arm, f"{arm} full event coverage")
    require(
        applied + ignored == expected_per_arm * len(EXPECTED_ARMS),
        "all formal events partition into applied or locked",
    )
    if replayed is not None:
        require(
            applied == sum(item.applied_event_count for item in replayed.values()),
            "raw/replay applied-event count",
        )
        require(
            ignored == sum(item.ignored_locked_event_count for item in replayed.values()),
            "raw/replay locked-event count",
        )
    return applied, ignored


def validate_artifact_manifest(repo_root: Path, run_dir: Path) -> None:
    manifest = read_json(run_dir / "artifact_hashes.json")
    require(manifest["algorithm"] == "sha256", "artifact hash algorithm")
    listed = unique_index(manifest["artifacts"], ("path",), "artifact manifest path")
    actual = {
        str(path.relative_to(repo_root)): path
        for path in run_dir.rglob("*")
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    require(set(key[0] for key in listed) == set(actual), "artifact inventory")
    for (relative,), row in listed.items():
        path = actual[relative]
        require(row["sha256"] == sha256_file(path), f"artifact hash: {relative}")
        require(int(row["bytes"]) == path.stat().st_size, f"artifact bytes: {relative}")


def validate_formal_run(repo_root: Path, run_dir: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    run_dir = run_dir.resolve()
    require(run_dir.is_relative_to(repo_root), "run directory is outside repository")
    metadata = read_json(run_dir / "metadata.json")
    decision = read_json(run_dir / "decision.json")
    raw_rows = read_csv(run_dir / "raw_runs.csv")
    session_rows = read_csv(run_dir / "session_summary.csv")
    paired_rows = read_csv(run_dir / "paired_summary.csv")

    validate_formal_metadata_contract(metadata, decision)
    require(metadata["trigger_mode"] == "batched", "formal trigger mode")
    require(int(metadata["q_bar"]) == Q_BAR, "formal q_bar")
    require(metadata["network"] == "L-main-threeshift-100c-01", "formal network")
    require(metadata["customer_count"] == 221, "formal customer count metadata")
    require(metadata["fleet"] == {"cv": 10, "ev": 10}, "formal fleet metadata")
    require(metadata["shared_initial_plan"] is True, "shared initial plan flag")
    require(metadata["treatment_difference"] == "cross-depot service permission only", "single treatment flag")
    require(metadata["result_direction_used_to_continue"] is False, "result direction guard")
    require(int(metadata["evaluations_per_stage"]) == EXPECTED_EVALUATIONS_PER_STAGE, "formal evaluation budget")
    validate_source_binding(repo_root, metadata)
    require(decision["passed"] is True, "internal formal decision")
    require(decision["verdict"] == "E7_PAIRED_FORMAL_PASS", "formal internal verdict")
    require(int(decision["failure_count"]) == 0, "formal failure count")
    require(int(decision["session_count"]) == EXPECTED_SESSION_COUNT, "formal decision session count")
    require(int(decision["paired_stream_count"]) == EXPECTED_PAIR_COUNT, "formal decision pair count")
    require(decision["zero_customer_loss"] is True, "formal customer-loss flag")
    require(decision["all_stages_completed_before_next_trigger"] is True, "formal timing flag")
    require(not (run_dir / "failures.csv").exists(), "formal failure file exists")

    require(len(raw_rows) == EXPECTED_RAW_STAGE_COUNT, "formal raw stage count")
    require(len(session_rows) == EXPECTED_SESSION_COUNT, "formal session count")
    require(len(paired_rows) == EXPECTED_PAIR_COUNT, "formal pair count")
    require(sum(int(row["evaluations"]) for row in raw_rows) == EXPECTED_TOTAL_EVALUATIONS, "formal total evaluations")

    raw_by_key = {
        (int(key[0]), key[1], int(key[2])): row
        for key, row in unique_index(raw_rows, ("stream_seed", "arm", "stage"), "raw stage").items()
    }
    session_by_key = {
        (int(key[0]), key[1]): row
        for key, row in unique_index(session_rows, ("stream_seed", "arm"), "session").items()
    }
    require(
        set(session_by_key)
        == {(seed, arm) for seed in EXPECTED_STREAMS for arm in EXPECTED_ARMS},
        "formal session coverage",
    )
    pair_by_seed = {
        int(key[0]): row
        for key, row in unique_index(paired_rows, ("stream_seed",), "paired stream").items()
    }
    require(set(pair_by_seed) == set(EXPECTED_STREAMS), "paired stream coverage")

    bundle = load_search_bundle(repo_root / BASE_BUNDLE)
    prices = formal_prices()
    require(sum(node.node_type.lower() == "c" for node in bundle.instance.nodes) == 221, "formal base customer count")
    require((bundle.instance.num_cv, bundle.instance.num_ev) == (10, 10), "formal base fleet")

    stream_contracts: dict[int, tuple[list[dict[str, Any]], dict[str, str], list[TriggerBatch]]] = {}
    for seed in EXPECTED_STREAMS:
        stream_contracts[seed] = validate_event_stream(repo_root, seed)

    replayed: dict[tuple[int, str], SessionReplay] = {}
    for seed in EXPECTED_STREAMS:
        _, owners, batches = stream_contracts[seed]
        require(len(batches) == EXPECTED_STAGE_COUNTS[seed], f"stream {seed} formal stage count")
        cooperative = session_by_key[(seed, "cooperative")]
        independent = session_by_key[(seed, "independent")]
        for field in (
            "initial_solution_sha256",
            "initial_certificate_sha256",
            "event_sha256",
            "owner_sha256",
            "initial_total_cost",
            "initial_total_emissions",
            "initial_route_count",
            "initial_charging_action_count",
            "initial_cross_site_customer_count",
        ):
            require(cooperative[field] == independent[field], f"stream {seed} shared start {field}")

        for arm, summary in (("cooperative", cooperative), ("independent", independent)):
            require(int(summary["stages"]) == EXPECTED_STAGE_COUNTS[seed], f"stream {seed} {arm} summary stages")
            require(int(summary["evaluations_per_stage"]) == EXPECTED_EVALUATIONS_PER_STAGE, f"stream {seed} {arm} summary budget")
            require(int(summary["total_evaluations"]) == EXPECTED_STAGE_COUNTS[seed] * EXPECTED_EVALUATIONS_PER_STAGE, f"stream {seed} {arm} summary evaluations")
            require(truth(summary["customer_accounting_pass"]), f"stream {seed} {arm} summary customer flag")
            for path_key, hash_key in (
                ("event_path", "event_sha256"),
                ("owner_path", "owner_sha256"),
                ("initial_solution_path", "initial_solution_sha256"),
                ("initial_certificate_path", "initial_certificate_sha256"),
                ("final_solution_path", "final_solution_sha256"),
                ("final_certificate_path", "final_certificate_sha256"),
                ("stage_evidence_path", "stage_evidence_sha256"),
            ):
                verify_recorded_file(repo_root, summary, path_key, hash_key)
            replayed[(seed, arm)] = replay_session_records(
                repo_root=repo_root,
                run_dir=run_dir,
                stream_seed=seed,
                arm=arm,
                batches=batches,
                owners=owners,
                summary=summary,
                raw_by_key=raw_by_key,
                base_instance=bundle.instance,
                carbon_profile=bundle.carbon_profile,
                prices=prices,
            )

        for stage in range(1, EXPECTED_STAGE_COUNTS[seed] + 1):
            left = raw_by_key[(seed, "cooperative", stage)]
            right = raw_by_key[(seed, "independent", stage)]
            for field in (
                "trigger_second",
                "trigger_reason",
                "event_ids",
                "event_types",
                "event_count",
                "evaluations",
                "stage_search_seed",
                "operator_pairs",
            ):
                require(left[field] == right[field], f"stream {seed} stage {stage} paired {field}")

        pair = pair_by_seed[seed]
        cooperative_cost = float(pair["cooperative_total_cost"])
        independent_cost = float(pair["independent_total_cost"])
        cooperative_replay = replayed[(seed, "cooperative")]
        independent_replay = replayed[(seed, "independent")]
        require_metric_close(
            cooperative_cost,
            cooperative_replay.final_total_cost,
            f"stream {seed} pair/cooperative cost",
        )
        require_metric_close(
            independent_cost,
            independent_replay.final_total_cost,
            f"stream {seed} pair/independent cost",
        )
        require_metric_close(
            pair["cooperative_total_emissions"],
            cooperative_replay.final_total_emissions,
            f"stream {seed} pair/cooperative emissions",
        )
        require_metric_close(
            pair["independent_total_emissions"],
            independent_replay.final_total_emissions,
            f"stream {seed} pair/independent emissions",
        )
        require_metric_close(
            pair["cooperative_saving_percent"],
            100.0 * (independent_cost - cooperative_cost) / independent_cost,
            f"stream {seed} pair saving arithmetic",
        )

    validate_decision_event_counts(decision, raw_rows, replayed)
    validate_artifact_manifest(repo_root, run_dir)

    pair_audits: list[dict[str, Any]] = []
    for seed in EXPECTED_STREAMS:
        cooperative = replayed[(seed, "cooperative")]
        independent = replayed[(seed, "independent")]
        differing_customers = sorted(
            customer_id
            for customer_id in set(cooperative.final_workload) | set(independent.final_workload)
            if cooperative.final_workload.get(customer_id) != independent.final_workload.get(customer_id)
        )
        pair_audits.append(
            {
                "stream_seed": seed,
                "final_service_ledger_equal": not differing_customers,
                "differing_customer_ids": differing_customers,
                "cooperative_customer_count": cooperative.final_customer_count,
                "independent_customer_count": independent.final_customer_count,
                "customer_count_delta": cooperative.final_customer_count - independent.final_customer_count,
                "cooperative_total_demand": cooperative.final_total_demand,
                "independent_total_demand": independent.final_total_demand,
                "total_demand_delta": cooperative.final_total_demand - independent.final_total_demand,
                "cooperative_locked_cancel_count": cooperative.locked_cancel_count,
                "independent_locked_cancel_count": independent.locked_cancel_count,
                "cooperative_locked_change_count": cooperative.locked_change_count,
                "independent_locked_change_count": independent.locked_change_count,
                "cost_comparison_requires_workload_note": bool(differing_customers),
            }
        )

    return {
        "verdict": "RECORD_LAYER_PASS",
        "run_dir": str(run_dir.relative_to(repo_root)),
        "stage_counts": EXPECTED_STAGE_COUNTS,
        "session_count": len(session_rows),
        "pair_count": len(paired_rows),
        "raw_stage_count": len(raw_rows),
        "total_evaluations": sum(int(row["evaluations"]) for row in raw_rows),
        "source_commit": metadata["source_commit"],
        "operator_pair_count": len(EXPECTED_OPERATOR_PAIRS),
        "operator_pairs_sha256": EXPECTED_OPERATOR_PAIRS_SHA256,
        "independence_scope": (
            "Independent reconstruction of records, events, locked work and inherited states; "
            "intentionally shares the bottom-level cost evaluator, strict scheduling checker, "
            "data classes and initial-certificate execution ledger, so this is not a second "
            "implementation of the physical model."
        ),
        "pair_workload_audits": pair_audits,
        "not_covered": [
            "external-clock proof of elapsed_seconds (the record layer checks arithmetic only)",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--repo-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = validate_formal_run(args.repo_root, args.run_dir)
    except (AuditFailure, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"verdict": "FAIL", "error": str(error)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
