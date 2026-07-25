#!/usr/bin/env python3
"""Zero-objective engineering gate for a depot/powertrain typed chromosome."""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import multiprocessing as mp
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
import time
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[4]
SOLVER_SRC = REPO_ROOT / "solver/src"
if str(SOLVER_SRC) not in sys.path:
    sys.path.insert(0, str(SOLVER_SRC))

from setp_solver.china81 import load_china81_bundle  # noqa: E402


GATE_DIR = Path(__file__).resolve().parent
V7_TASKS = (
    REPO_ROOT
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v7_small_archive_ledger_20260724/"
    "full_gate/tasks"
)
CONTRACT = (
    REPO_ROOT
    / "docs/handoff/e2_type_aware_resource_chromosome_contract_20260725.md"
)
INSTANCES = (
    "cn-prd-50c-02-V2-LOCATIONS",
    "cn-jjj-100c-02-V2-LOCATIONS",
    "cn-prd-200c-01-V2-LOCATIONS",
)
SEEDS = (3, 4)
ARM = "HGS-M"
STATE_LIMIT = 200_000
SECONDS_LIMIT = 10.0
TOL = 1e-9


@dataclass(frozen=True)
class TypedSequence:
    depot_id: str
    powertrain: str
    customers: tuple[str, ...]
    original_route_lengths: tuple[int, ...]

    @property
    def label(self) -> str:
        return f"{self.depot_id}|{self.powertrain}"


@dataclass(frozen=True)
class SplitResult:
    cost: float
    route_count: int
    cuts: tuple[int, ...]
    states_considered: int
    feasible_segments: int


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def task_dir(instance_id: str, seed: int) -> Path:
    return V7_TASKS / f"D6-E2-STAGED__{instance_id}__seed{seed}"


def load_parent(instance_id: str, seed: int) -> dict[str, Any]:
    path = task_dir(instance_id, seed) / "solution_witnesses.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload[ARM]


def encode_parent(parent: dict[str, Any]) -> tuple[TypedSequence, ...]:
    grouped: dict[tuple[str, str], list[list[str]]] = {}
    seen: set[str] = set()
    for route in parent["routes"]:
        depot = str(route["home_depot_id"])
        powertrain = str(route["vehicle_type"]).lower()
        if powertrain not in {"cv", "ev"}:
            raise ValueError(f"unsupported powertrain {powertrain!r}")
        sequence = [str(node) for node in route["node_sequence"]]
        if sequence[0] != depot or sequence[-1] != depot:
            raise ValueError("route endpoints do not match the typed depot")
        customers = sequence[1:-1]
        duplicate = seen.intersection(customers)
        if duplicate:
            raise ValueError(f"duplicate customers in parent: {sorted(duplicate)}")
        seen.update(customers)
        grouped.setdefault((depot, powertrain), []).append(customers)

    encoded: list[TypedSequence] = []
    for (depot, powertrain), routes in sorted(grouped.items()):
        encoded.append(
            TypedSequence(
                depot_id=depot,
                powertrain=powertrain,
                customers=tuple(itertools.chain.from_iterable(routes)),
                original_route_lengths=tuple(len(route) for route in routes),
            )
        )
    if sum(len(item.customers) for item in encoded) != len(seen):
        raise AssertionError("typed encoding lost a customer")
    return tuple(encoded)


def route_proxy(
    *,
    bundle: Any,
    depot_id: str,
    powertrain: str,
    customers: tuple[str, ...],
) -> tuple[bool, float]:
    if not customers:
        return False, math.inf
    instance = bundle.instance
    nodes = {node.node_id: node for node in instance.nodes}
    capacity = instance.payload_capacity_kg(powertrain, fallback=math.inf)
    load = sum(float(nodes[customer].demand) for customer in customers)
    if load > capacity + TOL:
        return False, math.inf

    sequence = (depot_id, *customers, depot_id)
    clock = float(nodes[depot_id].ready_time) + float(
        nodes[depot_id].service_time
    )
    distance = 0.0
    for left, right in zip(sequence, sequence[1:]):
        arc_distance, travel_seconds, _ = instance.arc_metrics(
            left,
            right,
            powertrain,
            fallback_speed_mps=1.0,
        )
        distance += float(arc_distance)
        arrival = clock + float(travel_seconds)
        node = nodes[right]
        start = max(arrival, float(node.ready_time))
        if start > float(node.due_time) + TOL:
            return False, math.inf
        clock = start + float(node.service_time)
    return True, distance


