from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from setp_instance_lab.build_curriculum_instances import (
    DEFAULT_TEMPLATE_MANIFEST,
    CurriculumSpec,
    _load_template_config,
    build_config_for_spec,
    build_curriculum_manifest,
    validate_generated_bundle,
)
from setp_instance_lab.generator import generate_scenario
from setp_instance_lab.io import write_scenario_bundle

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.charging import replay_fixed_route_charging
from setp_solver.search.construction import build_initial_solution
from setp_solver.search.evaluation import EvaluationContext, model_cost
from setp_solver.search.fleet import FleetLimits
from setp_solver.search.winner_operators import WinnerKernelConfig, run_winner_kernel

from .pilot20_learned_destroy_phaseA import (
    DEFAULT_WORKER,
    REQUIRED_WORKER_NUMPY,
    _episode_row,
    _parse_int_list,
    _require_torch_available,
    run_operator_select_episode,
    run_random_episode,
)
from .pilot21_learned_destroy_big import (
    run_best_of_k_episode,
    run_worst_removal_episode,
)
from .pilot22_grounded_fixes import _run_algorithm_row, flatten_pomo_shared_baseline
from .pilot23_stabilize import (
    linear_annealed_lr,
    ppo_update_learned_stable,
)
from .learned_destroy_policy import (
    load_learned_destroy_policy,
    make_learned_destroy_actor_critic,
    save_learned_destroy_policy,
)


DEFAULT_OUTPUT_DIR = Path("solver/reports/dr_alns_ppo_v3/final_track22")
DEFAULT_GENERATED_ROOT = Path("models/data_bundle/generated_instances")
DEFAULT_PPO_PYTHON = Path(r"C:\Users\zlxshu\.venvs\resetp-ppo-cu124-py312\Scripts\python.exe")

DESTROY_LEVERAGE_CLEAN = "DESTROY_LEVERAGE_CLEAN"
LEVERAGE_MARGINAL = "LEVERAGE_MARGINAL"
NO_DESTROY_LEVERAGE_CLEAN = "NO_DESTROY_LEVERAGE_CLEAN"

PASS_LEARNED_DESTROY_CLEAN = "PASS_LEARNED_DESTROY_CLEAN"
WEAK_LEARNED_DESTROY_CLEAN = "WEAK_LEARNED_DESTROY_CLEAN"
HALT_LEARNED_DESTROY_CLEAN = "HALT_LEARNED_DESTROY_CLEAN"
SKIP_LEARNED_DESTROY_NO_LEVERAGE = "SKIP_LEARNED_DESTROY_NO_LEVERAGE"

CARBON_TIMING_LEVERAGE = "CARBON_TIMING_LEVERAGE"
CARBON_TIMING_WEAK = "CARBON_TIMING_WEAK"
NO_CARBON_TIMING_LEVERAGE = "NO_CARBON_TIMING_LEVERAGE"
HALT_WORKER_INTEGRITY = "HALT_WORKER_INTEGRITY"


TRACK22_SPECS = {
    "stage2_probe": (
        CurriculumSpec("E-UK25_11", 25, 2211),
        CurriculumSpec("E-UK25_12", 25, 2212),
        CurriculumSpec("E-UK25_13", 25, 2213),
        CurriculumSpec("E-UK50_11", 50, 2251),
        CurriculumSpec("E-UK50_12", 50, 2252),
    ),
    "stage3_train": (
        CurriculumSpec("E-UK25_14", 25, 2314),
        CurriculumSpec("E-UK25_15", 25, 2315),
        CurriculumSpec("E-UK25_16", 25, 2316),
        CurriculumSpec("E-UK50_13", 50, 2353),
        CurriculumSpec("E-UK50_14", 50, 2354),
    ),
    "stage3_val": (
        CurriculumSpec("E-UK25_17", 25, 2417),
        CurriculumSpec("E-UK50_15", 50, 2455),
    ),
    "stage3_test": (
        CurriculumSpec("E-UK25_18", 25, 2518),
        CurriculumSpec("E-UK50_16", 50, 2556),
        CurriculumSpec("E-UK50_17", 50, 2557),
    ),
}


