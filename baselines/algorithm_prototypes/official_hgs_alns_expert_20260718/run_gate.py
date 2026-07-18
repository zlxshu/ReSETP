#!/usr/bin/env python3
"""Development-only, equal-time gate against official HGS and original ALNS.

This runner uses only the three already-observed CVRP development instances.
It does not touch any frozen public test instance, China81, or E2--E7 data.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import importlib.util
import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


REPO = Path(__file__).resolve().parents[3]
PROTOTYPE = Path(__file__).resolve().parent
REFERENCE_ALNS = REPO / "Reference Algorithm" / "ALNS-7.0.0@N-Wouda"
if str(REFERENCE_ALNS) not in sys.path:
    sys.path.insert(0, str(REFERENCE_ALNS))

from alns import ALNS  # noqa: E402
from alns.accept import RecordToRecordTravel  # noqa: E402
from alns.select import RouletteWheel  # noqa: E402
from alns.stop import MaxRuntime  # noqa: E402


BRIDGE_PATH = REPO / "baselines/e2_alns/official_hgs_bridge_20260718.py"
BRIDGE_SPEC = importlib.util.spec_from_file_location("official_hgs_bridge", BRIDGE_PATH)
if BRIDGE_SPEC is None or BRIDGE_SPEC.loader is None:
    raise RuntimeError(f"Cannot load {BRIDGE_PATH}")
BRIDGE = importlib.util.module_from_spec(BRIDGE_SPEC)
sys.modules[BRIDGE_SPEC.name] = BRIDGE
BRIDGE_SPEC.loader.exec_module(BRIDGE)


OFFICIAL_COMMIT = "1a927955cd2861a29d978f0d359d6e647db9319c"
ALNS_COMMIT = "4962d91385990033d9bce81d1407cf846d4fb70c"
INSTANCES = {
    "X-n110-k13": 14971,
    "X-n157-k13": 16876,
    "X-n190-k8": 16980,
}
SEEDS = (1, 2, 3)
DEFAULT_SECONDS = 3.0
TOL = 1.0e-9


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def load_and_verify_binaries() -> tuple[Path, Path, dict[str, Any]]:
    official_manifest_path = (
        REPO / "build/official-hgs-cvrp-1a927955cd28/install_manifest.json"
    )
    official_manifest = json.loads(official_manifest_path.read_text(encoding="utf-8"))
    if (
        official_manifest.get("pinned_commit") != OFFICIAL_COMMIT
        or official_manifest.get("upstream_tests") != "PASS"
    ):
        raise RuntimeError("Official HGS manifest is not the approved pinned install")
    official = Path(official_manifest["binary"])
    if sha256(official) != official_manifest.get("binary_sha256"):
        raise RuntimeError("Official HGS binary hash drift")

    candidate_manifest_path = (
        REPO / "build/official-hgs-alns-expert-20260718/build_manifest.json"
    )
    candidate_manifest = json.loads(candidate_manifest_path.read_text(encoding="utf-8"))
    if (
        candidate_manifest.get("official_commit") != OFFICIAL_COMMIT
        or candidate_manifest.get("upstream_tests") != "PASS"
    ):
        raise RuntimeError("Candidate must be rebuilt with all upstream tests passing")
    candidate = Path(candidate_manifest["binary"])
    if sha256(candidate) != candidate_manifest.get("binary_sha256"):
        raise RuntimeError("Candidate binary hash drift")
    return official, candidate, candidate_manifest


def parse_diagnostics(stdout: str) -> dict[str, Any]:
    line = next(
        (item for item in stdout.splitlines() if item.startswith("ME_HGS_ALNS_DIAGNOSTICS")),
        "",
    )
    parsed: dict[str, Any] = {}
    for token in line.split()[1:]:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        if key == "weights":
            parsed[key] = [float(item) for item in value.split(",")]
        elif key in {
            "hgs_best",
            "expert_best",
            "expert_cpu_seconds",
            "expert_cpu_share",
        }:
            parsed[key] = float(value)
        else:
            parsed[key] = int(value)
    return parsed


def run_hgs(
    *,
    algorithm: str,
    binary: Path,
    instance_path: Path,
    seed: int,
    seconds: float,
    solution_path: Path,
    candidate: bool,
) -> dict[str, Any]:
    problem = BRIDGE.parse_cvrplib(instance_path)
    command = [
        str(binary),
        str(instance_path),
        str(solution_path),
        "-t",
        str(seconds),
        "-seed",
        str(seed),
        "-round",
        "1",
        "-log",
        "1" if candidate else "0",
    ]
    environment = os.environ.copy()
    if candidate:
        environment.update(
            {
                "RESET_ME_EXPERT_ENABLED": "1",
                "RESET_ME_EXPERT_INTERVAL": "10",
                "RESET_ME_EXPERT_STAGNATION": "50",
                "RESET_ME_EXPERT_KIND": "-1",
                "RESET_ME_EXPERT_REMOVAL": "0",
                "RESET_ME_EXPERT_FAILURE_STOP": "40",
                "RESET_ME_EXPERT_MAX_CPU_SHARE": "0.10",
            }
        )
    began = time.perf_counter()
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=max(60.0, seconds + 30.0),
        check=False,
        env=environment,
    )
    elapsed = time.perf_counter() - began
    if completed.returncode != 0 or not solution_path.is_file():
        raise RuntimeError(
            f"{algorithm} failed: rc={completed.returncode}\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    validation = BRIDGE.parse_and_validate_solution(problem, solution_path)
    if not validation["passed"]:
        raise RuntimeError(f"{algorithm} invalid: {validation['failures']}")
    return {
        "algorithm": algorithm,
        "instance": problem.name,
        "seed": seed,
        "time_limit_seconds": seconds,
        "elapsed_seconds": elapsed,
        "cost": float(validation["cost"]),
        "route_count": int(validation["route_count"]),
        "feasible": True,
        "solution_sha256": sha256(solution_path),
        "diagnostics": parse_diagnostics(completed.stdout) if candidate else {},
    }


@dataclass
class OriginalALNSState:
    routes: list[list[int]]
    edge_weight: np.ndarray
    demands: np.ndarray
    capacity: float
    unassigned: list[int]

    def copy(self) -> "OriginalALNSState":
        return OriginalALNSState(
            copy.deepcopy(self.routes),
            self.edge_weight,
            self.demands,
            self.capacity,
            self.unassigned.copy(),
        )

    def objective(self) -> float:
        total = 0.0
        for route in self.routes:
            tour = [0, *route, 0]
            total += sum(
                self.edge_weight[source, target]
                for source, target in zip(tour, tour[1:])
            )
        return float(total)

    def find_route(self, customer: int) -> list[int]:
        for route in self.routes:
            if customer in route:
                return route
        raise ValueError(f"Customer {customer} is not assigned")


def original_alns_problem(problem: Any) -> tuple[np.ndarray, np.ndarray, float]:
    original_customers = sorted(
        node for node in problem.coordinates if node != problem.depot
    )
    original_nodes = [problem.depot, *original_customers]
    edge_weight = np.asarray(
        [
            [BRIDGE.distance(problem, source, target) for target in original_nodes]
            for source in original_nodes
        ],
        dtype=float,
    )
    demands = np.asarray(
        [problem.demands[node] for node in original_nodes],
        dtype=float,
    )
    return edge_weight, demands, float(problem.capacity)


def nearest_neighbor(
    edge_weight: np.ndarray,
    demands: np.ndarray,
    capacity: float,
) -> OriginalALNSState:
    routes: list[list[int]] = []
    unvisited = set(range(1, len(demands)))
    neighbors = [np.argsort(edge_weight[customer]) for customer in range(len(demands))]
    while unvisited:
        route = [0]
        route_demand = 0.0
        while unvisited:
            current = route[-1]
            nearest = next(
                int(node)
                for node in neighbors[current]
                if int(node) != 0 and int(node) in unvisited
            )
            if route_demand + demands[nearest] > capacity:
                break
            route.append(nearest)
            unvisited.remove(nearest)
            route_demand += demands[nearest]
        routes.append(route[1:])
    return OriginalALNSState(routes, edge_weight, demands, capacity, [])


def run_original_alns(
    *,
    instance_path: Path,
    seed: int,
    seconds: float,
) -> dict[str, Any]:
    """Faithful code-form of the official N-Wouda CVRP SISR notebook example."""

    problem = BRIDGE.parse_cvrplib(instance_path)
    edge_weight, demands, capacity = original_alns_problem(problem)
    dimension = len(demands)
    all_neighbors = [
        np.asarray(
            [node for node in np.argsort(edge_weight[customer]) if node != 0],
            dtype=int,
        )
        for customer in range(dimension)
    ]

    def remove_empty_routes(state: OriginalALNSState) -> OriginalALNSState:
        state.routes = [route for route in state.routes if route]
        return state

    def remove_string(
        route: list[int],
        customer: int,
        max_string_size: int,
        rng: np.random.Generator,
    ) -> list[int]:
        size = int(rng.integers(1, min(len(route), max_string_size) + 1))
        start = route.index(customer) - int(rng.integers(size))
        indices = [idx % len(route) for idx in range(start, start + size)]
        removed = []
        for idx in sorted(indices, reverse=True):
            removed.append(route.pop(idx))
        return removed

    def string_removal(
        state: OriginalALNSState,
        rng: np.random.Generator,
    ) -> OriginalALNSState:
        destroyed = state.copy()
        average_route_size = int(np.mean([len(route) for route in state.routes]))
        max_string_size = max(12, average_route_size)
        max_string_removals = min(len(state.routes), 2)
        destroyed_routes: list[list[int]] = []
        center = int(rng.integers(1, dimension))
        for customer_value in all_neighbors[center]:
            customer = int(customer_value)
            if len(destroyed_routes) >= max_string_removals:
                break
            if customer in destroyed.unassigned:
                continue
            route = destroyed.find_route(customer)
            if route in destroyed_routes:
                continue
            destroyed.unassigned.extend(
                remove_string(route, customer, max_string_size, rng)
            )
            destroyed_routes.append(route)
        return remove_empty_routes(destroyed)

    def insertion_cost(customer: int, route: list[int], index: int) -> float:
        predecessor = 0 if index == 0 else route[index - 1]
        successor = 0 if index == len(route) else route[index]
        return float(
            edge_weight[predecessor, customer]
            + edge_weight[customer, successor]
            - edge_weight[predecessor, successor]
        )

    def greedy_repair(
        state: OriginalALNSState,
        rng: np.random.Generator,
    ) -> OriginalALNSState:
        rng.shuffle(state.unassigned)
        while state.unassigned:
            customer = state.unassigned.pop()
            best: tuple[float, list[int], int] | None = None
            for route in state.routes:
                if demands[route].sum() + demands[customer] > capacity:
                    continue
                for index in range(len(route) + 1):
                    cost = insertion_cost(customer, route, index)
                    if best is None or cost < best[0]:
                        best = (cost, route, index)
            if best is None:
                state.routes.append([customer])
            else:
                best[1].insert(best[2], customer)
        return state

    rng = np.random.default_rng(seed)
    initial = nearest_neighbor(edge_weight, demands, capacity)
    search = ALNS(rng)
    search.add_destroy_operator(string_removal)
    search.add_repair_operator(greedy_repair)
    select = RouletteWheel([25, 5, 1, 0], 0.8, 1, 1)
    accept = RecordToRecordTravel.autofit(
        initial.objective(),
        0.02,
        0,
        3000,
    )
    began = time.perf_counter()
    result = search.iterate(initial, select, accept, MaxRuntime(seconds))
    elapsed = time.perf_counter() - began
    best = result.best_state

    flat = [customer for route in best.routes for customer in route]
    expected = list(range(1, dimension))
    failures = []
    if sorted(flat) != expected or len(flat) != len(set(flat)):
        failures.append("CUSTOMER_COVERAGE_NOT_EXACTLY_ONCE")
    if any(demands[route].sum() > capacity for route in best.routes):
        failures.append("CAPACITY_EXCEEDED")
    if failures:
        raise RuntimeError(f"Original ALNS returned invalid solution: {failures}")
    return {
        "algorithm": "original_n_wouda_alns_7_0_0_sisr_example",
        "instance": problem.name,
        "seed": seed,
        "time_limit_seconds": seconds,
        "elapsed_seconds": elapsed,
        "cost": best.objective(),
        "route_count": len(best.routes),
        "feasible": True,
        "solution_sha256": "",
        "diagnostics": {
            "upstream_commit": ALNS_COMMIT,
            "destroy": "official_cvrp_example_string_removal",
            "repair": "official_cvrp_example_greedy_repair",
            "selector": "RouletteWheel([25,5,1,0],0.8)",
            "acceptance": "RecordToRecordTravel.autofit(0.02,0,3000)",
        },
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    strict_double_wins = 0
    saturation_ties = 0
    pair_count = 0
    for instance, optimum in INSTANCES.items():
        by_algorithm = {
            algorithm: sorted(
                [
                    row
                    for row in rows
                    if row["instance"] == instance and row["algorithm"] == algorithm
                ],
                key=lambda row: row["seed"],
            )
            for algorithm in (
                "official_vidal_hgs_cvrp",
                "mechanism_expert_hgs_alns",
                "original_n_wouda_alns_7_0_0_sisr_example",
            )
        }
        candidate = by_algorithm["mechanism_expert_hgs_alns"]
        official = by_algorithm["official_vidal_hgs_cvrp"]
        original_alns = by_algorithm[
            "original_n_wouda_alns_7_0_0_sisr_example"
        ]
        paired = []
        for cand, hgs, alns in zip(candidate, official, original_alns):
            pair_count += 1
            double_win = (
                cand["cost"] < hgs["cost"] - TOL
                and cand["cost"] < alns["cost"] - TOL
            )
            saturated = (
                abs(cand["cost"] - optimum) <= TOL
                and abs(hgs["cost"] - optimum) <= TOL
                and cand["cost"] < alns["cost"] - TOL
            )
            strict_double_wins += int(double_win)
            saturation_ties += int(saturated)
            paired.append(
                {
                    "seed": cand["seed"],
                    "candidate_minus_official": cand["cost"] - hgs["cost"],
                    "candidate_minus_original_alns": cand["cost"] - alns["cost"],
                    "strict_double_win": double_win,
                    "known_optimum_saturation_tie": saturated,
                }
            )
        summaries[instance] = {
            "known_optimum": optimum,
            "median_costs": {
                algorithm: statistics.median(row["cost"] for row in algorithm_rows)
                for algorithm, algorithm_rows in by_algorithm.items()
            },
            "paired": paired,
        }
    return {
        "by_instance": summaries,
        "strict_double_wins": strict_double_wins,
        "known_optimum_saturation_ties": saturation_ties,
        "pair_count": pair_count,
        "strict_contract_pass": strict_double_wins == pair_count,
    }


def write_artifact_hashes(output: Path) -> None:
    rows = []
    for path in sorted(output.rglob("*")):
        if (
            not path.is_file()
            or path.name == "artifact_hashes.json"
            or path.name.startswith("._")
            or "__pycache__" in path.parts
        ):
            continue
        rows.append(
            {
                "path": str(path.relative_to(output)),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    write_json(
        output / "artifact_hashes.json",
        {
            "schema_version": "resetp.artifact-hashes.v1",
            "files": rows,
        },
    )


def seal_appledouble_and_hashes(output: Path) -> None:
    """Preserve contamination evidence, remove sidecars, then hash clean files."""

    sidecars = sorted(
        path for path in output.rglob("._*") if path.is_file()
    )
    if sidecars:
        contamination = {
            "schema_version": "resetp.appledouble-contamination.v1",
            "detected": True,
            "files": [
                {
                    "path": str(path.relative_to(output)),
                    "sha256": sha256(path),
                    "bytes": path.stat().st_size,
                }
                for path in sidecars
            ],
            "action": "Sidecars removed before the authoritative hash manifest.",
        }
        for path in sidecars:
            path.unlink()
        write_json(
            output / "artifact_hashes_contaminated_appledouble.json",
            contamination,
        )
        # Writing the contamination record on an external drive can itself
        # create a new AppleDouble sidecar.
        for path in output.rglob("._*"):
            if path.is_file():
                path.unlink()

    write_artifact_hashes(output)
    for path in output.rglob("._*"):
        if path.is_file():
            path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROTOTYPE / "equal_time_development_gate",
    )
    args = parser.parse_args()
    if args.seconds <= 0:
        raise SystemExit("--seconds must be positive")

    official, candidate, candidate_manifest = load_and_verify_binaries()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    solutions = output / "solutions"
    solutions.mkdir(exist_ok=True)
    source_dir = (
        REPO / "baselines/e2_alns/official_hgs_b_gate_20260718/raw_sources"
    )

    rows: list[dict[str, Any]] = []
    for name in INSTANCES:
        instance_path = source_dir / f"{name}.vrp"
        for seed in SEEDS:
            rows.append(
                run_hgs(
                    algorithm="official_vidal_hgs_cvrp",
                    binary=official,
                    instance_path=instance_path,
                    seed=seed,
                    seconds=args.seconds,
                    solution_path=solutions / f"official__{name}__seed{seed}.sol",
                    candidate=False,
                )
            )
            rows.append(
                run_hgs(
                    algorithm="mechanism_expert_hgs_alns",
                    binary=candidate,
                    instance_path=instance_path,
                    seed=seed,
                    seconds=args.seconds,
                    solution_path=solutions / f"candidate__{name}__seed{seed}.sol",
                    candidate=True,
                )
            )
            rows.append(
                run_original_alns(
                    instance_path=instance_path,
                    seed=seed,
                    seconds=args.seconds,
                )
            )

    summary = summarize(rows)
    metadata = {
        "schema_version": "resetp.mechanism-expert-hgs-alns-gate.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "approval": "EA-HGS-002",
        "development_only": True,
        "formal_search_allowed": False,
        "instances": INSTANCES,
        "seeds": list(SEEDS),
        "same_machine": True,
        "same_time_limit_seconds": args.seconds,
        "official_hgs_commit": OFFICIAL_COMMIT,
        "original_alns_commit": ALNS_COMMIT,
        "candidate_binary_sha256": candidate_manifest["binary_sha256"],
        "candidate_config": {
            "expert_interval": 10,
            "expert_stagnation": 50,
            "expert_failure_stop": 40,
            "expert_max_cpu_share": 0.10,
            "active_experts": ["weak_route_dissolution", "related_string_rebuild"],
            "selection": "adaptive_reward",
            "publication": "side_incumbent_only_at_end",
        },
        "strict_gate": (
            "Every paired task must be a strict candidate win over both official "
            "HGS and original ALNS. A tie at a known optimum is still a failure "
            "until the user explicitly approves a saturation exception."
        ),
        "claim_boundary": (
            "Pure CVRP development evidence only. It cannot validate ReSETP "
            "multi-depot, fleet, charging, carbon, fairness, or dynamic experts."
        ),
    }
    write_json(output / "metadata.json", metadata)
    fieldnames = [
        "algorithm",
        "instance",
        "seed",
        "time_limit_seconds",
        "elapsed_seconds",
        "cost",
        "route_count",
        "feasible",
        "solution_sha256",
        "diagnostics",
    ]
    with (output / "raw_runs.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            encoded = dict(row)
            encoded["diagnostics"] = json.dumps(
                row["diagnostics"],
                ensure_ascii=False,
                sort_keys=True,
            )
            writer.writerow(encoded)
    decision = {
        "schema_version": "resetp.mechanism-expert-hgs-alns-decision.v1",
        "decision": (
            "PASS_STRICT_DOUBLE_WIN"
            if summary["strict_contract_pass"]
            else "HOLD_STRICT_DOUBLE_WIN_NOT_MET"
        ),
        "summary": summary,
        "formal_search_allowed": False,
        "next_action": (
            "Request formal-experiment approval."
            if summary["strict_contract_pass"]
            else "Keep the result as development evidence; redesign or request "
            "a scientifically justified saturation-rule decision without "
            "changing this post-result verdict."
        ),
    }
    write_json(output / "decision.json", decision)

    lines = [
        "# 官方原算法同时间开发门",
        "",
        "这是纯 CVRP、非正式、已观察开发题上的最低成本淘汰赛。",
        f"每个算法每题每种子限时 {args.seconds:.1f} 秒，三题、三种子。",
        "",
        f"严格双赢：{summary['strict_double_wins']}/{summary['pair_count']}。",
        f"已知最优饱和平局：{summary['known_optimum_saturation_ties']}。",
        f"结论：`{decision['decision']}`。",
        "",
        "严格合同没有事后修改：候选必须在每个配对任务上同时严格胜过"
        "官方 Vidal HGS-CVRP 与 N-Wouda 7.0.0 官方 CVRP 示例。已知最优"
        "处客观上无法继续降低，但在用户批准饱和例外前，平局仍按失败。",
        "",
        "本门只说明共同 CVRP 骨架，不能替代多车场、车型补能、碳价、公平"
        "和动态订单各自的机制门。",
        "",
        "## 各题中位数",
        "",
        "| 题 | 官方 HGS | 新算法 | 原装 ALNS |",
        "|---|---:|---:|---:|",
    ]
    for name, item in summary["by_instance"].items():
        medians = item["median_costs"]
        lines.append(
            f"| {name} | {medians['official_vidal_hgs_cvrp']:.3f} | "
            f"{medians['mechanism_expert_hgs_alns']:.3f} | "
            f"{medians['original_n_wouda_alns_7_0_0_sisr_example']:.3f} |"
        )
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    seal_appledouble_and_hashes(output)
    print(json.dumps(decision, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
