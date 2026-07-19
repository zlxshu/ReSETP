#!/usr/bin/env python3
"""Fresh Solomon+BKS gate for the frozen ALNS -> HGS hybrid.

The six instances in this gate were not used by the preceding two-second
core screen.  BKS rows are loaded only after all solver tasks finish.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BASE_GATE_PATH = HERE / "run_public_bks_core_microgate.py"
SPEC = importlib.util.spec_from_file_location(
    "public_bks_core_gate_helpers_for_warm_hgs",
    BASE_GATE_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {BASE_GATE_PATH}")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
CORE = BASE.CORE


OUT = HERE / "public_bks_alns_warm_hgs_gate"
BUNDLES = BASE.BUNDLES
BKS_ROWS = BASE.BKS_ROWS
BKS_DECISION = BASE.BKS_DECISION
INSTANCES = (
    "C108",
    "C207",
    "R111",
    "R210",
    "RC107",
    "RC207",
)
ALGORITHMS = (
    "pyvrp_0_12_2_hgs",
    "project_alns",
    "alns_warm_hgs_01",
)
SEED = 1
TOTAL_SECONDS = 10.0
WARM_ALNS_SECONDS = 2.0
HGS_SECONDS = 7.5
SWITCH_GUARD_SECONDS = 0.5
TIME_LIMIT_TOLERANCE = 1.08
HYBRID_RELATIVE_TIME_TOLERANCE = 1.05
TOL = 1.0e-8
CONTRACT = REPO / (
    "docs/handoff/outcome_first_multiengine_hybrid_contract_20260719.md"
)
SOURCE_REGISTER = REPO / (
    "docs/handoff/algorithm_source_and_license_register_20260719.md"
)
SOURCES = (
    Path(__file__).resolve(),
    BASE_GATE_PATH,
    CORE.WORKER,
    CORE.HELPERS_PATH,
    CONTRACT,
    SOURCE_REGISTER,
)
PROTECTED = BASE.PROTECTED


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite: {OUT}")
    _configure_imported_helpers()
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
            f"warm={WARM_ALNS_SECONDS}:hgs={HGS_SECONDS}"
        ),
    )
    rows: list[dict[str, Any]] = []
    solutions: dict[str, Any] = {}
    failures: list[dict[str, str]] = []
    for name, algorithm in tasks:
        contract = contracts[name]
        initial = starts[name]
        try:
            row, solution = _run_arm(
                name=name,
                algorithm=algorithm,
                contract=contract,
                initial=initial,
            )
            row["common_initial_sha256"] = BASE._solution_sha(initial)
            rows.append(row)
            solutions[f"{name}::{algorithm}"] = CORE.solution_payload(
                solution
            )
        except Exception as error:  # preserve every failure
            failures.append(
                {
                    "instance": name,
                    "algorithm": algorithm,
                    "error": f"{type(error).__name__}: {error}",
                }
            )

    # Solver tasks are complete before the parent associates any BKS values.
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
        "schema_version": "resetp.public-bks-alns-warm-hgs-gate.v1",
        "created_at_utc": BASE.datetime.now(
            BASE.timezone.utc
        ).isoformat(),
        "git_head": BASE._git("rev-parse", "HEAD"),
        "git_status_short": BASE._git("status", "--short"),
        "instances": list(INSTANCES),
        "instance_selection_rule": (
            "lexicographically second-last original instance in each of "
            "C1,C2,R1,R2,RC1,RC2; frozen after the separate last-instance "
            "core screen and before any fusion result"
        ),
        "algorithms": list(ALGORITHMS),
        "seed": SEED,
        "single_thread_total_seconds_per_arm": TOTAL_SECONDS,
        "hybrid_schedule_seconds": {
            "project_alns_warm": WARM_ALNS_SECONDS,
            "pyvrp_hgs": HGS_SECONDS,
            "stage_switch_guard": SWITCH_GUARD_SECONDS,
        },
        "hybrid_schedule_tuned": False,
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
            "This is a development gate, not the 56-instance benchmark, "
            "a statistical result, or a SOTA claim."
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


def _configure_imported_helpers() -> None:
    BASE.OUT = OUT
    BASE.BUNDLES = BUNDLES
    BASE.BKS_ROWS = BKS_ROWS
    BASE.BKS_DECISION = BKS_DECISION
    BASE.INSTANCES = INSTANCES
    BASE.ALGORITHMS = ALGORITHMS
    BASE.SEED = SEED
    BASE.SECONDS = TOTAL_SECONDS
    BASE.SOURCES = SOURCES
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
        row["outer_wall_seconds"] = time.perf_counter() - outer_started
        return row, solution
    if algorithm == "project_alns":
        row, solution = CORE.run_alns(
            name=name,
            algorithm=algorithm,
            seconds=TOTAL_SECONDS,
            contract=contract,
            initial=initial,
        )
        row["search_elapsed_seconds"] = float(row["elapsed_seconds"])
        row["outer_wall_seconds"] = time.perf_counter() - outer_started
        return row, solution
    return _run_alns_warm_hgs(
        name=name,
        contract=contract,
        initial=initial,
        outer_started=outer_started,
    )


def _run_alns_warm_hgs(
    *,
    name: str,
    contract: dict[str, Any],
    initial: Any,
    outer_started: float,
) -> tuple[dict[str, Any], Any]:
    warm_row, warm_solution = CORE.run_alns(
        name=name,
        algorithm="alns_warm_hgs_01__warm_stage",
        seconds=WARM_ALNS_SECONDS,
        contract=contract,
        initial=initial,
    )
    if not bool(warm_row["feasible"]):
        raise RuntimeError(f"warm ALNS infeasible on {name}")
    warm_payload = CORE.solution_payload(warm_solution)
    warm_path = OUT / "neutral" / f"{name}__hybrid_warm_initial.json"
    warm_path.parent.mkdir(parents=True, exist_ok=True)
    BASE._write_json(
        warm_path,
        {
            "routes": [
                route["node_sequence"]
                for route in warm_payload["routes"]
            ],
            "solution_sha256": _payload_sha(warm_payload),
        },
    )
    hgs_row, solution = CORE.run_external(
        name=name,
        algorithm="alns_warm_hgs_01",
        python=CORE.PY_HGS,
        seconds=HGS_SECONDS,
        contract=contract,
        initial=warm_solution,
    )
    hgs_search_seconds = float(hgs_row["elapsed_seconds"])
    warm_search_seconds = float(warm_row["elapsed_seconds"])
    hgs_row.update(
        {
            "algorithm": "alns_warm_hgs_01",
            "time_limit_seconds": TOTAL_SECONDS,
            "search_elapsed_seconds": (
                warm_search_seconds + hgs_search_seconds
            ),
            "outer_wall_seconds": time.perf_counter() - outer_started,
            "warm_alns_elapsed_seconds": warm_search_seconds,
            "hgs_elapsed_seconds": hgs_search_seconds,
            "warm_alns_evaluations": warm_row["evaluations"],
            "warm_route_count": warm_row["route_count"],
            "warm_distance_double": warm_row["distance_double"],
            "warm_solution_sha256": warm_row["solution_sha256"],
            "hybrid_schedule": (
                f"{WARM_ALNS_SECONDS}s_project_alns+"
                f"{HGS_SECONDS}s_pyvrp_hgs+"
                f"{SWITCH_GUARD_SECONDS}s_guard"
            ),
        }
    )
    return hgs_row, solution


def _payload_sha(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _pairwise(
    comparisons: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    hybrid = "alns_warm_hgs_01"
    for baseline in ("pyvrp_0_12_2_hgs", "project_alns"):
        wins = ties = losses = 0
        for comparison in comparisons:
            scores = comparison["scores"]
            h_score = tuple(scores[hybrid])
            b_score = tuple(scores[baseline])
            wins += int(h_score < b_score)
            ties += int(h_score == b_score)
            losses += int(h_score > b_score)
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
            "verdict": "STOP_ALNS_WARM_HGS_EXECUTION_FAILURE",
            "strong_positive": False,
            "failures": failures,
            "formal_56_instance_run_allowed": False,
            "china81_run_allowed": False,
            "stage2_allowed": False,
        }
    hybrid = aggregate["algorithms"]["alns_warm_hgs_01"]
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
    integrity = bool(
        len(rows) == len(INSTANCES) * len(ALGORITHMS)
        and len(comparisons) == len(INSTANCES)
        and all(bool(row["feasible"]) for row in rows)
        and all(bool(row["independent_recompute_pass"]) for row in rows)
        and all(str(row["status"]) == "OK" for row in rows)
        and all(drift.values())
        and common_start_pass
        and time_checks["pass"]
    )
    aggregate_unique_best = (
        aggregate["aggregate_best_algorithms"]
        == ["alns_warm_hgs_01"]
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
    reasons = {
        "integrity": integrity,
        "aggregate_unique_best": aggregate_unique_best,
        "hybrid_best_count_at_least_4": int(hybrid["best_count"]) >= 4,
        "hybrid_last_count_zero": int(hybrid["last_count"]) == 0,
        "pairwise_pass": pairwise_pass,
        "time_fairness_pass": bool(time_checks["pass"]),
    }
    return {
        "verdict": (
            "STRONG_POSITIVE_ALNS_WARM_HGS"
            if strong
            else (
                "STOP_ALNS_WARM_HGS_INTEGRITY"
                if not integrity
                else "STOP_ALNS_WARM_HGS_NO_QUALITY_WIN"
            )
        ),
        "strong_positive": strong,
        "integrity_pass": integrity,
        "reasons": reasons,
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
            else "freeze_candidate_without_ratio_rescue"
        ),
    }


def _time_checks(rows: list[dict[str, Any]]) -> dict[str, Any]:
    per_run_limit = TOTAL_SECONDS * TIME_LIMIT_TOLERANCE
    absolute = {
        f"{row['instance']}::{row['algorithm']}": (
            float(row["outer_wall_seconds"]) <= per_run_limit
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
        hybrid_seconds = float(
            arms["alns_warm_hgs_01"]["outer_wall_seconds"]
        )
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
        "absolute_limit_seconds": per_run_limit,
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
        "# ALNS 预压缩 → HGS 的原始 Solomon+BKS 新鲜门",
        "",
        f"- 判决：`{decision['verdict']}`",
        "- 六题均未用于前一轮两秒核心筛选。",
        "- 每臂总预算十秒；融合只测试一次固定的 2.0秒 ALNS + "
        "7.5秒 HGS + 0.5秒切换余量。",
        "- BKS在18个任务结束后才关联，未进入求解器。",
        "",
        "|实例|BKS|纯HGS|纯项目ALNS|ALNS→HGS|当题最好|",
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
            f"{scores['alns_warm_hgs_01'][0]}/"
            f"{scores['alns_warm_hgs_01'][1]:.2f}|"
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
    lines.extend(
        [
            "",
            "逐对手胜平负：",
            "",
        ]
    )
    for baseline, item in pairwise.items():
        lines.append(
            f"- 对 {baseline}："
            f"{item['hybrid_wins']}胜/"
            f"{item['ties']}平/"
            f"{item['hybrid_losses']}负。"
        )
    lines.extend(
        [
            "",
            "即使通过，这仍只是单种子开发信号；不授权56题全量、China81或阶段二。",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
