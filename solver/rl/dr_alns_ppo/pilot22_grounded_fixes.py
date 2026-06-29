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

from .pilot20_learned_destroy_phaseA import (
    DEFAULT_HELD_OUT_BUNDLES,
    DEFAULT_TRAIN_BUNDLES,
    DEFAULT_WORKER,
    REQUIRED_WORKER_NUMPY,
    PhaseAEpisode,
    _checked,
    _episode_row,
    _mean,
    _parse_int_list,
    _require_torch_available,
    _scale_label,
    _worker_integrity_ok,
    ppo_update_learned,
    run_learned_episode,
    run_operator_select_episode,
    run_random_episode,
)
from .pilot21_learned_destroy_big import (
    HALT_STATUS,
    PASS_STATUS,
    REPORT_ROOT_TOKEN,
    WEAK_STATUS,
    run_worst_removal_episode,
    summarize_stage2,
)


DEFAULT_OUTPUT_DIR = Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot22_grounded_fixes")
PILOT21_OUTPUT_DIR = Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot21_learned_destroy_big")
PILOT21_MODEL_PATH = PILOT21_OUTPUT_DIR / "pilot21_learned_destroy_model.pt"
PILOT21_STATE_PATH = PILOT21_OUTPUT_DIR / "pilot21_state.json"
HALT_LEARNER_NO_VALIDATION_GAIN = "HALT_LEARNER_NO_VALIDATION_GAIN"
HALT_POLICY_UNSTABLE = "HALT_POLICY_UNSTABLE"
EXPLORATORY_ONLY = "EXPLORATORY_ONLY"