def typed_split(
    *,
    bundle: Any,
    encoded: TypedSequence,
) -> SplitResult:
    customers = encoded.customers
    n = len(customers)
    fleet_cap = int(
        bundle.fleet_caps_by_depot[encoded.depot_id][
            f"num_{encoded.powertrain}"
        ]
    )
    segment_cost: dict[tuple[int, int], float] = {}
    states_considered = 0
    for begin in range(n):
        for end in range(begin + 1, n + 1):
            states_considered += 1
            feasible, cost = route_proxy(
                bundle=bundle,
                depot_id=encoded.depot_id,
                powertrain=encoded.powertrain,
                customers=customers[begin:end],
            )
            if feasible:
                segment_cost[(begin, end)] = cost

    if states_considered > STATE_LIMIT:
        raise RuntimeError(
            f"{encoded.label}: state limit exceeded "
            f"{states_considered}>{STATE_LIMIT}"
        )

    best: dict[tuple[int, int], tuple[float, tuple[int, ...]]] = {
        (0, 0): (0.0, ())
    }
    for used in range(fleet_cap):
        for begin in range(n):
            prior = best.get((begin, used))
            if prior is None:
                continue
            for end in range(begin + 1, n + 1):
                cost = segment_cost.get((begin, end))
                if cost is None:
                    continue
                key = (end, used + 1)
                proposal = (prior[0] + cost, (*prior[1], end))
                incumbent = best.get(key)
                if incumbent is None or proposal < incumbent:
                    best[key] = proposal

    terminal = [
        (cost, used, cuts)
        for (position, used), (cost, cuts) in best.items()
        if position == n and used > 0
    ]
    if not terminal:
        raise RuntimeError(f"{encoded.label}: no typed split under fleet cap")
    cost, used, cuts = min(terminal)
    return SplitResult(
        cost=cost,
        route_count=used,
        cuts=cuts,
        states_considered=states_considered,
        feasible_segments=len(segment_cost),
    )


def original_partition_is_enumerable(
    *,
    bundle: Any,
    encoded: TypedSequence,
) -> bool:
    cursor = 0
    route_count = len(encoded.original_route_lengths)
    cap = int(
        bundle.fleet_caps_by_depot[encoded.depot_id][
            f"num_{encoded.powertrain}"
        ]
    )
    if route_count > cap:
        return False
    for length in encoded.original_route_lengths:
        begin, cursor = cursor, cursor + length
        feasible, _ = route_proxy(
            bundle=bundle,
            depot_id=encoded.depot_id,
            powertrain=encoded.powertrain,
            customers=encoded.customers[begin:cursor],
        )
        if not feasible:
            return False
    return cursor == len(encoded.customers)


def enumerate_compositions(n: int, max_parts: int) -> Iterable[tuple[int, ...]]:
    for parts in range(1, max_parts + 1):
        for cuts in itertools.combinations(range(1, n), parts - 1):
            yield (*cuts, n)


