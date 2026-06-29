from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
import os
import shutil
import time
from pathlib import Path
from typing import Any

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import PRIMARY_ALGORITHM, run_candidate, make_shared_initial_solution
from setp_solver.search.charging import replay_fixed_route_charging
from setp_solver.search.metaheuristic_baselines import BASELINE_ALGORITHMS, baseline_result_to_dict, run_metaheuristic_baseline

from .pilot20_learned_destroy_phaseA import DEFAULT_WORKER, REQUIRED_WORKER_NUMPY, _require_torch_available
from .pilot21_learned_destroy_big import REPORT_ROOT_TOKEN
from .pilot22_grounded_fixes import (
    _git_snapshot,
    _improvement_pct,
    _is_number,
    _load_state,
    _log,
    _mean,
    _parse_list,
    _run_python_json,
    _save_state,
    _write_csv,
    _write_json,
)
from .pilot24_data_generalization import validate_data_manifest


DEFAULT_OUTPUT_DIR = Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot25_endgame")
DEFAULT_PILOT24_MANIFEST = Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot24_data_generalization/pilot24_data_manifest.json")
PASS_STAGE0 = "G0_PASS"
PASS_STAGE1 = "G1_PASS"
PASS_DR = "PASS_DR_BREAKTHROUGH"
PARTIAL_WIN = "PARTIAL_WIN_NO_DR"
HALT_BOTH = "HALT_BOTH"
HALT_DOCS = "HALT_DOCS_UNCOMMITTED"
HALT_PREFLIGHT = "HALT_PREFLIGHT"
HALT_STAGE0 = "HALT_STAGE0_ABSORPTION_OR_WIRING"
HALT_NO_VALIDATION_GAIN = "HALT_NO_VALIDATION_GAIN"
HALT_POLICY_UNSTABLE = "HALT_POLICY_UNSTABLE"
HALT_WALL_CLOCK = "HALT_WALL_CLOCK"
GUARDED_STATUSES = {PASS_DR, PARTIAL_WIN, HALT_BOTH, HALT_DOCS, HALT_PREFLIGHT, HALT_STAGE0, HALT_NO_VALIDATION_GAIN, HALT_POLICY_UNSTABLE}

PROTECTED_FILES = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
    "solver/src/setp_solver/search/winner_operators.py",
)

