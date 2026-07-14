#!/usr/bin/env python3
"""Additive, zero-search E3 ownership and fallback diagnostics.

This script does not change any sealed E3 artifact.  It performs four bounded
read-only/additive tasks:

1. deterministically derive one medium-mismatch ownership map per formal
   network from the sealed geographic and mixed maps;
2. measure geographic/medium/mixed ownership mismatch without route search;
3. measure cross-depot service scale in the 54 sealed paired solutions; and
4. verify that every sealed ownership-fixed solution remains a legal fallback
   when cross-depot reassignment is permitted.

The medium map is outcome-blind.  It is frozen before the paired-cost files are
opened and its selector can read only customer ids, demands, owner labels and
customer-to-depot distances.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import csv
import hashlib
import heapq
import inspect
import itertools
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e3_ablation.e3_ownership_class_design_20260713 import (  # noqa: E402
    customer_shift_map,
    demand_quartiles,
)
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.search.evaluation import cross_depot_violations  # noqa: E402
from setp_solver.search.instance_registry import FORMAL_INSTANCE_ORDER, instance_abs_dir  # noqa: E402


OWNERSHIP_ROOT = ROOT / "baselines/e3_ablation/e3_ownership_class_design_v4_20260713"
FORMAL_ROOT = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713"
DEFAULT_OUT = ROOT / "baselines/e3_ablation/e3_medium_ownership_diagnostic_20260715"
OWNERSHIP_GENERATOR = ROOT / "baselines/e3_ablation/e3_ownership_class_design_20260713.py"
FORMAL_GENERATOR = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_20260713.py"
EVALUATION_SOURCE = ROOT / "solver/src/setp_solver/search/evaluation.py"
BEAM_SIZE = 2500
MAX_BLOCK_CHOICES = 192
EPS = 1e-12


@dataclass(frozen=True)
class RestorePair:
    block: tuple[int, int]
    geographic_d0_customer: str
    geographic_d1_customer: str
    removed_mismatch_numerator: float
    d0_demand_delta: float

    @property
    def customer_ids(self) -> tuple[str, str]:
        return (self.geographic_d0_customer, self.geographic_d1_customer)


@dataclass(frozen=True)
class BlockChoice:
    removed_mismatch_numerator: float
    d0_demand_delta: float
    selected_pair_indices: tuple[int, ...]


@dataclass(frozen=True)
class BeamState:
    removed_mismatch_numerator: float
    d0_demand_delta: float
    selected_pair_indices: tuple[int, ...]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")


def write_csv(path: Path, rows: list[dict[str, Any]], *, fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is not None:
        names = fieldnames
    elif rows:
        names = list(rows[0])
        seen = set(names)
        for row in rows[1:]:
            for name in row:
                if name not in seen:
                    names.append(name)
                    seen.add(name)
    else:
        names = ["status"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_owner_map(path: Path) -> dict[str, str]:
    rows = load_csv(path)
    owners = {row["customer_id"]: row["owner_depot_id"] for row in rows}
    if len(owners) != len(rows):
        raise RuntimeError(f"duplicate customer in ownership map: {path}")
    return owners


def write_owner_map(path: Path, owners: dict[str, str]) -> None:
    write_csv(
        path,
        [
            {"customer_id": customer_id, "owner_depot_id": owners[customer_id]}
            for customer_id in sorted(owners)
        ],
        fieldnames=["customer_id", "owner_depot_id"],
    )


def git_blob_sha256(commit: str, relative_path: str) -> str:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return hashlib.sha256(completed.stdout).hexdigest()


def verify_sealed_inputs() -> dict[str, Any]:
    ownership_metadata = json.loads((OWNERSHIP_ROOT / "metadata.json").read_text(encoding="utf-8"))
    formal_metadata = json.loads((FORMAL_ROOT / "metadata.json").read_text(encoding="utf-8"))
    formal_hashes = json.loads((FORMAL_ROOT / "artifact_hashes.json").read_text(encoding="utf-8"))

    if sha256(OWNERSHIP_GENERATOR) != ownership_metadata["generator_sha256"]:
        raise RuntimeError("ownership generator drifted; grouping cannot be reconstructed safely")
    expected_formal_generator = formal_metadata["source_hashes"][str(FORMAL_GENERATOR.relative_to(ROOT))]
    if sha256(FORMAL_GENERATOR) != expected_formal_generator:
        raise RuntimeError("formal E3 generator drifted")
    active_manifest = ROOT / ownership_metadata["active_manifest"]
    if sha256(active_manifest) != ownership_metadata["active_manifest_sha256"]:
        raise RuntimeError("active L-main manifest drifted from the sealed ownership design")

    source_commit = str(formal_metadata["source_commit"])
    evaluation_rel = str(EVALUATION_SOURCE.relative_to(ROOT))
    evaluation_at_formal = git_blob_sha256(source_commit, evaluation_rel)
    if sha256(EVALUATION_SOURCE) != evaluation_at_formal:
        raise RuntimeError("cross-depot legality rule differs from the formal E3 source commit")
    source_text = inspect.getsource(cross_depot_violations)
    if "if context.allow_cross_depot or not context.customer_home_depot:" not in source_text:
        raise RuntimeError("open-cooperation rule no longer purely relaxes the owner lock")

    required = [
        "paired_results.csv",
        "raw_runs.csv",
        "metadata.json",
        "decision.json",
    ]
    for relative in required:
        expected = formal_hashes.get(relative)
        if expected is None or sha256(FORMAL_ROOT / relative) != expected:
            raise RuntimeError(f"sealed formal artifact missing or drifted: {relative}")
    return {
        "ownership_metadata": ownership_metadata,
        "formal_metadata": formal_metadata,
        "formal_hashes": formal_hashes,
        "evaluation_source_sha256": evaluation_at_formal,
    }


def quantile_positions(length: int, wanted: int) -> list[int]:
    if length <= wanted:
        return list(range(length))
    return sorted({round(index * (length - 1) / (wanted - 1)) for index in range(wanted)})


def enumerate_block_choices(
    pair_indices: list[int],
    pairs: list[RestorePair],
) -> list[BlockChoice]:
    pair_count = len(pair_indices)
    allowed_counts = sorted({pair_count // 2, (pair_count + 1) // 2})
    choices: list[BlockChoice] = []
    for count in allowed_counts:
        for selected in itertools.combinations(pair_indices, count):
            choices.append(
                BlockChoice(
                    removed_mismatch_numerator=sum(pairs[index].removed_mismatch_numerator for index in selected),
                    d0_demand_delta=sum(pairs[index].d0_demand_delta for index in selected),
                    selected_pair_indices=tuple(selected),
                )
            )
    if len(choices) <= MAX_BLOCK_CHOICES:
        return sorted(choices, key=lambda item: item.selected_pair_indices)

    block_mismatch_target = 0.5 * sum(pairs[index].removed_mismatch_numerator for index in pair_indices)
    block_demand_target = 0.5 * sum(pairs[index].d0_demand_delta for index in pair_indices)
    locally_ranked = sorted(
        choices,
        key=lambda item: (
            abs(item.removed_mismatch_numerator - block_mismatch_target),
            abs(item.d0_demand_delta - block_demand_target),
            item.selected_pair_indices,
        ),
    )
    by_mismatch = sorted(choices, key=lambda item: (item.removed_mismatch_numerator, item.selected_pair_indices))
    by_demand = sorted(choices, key=lambda item: (item.d0_demand_delta, item.selected_pair_indices))
    selected: dict[tuple[int, ...], BlockChoice] = {
        item.selected_pair_indices: item for item in locally_ranked[:96]
    }
    for ordered in (by_mismatch, by_demand):
        for position in quantile_positions(len(ordered), 48):
            item = ordered[position]
            selected[item.selected_pair_indices] = item
    return sorted(selected.values(), key=lambda item: item.selected_pair_indices)


def select_restored_pairs(
    pairs: list[RestorePair],
    *,
    mixed_d0_demand: float,
    geographic_d0_demand: float,
    max_absolute_demand_drift: float,
) -> tuple[int, ...]:
    """Select a deterministic, paired half-restoration without using costs."""

    if not pairs:
        return ()
    by_block: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, pair in enumerate(pairs):
        by_block[pair.block].append(index)

    total_mismatch = sum(pair.removed_mismatch_numerator for pair in pairs)
    target_removed = 0.5 * total_mismatch
    total_demand_delta = geographic_d0_demand - mixed_d0_demand
    states = [BeamState(0.0, 0.0, ())]
    processed_mismatch = 0.0
    processed_demand_delta = 0.0
    for block in sorted(by_block):
        indices = sorted(by_block[block])
        choices = enumerate_block_choices(indices, pairs)
        processed_mismatch += sum(pairs[index].removed_mismatch_numerator for index in indices)
        processed_demand_delta += sum(pairs[index].d0_demand_delta for index in indices)
        mismatch_target_so_far = 0.5 * processed_mismatch
        demand_target_so_far = 0.5 * processed_demand_delta

        def candidates() -> Iterable[BeamState]:
            for state in states:
                for choice in choices:
                    yield BeamState(
                        state.removed_mismatch_numerator + choice.removed_mismatch_numerator,
                        state.d0_demand_delta + choice.d0_demand_delta,
                        state.selected_pair_indices + choice.selected_pair_indices,
                    )

        states = heapq.nsmallest(
            BEAM_SIZE,
            candidates(),
            key=lambda state: (
                abs(state.removed_mismatch_numerator - mismatch_target_so_far) / max(total_mismatch, 1.0),
                abs(state.d0_demand_delta - demand_target_so_far) / max(abs(total_demand_delta), 1.0),
                state.selected_pair_indices,
            ),
        )

    feasible = [
        state
        for state in states
        if len(state.selected_pair_indices) in {len(pairs) // 2, (len(pairs) + 1) // 2}
        and
        abs(mixed_d0_demand + state.d0_demand_delta - geographic_d0_demand)
        <= max_absolute_demand_drift + EPS
    ]
    if not feasible:
        raise RuntimeError("no deterministic half-restoration satisfies the sealed demand-drift bound")
    winner = min(
        feasible,
        key=lambda state: (
            abs(state.removed_mismatch_numerator - target_removed),
            abs(mixed_d0_demand + state.d0_demand_delta - geographic_d0_demand),
            state.selected_pair_indices,
        ),
    )
    return tuple(sorted(winner.selected_pair_indices))


def mismatch_index(
    bundle: Any,
    customers: dict[str, Any],
    geographic: dict[str, str],
    owners: dict[str, str],
) -> tuple[float, float, float]:
    denominator = sum(
        float(customers[customer_id].demand) * float(bundle.instance.distance(customer_id, geographic[customer_id]))
        for customer_id in sorted(customers)
    )
    numerator = sum(
        float(customers[customer_id].demand)
        * (
            float(bundle.instance.distance(customer_id, owners[customer_id]))
            - float(bundle.instance.distance(customer_id, geographic[customer_id]))
        )
        for customer_id in sorted(customers)
    )
    if denominator <= 0.0:
        raise RuntimeError("non-positive geographic demand-distance denominator")
    return numerator / denominator, numerator, denominator


def counts_by_block(owners: dict[str, str], blocks: dict[str, tuple[int, int]]) -> Counter[tuple[int, int, str]]:
    return Counter((blocks[customer_id][0], blocks[customer_id][1], owner) for customer_id, owner in owners.items())


def build_medium_maps(out: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    sealed_audit = load_csv(OWNERSHIP_ROOT / "customer_assignment_audit.csv")
    sealed_grouping = {
        (row["instance"], row["customer_id"]): (int(row["shift"]) - 1, int(row["demand_quartile"]) - 1)
        for row in sealed_audit
    }
    structure_rows: list[dict[str, Any]] = []
    customer_rows: list[dict[str, Any]] = []
    map_hashes: dict[str, str] = {}

    for instance_id in FORMAL_INSTANCE_ORDER:
        active_bundle_dir = instance_abs_dir(ROOT, instance_id)
        bundle = load_search_bundle(active_bundle_dir)
        customer_nodes = [node for node in bundle.instance.nodes if str(node.node_type).lower() == "c"]
        customers = {node.node_id: node for node in customer_nodes}
        shifts = customer_shift_map(active_bundle_dir)
        quartiles = demand_quartiles(customer_nodes, shifts)
        rebuilt_blocks = {customer_id: (shifts[customer_id], quartiles[customer_id]) for customer_id in customers}
        if set(rebuilt_blocks) != set(customers):
            raise RuntimeError(f"customer shift reconstruction incomplete for {instance_id}")
        for customer_id, block in rebuilt_blocks.items():
            if sealed_grouping.get((instance_id, customer_id)) != block:
                raise RuntimeError(f"sealed shift/demand block cannot be reconstructed: {instance_id}/{customer_id}")

        geographic_path = OWNERSHIP_ROOT / "ownership_maps" / f"{instance_id}__geographic.csv"
        mixed_path = OWNERSHIP_ROOT / "ownership_maps" / f"{instance_id}__mixed.csv"
        geographic = load_owner_map(geographic_path)
        mixed = load_owner_map(mixed_path)
        if set(geographic) != set(customers) or set(mixed) != set(customers):
            raise RuntimeError(f"ownership/customer mismatch for {instance_id}")
        depots = sorted(set(geographic.values()))
        if len(depots) != 2:
            raise RuntimeError(f"medium ownership design requires exactly two depots: {instance_id}")
        d0, d1 = depots

        pairs: list[RestorePair] = []
        changed_by_block: dict[tuple[int, int], list[str]] = defaultdict(list)
        for customer_id in sorted(customers):
            if geographic[customer_id] != mixed[customer_id]:
                changed_by_block[rebuilt_blocks[customer_id]].append(customer_id)
        for block in sorted(changed_by_block):
            ids = changed_by_block[block]
            left = sorted(
                [customer_id for customer_id in ids if geographic[customer_id] == d0 and mixed[customer_id] == d1],
                key=lambda customer_id: (float(customers[customer_id].demand), customer_id),
            )
            right = sorted(
                [customer_id for customer_id in ids if geographic[customer_id] == d1 and mixed[customer_id] == d0],
                key=lambda customer_id: (float(customers[customer_id].demand), customer_id),
            )
            if len(left) != len(right):
                raise RuntimeError(f"changed labels are not pairable inside block {instance_id}/{block}")
            for left_id, right_id in zip(left, right, strict=True):
                removed = sum(
                    float(customers[customer_id].demand)
                    * (
                        float(bundle.instance.distance(customer_id, mixed[customer_id]))
                        - float(bundle.instance.distance(customer_id, geographic[customer_id]))
                    )
                    for customer_id in (left_id, right_id)
                )
                if removed < -EPS:
                    raise RuntimeError(f"mixed ownership is closer than geographic ownership: {instance_id}")
                pairs.append(
                    RestorePair(
                        block=block,
                        geographic_d0_customer=left_id,
                        geographic_d1_customer=right_id,
                        removed_mismatch_numerator=removed,
                        d0_demand_delta=float(customers[left_id].demand) - float(customers[right_id].demand),
                    )
                )

        geographic_demand = {
            depot: sum(float(customers[customer_id].demand) for customer_id in customers if geographic[customer_id] == depot)
            for depot in depots
        }
        mixed_demand = {
            depot: sum(float(customers[customer_id].demand) for customer_id in customers if mixed[customer_id] == depot)
            for depot in depots
        }
        max_customer_demand = max(float(node.demand) for node in customer_nodes)
        selected = select_restored_pairs(
            pairs,
            mixed_d0_demand=mixed_demand[d0],
            geographic_d0_demand=geographic_demand[d0],
            max_absolute_demand_drift=max_customer_demand,
        )
        medium = dict(mixed)
        restored_customers: set[str] = set()
        for index in selected:
            pair = pairs[index]
            for customer_id in pair.customer_ids:
                medium[customer_id] = geographic[customer_id]
                restored_customers.add(customer_id)

        if Counter(medium.values()) != Counter(geographic.values()):
            raise RuntimeError(f"medium owner totals drifted for {instance_id}")
        if counts_by_block(medium, rebuilt_blocks) != counts_by_block(geographic, rebuilt_blocks):
            raise RuntimeError(f"medium block owner counts drifted for {instance_id}")
        medium_demand = {
            depot: sum(float(customers[customer_id].demand) for customer_id in customers if medium[customer_id] == depot)
            for depot in depots
        }
        demand_drifts = {
            depot: abs(medium_demand[depot] - geographic_demand[depot]) / max(geographic_demand[depot], EPS)
            for depot in depots
        }
        allowed_drifts = {
            depot: max_customer_demand / max(geographic_demand[depot], EPS) for depot in depots
        }
        if any(demand_drifts[depot] > allowed_drifts[depot] + EPS for depot in depots):
            raise RuntimeError(f"medium demand drift exceeds sealed limit for {instance_id}")

        map_path = out / "ownership_maps" / f"{instance_id}__medium.csv"
        write_owner_map(map_path, medium)
        map_hashes[str(map_path.relative_to(out))] = sha256(map_path)

        maps = {"geographic": geographic, "medium": medium, "mixed": mixed}
        indices = {condition: mismatch_index(bundle, customers, geographic, owners) for condition, owners in maps.items()}
        mixed_index = indices["mixed"][0]
        medium_index = indices["medium"][0]
        for condition, owners in maps.items():
            changed = sum(owners[customer_id] != geographic[customer_id] for customer_id in customers)
            structure_rows.append(
                {
                    "instance": instance_id,
                    "customer_count": len(customers),
                    "condition": condition,
                    "responsibility_mismatch_index": indices[condition][0],
                    "mismatch_numerator_demand_distance": indices[condition][1],
                    "geographic_denominator_demand_distance": indices[condition][2],
                    "changed_customer_count": changed,
                    "changed_customer_share": changed / len(customers),
                    "max_owner_demand_relative_drift": max(
                        abs(
                            sum(float(customers[customer_id].demand) for customer_id in customers if owners[customer_id] == depot)
                            - geographic_demand[depot]
                        )
                        / max(geographic_demand[depot], EPS)
                        for depot in depots
                    ),
                    "map_sha256": sha256(geographic_path if condition == "geographic" else mixed_path if condition == "mixed" else map_path),
                }
            )

        for customer_id in sorted(customers):
            customer_rows.append(
                {
                    "instance": instance_id,
                    "customer_id": customer_id,
                    "shift": rebuilt_blocks[customer_id][0] + 1,
                    "demand_quartile": rebuilt_blocks[customer_id][1] + 1,
                    "demand_kg": float(customers[customer_id].demand),
                    "geographic_owner": geographic[customer_id],
                    "medium_owner": medium[customer_id],
                    "mixed_owner": mixed[customer_id],
                    "restored_from_mixed": int(customer_id in restored_customers),
                    "medium_differs_from_geographic": int(medium[customer_id] != geographic[customer_id]),
                    "distance_to_geographic_owner_km": float(bundle.instance.distance(customer_id, geographic[customer_id])) / 1000.0,
                    "distance_to_medium_owner_km": float(bundle.instance.distance(customer_id, medium[customer_id])) / 1000.0,
                    "distance_to_mixed_owner_km": float(bundle.instance.distance(customer_id, mixed[customer_id])) / 1000.0,
                }
            )

        structure_rows.append(
            {
                "instance": instance_id,
                "customer_count": len(customers),
                "condition": "medium_generation_check",
                "responsibility_mismatch_index": medium_index,
                "mismatch_numerator_demand_distance": indices["medium"][1],
                "geographic_denominator_demand_distance": indices["medium"][2],
                "changed_customer_count": sum(
                    medium[customer_id] != geographic[customer_id] for customer_id in customers
                ),
                "changed_customer_share": sum(medium[customer_id] != geographic[customer_id] for customer_id in customers) / len(customers),
                "max_owner_demand_relative_drift": max(demand_drifts.values()),
                "map_sha256": sha256(map_path),
                "mixed_index": mixed_index,
                "target_half_mixed_index": 0.5 * mixed_index,
                "medium_minus_target": medium_index - 0.5 * mixed_index,
                "restored_pair_count": len(selected),
                "available_pair_count": len(pairs),
            }
        )

    return structure_rows, customer_rows, map_hashes


def customer_depots_from_routes(solution: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    served: dict[str, str] = {}
    duplicates: list[str] = []
    for route in solution.get("routes", []):
        depot = str(route["home_depot_id"])
        for customer_id in route.get("node_sequence", [])[1:-1]:
            if not str(customer_id).startswith("C"):
                continue
            if customer_id in served:
                duplicates.append(customer_id)
            served[str(customer_id)] = depot
    return served, sorted(duplicates)


def analyze_sealed_pairs(
    sealed: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    formal_hashes: dict[str, str] = sealed["formal_hashes"]
    paired = load_csv(FORMAL_ROOT / "paired_results.csv")
    raw = load_csv(FORMAL_ROOT / "raw_runs.csv")
    raw_by_id = {row["run_id"]: row for row in raw}
    pair_rows: list[dict[str, Any]] = []
    fallback_rows: list[dict[str, Any]] = []

    for pair in sorted(paired, key=lambda row: (row["instance"], row["condition"], int(row["seed"]))):
        instance = pair["instance"]
        condition = pair["condition"]
        seed = int(pair["seed"])
        bundle_dir = FORMAL_ROOT / "assets" / instance / "bundle"
        bundle = load_search_bundle(bundle_dir)
        customers = {node.node_id: node for node in bundle.instance.nodes if str(node.node_type).lower() == "c"}
        owner_path = OWNERSHIP_ROOT / "ownership_maps" / f"{instance}__{condition}.csv"
        owners = load_owner_map(owner_path)
        fixed_id = f"{instance}__{condition}__seed{seed}__ownership_fixed"
        shared_id = f"{instance}__{condition}__seed{seed}__reassignment_allowed"
        fixed_raw = raw_by_id[fixed_id]
        shared_raw = raw_by_id[shared_id]

        fixed_solution_rel = f"solutions/{fixed_id}.json"
        shared_solution_rel = f"solutions/{shared_id}.json"
        fixed_certificate_rel = f"certificates/{fixed_id}.json"
        for relative in (fixed_solution_rel, shared_solution_rel, fixed_certificate_rel):
            expected = formal_hashes.get(relative)
            if expected is None or sha256(FORMAL_ROOT / relative) != expected:
                raise RuntimeError(f"sealed pair artifact drifted: {relative}")
        fixed_solution = json.loads((FORMAL_ROOT / fixed_solution_rel).read_text(encoding="utf-8"))
        shared_solution = json.loads((FORMAL_ROOT / shared_solution_rel).read_text(encoding="utf-8"))
        fixed_certificate = json.loads((FORMAL_ROOT / fixed_certificate_rel).read_text(encoding="utf-8"))
        fixed_served, fixed_duplicates = customer_depots_from_routes(fixed_solution)
        shared_served, shared_duplicates = customer_depots_from_routes(shared_solution)
        if fixed_duplicates or shared_duplicates:
            raise RuntimeError(f"duplicate customer in sealed solution: {pair['pair_id']}")
        if set(fixed_served) != set(customers) or set(shared_served) != set(customers):
            raise RuntimeError(f"customer coverage mismatch in sealed solution: {pair['pair_id']}")
        fixed_owner_violations = [customer_id for customer_id, depot in fixed_served.items() if owners[customer_id] != depot]
        if fixed_owner_violations:
            raise RuntimeError(f"ownership-fixed solution contains cross-depot service: {pair['pair_id']}")

        listed_cross = {
            str(item["customer_id"]): str(item["served_by_depot_id"])
            for item in shared_solution.get("cross_site_services", [])
        }
        recomputed_cross = {
            customer_id: depot for customer_id, depot in shared_served.items() if owners[customer_id] != depot
        }
        if listed_cross != recomputed_cross:
            raise RuntimeError(f"cross-depot service list mismatch: {pair['pair_id']}")
        if int(shared_raw["cross_site_customer_count"]) != len(recomputed_cross):
            raise RuntimeError(f"cross-depot count mismatch: {pair['pair_id']}")

        total_demand = sum(float(node.demand) for node in customers.values())
        cross_demand = sum(float(customers[customer_id].demand) for customer_id in recomputed_cross)
        original_weighted_distance = sum(
            float(customers[customer_id].demand) * float(bundle.instance.distance(customer_id, owners[customer_id]))
            for customer_id in recomputed_cross
        )
        serving_weighted_distance = sum(
            float(customers[customer_id].demand) * float(bundle.instance.distance(customer_id, depot))
            for customer_id, depot in recomputed_cross.items()
        )
        distance_change_pct = (
            (serving_weighted_distance - original_weighted_distance) / original_weighted_distance * 100.0
            if original_weighted_distance > 0.0
            else 0.0
        )

        fixed_cost = float(pair["fixed_total_cost"])
        observed_shared_cost = float(pair["shared_total_cost"])
        fallback_cost = min(fixed_cost, observed_shared_cost)
        fixed_solution_sha256 = sha256(FORMAL_ROOT / fixed_solution_rel)
        shared_solution_sha256 = sha256(FORMAL_ROOT / shared_solution_rel)
        fixed_certificate_sha256 = sha256(FORMAL_ROOT / fixed_certificate_rel)
        ownership_sha256 = sha256(owner_path)
        fixed_legal_under_open = (
            fixed_certificate.get("status") == "PASS"
            and fixed_raw["status"] == "PASS"
            and shared_raw["status"] == "PASS"
            and fixed_raw["allow_reassignment"].lower() == "false"
            and shared_raw["allow_reassignment"].lower() == "true"
            and int(fixed_raw["violation_count"]) == 0
            and int(fixed_raw["cross_site_customer_count"]) == 0
            and not fixed_owner_violations
            and fixed_raw["start_sha256"] == shared_raw["start_sha256"]
            and fixed_raw["contract_sha256"] == shared_raw["contract_sha256"]
            and fixed_raw["ownership_sha256"] == shared_raw["ownership_sha256"] == ownership_sha256
            and fixed_raw["solution_sha256"] == fixed_solution_sha256
            and shared_raw["solution_sha256"] == shared_solution_sha256
            and fixed_raw["certificate_sha256"] == fixed_certificate_sha256
            and int(fixed_raw["budget"]) == int(shared_raw["budget"]) == 4000
            and int(fixed_raw["evaluations"]) == int(shared_raw["evaluations"]) == 4000
            and float(fixed_raw["cost_component_error"]) <= 1e-6
            and abs(float(fixed_raw["total_cost"]) - fixed_cost) <= 1e-9
            and abs(float(shared_raw["total_cost"]) - observed_shared_cost) <= 1e-9
        )
        if not fixed_legal_under_open:
            raise RuntimeError(f"fixed solution failed open-cooperation fallback audit: {pair['pair_id']}")

        pair_rows.append(
            {
                "pair_id": pair["pair_id"],
                "instance": instance,
                "condition": condition,
                "seed": seed,
                "customer_count": len(customers),
                "total_demand_kg": total_demand,
                "cross_site_customer_count": len(recomputed_cross),
                "cross_site_customer_share": len(recomputed_cross) / len(customers),
                "cross_site_demand_kg": cross_demand,
                "cross_site_demand_share": cross_demand / total_demand,
                "cross_site_demand_weighted_depot_distance_change_pct": distance_change_pct,
                "original_owner_demand_weighted_distance": original_weighted_distance,
                "serving_depot_demand_weighted_distance": serving_weighted_distance,
                "fixed_solution_legal_under_open_rule": True,
                "fixed_solution_sha256": fixed_solution_sha256,
                "shared_solution_sha256": shared_solution_sha256,
            }
        )
        fallback_rows.append(
            {
                "pair_id": pair["pair_id"],
                "instance": instance,
                "condition": condition,
                "seed": seed,
                "original_observed_fixed_cost": fixed_cost,
                "original_observed_shared_cost": observed_shared_cost,
                "original_observed_saving_pct": float(pair["saving_pct"]),
                "fixed_solution_legal_under_open_rule": True,
                "fallback_used": observed_shared_cost > fixed_cost + 1e-9,
                "fallback_preview_cost": fallback_cost,
                "fallback_preview_saving_pct": (fixed_cost - fallback_cost) / fixed_cost * 100.0,
                "claim_boundary": "preview only; original observed result remains unchanged",
            }
        )

    condition_rows: list[dict[str, Any]] = []
    for condition in ("geographic", "mixed"):
        selected = [row for row in pair_rows if row["condition"] == condition]
        selected_fallback = [row for row in fallback_rows if row["condition"] == condition]
        original_network_means: list[float] = []
        fallback_network_means: list[float] = []
        for instance in FORMAL_INSTANCE_ORDER:
            network_original = [
                float(row["original_observed_saving_pct"])
                for row in selected_fallback
                if row["instance"] == instance
            ]
            network_fallback = [
                float(row["fallback_preview_saving_pct"])
                for row in selected_fallback
                if row["instance"] == instance
            ]
            if len(network_original) != 3 or len(network_fallback) != 3:
                raise RuntimeError(f"missing seed rows for {instance}/{condition}")
            original_network_means.append(sum(network_original) / 3.0)
            fallback_network_means.append(sum(network_fallback) / 3.0)
        condition_rows.append(
            {
                "condition": condition,
                "pair_count": len(selected),
                "mean_pair_cross_site_customer_share_pct": 100.0
                * sum(float(row["cross_site_customer_share"]) for row in selected)
                / len(selected),
                "mean_pair_cross_site_demand_share_pct": 100.0
                * sum(float(row["cross_site_demand_share"]) for row in selected)
                / len(selected),
                "mean_pair_cross_site_demand_weighted_depot_distance_change_pct": sum(
                    float(row["cross_site_demand_weighted_depot_distance_change_pct"]) for row in selected
                )
                / len(selected),
                "original_observed_network_mean_saving_pct": sum(original_network_means) / len(original_network_means),
                "fallback_preview_network_mean_saving_pct": sum(fallback_network_means) / len(fallback_network_means),
                "fallback_used_pair_count": sum(bool(row["fallback_used"]) for row in selected_fallback),
                "claim_boundary": "fallback preview is additive and does not replace the formal observed estimate",
            }
        )
    return pair_rows, fallback_rows, condition_rows


def artifact_hashes(out: Path) -> dict[str, str]:
    return {
        str(path.relative_to(out)): sha256(path)
        for path in sorted(out.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
    }


def clean_appledouble(out: Path) -> int:
    removed = 0
    for path in sorted(out.rglob("._*"), reverse=True):
        if path.is_file():
            path.unlink()
            removed += 1
    return removed


def run(out: Path) -> dict[str, Any]:
    sealed = verify_sealed_inputs()
    out.mkdir(parents=True, exist_ok=True)
    clean_appledouble(out)

    # Freeze the outcome-blind maps before opening paired cost/result files.
    structure_rows, customer_rows, map_hashes = build_medium_maps(out)
    write_csv(out / "ownership_structure.csv", structure_rows)
    write_csv(out / "customer_assignment_audit.csv", customer_rows)
    write_json(out / "medium_map_freeze.json", {"map_count": len(map_hashes), "maps": map_hashes})
    map_freeze_sha256 = sha256(out / "medium_map_freeze.json")

    pair_rows, fallback_rows, condition_rows = analyze_sealed_pairs(sealed)
    write_csv(out / "raw_runs.csv", pair_rows)
    write_csv(out / "fallback_preview.csv", fallback_rows)
    write_csv(out / "condition_summary.csv", condition_rows)

    medium_checks = [row for row in structure_rows if row["condition"] == "medium_generation_check"]
    all_medium_gates = len(medium_checks) == len(FORMAL_INSTANCE_ORDER) and all(
        abs(float(row["medium_minus_target"])) <= max(0.05 * float(row["mixed_index"]), EPS)
        and float(row["max_owner_demand_relative_drift"]) >= 0.0
        for row in medium_checks
    )
    all_fallback_legal = len(fallback_rows) == 54 and all(
        bool(row["fixed_solution_legal_under_open_rule"]) for row in fallback_rows
    )
    geographic_summary = next(row for row in condition_rows if row["condition"] == "geographic")
    mixed_summary = next(row for row in condition_rows if row["condition"] == "mixed")
    status = "PASS_DIAGNOSTIC_ONLY" if all_medium_gates and all_fallback_legal else "HALT"
    decision = {
        "status": status,
        "schema": "setp.e3.medium_ownership_diagnostic.v1",
        "search_evaluations": 0,
        "formal_e3_artifacts_modified": False,
        "medium_map_count": len(map_hashes),
        "medium_map_freeze_sha256": map_freeze_sha256,
        "medium_selection_inputs": [
            "customer id",
            "customer demand",
            "geographic and mixed owner labels",
            "customer-to-depot distances",
            "service shift and demand quartile",
        ],
        "medium_selection_reads_cost_or_search_results": False,
        "all_grouping_fields_reconstructed_exactly": True,
        "all_medium_structure_gates_pass": all_medium_gates,
        "sealed_pair_count": len(pair_rows),
        "all_fixed_solutions_legal_under_open_rule": all_fallback_legal,
        "geographic_original_observed_saving_pct": geographic_summary["original_observed_network_mean_saving_pct"],
        "geographic_fallback_preview_saving_pct": geographic_summary["fallback_preview_network_mean_saving_pct"],
        "geographic_fallback_used_pair_count": geographic_summary["fallback_used_pair_count"],
        "mixed_original_observed_saving_pct": mixed_summary["original_observed_network_mean_saving_pct"],
        "mixed_fallback_preview_saving_pct": mixed_summary["fallback_preview_network_mean_saving_pct"],
        "mixed_fallback_used_pair_count": mixed_summary["fallback_used_pair_count"],
        "claim_guard": (
            "The fallback preview is an additive feasibility/envelope diagnostic. "
            "It must be shown beside, not substituted for, the sealed 4.157% observed geographic estimate."
        ),
        "formal_medium_search_authorized": False,
    }
    write_json(out / "decision.json", decision)
    metadata = {
        "schema": "setp.e3.medium_ownership_diagnostic.v1",
        "source_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip(),
        "generator": str(Path(__file__).resolve().relative_to(ROOT)),
        "generator_sha256": sha256(Path(__file__).resolve()),
        "ownership_source": str(OWNERSHIP_ROOT.relative_to(ROOT)),
        "ownership_decision_sha256": sha256(OWNERSHIP_ROOT / "decision.json"),
        "formal_source": str(FORMAL_ROOT.relative_to(ROOT)),
        "formal_decision_sha256": sha256(FORMAL_ROOT / "decision.json"),
        "formal_artifact_hashes_sha256": sha256(FORMAL_ROOT / "artifact_hashes.json"),
        "evaluation_source_sha256_at_formal_commit": sealed["evaluation_source_sha256"],
        "medium_map_freeze_sha256": map_freeze_sha256,
        "search_evaluations": 0,
        "scope": "diagnostic-only additive E3 evidence; no formal search and no sealed artifact replacement",
    }
    write_json(out / "metadata.json", metadata)
    report_lines = [
        "# E3中等责任偏离与开放合作保底诊断",
        "",
        f"判决：`{status}`。本批没有运行路线搜索，也没有改动任何现有E3封存目录。",
        "",
        "中等责任图直接从既有空间交错图出发，在每个班次和需求档内成对恢复客户责任。每个小组恢复的客户对数取该组可恢复对数的一半（奇数时只能取相邻整数），全网选择使需求加权责任偏离度尽量接近空间交错情形的一半。选择过程只读取客户编号、需求、责任标签和到两车场距离，不读取成本或合作结果；九张图各生成一次并立即锁定指纹。",
        "",
        f"现有54对保存方案的跨场规模已补算。地理聚集情形平均跨场客户占比为 {float(geographic_summary['mean_pair_cross_site_customer_share_pct']):.3f}%，跨场需求占比为 {float(geographic_summary['mean_pair_cross_site_demand_share_pct']):.3f}%，改派客户到服务车场的需求加权距离相对原责任车场平均变化 {float(geographic_summary['mean_pair_cross_site_demand_weighted_depot_distance_change_pct']):+.3f}%。空间交错情形对应为 {float(mixed_summary['mean_pair_cross_site_customer_share_pct']):.3f}%、{float(mixed_summary['mean_pair_cross_site_demand_share_pct']):.3f}% 和 {float(mixed_summary['mean_pair_cross_site_demand_weighted_depot_distance_change_pct']):+.3f}%。",
        "",
        "54份固定责任方案均由封存证书证明可行、无跨场服务；开放合作规则只取消责任锁定，不增加新的限制，因此这些方案在开放合作规则下仍合法。把它们作为求解保底后，地理聚集情形的预览均值为 "
        f"{float(geographic_summary['fallback_preview_network_mean_saving_pct']):.3f}%（27对中{int(geographic_summary['fallback_used_pair_count'])}对启用保底），空间交错情形仍为 {float(mixed_summary['fallback_preview_network_mean_saving_pct']):.3f}%（启用{int(mixed_summary['fallback_used_pair_count'])}对）。这只是可行域保底预览；原正式搜索观测到的地理聚集均值 {float(geographic_summary['original_observed_network_mean_saving_pct']):.3f}% 必须保留并与预览并列，不能被静默替换。",
        "",
        "逐网络责任偏离度见 `ownership_structure.csv`，逐客户地图见 `customer_assignment_audit.csv` 与 `ownership_maps/`，54对跨场读出见 `raw_runs.csv`，保底逐对计算见 `fallback_preview.csv`。本批不授权中等责任情形的正式路线搜索。",
    ]
    (out / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    write_json(out / "artifact_hashes.json", artifact_hashes(out))
    clean_appledouble(out)
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    decision = run(output)
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if decision["status"] == "PASS_DIAGNOSTIC_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
