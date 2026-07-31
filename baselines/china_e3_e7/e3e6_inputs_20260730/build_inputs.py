#!/usr/bin/env python3
"""Build only the E3/E6 responsibility-map inputs.

This program deliberately does not import or call the search, completion,
cost, or objective-evaluation entry points.  It replaces the symbolic
route-partition model with the task-card's frozen deterministic First-Fit
semantics and independently rechecks every returned route group with the
audited Python First-Fit packer.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from time import perf_counter
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OLD_ROOT = REPO / "baselines/china_e3_e7/e3e6_formal_20260729"
OLD_INPUTS = OLD_ROOT / "inputs"
RUNNER_PATH = OLD_ROOT / "run_e3e6_formal.py"
CPP_SOURCE = HERE / "first_fit_lexicographic.cpp"
BIN_DIR = HERE / ".builder_bin"
CPP_BINARY = BIN_DIR / "first_fit_lexicographic"
INPUTS = HERE / "inputs"
TASK_ID = "E3E6-MISMATCH-FAIRNESS-01"
INTENSITIES = (0, 25, 50)
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
    REPO
    / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py",
)
EXPECTED_PROTECTED_HASHES = {
    "solver/src/setp_solver/cost.py":
        "2717b4b4de39bb4c2a9a1bda602f4420cb3e3b1e87faa83678dfa64f88fc80be",
    "solver/src/setp_solver/check.py":
        "9c81e254e05591667c8225965bb9d0ba4e8bbfc53eb0f8c61ffdb4325a1403a8",
    "solver/src/setp_solver/search/evaluation.py":
        "c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3",
    "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/route_pool_sp.py":
        "976ef21d4952b3c488300de9a8d3e351411305d26f1e2601ca17c15185d462c1",
}
JSON_INDENT = 2


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(REPO.resolve()).as_posix()


def verify_protected() -> dict[str, str]:
    actual = {relative(path): sha256(path) for path in PROTECTED}
    if actual != EXPECTED_PROTECTED_HASHES:
        raise RuntimeError(
            "HALT_PROTECTED_HASH_DRIFT:"
            + json.dumps(
                {
                    key: {
                        "expected": EXPECTED_PROTECTED_HASHES.get(key),
                        "actual": value,
                    }
                    for key, value in actual.items()
                    if value != EXPECTED_PROTECTED_HASHES.get(key)
                },
                sort_keys=True,
            )
        )
    return actual


def load_runner() -> Any:
    spec = importlib.util.spec_from_file_location(
        "_e3e6_input_builder_source",
        RUNNER_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load E3/E6 source runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(
            value,
            handle,
            ensure_ascii=False,
            indent=JSON_INDENT,
            sort_keys=True,
        )
        handle.write("\n")
    temporary.replace(path)


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def compile_cpp() -> None:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    if (
        CPP_BINARY.is_file()
        and CPP_BINARY.stat().st_mtime_ns >= CPP_SOURCE.stat().st_mtime_ns
    ):
        return
    subprocess.run(
        [
            "clang++",
            "-std=c++17",
            "-O3",
            "-DNDEBUG",
            str(CPP_SOURCE),
            "-o",
            str(CPP_BINARY),
        ],
        check=True,
    )


def unit_name(instance_id: str, intensity: int) -> str:
    return f"{instance_id}__mismatch{intensity:02d}"


def prepare_selection(
    runner: Any,
    bundle: Any,
    intensity: int,
) -> tuple[
    dict[str, str],
    int,
    list[dict[str, Any]],
    int,
    dict[str, Any] | None,
]:
    original = dict(bundle.customer_home_depot)
    target = int(
        (
            Decimal(len(original))
            * Decimal(intensity)
            / Decimal(100)
        ).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    )
    allocations = runner.e3.allocation_counts(original, target)
    selected: list[dict[str, Any]] = []
    ineligible_second_is_owner = 0
    for owner in sorted(allocations):
        candidates: list[dict[str, Any]] = []
        for customer_id, registered_owner in original.items():
            if registered_owner != owner:
                continue
            ranking = runner._directed_depot_ranking(bundle, customer_id)
            if intensity and ranking[1] == owner:
                ineligible_second_is_owner += 1
                continue
            rank_hash = hashlib.sha256(
                (
                    f"{TASK_ID}|{bundle.instance_id}|{intensity}|"
                    f"{owner}|{customer_id}"
                ).encode("utf-8")
            ).hexdigest()
            candidates.append(
                {
                    "customer_id": customer_id,
                    "owner": owner,
                    "ranking": ranking,
                    "rank_hash": rank_hash,
                }
            )
        candidates.sort(
            key=lambda row: (row["rank_hash"], row["customer_id"])
        )
        if len(candidates) < allocations[owner]:
            return (
                original,
                target,
                [],
                ineligible_second_is_owner,
                {
                    "status": "INFEASIBLE_INPUT",
                    "reason":
                        "INSUFFICIENT_TRUE_SECOND_NEAREST_REASSIGNMENT_CANDIDATES",
                    "target_reassigned": target,
                    "owner": owner,
                    "needed": allocations[owner],
                    "available": len(candidates),
                },
            )
        selected.extend(candidates[: allocations[owner]])
    selected.sort(key=lambda row: (row["rank_hash"], row["customer_id"]))
    return original, target, selected, ineligible_second_is_owner, None


def serialize_problem(
    runner: Any,
    bundle: Any,
    original: dict[str, str],
    selected: list[dict[str, Any]],
) -> tuple[str, list[str], list[str], list[list[tuple[int, str]]]]:
    depots = runner._depot_ids(bundle)
    depot_index = {depot_id: index for index, depot_id in enumerate(depots)}
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    customers = sorted(
        (
            node
            for node in bundle.instance.nodes
            if node.node_type.lower() == "c"
        ),
        key=lambda node: (
            float(node.due_time),
            float(node.ready_time),
            node.node_id,
        ),
    )
    customer_ids = [node.node_id for node in customers]
    selected_position = {
        item["customer_id"]: index for index, item in enumerate(selected)
    }
    options: list[list[tuple[int, str]]] = [
        [
            (absolute_rank, destination)
            for absolute_rank, destination in enumerate(
                item["ranking"],
                start=1,
            )
            if absolute_rank != 1 and destination != item["owner"]
        ]
        for item in selected
    ]
    payload_capacity = bundle.instance.payload_capacity_kg(
        "cv",
        fallback=float(bundle.prices.Q_capacity),
    )
    random_seed = int(
        hashlib.sha256(
            f"{TASK_ID}|{bundle.instance_id}|first-fit-cpp".encode("utf-8")
        ).hexdigest()[:16],
        16,
    )
    lines = [
        (
            f"RESETPE3E6FF1 {len(depots)} {len(customers)} "
            f"{len(selected)} {payload_capacity:.17g} {random_seed}"
        )
    ]
    for depot_id in depots:
        node = nodes[depot_id]
        fleet = bundle.fleet_caps_by_depot[depot_id]
        cap = int(fleet["num_cv"]) + int(fleet["num_ev"])
        lines.append(
            f"{cap} {float(node.ready_time):.17g} "
            f"{float(node.due_time):.17g} "
            f"{float(node.service_time):.17g}"
        )
    for customer in customers:
        position = selected_position.get(customer.node_id, -1)
        item_options = [] if position < 0 else options[position]
        line = (
            f"{customer.node_id} {float(customer.demand):.17g} "
            f"{float(customer.ready_time):.17g} "
            f"{float(customer.due_time):.17g} "
            f"{float(customer.service_time):.17g} "
            f"{depot_index[original[customer.node_id]]} "
            f"{position} {len(item_options)}"
        )
        for absolute_rank, destination in item_options:
            line += f" {absolute_rank} {depot_index[destination]}"
        lines.append(line)
    node_ids = depots + customer_ids
    fallback_speed = float(bundle.prices.v_speed_ms)
    for left in node_ids:
        row = []
        for right in node_ids:
            _, travel_time, _ = bundle.instance.arc_metrics(
                left,
                right,
                "cv",
                fallback_speed_mps=fallback_speed,
            )
            row.append(f"{float(travel_time):.17g}")
        lines.append(" ".join(row))
    return "\n".join(lines) + "\n", depots, customer_ids, options


def parse_solver_output(
    output: str,
    depots: list[str],
    customers: list[str],
) -> tuple[
    str,
    list[int] | None,
    dict[str, list[list[str]]] | None,
    dict[str, int],
]:
    lines = iter(output.splitlines())
    status = next(lines)
    chosen: list[int] | None = None
    route_groups: dict[str, list[list[str]]] | None = None
    stats: dict[str, int] = {}
    if status == "PASS":
        chosen_row = next(lines).split()
        if chosen_row[0] != "CHOSEN":
            raise RuntimeError("malformed C++ chosen row")
        count = int(chosen_row[1])
        chosen = [int(value) for value in chosen_row[2:]]
        if len(chosen) != count:
            raise RuntimeError("malformed C++ chosen vector")
        depot_row = next(lines).split()
        if depot_row != ["DEPOTS", str(len(depots))]:
            raise RuntimeError("malformed C++ depot header")
        route_groups = {}
        for expected_index, depot_id in enumerate(depots):
            header = next(lines).split()
            if (
                len(header) != 3
                or header[0] != "DEPOT"
                or int(header[1]) != expected_index
            ):
                raise RuntimeError("malformed C++ depot row")
            groups: list[list[str]] = []
            for _ in range(int(header[2])):
                route = next(lines).split()
                if route[0] != "ROUTE" or len(route) != int(route[1]) + 2:
                    raise RuntimeError("malformed C++ route row")
                groups.append(
                    [customers[int(index)] for index in route[2:]]
                )
            route_groups[depot_id] = groups
    elif status != "INFEASIBLE":
        raise RuntimeError(f"unexpected C++ status: {status!r}")
    stats_row = next(lines).split()
    if stats_row[0] != "STATS" or len(stats_row) != 10:
        raise RuntimeError("malformed C++ stats row")
    keys = (
        "prefix_oracle_calls",
        "infeasible_prefix_attempts",
        "nodes_visited",
        "route_feasibility_checker_calls",
        "d2a_cap_prunes",
        "conflict_backjumps",
        "heuristic_checker_calls",
        "demand_hall_prunes",
        "pairwise_clique_prunes",
    )
    stats = {
        key: int(value) for key, value in zip(keys, stats_row[1:])
    }
    return status, chosen, route_groups, stats


def fast_assignment(
    runner: Any,
    bundle: Any,
    intensity: int,
) -> dict[str, Any]:
    (
        original,
        target,
        selected,
        ineligible,
        selection_failure,
    ) = prepare_selection(runner, bundle, intensity)
    if selection_failure is not None:
        return {
            "status": "INFEASIBLE_INPUT",
            "mapping": None,
            "rows": [],
            "audit": selection_failure,
            "route_groups": None,
            "rank_vector": None,
        }
    problem, depots, customers, options = serialize_problem(
        runner,
        bundle,
        original,
        selected,
    )
    started = perf_counter()
    completed = subprocess.run(
        [str(CPP_BINARY)],
        input=problem,
        text=True,
        capture_output=True,
        check=False,
    )
    elapsed = perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(
            f"C++ solver failed rc={completed.returncode}:"
            f"{completed.stderr.strip()}"
        )
    status, chosen, route_groups, stats = parse_solver_output(
        completed.stdout,
        depots,
        customers,
    )
    if status == "INFEASIBLE":
        audit = {
            "status": "INFEASIBLE_INPUT",
            "reason":
                "NO_COMPLETE_DESTINATION_ASSIGNMENT_PRESERVES_D2A_COMMON_INITIAL",
            "target_reassigned": target,
            "global_search_audit": {
                "algorithm":
                    "EXACT_LEXICOGRAPHIC_DFS_FROZEN_FIRST_FIT_CPP_V1",
                "global_feasible_completion_found": False,
                **stats,
            },
        }
        return {
            "status": status,
            "mapping": None,
            "rows": [],
            "audit": audit,
            "route_groups": None,
            "rank_vector": None,
            "elapsed_seconds": elapsed,
        }
    assert chosen is not None and route_groups is not None
    rank_vector = [
        options[index][option_index][0]
        for index, option_index in enumerate(chosen)
    ]
    mapping = dict(original)
    assignment: dict[str, dict[str, Any]] = {}
    fallback_steps = 0
    for item, absolute_rank in zip(selected, rank_vector):
        customer_id = item["customer_id"]
        destination = item["ranking"][absolute_rank - 1]
        mapping[customer_id] = destination
        fallback_steps += max(0, absolute_rank - 2)
        assignment[customer_id] = {
            "rank_hash": item["rank_hash"],
            "destination": destination,
            "absolute_distance_rank": absolute_rank,
            "directed_distance_m": float(
                bundle.instance.distance(destination, customer_id)
            ),
        }
    actual = sum(mapping[key] != original[key] for key in original)
    if actual != target:
        raise RuntimeError(
            f"HALT_MISMATCH_TARGET_NOT_MET:{bundle.instance_id}:"
            f"{intensity}:{actual}/{target}"
        )
    independently_packed: dict[str, list[list[str]]] = {}
    remapped = runner.e3.with_responsibility(bundle, mapping)
    for depot_id in depots:
        independently_packed[depot_id] = runner.e3._pack_depot(
            remapped,
            depot_id,
        )
    if independently_packed != route_groups:
        raise RuntimeError(
            "HALT_CPP_PYTHON_FIRST_FIT_DISAGREEMENT:"
            f"{bundle.instance_id}:{intensity}"
        )
    rows: list[dict[str, Any]] = []
    for customer_id in sorted(original):
        detail = assignment.get(customer_id)
        rows.append(
            {
                "instance_id": bundle.instance_id,
                "mismatch_intensity_nominal_pct": intensity,
                "customer_id": customer_id,
                "original_registered_depot": original[customer_id],
                "assigned_responsibility_depot": mapping[customer_id],
                "reassigned": detail is not None,
                "result_blind_rank_sha256":
                    "" if detail is None else detail["rank_hash"],
                "destination_absolute_distance_rank":
                    "" if detail is None else detail["absolute_distance_rank"],
                "destination_directed_distance_m":
                    "" if detail is None else detail["directed_distance_m"],
                "destination_rule":
                    "UNCHANGED"
                    if detail is None
                    else "SECOND_NEAREST_THEN_NEXT_IF_D2A_BLOCKED",
            }
        )
    search_audit = {
        "algorithm": "EXACT_LEXICOGRAPHIC_DFS_FROZEN_FIRST_FIT_CPP_V1",
        "global_feasible_completion_found": True,
        "fixed_customer_order":
            "result-blind SHA-256 order for lexicographic destination decisions",
        "destination_order":
            "directed-distance absolute rank, second then third/fourth, original owner skipped",
        "feasibility_search_order":
            "frozen due_time, ready_time, customer_id order used by D2-A First-Fit packer",
        "nonmonotone_hash_prefix_pruning": False,
        **stats,
        "route_groups_by_depot": route_groups,
    }
    audit = {
        "status": "PASS",
        "target_reassigned": target,
        "actual_reassigned": actual,
        "fallback_steps_beyond_second_nearest": fallback_steps,
        "customers_ineligible_because_second_nearest_is_original_owner":
            ineligible,
        "global_search_audit": search_audit,
        "final_fleet_probe": {
            "feasible": True,
            "reason": "PASS_EXACT_FROZEN_FIRST_FIT_D2A_CAP",
            "depot_counts": {
                depot_id: {
                    "packed_routes": len(route_groups[depot_id]),
                    "d2a_total_cap": (
                        int(bundle.fleet_caps_by_depot[depot_id]["num_cv"])
                        + int(bundle.fleet_caps_by_depot[depot_id]["num_ev"])
                    ),
                }
                for depot_id in depots
            },
        },
    }
    return {
        "status": status,
        "mapping": mapping,
        "rows": rows,
        "audit": audit,
        "route_groups": route_groups,
        "rank_vector": rank_vector,
        "elapsed_seconds": elapsed,
    }


def old_unit_summary(folder: Path) -> dict[str, Any]:
    certificate = json.loads(
        (folder / "input_certificate.json").read_text(encoding="utf-8")
    )
    if certificate["status"] == "INFEASIBLE_INPUT":
        return {
            "status": "INFEASIBLE_INPUT",
            "reason": certificate["audit"]["reason"],
            "mapping": None,
            "route_groups": None,
            "route_counts": None,
            "fallback_steps": None,
        }
    responsibility = json.loads(
        (folder / "responsibility_map.json").read_text(encoding="utf-8")
    )
    audit = responsibility["map_audit"]
    groups = audit["global_search_audit"]["route_groups_by_depot"]
    return {
        "status": "PASS",
        "mapping": responsibility["mapping"],
        "route_groups": groups,
        "route_counts": {
            depot_id: len(routes) for depot_id, routes in groups.items()
        },
        "fallback_steps":
            audit["fallback_steps_beyond_second_nearest"],
        "target_reassigned": audit["target_reassigned"],
        "actual_reassigned": audit["actual_reassigned"],
    }


def copy_old_unit_exactly(source: Path, destination: Path) -> dict[str, str]:
    destination.mkdir(parents=True, exist_ok=True)
    source_files = sorted(
        path
        for path in source.iterdir()
        if path.is_file() and not path.name.startswith("._")
    )
    copied: dict[str, str] = {}
    for source_file in source_files:
        destination_file = destination / source_file.name
        if destination_file.is_file():
            if sha256(destination_file) != sha256(source_file):
                raise RuntimeError(
                    f"HALT_REUSE_TARGET_DRIFT:{destination_file}"
                )
        else:
            shutil.copyfile(source_file, destination_file)
        source_hash = sha256(source_file)
        if sha256(destination_file) != source_hash:
            raise RuntimeError(
                f"HALT_REUSED_ARTIFACT_HASH_MISMATCH:{destination_file}"
            )
        copied[source_file.name] = source_hash
    return copied


def verify_one(args: tuple[str, int]) -> dict[str, Any]:
    instance_id, intensity = args
    runner = load_runner()
    result = fast_assignment(
        runner,
        runner.e3.load_bundle(instance_id),
        intensity,
    )
    folder = OLD_INPUTS / unit_name(instance_id, intensity)
    old = old_unit_summary(folder)
    mismatches: list[str] = []
    new_status = (
        "INFEASIBLE_INPUT"
        if result["status"] == "INFEASIBLE"
        else result["status"]
    )
    if new_status != old["status"]:
        mismatches.append("status")
    if old["status"] == "PASS" and result["status"] == "PASS":
        if result["mapping"] != old["mapping"]:
            mismatches.append("mapping")
        if result["route_groups"] != old["route_groups"]:
            mismatches.append("route_groups")
        new_counts = {
            depot_id: len(routes)
            for depot_id, routes in result["route_groups"].items()
        }
        if new_counts != old["route_counts"]:
            mismatches.append("route_counts")
        if (
            result["audit"]["fallback_steps_beyond_second_nearest"]
            != old["fallback_steps"]
        ):
            mismatches.append("fallback_steps")
        if (
            result["audit"]["target_reassigned"]
            != old["target_reassigned"]
        ):
            mismatches.append("target_reassigned")
        if (
            result["audit"]["actual_reassigned"]
            != old["actual_reassigned"]
        ):
            mismatches.append("actual_reassigned")
    if old["status"] == "INFEASIBLE_INPUT":
        if result["audit"]["reason"] != old["reason"]:
            mismatches.append("reason")
    return {
        "unit": unit_name(instance_id, intensity),
        "instance_id": instance_id,
        "intensity": intensity,
        "old_status": old["status"],
        "new_status": new_status,
        "elapsed_seconds": result.get("elapsed_seconds", 0.0),
        "mismatches": mismatches,
    }


def parse_old_units() -> list[tuple[str, int]]:
    result = []
    for folder in sorted(path for path in OLD_INPUTS.iterdir() if path.is_dir()):
        instance_id, suffix = folder.name.rsplit("__mismatch", 1)
        result.append((instance_id, int(suffix)))
    return result


def eligible_units(runner: Any) -> list[tuple[str, int]]:
    gate_csv = OLD_ROOT / "gate2_d3/eligible_multi_depot_instances.csv"
    with gate_csv.open(encoding="utf-8", newline="") as handle:
        instances = sorted(
            row["instance_id"] for row in csv.DictReader(handle)
        )
    return [
        (instance_id, intensity)
        for instance_id in instances
        for intensity in INTENSITIES
    ]


def log_progress(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        )
        handle.flush()


def run_equivalence(workers: int) -> dict[str, Any]:
    verify_protected()
    compile_cpp()
    old_units = parse_old_units()
    results: list[dict[str, Any]] = []
    progress = HERE / "equivalence_progress.log"
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(verify_one, item): item for item in old_units
        }
        for future in as_completed(futures):
            row = future.result()
            results.append(row)
            log_progress(
                progress,
                {
                    "timestamp_utc": datetime.now(UTC).isoformat(),
                    "phase": "equivalence",
                    "result": (
                        "MATCH" if not row["mismatches"] else "MISMATCH"
                    ),
                    **row,
                },
            )
            print(
                f"EQUIVALENCE unit={row['unit']} "
                f"elapsed={row['elapsed_seconds']:.6f}s "
                f"result={'MATCH' if not row['mismatches'] else 'MISMATCH'}",
                flush=True,
            )
    results.sort(key=lambda row: row["unit"])
    mismatch = [row for row in results if row["mismatches"]]
    payload = {
        "schema": "resetp.e3e6-input-builder-equivalence.v1",
        "checked_units": len(results),
        "matching_units": len(results) - len(mismatch),
        "mismatching_units": len(mismatch),
        "equivalence_check_passed": not mismatch,
        "comparison_fields": [
            "status",
            "mapping",
            "route_groups_by_depot",
            "route_counts_by_depot",
            "fallback_steps_beyond_second_nearest",
            "target_reassigned",
            "actual_reassigned",
            "infeasibility_reason",
        ],
        "historical_artifact_policy":
            "old files are byte-reused after independent core-field match",
        "results": results,
    }
    atomic_json(HERE / "equivalence_check.json", payload)
    if mismatch:
        raise RuntimeError(
            "HALT_EQUIVALENCE_MISMATCH:"
            + ",".join(row["unit"] for row in mismatch)
        )
    verify_protected()
    return payload


def build_one(args: tuple[str, int]) -> dict[str, Any]:
    instance_id, intensity = args
    runner = load_runner()
    bundle = runner.e3.load_bundle(instance_id)
    started = perf_counter()
    result = fast_assignment(runner, bundle, intensity)
    elapsed = perf_counter() - started
    folder = INPUTS / unit_name(instance_id, intensity)
    folder.mkdir(parents=True, exist_ok=True)
    if result["status"] == "INFEASIBLE":
        certificate = {
            "schema": "resetp.e3e6.infeasible-input-certificate.v2",
            "instance_id": instance_id,
            "mismatch_intensity_nominal_pct": intensity,
            "status": "INFEASIBLE_INPUT",
            "audit": result["audit"],
            "no_rows_deleted": True,
            "d2a_not_expanded": True,
            "unserved_customers_not_allowed": True,
            "objective_evaluations": 0,
            "formal_effect_search_started": False,
        }
        atomic_json(folder / "input_certificate.json", certificate)
        return {
            "unit": folder.name,
            "instance_id": instance_id,
            "mismatch_intensity_nominal_pct": intensity,
            "status": "INFEASIBLE_INPUT",
            "reason": result["audit"]["reason"],
            "elapsed_seconds": elapsed,
            "reused": False,
            "customer_count": len(bundle.customer_home_depot),
            "reassigned_customer_count": "",
            "fallback_steps_beyond_second_nearest": "",
            "route_counts_by_depot": "",
            "assignment_rows": [],
        }
    responsibility_payload = {
        "schema": "resetp.e3e6.responsibility-map.input-only.v2",
        "task_id": TASK_ID,
        "instance_id": instance_id,
        "mismatch_intensity_nominal_pct": intensity,
        "mapping": result["mapping"],
        "mapping_sha256": canonical_sha256(result["mapping"]),
        "selection_rule":
            "proportional largest-remainder allocation within original owner strata; frozen SHA-256 rank",
        "destination_rule":
            "absolute second-nearest depot by directed depot-to-customer road distance; advance to third/fourth only when frozen First-Fit D2-A cap blocks a complete mapping; never return to original owner",
        "map_audit": result["audit"],
        "input_only": True,
        "objective_evaluations": 0,
        "formal_effect_search_started": False,
    }
    route_groups = result["route_groups"]
    route_skeleton = {
        "schema": "resetp.e3e6.common-route-skeleton.input-only.v1",
        "instance_id": instance_id,
        "mismatch_intensity_nominal_pct": intensity,
        "construction":
            "FROZEN_DUE_READY_ID_FIRST_FIT_UNTYPED_ROUTE_GROUPS",
        "route_groups_by_depot": route_groups,
        "route_counts_by_depot": {
            depot_id: len(groups)
            for depot_id, groups in route_groups.items()
        },
        "customer_coverage": {
            "expected": len(bundle.customer_home_depot),
            "served_once": len(
                {
                    customer
                    for groups in route_groups.values()
                    for route in groups
                    for customer in route
                }
            ),
        },
        "vehicle_type_assignment_performed": False,
        "charging_completion_performed": False,
        "objective_evaluations": 0,
        "formal_effect_search_started": False,
    }
    certificate = {
        "schema": "resetp.e3e6.input-certificate.input-only.v2",
        "status": "PASS_INPUT_MAPPING_AND_ROUTE_GROUPS_ONLY",
        "responsibility_map_sha256":
            canonical_sha256(responsibility_payload),
        "common_route_skeleton_sha256": canonical_sha256(route_skeleton),
        "route_counts_by_depot":
            route_skeleton["route_counts_by_depot"],
        "frozen_python_first_fit_recheck_passed": True,
        "shared_by_all_future_seeds_and_e3_e6_arms_if_user_approves":
            True,
        "not_a_search_ready_solution": True,
        "objective_evaluations": 0,
        "formal_effect_search_started": False,
    }
    atomic_json(folder / "responsibility_map.json", responsibility_payload)
    atomic_json(folder / "common_route_skeleton.json", route_skeleton)
    atomic_json(folder / "input_certificate.json", certificate)
    return {
        "unit": folder.name,
        "instance_id": instance_id,
        "mismatch_intensity_nominal_pct": intensity,
        "status": "PASS_INPUT_MAPPING_AND_ROUTE_GROUPS_ONLY",
        "reason": "",
        "elapsed_seconds": elapsed,
        "reused": False,
        "customer_count": len(bundle.customer_home_depot),
        "reassigned_customer_count":
            result["audit"]["actual_reassigned"],
        "fallback_steps_beyond_second_nearest":
            result["audit"]["fallback_steps_beyond_second_nearest"],
        "route_counts_by_depot": json.dumps(
            {
                depot_id: len(groups)
                for depot_id, groups in route_groups.items()
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        "assignment_rows": result["rows"],
    }


def reused_row(
    runner: Any,
    instance_id: str,
    intensity: int,
) -> dict[str, Any]:
    source = OLD_INPUTS / unit_name(instance_id, intensity)
    hashes = copy_old_unit_exactly(source, INPUTS / source.name)
    old = old_unit_summary(source)
    bundle = runner.e3.load_bundle(instance_id)
    if old["status"] == "INFEASIBLE_INPUT":
        return {
            "unit": source.name,
            "instance_id": instance_id,
            "mismatch_intensity_nominal_pct": intensity,
            "status": "INFEASIBLE_INPUT",
            "reason": old["reason"],
            "elapsed_seconds": 0.0,
            "reused": True,
            "reused_file_hashes": hashes,
            "customer_count": len(bundle.customer_home_depot),
            "reassigned_customer_count": "",
            "fallback_steps_beyond_second_nearest": "",
            "route_counts_by_depot": "",
            "assignment_rows": [],
        }
    original, target, selected, _ineligible, failure = prepare_selection(
        runner,
        bundle,
        intensity,
    )
    if failure is not None:
        raise RuntimeError(
            f"HALT_REUSED_SELECTION_DRIFT:{instance_id}:{intensity}"
        )
    if target != old["actual_reassigned"]:
        raise RuntimeError(
            f"HALT_REUSED_TARGET_DRIFT:{instance_id}:{intensity}"
        )
    mapping = old["mapping"]
    selected_by_id = {
        item["customer_id"]: item for item in selected
    }
    assignment_rows = []
    for customer_id in sorted(original):
        reassigned = mapping[customer_id] != original[customer_id]
        item = selected_by_id.get(customer_id)
        if reassigned and item is None:
            raise RuntimeError(
                f"HALT_REUSED_SELECTED_SET_DRIFT:{instance_id}:"
                f"{intensity}:{customer_id}"
            )
        absolute_rank: int | str = ""
        rank_hash = ""
        directed_distance: float | str = ""
        if reassigned:
            assert item is not None
            absolute_rank = (
                item["ranking"].index(mapping[customer_id]) + 1
            )
            rank_hash = item["rank_hash"]
            directed_distance = float(
                bundle.instance.distance(
                    mapping[customer_id],
                    customer_id,
                )
            )
        assignment_rows.append(
            {
                "instance_id": instance_id,
                "mismatch_intensity_nominal_pct": intensity,
                "customer_id": customer_id,
                "original_registered_depot": original[customer_id],
                "assigned_responsibility_depot": mapping[customer_id],
                "reassigned": reassigned,
                "result_blind_rank_sha256": rank_hash,
                "destination_absolute_distance_rank": absolute_rank,
                "destination_directed_distance_m": directed_distance,
                "destination_rule":
                    "SECOND_NEAREST_THEN_NEXT_IF_D2A_BLOCKED"
                    if reassigned
                    else "UNCHANGED",
            }
        )
    return {
        "unit": source.name,
        "instance_id": instance_id,
        "mismatch_intensity_nominal_pct": intensity,
        "status": "PASS_REUSED_BYTE_IDENTICAL_AFTER_EQUIVALENCE",
        "reason": "",
        "elapsed_seconds": 0.0,
        "reused": True,
        "reused_file_hashes": hashes,
        "customer_count": len(bundle.customer_home_depot),
        "reassigned_customer_count": old["actual_reassigned"],
        "fallback_steps_beyond_second_nearest": old["fallback_steps"],
        "route_counts_by_depot": json.dumps(
            old["route_counts"],
            ensure_ascii=False,
            sort_keys=True,
        ),
        "assignment_rows": assignment_rows,
    }


def resumed_new_row(
    runner: Any,
    instance_id: str,
    intensity: int,
    elapsed_seconds: float,
) -> dict[str, Any] | None:
    folder = INPUTS / unit_name(instance_id, intensity)
    certificate_path = folder / "input_certificate.json"
    if not certificate_path.is_file():
        return None
    certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    if (
        certificate.get("formal_effect_search_started") is not False
        or certificate.get("objective_evaluations") != 0
    ):
        raise RuntimeError(f"HALT_RESUME_BOUNDARY_DRIFT:{folder.name}")
    bundle = runner.e3.load_bundle(instance_id)
    if certificate["status"] == "INFEASIBLE_INPUT":
        return {
            "unit": folder.name,
            "instance_id": instance_id,
            "mismatch_intensity_nominal_pct": intensity,
            "status": "INFEASIBLE_INPUT",
            "reason": certificate["audit"]["reason"],
            "elapsed_seconds": elapsed_seconds,
            "reused": True,
            "customer_count": len(bundle.customer_home_depot),
            "reassigned_customer_count": "",
            "fallback_steps_beyond_second_nearest": "",
            "route_counts_by_depot": "",
            "assignment_rows": [],
        }
    responsibility_path = folder / "responsibility_map.json"
    skeleton_path = folder / "common_route_skeleton.json"
    if not responsibility_path.is_file() or not skeleton_path.is_file():
        raise RuntimeError(f"HALT_PARTIAL_RESUMED_UNIT:{folder.name}")
    responsibility = json.loads(
        responsibility_path.read_text(encoding="utf-8")
    )
    skeleton = json.loads(skeleton_path.read_text(encoding="utf-8"))
    if (
        responsibility.get("instance_id") != instance_id
        or responsibility.get("mismatch_intensity_nominal_pct")
            != intensity
        or responsibility.get("formal_effect_search_started") is not False
        or responsibility.get("objective_evaluations") != 0
    ):
        raise RuntimeError(f"HALT_RESUMED_UNIT_IDENTITY_DRIFT:{folder.name}")
    original = dict(bundle.customer_home_depot)
    mapping = responsibility["mapping"]
    (
        _original,
        target,
        selected,
        _ineligible,
        selection_failure,
    ) = prepare_selection(runner, bundle, intensity)
    if selection_failure is not None:
        raise RuntimeError(f"HALT_RESUMED_SELECTION_DRIFT:{folder.name}")
    selected_by_id = {
        item["customer_id"]: item for item in selected
    }
    assignment_rows: list[dict[str, Any]] = []
    for customer_id in sorted(original):
        reassigned = mapping[customer_id] != original[customer_id]
        item = selected_by_id.get(customer_id)
        if reassigned and item is None:
            raise RuntimeError(
                f"HALT_RESUMED_SELECTED_SET_DRIFT:{folder.name}:"
                f"{customer_id}"
            )
        absolute_rank: int | str = ""
        rank_hash = ""
        directed_distance: float | str = ""
        if reassigned:
            assert item is not None
            absolute_rank = item["ranking"].index(mapping[customer_id]) + 1
            rank_hash = item["rank_hash"]
            directed_distance = float(
                bundle.instance.distance(
                    mapping[customer_id], customer_id
                )
            )
        assignment_rows.append(
            {
                "instance_id": instance_id,
                "mismatch_intensity_nominal_pct": intensity,
                "customer_id": customer_id,
                "original_registered_depot": original[customer_id],
                "assigned_responsibility_depot": mapping[customer_id],
                "reassigned": reassigned,
                "result_blind_rank_sha256": rank_hash,
                "destination_absolute_distance_rank": absolute_rank,
                "destination_directed_distance_m": directed_distance,
                "destination_rule":
                    "SECOND_NEAREST_THEN_NEXT_IF_D2A_BLOCKED"
                    if reassigned
                    else "UNCHANGED",
            }
        )
    actual = sum(
        mapping[customer_id] != original[customer_id]
        for customer_id in original
    )
    if actual != target:
        raise RuntimeError(f"HALT_RESUMED_TARGET_DRIFT:{folder.name}")
    return {
        "unit": folder.name,
        "instance_id": instance_id,
        "mismatch_intensity_nominal_pct": intensity,
        "status": "PASS_INPUT_MAPPING_AND_ROUTE_GROUPS_ONLY",
        "reason": "",
        "elapsed_seconds": elapsed_seconds,
        "reused": True,
        "customer_count": len(bundle.customer_home_depot),
        "reassigned_customer_count": actual,
        "fallback_steps_beyond_second_nearest":
            responsibility["map_audit"][
                "fallback_steps_beyond_second_nearest"
            ],
        "route_counts_by_depot": json.dumps(
            skeleton["route_counts_by_depot"],
            ensure_ascii=False,
            sort_keys=True,
        ),
        "assignment_rows": assignment_rows,
    }


def collect_artifact_hashes() -> dict[str, str]:
    excluded_parts = {".builder_bin", "__pycache__"}
    excluded_names = {"artifact_hashes.json"}
    paths = sorted(
        path
        for path in HERE.rglob("*")
        if path.is_file()
        and not path.name.startswith("._")
        and path.name not in excluded_names
        and not excluded_parts.intersection(path.parts)
    )
    return {relative(path): sha256(path) for path in paths}


def run_build(workers: int) -> dict[str, Any]:
    protected = verify_protected()
    compile_cpp()
    equivalence_path = HERE / "equivalence_check.json"
    if not equivalence_path.is_file():
        raise RuntimeError("HALT_EQUIVALENCE_CERTIFICATE_MISSING")
    equivalence = json.loads(equivalence_path.read_text(encoding="utf-8"))
    if not equivalence.get("equivalence_check_passed"):
        raise RuntimeError("HALT_EQUIVALENCE_NOT_PASSED")
    runner = load_runner()
    units = eligible_units(runner)
    old_set = set(parse_old_units())
    remaining = [unit for unit in units if unit not in old_set]
    elapsed_by_unit: dict[str, float] = {}
    for prior_log in sorted(HERE.glob("build_progress*.log")):
        for line in prior_log.read_text(encoding="utf-8").splitlines():
            try:
                prior = json.loads(line)
            except json.JSONDecodeError:
                continue
            if prior.get("phase") == "build" and "unit" in prior:
                elapsed_by_unit[prior["unit"]] = float(
                    prior.get("elapsed_seconds", 0.0)
                )
    resumed: list[dict[str, Any]] = []
    pending: list[tuple[str, int]] = []
    for instance_id, intensity in remaining:
        current_unit = unit_name(instance_id, intensity)
        if current_unit not in elapsed_by_unit:
            pending.append((instance_id, intensity))
            continue
        row = resumed_new_row(
            runner,
            instance_id,
            intensity,
            elapsed_by_unit[current_unit],
        )
        if row is None:
            pending.append((instance_id, intensity))
        else:
            resumed.append(row)
    progress = HERE / "build_progress.log"
    rows: list[dict[str, Any]] = []
    assignment_rows: list[dict[str, Any]] = []
    for instance_id, intensity in sorted(old_set):
        row = reused_row(runner, instance_id, intensity)
        assignment_rows.extend(row.pop("assignment_rows"))
        rows.append(row)
        log_progress(
            progress,
            {
                "timestamp_utc": datetime.now(UTC).isoformat(),
                "phase": "build",
                **row,
            },
        )
        print(
            f"BUILD unit={row['unit']} elapsed=0.000000s "
            f"result={row['status']} reused=true",
            flush=True,
        )
    for row in resumed:
        assignment_rows.extend(row.pop("assignment_rows"))
        rows.append(row)
        log_progress(
            progress,
            {
                "timestamp_utc": datetime.now(UTC).isoformat(),
                "phase": "build",
                **row,
            },
        )
        print(
            f"BUILD unit={row['unit']} "
            f"elapsed={row['elapsed_seconds']:.6f}s "
            f"result={row['status']} reused=resume",
            flush=True,
        )
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(build_one, unit): unit for unit in pending
        }
        for future in as_completed(futures):
            row = future.result()
            assignment_rows.extend(row.pop("assignment_rows"))
            rows.append(row)
            log_progress(
                progress,
                {
                    "timestamp_utc": datetime.now(UTC).isoformat(),
                    "phase": "build",
                    **row,
                },
            )
            print(
                f"BUILD unit={row['unit']} "
                f"elapsed={row['elapsed_seconds']:.6f}s "
                f"result={row['status']} reused=false",
                flush=True,
            )
            verify_protected()
    rows.sort(
        key=lambda row: (
            row["instance_id"],
            row["mismatch_intensity_nominal_pct"],
        )
    )
    assignment_rows.sort(
        key=lambda row: (
            row["instance_id"],
            row["mismatch_intensity_nominal_pct"],
            row["customer_id"],
        )
    )
    if len(rows) != 135:
        raise RuntimeError(f"HALT_UNIT_DENOMINATOR:{len(rows)}/135")
    atomic_csv(
        HERE / "input_manifest.csv",
        [
            {
                key: value
                for key, value in row.items()
                if key != "reused_file_hashes"
            }
            for row in rows
        ],
    )
    atomic_csv(HERE / "mismatch_assignment.csv", assignment_rows)
    atomic_csv(
        HERE / "raw_runs.csv",
        [
            {
                "unit": row["unit"],
                "instance_id": row["instance_id"],
                "mismatch_intensity_nominal_pct":
                    row["mismatch_intensity_nominal_pct"],
                "elapsed_seconds": row["elapsed_seconds"],
                "status": row["status"],
                "reason": row["reason"],
                "reused": row["reused"],
                "formal_effect_search_started": False,
                "objective_evaluations": 0,
            }
            for row in rows
        ],
    )
    infeasible = [
        row for row in rows if row["status"] == "INFEASIBLE_INPUT"
    ]
    metadata = {
        "schema": "resetp.e3e6-input-builder-perf.metadata.v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "task_id": TASK_ID,
        "units_expected": 135,
        "units_built_or_reused": len(rows),
        "old_units_reused": len(old_set),
        "new_units_constructed": len(remaining),
        "new_units_resumed_after_builder_upgrade": len(resumed),
        "new_units_constructed_by_final_invocation": len(pending),
        "infeasible_units": len(infeasible),
        "equivalence_check_passed": True,
        "builder": relative(Path(__file__)),
        "cpp_builder": relative(CPP_SOURCE),
        "runner_source_read_only": relative(RUNNER_PATH),
        "python": sys.version,
        "platform": platform.platform(),
        "protected_hashes": protected,
        "formal_effect_search_started": False,
        "objective_evaluations": 0,
        "cost_or_objective_fields_generated_for_new_units": False,
        "old_artifacts_with_historical_integrity_cost_fields_reused":
            len(old_set),
    }
    decision = {
        "schema": "resetp.e3e6-input-builder-perf.decision.v1",
        "verdict": "PASS_INPUT_CONSTRUCTION_COMPLETE",
        "equivalence_check_passed": True,
        "units_built_or_reused": len(rows),
        "infeasible_units": len(infeasible),
        "infeasible_units_retained": True,
        "no_fleet_cap_expansion": True,
        "no_unserved_customers": True,
        "formal_effect_search_started": False,
        "objective_evaluations": 0,
        "scientific_effect_claim_authorized": False,
        "future_search_authorized": False,
    }
    atomic_json(HERE / "metadata.json", metadata)
    atomic_json(HERE / "decision.json", decision)
    atomic_json(
        HERE / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "files": collect_artifact_hashes(),
        },
    )
    verify_protected()
    return {
        "rows": rows,
        "metadata": metadata,
        "decision": decision,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("verify", "build", "all"),
    )
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    if args.command in {"verify", "all"}:
        run_equivalence(args.workers)
    if args.command in {"build", "all"}:
        run_build(args.workers)


if __name__ == "__main__":
    main()