class Pilot22Halt(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = str(status)
        self.message = str(message)


def run(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    _require_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    progress_path = output_dir / "pilot22_progress.log"
    state_path = output_dir / "pilot22_state.json"
    state = _load_state(state_path) if args.resume else {}
    final_status = str(state.get("final_status", "RUNNING") or "RUNNING")
    final_reason = str(state.get("final_reason", "") or "")

    try:
        _enforce_resume_guard(state, resume=bool(args.resume), force_exploratory=bool(args.force_exploratory))
        _log(progress_path, "Pilot22 start")
        preflight = run_preflight(args, output_dir)
        os.environ["SETP_WORKER_PYTHON"] = str(Path(args.worker_python).resolve())
        state["preflight"] = preflight
        state["literature_fixes"] = literature_fix_records()
        _save_state(state_path, state)
        _write_json(output_dir / "pilot22_literature_fixes.json", state["literature_fixes"])

        if not _stage_done(state, "stageA"):
            _check_wall(started, args.max_wall_seconds)
            rows = run_stage_a(args, output_dir, progress_path)
            stage_a = summarize_stage_a(rows)
            state["stageA"] = stage_a
            state["completed_stage"] = "stageA"
            _save_state(state_path, state)
            _write_json(output_dir / "pilot22_stageA_summary.json", stage_a)
            _log(progress_path, f"StageA EXPLORATORY verdict={stage_a['proxy_status']}: {stage_a['reason']}")

        if bool(args.force_exploratory):
            final_status = EXPLORATORY_ONLY
            final_reason = "Stage A exploratory-only run requested"
            state["final_status"] = final_status
            state["final_reason"] = final_reason
            return 0

        if not _stage_done(state, "stageB"):
            _check_wall(started, args.max_wall_seconds)
            stage_b = run_stage_b(args, output_dir, progress_path, state, started)
            state["stageB"] = stage_b
            state["completed_stage"] = "stageB"
            _save_state(state_path, state)
            _write_json(output_dir / "pilot22_stageB_summary.json", stage_b)
            _log(progress_path, f"StageB verdict={stage_b['gate_status']}: {stage_b['gate_reason']}")
            if stage_b["gate_status"] != "G1_PASS":
                raise Pilot22Halt(stage_b["gate_status"], stage_b["gate_reason"])

        if not _stage_done(state, "stageC"):
            _check_wall(started, args.max_wall_seconds)
            rows = run_stage_c(args, output_dir, progress_path, state)
            stage_c = summarize_stage2(rows)
            state["stageC"] = stage_c
            state["completed_stage"] = "stageC"
            _save_state(state_path, state)
            _write_json(output_dir / "pilot22_stageC_summary.json", stage_c)
            _log(progress_path, f"StageC verdict={stage_c['status']}: {stage_c['reason']}")

        final_status = str((state.get("stageC") or {}).get("status") or state.get("final_status") or "UNKNOWN")
        final_reason = str((state.get("stageC") or {}).get("reason") or state.get("final_reason") or "")
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        return 0 if final_status in {PASS_STATUS, WEAK_STATUS} else 2
    except Pilot22Halt as exc:
        final_status = exc.status
        final_reason = exc.message
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        _write_stage_c_skipped_marker(output_dir, state, final_status=final_status, final_reason=final_reason)
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
        _write_json(output_dir / "pilot22_report.json", state)
        _write_report(output_dir / "pilot22_report.md", state)


def run_preflight(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    worker_python = Path(args.worker_python).resolve()
    if not worker_python.exists():
        raise Pilot22Halt("HALT_WORKER_INTEGRITY", f"py313 worker missing: {worker_python}")
    worker = _run_python_json(
        worker_python,
        "import json,sys,numpy; print(json.dumps({'exe':sys.executable,'version':sys.version.split()[0],'numpy':numpy.__version__}))",
    )
    if str(worker.get("numpy")) != REQUIRED_WORKER_NUMPY:
        raise Pilot22Halt("HALT_WORKER_INTEGRITY", f"worker NumPy drift: {worker.get('numpy')} != {REQUIRED_WORKER_NUMPY}")
    _require_torch_available()
    import torch

    if not torch.cuda.is_available():
        raise Pilot22Halt("HALT_PREFLIGHT", "py312 torch CUDA is not available")
    if not Path(args.pilot21_model).exists():
        raise Pilot22Halt("HALT_PREFLIGHT", f"Pilot21 model missing for Stage A: {args.pilot21_model}")
    missing = [bundle for bundle in _all_required_bundles(args) if not Path(bundle).exists()]
    if missing:
        raise Pilot22Halt("HALT_PREFLIGHT", f"missing bundles: {missing}")
    usage = shutil.disk_usage(output_dir.resolve().anchor or ".")
    free_gb = float(usage.free) / (1024.0**3)
    if free_gb < float(args.min_free_disk_gb):
        raise Pilot22Halt("HALT_PREFLIGHT", f"free disk {free_gb:.1f}GB < {args.min_free_disk_gb}GB")
    preflight = {
        "worker": worker,
        "torch_version": str(torch.__version__),
        "cuda_available": True,
        "cuda_device": torch.cuda.get_device_name(0),
        "cuda_total_gb": float(torch.cuda.get_device_properties(0).total_memory) / (1024.0**3),
        "disk_free_gb": free_gb,
        "required_bundles": _all_required_bundles(args),
        "git": _git_snapshot(),
    }
    _write_json(output_dir / "pilot22_preflight.json", preflight)
    return preflight


def run_stage_a(args: argparse.Namespace, output_dir: Path, progress_path: Path) -> list[dict[str, Any]]:
    from .learned_destroy_policy import load_learned_destroy_policy

    model = load_learned_destroy_policy(args.pilot21_model)
    rows_path = output_dir / "pilot22_stageA_exploratory.csv"
    rows = _read_csv(rows_path) if args.resume else []
    completed = {(row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0)) for row in rows}
    bundles = _parse_list(args.stage_a_bundles) or list(DEFAULT_HELD_OUT_BUNDLES)
    seeds = _parse_int_list(args.stage_a_seeds)
    for bundle in bundles:
        for seed in seeds:
            for algorithm in ("learned_destroy", "operator_select", "random_operator", "worst_removal_fixed"):
                key = (algorithm, bundle, int(seed))
                if key in completed:
                    continue
                _log(progress_path, f"StageA EXPLORATORY run {algorithm} bundle={bundle} seed={seed}")
                row = _run_algorithm_row(
                    algorithm,
                    model,
                    bundle,
                    seed=int(seed),
                    eval_budget=int(args.stage_a_eval_budget),
                    max_customers=int(args.max_customers),
                )
                row["evidence_role"] = "EXPLORATORY"
                rows.append(row)
                _write_csv(rows_path, rows)
    return rows


def run_stage_b(
    args: argparse.Namespace,
    output_dir: Path,
    progress_path: Path,
    state: dict[str, Any],
    started: float,
) -> dict[str, Any]:
    import torch
    from .learned_destroy_policy import make_learned_destroy_actor_critic, save_learned_destroy_policy, load_learned_destroy_policy

    model_path = output_dir / "pilot22_learned_destroy_model.pt"
    checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    train_state = dict(state.get("stageB_progress") or {})
    latest_checkpoint = _latest_checkpoint(checkpoint_dir)
    if args.resume and latest_checkpoint is not None:
        model = load_learned_destroy_policy(latest_checkpoint)
        start_group = int(train_state.get("next_group", 0))
    else:
        model = make_learned_destroy_actor_critic(seed=int(args.seed), hidden_size=int(args.hidden_size))
        start_group = 0
    model.train()
    optimizer = torch.optim.Adam(model.parameters(), lr=float(args.learning_rate))
    train_bundles = _stage_b_train_bundles(state, args)
    if not train_bundles:
        raise Pilot22Halt("HALT_NO_TRAIN_BUNDLES", "No Pilot22 training bundles after headroom-scale filtering")

    update_rows = _read_csv(output_dir / "pilot22_update_log.csv") if args.resume else []
    episode_rows = _read_csv(output_dir / "pilot22_training_episode_log.csv") if args.resume else []
    validation_rows = _read_csv(output_dir / "pilot22_validation_rows.csv") if args.resume else []
    pending_groups: list[list[PhaseAEpisode]] = []
    initial_validation_mean = _initial_validation_mean(validation_rows)
    if initial_validation_mean is None:
        initial_summary = validate_policy(
            model,
            args,
            output_dir,
            progress_path,
            update_index=-1,
            tag="initial",
        )
        validation_rows.append(initial_summary)
        _write_csv(output_dir / "pilot22_validation_rows.csv", validation_rows)
        initial_validation_mean = float(initial_summary["validation_mean_obj"])
    total_groups = int(math.ceil(int(args.stage_b_train_episodes) / max(1, int(args.pomo_rollouts))))

    for group_index in range(start_group, total_groups):
        _check_wall(started, args.max_wall_seconds)
        bundle = train_bundles[int(group_index) % len(train_bundles)]
        group: list[PhaseAEpisode] = []
        for rollout_idx in range(int(args.pomo_rollouts)):
            episode_index = group_index * int(args.pomo_rollouts) + rollout_idx
            if episode_index >= int(args.stage_b_train_episodes):
                break
            seed = int(args.seed) + episode_index
            episode = run_learned_episode(
                model,
                bundle,
                seed=seed,
                eval_budget=int(args.stage_b_eval_budget),
                max_customers=int(args.max_customers),
                deterministic=False,
            )
            group.append(episode)
            row = _episode_row(episode)
            row["pomo_group"] = int(group_index)
            row["pomo_rollout"] = int(rollout_idx)
            episode_rows.append(row)
            _write_csv(output_dir / "pilot22_training_episode_log.csv", episode_rows)
        if group:
            pending_groups.append(group)
        if len(pending_groups) >= int(args.rollout_min_groups):
            batch = flatten_pomo_shared_baseline(pending_groups)
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
            validation_summary: dict[str, Any] = {}
            if (update_index + 1) % int(args.validation_every_updates) == 0:
                validation_summary = validate_policy(
                    model,
                    args,
                    output_dir,
                    progress_path,
                    update_index=update_index,
                    tag=f"update_{update_index + 1:04d}",
                )
                validation_summary["validation_gain_pct_vs_initial"] = _improvement_pct(
                    initial_validation_mean,
                    float(validation_summary["validation_mean_obj"]),
                )
                validation_rows.append(validation_summary)
                _write_csv(output_dir / "pilot22_validation_rows.csv", validation_rows)
            update_row = {
                "update_index": int(update_index),
                "group_index": int(group_index),
                "episode_index": int(min((group_index + 1) * int(args.pomo_rollouts), int(args.stage_b_train_episodes)) - 1),
                "pomo_rollouts": int(args.pomo_rollouts),
                **metrics,
                **{key: validation_summary.get(key, "") for key in ("validation_mean_obj", "validation_gain_pct_vs_initial", "validation_zero_violations")},
            }
            update_rows.append(update_row)
            _write_csv(output_dir / "pilot22_update_log.csv", update_rows)
            _log(progress_path, f"StageB update {update_index} group={group_index} entropy={metrics.get('entropy')} val_gain={update_row.get('validation_gain_pct_vs_initial')}")
            if (update_index + 1) % int(args.checkpoint_every_updates) == 0:
                ckpt = checkpoint_dir / f"pilot22_learned_destroy_update_{update_index + 1:04d}.pt"
                save_learned_destroy_policy(ckpt, model, metadata={"update_index": update_index, "group_index": group_index})
                _log(progress_path, f"StageB checkpoint {ckpt}")
            pending_groups = []
        train_state["next_group"] = group_index + 1
        state["stageB_progress"] = train_state
        _save_state(output_dir / "pilot22_state.json", state)

    final_validation = validate_policy(model, args, output_dir, progress_path, update_index=len(update_rows), tag="final")
    final_validation["validation_gain_pct_vs_initial"] = _improvement_pct(initial_validation_mean, float(final_validation["validation_mean_obj"]))
    validation_rows.append(final_validation)
    _write_csv(output_dir / "pilot22_validation_rows.csv", validation_rows)
    save_learned_destroy_policy(model_path, model, metadata={"train_episodes": int(args.stage_b_train_episodes), "pomo_rollouts": int(args.pomo_rollouts)})
    return summarize_stage_b(update_rows, episode_rows, validation_rows, model_path, threshold_pct=float(args.validation_gain_threshold))


def validate_policy(
    model: Any,
    args: argparse.Namespace,
    output_dir: Path,
    progress_path: Path,
    *,
    update_index: int,
    tag: str,
) -> dict[str, Any]:
    rows_path = output_dir / "pilot22_validation_detail_rows.csv"
    detail_rows = _read_csv(rows_path)
    bundles = _parse_list(args.validation_bundles) or list(DEFAULT_HELD_OUT_BUNDLES)
    seeds = _parse_int_list(args.validation_seeds)
    validation_rows = []
    for bundle in bundles:
        for seed in seeds:
            _log(progress_path, f"StageB validation {tag} bundle={bundle} seed={seed}")
            episode = run_learned_episode(
                model,
                bundle,
                seed=int(seed),
                eval_budget=int(args.validation_eval_budget),
                max_customers=int(args.max_customers),
                deterministic=True,
            )
            row = _episode_row(episode)
            row["tag"] = str(tag)
            row["update_index"] = int(update_index)
            detail_rows.append(row)
            validation_rows.append(row)
            _write_csv(rows_path, detail_rows)
    return {
        "tag": str(tag),
        "update_index": int(update_index),
        "validation_mean_obj": _mean([float(row["best_obj"]) for row in validation_rows]),
        "validation_zero_violations": all(int(row.get("violation_count", 1)) == 0 for row in validation_rows),
        "validation_row_count": len(validation_rows),
    }


def run_stage_c(args: argparse.Namespace, output_dir: Path, progress_path: Path, state: dict[str, Any]) -> list[dict[str, Any]]:
    from .learned_destroy_policy import load_learned_destroy_policy

    model_path = Path((state.get("stageB") or {}).get("model_path") or output_dir / "pilot22_learned_destroy_model.pt")
    model = load_learned_destroy_policy(model_path)
    rows_path = output_dir / "pilot22_phase_rows.csv"
    rows = _read_csv(rows_path) if args.resume else []
    completed = {(row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0)) for row in rows}
    bundles = _parse_list(args.stage_c_bundles) or list(DEFAULT_HELD_OUT_BUNDLES)
    seeds = _parse_int_list(args.stage_c_seeds)
    for bundle in bundles:
        for seed in seeds:
            for algorithm in ("learned_destroy", "operator_select", "random_operator", "worst_removal_fixed"):
                key = (algorithm, bundle, int(seed))
                if key in completed:
                    continue
                _log(progress_path, f"StageC run {algorithm} bundle={bundle} seed={seed}")
                row = _run_algorithm_row(
                    algorithm,
                    model,
                    bundle,
                    seed=int(seed),
                    eval_budget=int(args.stage_c_eval_budget),
                    max_customers=int(args.max_customers),
                )
                row["evidence_role"] = "GATE"
                rows.append(row)
                _write_csv(rows_path, rows)
    return rows


def _run_algorithm_row(
    algorithm: str,
    model: Any,
    bundle: str,
    *,
    seed: int,
    eval_budget: int,
    max_customers: int,
) -> dict[str, Any]:
    if algorithm == "learned_destroy":
        episode = run_learned_episode(
            model,
            bundle,
            seed=int(seed),
            eval_budget=int(eval_budget),
            max_customers=int(max_customers),
            deterministic=True,
        )
        row = _episode_row(episode)
    elif algorithm == "operator_select":
        row = run_operator_select_episode(bundle, seed=int(seed), eval_budget=int(eval_budget))
    elif algorithm == "random_operator":
        row = run_random_episode(bundle, seed=int(seed), eval_budget=int(eval_budget))
    elif algorithm == "worst_removal_fixed":
        row = run_worst_removal_episode(bundle, seed=int(seed), eval_budget=int(eval_budget))
    else:
        raise ValueError(f"unknown algorithm: {algorithm}")
    row["algorithm"] = algorithm
    return row


def flatten_pomo_shared_baseline(groups: list[list[PhaseAEpisode]]) -> dict[str, Any]:
    import torch

    global_obs: list[list[float]] = []
    customer_features: list[list[list[float]]] = []
    customer_masks: list[list[bool]] = []
    repair_actions: list[int] = []
    q_actions: list[int] = []
    threshold_actions: list[int] = []
    selected_indices: list[list[int]] = []
    selected_counts: list[int] = []
    old_log_probs: list[float] = []
    old_values: list[float] = []
    advantages: list[float] = []
    returns: list[float] = []
    for group in groups:
        group_returns = [float(sum(episode.rewards)) for episode in group]
        baseline = _mean(group_returns)
        for episode, episode_return in zip(group, group_returns):
            step_advantage = float(episode_return - baseline)
            global_obs.extend(episode.global_obs)
            customer_features.extend(episode.customer_features)
            customer_masks.extend(episode.customer_masks)
            repair_actions.extend(episode.repair_actions)
            q_actions.extend(episode.q_actions)
            threshold_actions.extend(episode.threshold_actions)
            selected_indices.extend(episode.selected_indices)
            selected_counts.extend(episode.selected_counts)
            old_log_probs.extend(episode.old_log_probs)
            old_values.extend(episode.values)
            advantages.extend([step_advantage for _ in episode.rewards])
            returns.extend([float(episode_return) for _ in episode.rewards])
    if not global_obs:
        raise ValueError("no POMO rollout steps")
    adv_tensor = torch.as_tensor(advantages, dtype=torch.float32)
    adv_std = adv_tensor.std(unbiased=False)
    adv_tensor = (adv_tensor - adv_tensor.mean()) / (adv_std + 1e-8) if float(adv_std) > 1e-8 else adv_tensor - adv_tensor.mean()
    return {
        "global_obs": torch.as_tensor(global_obs, dtype=torch.float32),
        "customer_features": torch.as_tensor(customer_features, dtype=torch.float32),
        "customer_masks": torch.as_tensor(customer_masks, dtype=torch.bool),
        "repair_actions": torch.as_tensor(repair_actions, dtype=torch.long),
        "q_actions": torch.as_tensor(q_actions, dtype=torch.long),
        "threshold_actions": torch.as_tensor(threshold_actions, dtype=torch.long),
        "selected_indices": torch.as_tensor(selected_indices, dtype=torch.long),
        "selected_counts": torch.as_tensor(selected_counts, dtype=torch.long),
        "old_log_probs": torch.as_tensor(old_log_probs, dtype=torch.float32),
        "old_values": torch.as_tensor(old_values, dtype=torch.float32),
        "advantages": adv_tensor,
        "returns": torch.as_tensor(returns, dtype=torch.float32),
    }


def summarize_stage_a(rows: list[dict[str, Any]]) -> dict[str, Any]:
    phase = summarize_stage2(rows)
    avg = float(phase.get("heldout_avg_improvement_pct_vs_operator_select", math.nan))
    if math.isfinite(avg) and avg >= -8.0:
        proxy_status = "EXPLORATORY_GAP_SHRUNK"
        reason = f"Pilot21 ckpt gap vs operator-select is {avg:.3f}%, clearly less bad than the Pilot20 roughly -22% baseline"
    elif math.isfinite(avg) and avg <= -20.0:
        proxy_status = "EXPLORATORY_REWARD_PROXY_MISMATCH"
        reason = f"Pilot21 ckpt gap remains {avg:.3f}%, so Pilot21 reward lift did not transfer to held-out cost"
    else:
        proxy_status = "EXPLORATORY_MIXED_GAP"
        reason = f"Pilot21 ckpt gap is {avg:.3f}%; Stage B still proceeds with the grounded fixes"
    return {"proxy_status": proxy_status, "reason": reason, "phase_summary": phase}


def summarize_stage_b(
    update_rows: list[dict[str, Any]],
    episode_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    model_path: Path,
    *,
    threshold_pct: float,
) -> dict[str, Any]:
    gains = [float(row.get("validation_gain_pct_vs_initial")) for row in validation_rows if _is_number(row.get("validation_gain_pct_vs_initial"))]
    kls = [float(row.get("approx_kl")) for row in update_rows if _is_number(row.get("approx_kl"))]
    entropies = [float(row.get("entropy")) for row in update_rows if _is_number(row.get("entropy"))]
    finite_losses = all(
        math.isfinite(float(row.get(key) or 0.0))
        for row in update_rows
        for key in ("policy_loss", "value_loss", "approx_kl", "entropy")
    )
    kl_ok = all(0.0 <= value <= 0.30 for value in kls) if kls else False
    best_gain = max(gains, default=math.nan)
    final_gain = gains[-1] if gains else math.nan
    gain_slope = _slope(gains)
    zero_violations = all(str(row.get("validation_zero_violations", "True")).lower() == "true" for row in validation_rows)
    entropy_floor_ok = (min(entropies) > 0.05) if entropies else True
    learned = bool(
        math.isfinite(best_gain)
        and math.isfinite(final_gain)
        and final_gain >= float(threshold_pct)
        and finite_losses
        and kl_ok
        and zero_violations
        and entropy_floor_ok
    )
    if learned:
        status = "G1_PASS"
    elif not finite_losses or not kl_ok:
        status = HALT_POLICY_UNSTABLE
    else:
        status = HALT_LEARNER_NO_VALIDATION_GAIN
    reason = (
        f"best_validation_gain={best_gain:.3f}%, final_validation_gain={final_gain:.3f}%, "
        f"gain_slope={gain_slope:.6g}, finite_losses={finite_losses}, kl_ok={kl_ok}, "
        f"zero_violations={zero_violations}, entropy_floor_ok={entropy_floor_ok}"
    )
    return {
        "gate_status": status,
        "gate_reason": reason,
        "model_path": str(model_path),
        "episode_count": len(episode_rows),
        "update_count": len(update_rows),
        "validation_count": len(validation_rows),
        "best_validation_gain_pct_vs_initial": best_gain,
        "final_validation_gain_pct_vs_initial": final_gain,
        "validation_gain_slope": gain_slope,
        "finite_losses": finite_losses,
        "approx_kl_ok": kl_ok,
        "entropy_first": entropies[0] if entropies else None,
        "entropy_last": entropies[-1] if entropies else None,
        "entropy_floor_ok": entropy_floor_ok,
        "validation_zero_violations": zero_violations,
    }


def literature_fix_records() -> list[dict[str, str]]:
    return [
        {
            "fix": "G1_VALIDATION_COST",
            "symptom": "Pilot21 failed only because entropy increased although reward, slope, loss, and KL were healthy.",
            "source": "POMO NeurIPS 2020 discourages premature convergence; RL4CO reports validation/test gaps rather than entropy-drop gates.",
            "change": "Pilot22 Stage B G1 uses held-out deterministic cost improvement, finite losses, KL stability, and only an entropy floor.",
            "why_only_this": "The failure was a gate-definition problem, not evidence that high entropy itself is unhealthy.",
        },
        {
            "fix": "POMO_SHARED_BASELINE",
            "symptom": "Single-trajectory GAE gave high-variance credit for the same instance.",
            "source": "POMO uses multiple rollouts per instance and a shared group baseline.",
            "change": "Pilot22 groups multiple stochastic learned-destroy rollouts on the same bundle and uses group mean return as the advantage baseline.",
            "why_only_this": "It changes the credit estimator while preserving the existing policy, worker, and solution-feasibility contract.",
        },
        {
            "fix": "DISCRETE_5_3_1_0_REWARD",
            "symptom": "Pilot21 still used custom 120x best-gain scaling after removing the max(0) clamp.",
            "source": "Cao alns/ALNS.py reward_list=[5,3,1,0]; Reijnen-style ALNS outcome classes are best, better, accepted, rejected.",
            "change": "learned_destroy_reward maps new best/accepted improvement/accepted worsening/rejected to 5/3/1/0.",
            "why_only_this": "This is the published operator-selection reward shape; the rest of the search/referee semantics stay unchanged.",
        },
    ]


def _stage_b_train_bundles(state: dict[str, Any], args: argparse.Namespace) -> list[str]:
    explicit = _parse_list(args.stage_b_train_bundles)
    if explicit:
        return explicit
    headroom_scales = _pilot21_headroom_scales()
    candidates = list(DEFAULT_TRAIN_BUNDLES)
    if not headroom_scales:
        return candidates
    filtered = [bundle for bundle in candidates if _scale_label(bundle) in headroom_scales]
    return filtered or candidates


def _pilot21_headroom_scales() -> set[str]:
    if not PILOT21_STATE_PATH.exists():
        return set()
    try:
        state = json.loads(PILOT21_STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    return {str(value) for value in (state.get("stage0") or {}).get("headroom_scales") or []}


def _enforce_resume_guard(state: dict[str, Any], *, resume: bool, force_exploratory: bool) -> None:
    status = str(state.get("final_status", "") or "")
    guarded = {"HALT_LEARNER_FLAT", HALT_LEARNER_NO_VALIDATION_GAIN, HALT_POLICY_UNSTABLE, HALT_STATUS, "HALT_NO_DESTROY_HEADROOM", "HALT_NO_TRAIN_BUNDLES"}
    if bool(resume) and status in guarded and not bool(force_exploratory):
        raise Pilot22Halt("HALT_RESUME_GUARD", f"HALT_RESUME_GUARD: refusing to resume from halted state {status}; start a fresh Pilot22 output dir or use --force-exploratory for Stage A only")


def _stage_done(state: dict[str, Any], stage: str) -> bool:
    order = {"stageA": 0, "stageB": 1, "stageC": 2}
    completed = str(state.get("completed_stage", "") or "")
    return completed in order and order[completed] >= order[stage]


def _all_required_bundles(args: argparse.Namespace) -> list[str]:
    values: list[str] = []
    for text in (args.stage_a_bundles, args.stage_b_train_bundles, args.validation_bundles, args.stage_c_bundles):
        values.extend(_parse_list(text))
    if not values:
        values.extend(DEFAULT_TRAIN_BUNDLES)
        values.extend(DEFAULT_HELD_OUT_BUNDLES)
    return sorted(dict.fromkeys(values))


def _latest_checkpoint(path: Path) -> Path | None:
    items = sorted(path.glob("pilot22_learned_destroy_update_*.pt"))
    return items[-1] if items else None


def _initial_validation_mean(rows: list[dict[str, Any]]) -> float | None:
    for row in rows:
        if str(row.get("tag", "")) == "initial" and _is_number(row.get("validation_mean_obj")):
            return float(row["validation_mean_obj"])
    return None


def _check_wall(started: float, max_wall_seconds: int) -> None:
    if time.monotonic() - started >= float(max_wall_seconds):
        raise Pilot22Halt("HALT_WALL_CLOCK", f"global wall clock reached {max_wall_seconds}s")


def _run_python_json(python: Path, code: str) -> dict[str, Any]:
    env = os.environ.copy()
    root = Path.cwd()
    env["PYTHONPATH"] = os.pathsep.join([str(root / "solver" / "rl"), str(root / "solver" / "src"), str(root / "models" / "src")])
    proc = subprocess.run([str(python), "-c", code], cwd=root, env=env, text=True, capture_output=True, check=False, timeout=30)
    if proc.returncode != 0:
        raise Pilot22Halt("HALT_PREFLIGHT", proc.stderr.strip() or proc.stdout.strip())
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
            "docs/handoff/codex_prompts/10_dr_learned_destroy_big_experiment.md",
            "docs/handoff/codex_prompts/11_dr_learned_destroy_pilot22_grounded_fixes.md",
        ).splitlines(),
    }


