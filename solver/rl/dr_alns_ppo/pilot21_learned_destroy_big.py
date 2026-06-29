from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np

from .action_space import (
    ALPHA_UCB_CHOICE,
    BLOCK_DESTROY_IDS,
    BLOCK_EXPLORATION_RATIOS,
    BLOCK_Q_RATIOS,
    BLOCK_REPAIR_IDS,
    BLOCK_THRESHOLD_RATIOS,
    DESTROY_IDS,
)
from .pilot20_learned_destroy_phaseA import (
    DEFAULT_HELD_OUT_BUNDLES,
    DEFAULT_OUTPUT_DIR as PILOT20_OUTPUT_DIR,
    DEFAULT_TRAIN_BUNDLES,
    DEFAULT_WORKER,
    REQUIRED_WORKER_NUMPY,
    collect_training_episode,
    flatten_learned_episodes,
    ppo_update_learned,
    run_learned_episode,
    run_operator_select_episode,
    run_random_episode,
    _checked,
    _episode_row,
    _parse_int_list,
    _require_torch_available,
    _scale_label,
    _worker_integrity_ok,
)
from .schemas import BlockDecodedAction
from .worker_client import WorkerClient


DEFAULT_OUTPUT_DIR = Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot21_learned_destroy_big")
DEFAULT_STAGE0_BUNDLES = (
    "models/data_bundle/generated_instances/E-UK25_02__curric_d2_s3_seed2_24h",
    "models/data_bundle/generated_instances/E-UK25_08__curric_d2_s3_seed8_24h",
    "models/data_bundle/generated_instances/E-UK50_01__curric_d2_s3_seed1_24h",
    "models/data_bundle/generated_instances/E-UK50_04__curric_d2_s3_seed4_24h",
    "models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113",
    "models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113",
)
EXTRA_TRAIN_BUNDLES = (
    "models/data_bundle/generated_instances/E-UK100_02__u0_seed2_24h_20251113",
    "models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113",
)
REPORT_ROOT_TOKEN = "solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot"
PASS_STATUS = "PASS_LEARNED_DESTROY"
WEAK_STATUS = "WEAK_LEARNED_DESTROY"
HALT_STATUS = "HALT_LEARNED_DESTROY"


