#!/usr/bin/env python3
"""Final fresh public gate for common+ALNS dual-elite HGS."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PREVIOUS_GATE_PATH = HERE / "run_public_bks_alns_warm_hgs_gate.py"
SPEC = importlib.util.spec_from_file_location(
    "alns_warm_hgs_gate_helpers_for_dual_elite",
    PREVIOUS_GATE_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {PREVIOUS_GATE_PATH}")
PREVIOUS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREVIOUS
SPEC.loader.exec_module(PREVIOUS)
BASE = PREVIOUS.BASE
CORE = PREVIOUS.CORE


OUT = HERE / "public_bks_dual_elite_hgs_gate"
WORKER = HERE / "run_pyvrp_dual_initial_hgs_worker.py"
BUNDLES = BASE.BUNDLES
BKS_ROWS = BASE.BKS_ROWS
BKS_DECISION = BASE.BKS_DECISION
INSTANCES = ("C107", "C206", "R110", "R209", "RC106", "RC206")
HYBRID = "alns_dual_elite_hgs_02"
ALGORITHMS = ("pyvrp_0_12_2_hgs", "project_alns", HYBRID)
SEED = 1
TOTAL_SECONDS = 10.0
WARM_ALNS_SECONDS = 2.0
HGS_SECONDS = 7.5
SWITCH_GUARD_SECONDS = 0.5
TIME_LIMIT_TOLERANCE = 1.08
HYBRID_RELATIVE_TIME_TOLERANCE = 1.05
CONTRACT = REPO / (
    "docs/handoff/outcome_first_multiengine_hybrid_contract_20260719.md"
)
SOURCE_REGISTER = REPO / (
    "docs/handoff/algorithm_source_and_license_register_20260719.md"
)
SOURCES = (
    Path(__file__).resolve(),
    WORKER,
    PREVIOUS_GATE_PATH,
    HERE / "run_public_bks_core_microgate.py",
    CORE.WORKER,
    CORE.HELPERS_PATH,
    CONTRACT,
    SOURCE_REGISTER,
)
PROTECTED = BASE.PROTECTED


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite: {OUT}")
    _configure_helpers()
    BASE._verify_bks_audit()
    BASE._verify_solver_visible_inputs()
    source_hashes = BASE._hash_map(SOURCES)
    protected_hashes = BASE._hash_map(PROTECTED)
    input_hashes = BASE._input_hashes()
    runtime = BASE._runtime_metadata()
    OUT.mkdir(parents=True)

    contracts = {
        name: BASE._bundle_contract(name)
        for name in INSTANCES
    }
    starts = {
        name: CORE.HELPERS.deterministic_common_initial_solution(
            contracts[name]["bundle"].instance,
            capacity=contracts[name]["capacity"],
        )
        for name in INSTANCES
    }
    tasks = sorted(
        (
            (name, algorithm)
            for name in INSTANCES
            for algorithm in ALGORITHMS
        ),
        key=lambda item: BASE._sha_text(
            f"{item[0]}:{item[1]}:seed={SEED}:seconds={TOTAL_SECONDS}:"
            f"warm={WARM_ALNS_SECONDS}:hgs={HGS_SECONDS}:dual=true"
        ),
    )
    rows: list[dict[str, Any]] = []
    solutions: dict[str, Any] = {}
    failures: list[dict[str, str]] = []
    for name, algorithm in tasks:
        try:
            row, solution = _run_arm(
                name=name,
                algorithm=algorithm,
                contract=contracts[name],
                initial=starts[name],
            )
            row["common_initial_sha256"] = BASE._solution_sha(
                starts[name]
            )
            rows.append(row)
            solutions[f"{name}::{algorithm}"] = CORE.solution_payload(
                solution
            )
        except Exception as error:
            failures.append(
                {
                    "instance": name,
                    "algorithm": algorithm,
                    "error": f"{type(error).__name__}: {error}",
                }
            )

    # The BKS table is opened only after all 18 solver tasks finish.
    bks = BASE._load_bks()
    enriched = BASE._associate_bks(rows, bks)
    comparisons, aggregate = BASE._compare(enriched)
    pairwise = _pairwise(comparisons)
    drift = {
        "sources_unchanged": source_hashes == BASE._hash_map(SOURCES),
        "protected_unchanged": (
            protected_hashes == BASE._hash_map(PROTECTED)
        ),
        "inputs_unchanged": input_hashes == BASE._input_hashes(),
    }
    decision = _decision(
        enriched,
        comparisons,
        aggregate,
        pairwise,
        drift,
        failures,
    )
    metadata = {
        "schema_version": "resetp.public-bks-dual-elite-hgs-gate.v1",
        "created_at_utc": BASE.datetime.now(
            BASE.timezone.utc
        ).isoformat(),
        "git_head": BASE._git("rev-parse", "HEAD"),
        "git_status_short": BASE._git("status", "--short"),
        "instances": list(INSTANCES),
        "instance_selection_rule": (
            "lexicographically third-last original instance in each of "
            "C1,C2,R1,R2,RC1,RC2; frozen before any dual-elite result"
        ),
        "algorithms": list(ALGORITHMS),
        "seed": SEED,
        "single_thread_total_seconds_per_arm": TOTAL_SECONDS,
        "hybrid_schedule_seconds": {
            "project_alns_warm": WARM_ALNS_SECONDS,
            "pyvrp_hgs": HGS_SECONDS,
            "stage_switch_guard": SWITCH_GUARD_SECONDS,
        },
        "hybrid_initial_population": (
            "common initial + project ALNS warm elite + PyVRP random starts"
        ),
        "hybrid_schedule_tuned_after_candidate_01": False,
        "objective": (
            "lexicographic vehicle count, then double-precision distance"
        ),
        "bks_association_timing": (
            "parent loaded BKS only after all 18 solver tasks completed"
        ),
        "solver_visible_bks_fields": 0,
        "bks_rows_sha256": BASE._sha(BKS_ROWS),
        "bks_decision_sha256": BASE._sha(BKS_DECISION),
        "source_hashes": source_hashes,
        "protected_hashes": protected_hashes,
        "input_hashes": input_hashes,
        "runtime": runtime,
        "task_order": [
            {"instance": name, "algorithm": algorithm}
            for name, algorithm in tasks
        ],
        "claim_boundary": (
            "Six fresh original Solomon instances, one seed and ten seconds. "
            "This is the final public development architecture gate, not the "
            "56-instance benchmark, a statistical result, or a SOTA claim."
        ),
    }
    BASE._write_csv(OUT / "raw_runs.csv", enriched, failures)
    BASE._write_json(OUT / "comparisons.json", comparisons)
    BASE._write_json(OUT / "aggregate.json", aggregate)
    BASE._write_json(OUT / "pairwise.json", pairwise)
    BASE._write_json(OUT / "solutions.json", solutions)
    BASE._write_json(OUT / "metadata.json", metadata)
    BASE._write_json(OUT / "decision.json", decision)
    BASE._write_text(
        OUT / "report.md",
        _report(comparisons, aggregate, pairwise, decision),
    )
    BASE._write_json(
        OUT / "artifact_hashes.json",
        {
            path.name: BASE._sha(path)
            for path in sorted(OUT.iterdir())
            if path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if not failures else 1


def _configure_helpers() -> None:
    for module in (BASE, PREVIOUS):
        module.OUT = OUT
        module.BUNDLES = BUNDLES
        module.BKS_ROWS = BKS_ROWS
        module.BKS_DECISION = BKS_DECISION
        module.INSTANCES = INSTANCES
        module.ALGORITHMS = ALGORITHMS
        module.SEED = SEED
        module.SOURCES = SOURCES
    BASE.SECONDS = TOTAL_SECONDS
    CORE.OUT = OUT
    CORE.BUNDLES = BUNDLES
    CORE.SEED = SEED


def _run_arm(
    *,
    name: str,
    algorithm: str,
    contract: dict[str, Any],
    initial: Any,
) -> tuple[dict[str, Any], Any]:
    started = time.perf_counter()
    if algorithm == "pyvrp_0_12_2_hgs":
        row, solution = CORE.run_external(
            name=name,
            algorithm=algorithm,
            python=CORE.PY_HGS,
            seconds=TOTAL_SECONDS,
            contract=contract,
            initial=initial,
        )
        row["search_elapsed_seconds"] = float(row["elapsed_seconds"])
    elif algorithm == "project_alns":
        row, solution = CORE.run_alns(
            name=name,
            algorithm=algorithm,
            seconds=TOTAL_SECONDS,
            contract=contract,
            initial=initial,
        )
        row["search_elapsed_seconds"] = float(row["elapsed_seconds"])
    else:
        row, solution = _run_dual_elite(
            name=name,
            contract=contract,
            common_initial=initial,
        )
    row["outer_wall_seconds"] = time.perf_counter() - started
    return row, solution


def _run_dual_elite(
    *,
    name: str,
    contract: dict[str, Any],
    common_initial: Any,
) -> tuple[dict[str, Any], Any]:
    warm_row, warm_solution = CORE.run_alns(
        name=name,
        algorithm=f"{HYBRID}__warm_stage",
        seconds=WARM_ALNS_SECONDS,
        contract=contract,
        initial=common_initial,
    )
    if not bool(warm_row["feasible"]):
        raise RuntimeError(f"warm ALNS infeasible on {name}")
    neutral_dir = OUT / "neutral"
    neutral_dir.mkdir(parents=True, exist_ok=True)
    common_path = neutral_dir / f"{name}__{HYBRID}__common.json"
    warm_path = neutral_dir / f"{name}__{HYBRID}__alns.json"
    output_path = neutral_dir / f"{name}__{HYBRID}.json"
    _write_index_routes(common_path, common_initial, contract)
    _write_index_routes(warm_path, warm_solution, contract)
    command = [
        str(CORE.PY_HGS),
        str(WORKER),
        "--bundle",
        str(BUNDLES / name),
        "--seed",
        str(SEED),
        "--seconds",
        str(HGS_SECONDS),
        "--scale",
        str(CORE.SCALE),
        "--fixed-cost",
        str(int(contract["big_m"] * CORE.SCALE)),
        "--common-initial-routes",
        str(common_path),
        "--alns-initial-routes",
        str(warm_path),
        "--output",
        str(output_path),
    ]
    environment = os.environ.copy()
    environment.update(CORE.THREAD_ENV)
    completed = subprocess.run(
        command,
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=HGS_SECONDS + 30.0,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{HYBRID} failed on {name}: "
            f"{completed.stdout}\n{completed.stderr}"
        )
    neutral = json.loads(output_path.read_text(encoding="utf-8"))
    solution = CORE.neutral_to_solution(neutral, contract)
    independent = CORE.recompute(solution, contract)
    prices = CORE.HELPERS.vrptw_prices(
        capacity=contract["capacity"],
        big_m=contract["big_m"],
    )
    violations = CORE.check_solution(
        solution,
        contract["bundle"].instance,
        prices,
    )
    feasible = bool(
        neutral["feasible"]
        and independent["passed"]
        and not violations
    )
    row = {
        "instance": name,
        "seed": SEED,
        "algorithm": HYBRID,
        "time_limit_seconds": TOTAL_SECONDS,
        "elapsed_seconds": (
            float(warm_row["elapsed_seconds"])
            + float(neutral["elapsed_seconds"])
        ),
        "search_elapsed_seconds": (
            float(warm_row["elapsed_seconds"])
            + float(neutral["elapsed_seconds"])
        ),
        "warm_alns_elapsed_seconds": float(warm_row["elapsed_seconds"]),
        "hgs_elapsed_seconds": float(neutral["elapsed_seconds"]),
        "warm_alns_evaluations": warm_row["evaluations"],
        "warm_route_count": warm_row["route_count"],
        "warm_distance_double": warm_row["distance_double"],
        "warm_solution_sha256": warm_row["solution_sha256"],
        "hgs_initial_solution_count": neutral["initial_solution_count"],
        "route_count": int(independent["route_count"]),
        "distance_double": float(independent["distance_double"]),
        "lexicographic_score": float(independent["score"]),
        "evaluations": "",
        "feasible": feasible,
        "independent_recompute_pass": bool(independent["passed"]),
        "violation_count": len(violations),
        "solution_sha256": hashlib.sha256(
            json.dumps(
                CORE.solution_payload(solution),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "status": "OK" if feasible else "FAIL",
        "hybrid_schedule": (
            f"{WARM_ALNS_SECONDS}s_project_alns+"
            f"{HGS_SECONDS}s_dual_initial_pyvrp_hgs+"
            f"{SWITCH_GUARD_SECONDS}s_guard"
        ),
    }
    return row, solution


def _write_index_routes(
    path: Path,
    solution: Any,
    contract: dict[str, Any],
) -> None:
    nodes = [
        node.node_id
        for node in contract["bundle"].instance.nodes
    ]
    node_to_index = {
        node_id: index for index, node_id in enumerate(nodes)
    }
    BASE._write_json(
        path,
        {
            "routes": [
                [
                    node_to_index[node_id]
                    for node_id in route.node_sequence[1:-1]
                ]
                for route in solution.routes
            ]
        },
    )


def _pairwise(
    comparisons: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for baseline in ("pyvrp_0_12_2_hgs", "project_alns"):
        wins = ties = losses = 0
        for comparison in comparisons:
            scores = comparison["scores"]
            hybrid_score = tuple(scores[HYBRID])
            baseline_score = tuple(scores[baseline])
            wins += int(hybrid_score < baseline_score)
            ties += int(hybrid_score == baseline_score)
            losses += int(hybrid_score > baseline_score)
        result[baseline] = {
            "hybrid_wins": wins,
            "ties": ties,
            "hybrid_losses": losses,
        }
    return result


def _decision(
    rows: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    aggregate: dict[str, Any],
    pairwise: dict[str, dict[str, int]],
    drift: dict[str, bool],
    failures: list[dict[str, str]],
) -> dict[str, Any]:
    if failures:
        return {
            "verdict": "STOP_DUAL_ELITE_HGS_EXECUTION_FAILURE",
            "strong_positive": False,
            "failures": failures,
            "formal_56_instance_run_allowed": False,
            "china81_run_allowed": False,
            "stage2_allowed": False,
        }
    hybrid = aggregate["algorithms"][HYBRID]
    time_checks = _time_checks(rows)
    integrity = bool(
        len(rows) == len(INSTANCES) * len(ALGORITHMS)
        and len(comparisons) == len(INSTANCES)
        and all(bool(row["feasible"]) for row in rows)
        and all(bool(row["independent_recompute_pass"]) for row in rows)
        and all(str(row["status"]) == "OK" for row in rows)
        and all(drift.values())
        and bool(time_checks["pass"])
        and all(
            len(
                {
                    str(row["common_initial_sha256"])
                    for row in rows
                    if row["instance"] == name
                }
            )
            == 1
            for name in INSTANCES
        )
    )
    aggregate_unique_best = (
        aggregate["aggregate_best_algorithms"] == [HYBRID]
    )
    pairwise_pass = all(
        item["hybrid_wins"] >= 3
        and item["hybrid_losses"] <= 1
        for item in pairwise.values()
    )
    strong = bool(
        integrity
        and aggregate_unique_best
        and int(hybrid["best_count"]) >= 4
        and int(hybrid["last_count"]) == 0
        and pairwise_pass
    )
    return {
        "verdict": (
            "STRONG_POSITIVE_DUAL_ELITE_HGS"
            if strong
            else (
                "STOP_DUAL_ELITE_HGS_INTEGRITY"
                if not integrity
                else "STOP_DUAL_ELITE_HGS_NO_QUALITY_WIN"
            )
        ),
        "strong_positive": strong,
        "integrity_pass": integrity,
        "reasons": {
            "integrity": integrity,
            "aggregate_unique_best": aggregate_unique_best,
            "hybrid_best_count_at_least_4": int(hybrid["best_count"]) >= 4,
            "hybrid_last_count_zero": int(hybrid["last_count"]) == 0,
            "pairwise_pass": pairwise_pass,
            "time_fairness_pass": bool(time_checks["pass"]),
        },
        "hybrid_metrics": hybrid,
        "pairwise": pairwise,
        "time_checks": time_checks,
        "failures": [],
        "drift_checks": drift,
        "three_seed_repeat_allowed": strong,
        "formal_56_instance_run_allowed": False,
        "china81_run_allowed": False,
        "stage2_allowed": False,
        "next_action": (
            "three_seed_repeat_on_same_frozen_fresh_six"
            if strong
            else "stop_public_hybrid_development_no_third_candidate"
        ),
    }


def _time_checks(rows: list[dict[str, Any]]) -> dict[str, Any]:
    limit = TOTAL_SECONDS * TIME_LIMIT_TOLERANCE
    absolute = {
        f"{row['instance']}::{row['algorithm']}": (
            float(row["outer_wall_seconds"]) <= limit
        )
        for row in rows
    }
    relative: dict[str, bool] = {}
    for name in INSTANCES:
        arms = {
            str(row["algorithm"]): row
            for row in rows
            if row["instance"] == name
        }
        if set(arms) != set(ALGORITHMS):
            relative[name] = False
            continue
        hybrid_seconds = float(arms[HYBRID]["outer_wall_seconds"])
        slower_pure = max(
            float(arms["pyvrp_0_12_2_hgs"]["outer_wall_seconds"]),
            float(arms["project_alns"]["outer_wall_seconds"]),
        )
        relative[name] = (
            hybrid_seconds
            <= slower_pure * HYBRID_RELATIVE_TIME_TOLERANCE
        )
    return {
        "pass": all(absolute.values()) and all(relative.values()),
        "absolute_limit_seconds": limit,
        "absolute": absolute,
        "hybrid_vs_slower_pure": relative,
    }


def _report(
    comparisons: list[dict[str, Any]],
    aggregate: dict[str, Any],
    pairwise: dict[str, dict[str, int]],
    decision: dict[str, Any],
) -> str:
    lines = [
        "# ALNS+共同起点双精英 HGS 的原始 Solomon+BKS 最终开发门",
        "",
        f"- 判决：`{decision['verdict']}`",
        "- 六题均未用于前两轮公开开发门。",
        "- 每臂十秒；融合时间仍为2.0秒 ALNS + 7.5秒 HGS + 0.5秒余量。",
        "- HGS 同时保留共同初解和 ALNS 暖启动解；BKS 在任务结束后才关联。",
        "",
        "|实例|BKS|纯HGS|纯项目ALNS|双精英融合|当题最好|",
        "|---|---:|---:|---:|---:|---|",
    ]
    for item in comparisons:
        scores = item["scores"]
        lines.append(
            f"|{item['instance']}|"
            f"{item['bks'][0]}/{item['bks'][1]:.2f}|"
            f"{scores['pyvrp_0_12_2_hgs'][0]}/"
            f"{scores['pyvrp_0_12_2_hgs'][1]:.2f}|"
            f"{scores['project_alns'][0]}/"
            f"{scores['project_alns'][1]:.2f}|"
            f"{scores[HYBRID][0]}/{scores[HYBRID][1]:.2f}|"
            f"{', '.join(item['best_algorithms'])}|"
        )
    lines.extend(
        [
            "",
            "|算法|最好数|垫底数|相对BKS多车合计|命中BKS车辆数|完整BKS命中|",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for algorithm in ALGORITHMS:
        item = aggregate["algorithms"][algorithm]
        lines.append(
            f"|{algorithm}|{item['best_count']}|{item['last_count']}|"
            f"{item['total_vehicle_excess_vs_bks']}|"
            f"{item['bks_vehicle_hit_count']}|"
            f"{item['complete_bks_hit_count']}|"
        )
    lines.append("")
    for baseline, item in pairwise.items():
        lines.append(
            f"- 对 {baseline}：{item['hybrid_wins']}胜/"
            f"{item['ties']}平/{item['hybrid_losses']}负。"
        )
    lines.extend(
        [
            "",
            "失败则停止公开融合开发；通过也只允许三种子复核，不授权全量、China81或阶段二。",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
