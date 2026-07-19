#!/usr/bin/env python3
"""Equal-time core selection on original Solomon instances with SINTEF BKS.

BKS rows are loaded only after all solver processes finish.  Solver-visible
v3 bundles contain no BKS fields.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import numpy as np


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SOLVER_SRC = REPO / "solver/src"
if str(SOLVER_SRC) not in sys.path:
    sys.path.insert(0, str(SOLVER_SRC))

from setp_solver.search.bundle import load_search_bundle  # noqa: E402


OLD_GATE_PATH = (
    REPO
    / "baselines/algorithm_prototypes/algo_reset_20260719/"
    "run_route_core_microgate.py"
)
SPEC = importlib.util.spec_from_file_location(
    "route_core_helpers_bks_gate",
    OLD_GATE_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {OLD_GATE_PATH}")
CORE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CORE
SPEC.loader.exec_module(CORE)


OUT = HERE / "public_bks_core_microgate"
BUNDLES = (
    REPO
    / "baselines/e2_alns/"
    "solomon_sintef_formal_bundles_20260717_v3"
)
BKS_ROWS = (
    REPO
    / "baselines/e2_alns/"
    "e2_solomon_sintef_bks_audit_20260717/raw_runs.csv"
)
BKS_DECISION = (
    REPO
    / "baselines/e2_alns/"
    "e2_solomon_sintef_bks_audit_20260717/decision.json"
)
INSTANCES = (
    "C109",
    "C208",
    "R112",
    "R211",
    "RC108",
    "RC208",
)
ALGORITHMS = (
    "pyvrp_0_12_2_hgs",
    "pyvrp_0_13_4_ils",
    "project_alns",
)
SEED = 1
SECONDS = 2.0
TOL = 1.0e-8
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
    REPO
    / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
)
SOURCES = (
    Path(__file__).resolve(),
    OLD_GATE_PATH,
    CORE.WORKER,
    CORE.HELPERS_PATH,
    REPO
    / "docs/handoff/outcome_first_multiengine_hybrid_contract_20260719.md",
    REPO
    / "docs/handoff/algorithm_source_and_license_register_20260719.md",
)


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite: {OUT}")
    _verify_bks_audit()
    _verify_solver_visible_inputs()
    source_hashes = _hash_map(SOURCES)
    protected_hashes = _hash_map(PROTECTED)
    input_hashes = _input_hashes()
    runtime = _runtime_metadata()

    OUT.mkdir(parents=True)
    CORE.OUT = OUT
    CORE.BUNDLES = BUNDLES
    CORE.SEED = SEED

    contracts = {
        name: _bundle_contract(name)
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
        key=lambda item: _sha_text(
            f"{item[0]}:{item[1]}:seed={SEED}:seconds={SECONDS}"
        ),
    )
    rows: list[dict[str, Any]] = []
    solutions: dict[str, Any] = {}
    failures: list[dict[str, str]] = []
    for name, algorithm in tasks:
        contract = contracts[name]
        initial = starts[name]
        try:
            if algorithm == "pyvrp_0_12_2_hgs":
                row, solution = CORE.run_external(
                    name=name,
                    algorithm=algorithm,
                    python=CORE.PY_HGS,
                    seconds=SECONDS,
                    contract=contract,
                    initial=initial,
                )
            elif algorithm == "pyvrp_0_13_4_ils":
                row, solution = CORE.run_external(
                    name=name,
                    algorithm=algorithm,
                    python=CORE.PY_ILS,
                    seconds=SECONDS,
                    contract=contract,
                    initial=initial,
                )
            else:
                row, solution = CORE.run_alns(
                    name=name,
                    algorithm=algorithm,
                    seconds=SECONDS,
                    contract=contract,
                    initial=initial,
                )
            row["common_initial_sha256"] = _solution_sha(initial)
            rows.append(row)
            solutions[f"{name}::{algorithm}"] = CORE.solution_payload(
                solution
            )
        except Exception as error:  # preserve all failures
            failures.append(
                {
                    "instance": name,
                    "algorithm": algorithm,
                    "error": f"{type(error).__name__}: {error}",
                }
            )

    # BKS is intentionally associated only after every solver task finishes.
    bks = _load_bks()
    enriched = _associate_bks(rows, bks)
    comparisons, aggregate = _compare(enriched)
    drift = {
        "sources_unchanged": source_hashes == _hash_map(SOURCES),
        "protected_unchanged": (
            protected_hashes == _hash_map(PROTECTED)
        ),
        "inputs_unchanged": input_hashes == _input_hashes(),
    }
    decision = _decision(
        enriched,
        comparisons,
        aggregate,
        drift,
        failures,
    )
    metadata = {
        "schema_version": "resetp.public-bks-core-microgate.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_short": _git("status", "--short"),
        "instances": list(INSTANCES),
        "instance_selection_rule": (
            "lexicographically last original instance in each of "
            "C1,C2,R1,R2,RC1,RC2; fixed before solver results"
        ),
        "algorithms": list(ALGORITHMS),
        "seed": SEED,
        "single_thread_wall_seconds_per_run": SECONDS,
        "objective": (
            "lexicographic vehicle count, then double-precision distance"
        ),
        "bks_association_timing": (
            "parent loaded BKS only after all 18 solver tasks completed"
        ),
        "solver_visible_bks_fields": 0,
        "bks_rows_sha256": _sha(BKS_ROWS),
        "bks_decision_sha256": _sha(BKS_DECISION),
        "source_hashes": source_hashes,
        "protected_hashes": protected_hashes,
        "input_hashes": input_hashes,
        "runtime": runtime,
        "task_order": [
            {"instance": name, "algorithm": algorithm}
            for name, algorithm in tasks
        ],
        "claim_boundary": (
            "Six original Solomon instances, one seed, two seconds. "
            "This is a low-cost core warning, not the 56-instance "
            "formal benchmark or a global SOTA claim."
        ),
    }
    _write_csv(OUT / "raw_runs.csv", enriched, failures)
    _write_json(OUT / "comparisons.json", comparisons)
    _write_json(OUT / "aggregate.json", aggregate)
    _write_json(OUT / "solutions.json", solutions)
    _write_json(OUT / "metadata.json", metadata)
    _write_json(OUT / "decision.json", decision)
    _write_text(
        OUT / "report.md",
        _report(comparisons, aggregate, decision),
    )
    _write_json(
        OUT / "artifact_hashes.json",
        {
            path.name: _sha(path)
            for path in sorted(OUT.iterdir())
            if path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if not failures else 1


def _bundle_contract(name: str) -> dict[str, Any]:
    root = BUNDLES / name
    payload = json.loads(
        (root / "instance.json").read_text(encoding="utf-8")
    )
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
    ).lower()
    if "bks" in serialized or "reference_code" in serialized:
        raise RuntimeError(f"solver-visible BKS leak: {name}")
    bundle = load_search_bundle(root)
    matrix = np.asarray(bundle.instance.distance_matrix, dtype=float)
    customer_count = sum(
        str(node.node_type).lower() == "c"
        for node in bundle.instance.nodes
    )
    max_vehicles = int(bundle.instance.num_cv or 0)
    max_edge = float(np.max(matrix))
    upper_bound = float((customer_count + max_vehicles) * max_edge)
    big_m = float(int(upper_bound) + 1)
    if not big_m > upper_bound:
        raise RuntimeError(f"lexicographic big-M proof failed: {name}")
    metadata = payload["metadata"]
    return {
        "bundle": bundle,
        "capacity": float(metadata["vehicle_capacity"]),
        "customer_count": customer_count,
        "max_vehicles": max_vehicles,
        "max_edge": max_edge,
        "distance_upper_bound": upper_bound,
        "big_m": big_m,
        "bundle_hashes": {
            filename: _sha(root / filename)
            for filename in (
                "instance.json",
                "distance_matrix.npy",
                "carbon_profile.csv",
            )
        },
    }


def _verify_solver_visible_inputs() -> None:
    for name in INSTANCES:
        root = BUNDLES / name
        if not root.is_dir():
            raise FileNotFoundError(root)
        text = (root / "instance.json").read_text(
            encoding="utf-8"
        ).lower()
        if "bks" in text or "reference_code" in text:
            raise RuntimeError(f"BKS leaked into solver bundle: {name}")


def _verify_bks_audit() -> None:
    decision = json.loads(
        BKS_DECISION.read_text(encoding="utf-8")
    )
    if (
        decision.get("verdict")
        != "PASS_SOLOMON_SINTEF_BKS_ZERO_SEARCH_AUDIT"
        or int(decision.get("instances_verified", 0)) != 56
        or decision.get("failures")
    ):
        raise RuntimeError("SINTEF BKS audit is not authoritative")


def _load_bks() -> dict[str, dict[str, Any]]:
    rows = {
        str(row["instance"]): row
        for row in csv.DictReader(
            BKS_ROWS.open(encoding="utf-8", newline="")
        )
    }
    missing = [name for name in INSTANCES if name not in rows]
    if missing:
        raise RuntimeError(f"BKS rows missing: {missing}")
    return {name: rows[name] for name in INSTANCES}


def _associate_bks(
    rows: list[dict[str, Any]],
    bks: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    enriched = []
    for row in rows:
        reference = bks[str(row["instance"])]
        bks_vehicles = int(reference["computed_vehicles"])
        bks_distance = float(reference["computed_distance_double"])
        route_count = int(row["route_count"])
        distance = float(row["distance_double"])
        vehicle_excess = route_count - bks_vehicles
        enriched.append(
            {
                **row,
                "bks_vehicles": bks_vehicles,
                "bks_distance_double": bks_distance,
                "vehicle_excess_vs_bks": vehicle_excess,
                "bks_vehicle_count_hit": route_count == bks_vehicles,
                "distance_gap_pct_if_vehicle_hit": (
                    100.0 * (distance - bks_distance) / bks_distance
                    if route_count == bks_vehicles
                    else None
                ),
                "complete_bks_hit": (
                    route_count == bks_vehicles
                    and distance <= bks_distance + 0.005
                ),
            }
        )
    return enriched


def _compare(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    aggregate: dict[str, dict[str, Any]] = {
        algorithm: {
            "algorithm": algorithm,
            "best_count": 0,
            "last_count": 0,
            "total_vehicle_excess_vs_bks": 0,
            "bks_vehicle_hit_count": 0,
            "complete_bks_hit_count": 0,
            "sum_distance_gap_pct_on_vehicle_hits": 0.0,
            "total_distance_double": 0.0,
        }
        for algorithm in ALGORITHMS
    }
    for name in INSTANCES:
        arms = [
            row for row in rows if row["instance"] == name
        ]
        if len(arms) != len(ALGORITHMS):
            continue
        scores = {
            str(row["algorithm"]): (
                int(row["route_count"]),
                float(row["distance_double"]),
            )
            for row in arms
        }
        best = min(scores.values())
        worst = max(scores.values())
        comparison = {
            "instance": name,
            "bks": [
                int(arms[0]["bks_vehicles"]),
                float(arms[0]["bks_distance_double"]),
            ],
            "scores": {
                algorithm: list(scores[algorithm])
                for algorithm in ALGORITHMS
            },
            "best_algorithms": [
                algorithm
                for algorithm, score in scores.items()
                if score == best
            ],
            "last_algorithms": [
                algorithm
                for algorithm, score in scores.items()
                if score == worst
            ],
        }
        comparisons.append(comparison)
        for row in arms:
            algorithm = str(row["algorithm"])
            item = aggregate[algorithm]
            score = scores[algorithm]
            item["best_count"] += int(score == best)
            item["last_count"] += int(score == worst)
            item["total_vehicle_excess_vs_bks"] += int(
                row["vehicle_excess_vs_bks"]
            )
            item["bks_vehicle_hit_count"] += int(
                bool(row["bks_vehicle_count_hit"])
            )
            item["complete_bks_hit_count"] += int(
                bool(row["complete_bks_hit"])
            )
            gap = row["distance_gap_pct_if_vehicle_hit"]
            if gap is not None:
                item["sum_distance_gap_pct_on_vehicle_hits"] += float(
                    gap
                )
            item["total_distance_double"] += float(
                row["distance_double"]
            )
    keys = {
        algorithm: (
            int(item["total_vehicle_excess_vs_bks"]),
            -int(item["bks_vehicle_hit_count"]),
            float(item["sum_distance_gap_pct_on_vehicle_hits"]),
            float(item["total_distance_double"]),
        )
        for algorithm, item in aggregate.items()
    }
    best_key = min(keys.values())
    for algorithm, item in aggregate.items():
        item["aggregate_key"] = list(keys[algorithm])
        item["aggregate_best"] = keys[algorithm] == best_key
    return comparisons, {
        "algorithms": aggregate,
        "aggregate_best_algorithms": [
            algorithm
            for algorithm, key in keys.items()
            if key == best_key
        ],
    }


def _decision(
    rows: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    aggregate: dict[str, Any],
    drift: dict[str, bool],
    failures: list[dict[str, str]],
) -> dict[str, Any]:
    if failures:
        return {
            "verdict": "STOP_PUBLIC_CORE_EXECUTION_FAILURE",
            "strong_positive": False,
            "failures": failures,
            "selected_core": None,
            "formal_56_instance_run_allowed": False,
            "stage2_allowed": False,
        }
    integrity = (
        len(rows) == len(INSTANCES) * len(ALGORITHMS)
        and len(comparisons) == len(INSTANCES)
        and all(bool(row["feasible"]) for row in rows)
        and all(bool(row["independent_recompute_pass"]) for row in rows)
        and all(str(row["status"]) == "OK" for row in rows)
        and all(drift.values())
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
    aggregate_best = list(
        aggregate["aggregate_best_algorithms"]
    )
    selected = (
        aggregate_best[0]
        if len(aggregate_best) == 1
        else None
    )
    selected_metrics = (
        aggregate["algorithms"][selected]
        if selected is not None
        else None
    )
    strong = bool(
        integrity
        and selected_metrics is not None
        and int(selected_metrics["best_count"]) >= 4
        and int(selected_metrics["last_count"]) <= 1
    )
    return {
        "verdict": (
            "STRONG_POSITIVE_PUBLIC_CORE_SELECTED"
            if strong
            else (
                "STOP_PUBLIC_CORE_INTEGRITY"
                if not integrity
                else "HOLD_NO_PUBLIC_CORE_WINNER"
            )
        ),
        "strong_positive": strong,
        "integrity_pass": bool(integrity),
        "selected_core": selected if strong else None,
        "selected_core_metrics": selected_metrics,
        "failures": [],
        "drift_checks": drift,
        "three_seed_development_repeat_allowed": strong,
        "formal_56_instance_run_allowed": False,
        "china81_run_allowed": False,
        "stage2_allowed": False,
        "next_action": (
            "build_one_sparse_hybrid_candidate_around_selected_core"
            if strong
            else "do_not_tune_on_seen_six_instances"
        ),
    }


def _report(
    comparisons: list[dict[str, Any]],
    aggregate: dict[str, Any],
    decision: dict[str, Any],
) -> str:
    lines = [
        "# 原始 Solomon+BKS 公开核心最低成本门",
        "",
        f"- 判决：`{decision['verdict']}`",
        f"- 选中核心：`{decision.get('selected_core')}`",
        "- 范围：六类各一份原始100客户算例、共同seed1、每臂单线程2秒。",
        "- BKS在18个求解任务全部结束后才由父进程关联，未进入求解输入。",
        "",
        "|实例|BKS|HGS|ILS|项目ALNS|当题最好|",
        "|---|---:|---:|---:|---:|---|",
    ]
    for item in comparisons:
        scores = item["scores"]
        lines.append(
            f"|{item['instance']}|"
            f"{item['bks'][0]}/{item['bks'][1]:.2f}|"
            f"{scores['pyvrp_0_12_2_hgs'][0]}/"
            f"{scores['pyvrp_0_12_2_hgs'][1]:.2f}|"
            f"{scores['pyvrp_0_13_4_ils'][0]}/"
            f"{scores['pyvrp_0_13_4_ils'][1]:.2f}|"
            f"{scores['project_alns'][0]}/"
            f"{scores['project_alns'][1]:.2f}|"
            f"{', '.join(item['best_algorithms'])}|"
        )
    lines.extend(
        [
            "",
            "汇总：",
            "",
            "|算法|当题最好数|垫底数|相对BKS多车合计|命中BKS车辆数|完整BKS命中|",
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
            "这只是选核心的警报门，不是混合算法已经胜出，也不授权56例全量。",
            "",
        ]
    )
    return "\n".join(lines)


def _runtime_metadata() -> dict[str, Any]:
    return {
        "hgs_python": str(CORE.PY_HGS),
        "hgs_pyvrp_version": _python_value(
            CORE.PY_HGS,
            "from importlib.metadata import version; print(version('pyvrp'))",
        ),
        "ils_python": str(CORE.PY_ILS),
        "ils_pyvrp_version": _python_value(
            CORE.PY_ILS,
            "from importlib.metadata import version; print(version('pyvrp'))",
        ),
        "project_python": sys.executable,
        "single_thread_environment": CORE.THREAD_ENV,
    }


def _python_value(python: Path, source: str) -> str:
    environment = os.environ.copy()
    environment.update(CORE.THREAD_ENV)
    return subprocess.check_output(
        [str(python), "-c", source],
        cwd=REPO,
        env=environment,
        text=True,
    ).strip()


def _solution_sha(solution: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            CORE.solution_payload(solution),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _input_hashes() -> dict[str, str]:
    rows = {
        str(BKS_ROWS.relative_to(REPO)): _sha(BKS_ROWS),
        str(BKS_DECISION.relative_to(REPO)): _sha(BKS_DECISION),
    }
    for name in INSTANCES:
        for filename in (
            "instance.json",
            "distance_matrix.npy",
            "carbon_profile.csv",
        ):
            path = BUNDLES / name / filename
            rows[str(path.relative_to(REPO))] = _sha(path)
    return rows


def _hash_map(paths: tuple[Path, ...]) -> dict[str, str]:
    return {
        str(path.relative_to(REPO)): _sha(path)
        for path in paths
    }


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    failures: list[dict[str, str]],
) -> None:
    output_rows: list[dict[str, Any]] = rows or failures
    fields = sorted(
        {key for row in output_rows for key in row}
    )
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for row in output_rows:
        writer.writerow(
            {
                key: (
                    json.dumps(value, ensure_ascii=False, sort_keys=True)
                    if isinstance(value, (dict, list, tuple))
                    else value
                )
                for key, value in row.items()
            }
        )
    path.write_text(buffer.getvalue(), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=REPO,
        text=True,
    ).strip()


if __name__ == "__main__":
    raise SystemExit(main())
