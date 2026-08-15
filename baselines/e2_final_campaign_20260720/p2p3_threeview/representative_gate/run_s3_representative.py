#!/usr/bin/env python3
"""S3: preregistered representative China81 four-arm formal batch."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import multiprocessing as mp
import os
import platform
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = ROOT / "baselines/e2_final_campaign_20260720/mv_hgs_sp_final"
OUT = Path(__file__).resolve().parent
S2_DECISION_V1 = ROOT / "baselines/e2_final_campaign_20260720/p2p3_threeview/full_gate/decision.json"
S2_DECISION_V2 = ROOT / "baselines/e2_final_campaign_20260720/p2p3_threeview/full_gate/decision_v2.json"
S2_DECISION = S2_DECISION_V2
S2_RAW = ROOT / "baselines/e2_final_campaign_20260720/p2p3_threeview/full_gate/raw_runs.csv"
P3_RAW = PACKAGE / "p3_china81_gate/raw_runs.csv"
P3_RUNNER = PACKAGE / "run_p3_china81_formal.py"
ARMS = ("cv_only", "naive_ev", "mechanism_ev", "MV-HGS-SP")
SEEDS = tuple(range(1, 11))
WORKERS = 6
ROTATION = ("cv_only", "naive_ev", "mechanism_ev")
MAX_EPOCHS = 4
STALL_EPOCHS = 2
SP_TIME = 10.0
EPS = 1.0e-6
REGISTERED_EXCEPTION_ID = "S2-INFEASIBLE-UNIT-001"
S2_ALLOWED_DECISIONS = {
    "PASS_S2_FULL_THREEVIEW",
    "PASS_S2_FULL_THREEVIEW_WITH_REGISTERED_INFEASIBLE_UNIT",
}
SINGLE_ARM_FAILURE_RATE_LIMIT = 0.05
FEATURES = (
    "customer_count", "depot_count", "demand_dispersion",
    "time_window_tightness", "ev_reachability",
)

for path in (ROOT / "solver/src", PACKAGE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_p3_china81_formal as p3  # noqa: E402
from setp_solver.cost import ev_instance_arc_energy_kwh  # noqa: E402

RAW_FIELDS = [
    "instance_id", "n", "seed", "arm", "status", "cost", "cpu_seconds",
    "violation_count", "violations", "epochs_run", "hgs_iterations",
    "trajectory_file", "witness_file", "error_type", "error",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNAVAILABLE"


def _protected_hashes() -> dict[str, str]:
    paths = [
        ROOT / "solver/src/setp_solver/cost.py",
        ROOT / "solver/src/setp_solver/check.py",
        ROOT / "solver/src/setp_solver/search/evaluation.py",
        ROOT / "solver/src/setp_solver/prices.py",
        ROOT / "docs/paper_submission_final/RETIRED_paper_main.tex",
        P3_RUNNER, P3_RAW, S2_RAW,
    ]
    return {
        str(path.relative_to(ROOT)): _sha256(path)
        for path in paths if path.exists()
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _is_registered_infeasible(row: dict[str, str]) -> bool:
    """Recognize only the approved proxy-to-exact time-window failure class."""
    if row.get("arm") != "naive_ev" or row.get("status") not in {"ERROR", "INFEASIBLE"}:
        return False
    evidence = " ".join((row.get("error", ""), row.get("violations", ""))).lower()
    return "time_window" in evidence and "late by" in evidence


def _instance_features(instance_id: str) -> dict[str, float]:
    bundle = p3.load_china81_bundle(ROOT, instance_id)
    customers = [node for node in bundle.instance.nodes if node.node_type.lower() == "c"]
    depots = [node for node in bundle.instance.nodes if node.node_type.lower() == "d"]
    demands = [float(node.demand) for node in customers]
    mean_demand = statistics.fmean(demands)
    demand_dispersion = statistics.pstdev(demands) / mean_demand
    horizon = float(p3.CHINA81_HORIZON_END_SECOND - p3.CHINA81_HORIZON_START_SECOND) if hasattr(p3, "CHINA81_HORIZON_END_SECOND") else 16.0 * 3600.0
    time_window_tightness = statistics.fmean(
        float(node.due_time - node.ready_time) for node in customers
    ) / horizon
    ev = bundle.instance.vehicle_profile("ev")
    assert ev is not None and ev.battery_kwh is not None
    half_load = 0.5 * float(ev.payload_capacity_kg)
    reachability: list[float] = []
    for customer in customers:
        depot_id = bundle.customer_home_depot[customer.node_id]
        energy = ev_instance_arc_energy_kwh(
            bundle.instance, depot_id, customer.node_id, half_load, bundle.prices
        )
        reachability.append(
            min(1.0, float(ev.battery_kwh) / max(float(energy), 1.0e-12))
        )
    return {
        "customer_count": float(len(customers)),
        "depot_count": float(len(depots)),
        "demand_dispersion": float(demand_dispersion),
        "time_window_tightness": float(time_window_tightness),
        "ev_reachability": float(statistics.fmean(reachability)),
    }


def _registration() -> dict[str, Any]:
    path = OUT / "representative_registration.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    instance_ids = p3._instance_list()
    raw = {instance_id: _instance_features(instance_id) for instance_id in instance_ids}
    means = {
        feature: statistics.fmean(raw[instance_id][feature] for instance_id in instance_ids)
        for feature in FEATURES
    }
    scales = {
        feature: statistics.pstdev(raw[instance_id][feature] for instance_id in instance_ids)
        for feature in FEATURES
    }
    zrows: dict[str, dict[str, float]] = {}
    for instance_id in instance_ids:
        zrows[instance_id] = {
            feature: (
                (raw[instance_id][feature] - means[feature]) / scales[feature]
                if scales[feature] > 0 else 0.0
            )
            for feature in FEATURES
        }
    medians = {
        feature: statistics.median(zrows[instance_id][feature] for instance_id in instance_ids)
        for feature in FEATURES
    }
    distances = {
        instance_id: math.sqrt(sum(
            (zrows[instance_id][feature] - medians[feature]) ** 2
            for feature in FEATURES
        ))
        for instance_id in instance_ids
    }
    selected = min(instance_ids, key=lambda instance_id: (distances[instance_id], instance_id))
    payload = {
        "schema_version": "resetp.e2-final-campaign.s3-representative-registration.v1",
        "registered_at_utc": datetime.now(timezone.utc).isoformat(),
        "selection_rule": "81-instance input-only features; per-feature population z-score; nearest Euclidean distance to feature-wise median; instance_id lexicographic tie-break",
        "feature_definitions": {
            "customer_count": "number of customer nodes",
            "depot_count": "number of depot nodes",
            "demand_dispersion": "population standard deviation of customer demand divided by mean demand",
            "time_window_tightness": "mean customer time-window width divided by 16-hour China81 work horizon",
            "ev_reachability": "mean min(1, EV full battery kWh / half-payload EV energy from customer home depot to customer)",
        },
        "features": raw,
        "z_scores": zrows,
        "feature_means": means,
        "feature_population_scales": scales,
        "z_score_medians": medians,
        "distance_to_median": distances,
        "selected_instance_id": selected,
        "tie_candidates": [
            instance_id for instance_id in instance_ids
            if abs(distances[instance_id] - distances[selected]) <= 1.0e-12
        ],
        "result_blind": True,
    }
    _write_json(path, payload)
    return payload


def _solution_payload(solution: Any, objective: float, breakdown: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw_cost": float(objective),
        "breakdown": {str(key): float(value) for key, value in breakdown.items() if isinstance(value, (int, float))},
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
                "energy_kwh": action.energy_kwh,
                "occupancy_minutes": action.occupancy_minutes,
                "charge_start_second": action.charge_start_second,
                "charge_day_offset": action.charge_day_offset,
                "start_energy_kwh": action.start_energy_kwh,
                "end_energy_kwh": action.end_energy_kwh,
                "charging_curve_id": action.charging_curve_id,
            }
            for action in solution.charging_actions
        ],
        "cross_site_services": [
            {"customer_id": item.customer_id, "served_by_depot_id": item.served_by_depot_id}
            for item in solution.cross_site_services
        ],
    }


def _record(trace: list[dict[str, Any]], state: list[float], elapsed: float, cost: float, source: str) -> None:
    if float(cost) < state[0] - EPS:
        state[0] = float(cost)
        trace.append({"elapsed_seconds": float(elapsed), "cost": float(cost), "source": source})


def _single_arm(bundle: Any, instance_id: str, seed: int, mode: str) -> tuple[float, float, list[dict[str, Any]], Any, dict[str, Any], int]:
    caps = p3.TIER_CAPS[p3._tier_of(instance_id)]
    common = p3.complete_china81_route_skeleton(
        p3.build_initial_solution(
            bundle.instance, bundle.time_profile, bundle.prices,
            introduce_ev=False, require_charging_signal=False,
        ), bundle,
    )
    started = perf_counter()
    problem = p3.build_pyvrp_problem(bundle, route_proxy_mode=mode)
    stop = p3.MultipleCriteria(
        [p3.NoImprovement(int(caps["K_M"])), p3.MaxRuntime(caps["CAP_M"])]
    )
    epoch = p3._run_epoch(bundle, problem, common.solution, seed=seed, stop=stop, warm_elites=())
    completion = min((*epoch.elite_completions, common), key=lambda item: item.objective)
    objective, breakdown, violations = p3.exact_china81_score(completion.solution, bundle)
    trace = [{"elapsed_seconds": 0.0, "cost": float(common.objective), "source": "common_initial"}]
    state = [float(common.objective)]
    _record(trace, state, float(epoch.elapsed_seconds), float(objective), "single_view_epoch_end")
    return float(objective), perf_counter() - started, trace, completion.solution, breakdown, int(epoch.stats.get("hgs_iterations", -1))


def _full_arm(bundle: Any, instance_id: str, seed: int) -> tuple[float, float, list[dict[str, Any]], Any, dict[str, Any], int, int]:
    caps = p3.TIER_CAPS[p3._tier_of(instance_id)]
    common = p3.complete_china81_route_skeleton(
        p3.build_initial_solution(
            bundle.instance, bundle.time_profile, bundle.prices,
            introduce_ev=False, require_charging_signal=False,
        ), bundle,
    )
    started = perf_counter()
    mother_problem = p3.build_pyvrp_problem(bundle, route_proxy_mode="mechanism_ev")
    mother_stop = p3.MultipleCriteria(
        [p3.NoImprovement(int(caps["K_M"])), p3.MaxRuntime(caps["CAP_M"])]
    )
    mother_epoch = p3._run_epoch(
        bundle, mother_problem, common.solution, seed=seed,
        stop=mother_stop, warm_elites=(),
    )
    mother_completion = min((*mother_epoch.elite_completions, common), key=lambda item: item.objective)
    best_completion = mother_completion
    global_best = float(mother_completion.objective)
    trace = [{"elapsed_seconds": 0.0, "cost": float(common.objective), "source": "common_initial"}]
    state = [float(common.objective)]
    _record(trace, state, float(mother_epoch.elapsed_seconds), float(mother_completion.objective), "mechanism_ev_mother_epoch_end")
    view_epochs = {"mechanism_ev": mother_epoch}
    elites = mother_epoch.elite_skeletons
    stall = 0
    epochs_run = 0
    total_iterations = int(mother_epoch.stats.get("hgs_iterations", -1))
    for epoch_index in range(MAX_EPOCHS):
        improved = False
        pool = p3._route_pool_records(bundle, view_epochs)
        sp_solution, _sp_stats = p3._solve_set_partitioning(bundle, pool, time_limit_seconds=SP_TIME)
        if sp_solution is not None:
            sp_completion = p3.complete_china81_route_skeleton(sp_solution, bundle)
            if sp_completion.objective < global_best - EPS:
                global_best = float(sp_completion.objective)
                best_completion = sp_completion
                improved = True
                _record(trace, state, perf_counter() - started, float(global_best), "set_partitioning")
        mode = ROTATION[epoch_index % len(ROTATION)]
        problem = p3.build_pyvrp_problem(bundle, route_proxy_mode=mode)
        epoch_stop = p3.MultipleCriteria(
            [p3.NoImprovement(int(caps["K_E"])), p3.MaxRuntime(caps["CAP_E"])]
        )
        epoch_seed = int(seed) + 1009 * (epoch_index + 1)
        epoch = p3._run_epoch(
            bundle, problem, best_completion.solution, seed=epoch_seed,
            stop=epoch_stop, warm_elites=(best_completion.solution, *elites),
        )
        total_iterations += int(epoch.stats.get("hgs_iterations", -1))
        epoch_best = min(epoch.elite_completions, key=lambda item: item.objective)
        if epoch_best.objective < global_best - EPS:
            global_best = float(epoch_best.objective)
            best_completion = epoch_best
            improved = True
            _record(trace, state, perf_counter() - started, float(global_best), f"{mode}_continuation_epoch_end")
        view_epochs[mode] = epoch
        elites = epoch.elite_skeletons
        epochs_run += 1
        stall = 0 if improved else stall + 1
        if stall >= STALL_EPOCHS:
            break
    objective, breakdown, _violations = p3.exact_china81_score(best_completion.solution, bundle)
    return float(objective), perf_counter() - started, trace, best_completion.solution, breakdown, epochs_run, total_iterations


def _run_unit(args: tuple[str, int, str]) -> dict[str, Any]:
    instance_id, seed, arm = args
    row: dict[str, Any] = {
        "instance_id": instance_id, "n": p3._tier_of(instance_id), "seed": seed,
        "arm": arm, "status": "ERROR", "cost": None, "cpu_seconds": None,
        "violation_count": None, "violations": "", "epochs_run": None,
        "hgs_iterations": None, "trajectory_file": "", "witness_file": "",
        "error_type": "", "error": "",
        "_trajectory": [], "_witness": None,
    }
    try:
        bundle = p3.load_china81_bundle(ROOT, instance_id)
        if arm == "MV-HGS-SP":
            objective, cpu, trace, solution, breakdown, epochs, iterations = _full_arm(bundle, instance_id, seed)
        else:
            objective, cpu, trace, solution, breakdown, iterations = _single_arm(bundle, instance_id, seed, arm)
            epochs = 1
        _objective, _breakdown, violations = p3.exact_china81_score(solution, bundle)
        row.update(
            {
                "status": "OK" if not violations else "INFEASIBLE",
                "cost": float(objective), "cpu_seconds": float(cpu),
                "violation_count": len(violations),
                "violations": json.dumps([str(item) for item in violations], ensure_ascii=False),
                "epochs_run": int(epochs), "hgs_iterations": int(iterations),
                "_trajectory": trace,
                "_witness": _solution_payload(solution, objective, breakdown),
            }
        )
        if violations:
            row["error_type"] = "EXACT_SCORE_VIOLATION"
            row["error"] = "completion/exact scoring returned violations"
    except Exception as exc:
        row.update({"error_type": type(exc).__name__, "error": str(exc)})
    return row


def _existing_ok(raw_path: Path) -> set[tuple[str, int, str]]:
    if not raw_path.exists():
        return set()
    rows = list(csv.DictReader(raw_path.open(encoding="utf-8")))
    keys: set[tuple[str, int, str]] = set()
    for row in rows:
        key = (row["instance_id"], int(row["seed"]), row["arm"])
        if key in keys:
            raise RuntimeError(f"existing S3 raw cannot be resumed safely: {key}")
        if row["status"] != "OK" and not _is_registered_infeasible(row):
            raise RuntimeError(f"existing S3 raw has unregistered non-OK row: {key}")
        keys.add(key)
    return keys


def _append_raw(path: Path, row: dict[str, Any], first: bool) -> None:
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_FIELDS)
        if first:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in RAW_FIELDS})
        handle.flush()


def _artifact_paths() -> list[Path]:
    paths: list[Path] = [
        P3_RUNNER, P3_RAW, S2_RAW, S2_DECISION_V1, S2_DECISION_V2,
        OUT / "task_card.md", OUT / "run_s3_representative.py",
        OUT / "representative_registration.json", OUT / "raw_runs.csv",
        OUT / "metadata.json", OUT / "decision.json", OUT / "report.md",
    ]
    for folder in (OUT / "trajectories", OUT / "witnesses"):
        if folder.exists():
            paths.extend(path for path in folder.rglob("*") if path.is_file())
    return [
        path for path in paths
        if path.exists()
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    ]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "trajectories").mkdir(exist_ok=True)
    (OUT / "witnesses").mkdir(exist_ok=True)
    if not S2_DECISION.exists():
        raise SystemExit(f"missing S2 decision: {S2_DECISION}")
    s2 = json.loads(S2_DECISION.read_text(encoding="utf-8"))
    if s2.get("decision") not in S2_ALLOWED_DECISIONS:
        _write_json(OUT / "decision.json", {
            "schema_version": "resetp.e2-final-campaign.s3-representative.v1",
            "decision": "HALT_S3_S2_NOT_PASS",
            "reason": f"S2 v2 decision is {s2.get('decision')!r}",
        })
        return 2
    registration = _registration()
    instance_id = registration["selected_instance_id"]
    if instance_id not in p3._instance_list():
        raise SystemExit(f"registered representative is not a China81 instance: {instance_id}")
    raw_path = OUT / "raw_runs.csv"
    done = _existing_ok(raw_path)
    tasks = [
        (instance_id, seed, arm)
        for seed in SEEDS for arm in ARMS
        if (instance_id, seed, arm) not in done
    ]
    print(f"[S3] representative={instance_id}; {len(done)} complete; {len(tasks)} remaining", flush=True)
    first = not raw_path.exists()
    if tasks:
        with mp.Pool(processes=WORKERS) as pool:
            for row in pool.imap_unordered(_run_unit, tasks):
                if row["_trajectory"]:
                    trajectory_file = f"trajectories/{row['arm']}_seed{row['seed']}.json"
                    (OUT / trajectory_file).write_text(
                        json.dumps({
                            "instance_id": row["instance_id"], "seed": row["seed"],
                            "arm": row["arm"], "points": row["_trajectory"],
                            "cost_definition": "exact_china81_score objective",
                            "time_definition": "elapsed wall seconds measured by the runner",
                            "resolution": "common initial and exact archive/epoch boundary observations",
                        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                    )
                    row["trajectory_file"] = trajectory_file
                if row["_witness"] is not None:
                    witness_file = f"witnesses/{row['arm']}_seed{row['seed']}.json"
                    (OUT / witness_file).write_text(
                        json.dumps({
                            "instance_id": row["instance_id"], "seed": row["seed"],
                            "arm": row["arm"], "route_proxy_mode": row["arm"],
                            **row["_witness"],
                        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                    )
                    row["witness_file"] = witness_file
                _append_raw(raw_path, row, first)
                first = False
                print(
                    f"[S3] seed={row['seed']} arm={row['arm']} status={row['status']} cost={row['cost']}",
                    flush=True,
                )
    rows = list(csv.DictReader(raw_path.open(encoding="utf-8"))) if raw_path.exists() else []
    expected = len(SEEDS) * len(ARMS)
    keys = [(row["instance_id"], int(row["seed"]), row["arm"]) for row in rows]
    non_ok = [row for row in rows if row["status"] != "OK"]
    violation_rows = [row for row in rows if int(row["violation_count"] or 0) != 0]
    failed_rows = [
        row for row in rows
        if row["status"] != "OK" or int(row["violation_count"] or 0) != 0
    ]
    registered_rows = [row for row in failed_rows if _is_registered_infeasible(row)]
    unregistered_rows = [row for row in failed_rows if not _is_registered_infeasible(row)]
    failure_count_by_arm = {
        arm: sum(
            1 for row in failed_rows
            if row["arm"] == arm
        )
        for arm in ARMS
    }
    failure_rate_by_arm = {
        arm: failure_count_by_arm[arm] / len(SEEDS)
        for arm in ARMS
    }
    rate_exceeded_arms = [
        arm for arm in ARMS
        if failure_rate_by_arm[arm] > SINGLE_ARM_FAILURE_RATE_LIMIT
    ]
    duplicates = len(keys) - len(set(keys))
    if len(rows) != expected or duplicates:
        verdict = "HALT_S3_INCOMPLETE_OR_DUPLICATE_RAW"
        reason = f"expected {expected} unique rows, observed {len(rows)}, duplicates {duplicates}"
    elif unregistered_rows:
        verdict = "HALT_S3_UNREGISTERED_INFEASIBLE_OR_ERROR"
        reason = f"unregistered failed rows={len(unregistered_rows)}; registered rows={len(registered_rows)}"
    elif rate_exceeded_arms:
        verdict = "HALT_S3_REGISTERED_INFEASIBLE_RATE_EXCEEDED"
        reason = (
            f"registered failed rows={len(registered_rows)}; failure rate exceeds "
            f"{SINGLE_ARM_FAILURE_RATE_LIMIT:.1%} for arms={rate_exceeded_arms}"
        )
    elif failed_rows:
        verdict = "PASS_S3_REPRESENTATIVE"
        reason = (
            f"40 four-arm rows complete with {len(registered_rows)} registered "
            "infeasible row(s); all single-arm failure rates are within 5%"
        )
    else:
        verdict = "PASS_S3_REPRESENTATIVE"
        reason = "40 four-arm exact-feasible rows complete"
    decision = {
        "schema_version": "resetp.e2-final-campaign.s3-representative.v1",
        "decision": verdict, "reason": reason,
        "representative_instance_id": instance_id,
        "expected_rows": expected, "observed_rows": len(rows),
        "duplicate_row_count": duplicates, "non_ok_rows": len(non_ok),
        "violation_rows": len(violation_rows),
        "registered_exception_id": REGISTERED_EXCEPTION_ID,
        "registered_exception_applied": bool(registered_rows),
        "registered_infeasible_rows": [
            {
                "instance_id": row["instance_id"], "seed": int(row["seed"]),
                "arm": row["arm"], "status": row["status"],
                "error_type": row.get("error_type", ""), "error": row.get("error", ""),
            }
            for row in registered_rows
        ],
        "failure_count_by_arm": failure_count_by_arm,
        "failure_rate_by_arm": failure_rate_by_arm,
        "single_arm_failure_rate_limit": SINGLE_ARM_FAILURE_RATE_LIMIT,
        "rate_exceeded_arms": rate_exceeded_arms,
        "arms": list(ARMS), "seeds": list(SEEDS),
        "registration_result_blind": registration.get("result_blind", False),
        "claim_boundary": "S3 supplies representative descriptive values and exact-incumbent trajectory evidence; it does not establish equal-compute superiority.",
    }
    _write_json(OUT / "decision.json", decision)
    summary: dict[str, dict[str, float]] = {}
    for arm in ARMS:
        values = [float(row["cost"]) for row in rows if row["arm"] == arm and row["status"] == "OK"]
        summary[arm] = {
            "min": min(values) if values else float("nan"),
            "avg": sum(values) / len(values) if values else float("nan"),
            "max": max(values) if values else float("nan"),
        }
    metadata = {
        "schema_version": "resetp.e2-final-campaign.s3-representative-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": " ".join([sys.executable, *sys.argv]),
        "git_head": _git_head(), "branch": "codex/reporting-pipeline",
        "python": sys.version, "python_executable": sys.executable,
        "platform": platform.platform(), "numpy_version": __import__("numpy").__version__,
        "pyvrp_version": getattr(__import__("pyvrp"), "__version__", "unknown"),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", "UNSET"),
        "workers": WORKERS, "seeds": list(SEEDS), "arms": list(ARMS),
        "tier_caps": {str(key): value for key, value in p3.TIER_CAPS.items()},
        "max_epochs": MAX_EPOCHS, "stall_epochs": STALL_EPOCHS, "sp_time_seconds": SP_TIME,
        "trajectory_resolution": "common initial plus exact archive/epoch-boundary incumbent observations",
        "runner_reused": str(P3_RUNNER.relative_to(ROOT)),
        "s2_decision_sha256": _sha256(S2_DECISION),
        "s2_decision_v1_sha256": _sha256(S2_DECISION_V1),
        "s2_decision_v2_sha256": _sha256(S2_DECISION_V2),
        "s2_registered_exception_id": REGISTERED_EXCEPTION_ID,
        "s2_raw_sha256": _sha256(S2_RAW),
        "p3_raw_sha256": _sha256(P3_RAW), "protected_file_sha256": _protected_hashes(),
        "integrity_flags": [],
        "summary": summary,
    }
    _write_json(OUT / "metadata.json", metadata)
    report_lines = [
        "# S3 Representative four-arm batch", "",
        f"Decision: `{verdict}`.", f"Representative: `{instance_id}`.",
        f"Rows: {len(rows)}/{expected}; non-OK: {len(non_ok)}; violation rows: {len(violation_rows)}.",
        f"Failure rates by arm: {json.dumps(failure_rate_by_arm, ensure_ascii=False, sort_keys=True)}; limit={SINGLE_ARM_FAILURE_RATE_LIMIT:.1%}.",
        "", "Arm summaries (cost):",
    ]
    for arm in ARMS:
        item = summary[arm]
        report_lines.append(f"- `{arm}` min={item['min']:.6f}, avg={item['avg']:.6f}, max={item['max']:.6f}")
    if registered_rows:
        report_lines.extend(["", f"Registered exception `{REGISTERED_EXCEPTION_ID}` rows:"])
        report_lines.extend(
            f"- `{row['instance_id']}`, seed {row['seed']}, `{row['arm']}`: {row.get('error', '')}"
            for row in registered_rows
        )
        report_lines.append(
            "These rows remain in raw_runs.csv; they are not filtered or rerun. "
            "The registered exception is admissible only while every single-arm failure rate is at most 5%."
        )
    report_lines.extend([
        "", "The representative was registered from input-only features before this batch. Trajectories record exact-cost incumbent observations at available epoch boundaries; they do not expose PyVRP proxy costs as if they were exact costs.",
    ])
    (OUT / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    hash_paths = _artifact_paths() + [OUT / "metadata.json", OUT / "decision.json", OUT / "report.md"]
    _write_json(OUT / "artifact_hashes.json", {
        "schema_version": "resetp.artifact-hashes.v1", "algorithm": "sha256",
        "appledouble_excluded": True,
        "files": {
            str(path.relative_to(ROOT)): _sha256(path)
            for path in hash_paths if path.exists() and not path.name.startswith("._")
        },
    })
    _write_json(OUT / "done.json", {
        "decision": verdict, "raw_rows": len(rows),
        "artifact_hashes": "artifact_hashes.json",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    print(f"[S3] {verdict}", flush=True)
    return 0 if verdict.startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