def synthetic_equivalence() -> dict[str, Any]:
    # A deterministic six-customer segment table with capacity-like forbidden
    # long segments. The DP and exhaustive partition enumeration must agree.
    n = 6
    max_parts = 3
    segment_cost = {
        (begin, end): float((end - begin) ** 2 + begin * 0.125 + end * 0.25)
        for begin in range(n)
        for end in range(begin + 1, min(n, begin + 3) + 1)
    }
    exhaustive: list[tuple[float, tuple[int, ...]]] = []
    for cuts in enumerate_compositions(n, max_parts):
        begin = 0
        cost = 0.0
        valid = True
        for end in cuts:
            if (begin, end) not in segment_cost:
                valid = False
                break
            cost += segment_cost[(begin, end)]
            begin = end
        if valid:
            exhaustive.append((cost, cuts))
    expected = min(exhaustive)

    best: dict[tuple[int, int], tuple[float, tuple[int, ...]]] = {
        (0, 0): (0.0, ())
    }
    for used in range(max_parts):
        for begin in range(n):
            if (begin, used) not in best:
                continue
            prior_cost, prior_cuts = best[(begin, used)]
            for end in range(begin + 1, n + 1):
                if (begin, end) not in segment_cost:
                    continue
                proposal = (
                    prior_cost + segment_cost[(begin, end)],
                    (*prior_cuts, end),
                )
                key = (end, used + 1)
                if key not in best or proposal < best[key]:
                    best[key] = proposal
    actual = min(
        value
        for (position, used), value in best.items()
        if position == n and used > 0
    )
    if actual != expected:
        raise AssertionError(f"synthetic split mismatch: {actual} != {expected}")
    return {
        "customer_count": n,
        "max_routes": max_parts,
        "enumerated_partitions": len(tuple(enumerate_compositions(n, max_parts))),
        "feasible_partitions": len(exhaustive),
        "best_cost": actual[0],
        "best_cuts": list(actual[1]),
        "equivalent": True,
    }


def worker_identity(index: int) -> dict[str, Any]:
    return {
        "index": index,
        "pid": os.getpid(),
        "module": __name__,
        "file": str(Path(__file__).resolve()),
    }


def identity_process(index: int, queue: Any) -> None:
    queue.put(worker_identity(index))


def six_worker_smoke() -> list[dict[str, Any]]:
    context = mp.get_context("spawn")
    queue = context.Queue()
    processes = [
        context.Process(target=identity_process, args=(index, queue))
        for index in range(6)
    ]
    for process in processes:
        process.start()
    rows = [queue.get(timeout=30.0) for _ in processes]
    for process in processes:
        process.join(timeout=30.0)
        if process.exitcode != 0:
            raise RuntimeError(
                f"spawn identity worker exited with {process.exitcode}"
            )
    expected_file = str(Path(__file__).resolve())
    if len({row["pid"] for row in rows}) != 6:
        raise RuntimeError("spawn smoke did not use six distinct workers")
    if any(row["file"] != expected_file for row in rows):
        raise RuntimeError("spawned worker resolved the wrong runner file")
    return rows