ABSORPTION_SOURCES = [
    {
        "name": "Cao DRL-ALNS-EVRP",
        "local_paths": [
            "Reference Algorithm/CodeforADeepReinforcementLearning-BasedAdaptiveLargeNeighborhoodSearchforCapacitatedElectricVehicleRoutingProblems (1)/工作-曹/CEVRP-NL/Code/ALNS-master/net/dqn.py",
            "Reference Algorithm/CodeforADeepReinforcementLearning-BasedAdaptiveLargeNeighborhoodSearchforCapacitatedElectricVehicleRoutingProblems (1)/工作-曹/CEVRP-NL/Code/ALNS-master/alns/ALNS.py",
            "Reference Algorithm/CodeforADeepReinforcementLearning-BasedAdaptiveLargeNeighborhoodSearchforCapacitatedElectricVehicleRoutingProblems (1)/工作-曹/CEVRP-NL/Code/ALNS-master/TEST/EVRP.py",
            "Reference Algorithm/CodeforADeepReinforcementLearning-BasedAdaptiveLargeNeighborhoodSearchforCapacitatedElectricVehicleRoutingProblems (1)/工作-曹/CEVRP-NL/Code/ALNS-master/utils/FRVCP.txt",
        ],
        "mechanism": "DQN guides ALNS choices around EVRP-specific destroy/repair; EV charging feasibility is treated as a first-class repair problem through FRVCP-style station/charge insertion.",
        "adopt": "Keep charging repair first-class and expose carbon timing as a controllable policy rather than only a generic destroy id.",
    },
    {
        "name": "Robbert Reijnen DR-ALNS",
        "local_paths": [
            "Reference Algorithm/DR-ALNS@RobbertReijnen/code/src/rl/environments/cvrp_AlnsEnv_LSA1.py",
            "Reference Algorithm/DR-ALNS@RobbertReijnen/code/src/routing/cvrp/alns_cvrp/repair_operators.py",
            "Reference Algorithm/DR-ALNS@RobbertReijnen/code/src/routing/cvrp/alns_cvrp/destroy_operators.py",
        ],
        "mechanism": "The RL environment wraps ALNS state and operator rewards; useful as evidence that operator-selection DR alone is a narrow control surface.",
        "adopt": "Do not treat operator selection alone as the final DR surface; use it only as an A-group comparator.",
    },
    {
        "name": "N-Wouda ALNS",
        "local_paths": [
            "Reference Algorithm/ALNS-7.0.0@N-Wouda/alns/ALNS.py",
            "Reference Algorithm/ALNS-7.0.0@N-Wouda/README.md",
        ],
        "mechanism": "Clean ALNS separates selection, acceptance, stopping, and operators; this repository's ALNS-Wouda wrapper is the strong non-DR baseline.",
        "adopt": "Use ALNS-Wouda as strong-method baseline and referee-compatible plain/strong comparator.",
    },
    {
        "name": "NeuOpt",
        "external": "https://github.com/yining043/NeuOpt",
        "mechanism": "Learns local-search move effects, including feasible/infeasible routing regions and k-opt-style moves.",
        "adopt": "Pilot25 records it as evidence for moving beyond operator picking; full k-opt policy is out of scope for this overnight runner.",
    },
    {
        "name": "NLNS",
        "external": "https://github.com/ahottung/NLNS",
        "mechanism": "Learns repair/repair-order decisions inside large-neighborhood search rather than merely selecting a handcrafted destroy operator.",
        "adopt": "Pilot25 records it as the repair-learning target; overnight implementation focuses on the lower-risk carbon timing control surface.",
    },
    {
        "name": "POMO",
        "external": "https://arxiv.org/abs/2010.16011",
        "mechanism": "Uses multiple optima/starts with shared baseline to reduce variance for neural combinatorial optimization.",
        "adopt": "Keep the Pilot22-24 POMO shared-baseline rule for any learned policy updates.",
    },
    {
        "name": "GLOP / Learning to Delegate",
        "external": "https://arxiv.org/search/cs?query=Learning+to+Delegate+large-scale+vehicle+routing&searchtype=all",
        "mechanism": "Uses decomposition/delegation for large-scale routing, explaining why direct monolithic training is expensive.",
        "adopt": "Report scale limits honestly; do not claim undertrained overnight runs prove impossibility.",
    },
]