def _write_report(path: Path, state: dict[str, Any]) -> None:
    status = str(state.get("final_status", "UNKNOWN"))
    reason = str(state.get("final_reason", ""))
    stage_a = state.get("stageA") or {}
    stage_b = state.get("stageB") or {}
    stage_c = state.get("stageC") or {}
    stage_a_gap = ((stage_a.get("phase_summary") or {}).get("heldout_avg_improvement_pct_vs_operator_select"))
    if status == PASS_STATUS:
        next_step = "绿灯 Phase B：FRVCP、碳感知控制、全规模擂台和精确解锚。"
    elif status == WEAK_STATUS:
        next_step = "记录弱正结果，先看消融/验证曲线再决定是否扩大。"
    elif status == HALT_LEARNER_NO_VALIDATION_GAIN:
        next_step = "按文献修齐后验证 cost 仍未达阈值，转查动作空间/碳感知时刻或 future-work。"
    elif status == HALT_POLICY_UNSTABLE:
        next_step = "验证曾有峰值但训练后期回落且 KL 不稳；先查 PPO 更新幅度、学习率、batch/clip，再决定是否新开稳定性实验。"
    elif status == HALT_STATUS:
        next_step = "按文献修齐且通过 G1 后仍打不过 operator-select，记录诚实负结果，learned-destroy 转 future-work。"
    else:
        next_step = "先处理 HALT 原因，再决定是否新开实验。"
    artifacts = [
        "`pilot22_preflight.json`",
        "`pilot22_literature_fixes.json`",
        "`pilot22_stageA_exploratory.csv`",
        "`pilot22_update_log.csv`",
        "`pilot22_validation_rows.csv`",
        "`pilot22_report.json`",
    ]
    if stage_c:
        artifacts.append("`pilot22_phase_rows.csv`")
    elif state.get("completed_stage") == "stageB":
        artifacts.append("`pilot22_phase_rows.csv` (Stage C skipped marker)")
    lines = [
        "# Pilot22 Learned-Destroy Grounded Fixes Report",
        "",
        f"Final verdict: `{status}`",
        f"Stop reason: {reason}",
        "",
        "## 人话结论",
        "",
        f"- 现 ckpt 差距缩没缩：Stage A avg vs operator-select = {stage_a_gap}%，{stage_a.get('reason', 'Stage A 未完成')}",
        f"- 按文献修齐后学没学到：{stage_b.get('gate_reason', 'Stage B 未完成')}",
        f"- 最终判级：`{status}`",
        f"- 下一步：{next_step}",
        f"- 跑到哪：{state.get('completed_stage', 'none')}；墙钟 {float(state.get('wall_time_seconds') or 0.0):.1f}s",
        "",
        "## 三修法落地",
        "",
    ]
    for item in state.get("literature_fixes") or literature_fix_records():
        lines.append(f"- {item['fix']}：症状={item['symptom']}；出处={item['source']}；改哪={item['change']}；为什么只改这={item['why_only_this']}")
    lines.extend(["", "## Artifacts", ""])
    lines.extend(f"- {artifact}" for artifact in artifacts)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _write_stage_c_skipped_marker(output_dir: Path, state: dict[str, Any], *, final_status: str, final_reason: str) -> None:
    if state.get("completed_stage") != "stageB" or state.get("stageC"):
        return
    rows_path = output_dir / "pilot22_phase_rows.csv"
    if rows_path.exists():
        return
    _write_csv(
        rows_path,
        [
            {
                "algorithm": "SKIPPED_STAGE_C",
                "evidence_role": "SKIPPED",
                "status": str(final_status),
                "reason": str(final_reason),
            }
        ],
    )


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
    if REPORT_ROOT_TOKEN not in path.as_posix():
        raise ValueError(f"Pilot22 outputs must stay under {REPORT_ROOT_TOKEN}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pilot22 learned-destroy grounded fixes")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    run_parser.add_argument("--worker-python", default=str(DEFAULT_WORKER))
    run_parser.add_argument("--pilot21-model", default=str(PILOT21_MODEL_PATH))
    run_parser.add_argument("--resume", action="store_true", default=True)
    run_parser.add_argument("--no-resume", dest="resume", action="store_false")
    run_parser.add_argument("--force-exploratory", action="store_true")
    run_parser.add_argument("--max-wall-seconds", type=int, default=21600)
    run_parser.add_argument("--min-free-disk-gb", type=float, default=5.0)
    run_parser.add_argument("--seed", type=int, default=1)
    run_parser.add_argument("--stage-a-bundles", default="")
    run_parser.add_argument("--stage-a-seeds", default="101,102")
    run_parser.add_argument("--stage-a-eval-budget", type=int, default=180)
    run_parser.add_argument("--stage-b-train-bundles", default="")
    run_parser.add_argument("--stage-b-train-episodes", type=int, default=1000)
    run_parser.add_argument("--stage-b-eval-budget", type=int, default=120)
    run_parser.add_argument("--pomo-rollouts", type=int, default=4)
    run_parser.add_argument("--rollout-min-groups", type=int, default=1)
    run_parser.add_argument("--validation-bundles", default="")
    run_parser.add_argument("--validation-seeds", default="301")
    run_parser.add_argument("--validation-eval-budget", type=int, default=120)
    run_parser.add_argument("--validation-every-updates", type=int, default=10)
    run_parser.add_argument("--validation-gain-threshold", type=float, default=3.0)
    run_parser.add_argument("--checkpoint-every-updates", type=int, default=10)
    run_parser.add_argument("--stage-c-bundles", default="")
    run_parser.add_argument("--stage-c-seeds", default="401,402")
    run_parser.add_argument("--stage-c-eval-budget", type=int, default=180)
    run_parser.add_argument("--max-customers", type=int, default=128)
    run_parser.add_argument("--hidden-size", type=int, default=128)
    run_parser.add_argument("--learning-rate", type=float, default=3e-4)
    run_parser.add_argument("--ppo-epochs", type=int, default=2)
    run_parser.add_argument("--minibatch-size", type=int, default=64)
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