class Track22Halt(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = str(status)
        self.message = str(message)


def run(args: argparse.Namespace) -> int:
    started = time.monotonic()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "track22_progress.log"
    state_path = output_dir / "track22_state.json"
    state = _load_json(state_path) if args.resume and state_path.exists() else {}
    try:
        _log(progress_path, "Track22 run start")
        state["preflight"] = run_preflight(args, output_dir)
        _write_json(output_dir / "track22_preflight.json", state["preflight"])
        _write_json(state_path, state)

        if not _stage_done(state, "stage2"):
            bundle_manifest = ensure_track22_bundles(args, output_dir)
            state["bundle_manifest"] = bundle_manifest
            _write_json(output_dir / "track22_bundle_manifest.json", bundle_manifest)
            rows = run_stage2_destroy_leverage(args, output_dir, progress_path, bundle_manifest)
            stage2 = summarize_stage2_destroy(rows)
            state["stage2"] = stage2
            state["completed_stage"] = "stage2"
            _write_json(output_dir / "stage2_destroy_leverage_summary.json", stage2)
            write_stage2_report(output_dir / "track22_destroy_leverage_report.md", stage2, bundle_manifest)
            _write_json(state_path, state)
            _log(progress_path, f"Stage2 verdict={stage2['status']}: {stage2['reason']}")

        if not _stage_done(state, "stage3"):
            stage2_status = str((state.get("stage2") or {}).get("status", ""))
            if stage2_status not in {DESTROY_LEVERAGE_CLEAN, LEVERAGE_MARGINAL}:
                stage3 = {
                    "status": SKIP_LEARNED_DESTROY_NO_LEVERAGE,
                    "reason": f"Stage2 status={stage2_status}; learned-destroy training skipped by Track22 gate.",
                    "trained": False,
                }
                _write_csv(output_dir / "track22_learned_destroy_test_rows.csv", [{"algorithm": "SKIPPED_STAGE3", **stage3}])
            else:
                stage3 = run_stage3_learned_destroy(args, output_dir, progress_path, state)
            state["stage3"] = stage3
            state["completed_stage"] = "stage3"
            _write_json(output_dir / "stage3_learned_destroy_summary.json", stage3)
            write_stage3_report(output_dir / "track22_learned_destroy_report.md", stage3)
            _write_json(state_path, state)
            _log(progress_path, f"Stage3 verdict={stage3['status']}: {stage3['reason']}")

        if not _stage_done(state, "stage4"):
            stage4 = run_stage4_carbon_timing(args, output_dir, progress_path, state)
            state["stage4"] = stage4
            state["completed_stage"] = "stage4"
            _write_json(output_dir / "stage4_carbon_timing_summary.json", stage4)
            write_stage4_report(output_dir / "track22_carbon_timing_report.md", stage4)
            _write_json(state_path, state)
            _log(progress_path, f"Stage4 verdict={stage4['status']}: {stage4['reason']}")

        state["final_status"] = final_status_from_state(state)
        state["final_reason"] = final_reason_from_state(state)
        state["wall_time_seconds"] = float(time.monotonic() - started)
        _write_json(state_path, state)
        _write_json(output_dir / "track22_final_report.json", state)
        write_final_report(output_dir / "final_report.md", state)
        Path("final_report.md").write_text((output_dir / "final_report.md").read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        return 0
    except Track22Halt as exc:
        state["final_status"] = exc.status
        state["final_reason"] = exc.message
        state["wall_time_seconds"] = float(time.monotonic() - started)
        _write_json(state_path, state)
        _write_json(output_dir / "track22_final_report.json", state)
        write_final_report(output_dir / "final_report.md", state)
        Path("final_report.md").write_text((output_dir / "final_report.md").read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        _log(progress_path, f"HALT {exc.status}: {exc.message}")
        return 2


def run_preflight(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    worker_python = Path(args.worker_python).resolve()
    if not worker_python.exists():
        raise Track22Halt(HALT_WORKER_INTEGRITY, f"py313 worker missing: {worker_python}")
    worker = _run_python_json(
        worker_python,
        "import json,sys,numpy; print(json.dumps({'exe':sys.executable,'version':sys.version.split()[0],'numpy':numpy.__version__}))",
    )
    if str(worker.get("numpy")) != REQUIRED_WORKER_NUMPY:
        raise Track22Halt(HALT_WORKER_INTEGRITY, f"worker NumPy drift: {worker.get('numpy')} != {REQUIRED_WORKER_NUMPY}")
    os.environ["SETP_WORKER_PYTHON"] = str(worker_python)
    disk = shutil.disk_usage(output_dir.resolve().anchor or ".")
    return {
        "worker": worker,
        "required_worker_numpy": REQUIRED_WORKER_NUMPY,
        "output_dir": str(output_dir),
        "disk_free_gb": float(disk.free) / (1024.0**3),
        "git": _git_snapshot(),
    }


def ensure_track22_bundles(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    root = Path(".").resolve()
    template = _load_template_config((root / DEFAULT_TEMPLATE_MANIFEST).resolve())
    rows_by_role: dict[str, list[dict[str, Any]]] = {}
    for role, specs in TRACK22_SPECS.items():
        rows: list[dict[str, Any]] = []
        for spec in specs:
            output = root / DEFAULT_GENERATED_ROOT / spec.scenario_id
            if output.exists() and not bool(args.regenerate_bundles):
                manifest = validate_generated_bundle(output, expected_n=spec.n_customers)
            else:
                if output.exists():
                    _remove_existing_output(output, (root / DEFAULT_GENERATED_ROOT).resolve())
                scenario_config, manifest_config = build_config_for_spec(root, template, spec)
                scenario = generate_scenario(scenario_config)
                write_scenario_bundle(scenario, output, config=manifest_config)
                manifest = validate_generated_bundle(output, expected_n=spec.n_customers)
            rows.append(
                {
                    "role": role,
                    "name": spec.scenario_id,
                    "path": _manifest_bundle_path(root, output),
                    "n_customers": int(manifest["validation"]["customer_count"]),
                    "validation_passed": bool(manifest["validation"]["passed"]),
                    "has_carbon_profile": bool((output / "carbon_profile.csv").is_file()),
                    "seed": int(spec.seed),
                    "base_id": spec.base_id,
                }
            )
        role_manifest = build_curriculum_manifest(rows)
        _write_json(output_dir / f"track22_bundle_manifest_{role}.json", role_manifest)
        rows_by_role[role] = rows
    flat = [row for rows in rows_by_role.values() for row in rows]
    return {
        "schema_version": "track22-bundle-manifest.v1",
        "roles": rows_by_role,
        "all": flat,
        "non_overlap_ok": len({row["path"] for row in flat}) == len(flat),
    }


def run_stage2_destroy_leverage(
    args: argparse.Namespace,
    output_dir: Path,
    progress_path: Path,
    bundle_manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    rows_path = output_dir / "track22_destroy_leverage_rows.csv"
    rows = _read_csv(rows_path) if args.resume else []
    completed = {
        (row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0))
        for row in rows
    }
    bundles = [str(row["path"]) for row in bundle_manifest["roles"]["stage2_probe"]]
    seeds = _parse_int_list(args.stage2_seeds)
    for bundle in bundles:
        for seed in seeds:
            for algorithm in ("operator_select", "worst_removal_fixed", "best_of_k_destroy"):
                key = (algorithm, bundle, int(seed))
                if key in completed:
                    continue
                _log(progress_path, f"Stage2 run {algorithm} bundle={bundle} seed={seed}")
                if algorithm == "operator_select":
                    row = run_operator_select_episode(bundle, seed=int(seed), eval_budget=int(args.stage2_eval_budget))
                elif algorithm == "worst_removal_fixed":
                    row = run_worst_removal_episode(bundle, seed=int(seed), eval_budget=int(args.stage2_eval_budget))
                else:
                    row = run_best_of_k_episode(
                        bundle,
                        seed=int(seed),
                        eval_budget=int(args.stage2_eval_budget),
                        candidate_k=int(args.stage2_best_of_k),
                    )
                row["algorithm"] = algorithm
                row["track"] = "track22"
                row["evidence_role"] = "DESTROY_LEVERAGE_GATE"
                rows.append(row)
                _write_csv(rows_path, rows)
    return rows


def summarize_stage2_destroy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_scale: dict[str, dict[str, list[float]]] = {}
    by_bundle: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        algo = str(row.get("algorithm", ""))
        bundle = str(row.get("bundle", ""))
        scale = str(row.get("scale") or _scale_label(bundle))
        best = _float(row.get("best_obj"))
        by_scale.setdefault(scale, {}).setdefault(algo, []).append(best)
        by_bundle.setdefault(bundle, {}).setdefault(algo, []).append(best)
    scale_rows = [_headroom_row(scale, algos) for scale, algos in sorted(by_scale.items())]
    bundle_rows = [_headroom_row(bundle, algos) for bundle, algos in sorted(by_bundle.items())]
    overall = _headroom_row("overall", _merge_algo_values(by_scale.values()))
    max_scale_headroom = max((_finite_or(row["best_of_k_headroom_pct"], -math.inf) for row in scale_rows), default=math.nan)
    worker_ok = all(_truthy(row.get("worker_integrity_ok")) for row in rows)
    zero_violations = _all_zero(rows, "violation_count")
    if not worker_ok:
        status = HALT_WORKER_INTEGRITY
        reason = "At least one Stage2 row did not use the py313/NumPy 2.3.5 worker."
    elif not zero_violations:
        status = "HALT_STAGE2_VIOLATION"
        reason = "At least one Stage2 row has nonzero violation_count."
    elif math.isfinite(max_scale_headroom) and max_scale_headroom >= 3.0:
        status = DESTROY_LEVERAGE_CLEAN
        reason = f"Clean best-of-k destroy leverage >=3% on at least one scale; max_scale={max_scale_headroom:.3f}%."
    elif math.isfinite(max_scale_headroom) and max_scale_headroom >= 1.0:
        status = LEVERAGE_MARGINAL
        reason = f"Clean best-of-k destroy leverage is marginal; max_scale={max_scale_headroom:.3f}%."
    else:
        status = NO_DESTROY_LEVERAGE_CLEAN
        reason = f"Clean best-of-k destroy leverage <1%; max_scale={max_scale_headroom:.3f}%."
    return {
        "status": status,
        "reason": reason,
        "row_count": len(rows),
        "worker_integrity_ok": worker_ok,
        "zero_violations": zero_violations,
        "overall": overall,
        "scale_rows": scale_rows,
        "bundle_rows": bundle_rows,
        "max_scale_best_of_k_headroom_pct": max_scale_headroom,
        "gate_rule": "DESTROY_LEVERAGE_CLEAN if any scale >=3%; LEVERAGE_MARGINAL if any scale is 1-3%; NO_DESTROY_LEVERAGE_CLEAN if all scales <1%.",
    }


def run_stage3_learned_destroy(
    args: argparse.Namespace,
    output_dir: Path,
    progress_path: Path,
    state: dict[str, Any],
) -> dict[str, Any]:
    _require_torch_available()
    import torch

    bundle_manifest = state["bundle_manifest"]
    train_bundles = [str(row["path"]) for row in bundle_manifest["roles"]["stage3_train"]]
    validation_bundles = [str(row["path"]) for row in bundle_manifest["roles"]["stage3_val"]]
    test_bundles = [str(row["path"]) for row in bundle_manifest["roles"]["stage3_test"]]
    overlap = sorted((set(train_bundles) | set(validation_bundles)) & set(test_bundles))
    if overlap:
        raise Track22Halt("HALT_STAGE3_OVERLAP", f"train/validation/test overlap: {overlap}")

    model = make_learned_destroy_actor_critic(seed=int(args.stage3_seed), hidden_size=int(args.stage3_hidden_size))
    optimizer = torch.optim.Adam(model.parameters(), lr=float(args.stage3_learning_rate))
    model_path = output_dir / "track22_learned_destroy_final_model.pt"
    best_model_path = output_dir / "track22_learned_destroy_best_validation_model.pt"
    update_rows: list[dict[str, Any]] = _read_csv(output_dir / "track22_learned_destroy_update_log.csv") if args.resume else []
    episode_rows: list[dict[str, Any]] = _read_csv(output_dir / "track22_learned_destroy_training_rows.csv") if args.resume else []
    validation_rows: list[dict[str, Any]] = _read_csv(output_dir / "track22_learned_destroy_validation_rows.csv") if args.resume else []

    train_started = time.monotonic()
    pending_groups: list[list[Any]] = []
    best_validation_gain = -math.inf
    best_validation_summary: dict[str, Any] | None = None
    total_groups = int(math.ceil(int(args.stage3_train_episodes) / max(1, int(args.stage3_pomo_rollouts))))
    initial_validation = eval_learned_vs_operator(
        model,
        validation_bundles,
        _parse_int_list(args.stage3_validation_seeds),
        eval_budget=int(args.stage3_validation_eval_budget),
        max_customers=int(args.stage3_max_customers),
        rows_path=output_dir / "track22_learned_destroy_validation_detail_rows.csv",
        tag="initial",
    )
    validation_rows.append(initial_validation)
    _write_csv(output_dir / "track22_learned_destroy_validation_rows.csv", validation_rows)
    best_validation_gain = float(initial_validation["avg_improvement_pct_vs_operator_select"])
    best_validation_summary = dict(initial_validation)
    save_learned_destroy_policy(best_model_path, model, metadata={"reason": "initial_validation", **best_validation_summary})

    for group_index in range(total_groups):
        if time.monotonic() - train_started >= float(args.stage3_max_train_seconds):
            break
        bundle = train_bundles[int(group_index) % len(train_bundles)]
        group: list[Any] = []
        for rollout_idx in range(int(args.stage3_pomo_rollouts)):
            episode_index = group_index * int(args.stage3_pomo_rollouts) + rollout_idx
            if episode_index >= int(args.stage3_train_episodes):
                break
            episode = run_learned_episode_for_train(
                model,
                bundle,
                seed=int(args.stage3_seed) + int(episode_index),
                eval_budget=int(args.stage3_train_eval_budget),
                max_customers=int(args.stage3_max_customers),
            )
            group.append(episode)
            row = _episode_row(episode)
            row["pomo_group"] = int(group_index)
            row["pomo_rollout"] = int(rollout_idx)
            episode_rows.append(row)
            _write_csv(output_dir / "track22_learned_destroy_training_rows.csv", episode_rows)
        if group:
            pending_groups.append(group)
        if len(pending_groups) >= int(args.stage3_rollout_min_groups):
            update_index = len(update_rows)
            lr = linear_annealed_lr(
                initial_lr=float(args.stage3_learning_rate),
                final_lr=float(args.stage3_final_learning_rate),
                update_index=update_index,
                total_updates=max(1, total_groups // max(1, int(args.stage3_rollout_min_groups))),
            )
            for param_group in optimizer.param_groups:
                param_group["lr"] = lr
            batch = flatten_pomo_shared_baseline(pending_groups)
            metrics = ppo_update_learned_stable(
                model,
                optimizer,
                batch,
                epochs=int(args.stage3_ppo_epochs),
                minibatch_size=int(args.stage3_minibatch_size),
                clip_range=float(args.stage3_clip_range),
                value_coef=float(args.stage3_value_coef),
                entropy_coef=float(args.stage3_entropy_coef),
                max_grad_norm=float(args.stage3_max_grad_norm),
                target_kl=float(args.stage3_target_kl),
            )
            update_row = {
                "update_index": int(update_index),
                "group_index": int(group_index),
                "learning_rate": float(lr),
                **metrics,
            }
            update_rows.append(update_row)
            _write_csv(output_dir / "track22_learned_destroy_update_log.csv", update_rows)
            if (update_index + 1) % int(args.stage3_validation_every_updates) == 0:
                summary = eval_learned_vs_operator(
                    model,
                    validation_bundles,
                    _parse_int_list(args.stage3_validation_seeds),
                    eval_budget=int(args.stage3_validation_eval_budget),
                    max_customers=int(args.stage3_max_customers),
                    rows_path=output_dir / "track22_learned_destroy_validation_detail_rows.csv",
                    tag=f"update_{update_index + 1:04d}",
                )
                summary["update_index"] = int(update_index)
                validation_rows.append(summary)
                _write_csv(output_dir / "track22_learned_destroy_validation_rows.csv", validation_rows)
                gain = float(summary["avg_improvement_pct_vs_operator_select"])
                if gain > best_validation_gain:
                    best_validation_gain = gain
                    best_validation_summary = dict(summary)
                    save_learned_destroy_policy(best_model_path, model, metadata={"reason": "best_validation", **best_validation_summary})
            pending_groups = []

    save_learned_destroy_policy(model_path, model, metadata={"train_episodes_requested": int(args.stage3_train_episodes)})
    if best_model_path.exists():
        eval_model = load_learned_destroy_policy(best_model_path)
    else:
        eval_model = model
    test_rows = run_learned_test_rows(
        eval_model,
        test_bundles,
        _parse_int_list(args.stage3_test_seeds),
        eval_budget=int(args.stage3_test_eval_budget),
        max_customers=int(args.stage3_max_customers),
        rows_path=output_dir / "track22_learned_destroy_test_rows.csv",
    )
    test_summary = summarize_learned_rows(test_rows)
    status = learned_status(test_summary)
    return {
        "status": status,
        "reason": learned_reason(test_summary),
        "trained": True,
        "train_bundles": train_bundles,
        "validation_bundles": validation_bundles,
        "test_bundles": test_bundles,
        "train_episode_count": len(episode_rows),
        "update_count": len(update_rows),
        "validation_count": len(validation_rows),
        "best_validation_gain_pct_vs_operator_select": best_validation_gain,
        "best_validation_summary": best_validation_summary or {},
        "model_path": str(model_path),
        "best_model_path": str(best_model_path),
        "test_summary": test_summary,
        "wall_time_seconds": float(time.monotonic() - train_started),
    }


def run_learned_episode_for_train(model: Any, bundle: str, *, seed: int, eval_budget: int, max_customers: int) -> Any:
    from .pilot20_learned_destroy_phaseA import run_learned_episode

    return run_learned_episode(
        model,
        bundle,
        seed=int(seed),
        eval_budget=int(eval_budget),
        max_customers=int(max_customers),
        deterministic=False,
    )


def eval_learned_vs_operator(
    model: Any,
    bundles: list[str],
    seeds: list[int],
    *,
    eval_budget: int,
    max_customers: int,
    rows_path: Path,
    tag: str,
) -> dict[str, Any]:
    rows = _read_csv(rows_path)
    completed = {
        (row.get("tag"), row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0))
        for row in rows
    }
    for bundle in bundles:
        for seed in seeds:
            for algorithm in ("learned_destroy", "operator_select"):
                key = (tag, algorithm, bundle, int(seed))
                if key in completed:
                    continue
                row = _run_algorithm_row(
                    algorithm,
                    model,
                    bundle,
                    seed=int(seed),
                    eval_budget=int(eval_budget),
                    max_customers=int(max_customers),
                )
                row["tag"] = tag
                row["evidence_role"] = "VALIDATION"
                rows.append(row)
                _write_csv(rows_path, rows)
    tagged = [row for row in rows if row.get("tag") == tag]
    summary = summarize_learned_rows(tagged)
    return {
        "tag": tag,
        "validation_mean_obj": summary["learned_mean_obj"],
        "operator_mean_obj": summary["operator_mean_obj"],
        "avg_improvement_pct_vs_operator_select": summary["avg_vs_operator"],
        "min_scale_improvement_pct_vs_operator_select": summary["min_scale_vs_operator"],
        "zero_violations": summary["zero_violations"],
        "worker_integrity_ok": summary["worker_ok"],
        "row_count": len(tagged),
    }


def run_learned_test_rows(
    model: Any,
    bundles: list[str],
    seeds: list[int],
    *,
    eval_budget: int,
    max_customers: int,
    rows_path: Path,
) -> list[dict[str, Any]]:
    rows = _read_csv(rows_path)
    completed = {
        (row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0))
        for row in rows
    }
    for bundle in bundles:
        for seed in seeds:
            for algorithm in ("learned_destroy", "operator_select", "random_operator", "worst_removal_fixed"):
                key = (algorithm, bundle, int(seed))
                if key in completed:
                    continue
                row = _run_algorithm_row(
                    algorithm,
                    model,
                    bundle,
                    seed=int(seed),
                    eval_budget=int(eval_budget),
                    max_customers=int(max_customers),
                )
                row["evidence_role"] = "INDEPENDENT_TEST"
                rows.append(row)
                _write_csv(rows_path, rows)
    return rows


def summarize_learned_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_key = {(row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0)): row for row in rows}
    learned = [row for row in rows if row.get("algorithm") == "learned_destroy"]
    improvements: list[float] = []
    random_improvements: list[float] = []
    worst_improvements: list[float] = []
    by_scale: dict[str, list[float]] = {}
    learned_objs: list[float] = []
    operator_objs: list[float] = []
    for row in learned:
        key = (row.get("bundle"), int(row.get("seed") or 0))
        op = by_key.get(("operator_select", *key))
        random_row = by_key.get(("random_operator", *key))
        worst = by_key.get(("worst_removal_fixed", *key))
        learned_obj = _float(row.get("best_obj"))
        learned_objs.append(learned_obj)
        if op:
            op_obj = _float(op.get("best_obj"))
            operator_objs.append(op_obj)
            value = _improvement_pct(op_obj, learned_obj)
            improvements.append(value)
            by_scale.setdefault(str(row.get("scale") or _scale_label(str(row.get("bundle", "")))), []).append(value)
        if random_row:
            random_improvements.append(_improvement_pct(_float(random_row.get("best_obj")), learned_obj))
        if worst:
            worst_improvements.append(_improvement_pct(_float(worst.get("best_obj")), learned_obj))
    return {
        "avg_vs_operator": _mean(improvements),
        "min_scale_vs_operator": min((_mean(values) for values in by_scale.values()), default=math.nan),
        "avg_vs_random": _mean(random_improvements),
        "avg_vs_worst": _mean(worst_improvements),
        "scale_improvement_pct": {scale: _mean(values) for scale, values in sorted(by_scale.items())},
        "zero_violations": _all_zero(learned, "violation_count"),
        "worker_ok": all(_truthy(row.get("worker_integrity_ok")) for row in rows),
        "learned_mean_obj": _mean(learned_objs),
        "operator_mean_obj": _mean(operator_objs),
        "row_count": len(rows),
    }


def learned_status(summary: dict[str, Any]) -> str:
    if not summary["worker_ok"]:
        return HALT_WORKER_INTEGRITY
    if not summary["zero_violations"]:
        return "HALT_STAGE3_VIOLATION"
    if summary["avg_vs_operator"] >= 2.0 and summary["min_scale_vs_operator"] >= 0.0 and summary["avg_vs_random"] > 0.0 and summary["avg_vs_worst"] > 0.0:
        return PASS_LEARNED_DESTROY_CLEAN
    if summary["avg_vs_operator"] >= 0.0 and summary["min_scale_vs_operator"] >= 0.0:
        return WEAK_LEARNED_DESTROY_CLEAN
    return HALT_LEARNED_DESTROY_CLEAN


def learned_reason(summary: dict[str, Any]) -> str:
    return (
        f"avg_vs_operator={summary['avg_vs_operator']:.3f}%, "
        f"min_scale={summary['min_scale_vs_operator']:.3f}%, "
        f"avg_vs_random={summary['avg_vs_random']:.3f}%, "
        f"avg_vs_worst={summary['avg_vs_worst']:.3f}%, "
        f"zero_violations={summary['zero_violations']}, worker_ok={summary['worker_ok']}"
    )


def run_stage4_carbon_timing(
    args: argparse.Namespace,
    output_dir: Path,
    progress_path: Path,
    state: dict[str, Any],
) -> dict[str, Any]:
    manifest = state.get("bundle_manifest") or ensure_track22_bundles(args, output_dir)
    bundles = [str(row["path"]) for row in manifest["roles"]["stage2_probe"][: int(args.stage4_bundle_count)]]
    rows_path = output_dir / "track22_carbon_timing_rows.csv"
    rows = _read_csv(rows_path) if args.resume else []
    completed = {(row.get("bundle"), int(row.get("seed") or 0), row.get("diagnostic_role", "")) for row in rows}
    for bundle in bundles:
        for seed in _parse_int_list(args.stage4_seeds):
            key = (bundle, int(seed), "default_winner_route_replay")
            if key in completed:
                continue
            _log(progress_path, f"Stage4 carbon replay bundle={bundle} seed={seed}")
            row = carbon_replay_row(
                bundle,
                seed=int(seed),
                eval_budget=int(args.stage4_eval_budget),
                max_runtime_seconds=float(args.stage4_max_runtime_seconds),
                diagnostic_role="default_winner_route_replay",
            )
            rows.append(row)
            _write_csv(rows_path, rows)
    summary = summarize_carbon_rows(rows)
    if summary["avg_improvement_pct"] < 0.5:
        diagnostic = run_ev_heavy_diagnostic(args, output_dir, progress_path, manifest)
        if diagnostic:
            rows.append(diagnostic)
            _write_csv(rows_path, rows)
            summary = summarize_carbon_rows(rows)
            summary["ev_heavy_diagnostic"] = diagnostic
    return summary


def carbon_replay_row(
    bundle: str,
    *,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
    diagnostic_role: str,
) -> dict[str, Any]:
    loaded = load_search_bundle(bundle)
    result = run_winner_kernel(
        bundle,
        config=WinnerKernelConfig(seed=int(seed), eval_budget=int(eval_budget), max_runtime_seconds=float(max_runtime_seconds)),
    )
    solution = result["best_solution"]
    return carbon_compare_solution(bundle, loaded, solution, seed=seed, diagnostic_role=diagnostic_role, source="winner_kernel")


def carbon_compare_solution(
    bundle: str,
    loaded: Any,
    solution: Any,
    *,
    seed: int,
    diagnostic_role: str,
    source: str,
) -> dict[str, Any]:
    aware = replay_fixed_route_charging(solution, loaded.instance, loaded.carbon_profile, DEFAULT_PRICES, strategy="aware")
    naive = replay_fixed_route_charging(solution, loaded.instance, loaded.carbon_profile, DEFAULT_PRICES, strategy="naive")
    aware_violations = check_solution(aware, loaded.instance, DEFAULT_PRICES)
    naive_violations = check_solution(naive, loaded.instance, DEFAULT_PRICES)
    aware_context = EvaluationContext(loaded.instance, loaded.carbon_profile)
    naive_context = EvaluationContext(loaded.instance, loaded.carbon_profile)
    aware_cost = model_cost(aware, aware_context)
    naive_cost = model_cost(naive, naive_context)
    aware_metrics = evaluate(aware, loaded.instance, loaded.carbon_profile, DEFAULT_PRICES)
    naive_metrics = evaluate(naive, loaded.instance, loaded.carbon_profile, DEFAULT_PRICES)
    return {
        "bundle": str(bundle),
        "scale": _scale_label(str(bundle)),
        "seed": int(seed),
        "diagnostic_role": diagnostic_role,
        "source": source,
        "route_count": len(solution.routes),
        "ev_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"),
        "aware_charging_actions": len(aware.charging_actions),
        "naive_charging_actions": len(naive.charging_actions),
        "aware_cost": float(aware_cost),
        "naive_cost": float(naive_cost),
        "improvement_pct": _improvement_pct(float(naive_cost), float(aware_cost)),
        "aware_violation_count": len(aware_violations),
        "naive_violation_count": len(naive_violations),
        "aware_charging_carbon_kg": float(aware_metrics.get("E_ev_indirect", 0.0)),
        "naive_charging_carbon_kg": float(naive_metrics.get("E_ev_indirect", 0.0)),
        "aware_cost_carbon": float(aware_metrics.get("cost_carbon", 0.0)),
        "naive_cost_carbon": float(naive_metrics.get("cost_carbon", 0.0)),
    }


def run_ev_heavy_diagnostic(args: argparse.Namespace, output_dir: Path, progress_path: Path, manifest: dict[str, Any]) -> dict[str, Any] | None:
    bundle = str(manifest["roles"]["stage2_probe"][0]["path"])
    try:
        loaded = load_search_bundle(bundle)
        ev_instance = replace(loaded.instance, num_cv=0, num_ev=max(10, len([node for node in loaded.instance.nodes if node.node_type.lower() == "c"])))
        seed_solution = build_initial_solution(
            ev_instance,
            loaded.carbon_profile,
            DEFAULT_PRICES,
            fleet_limits=FleetLimits(cv=0, ev=999, source="track22_ev_heavy_diagnostic"),
            introduce_ev=True,
            require_charging_signal=True,
        )
        synthetic_loaded = replace(loaded, instance=ev_instance)
        row = carbon_compare_solution(
            bundle,
            synthetic_loaded,
            seed_solution,
            seed=int(args.stage4_ev_heavy_seed),
            diagnostic_role="ev_heavy_diagnostic_only",
            source="ev_heavy_initial_solution",
        )
        _log(progress_path, "Stage4 EV-heavy diagnostic succeeded")
        return row
    except Exception as exc:
        _log(progress_path, f"Stage4 EV-heavy diagnostic failed: {type(exc).__name__}: {exc}")
        return {
            "bundle": bundle,
            "scale": _scale_label(bundle),
            "seed": int(args.stage4_ev_heavy_seed),
            "diagnostic_role": "ev_heavy_diagnostic_only",
            "source": "ev_heavy_initial_solution",
            "error": f"{type(exc).__name__}: {exc}",
            "improvement_pct": math.nan,
        }


def summarize_carbon_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gate_rows = [row for row in rows if row.get("diagnostic_role") == "default_winner_route_replay"]
    improvements = [_float(row.get("improvement_pct")) for row in gate_rows if _is_number(row.get("improvement_pct"))]
    zero_violations = _all_zero(gate_rows, "aware_violation_count") and _all_zero(gate_rows, "naive_violation_count")
    avg = _mean(improvements)
    if not zero_violations:
        status = "HALT_CARBON_TIMING_VIOLATION"
        reason = "At least one aware/naive carbon replay row has nonzero violations."
    elif avg >= 2.0:
        status = CARBON_TIMING_LEVERAGE
        reason = f"Carbon-aware timing beats naive replay by {avg:.3f}% on average."
    elif avg >= 0.5:
        status = CARBON_TIMING_WEAK
        reason = f"Carbon-aware timing leverage is weak but nonzero: {avg:.3f}%."
    else:
        status = NO_CARBON_TIMING_LEVERAGE
        reason = f"Default scenario carbon timing leverage <0.5%: {avg:.3f}%."
    return {
        "status": status,
        "reason": reason,
        "avg_improvement_pct": avg,
        "row_count": len(rows),
        "gate_row_count": len(gate_rows),
        "zero_violations": zero_violations,
        "gate_rule": ">=2% passes, 0.5-2% weak, <0.5% no leverage; EV-heavy row is diagnostic only.",
    }


def write_stage2_report(path: Path, summary: dict[str, Any], manifest: dict[str, Any]) -> None:
    lines = [
        "# Track22 Destroy Leverage Clean Probe",
        "",
        f"Verdict: `{summary['status']}`",
        f"Reason: {summary['reason']}",
        "",
        "## Evidence",
        "",
        f"- Rows: {summary['row_count']}",
        f"- Worker integrity: {summary['worker_integrity_ok']}",
        f"- Zero violations: {summary['zero_violations']}",
        f"- Max scale best-of-k headroom: {summary['max_scale_best_of_k_headroom_pct']:.3f}%",
        f"- Fresh bundle non-overlap: {manifest['non_overlap_ok']}",
        "",
        "## Scale Rows",
        "",
    ]
    for row in summary["scale_rows"]:
        lines.append(
            f"- {row['label']}: operator={row['operator_select_mean']:.6f}, "
            f"best_of_k={row['best_of_k_mean']:.6f}, headroom={row['best_of_k_headroom_pct']:.3f}%, "
            f"worst_fixed={row['worst_removal_mean']:.6f}, worst_gain={row['worst_improvement_pct']:.3f}%"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_stage3_report(path: Path, summary: dict[str, Any]) -> None:
    test = summary.get("test_summary") or {}
    lines = [
        "# Track22 Learned-Destroy Clean Report",
        "",
        f"Verdict: `{summary['status']}`",
        f"Reason: {summary['reason']}",
        "",
        "## Evidence",
        "",
        f"- Trained: {summary.get('trained')}",
        f"- Train episodes: {summary.get('train_episode_count', 0)}",
        f"- Updates: {summary.get('update_count', 0)}",
        f"- Best validation gain vs operator-select: {summary.get('best_validation_gain_pct_vs_operator_select')}",
        f"- Test avg vs operator-select: {test.get('avg_vs_operator')}",
        f"- Test min-scale vs operator-select: {test.get('min_scale_vs_operator')}",
        f"- Test zero violations: {test.get('zero_violations')}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_stage4_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Track22 Carbon Timing Leverage Probe",
        "",
        f"Verdict: `{summary['status']}`",
        f"Reason: {summary['reason']}",
        "",
        "## Evidence",
        "",
        f"- Gate rows: {summary['gate_row_count']}",
        f"- Average improvement: {summary['avg_improvement_pct']:.3f}%",
        f"- Zero violations: {summary['zero_violations']}",
        f"- Rule: {summary['gate_rule']}",
    ]
    if summary.get("ev_heavy_diagnostic"):
        lines.extend(["", "## EV-heavy diagnostic", "", json.dumps(summary["ev_heavy_diagnostic"], ensure_ascii=False)])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_final_report(path: Path, state: dict[str, Any]) -> None:
    stage2 = state.get("stage2") or {}
    stage3 = state.get("stage3") or {}
    stage4 = state.get("stage4") or {}
    stage1_path = path.parent / "stage1_instrument_gate.json"
    if not stage1_path.exists():
        stage1_path = DEFAULT_OUTPUT_DIR / "stage1_instrument_gate.json"
    stage1 = _load_json(stage1_path) if stage1_path.exists() else {}
    stage1_row = stage1.get("row") or {}
    lines = [
        "# Track22 Final Report",
        "",
        f"Final verdict: `{state.get('final_status', 'UNKNOWN')}`",
        "",
        "## 人话结论",
        "",
        "Track22 的结果不支持继续把 x86 线的 DR-ALNS 推成主算法候选。不是因为训练不够，而是前置杠杆没有肉：学习型破坏的 best-of-k 探针在干净仪器上没有优势，碳时刻控制在默认场景也几乎没有可吃空间。",
        "",
        "## 证据链",
        "",
        "- Track21 已收口：25c+50c 共 140 行合法比较，判 `MARGIN_REAL_PROVISIONAL_X86`；100c 只保留 1 行 partial，不作公平结论。主方法对健康基线最小平均优势约 5.669%，没有达到“每个基线 >=10%”。",
        f"- Stage1 仪器闸：`{stage1.get('verdict', 'see stage1_instrument_gate.json')}`；100-01 seed901、300 eval、py313+NumPy2.3.5，winner best `{_float(stage1_row.get('best_cost')):.6f}`，warm `{_float(stage1_row.get('warm_start_cost')):.6f}`，unique `{stage1_row.get('unique_solution_count')}`，updates `{stage1_row.get('best_update_count')}`，violations `{stage1_row.get('violation_count')}`。",
        f"- Stage2 学习型破坏杠杆闸：`{stage2.get('status', 'NOT_RUN')}`；rows `{stage2.get('row_count')}`，worker integrity `{stage2.get('worker_integrity_ok')}`，zero violations `{stage2.get('zero_violations')}`，max-scale headroom `{_float(stage2.get('max_scale_best_of_k_headroom_pct')):.3f}%`，overall headroom `{_float((stage2.get('overall') or {}).get('best_of_k_headroom_pct')):.3f}%`。",
        f"- Stage3 训练/测试：`{stage3.get('status', 'NOT_RUN')}`；{stage3.get('reason', '')}",
        f"- Stage4 碳时刻探针：`{stage4.get('status', 'NOT_RUN')}`；默认场景平均 improvement `{_float(stage4.get('avg_improvement_pct')):.3f}%`，gate rows `{stage4.get('gate_row_count')}`，zero violations `{stage4.get('zero_violations')}`。",
        "",
        "## 判定",
        "",
        f"- Learned-destroy: `{stage2.get('status', 'NOT_RUN')}`",
        f"- Clean training/test: `{stage3.get('status', 'NOT_RUN')}`",
        f"- Carbon timing: `{stage4.get('status', 'NOT_RUN')}`",
        f"- Overall: `{state.get('final_status', 'UNKNOWN')}`",
        "",
        "## 主要证据文件",
        "",
        "- `solver/reports/dr_alns_ppo_v3/final_track21_reclaim/final_report.md`",
        "- `stage1_instrument_gate.json`",
        "- `track22_preflight.json`",
        "- `track22_bundle_manifest.json`",
        "- `track22_destroy_leverage_rows.csv`",
        "- `stage2_destroy_leverage_summary.json`",
        "- `track22_learned_destroy_test_rows.csv`",
        "- `track22_carbon_timing_rows.csv`",
        "- `track22_final_report.json`",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def final_status_from_state(state: dict[str, Any]) -> str:
    stage3 = str((state.get("stage3") or {}).get("status", ""))
    stage4 = str((state.get("stage4") or {}).get("status", ""))
    if stage3 == PASS_LEARNED_DESTROY_CLEAN and stage4 == CARBON_TIMING_LEVERAGE:
        return "DR_COMPETITIVE_CANDIDATE"
    if stage3 == PASS_LEARNED_DESTROY_CLEAN:
        return "DR_PARTIAL"
    if stage4 == CARBON_TIMING_LEVERAGE:
        return "DR_PARTIAL"
    if stage3 == WEAK_LEARNED_DESTROY_CLEAN or stage4 == CARBON_TIMING_WEAK:
        return "DR_PARTIAL"
    if stage3 == SKIP_LEARNED_DESTROY_NO_LEVERAGE and stage4 == NO_CARBON_TIMING_LEVERAGE:
        return "DR_CLEAN_NEGATIVE"
    return "TRACK22_COMPLETED_WITH_HALTS"


def final_reason_from_state(state: dict[str, Any]) -> str:
    return (
        f"stage2={((state.get('stage2') or {}).get('status'))}; "
        f"stage3={((state.get('stage3') or {}).get('status'))}; "
        f"stage4={((state.get('stage4') or {}).get('status'))}"
    )


def _headroom_row(label: str, algos: dict[str, list[float]]) -> dict[str, Any]:
    op = _mean(algos.get("operator_select", []))
    worst = _mean(algos.get("worst_removal_fixed", []))
    best = _mean(algos.get("best_of_k_destroy", []))
    return {
        "label": label,
        "operator_select_mean": op,
        "worst_removal_mean": worst,
        "best_of_k_mean": best,
        "best_of_k_headroom_pct": _improvement_pct(op, best) if math.isfinite(op) and math.isfinite(best) else math.nan,
        "worst_improvement_pct": _improvement_pct(op, worst) if math.isfinite(op) and math.isfinite(worst) else math.nan,
    }


def _merge_algo_values(items: Iterable[dict[str, list[float]]]) -> dict[str, list[float]]:
    merged: dict[str, list[float]] = {}
    for item in items:
        for key, values in item.items():
            merged.setdefault(key, []).extend(values)
    return merged


def _stage_done(state: dict[str, Any], stage: str) -> bool:
    order = {"stage2": 2, "stage3": 3, "stage4": 4}
    completed = str(state.get("completed_stage", "") or "")
    return completed in order and order[completed] >= order[stage]


def _git_snapshot() -> dict[str, Any]:
    def git(*parts: str) -> str:
        proc = subprocess.run(["git", *parts], text=True, capture_output=True, check=False, timeout=30)
        return (proc.stdout or proc.stderr).strip()

    return {
        "status_short_branch": git("status", "--short", "--branch"),
        "head": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
    }


def _run_python_json(python: Path, code: str) -> dict[str, Any]:
    env = os.environ.copy()
    root = Path.cwd()
    env["PYTHONPATH"] = os.pathsep.join([str(root / "solver" / "rl"), str(root / "solver" / "src"), str(root / "models" / "src")])
    proc = subprocess.run([str(python), "-c", code], cwd=root, env=env, text=True, capture_output=True, check=False, timeout=30)
    if proc.returncode != 0:
        raise Track22Halt("HALT_PREFLIGHT", proc.stderr.strip() or proc.stdout.strip())
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _manifest_bundle_path(root: Path, output_dir: Path) -> str:
    try:
        return output_dir.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(output_dir.resolve())


def _remove_existing_output(output_dir: Path, output_root: Path) -> None:
    resolved_output = output_dir.resolve()
    resolved_root = output_root.resolve()
    if resolved_output == resolved_root or resolved_root not in resolved_output.parents:
        raise ValueError(f"Refusing to remove output outside generated root: {resolved_output}")
    shutil.rmtree(resolved_output)


def _scale_label(bundle: str) -> str:
    text = str(bundle)
    for marker in ("E-UK25", "E-UK50", "E-UK100", "E-UK150", "E-UK200"):
        if marker in text:
            return marker.replace("E-UK", "") + "c"
    return "unknown"


def _improvement_pct(base: float, candidate: float) -> float:
    return (float(base) - float(candidate)) / max(abs(float(base)), 1.0) * 100.0


def _mean(values: Iterable[float]) -> float:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    return float(sum(finite) / len(finite)) if finite else math.nan


def _finite_or(value: Any, default: float) -> float:
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        return default
    return value_f if math.isfinite(value_f) else default


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _is_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _int_or(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, str) and value.strip() == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _all_zero(rows: Iterable[dict[str, Any]], key: str) -> bool:
    return all(_int_or(row.get(key), 1) == 0 for row in rows)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8", newline="\n")
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{stamp}\t{message}\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Track22 clean DR-ALNS endgame runner")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    run_parser.add_argument("--worker-python", default=str(DEFAULT_WORKER))
    run_parser.add_argument("--resume", action="store_true", default=True)
    run_parser.add_argument("--no-resume", dest="resume", action="store_false")
    run_parser.add_argument("--regenerate-bundles", action="store_true")
    run_parser.add_argument("--stage2-seeds", default="1201,1202,1203")
    run_parser.add_argument("--stage2-eval-budget", type=int, default=80)
    run_parser.add_argument("--stage2-best-of-k", type=int, default=4)
    run_parser.add_argument("--stage3-seed", type=int, default=2601)
    run_parser.add_argument("--stage3-train-episodes", type=int, default=1000)
    run_parser.add_argument("--stage3-train-eval-budget", type=int, default=120)
    run_parser.add_argument("--stage3-validation-eval-budget", type=int, default=120)
    run_parser.add_argument("--stage3-test-eval-budget", type=int, default=180)
    run_parser.add_argument("--stage3-validation-seeds", default="2701")
    run_parser.add_argument("--stage3-test-seeds", default="2801,2802")
    run_parser.add_argument("--stage3-pomo-rollouts", type=int, default=4)
    run_parser.add_argument("--stage3-rollout-min-groups", type=int, default=1)
    run_parser.add_argument("--stage3-validation-every-updates", type=int, default=10)
    run_parser.add_argument("--stage3-max-train-seconds", type=float, default=28800.0)
    run_parser.add_argument("--stage3-max-customers", type=int, default=128)
    run_parser.add_argument("--stage3-hidden-size", type=int, default=128)
    run_parser.add_argument("--stage3-learning-rate", type=float, default=1e-4)
    run_parser.add_argument("--stage3-final-learning-rate", type=float, default=1e-5)
    run_parser.add_argument("--stage3-ppo-epochs", type=int, default=1)
    run_parser.add_argument("--stage3-minibatch-size", type=int, default=64)
    run_parser.add_argument("--stage3-clip-range", type=float, default=0.1)
    run_parser.add_argument("--stage3-target-kl", type=float, default=0.08)
    run_parser.add_argument("--stage3-value-coef", type=float, default=0.5)
    run_parser.add_argument("--stage3-entropy-coef", type=float, default=0.01)
    run_parser.add_argument("--stage3-max-grad-norm", type=float, default=0.5)
    run_parser.add_argument("--stage4-bundle-count", type=int, default=3)
    run_parser.add_argument("--stage4-seeds", default="2901")
    run_parser.add_argument("--stage4-eval-budget", type=int, default=300)
    run_parser.add_argument("--stage4-max-runtime-seconds", type=float, default=120.0)
    run_parser.add_argument("--stage4-ev-heavy-seed", type=int, default=2999)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "run":
        return run(args)
    raise ValueError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