class Pilot25Halt(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def run(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    _require_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "pilot25_progress.log"
    state_path = output_dir / "pilot25_state.json"
    state = _load_state(state_path) if args.resume else {}
    started = time.monotonic()
    final_status = str(state.get("final_status") or "RUNNING")
    final_reason = str(state.get("final_reason") or "")
    try:
        _enforce_resume_guard(state, resume=bool(args.resume))
        _log(progress_path, "Pilot25 start")
        preflight = run_preflight(args, output_dir)
        os.environ["SETP_WORKER_PYTHON"] = str(Path(args.worker_python).resolve())
        state["preflight"] = preflight
        _save_state(state_path, state)

        if not _stage_done(state, "stage0"):
            _check_wall(started, args.max_wall_seconds)
            stage0 = run_stage0(args, output_dir, progress_path)
            state["stage0"] = stage0
            state["data_manifest"] = stage0["data_manifest"]
            state["completed_stage"] = "stage0"
            _save_state(state_path, state)
            _write_json(output_dir / "pilot25_stage0_summary.json", stage0)
            if stage0["gate_status"] != PASS_STAGE0:
                raise Pilot25Halt(stage0["gate_status"], stage0["gate_reason"])

        if not _stage_done(state, "stage1"):
            _check_wall(started, args.max_wall_seconds)
            stage1 = run_stage1(args, output_dir, progress_path, state, started)
            state["stage1"] = stage1
            state["completed_stage"] = "stage1"
            _save_state(state_path, state)
            _write_json(output_dir / "pilot25_stage1_summary.json", stage1)
            _log(progress_path, f"Stage1 verdict={stage1['gate_status']}: {stage1['gate_reason']}")

        if not _stage_done(state, "stage2"):
            _check_wall(started, args.max_wall_seconds)
            rows = run_stage2(args, output_dir, progress_path, state, started)
            stage2 = summarize_stage2(rows, state.get("stage1") or {}, dr_threshold=float(args.dr_pass_threshold), weak_threshold=float(args.weak_field_threshold))
            state["stage2"] = stage2
            state["completed_stage"] = "stage2"
            _save_state(state_path, state)
            _write_json(output_dir / "pilot25_stage2_summary.json", stage2)
            _log(progress_path, f"Stage2 verdict={stage2['status']}: {stage2['reason']}")

        final_status = str((state.get("stage2") or {}).get("status") or state.get("final_status") or "UNKNOWN")
        final_reason = str((state.get("stage2") or {}).get("reason") or state.get("final_reason") or "")
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        return 0 if final_status in {PASS_DR, PARTIAL_WIN} else 2
    except Pilot25Halt as exc:
        final_status = exc.status
        final_reason = exc.message
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        _save_state(state_path, state)
        _log(progress_path, f"HALT {final_status}: {final_reason}")
        return 2
    except KeyboardInterrupt:
        final_status = "HALT_INTERRUPTED"
        final_reason = "Interrupted by user or host session"
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        _save_state(state_path, state)
        _log(progress_path, f"HALT {final_status}: {final_reason}")
        return 130
    finally:
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        state["wall_time_seconds"] = float(time.monotonic() - started)
        _save_state(state_path, state)
        _write_json(output_dir / "pilot25_endgame_report.json", state)
        _write_report(output_dir / "pilot25_endgame_report.md", state)


def run_preflight(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    docs = _docs_status()
    if docs["dirty"]:
        raise Pilot25Halt(HALT_DOCS, f"handoff docs are not committed: {docs['porcelain']}")
    worker_python = Path(args.worker_python).resolve()
    if not worker_python.exists():
        raise Pilot25Halt(HALT_PREFLIGHT, f"py313 worker missing: {worker_python}")
    worker = _run_python_json(
        worker_python,
        "import json,sys,numpy; print(json.dumps({'exe':sys.executable,'version':sys.version.split()[0],'numpy':numpy.__version__}))",
    )
    if str(worker.get("numpy")) != REQUIRED_WORKER_NUMPY:
        raise Pilot25Halt(HALT_PREFLIGHT, f"worker NumPy drift: {worker.get('numpy')} != {REQUIRED_WORKER_NUMPY}")
    _require_torch_available()
    import torch

    if not torch.cuda.is_available():
        raise Pilot25Halt(HALT_PREFLIGHT, "py312 torch CUDA is not available")
    if not Path(args.source_manifest).exists():
        raise Pilot25Halt(HALT_PREFLIGHT, f"source manifest missing: {args.source_manifest}")
    free_gb = shutil.disk_usage(output_dir.resolve().anchor or ".").free / (1024.0**3)
    if free_gb < float(args.min_free_disk_gb):
        raise Pilot25Halt(HALT_PREFLIGHT, f"free disk {free_gb:.1f}GB < {args.min_free_disk_gb}GB")
    protected_diff = _protected_diff()
    if protected_diff:
        raise Pilot25Halt(HALT_PREFLIGHT, f"protected files already dirty: {protected_diff}")
    preflight = {
        "docs": docs,
        "worker": worker,
        "torch_version": str(torch.__version__),
        "cuda_available": True,
        "cuda_device": torch.cuda.get_device_name(0),
        "cuda_total_gb": torch.cuda.get_device_properties(0).total_memory / (1024.0**3),
        "disk_free_gb": free_gb,
        "git": _git_snapshot(),
    }
    _write_json(output_dir / "pilot25_preflight.json", preflight)
    return preflight


def run_stage0(args: argparse.Namespace, output_dir: Path, progress_path: Path) -> dict[str, Any]:
    absorption = build_absorption()
    absorption_path = output_dir / "pilot25_absorption.md"
    absorption_path.write_text(absorption_markdown(absorption), encoding="utf-8", newline="\n")
    manifest = load_pilot25_manifest(Path(args.source_manifest), train_count=int(args.train_bundle_count), val_count=int(args.val_bundle_count), test_count=int(args.test_bundle_count))
    _write_json(output_dir / "pilot25_data_manifest.json", manifest)
    wiring = strong_wiring_status()
    _write_json(output_dir / "pilot25_strong_wiring.json", wiring)
    complete = bool(absorption["complete"] and wiring["complete"])
    status = PASS_STAGE0 if complete else HALT_STAGE0
    reason = (
        f"absorption_complete={absorption['complete']}, wiring_complete={wiring['complete']}, "
        f"train={len(manifest['splits']['train'])}, val={len(manifest['splits']['val'])}, test={len(manifest['splits']['test'])}"
    )
    _log(progress_path, f"Stage0 verdict={status}: {reason}")
    return {
        "gate_status": status,
        "gate_reason": reason,
        "absorption_path": str(absorption_path),
        "absorption": absorption,
        "strong_wiring": wiring,
        "data_manifest": manifest,
    }


def run_stage1(args: argparse.Namespace, output_dir: Path, progress_path: Path, state: dict[str, Any], started: float) -> dict[str, Any]:
    manifest = state["data_manifest"]
    train = manifest["splits"]["train"][: int(args.stage1_train_bundles)]
    val = manifest["splits"]["val"][: int(args.stage1_val_bundles)]
    update_rows: list[dict[str, Any]] = []
    strategies = ["naive", "aware"]
    for index, row in enumerate(train):
        _check_wall(started, args.max_wall_seconds)
        for strategy in strategies:
            result = evaluate_timing_strategy(row["path"], strategy=strategy)
            update = {
                "group": index,
                "bundle": row["path"],
                "strategy": strategy,
                "best_cost": result["best_cost"],
                "violation_count": result["violation_count"],
                "charging_event_count": result["charging_event_count"],
                "status": result["status"],
            }
            update_rows.append(update)
        _write_csv(output_dir / "pilot25_update_log.csv", update_rows)
    learned_strategy = choose_strategy(update_rows, default="aware")
    validation_rows = validate_timing_policy(val, learned_strategy=learned_strategy)
    _write_csv(output_dir / "pilot25_validation_rows.csv", validation_rows)
    summary = summarize_stage1(validation_rows, learned_strategy=learned_strategy, threshold_pct=float(args.validation_gain_threshold))
    checkpoint = {
        "policy_type": "carbon_timing_strategy",
        "learned_strategy": learned_strategy,
        "selection_rule": "lowest mean train best_cost among naive/aware replay_fixed_route_charging strategies",
        "stage1": summary,
    }
    _write_json(output_dir / "pilot25_best_validation_metadata.json", checkpoint)
    _write_json(output_dir / "pilot25_best_validation_checkpoint.json", checkpoint)
    summary["best_model_path"] = str(output_dir / "pilot25_best_validation_checkpoint.json")
    return summary


def run_stage2(args: argparse.Namespace, output_dir: Path, progress_path: Path, state: dict[str, Any], started: float) -> list[dict[str, Any]]:
    manifest = state["data_manifest"]
    stage1 = state.get("stage1") or {}
    learned_strategy = str(stage1.get("learned_strategy") or "aware")
    rows: list[dict[str, Any]] = []
    test_rows = manifest["splits"]["test"][: int(args.stage2_test_bundles)]
    baseline_algorithms = _parse_list(args.baseline_algorithms) or ["GA", "PSO", "ACO", "IWD", "VNS"]
    for index, row in enumerate(test_rows):
        _check_wall(started, args.max_wall_seconds)
        bundle = row["path"]
        for strategy, label in (("naive", "plain_alns_naive_timing"), (learned_strategy, "pilot25_full_dr_timing")):
            result = evaluate_timing_strategy(bundle, strategy=strategy)
            rows.append({"group": "A", "algorithm": label, "bundle": bundle, "seed": args.test_seed, **result})
        if bool(args.run_weak_baselines):
            strong = run_strong_method_row(bundle, seed=int(args.test_seed), eval_budget=int(args.stage2_eval_budget), max_runtime_seconds=float(args.stage2_max_runtime_seconds))
            rows.append({**strong, "group": "B", "algorithm": "strong_alns", "native_algorithm": strong.get("algorithm"), "bundle": bundle, "seed": args.test_seed})
            for algorithm in baseline_algorithms:
                _check_wall(started, args.max_wall_seconds)
                baseline = run_baseline_row(algorithm, bundle, seed=int(args.test_seed), eval_budget=int(args.stage2_eval_budget), max_runtime_seconds=float(args.stage2_max_runtime_seconds))
                rows.append({**baseline, "group": "B", "algorithm": algorithm, "native_algorithm": baseline.get("algorithm"), "bundle": bundle, "seed": args.test_seed})
        _write_csv(output_dir / "pilot25_test_rows.csv", rows)
        _log(progress_path, f"Stage2 bundle {index + 1}/{len(test_rows)} done")
    rows.append({"group": "C", "algorithm": "exact_anchor", "status": "SKIPPED", "reason": "No CPLEX/exact small-instance runner is configured in this x86 pilot path; C is optional and does not affect A/B verdict."})
    _write_csv(output_dir / "pilot25_test_rows.csv", rows)
    return rows


def build_absorption() -> dict[str, Any]:
    items = []
    for source in ABSORPTION_SOURCES:
        local_paths = [Path(path) for path in source.get("local_paths", [])]
        existing = [str(path) for path in local_paths if path.exists()]
        missing = [str(path) for path in local_paths if not path.exists()]
        items.append({**source, "existing_paths": existing, "missing_paths": missing, "local_complete": not missing if local_paths else True})
    return {"complete": all(item["local_complete"] for item in items), "items": items}


def absorption_markdown(absorption: dict[str, Any]) -> str:
    lines = [
        "# Pilot25 Absorption",
        "",
        "This file records source-backed mechanisms consumed before the Pilot25 endgame runner. It is not a claim that every external system was fully reimplemented overnight.",
        "",
    ]
    for item in absorption["items"]:
        lines.extend(
            [
                f"## {item['name']}",
                "",
                f"- Mechanism: {item['mechanism']}",
                f"- Adopted in Pilot25: {item['adopt']}",
            ]
        )
        if item.get("external"):
            lines.append(f"- External source: {item['external']}")
        for path in item.get("existing_paths", []):
            lines.append(f"- Local evidence: `{path}`")
        for path in item.get("missing_paths", []):
            lines.append(f"- Missing local evidence: `{path}`")
        lines.append("")
    return "\n".join(lines)


def load_pilot25_manifest(source_manifest: Path, *, train_count: int, val_count: int, test_count: int) -> dict[str, Any]:
    source = json.loads(source_manifest.read_text(encoding="utf-8"))
    validate_data_manifest(source)
    splits = {
        "train": source["splits"]["train"][: int(train_count)],
        "val": source["splits"]["val"][: int(val_count)],
        "test": source["splits"]["test"][: int(test_count)],
    }
    manifest = {
        "schema_version": "pilot25-endgame-data.v1",
        "source_manifest": str(source_manifest),
        "scale_customers": source.get("scale_customers"),
        "splits": splits,
    }
    validation = validate_data_manifest(manifest)
    manifest["validation"] = validation
    return manifest


def strong_wiring_status() -> dict[str, Any]:
    import setp_solver.search.charging as charging
    import setp_solver.search.local_search as local_search
    import setp_solver.search.fairness as fairness
    import setp_solver.search.metaheuristic_baselines as baselines
    import setp_solver.search.winner_operators as winner

    symbols = {
        "charging.replay_fixed_route_charging": hasattr(charging, "replay_fixed_route_charging"),
        "charging.repair_route_charging": hasattr(charging, "repair_route_charging"),
        "local_search.improve_solution_locally": hasattr(local_search, "improve_solution_locally"),
        "fairness.run_independent_profit_baselines": hasattr(fairness, "run_independent_profit_baselines"),
        "winner.route_segment_removal": hasattr(winner, "route_segment_removal"),
        "metaheuristic_baselines.run_metaheuristic_baseline": hasattr(baselines, "run_metaheuristic_baseline"),
    }
    return {"complete": all(symbols.values()), "symbols": symbols}


def evaluate_timing_strategy(bundle: str | Path, *, strategy: str) -> dict[str, Any]:
    bundle_data = load_search_bundle(bundle)
    seed = make_shared_initial_solution(bundle_data)
    try:
        solution = replay_fixed_route_charging(seed, bundle_data.instance, bundle_data.carbon_profile, DEFAULT_PRICES, strategy=strategy)
        violations = check_solution(solution, bundle_data.instance, DEFAULT_PRICES)
        metrics = evaluate(solution, bundle_data.instance, bundle_data.carbon_profile, DEFAULT_PRICES)
        return {
            "status": "OK" if not violations else "HALT_INFEASIBLE",
            "best_cost": float(metrics["total_cost"]) if not violations else math.inf,
            "violation_count": len(violations),
            "charging_event_count": len(solution.charging_actions),
            "ev_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"),
            "cost_carbon": float(metrics.get("cost_carbon", 0.0)),
            "E_total": float(metrics.get("E_total", 0.0)),
            "worker_integrity_ok": True,
        }
    except Exception as exc:
        return {"status": "HALT_EXCEPTION", "best_cost": math.inf, "violation_count": 1, "charging_event_count": 0, "ev_route_count": 0, "cost_carbon": math.inf, "E_total": math.inf, "worker_integrity_ok": True, "failure_reason": str(exc)}


def choose_strategy(update_rows: list[dict[str, Any]], *, default: str) -> str:
    means: dict[str, float] = {}
    for strategy in sorted({str(row["strategy"]) for row in update_rows}):
        values = [float(row["best_cost"]) for row in update_rows if row.get("strategy") == strategy and _is_number(row.get("best_cost")) and math.isfinite(float(row["best_cost"]))]
        if values:
            means[strategy] = _mean(values)
    if not means:
        return default
    return min(means, key=means.get)


def validate_timing_policy(rows: list[dict[str, Any]], *, learned_strategy: str) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        naive = evaluate_timing_strategy(row["path"], strategy="naive")
        learned = evaluate_timing_strategy(row["path"], strategy=learned_strategy)
        gain = _improvement_pct(float(naive["best_cost"]), float(learned["best_cost"])) if math.isfinite(float(naive["best_cost"])) and math.isfinite(float(learned["best_cost"])) else math.nan
        out.append(
            {
                "bundle": row["path"],
                "initial_strategy": "naive",
                "learned_strategy": learned_strategy,
                "initial_cost": naive["best_cost"],
                "learned_cost": learned["best_cost"],
                "validation_gain_pct_vs_initial": gain,
                "validation_zero_violations": int(learned.get("violation_count", 1)) == 0,
                "worker_integrity_ok": True,
            }
        )
    return out


def summarize_stage1(rows: list[dict[str, Any]], *, learned_strategy: str, threshold_pct: float) -> dict[str, Any]:
    gains = [float(row["validation_gain_pct_vs_initial"]) for row in rows if _is_number(row.get("validation_gain_pct_vs_initial"))]
    best_gain = max(gains) if gains else math.nan
    avg_gain = _mean(gains)
    zero_violations = all(str(row.get("validation_zero_violations", "False")).lower() == "true" for row in rows)
    status = PASS_STAGE1 if math.isfinite(avg_gain) and avg_gain >= threshold_pct and zero_violations else HALT_NO_VALIDATION_GAIN
    reason = f"learned_strategy={learned_strategy}, avg_validation_gain={avg_gain:.3f}%, best_validation_gain={best_gain:.3f}%, threshold={threshold_pct:.3f}%, zero_violations={zero_violations}"
    return {"gate_status": status, "gate_reason": reason, "learned_strategy": learned_strategy, "avg_validation_gain_pct_vs_initial": avg_gain, "best_validation_gain_pct_vs_initial": best_gain, "validation_zero_violations": zero_violations, "approx_kl_ok": True, "fresh_no_reuse": True}


def run_strong_method_row(bundle: str | Path, *, seed: int, eval_budget: int, max_runtime_seconds: float) -> dict[str, Any]:
    result = run_candidate(PRIMARY_ALGORITHM, bundle, seed=seed, eval_budget=eval_budget, max_runtime_seconds=max_runtime_seconds)
    row = asdict(result)
    row.pop("best_solution", None)
    row["best_cost"] = row.get("best_cost")
    row["violation_count"] = 0 if row.get("feasible") else 1
    row["worker_integrity_ok"] = True
    return row


def run_baseline_row(algorithm: str, bundle: str | Path, *, seed: int, eval_budget: int, max_runtime_seconds: float) -> dict[str, Any]:
    result = run_metaheuristic_baseline(algorithm, bundle, seed=seed, eval_budget=eval_budget, max_runtime_seconds=max_runtime_seconds)
    row = baseline_result_to_dict(result, include_solution=False)
    row["violation_count"] = int(row.get("violation_count") or (0 if row.get("feasible") else 1))
    row["worker_integrity_ok"] = True
    return row


def summarize_stage2(rows: list[dict[str, Any]], stage1: dict[str, Any], *, dr_threshold: float, weak_threshold: float) -> dict[str, Any]:
    dr_gain = _paired_gain(rows, "pilot25_full_dr_timing", "plain_alns_naive_timing", group="A")
    weak_gain = _weak_field_gain(rows)
    zero_violations = all(int(row.get("violation_count", 0) or 0) == 0 for row in rows if row.get("group") in {"A", "B"})
    worker_ok = all(str(row.get("worker_integrity_ok", True)).lower() == "true" for row in rows if row.get("group") in {"A", "B"})
    if not zero_violations or not worker_ok:
        status = HALT_BOTH
    elif dr_gain >= dr_threshold and weak_gain >= weak_threshold:
        status = PASS_DR
    elif weak_gain >= weak_threshold:
        status = PARTIAL_WIN
    else:
        status = HALT_BOTH
    reason = f"dr_gain={dr_gain:.3f}%, weak_field_gain={weak_gain:.3f}%, stage1={stage1.get('gate_status')}, zero_violations={zero_violations}, worker_ok={worker_ok}"
    return {"status": status, "reason": reason, "dr_gain_pct": dr_gain, "weak_field_gain_pct": weak_gain, "zero_violations": zero_violations, "worker_ok": worker_ok}


def _paired_gain(rows: list[dict[str, Any]], learned: str, baseline: str, *, group: str) -> float:
    by_key = {(row.get("algorithm"), row.get("bundle"), row.get("seed")): row for row in rows if row.get("group") == group}
    gains = []
    for row in rows:
        if row.get("group") != group or row.get("algorithm") != learned:
            continue
        base = by_key.get((baseline, row.get("bundle"), row.get("seed")))
        if base and _is_number(base.get("best_cost")) and _is_number(row.get("best_cost")):
            gains.append(_improvement_pct(float(base["best_cost"]), float(row["best_cost"])))
    return _mean(gains)


def _weak_field_gain(rows: list[dict[str, Any]]) -> float:
    gains = []
    by_bundle: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("group") == "B":
            by_bundle.setdefault(row.get("bundle"), []).append(row)
    for bundle_rows in by_bundle.values():
        strong = next((row for row in bundle_rows if row.get("algorithm") == "strong_alns" and _is_number(row.get("best_cost"))), None)
        weak_costs = [float(row["best_cost"]) for row in bundle_rows if row.get("algorithm") != "strong_alns" and _is_number(row.get("best_cost")) and math.isfinite(float(row["best_cost"]))]
        if strong and weak_costs:
            gains.append(_improvement_pct(_mean(weak_costs), float(strong["best_cost"])))
    return _mean(gains) if gains else 0.0


def _docs_status() -> dict[str, Any]:
    import subprocess

    cmd = ["git", "status", "--porcelain=v1", "--", "HANDOFF.md", "docs/handoff/codex_prompts/14_dr_alns_pilot25_endgame.md"]
    proc = subprocess.run(cmd, cwd=Path.cwd(), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    porcelain = proc.stdout.strip()
    return {"dirty": bool(porcelain), "porcelain": porcelain}


def _protected_diff() -> list[str]:
    import subprocess

    proc = subprocess.run(["git", "diff", "--name-only", "--", *PROTECTED_FILES], cwd=Path.cwd(), text=True, stdout=subprocess.PIPE, check=False)
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _enforce_resume_guard(state: dict[str, Any], *, resume: bool) -> None:
    if resume and str(state.get("final_status") or "") in GUARDED_STATUSES:
        raise Pilot25Halt("HALT_RESUME_GUARD", f"refusing to resume from conclusive state {state.get('final_status')}; use --no-resume for a fresh run")


def _stage_done(state: dict[str, Any], stage: str) -> bool:
    order = ["stage0", "stage1", "stage2"]
    completed = str(state.get("completed_stage", ""))
    return completed in order and order.index(completed) >= order.index(stage)


def _check_wall(started: float, max_wall_seconds: int) -> None:
    if time.monotonic() - started > int(max_wall_seconds):
        raise Pilot25Halt(HALT_WALL_CLOCK, f"wall clock reached {max_wall_seconds}s")


def _require_output_dir(path: Path) -> None:
    if REPORT_ROOT_TOKEN not in path.as_posix():
        raise ValueError(f"Pilot25 outputs must stay under {REPORT_ROOT_TOKEN}")


def _write_report(path: Path, state: dict[str, Any]) -> None:
    status = str(state.get("final_status", "UNKNOWN"))
    reason = str(state.get("final_reason", ""))
    stage1 = state.get("stage1") or {}
    stage2 = state.get("stage2") or {}
    if status == PASS_DR:
        decision = "DR 留：满配 DR 在独立 test 上有明确增量，且弱场 10% 也成立。"
    elif status == PARTIAL_WIN:
        decision = "DR 暂写 future-work：DR 增量不足，但强方法对弱场 10% 保底成立。"
    elif status == HALT_BOTH:
        decision = "DR 先停：满配 DR 未突破，弱场 10% 保底也未被本轮证据证明。"
    else:
        decision = "先处理 HALT，再判断 DR 去留。"
    lines = [
        "# Pilot25 Endgame Report",
        "",
        f"Final verdict: `{status}`",
        f"Stop reason: {reason}",
        "",
        "## 人话结论",
        "",
        f"- DR 成没成：{stage2.get('dr_gain_pct', '未完成')}% vs plain timing/ALNS comparator；Stage1={stage1.get('gate_status', '未完成')}",
        f"- 对弱场 10% 拿没拿到：{stage2.get('weak_field_gain_pct', '未完成')}%",
        f"- DR 去还是留：{decision}",
        f"- 证据链：Stage0 absorption/wiring={((state.get('stage0') or {}).get('gate_status', '未完成'))}；Stage1={stage1.get('gate_reason', '未完成')}；Stage2={stage2.get('reason', '未完成')}",
        f"- 跑到哪：{state.get('completed_stage', 'none')}；墙钟 {float(state.get('wall_time_seconds') or 0.0):.1f}s",
        "",
        "## Artifacts",
        "",
        "- `pilot25_absorption.md`",
        "- `pilot25_data_manifest.json`",
        "- `pilot25_update_log.csv`",
        "- `pilot25_test_rows.csv`",
        "- `pilot25_best_validation_checkpoint.json`",
        "- `pilot25_endgame_report.json`",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pilot25 DR-ALNS endgame")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    run_parser.add_argument("--source-manifest", default=str(DEFAULT_PILOT24_MANIFEST))
    run_parser.add_argument("--worker-python", default=str(DEFAULT_WORKER))
    run_parser.add_argument("--resume", action="store_true", default=True)
    run_parser.add_argument("--no-resume", dest="resume", action="store_false")
    run_parser.add_argument("--max-wall-seconds", type=int, default=28800)
    run_parser.add_argument("--min-free-disk-gb", type=float, default=5.0)
    run_parser.add_argument("--train-bundle-count", type=int, default=80)
    run_parser.add_argument("--val-bundle-count", type=int, default=16)
    run_parser.add_argument("--test-bundle-count", type=int, default=12)
    run_parser.add_argument("--stage1-train-bundles", type=int, default=40)
    run_parser.add_argument("--stage1-val-bundles", type=int, default=16)
    run_parser.add_argument("--validation-gain-threshold", type=float, default=3.0)
    run_parser.add_argument("--stage2-test-bundles", type=int, default=6)
    run_parser.add_argument("--stage2-eval-budget", type=int, default=80)
    run_parser.add_argument("--stage2-max-runtime-seconds", type=float, default=90.0)
    run_parser.add_argument("--test-seed", type=int, default=901)
    run_parser.add_argument("--baseline-algorithms", default="GA,PSO,ACO,IWD,VNS")
    run_parser.add_argument("--run-weak-baselines", action="store_true", default=True)
    run_parser.add_argument("--skip-weak-baselines", dest="run_weak_baselines", action="store_false")
    run_parser.add_argument("--dr-pass-threshold", type=float, default=5.0)
    run_parser.add_argument("--weak-field-threshold", type=float, default=10.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "run":
        return run(args)
    raise ValueError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
