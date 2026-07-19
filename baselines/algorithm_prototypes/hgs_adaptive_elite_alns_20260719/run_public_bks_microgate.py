#!/usr/bin/env python3
"""Fresh equal-time Solomon+BKS gate for HGS-AEALNS-03.

The BKS table is not opened until every solver process has finished.
"""

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
PREVIOUS_GATE_PATH = (
    REPO
    / "baselines/algorithm_prototypes/outcome_first_hybrid_20260719/"
    "run_public_bks_alns_warm_hgs_gate.py"
)
SPEC = importlib.util.spec_from_file_location(
    "public_bks_helpers_for_hgs_aealns_03",
    PREVIOUS_GATE_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {PREVIOUS_GATE_PATH}")
PREVIOUS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREVIOUS
SPEC.loader.exec_module(PREVIOUS)
BASE = PREVIOUS.BASE
CORE = PREVIOUS.CORE


OUT = HERE / "public_bks_microgate"
WORKER = HERE / "adaptive_elite_alns_worker.py"
BUNDLES = BASE.BUNDLES
BKS_ROWS = BASE.BKS_ROWS
BKS_DECISION = BASE.BKS_DECISION
INSTANCES = ("C106", "C205", "R109", "R208", "RC105", "RC205")
HYBRID = "hgs_adaptive_elite_alns_03"
PURE_HGS = "pyvrp_0_12_2_hgs"
ALGORITHMS = (PURE_HGS, HYBRID)
SEED = 1
SECONDS = 5.0
TIME_LIMIT_TOLERANCE = 1.08
HYBRID_RELATIVE_TIME_TOLERANCE = 1.10
CONTRACT = REPO / (
    "docs/handoff/hgs_adaptive_elite_alns_contract_20260719.md"
)
SOURCE_REGISTER = REPO / (
    "docs/handoff/algorithm_source_and_license_register_20260719.md"
)
APPROVAL_REGISTER = REPO / (
    "docs/handoff/model_change_approval_register_20260718.md"
)
SOURCES = (
    Path(__file__).resolve(),
    WORKER,
    HERE / "test_adaptive_elite_alns.py",
    PREVIOUS_GATE_PATH,
    REPO
    / "baselines/algorithm_prototypes/outcome_first_hybrid_20260719/"
    "run_public_bks_core_microgate.py",
    CORE.WORKER,
    CORE.HELPERS_PATH,
    CONTRACT,
    SOURCE_REGISTER,
    APPROVAL_REGISTER,
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
            f"{item[0]}:{item[1]}:seed={SEED}:seconds={SECONDS}:"
            "candidate=HGS-AEALNS-03"
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
            row["common_initial_sha256"] = BASE._solution_sha(starts[name])
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

    # Result isolation: the BKS source is opened only after all 12 tasks.
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
        "schema_version": "resetp.hgs-aealns-03-public-bks-microgate.v1",
        "created_at_utc": BASE.datetime.now(
            BASE.timezone.utc
        ).isoformat(),
        "git_head": BASE._git("rev-parse", "HEAD"),
        "git_status_short": BASE._git("status", "--short"),
        "instances": list(INSTANCES),
        "instance_selection_rule": (
            "lexicographically fourth-last original instance in each of "
            "C1,C2,R1,R2,RC1,RC2; frozen before any HGS-AEALNS-03 result"
        ),
        "algorithms": list(ALGORITHMS),
        "seed": SEED,
        "single_thread_seconds_per_arm": SECONDS,
        "objective": (
            "lexicographic vehicle count, then double-precision distance"
        ),
        "candidate_parameters": {
            "gamma": 30,
            "d_max": 30,
            "d_min": 15,
            "archive_size": 8,
            "max_string_size": 12,
            "max_source_routes": 2,
            "repair_schedule": (
                "deterministic alternation of elite-adjacency and "
                "distance-cost regret repair"
            ),
            "route_elimination_schedule": (
                "every third trigger when route count exceeds capacity "
                "lower bound"
            ),
        },
        "bks_association_timing": (
            "parent loaded BKS only after all 12 solver tasks completed"
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
            "Six fresh original Solomon instances, one seed and five "
            "seconds. This is a one-shot development gate, not the "
            "56-instance benchmark, a statistical result, a BKS update, "
            "or a China81 result."
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
    BASE.SECONDS = SECONDS
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
    outer_started = time.perf_counter()
    if algorithm == PURE_HGS:
        row, solution = CORE.run_external(
            name=name,
            algorithm=algorithm,
            python=CORE.PY_HGS,
            seconds=SECONDS,
            contract=contract,
            initial=initial,
        )
        row["search_elapsed_seconds"] = float(row["elapsed_seconds"])
        row["outer_wall_seconds"] = time.perf_counter() - outer_started
        row.update(
            {
                "education_triggers": 0,
                "education_accepted": 0,
                "education_removed_customers": 0,
                "education_seconds": 0.0,
            }
        )
        return row, solution
    return _run_hybrid(
        name=name,
        contract=contract,
        initial=initial,
        outer_started=outer_started,
    )


def _run_hybrid(
    *,
    name: str,
    contract: dict[str, Any],
    initial: Any,
    outer_started: float,
) -> tuple[dict[str, Any], Any]:
    neutral_dir = OUT / "neutral"
    neutral_dir.mkdir(parents=True, exist_ok=True)
    initial_path = neutral_dir / f"{name}__common_initial.json"
    neutral_path = neutral_dir / f"{name}__{HYBRID}.json"
    node_ids = [
        node.node_id
        for node in contract["bundle"].instance.nodes
    ]
    node_to_index = {
        node_id: index
        for index, node_id in enumerate(node_ids)
    }
    BASE._write_json(
        initial_path,
        {
            "routes": [
                [
                    node_to_index[node_id]
                    for node_id in route.node_sequence[1:-1]
                ]
                for route in initial.routes
            ]
        },
    )
    command = [
        str(CORE.PY_HGS),
        str(WORKER),
        "--bundle",
        str(BUNDLES / name),
        "--seed",
        str(SEED),
        "--seconds",
        str(SECONDS),
        "--scale",
        str(CORE.SCALE),
        "--fixed-cost",
        str(int(contract["big_m"] * CORE.SCALE)),
        "--initial-routes",
        str(initial_path),
        "--output",
        str(neutral_path),
    ]
    environment = os.environ.copy()
    environment.update(CORE.THREAD_ENV)
    completed = subprocess.run(
        command,
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=SECONDS + 30.0,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{HYBRID} failed on {name}: "
            f"{completed.stdout}\n{completed.stderr}"
        )
    neutral = json.loads(neutral_path.read_text(encoding="utf-8"))
    solution = CORE.neutral_to_solution(neutral, contract)
    independent = CORE.recompute(solution, contract)
    violations = CORE.check_solution(
        solution,
        contract["bundle"].instance,
        CORE.HELPERS.vrptw_prices(
            capacity=contract["capacity"],
            big_m=contract["big_m"],
        ),
    )
    feasible = bool(
        neutral["feasible"]
        and independent["passed"]
        and not violations
    )
    education = neutral.get("education", {})
    row = {
        "instance": name,
        "seed": SEED,
        "algorithm": HYBRID,
        "time_limit_seconds": SECONDS,
        "elapsed_seconds": float(neutral["elapsed_seconds"]),
        "search_elapsed_seconds": float(neutral["elapsed_seconds"]),
        "outer_wall_seconds": time.perf_counter() - outer_started,
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
        "education": json.dumps(
            education,
            ensure_ascii=False,
            sort_keys=True,
        ),
        "education_triggers": int(
            education.get("education_triggers", 0)
        ),
        "education_accepted": int(
            education.get("education_accepted", 0)
        ),
        "education_removed_customers": int(
            education.get("removed_customers", 0)
        ),
        "education_seconds": float(
            education.get("education_seconds", 0.0)
        ),
        "status": "OK" if feasible else "FAIL",
    }
    return row, solution


def _pairwise(
    comparisons: list[dict[str, Any]],
) -> dict[str, int]:
    wins = ties = losses = 0
    for comparison in comparisons:
        hybrid_score = tuple(comparison["scores"][HYBRID])
        pure_score = tuple(comparison["scores"][PURE_HGS])
        wins += int(hybrid_score < pure_score)
        ties += int(hybrid_score == pure_score)
        losses += int(hybrid_score > pure_score)
    return {
        "hybrid_wins": wins,
        "ties": ties,
        "hybrid_losses": losses,
    }


def _decision(
    rows: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    aggregate: dict[str, Any],
    pairwise: dict[str, int],
    drift: dict[str, bool],
    failures: list[dict[str, str]],
) -> dict[str, Any]:
    if failures:
        return {
            "verdict": "STOP_HGS_AEALNS_03_EXECUTION_FAILURE",
            "strong_positive": False,
            "failures": failures,
            "additional_public_run_allowed": False,
            "formal_56_instance_run_allowed": False,
            "china81_run_allowed": False,
            "stage2_allowed": False,
        }
    time_checks = _time_checks(rows)
    common_start_pass = all(
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
    hybrid_rows = [
        row
        for row in rows
        if row["algorithm"] == HYBRID
    ]
    activation_pass = bool(
        len(hybrid_rows) == len(INSTANCES)
        and all(
            int(row["education_triggers"]) > 0
            and int(row["education_removed_customers"]) > 0
            and float(row["education_seconds"]) > 0.0
            for row in hybrid_rows
        )
    )
    integrity = bool(
        len(rows) == len(INSTANCES) * len(ALGORITHMS)
        and len(comparisons) == len(INSTANCES)
        and all(bool(row["feasible"]) for row in rows)
        and all(bool(row["independent_recompute_pass"]) for row in rows)
        and all(str(row["status"]) == "OK" for row in rows)
        and all(drift.values())
        and common_start_pass
        and activation_pass
        and time_checks["pass"]
    )
    hgs_excess = int(
        aggregate["algorithms"][PURE_HGS][
            "total_vehicle_excess_vs_bks"
        ]
    )
    hybrid_excess = int(
        aggregate["algorithms"][HYBRID][
            "total_vehicle_excess_vs_bks"
        ]
    )
    bks_vehicle_pass = hybrid_excess <= hgs_excess
    zero_loss = int(pairwise["hybrid_losses"]) == 0
    wins = int(pairwise["hybrid_wins"])
    strong = bool(
        integrity
        and zero_loss
        and wins >= 2
        and bks_vehicle_pass
    )
    promising = bool(
        integrity
        and zero_loss
        and wins == 1
        and bks_vehicle_pass
    )
    if strong:
        verdict = "STRONG_POSITIVE_HGS_AEALNS_03"
    elif promising:
        verdict = "PROMISING_BUT_NOT_STRONG_HGS_AEALNS_03"
    elif not integrity:
        verdict = "STOP_HGS_AEALNS_03_INTEGRITY"
    elif not zero_loss:
        verdict = "STOP_HGS_AEALNS_03_ANY_LOSS"
    else:
        verdict = "STOP_HGS_AEALNS_03_NO_STRICT_WIN"
    return {
        "verdict": verdict,
        "strong_positive": strong,
        "promising_but_not_strong": promising,
        "integrity_pass": integrity,
        "reasons": {
            "zero_losses_vs_pure_hgs": zero_loss,
            "at_least_two_strict_wins": wins >= 2,
            "bks_vehicle_excess_not_worse": bks_vehicle_pass,
            "common_initial_pass": common_start_pass,
            "education_activation_pass": activation_pass,
            "time_fairness_pass": bool(time_checks["pass"]),
            "source_input_protected_drift_pass": all(drift.values()),
        },
        "pairwise_vs_pure_hgs": pairwise,
        "bks_vehicle_excess": {
            PURE_HGS: hgs_excess,
            HYBRID: hybrid_excess,
        },
        "aggregate": aggregate,
        "time_checks": time_checks,
        "drift_checks": drift,
        "failures": [],
        "additional_public_run_allowed": False,
        "formal_56_instance_run_allowed": False,
        "china81_run_allowed": False,
        "stage2_allowed": False,
        "next_action": (
            "user_review_before_any_new_experiment"
            if strong
            else "freeze_candidate_without_parameter_or_instance_rescue"
        ),
    }


def _time_checks(rows: list[dict[str, Any]]) -> dict[str, Any]:
    absolute_limit = SECONDS * TIME_LIMIT_TOLERANCE
    absolute = {
        f"{row['instance']}::{row['algorithm']}": (
            float(row["search_elapsed_seconds"]) <= absolute_limit
        )
        for row in rows
    }
    relative: dict[str, bool] = {}
    ratios: dict[str, float | None] = {}
    for name in INSTANCES:
        arms = {
            str(row["algorithm"]): row
            for row in rows
            if row["instance"] == name
        }
        if set(arms) != set(ALGORITHMS):
            relative[name] = False
            ratios[name] = None
            continue
        pure_seconds = float(arms[PURE_HGS]["outer_wall_seconds"])
        hybrid_seconds = float(arms[HYBRID]["outer_wall_seconds"])
        ratio = (
            hybrid_seconds / pure_seconds
            if pure_seconds > 0.0
            else float("inf")
        )
        ratios[name] = ratio
        relative[name] = ratio <= HYBRID_RELATIVE_TIME_TOLERANCE
    return {
        "pass": all(absolute.values()) and all(relative.values()),
        "absolute_limit_seconds": absolute_limit,
        "absolute_search_time": absolute,
        "hybrid_outer_vs_pure_outer_ratio": ratios,
        "hybrid_outer_relative_limit": HYBRID_RELATIVE_TIME_TOLERANCE,
        "hybrid_outer_relative_pass": relative,
    }


def _report(
    comparisons: list[dict[str, Any]],
    aggregate: dict[str, Any],
    pairwise: dict[str, int],
    decision: dict[str, Any],
) -> str:
    lines = [
        "# HGS-AEALNS-03 原始 Solomon+BKS 最小门",
        "",
        f"- 判决：`{decision['verdict']}`",
        "- 两臂均为单线程、seed 1、共同确定性初解、每臂五秒。",
        "- BKS在12个求解任务完成后才关联，没有进入求解器输入。",
        "- 先比车辆数，再比双精度距离。",
        "",
        "|实例|BKS|纯HGS|HGS-AEALNS-03|当题最好|",
        "|---|---:|---:|---:|---|",
    ]
    for item in comparisons:
        scores = item["scores"]
        lines.append(
            f"|{item['instance']}|"
            f"{item['bks'][0]}/{item['bks'][1]:.2f}|"
            f"{scores[PURE_HGS][0]}/{scores[PURE_HGS][1]:.2f}|"
            f"{scores[HYBRID][0]}/{scores[HYBRID][1]:.2f}|"
            f"{', '.join(item['best_algorithms'])}|"
        )
    lines.extend(
        [
            "",
            f"逐题胜平负：{pairwise['hybrid_wins']}胜/"
            f"{pairwise['ties']}平/{pairwise['hybrid_losses']}负。",
            "",
            "|算法|当题最好数|相对BKS多车合计|BKS车辆数命中|完整BKS命中|",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for algorithm in ALGORITHMS:
        item = aggregate["algorithms"][algorithm]
        lines.append(
            f"|{algorithm}|{item['best_count']}|"
            f"{item['total_vehicle_excess_vs_bks']}|"
            f"{item['bks_vehicle_hit_count']}|"
            f"{item['complete_bks_hit_count']}|"
        )
    lines.extend(
        [
            "",
            "这只是单种子开发门。无论结果如何，都不自动授权56题、"
            "China81、阶段二或论文优胜结论。",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