def main() -> None:
    started = time.perf_counter()
    smoke = six_worker_smoke()
    synthetic = synthetic_equivalence()
    rows: list[dict[str, Any]] = []
    input_paths: set[Path] = {CONTRACT, Path(__file__).resolve()}
    for instance_id in INSTANCES:
        bundle = load_china81_bundle(REPO_ROOT, instance_id)
        for source_path in bundle.source_paths.values():
            path = Path(source_path)
            if not path.is_absolute():
                path = REPO_ROOT / path
            if path.is_file():
                input_paths.add(path.resolve())
        for seed in SEEDS:
            witness_path = task_dir(instance_id, seed) / "solution_witnesses.json"
            input_paths.add(witness_path.resolve())
            parent = load_parent(instance_id, seed)
            encoded_items = encode_parent(parent)
            parent_started = time.perf_counter()
            total_states = 0
            all_original_enumerable = True
            for encoded in encoded_items:
                result = typed_split(bundle=bundle, encoded=encoded)
                total_states += result.states_considered
                enumerable = original_partition_is_enumerable(
                    bundle=bundle,
                    encoded=encoded,
                )
                all_original_enumerable &= enumerable
                rows.append(
                    {
                        "instance_id": instance_id,
                        "seed": seed,
                        "resource_label": encoded.label,
                        "customer_count": len(encoded.customers),
                        "original_route_count": len(
                            encoded.original_route_lengths
                        ),
                        "original_partition_enumerable": enumerable,
                        "dp_route_count": result.route_count,
                        "dp_proxy_cost": result.cost,
                        "dp_cuts_json": json.dumps(result.cuts),
                        "states_considered": result.states_considered,
                        "feasible_segments": result.feasible_segments,
                    }
                )
            elapsed = time.perf_counter() - parent_started
            if not all_original_enumerable:
                raise RuntimeError(
                    f"{instance_id}/seed{seed}: original partition lost"
                )
            if elapsed > SECONDS_LIMIT:
                raise RuntimeError(
                    f"{instance_id}/seed{seed}: "
                    f"decode {elapsed:.6f}s>{SECONDS_LIMIT}s"
                )
            if total_states > len(encoded_items) * STATE_LIMIT:
                raise RuntimeError("aggregate state count exceeded contract")

    with (GATE_DIR / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    input_rows = [
        {
            "relative_or_absolute_path": (
                str(path.relative_to(REPO_ROOT))
                if path.is_relative_to(REPO_ROOT)
                else str(path)
            ),
            "sha256": sha256(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(input_paths)
    ]
    with (GATE_DIR / "input_hashes.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(input_rows[0]))
        writer.writeheader()
        writer.writerows(input_rows)

    task_groups = {
        (str(row["instance_id"]), int(row["seed"])) for row in rows
    }
    decision = {
        "decision": "PASS_TARC_ZERO_OBJECTIVE_REPRESENTATION_AND_DECODER_GATE",
        "contract_id": "E2-TARC-001",
        "synthetic_equivalence": synthetic,
        "six_worker_smoke": {
            "workers": 6,
            "distinct_pids": len({row["pid"] for row in smoke}),
            "module": smoke[0]["module"],
            "file": smoke[0]["file"],
        },
        "real_parent_tasks": len(task_groups),
        "resource_label_rows": len(rows),
        "all_original_partitions_enumerable": all(
            bool(row["original_partition_enumerable"]) for row in rows
        ),
        "max_states_per_label": max(
            int(row["states_considered"]) for row in rows
        ),
        "objective_evaluations": 0,
        "completion_calls": 0,
        "scorer_calls": 0,
        "search_calls": 0,
        "next_action": (
            "T0 authorizes only the frozen 3-instance x 2-arm G0 in the "
            "contract. It does not authorize any broader run or claim."
        ),
    }
    write_json(GATE_DIR / "decision.json", decision)
    write_json(
        GATE_DIR / "metadata.json",
        {
            "task_id": "E2-TARC-T0-001",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "mode": "ZERO_OBJECTIVE_ENGINEERING_GATE",
            "instances": list(INSTANCES),
            "seeds": list(SEEDS),
            "arm": ARM,
            "workers": 6,
            "wall_seconds": time.perf_counter() - started,
            "input_count": len(input_rows),
            "protected_files_modified": False,
        },
    )
    (GATE_DIR / "report.md").write_text(
        "\n".join(
            [
                "# TARC T0 zero-objective representation/decoder gate",
                "",
                f"Decision: `{decision['decision']}`.",
                "",
                "- Six-customer exhaustive/DP equivalence: PASS.",
                "- Spawn identity: six distinct workers, intended module/file.",
                f"- Real parent tasks: {len(task_groups)}/6.",
                f"- Resource-label rows: {len(rows)}.",
                "- Original parent route partitions retained in the decoder "
                "candidate set: PASS.",
                "- Maximum segment states for one label: "
                f"{decision['max_states_per_label']}.",
                "- Search, completion, scorer and objective calls: 0.",
                "",
                "This gate proves only representation and bounded split "
                "enumerability. It does not prove feasibility after forced "
                "resource inheritance, performance, novelty, BKS/SOTA, or "
                "paper readiness.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    artifact_paths = sorted(
        path
        for path in GATE_DIR.iterdir()
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    )
    write_json(
        GATE_DIR / "artifact_hashes.json",
        {
            str(path.relative_to(GATE_DIR)): sha256(path)
            for path in artifact_paths
        },
    )


if __name__ == "__main__":
    main()