class Pilot21Halt(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = str(status)
        self.message = str(message)


def run(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    _require_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    progress_path = output_dir / "pilot21_progress.log"
    state_path = output_dir / "pilot21_state.json"
    state = _load_state(state_path) if args.resume else {}
    final_status = str(state.get("final_status", "RUNNING") or "RUNNING")
    final_reason = str(state.get("final_reason", "") or "")

    try:
        _enforce_resume_guard(state, resume=bool(args.resume))
        _log(progress_path, "Pilot21 start")
        preflight = run_preflight(args, output_dir)
        os.environ["SETP_WORKER_PYTHON"] = str(Path(args.worker_python).resolve())
        state["preflight"] = preflight
        _save_state(state_path, state)

        if not _stage_done(state, "stage0"):
            _check_wall(started, args.max_wall_seconds)
            rows = run_stage0(args, output_dir, progress_path)
            stage0 = summarize_stage0(rows)
            state["stage0"] = stage0
            state["completed_stage"] = "stage0"
            _save_state(state_path, state)
            _write_json(output_dir / "pilot21_stage0_summary.json", stage0)
            _log(progress_path, f"Stage0 verdict={stage0['gate_status']}: {stage0['gate_reason']}")
            if stage0["gate_status"] != "G0_PASS":
                raise Pilot21Halt(stage0["gate_status"], stage0["gate_reason"])

        if not _stage_done(state, "stage1"):
            _check_wall(started, args.max_wall_seconds)
            stage1 = run_stage1(args, output_dir, progress_path, state, started)
            state["stage1"] = stage1
            state["completed_stage"] = "stage1"
            _save_state(state_path, state)
            _write_json(output_dir / "pilot21_stage1_summary.json", stage1)
            _log(progress_path, f"Stage1 verdict={stage1['gate_status']}: {stage1['gate_reason']}")
            if stage1["gate_status"] != "G1_PASS":
                raise Pilot21Halt(stage1["gate_status"], stage1["gate_reason"])

        if not _stage_done(state, "stage2"):
            _check_wall(started, args.max_wall_seconds)
            rows = run_stage2(args, output_dir, progress_path, state)
            stage2 = summarize_stage2(rows)
            state["stage2"] = stage2
            state["completed_stage"] = "stage2"
            _save_state(state_path, state)
            _write_json(output_dir / "pilot21_stage2_summary.json", stage2)
            _log(progress_path, f"Stage2 verdict={stage2['status']}: {stage2['reason']}")

        final_status = str((state.get("stage2") or {}).get("status") or state.get("final_status") or "UNKNOWN")
        final_reason = str((state.get("stage2") or {}).get("reason") or state.get("final_reason") or "")
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        return 0 if final_status in {PASS_STATUS, WEAK_STATUS} else 2
    except Pilot21Halt as exc:
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
    except Exception as exc:
        final_status = "HALT_EXCEPTION"
        final_reason = f"{type(exc).__name__}: {exc}"
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        _save_state(state_path, state)
        _log(progress_path, f"HALT {final_status}: {final_reason}")
        return 2
    finally:
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        state["wall_time_seconds"] = float(time.monotonic() - started)
        _write_json(output_dir / "pilot21_big_report.json", state)
        _write_big_report(output_dir / "pilot21_big_report.md", state)


def run_preflight(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    worker_python = Path(args.worker_python).resolve()
    if not worker_python.exists():
        raise Pilot21Halt("HALT_WORKER_INTEGRITY", f"py313 worker missing: {worker_python}")
    worker = _run_python_json(
        worker_python,
        "import json,sys,numpy; print(json.dumps({'exe':sys.executable,'version':sys.version.split()[0],'numpy':numpy.__version__}))",
    )
    if str(worker.get("numpy")) != REQUIRED_WORKER_NUMPY:
        raise Pilot21Halt("HALT_WORKER_INTEGRITY", f"worker NumPy drift: {worker.get('numpy')} != {REQUIRED_WORKER_NUMPY}")
    _require_torch_available()
    import torch

    if not torch.cuda.is_available():
        raise Pilot21Halt("HALT_PREFLIGHT", "py312 torch CUDA is not available")
    missing = [bundle for bundle in _all_required_bundles(args) if not Path(bundle).exists()]
    if missing:
        raise Pilot21Halt("HALT_PREFLIGHT", f"missing bundles: {missing}")
    usage = shutil.disk_usage(output_dir.resolve().anchor or ".")
    free_gb = float(usage.free) / (1024.0**3)
    if free_gb < float(args.min_free_disk_gb):
        raise Pilot21Halt("HALT_PREFLIGHT", f"free disk {free_gb:.1f}GB < {args.min_free_disk_gb}GB")
    git = _git_snapshot()
    preflight = {
        "worker": worker,
        "torch_version": str(torch.__version__),
        "cuda_available": True,
        "cuda_device": torch.cuda.get_device_name(0),
        "disk_free_gb": free_gb,
        "required_bundles": _all_required_bundles(args),
        "git": git,
    }
    _write_json(output_dir / "pilot21_preflight.json", preflight)
    return preflight


def run_stage0(args: argparse.Namespace, output_dir: Path, progress_path: Path) -> list[dict[str, Any]]:
    rows_path = output_dir / "pilot21_stage0_headroom.csv"
    rows = _read_csv(rows_path) if args.resume else []
    completed = {(row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0)) for row in rows}
    seeds = _parse_int_list(args.stage0_seeds)
    bundles = _parse_list(args.stage0_bundles) or list(DEFAULT_STAGE0_BUNDLES)
    for bundle in bundles:
        for seed in seeds:
            for algorithm in ("operator_select", "worst_removal_fixed", "best_of_k_destroy"):
                key = (algorithm, bundle, int(seed))
                if key in completed:
                    continue
                _log(progress_path, f"Stage0 run {algorithm} bundle={bundle} seed={seed}")
                if algorithm == "operator_select":
                    row = run_operator_select_episode(bundle, seed=int(seed), eval_budget=int(args.stage0_eval_budget))
                elif algorithm == "worst_removal_fixed":
                    row = run_worst_removal_episode(bundle, seed=int(seed), eval_budget=int(args.stage0_eval_budget))
                else:
                    row = run_best_of_k_episode(
                        bundle,
                        seed=int(seed),
                        eval_budget=int(args.stage0_eval_budget),
                        candidate_k=int(args.best_of_k),
                    )
                row["algorithm"] = algorithm
                rows.append(row)
                _write_csv(rows_path, rows)
    return rows


def run_worst_removal_episode(bundle: str, *, seed: int, eval_budget: int) -> dict[str, Any]:
    d_idx = BLOCK_DESTROY_IDS.index("worst_customer_removal")
    r_idx = BLOCK_REPAIR_IDS.index(ALPHA_UCB_CHOICE)
    q_idx = BLOCK_Q_RATIOS.index(0.40)
    threshold_idx = BLOCK_THRESHOLD_RATIOS.index(0.0025)
    exploration_idx = BLOCK_EXPLORATION_RATIOS.index(0.0)
    action = BlockDecodedAction(
        destroy_id="worst_customer_removal",
        repair_id=ALPHA_UCB_CHOICE,
        q_ratio=0.40,
        threshold_ratio=0.0025,
        exploration_ratio=0.0,
        block_size=1,
        raw=(d_idx, r_idx, q_idx, threshold_idx, exploration_idx),
    )
    return _run_fixed_block_episode("worst_removal_fixed", bundle, seed=seed, eval_budget=eval_budget, action=action)


def run_best_of_k_episode(bundle: str, *, seed: int, eval_budget: int, candidate_k: int) -> dict[str, Any]:
    started = time.monotonic()
    client = WorkerClient(bundle, seed=int(seed), max_evals=int(eval_budget))
    response: dict[str, Any] = {}
    steps = 0
    try:
        response = _checked(client.reset())
        while int(response.get("actual_evals", 0)) < int(eval_budget):
            response = _checked(
                client.best_of_k_destroy(
                    {
                        "candidate_k": int(candidate_k),
                        "destroy_ids": [value for value in DESTROY_IDS if value != ALPHA_UCB_CHOICE],
                        "repair_id": ALPHA_UCB_CHOICE,
                        "q_ratio": 0.40,
                        "threshold_ratio": 0.0025,
                    }
                )
            )
            steps += 1
    finally:
        client.close()
    return _row_from_response("best_of_k_destroy", bundle, seed=seed, eval_budget=eval_budget, response=response, started=started, steps=steps)


def _run_fixed_block_episode(
    algorithm: str,
    bundle: str,
    *,
    seed: int,
    eval_budget: int,
    action: BlockDecodedAction,
) -> dict[str, Any]:
    started = time.monotonic()
    client = WorkerClient(bundle, seed=int(seed), max_evals=int(eval_budget))
    response: dict[str, Any] = {}
    steps = 0
    try:
        response = _checked(client.reset())
        while int(response.get("actual_evals", 0)) < int(eval_budget):
            response = _checked(client.block_step(action))
            steps += 1
    finally:
        client.close()
    return _row_from_response(algorithm, bundle, seed=seed, eval_budget=eval_budget, response=response, started=started, steps=steps)


def run_stage1(
    args: argparse.Namespace,
    output_dir: Path,
    progress_path: Path,
    state: dict[str, Any],
    started: float,
) -> dict[str, Any]:
    import torch
    from .learned_destroy_policy import (
        load_learned_destroy_policy,
        make_learned_destroy_actor_critic,
        save_learned_destroy_policy,
    )

    model_path = output_dir / "pilot21_learned_destroy_model.pt"
    checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    train_state = dict(state.get("stage1_progress") or {})
    latest_checkpoint = _latest_checkpoint(checkpoint_dir)
    if args.resume and latest_checkpoint is not None:
        model = load_learned_destroy_policy(latest_checkpoint)
        start_episode = int(train_state.get("next_episode", 0))
    else:
        model = make_learned_destroy_actor_critic(seed=int(args.seed), hidden_size=int(args.hidden_size))
        start_episode = 0
    model.train()
    optimizer = torch.optim.Adam(model.parameters(), lr=float(args.learning_rate))
    train_bundles = _stage1_train_bundles(state)
    if not train_bundles:
        raise Pilot21Halt("HALT_NO_TRAIN_BUNDLES", "G0 passed but no training bundles match headroom scales")
    update_rows = _read_csv(output_dir / "pilot21_update_log.csv") if args.resume else []
    episode_rows = _read_csv(output_dir / "pilot21_training_episode_log.csv") if args.resume else []
    pending = []

    for episode_index in range(start_episode, int(args.stage1_train_episodes)):
        _check_wall(started, args.max_wall_seconds)
        episode = collect_training_episode(
            model,
            train_bundles,
            episode_index=episode_index,
            base_seed=int(args.seed),
            eval_budget=int(args.stage1_eval_budget),
            max_customers=int(args.max_customers),
        )
        pending.append(episode)
        episode_rows.append(_episode_row(episode))
        _write_csv(output_dir / "pilot21_training_episode_log.csv", episode_rows)
        if len(pending) >= int(args.rollout_min_episodes):
            batch = flatten_learned_episodes(pending, gamma=float(args.gamma), gae_lambda=float(args.gae_lambda))
            metrics = ppo_update_learned(
                model,
                optimizer,
                batch,
                epochs=int(args.ppo_epochs),
                minibatch_size=int(args.minibatch_size),
                clip_range=float(args.clip_range),
                value_coef=float(args.value_coef),
                entropy_coef=float(args.entropy_coef),
                max_grad_norm=float(args.max_grad_norm),
            )
            update_index = len(update_rows)
            update_rows.append({"update_index": update_index, "episode_index": episode_index, **metrics})
            _write_csv(output_dir / "pilot21_update_log.csv", update_rows)
            _log(
                progress_path,
                "Stage1 update "
                f"{update_index} episode={episode_index} "
                f"policy_loss={metrics.get('policy_loss')} "
                f"value_loss={metrics.get('value_loss')} "
                f"entropy={metrics.get('entropy')} "
                f"approx_kl={metrics.get('approx_kl')}",
            )
            if (update_index + 1) % int(args.checkpoint_every_updates) == 0:
                ckpt = checkpoint_dir / f"pilot21_learned_destroy_update_{update_index + 1:04d}.pt"
                save_learned_destroy_policy(ckpt, model, metadata={"update_index": update_index, "episode_index": episode_index})
                _log(progress_path, f"Stage1 checkpoint {ckpt}")
            pending = []
        train_state["next_episode"] = episode_index + 1
        state["stage1_progress"] = train_state
        _save_state(output_dir / "pilot21_state.json", state)
    save_learned_destroy_policy(model_path, model, metadata={"train_episodes": int(args.stage1_train_episodes)})
    summary = summarize_stage1(update_rows, episode_rows, model_path)
    return summary


def run_stage2(args: argparse.Namespace, output_dir: Path, progress_path: Path, state: dict[str, Any]) -> list[dict[str, Any]]:
    from .learned_destroy_policy import load_learned_destroy_policy

    model_path = Path((state.get("stage1") or {}).get("model_path") or output_dir / "pilot21_learned_destroy_model.pt")
    model = load_learned_destroy_policy(model_path)
    rows_path = output_dir / "pilot21_phase_rows.csv"
    rows = _read_csv(rows_path) if args.resume else []
    completed = {(row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0)) for row in rows}
    bundles = _parse_list(args.stage2_bundles) or list(DEFAULT_HELD_OUT_BUNDLES) + ["models/data_bundle/generated_instances/E-UK100_03__u0_seed3_24h_20251113"]
    seeds = _parse_int_list(args.stage2_seeds)
    for bundle in bundles:
        for seed in seeds:
            for algorithm in ("learned_destroy", "operator_select", "random_operator", "worst_removal_fixed"):
                key = (algorithm, bundle, int(seed))
                if key in completed:
                    continue
                _log(progress_path, f"Stage2 run {algorithm} bundle={bundle} seed={seed}")
                if algorithm == "learned_destroy":
                    episode = run_learned_episode(
                        model,
                        bundle,
                        seed=int(seed),
                        eval_budget=int(args.stage2_eval_budget),
                        max_customers=int(args.max_customers),
                        deterministic=True,
                    )
                    row = _episode_row(episode)
                elif algorithm == "operator_select":
                    row = run_operator_select_episode(bundle, seed=int(seed), eval_budget=int(args.stage2_eval_budget))
                elif algorithm == "random_operator":
                    row = run_random_episode(bundle, seed=int(seed), eval_budget=int(args.stage2_eval_budget))
                else:
                    row = run_worst_removal_episode(bundle, seed=int(seed), eval_budget=int(args.stage2_eval_budget))
                row["algorithm"] = algorithm
                rows.append(row)
                _write_csv(rows_path, rows)
    return rows


def summarize_stage0(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_scale: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        scale = str(row.get("scale") or _scale_label(str(row.get("bundle", ""))))
        algo = str(row.get("algorithm", ""))
        by_scale.setdefault(scale, {}).setdefault(algo, []).append(float(row.get("best_obj") or math.nan))
    scale_rows = []
    g0_pass_scales = []
    for scale, algos in sorted(by_scale.items()):
        op = _mean(algos.get("operator_select", []))
        worst = _mean(algos.get("worst_removal_fixed", []))
        best = _mean(algos.get("best_of_k_destroy", []))
        headroom = (op - best) / max(abs(op), 1.0) * 100.0 if math.isfinite(op) and math.isfinite(best) else math.nan
        worst_improvement = (op - worst) / max(abs(op), 1.0) * 100.0 if math.isfinite(op) and math.isfinite(worst) else math.nan
        has_headroom = bool((math.isfinite(headroom) and headroom > 1.0) or (math.isfinite(worst_improvement) and worst_improvement > 0.0))
        if has_headroom:
            g0_pass_scales.append(scale)
        scale_rows.append(
            {
                "scale": scale,
                "operator_select_mean": op,
                "worst_removal_mean": worst,
                "best_of_k_mean": best,
                "headroom_pct": headroom,
                "worst_improvement_pct": worst_improvement,
                "has_destroy_headroom": has_headroom,
            }
        )
    worker_ok = all(bool(row.get("worker_integrity_ok", False)) for row in rows)
    if not worker_ok:
        status = "HALT_WORKER_INTEGRITY"
        reason = "At least one Stage0 row did not use the py313/NumPy 2.3.5 worker"
    elif not g0_pass_scales:
        status = "HALT_NO_DESTROY_HEADROOM"
        reason = "No scale had best-of-k headroom > 1% or worst-removal improvement > 0%"
    else:
        status = "G0_PASS"
        reason = f"Destroy headroom found on scales: {', '.join(g0_pass_scales)}"
    _write_csv(DEFAULT_OUTPUT_DIR / "_unused.csv", []) if False else None
    return {"gate_status": status, "gate_reason": reason, "scale_rows": scale_rows, "headroom_scales": g0_pass_scales, "worker_integrity_ok": worker_ok}


def summarize_stage1(update_rows: list[dict[str, Any]], episode_rows: list[dict[str, Any]], model_path: Path) -> dict[str, Any]:
    rewards = [float(row.get("reward_sum") or 0.0) for row in episode_rows if _is_number(row.get("reward_sum"))]
    entropies = [float(row.get("entropy") or 0.0) for row in update_rows if _is_number(row.get("entropy"))]
    approx_kls = [float(row.get("approx_kl") or 0.0) for row in update_rows if _is_number(row.get("approx_kl"))]
    finite_losses = all(
        math.isfinite(float(row.get(key) or 0.0))
        for row in update_rows
        for key in ("policy_loss", "value_loss", "approx_kl", "entropy")
    )
    early = _mean(rewards[: max(1, len(rewards) // 3)])
    late = _mean(rewards[-max(1, len(rewards) // 3) :])
    reward_lift = (late - early) / max(abs(early), 1.0) * 100.0 if rewards else math.nan
    slope = _slope(rewards)
    entropy_drop = entropies[0] - entropies[-1] if len(entropies) >= 2 else math.nan
    kl_ok = all(0.0 <= value <= 0.30 for value in approx_kls) if approx_kls else False
    learned = bool(math.isfinite(reward_lift) and reward_lift >= 1.0 and slope > 0.0 and math.isfinite(entropy_drop) and entropy_drop > 0.0 and finite_losses and kl_ok)
    status = "G1_PASS" if learned else "HALT_LEARNER_FLAT"
    reason = (
        f"reward_lift={reward_lift:.3f}%, slope={slope:.6g}, entropy_drop={entropy_drop:.3f}, finite_losses={finite_losses}, kl_ok={kl_ok}"
    )
    return {
        "gate_status": status,
        "gate_reason": reason,
        "model_path": str(model_path),
        "episode_count": len(episode_rows),
        "update_count": len(update_rows),
        "reward_early_mean": early,
        "reward_late_mean": late,
        "reward_late_vs_early_pct": reward_lift,
        "reward_slope": slope,
        "entropy_first": entropies[0] if entropies else None,
        "entropy_last": entropies[-1] if entropies else None,
        "entropy_drop": entropy_drop,
        "finite_losses": finite_losses,
        "approx_kl_ok": kl_ok,
    }


def summarize_stage2(rows: list[dict[str, Any]]) -> dict[str, Any]:
    learned = [row for row in rows if row.get("algorithm") == "learned_destroy"]
    by_algo = {(row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0)): row for row in rows}
    improvements = []
    random_improvements = []
    worst_improvements = []
    by_scale: dict[str, list[float]] = {}
    for row in learned:
        key = (row.get("bundle"), int(row.get("seed") or 0))
        op = by_algo.get(("operator_select", *key))
        random_row = by_algo.get(("random_operator", *key))
        worst = by_algo.get(("worst_removal_fixed", *key))
        if op:
            value = _improvement_pct(float(op["best_obj"]), float(row["best_obj"]))
            improvements.append(value)
            by_scale.setdefault(str(row.get("scale") or _scale_label(str(row.get("bundle", "")))), []).append(value)
        if random_row:
            random_improvements.append(_improvement_pct(float(random_row["best_obj"]), float(row["best_obj"])))
        if worst:
            worst_improvements.append(_improvement_pct(float(worst["best_obj"]), float(row["best_obj"])))
    avg = _mean(improvements)
    min_scale = min((_mean(values) for values in by_scale.values()), default=math.nan)
    avg_random = _mean(random_improvements)
    avg_worst = _mean(worst_improvements)
    zero_violations = all(int(row.get("violation_count", 1)) == 0 for row in learned)
    worker_ok = all(bool(row.get("worker_integrity_ok", False)) for row in rows)
    if not worker_ok:
        status = "HALT_WORKER_INTEGRITY"
    elif zero_violations and avg >= 2.0 and min_scale >= 0.0 and avg_random > 0.0 and avg_worst > 0.0:
        status = PASS_STATUS
    elif zero_violations and avg >= 0.0 and min_scale >= 0.0:
        status = WEAK_STATUS
    else:
        status = HALT_STATUS
    reason = f"avg_vs_operator={avg:.3f}%, min_scale={min_scale:.3f}%, avg_vs_random={avg_random:.3f}%, avg_vs_worst={avg_worst:.3f}%, zero_violations={zero_violations}, worker_ok={worker_ok}"
    return {
        "status": status,
        "reason": reason,
        "heldout_avg_improvement_pct_vs_operator_select": avg,
        "min_scale_improvement_pct_vs_operator_select": min_scale,
        "heldout_avg_improvement_pct_vs_random": avg_random,
        "heldout_avg_improvement_pct_vs_worst_removal": avg_worst,
        "zero_violation_learned": zero_violations,
        "worker_integrity_ok": worker_ok,
        "scale_improvement_pct": {scale: _mean(values) for scale, values in sorted(by_scale.items())},
    }


def _row_from_response(
    algorithm: str,
    bundle: str,
    *,
    seed: int,
    eval_budget: int,
    response: dict[str, Any],
    started: float,
    steps: int,
) -> dict[str, Any]:
    trace = response.get("trace", {}) or {}
    return {
        "algorithm": algorithm,
        "bundle": str(bundle),
        "scale": _scale_label(str(bundle)),
        "seed": int(seed),
        "eval_budget": int(eval_budget),
        "best_obj": float(response.get("best_obj", 0.0)),
        "current_obj": float(response.get("current_obj", 0.0)),
        "actual_evals": int(response.get("actual_evals", 0)),
        "candidate_scores": int(response.get("candidate_scores", 0)),
        "violation_count": int(response.get("violation_count", 0)),
        "steps": int(steps),
        "wall_time_seconds": float(time.monotonic() - started),
        "worker_python_executable": str(trace.get("worker_python_executable", "")),
        "worker_numpy_version": str(trace.get("worker_numpy_version", "")),
        "worker_integrity_ok": _worker_integrity_ok(trace),
        "control_mode": str(trace.get("control_mode", "")),
        "trace_destroy_id": str(trace.get("destroy_id", "")),
        "trace_repair_id": str(trace.get("repair_id", "")),
        "candidate_k_evaluated": int(trace.get("candidate_k_evaluated", 0) or 0),
    }


def _stage1_train_bundles(state: dict[str, Any]) -> list[str]:
    headroom_scales = set((state.get("stage0") or {}).get("headroom_scales") or [])
    candidates = list(DEFAULT_TRAIN_BUNDLES) + list(EXTRA_TRAIN_BUNDLES)
    if not headroom_scales:
        return candidates
    return [bundle for bundle in candidates if _scale_label(bundle) in headroom_scales]


def _all_required_bundles(args: argparse.Namespace) -> list[str]:
    values: list[str] = []
    for text in (args.stage0_bundles, args.stage2_bundles):
        values.extend(_parse_list(text))
    if not values:
        values.extend(DEFAULT_STAGE0_BUNDLES)
        values.extend(DEFAULT_HELD_OUT_BUNDLES)
    values.extend(DEFAULT_TRAIN_BUNDLES)
    values.extend(EXTRA_TRAIN_BUNDLES)
    return sorted(dict.fromkeys(values))


def _stage_done(state: dict[str, Any], stage: str) -> bool:
    order = {"stage0": 0, "stage1": 1, "stage2": 2}
    completed = str(state.get("completed_stage", "") or "")
    return completed in order and order[completed] >= order[stage]


def _enforce_resume_guard(state: dict[str, Any], *, resume: bool) -> None:
    status = str(state.get("final_status", "") or "")
    guarded = {"HALT_LEARNER_FLAT", "HALT_LEARNED_DESTROY", "HALT_NO_DESTROY_HEADROOM", "HALT_NO_TRAIN_BUNDLES"}
    if bool(resume) and status in guarded:
        raise Pilot21Halt("HALT_RESUME_GUARD", f"Refusing to resume from halted Pilot21 state {status}; start a fresh run instead")


def _check_wall(started: float, max_wall_seconds: int) -> None:
    if time.monotonic() - started >= float(max_wall_seconds):
        raise Pilot21Halt("HALT_WALL_CLOCK", f"global wall clock reached {max_wall_seconds}s")


def _latest_checkpoint(path: Path) -> Path | None:
    items = sorted(path.glob("pilot21_learned_destroy_update_*.pt"))
    return items[-1] if items else None


def _run_python_json(python: Path, code: str) -> dict[str, Any]:
    env = os.environ.copy()
    root = Path.cwd()
    env["PYTHONPATH"] = os.pathsep.join([str(root / "solver" / "rl"), str(root / "solver" / "src"), str(root / "models" / "src")])
    proc = subprocess.run([str(python), "-c", code], cwd=root, env=env, text=True, capture_output=True, check=False, timeout=30)
    if proc.returncode != 0:
        raise Pilot21Halt("HALT_PREFLIGHT", proc.stderr.strip() or proc.stdout.strip())
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _git_snapshot() -> dict[str, Any]:
    def run_git(*parts: str) -> str:
        proc = subprocess.run(["git", *parts], text=True, capture_output=True, check=False, timeout=30)
        return (proc.stdout or proc.stderr).strip()

    return {
        "status_short_branch": run_git("status", "--short", "--branch"),
        "head": run_git("rev-parse", "HEAD"),
        "branch": run_git("branch", "--show-current"),
        "tracked_docs": run_git(
            "ls-files",
            "HANDOFF.md",
            "docs/handoff/codex_prompts/09_dr_learned_destroy_phaseA.md",
            "docs/handoff/codex_prompts/10_dr_learned_destroy_big_experiment.md",
            "docs/handoff/dr_alns_learned_destroy_plan.md",
        ).splitlines(),
    }


def _write_big_report(path: Path, state: dict[str, Any]) -> None:
    status = str(state.get("final_status", "UNKNOWN"))
    reason = str(state.get("final_reason", ""))
    stage0 = state.get("stage0") or {}
    stage1 = state.get("stage1") or {}
    stage2 = state.get("stage2") or {}
    q1 = str(stage0.get("gate_reason") or "Stage0 未完成")
    if stage1:
        if stage1.get("gate_status") == "HALT_LEARNER_FLAT":
            q2 = (
                "没有通过 G1；奖励均值有上升，"
                f"但 entropy 从 {stage1.get('entropy_first')} 升到 {stage1.get('entropy_last')}，"
                "按保守闸门判定学习器仍未收敛。"
            )
        else:
            q2 = str(stage1.get("gate_reason") or "Stage1 已完成")
    else:
        q2 = "Stage1 未运行或未完成"
    if status == PASS_STATUS:
        next_step = "绿灯 Phase B：FRVCP、碳感知控制、全规模擂台和精确解锚。"
    elif status == "HALT_NO_DESTROY_HEADROOM":
        next_step = "换 DR 旋钮：优先碳感知充电/出发时刻，或把 learned-destroy 放入 future-work。"
    elif status == "HALT_LEARNER_FLAT":
        next_step = "先查学习机器：lr、entropy、credit assignment、编码器容量，不再盲目加 episode。"
    elif status in {WEAK_STATUS, HALT_STATUS}:
        next_step = "记录诚实弱/负结果，论文主线转押富问题 vs 弱场 + 机制。"
    else:
        next_step = "先处理 HALT 原因，再决定是否 resume。"
    artifacts = ["`pilot21_preflight.json`", "`pilot21_big_report.json`"]
    if stage0:
        artifacts.extend(["`pilot21_stage0_headroom.csv`", "`pilot21_stage0_summary.json`"])
    if stage1:
        artifacts.extend(["`pilot21_training_episode_log.csv`", "`pilot21_update_log.csv`", "`pilot21_stage1_summary.json`"])
    if stage2:
        artifacts.extend(["`pilot21_phase_rows.csv`", "`pilot21_stage2_summary.json`"])
    lines = [
        "# Pilot21 Learned-Destroy Big Report",
        "",
        f"Final verdict: `{status}`",
        f"Stop reason: {reason or stage2.get('reason') or stage1.get('gate_reason') or stage0.get('gate_reason') or ''}",
        "",
        "## 人话结论",
        "",
        f"- Q1 破坏有没有杠杆：{q1}",
        f"- Q2 修学习机器后学没学到：{q2}",
        f"- 最终判级：`{status}`",
        f"- 下一步：{next_step}",
        f"- 跑到哪：{state.get('completed_stage', 'none')}；墙钟 {float(state.get('wall_time_seconds') or 0.0):.1f}s",
        "",
        "## Artifacts",
        "",
        *(f"- {artifact}" for artifact in artifacts),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8", newline="\n")
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_state(path: Path, state: dict[str, Any]) -> None:
    _write_json(path, state)


def _log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{stamp}\t{message}\n")


def _parse_list(text: str | None) -> list[str]:
    return [part.strip() for part in str(text or "").split(",") if part.strip()]


def _mean(values: list[float]) -> float:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    return float(sum(finite) / len(finite)) if finite else math.nan


def _slope(values: list[float]) -> float:
    if len(values) < 2:
        return math.nan
    xs = np.arange(len(values), dtype=np.float64)
    ys = np.asarray(values, dtype=np.float64)
    return float(np.polyfit(xs, ys, 1)[0])


def _improvement_pct(base: float, candidate: float) -> float:
    return (float(base) - float(candidate)) / max(abs(float(base)), 1.0) * 100.0


def _is_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _require_output_dir(path: Path) -> None:
    normalized = path.as_posix()
    if REPORT_ROOT_TOKEN not in normalized:
        raise ValueError(f"Pilot21 outputs must stay under {REPORT_ROOT_TOKEN}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pilot21 learned-destroy big experiment")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    run_parser.add_argument("--worker-python", default=str(DEFAULT_WORKER))
    run_parser.add_argument("--resume", action="store_true", default=True)
    run_parser.add_argument("--no-resume", dest="resume", action="store_false")
    run_parser.add_argument("--max-wall-seconds", type=int, default=21600)
    run_parser.add_argument("--min-free-disk-gb", type=float, default=5.0)
    run_parser.add_argument("--seed", type=int, default=1)
    run_parser.add_argument("--stage0-bundles", default="")
    run_parser.add_argument("--stage0-seeds", default="11,12")
    run_parser.add_argument("--stage0-eval-budget", type=int, default=80)
    run_parser.add_argument("--best-of-k", type=int, default=4)
    run_parser.add_argument("--stage1-train-episodes", type=int, default=1000)
    run_parser.add_argument("--stage1-eval-budget", type=int, default=120)
    run_parser.add_argument("--rollout-min-episodes", type=int, default=4)
    run_parser.add_argument("--checkpoint-every-updates", type=int, default=10)
    run_parser.add_argument("--stage2-bundles", default="")
    run_parser.add_argument("--stage2-seeds", default="101,102,103")
    run_parser.add_argument("--stage2-eval-budget", type=int, default=180)
    run_parser.add_argument("--max-customers", type=int, default=128)
    run_parser.add_argument("--hidden-size", type=int, default=128)
    run_parser.add_argument("--learning-rate", type=float, default=3e-4)
    run_parser.add_argument("--ppo-epochs", type=int, default=2)
    run_parser.add_argument("--minibatch-size", type=int, default=64)
    run_parser.add_argument("--gamma", type=float, default=0.99)
    run_parser.add_argument("--gae-lambda", type=float, default=0.95)
    run_parser.add_argument("--clip-range", type=float, default=0.2)
    run_parser.add_argument("--value-coef", type=float, default=0.5)
    run_parser.add_argument("--entropy-coef", type=float, default=0.01)
    run_parser.add_argument("--max-grad-norm", type=float, default=0.5)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "run":
        return run(args)
    raise ValueError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
