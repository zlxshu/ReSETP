from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import time
from pathlib import Path
from typing import Any

from .pilot20_learned_destroy_phaseA import (
    DEFAULT_WORKER,
    REQUIRED_WORKER_NUMPY,
    PhaseAEpisode,
    _episode_row,
    _mean,
    _parse_int_list,
    _require_torch_available,
    _scale_label,
    _worker_integrity_ok,
    run_learned_episode,
)
from .pilot21_learned_destroy_big import (
    HALT_STATUS,
    PASS_STATUS,
    REPORT_ROOT_TOKEN,
    WEAK_STATUS,
)
from .pilot22_grounded_fixes import (
    flatten_pomo_shared_baseline,
    _git_snapshot,
    _improvement_pct,
    _is_number,
    _latest_checkpoint,
    _load_state,
    _log,
    _parse_list,
    _read_csv,
    _run_algorithm_row,
    _run_python_json,
    _save_state,
    _slope,
    _write_csv,
    _write_json,
)


DEFAULT_OUTPUT_DIR = Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot23_stabilize")
PILOT22_OUTPUT_DIR = Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot22_grounded_fixes")
PILOT22_VALIDATION_ROWS = PILOT22_OUTPUT_DIR / "pilot22_validation_rows.csv"
PILOT22_TRAINING_ROWS = PILOT22_OUTPUT_DIR / "pilot22_training_episode_log.csv"
PILOT22_VALIDATION_DETAIL_ROWS = PILOT22_OUTPUT_DIR / "pilot22_validation_detail_rows.csv"
PILOT22_CHECKPOINT_DIR = PILOT22_OUTPUT_DIR / "checkpoints"

PASS_CKPT_STATUS = "PASS_LEARNED_DESTROY_CKPT"
WEAK_CKPT_STATUS = "WEAK_CKPT_GENERALIZATION"
STAGEB_REQUIRED_STATUS = "STAGEB_REQUIRED_CKPT_LT2"
PEAK_CKPT_MISSING = "PEAK_CKPT_MISSING"
HALT_TEST_SET_OVERLAP = "HALT_TEST_SET_OVERLAP"
HALT_POLICY_UNSTABLE_V2 = "HALT_POLICY_UNSTABLE_V2"
HALT_LEARNER_NO_VALIDATION_GAIN_V2 = "HALT_LEARNER_NO_VALIDATION_GAIN_V2"
HALT_INTEGRITY = "HALT_INTEGRITY"

DEFAULT_STAGE_B_TRAIN_BUNDLES = (
    "models/data_bundle/generated_instances/E-UK25_02__curric_d2_s3_seed2_24h",
    "models/data_bundle/generated_instances/E-UK25_03__curric_d2_s3_seed3_24h",
    "models/data_bundle/generated_instances/E-UK25_04__curric_d2_s3_seed4_24h",
    "models/data_bundle/generated_instances/E-UK25_05__curric_d2_s3_seed5_24h",
    "models/data_bundle/generated_instances/E-UK25_06__curric_d2_s3_seed6_24h",
    "models/data_bundle/generated_instances/E-UK25_07__curric_d2_s3_seed7_24h",
)
DEFAULT_VALIDATION_BUNDLES = (
    "models/data_bundle/generated_instances/E-UK25_08__curric_d2_s3_seed8_24h",
    "models/data_bundle/generated_instances/E-UK25_09__curric_d2_s3_seed9_24h",
    "models/data_bundle/generated_instances/E-UK50_04__curric_d2_s3_seed4_24h",
)
DEFAULT_TEST_BUNDLES = (
    "models/data_bundle/generated_instances/E-UK50_01__curric_d2_s3_seed1_24h",
    "models/data_bundle/generated_instances/E-UK50_02__curric_d2_s3_seed2_24h",
    "models/data_bundle/generated_instances/E-UK50_03__curric_d2_s3_seed3_24h",
    "models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113",
)
_REQUIRED_BUNDLE_FILES = ("instance.json", "distance_matrix.npy", "carbon_profile.csv", "nodes.csv", "scenario_manifest.json")


class Pilot23Halt(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = str(status)
        self.message = str(message)


def run(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    _require_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    progress_path = output_dir / "pilot23_progress.log"
    state_path = output_dir / "pilot23_state.json"
    state = _load_state(state_path) if args.resume else {}
    final_status = str(state.get("final_status", "RUNNING") or "RUNNING")
    final_reason = str(state.get("final_reason", "") or "")

    try:
        _enforce_resume_guard(state, resume=bool(args.resume))
        _log(progress_path, "Pilot23 start")
        preflight = run_preflight(args, output_dir)
        os.environ["SETP_WORKER_PYTHON"] = str(Path(args.worker_python).resolve())
        state["preflight"] = preflight
        state["stabilization_fixes"] = stabilization_fix_records()
        _save_state(state_path, state)
        _write_json(output_dir / "pilot23_stabilization_fixes.json", state["stabilization_fixes"])

        if not _stage_done(state, "stageA"):
            _check_wall(started, args.max_wall_seconds)
            peak = select_pilot22_peak_checkpoint(args)
            state["pilot22_peak"] = peak
            _write_json(output_dir / "pilot23_peak_checkpoint.json", peak)
            if not peak.get("checkpoint_path"):
                stage_a = {
                    "gate_status": PEAK_CKPT_MISSING,
                    "reason": str(peak.get("reason") or "Pilot22 peak checkpoint missing"),
                    "peak": peak,
                }
                _write_stage_a_skipped_marker(output_dir, stage_a)
            else:
                rows = run_stage_a(args, output_dir, progress_path, peak)
                stage_a = summarize_stage_a(
                    rows,
                    pass_threshold=float(args.stage_a_pass_threshold),
                    train_threshold=float(args.stage_a_train_threshold),
                )
            state["stageA"] = stage_a
            state["completed_stage"] = "stageA"
            _save_state(state_path, state)
            _write_json(output_dir / "pilot23_stageA_summary.json", stage_a)
            _log(progress_path, f"StageA verdict={stage_a['gate_status']}: {stage_a['reason']}")
            if stage_a["gate_status"] == PASS_CKPT_STATUS:
                final_status = PASS_CKPT_STATUS
                final_reason = stage_a["reason"]
                state["final_status"] = final_status
                state["final_reason"] = final_reason
                _write_stage_b_skipped_marker(output_dir, final_status, final_reason)
                _write_stage_c_skipped_marker(output_dir, final_status, final_reason)
                return 0
            if stage_a["gate_status"] in {"HALT_WORKER_INTEGRITY", HALT_INTEGRITY, HALT_TEST_SET_OVERLAP}:
                raise Pilot23Halt(stage_a["gate_status"], stage_a["reason"])

        if not _stage_done(state, "stageB"):
            _check_wall(started, args.max_wall_seconds)
            stage_b = run_stage_b(args, output_dir, progress_path, state, started)
            state["stageB"] = stage_b
            state["completed_stage"] = "stageB"
            _save_state(state_path, state)
            _write_json(output_dir / "pilot23_stageB_summary.json", stage_b)
            _log(progress_path, f"StageB verdict={stage_b['gate_status']}: {stage_b['gate_reason']}")
            if stage_b["gate_status"] != "G1_PASS":
                raise Pilot23Halt(stage_b["gate_status"], stage_b["gate_reason"])

        if not _stage_done(state, "stageC"):
            _check_wall(started, args.max_wall_seconds)
            rows = run_stage_c(args, output_dir, progress_path, state)
            stage_c = summarize_stage_c(rows, pass_threshold=float(args.stage_c_pass_threshold))
            state["stageC"] = stage_c
            state["completed_stage"] = "stageC"
            _save_state(state_path, state)
            _write_json(output_dir / "pilot23_stageC_summary.json", stage_c)
            _log(progress_path, f"StageC verdict={stage_c['status']}: {stage_c['reason']}")

        final_status = str((state.get("stageC") or {}).get("status") or state.get("final_status") or "UNKNOWN")
        final_reason = str((state.get("stageC") or {}).get("reason") or state.get("final_reason") or "")
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        return 0 if final_status in {PASS_CKPT_STATUS, PASS_STATUS, WEAK_STATUS} else 2
    except Pilot23Halt as exc:
        final_status = exc.status
        final_reason = exc.message
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        _write_stage_c_skipped_marker(output_dir, final_status, final_reason)
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
        _write_json(output_dir / "pilot23_report.json", state)
        _write_report(output_dir / "pilot23_report.md", state)


def run_preflight(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    worker_python = Path(args.worker_python).resolve()
    if not worker_python.exists():
        raise Pilot23Halt("HALT_WORKER_INTEGRITY", f"py313 worker missing: {worker_python}")
    worker = _run_python_json(
        worker_python,
        "import json,sys,numpy; print(json.dumps({'exe':sys.executable,'version':sys.version.split()[0],'numpy':numpy.__version__}))",
    )
    if str(worker.get("numpy")) != REQUIRED_WORKER_NUMPY:
        raise Pilot23Halt("HALT_WORKER_INTEGRITY", f"worker NumPy drift: {worker.get('numpy')} != {REQUIRED_WORKER_NUMPY}")
    _require_torch_available()
    import torch

    if not torch.cuda.is_available():
        raise Pilot23Halt("HALT_PREFLIGHT", "py312 torch CUDA is not available")
    required_files = [
        PILOT22_VALIDATION_ROWS,
        PILOT22_TRAINING_ROWS,
        PILOT22_VALIDATION_DETAIL_ROWS,
    ]
    missing_files = [str(path) for path in required_files if not path.exists()]
    if missing_files:
        raise Pilot23Halt("HALT_PREFLIGHT", f"missing Pilot22 artifacts: {missing_files}")
    missing_bundles = [bundle for bundle in _all_required_bundles(args) if not Path(bundle).exists()]
    if missing_bundles:
        raise Pilot23Halt("HALT_PREFLIGHT", f"missing bundles: {missing_bundles}")
    incomplete_bundles = _incomplete_bundles(_all_required_bundles(args))
    if incomplete_bundles:
        raise Pilot23Halt("HALT_PREFLIGHT", f"incomplete bundles: {incomplete_bundles}")
    overlap = independent_test_overlap(args)
    if overlap["overlap"]:
        raise Pilot23Halt(HALT_TEST_SET_OVERLAP, json.dumps(overlap, ensure_ascii=False))
    usage = shutil.disk_usage(output_dir.resolve().anchor or ".")
    free_gb = float(usage.free) / (1024.0**3)
    if free_gb < float(args.min_free_disk_gb):
        raise Pilot23Halt("HALT_PREFLIGHT", f"free disk {free_gb:.1f}GB < {args.min_free_disk_gb}GB")
    preflight = {
        "worker": worker,
        "torch_version": str(torch.__version__),
        "cuda_available": True,
        "cuda_device": torch.cuda.get_device_name(0),
        "cuda_total_gb": float(torch.cuda.get_device_properties(0).total_memory) / (1024.0**3),
        "disk_free_gb": free_gb,
        "required_bundles": _all_required_bundles(args),
        "required_bundle_files": _REQUIRED_BUNDLE_FILES,
        "independent_test_overlap": overlap,
        "git": _git_snapshot(),
    }
    _write_json(output_dir / "pilot23_preflight.json", preflight)
    return preflight


def select_pilot22_peak_checkpoint(args: argparse.Namespace) -> dict[str, Any]:
    rows = _read_csv(Path(args.pilot22_validation_rows))
    candidates = [row for row in rows if _is_number(row.get("validation_gain_pct_vs_initial"))]
    if not candidates:
        return {"checkpoint_path": "", "reason": "No numeric Pilot22 validation gains"}
    candidates.sort(key=lambda row: float(row["validation_gain_pct_vs_initial"]), reverse=True)
    for row in candidates:
        ckpt = _checkpoint_for_validation_row(row, Path(args.pilot22_checkpoint_dir))
        if ckpt is not None and ckpt.exists():
            return {
                "checkpoint_path": str(ckpt),
                "checkpoint_selection_method": "best_validation_exact_checkpoint",
                "tag": str(row.get("tag", "")),
                "update_index": int(row.get("update_index") or -1),
                "validation_gain_pct_vs_initial": float(row["validation_gain_pct_vs_initial"]),
                "validation_mean_obj": float(row["validation_mean_obj"]),
                "validation_zero_violations": str(row.get("validation_zero_violations", "")).lower() == "true",
            }
    return {
        "checkpoint_path": "",
        "checkpoint_selection_method": "missing_all_validation_checkpoints",
        "reason": "No Pilot22 validation checkpoint file exists for numeric validation rows",
        "best_tag": str(candidates[0].get("tag", "")),
        "best_validation_gain_pct_vs_initial": float(candidates[0]["validation_gain_pct_vs_initial"]),
    }


def run_stage_a(args: argparse.Namespace, output_dir: Path, progress_path: Path, peak: dict[str, Any]) -> list[dict[str, Any]]:
    from .learned_destroy_policy import load_learned_destroy_policy

    model = load_learned_destroy_policy(str(peak["checkpoint_path"]))
    selected_copy = output_dir / "pilot23_selected_peak_model.pt"
    if not selected_copy.exists():
        shutil.copy2(str(peak["checkpoint_path"]), selected_copy)
    rows_path = output_dir / "pilot23_stageA_independent_test.csv"
    rows = _read_csv(rows_path) if args.resume else []
    completed = {(row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0)) for row in rows}
    for bundle in _test_bundles(args):
        for seed in _parse_int_list(args.test_seeds):
            for algorithm in ("learned_destroy", "operator_select", "random_operator", "worst_removal_fixed"):
                key = (algorithm, bundle, int(seed))
                if key in completed:
                    continue
                _log(progress_path, f"StageA independent-test {algorithm} bundle={bundle} seed={seed}")
                row = _run_algorithm_row(
                    algorithm,
                    model,
                    bundle,
                    seed=int(seed),
                    eval_budget=int(args.stage_a_eval_budget),
                    max_customers=int(args.max_customers),
                )
                row["evidence_role"] = "INDEPENDENT_TEST"
                row["peak_checkpoint_path"] = str(peak["checkpoint_path"])
                row["peak_validation_tag"] = str(peak.get("tag", ""))
                row["peak_validation_gain_pct_vs_initial"] = peak.get("validation_gain_pct_vs_initial", "")
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

    model_path = output_dir / "pilot23_learned_destroy_model.pt"
    best_model_path = output_dir / "pilot23_best_validation_model.pt"
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
    train_bundles = _stage_b_train_bundles(args)
    if not train_bundles:
        raise Pilot23Halt("HALT_NO_TRAIN_BUNDLES", "No Pilot23 Stage B train bundles")

    update_rows = _read_csv(output_dir / "pilot23_update_log.csv") if args.resume else []
    episode_rows = _read_csv(output_dir / "pilot23_training_episode_log.csv") if args.resume else []
    validation_rows = _read_csv(output_dir / "pilot23_validation_rows.csv") if args.resume else []
    initial_validation_mean = _initial_validation_mean(validation_rows)
    best_validation_mean = _best_validation_mean(validation_rows)
    if initial_validation_mean is None:
        initial_summary = validate_policy(model, args, output_dir, progress_path, update_index=-1, tag="initial")
        validation_rows.append(initial_summary)
        _write_csv(output_dir / "pilot23_validation_rows.csv", validation_rows)
        initial_validation_mean = float(initial_summary["validation_mean_obj"])
        best_validation_mean = float(initial_summary["validation_mean_obj"])
        _save_best_validation_checkpoint(
            best_model_path,
            output_dir / "pilot23_best_validation_metadata.json",
            model,
            initial_summary,
            update_index=-1,
            group_index=-1,
            reason="initial_validation_baseline",
        )
    pending_groups: list[list[PhaseAEpisode]] = []
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
            _write_csv(output_dir / "pilot23_training_episode_log.csv", episode_rows)
        if group:
            pending_groups.append(group)
        if len(pending_groups) >= int(args.rollout_min_groups):
            update_index = len(update_rows)
            lr = linear_annealed_lr(
                initial_lr=float(args.learning_rate),
                final_lr=float(args.final_learning_rate),
                update_index=update_index,
                total_updates=max(1, total_groups // max(1, int(args.rollout_min_groups))),
            )
            for group_obj in optimizer.param_groups:
                group_obj["lr"] = lr
            batch = flatten_pomo_shared_baseline(pending_groups)
            metrics = ppo_update_learned_stable(
                model,
                optimizer,
                batch,
                epochs=int(args.ppo_epochs),
                minibatch_size=int(args.minibatch_size),
                clip_range=float(args.clip_range),
                value_coef=float(args.value_coef),
                entropy_coef=float(args.entropy_coef),
                max_grad_norm=float(args.max_grad_norm),
                target_kl=float(args.target_kl),
            )
            validation_summary: dict[str, Any] = {}
            best_checkpoint_saved = False
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
                _write_csv(output_dir / "pilot23_validation_rows.csv", validation_rows)
                if best_validation_mean is None or float(validation_summary["validation_mean_obj"]) < float(best_validation_mean):
                    best_validation_mean = float(validation_summary["validation_mean_obj"])
                    _save_best_validation_checkpoint(
                        best_model_path,
                        output_dir / "pilot23_best_validation_metadata.json",
                        model,
                        validation_summary,
                        update_index=update_index,
                        group_index=group_index,
                        reason="validation_mean_obj_improved",
                    )
                    best_checkpoint_saved = True
            update_row = {
                "update_index": int(update_index),
                "group_index": int(group_index),
                "episode_index": int(min((group_index + 1) * int(args.pomo_rollouts), int(args.stage_b_train_episodes)) - 1),
                "pomo_rollouts": int(args.pomo_rollouts),
                "learning_rate": float(lr),
                "target_kl": float(args.target_kl),
                "best_checkpoint_saved": bool(best_checkpoint_saved),
                **metrics,
                **{key: validation_summary.get(key, "") for key in ("validation_mean_obj", "validation_gain_pct_vs_initial", "validation_zero_violations")},
            }
            update_rows.append(update_row)
            _write_csv(output_dir / "pilot23_update_log.csv", update_rows)
            _log(
                progress_path,
                f"StageB update {update_index} group={group_index} lr={lr:.6g} kl={metrics.get('approx_kl')} early={metrics.get('kl_early_stop')} val_gain={update_row.get('validation_gain_pct_vs_initial')}",
            )
            if (update_index + 1) % int(args.checkpoint_every_updates) == 0:
                ckpt = checkpoint_dir / f"pilot23_learned_destroy_update_{update_index + 1:04d}.pt"
                save_learned_destroy_policy(ckpt, model, metadata={"update_index": update_index, "group_index": group_index, "learning_rate": lr})
                _log(progress_path, f"StageB checkpoint {ckpt}")
            pending_groups = []
        train_state["next_group"] = group_index + 1
        state["stageB_progress"] = train_state
        _save_state(output_dir / "pilot23_state.json", state)

    final_validation = validate_policy(model, args, output_dir, progress_path, update_index=len(update_rows), tag="final")
    final_validation["validation_gain_pct_vs_initial"] = _improvement_pct(initial_validation_mean, float(final_validation["validation_mean_obj"]))
    validation_rows.append(final_validation)
    _write_csv(output_dir / "pilot23_validation_rows.csv", validation_rows)
    if best_validation_mean is None or float(final_validation["validation_mean_obj"]) < float(best_validation_mean):
        _save_best_validation_checkpoint(
            best_model_path,
            output_dir / "pilot23_best_validation_metadata.json",
            model,
            final_validation,
            update_index=len(update_rows),
            group_index=total_groups,
            reason="final_validation_mean_obj_improved",
        )
    save_learned_destroy_policy(model_path, model, metadata={"train_episodes": int(args.stage_b_train_episodes), "pomo_rollouts": int(args.pomo_rollouts)})
    return summarize_stage_b(
        update_rows,
        validation_rows,
        best_model_path,
        threshold_pct=float(args.validation_gain_threshold),
        rollback_tolerance_pct=float(args.validation_rollback_tolerance),
        kl_ok_threshold=float(args.kl_ok_threshold),
        recent_count=int(args.validation_recent_count),
    )


def ppo_update_learned_stable(
    model: Any,
    optimizer: Any,
    batch: dict[str, Any],
    *,
    epochs: int,
    minibatch_size: int,
    clip_range: float,
    value_coef: float,
    entropy_coef: float,
    max_grad_norm: float,
    target_kl: float,
) -> dict[str, float | bool | int]:
    _require_torch_available()
    import torch
    from torch import nn

    sample_count = int(batch["global_obs"].shape[0])
    metrics: list[dict[str, float]] = []
    kl_early_stop = False
    epoch_count = 0
    minibatch_count = 0
    for epoch_index in range(int(epochs)):
        epoch_count = epoch_index + 1
        permutation = torch.randperm(sample_count)
        for start in range(0, sample_count, int(minibatch_size)):
            idx = permutation[start : start + int(minibatch_size)]
            log_probs, entropies, values = model.evaluate_actions(
                batch["global_obs"][idx],
                batch["customer_features"][idx],
                batch["customer_masks"][idx],
                batch["repair_actions"][idx],
                batch["q_actions"][idx],
                batch["threshold_actions"][idx],
                batch["selected_indices"][idx],
                batch["selected_counts"][idx],
            )
            old_log_probs = batch["old_log_probs"][idx]
            advantages = batch["advantages"][idx]
            returns = batch["returns"][idx]
            ratio = torch.exp(log_probs - old_log_probs)
            unclipped = ratio * advantages
            clipped = torch.clamp(ratio, 1.0 - float(clip_range), 1.0 + float(clip_range)) * advantages
            policy_loss = -torch.minimum(unclipped, clipped).mean()
            value_loss = nn.functional.mse_loss(values, returns)
            entropy = entropies.mean()
            loss = policy_loss + float(value_coef) * value_loss - float(entropy_coef) * entropy
            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), float(max_grad_norm))
            optimizer.step()
            with torch.no_grad():
                approx_kl = (old_log_probs - log_probs).mean().abs()
                clip_fraction = ((ratio - 1.0).abs() > float(clip_range)).float().mean()
            minibatch_count += 1
            metrics.append(
                {
                    "policy_loss": float(policy_loss.detach()),
                    "value_loss": float(value_loss.detach()),
                    "entropy": float(entropy.detach()),
                    "approx_kl": float(approx_kl.detach()),
                    "clip_fraction": float(clip_fraction.detach()),
                }
            )
            if float(approx_kl.detach()) > float(target_kl):
                kl_early_stop = True
                break
        if kl_early_stop:
            break
    result = _mean_metrics(metrics)
    result["kl_early_stop"] = bool(kl_early_stop)
    result["epoch_count"] = int(epoch_count)
    result["minibatch_count"] = int(minibatch_count)
    return result


def validate_policy(
    model: Any,
    args: argparse.Namespace,
    output_dir: Path,
    progress_path: Path,
    *,
    update_index: int,
    tag: str,
) -> dict[str, Any]:
    rows_path = output_dir / "pilot23_validation_detail_rows.csv"
    detail_rows = _read_csv(rows_path)
    completed = {(row.get("tag"), row.get("bundle"), int(row.get("seed") or 0)) for row in detail_rows}
    current_rows = [row for row in detail_rows if row.get("tag") == tag]
    for bundle in _validation_bundles(args):
        for seed in _parse_int_list(args.validation_seeds):
            key = (tag, bundle, int(seed))
            if key in completed:
                continue
            _log(progress_path, f"StageB validation {tag} bundle={bundle} seed={seed}")
            row = _run_algorithm_row(
                "learned_destroy",
                model,
                bundle,
                seed=int(seed),
                eval_budget=int(args.validation_eval_budget),
                max_customers=int(args.max_customers),
            )
            row["tag"] = str(tag)
            row["update_index"] = int(update_index)
            row["evidence_role"] = "VALIDATION"
            detail_rows.append(row)
            current_rows.append(row)
            _write_csv(rows_path, detail_rows)
    return {
        "tag": str(tag),
        "update_index": int(update_index),
        "validation_mean_obj": _mean([float(row["best_obj"]) for row in current_rows]),
        "validation_zero_violations": all(int(row.get("violation_count", 1)) == 0 for row in current_rows),
        "validation_row_count": len(current_rows),
    }


def run_stage_c(args: argparse.Namespace, output_dir: Path, progress_path: Path, state: dict[str, Any]) -> list[dict[str, Any]]:
    from .learned_destroy_policy import load_learned_destroy_policy

    model_path = Path((state.get("stageB") or {}).get("best_model_path") or output_dir / "pilot23_best_validation_model.pt")
    model = load_learned_destroy_policy(model_path)
    rows_path = output_dir / "pilot23_phase_rows.csv"
    rows = _read_csv(rows_path) if args.resume else []
    completed = {(row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0)) for row in rows}
    for bundle in _test_bundles(args):
        for seed in _parse_int_list(args.test_seeds):
            for algorithm in ("learned_destroy", "operator_select", "random_operator", "worst_removal_fixed"):
                key = (algorithm, bundle, int(seed))
                if key in completed:
                    continue
                _log(progress_path, f"StageC independent-test {algorithm} bundle={bundle} seed={seed}")
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


def summarize_stage_a(rows: list[dict[str, Any]], *, pass_threshold: float, train_threshold: float) -> dict[str, Any]:
    summary = _comparison_summary(rows)
    status = _stage_a_status(summary, pass_threshold=pass_threshold, train_threshold=train_threshold)
    reason = (
        f"avg_vs_operator={summary['avg_vs_operator']:.3f}%, min_scale={summary['min_scale_vs_operator']:.3f}%, "
        f"avg_vs_random={summary['avg_vs_random']:.3f}%, avg_vs_worst={summary['avg_vs_worst']:.3f}%, "
        f"zero_violations={summary['zero_violations']}, worker_ok={summary['worker_ok']}, preserves_plus_10={summary['preserves_plus_10']}"
    )
    return {"gate_status": status, "reason": reason, **summary}


def summarize_stage_c(rows: list[dict[str, Any]], *, pass_threshold: float) -> dict[str, Any]:
    summary = _comparison_summary(rows)
    if not summary["worker_ok"]:
        status = "HALT_WORKER_INTEGRITY"
    elif not summary["zero_violations"]:
        status = HALT_INTEGRITY
    elif (
        summary["avg_vs_operator"] >= float(pass_threshold)
        and summary["min_scale_vs_operator"] >= 0.0
        and summary["avg_vs_random"] > 0.0
        and summary["avg_vs_worst"] > 0.0
    ):
        status = PASS_STATUS
    elif summary["avg_vs_operator"] >= 0.0 and summary["min_scale_vs_operator"] >= 0.0:
        status = WEAK_STATUS
    else:
        status = HALT_STATUS
    reason = (
        f"avg_vs_operator={summary['avg_vs_operator']:.3f}%, min_scale={summary['min_scale_vs_operator']:.3f}%, "
        f"avg_vs_random={summary['avg_vs_random']:.3f}%, avg_vs_worst={summary['avg_vs_worst']:.3f}%, "
        f"zero_violations={summary['zero_violations']}, worker_ok={summary['worker_ok']}"
    )
    return {"status": status, "reason": reason, **summary}


def summarize_stage_b(
    update_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    best_model_path: Path,
    *,
    threshold_pct: float,
    rollback_tolerance_pct: float,
    kl_ok_threshold: float,
    recent_count: int,
) -> dict[str, Any]:
    gains = [float(row.get("validation_gain_pct_vs_initial")) for row in validation_rows if _is_number(row.get("validation_gain_pct_vs_initial"))]
    kls = [float(row.get("approx_kl")) for row in update_rows if _is_number(row.get("approx_kl"))]
    entropies = [float(row.get("entropy")) for row in update_rows if _is_number(row.get("entropy"))]
    finite_losses = all(
        math.isfinite(float(row.get(key) or 0.0))
        for row in update_rows
        for key in ("policy_loss", "value_loss", "approx_kl", "entropy")
    )
    best_gain = max(gains) if gains else math.nan
    final_gain = gains[-1] if gains else math.nan
    recent_gains = gains[-max(1, int(recent_count)) :] if gains else []
    recent_slope = _slope(recent_gains) if len(recent_gains) >= 2 else 0.0
    recent_floor = min(recent_gains) if recent_gains else math.nan
    kl_ok = bool(kls) and all(0.0 <= value <= float(kl_ok_threshold) for value in kls)
    entropy_floor_ok = bool(entropies) and min(entropies) > 0.05
    zero_violations = all(str(row.get("validation_zero_violations", "True")).lower() == "true" for row in validation_rows)
    stable_keep = (
        math.isfinite(best_gain)
        and math.isfinite(final_gain)
        and math.isfinite(recent_floor)
        and final_gain >= best_gain - float(rollback_tolerance_pct)
        and recent_floor >= best_gain - float(rollback_tolerance_pct)
    )
    if (
        math.isfinite(best_gain)
        and best_gain >= float(threshold_pct)
        and stable_keep
        and recent_slope >= 0.0
        and finite_losses
        and kl_ok
        and zero_violations
        and entropy_floor_ok
    ):
        status = "G1_PASS"
    elif (math.isfinite(best_gain) and best_gain >= float(threshold_pct)) or not kl_ok:
        status = HALT_POLICY_UNSTABLE_V2
    else:
        status = HALT_LEARNER_NO_VALIDATION_GAIN_V2
    reason = (
        f"best_validation_gain={best_gain:.3f}%, final_validation_gain={final_gain:.3f}%, "
        f"recent_slope={recent_slope:.6g}, stable_keep={stable_keep}, finite_losses={finite_losses}, "
        f"kl_ok={kl_ok}, zero_violations={zero_violations}, entropy_floor_ok={entropy_floor_ok}"
    )
    return {
        "gate_status": status,
        "gate_reason": reason,
        "best_model_path": str(best_model_path),
        "update_count": len(update_rows),
        "validation_count": len(validation_rows),
        "best_validation_gain_pct_vs_initial": best_gain,
        "final_validation_gain_pct_vs_initial": final_gain,
        "recent_validation_gain_slope": recent_slope,
        "recent_validation_gain_floor": recent_floor,
        "stable_keep": stable_keep,
        "finite_losses": finite_losses,
        "approx_kl_ok": kl_ok,
        "max_approx_kl": max(kls) if kls else None,
        "entropy_floor_ok": entropy_floor_ok,
        "validation_zero_violations": zero_violations,
    }


def independent_test_overlap(args: argparse.Namespace) -> dict[str, Any]:
    test = set(_test_bundles(args))
    pilot22_train = {str(row.get("bundle")) for row in _read_csv(Path(args.pilot22_training_rows)) if row.get("bundle")}
    pilot22_validation = {str(row.get("bundle")) for row in _read_csv(Path(args.pilot22_validation_detail_rows)) if row.get("bundle")}
    stage_b_train = set(_stage_b_train_bundles(args))
    validation = set(_validation_bundles(args))
    overlaps = {
        "pilot22_train": sorted(test & pilot22_train),
        "pilot22_validation": sorted(test & pilot22_validation),
        "pilot23_stage_b_train": sorted(test & stage_b_train),
        "pilot23_validation": sorted(test & validation),
    }
    return {"overlap": any(overlaps.values()), "test_bundles": sorted(test), "overlaps": overlaps}


def linear_annealed_lr(*, initial_lr: float, final_lr: float, update_index: int, total_updates: int) -> float:
    if int(total_updates) <= 1:
        return float(final_lr)
    progress = min(max(float(update_index) / float(int(total_updates) - 1), 0.0), 1.0)
    return float(initial_lr) + (float(final_lr) - float(initial_lr)) * progress


def stabilization_fix_records() -> list[dict[str, str]]:
    return [
        {
            "fix": "PEAK_CHECKPOINT_INDEPENDENT_TEST",
            "symptom": "Pilot22 final checkpoint fell back to +2.4% after a +11.5% validation peak.",
            "source": "Standard NCO/RL practice selects checkpoints on validation and reports on a separate test set.",
            "change": "Pilot23 Stage A locates the Pilot22 validation peak checkpoint and evaluates it on non-overlapping independent test bundles/seeds.",
            "why_only_this": "It tests the cheapest explanation, checkpoint selection, before spending another training run.",
        },
        {
            "fix": "TARGET_KL_EARLY_STOP",
            "symptom": "Pilot22 gate failed because approx_kl exceeded the stability bound.",
            "source": "PPO implementations commonly stop update epochs when approximate KL crosses a target.",
            "change": "Pilot23 Stage B stops the current PPO update when minibatch approx_kl exceeds target_kl and logs the stop.",
            "why_only_this": "It directly limits the observed failure mode without changing the learned-destroy action space.",
        },
        {
            "fix": "LR_ANNEAL_SMALLER_CLIP_FEWER_EPOCHS",
            "symptom": "Pilot22 validation peaked and then regressed late in training.",
            "source": "PPO stabilization uses smaller updates via LR schedules, tighter clipping, and fewer epochs.",
            "change": "Pilot23 defaults to lr 1e-4 -> 1e-5, clip 0.1, and one PPO epoch while preserving POMO and 5/3/1/0 reward.",
            "why_only_this": "The reward/baseline fixes worked; this only reduces late destructive update size.",
        },
    ]


def _checkpoint_for_validation_row(row: dict[str, Any], checkpoint_dir: Path) -> Path | None:
    tag = str(row.get("tag", ""))
    if tag.startswith("update_"):
        return checkpoint_dir / f"pilot22_learned_destroy_{tag}.pt"
    if _is_number(row.get("update_index")):
        return checkpoint_dir / f"pilot22_learned_destroy_update_{int(row['update_index']) + 1:04d}.pt"
    return None


def _comparison_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    learned = [row for row in rows if row.get("algorithm") == "learned_destroy"]
    by_algo = {(row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0)): row for row in rows}
    improvements: list[float] = []
    random_improvements: list[float] = []
    worst_improvements: list[float] = []
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
    return {
        "avg_vs_operator": _mean(improvements),
        "min_scale_vs_operator": min((_mean(values) for values in by_scale.values()), default=math.nan),
        "avg_vs_random": _mean(random_improvements),
        "avg_vs_worst": _mean(worst_improvements),
        "zero_violations": all(int(row.get("violation_count", 1)) == 0 for row in learned),
        "worker_ok": all(_truthy(row.get("worker_integrity_ok", False)) for row in rows),
        "preserves_plus_10": _mean(improvements) >= 10.0 if improvements else False,
        "scale_improvement_pct": {scale: _mean(values) for scale, values in sorted(by_scale.items())},
        "row_count": len(rows),
    }


def _stage_a_status(summary: dict[str, Any], *, pass_threshold: float, train_threshold: float) -> str:
    if not summary["worker_ok"]:
        return "HALT_WORKER_INTEGRITY"
    if not summary["zero_violations"]:
        return HALT_INTEGRITY
    pass_conditions = (
        summary["avg_vs_operator"] >= float(pass_threshold)
        and summary["min_scale_vs_operator"] >= 0.0
        and summary["avg_vs_random"] > 0.0
        and summary["avg_vs_worst"] > 0.0
    )
    if pass_conditions:
        return PASS_CKPT_STATUS
    if summary["avg_vs_operator"] < float(train_threshold):
        return STAGEB_REQUIRED_STATUS
    return WEAK_CKPT_STATUS


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _save_best_validation_checkpoint(
    model_path: Path,
    metadata_path: Path,
    model: Any,
    validation_summary: dict[str, Any],
    *,
    update_index: int,
    group_index: int,
    reason: str,
) -> None:
    from .learned_destroy_policy import save_learned_destroy_policy

    metadata = best_validation_metadata(validation_summary, update_index=update_index, group_index=group_index, reason=reason)
    save_learned_destroy_policy(model_path, model, metadata=metadata)
    _write_json(metadata_path, metadata)


def best_validation_metadata(validation_summary: dict[str, Any], *, update_index: int, group_index: int, reason: str) -> dict[str, Any]:
    return {
        "reason": str(reason),
        "update_index": int(update_index),
        "group_index": int(group_index),
        "tag": str(validation_summary.get("tag", "")),
        "validation_mean_obj": float(validation_summary.get("validation_mean_obj")),
        "validation_gain_pct_vs_initial": float(validation_summary.get("validation_gain_pct_vs_initial") or 0.0),
        "validation_zero_violations": str(validation_summary.get("validation_zero_violations", "True")).lower() == "true",
    }


def _mean_metrics(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {"policy_loss": 0.0, "value_loss": 0.0, "entropy": 0.0, "approx_kl": 0.0, "clip_fraction": 0.0}
    keys = sorted({key for row in rows for key in row})
    return {key: _mean([float(row[key]) for row in rows if key in row]) for key in keys}


def _stage_b_train_bundles(args: argparse.Namespace) -> list[str]:
    explicit = _parse_list(args.stage_b_train_bundles)
    return explicit or list(DEFAULT_STAGE_B_TRAIN_BUNDLES)


def _validation_bundles(args: argparse.Namespace) -> list[str]:
    explicit = _parse_list(args.validation_bundles)
    return explicit or list(DEFAULT_VALIDATION_BUNDLES)


def _test_bundles(args: argparse.Namespace) -> list[str]:
    explicit = _parse_list(args.test_bundles)
    return explicit or list(DEFAULT_TEST_BUNDLES)


def _all_required_bundles(args: argparse.Namespace) -> list[str]:
    return sorted(set(_stage_b_train_bundles(args) + _validation_bundles(args) + _test_bundles(args)))


def _incomplete_bundles(bundles: list[str]) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for bundle in bundles:
        root = Path(bundle)
        bundle_missing = [name for name in _REQUIRED_BUNDLE_FILES if not (root / name).exists()]
        if bundle_missing:
            missing[str(bundle)] = bundle_missing
    return missing


def _initial_validation_mean(rows: list[dict[str, Any]]) -> float | None:
    for row in rows:
        if str(row.get("tag", "")) == "initial" and _is_number(row.get("validation_mean_obj")):
            return float(row["validation_mean_obj"])
    return None


def _best_validation_mean(rows: list[dict[str, Any]]) -> float | None:
    values = [float(row["validation_mean_obj"]) for row in rows if _is_number(row.get("validation_mean_obj"))]
    return min(values) if values else None


def _enforce_resume_guard(state: dict[str, Any], *, resume: bool) -> None:
    if not resume:
        return
    status = str(state.get("final_status", ""))
    guarded = {
        PASS_CKPT_STATUS,
        PASS_STATUS,
        WEAK_STATUS,
        WEAK_CKPT_STATUS,
        STAGEB_REQUIRED_STATUS,
        HALT_STATUS,
        HALT_INTEGRITY,
        HALT_TEST_SET_OVERLAP,
        HALT_POLICY_UNSTABLE_V2,
        HALT_LEARNER_NO_VALIDATION_GAIN_V2,
        "HALT_WORKER_INTEGRITY",
        "HALT_PREFLIGHT",
        "HALT_SELF_REPAIR_FAILED",
    }
    if status in guarded:
        raise Pilot23Halt("HALT_RESUME_GUARD", f"HALT_RESUME_GUARD: refusing to resume from conclusive Pilot23 state {status}; use --no-resume for a fresh run")


def _stage_done(state: dict[str, Any], stage: str) -> bool:
    order = ["stageA", "stageB", "stageC"]
    completed = str(state.get("completed_stage", ""))
    return completed in order and order.index(completed) >= order.index(stage)


def _check_wall(started: float, max_wall_seconds: int) -> None:
    if time.monotonic() - started > int(max_wall_seconds):
        raise Pilot23Halt("HALT_WALL_CLOCK", f"wall clock reached {max_wall_seconds}s")


def _require_output_dir(path: Path) -> None:
    if REPORT_ROOT_TOKEN not in path.as_posix():
        raise ValueError(f"Pilot23 outputs must stay under {REPORT_ROOT_TOKEN}")


def _write_report(path: Path, state: dict[str, Any]) -> None:
    status = str(state.get("final_status", "UNKNOWN"))
    reason = str(state.get("final_reason", ""))
    stage_a = state.get("stageA") or {}
    stage_b = state.get("stageB") or {}
    stage_c = state.get("stageC") or {}
    if status == PASS_CKPT_STATUS:
        next_step = "绿灯 Phase B：峰值 checkpoint 已在独立 test 上过闸，不需要再训 Pilot23。"
    elif status == PASS_STATUS:
        next_step = "绿灯 Phase B：稳定化重训后的 best-validation checkpoint 通过独立 test。"
    elif status in {WEAK_STATUS, WEAK_CKPT_STATUS}:
        next_step = "记录弱正结果，先看分规模和消融，再决定是否扩大全规模。"
    elif status == HALT_POLICY_UNSTABLE_V2:
        if stage_b.get("approx_kl_ok") and not stage_b.get("stable_keep"):
            next_step = "KL 已被 target-KL/LR/clip 稳住，但验证峰后保持未过闸；扩大前先复核 best-validation checkpoint 或调整稳定保持策略。"
        else:
            next_step = "target-KL/LR/clip 后仍不稳；继续降更新幅度或改 batch/优势估计前，不应扩大实验。"
    elif status == HALT_LEARNER_NO_VALIDATION_GAIN_V2:
        next_step = "稳定化后验证仍无足够 gain，learned-destroy 暂转 future-work 或换碳感知时刻旋钮。"
    elif status == HALT_STATUS:
        next_step = "G1 过后独立 test 仍打不过 operator-select，记录诚实负结果。"
    else:
        next_step = "先处理 HALT 原因，再决定是否新开实验。"
    stage_a_avg = stage_a.get("avg_vs_operator")
    stage_a_plus10 = stage_a.get("preserves_plus_10")
    preflight = state.get("preflight") or {}
    overlap = (preflight.get("independent_test_overlap") or {}) if isinstance(preflight, dict) else {}
    test_bundles = overlap.get("test_bundles") or []
    kl_line = (
        f"Stage B max_approx_kl={stage_b.get('max_approx_kl')}，approx_kl_ok={stage_b.get('approx_kl_ok')}，stable_keep={stage_b.get('stable_keep')}"
        if stage_b
        else "Stage B 未运行；KL 稳定化未验证，因为 Stage A 已直接结束或前置 HALT。"
    )
    lines = [
        "# Pilot23 Learned-Destroy Stabilization Report",
        "",
        f"Final verdict: `{status}`",
        f"Stop reason: {reason}",
        "",
        "## 人话结论",
        "",
        f"- 峰值 ckpt 独立 test：avg vs operator-select = {stage_a_avg}%，保没保住 +10% = {stage_a_plus10}；{stage_a.get('reason', 'Stage A 未完成')}",
        f"- 独立 test 集：{test_bundles}；与训练/验证重叠 = {overlap.get('overlap')}",
        f"- KL 稳没稳：{kl_line}",
        f"- 最终判级：`{status}`",
        f"- 下一步：{next_step}",
        f"- 跑到哪：{state.get('completed_stage', 'none')}；墙钟 {float(state.get('wall_time_seconds') or 0.0):.1f}s",
        "",
        "## 稳定化落地",
        "",
    ]
    for item in state.get("stabilization_fixes") or stabilization_fix_records():
        lines.append(f"- {item['fix']}：症状={item['symptom']}；出处={item['source']}；改哪={item['change']}；为什么只改这={item['why_only_this']}")
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "- `pilot23_preflight.json`",
            "- `pilot23_peak_checkpoint.json`",
            "- `pilot23_stageA_independent_test.csv`",
            "- `pilot23_update_log.csv`",
            "- `pilot23_validation_rows.csv`",
            "- `pilot23_phase_rows.csv`",
            "- `pilot23_report.json`",
        ]
    )
    if stage_b:
        lines.append("- `pilot23_best_validation_model.pt`")
        lines.append("- `pilot23_best_validation_metadata.json`")
    if stage_c:
        lines.append(f"- Stage C summary: {stage_c.get('reason')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _write_stage_a_skipped_marker(output_dir: Path, stage_a: dict[str, Any]) -> None:
    _write_csv(
        output_dir / "pilot23_stageA_independent_test.csv",
        [{"algorithm": "SKIPPED_STAGE_A", "evidence_role": "SKIPPED", "status": stage_a["gate_status"], "reason": stage_a["reason"]}],
    )


def _write_stage_b_skipped_marker(output_dir: Path, final_status: str, final_reason: str) -> None:
    path = output_dir / "pilot23_update_log.csv"
    if path.exists():
        return
    _write_csv(path, [{"update_index": -1, "status": str(final_status), "reason": str(final_reason), "evidence_role": "SKIPPED_STAGE_B"}])


def _write_stage_c_skipped_marker(output_dir: Path, final_status: str, final_reason: str) -> None:
    path = output_dir / "pilot23_phase_rows.csv"
    if path.exists():
        return
    _write_csv(path, [{"algorithm": "SKIPPED_STAGE_C", "evidence_role": "SKIPPED", "status": str(final_status), "reason": str(final_reason)}])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pilot23 learned-destroy checkpoint test and PPO stabilization")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    run_parser.add_argument("--worker-python", default=str(DEFAULT_WORKER))
    run_parser.add_argument("--resume", action="store_true", default=True)
    run_parser.add_argument("--no-resume", dest="resume", action="store_false")
    run_parser.add_argument("--max-wall-seconds", type=int, default=21600)
    run_parser.add_argument("--min-free-disk-gb", type=float, default=5.0)
    run_parser.add_argument("--seed", type=int, default=1)
    run_parser.add_argument("--pilot22-validation-rows", default=str(PILOT22_VALIDATION_ROWS))
    run_parser.add_argument("--pilot22-training-rows", default=str(PILOT22_TRAINING_ROWS))
    run_parser.add_argument("--pilot22-validation-detail-rows", default=str(PILOT22_VALIDATION_DETAIL_ROWS))
    run_parser.add_argument("--pilot22-checkpoint-dir", default=str(PILOT22_CHECKPOINT_DIR))
    run_parser.add_argument("--test-bundles", default="")
    run_parser.add_argument("--test-seeds", default="501,502,503")
    run_parser.add_argument("--stage-a-eval-budget", type=int, default=180)
    run_parser.add_argument("--stage-a-pass-threshold", type=float, default=5.0)
    run_parser.add_argument("--stage-a-train-threshold", type=float, default=2.0)
    run_parser.add_argument("--stage-b-train-bundles", default="")
    run_parser.add_argument("--stage-b-train-episodes", type=int, default=1000)
    run_parser.add_argument("--stage-b-eval-budget", type=int, default=120)
    run_parser.add_argument("--pomo-rollouts", type=int, default=4)
    run_parser.add_argument("--rollout-min-groups", type=int, default=1)
    run_parser.add_argument("--validation-bundles", default="")
    run_parser.add_argument("--validation-seeds", default="301")
    run_parser.add_argument("--validation-eval-budget", type=int, default=120)
    run_parser.add_argument("--validation-every-updates", type=int, default=10)
    run_parser.add_argument("--validation-gain-threshold", type=float, default=5.0)
    run_parser.add_argument("--validation-rollback-tolerance", type=float, default=3.0)
    run_parser.add_argument("--validation-recent-count", type=int, default=3)
    run_parser.add_argument("--checkpoint-every-updates", type=int, default=10)
    run_parser.add_argument("--stage-c-eval-budget", type=int, default=180)
    run_parser.add_argument("--stage-c-pass-threshold", type=float, default=2.0)
    run_parser.add_argument("--max-customers", type=int, default=128)
    run_parser.add_argument("--hidden-size", type=int, default=128)
    run_parser.add_argument("--learning-rate", type=float, default=1e-4)
    run_parser.add_argument("--final-learning-rate", type=float, default=1e-5)
    run_parser.add_argument("--ppo-epochs", type=int, default=1)
    run_parser.add_argument("--minibatch-size", type=int, default=64)
    run_parser.add_argument("--clip-range", type=float, default=0.1)
    run_parser.add_argument("--target-kl", type=float, default=0.08)
    run_parser.add_argument("--kl-ok-threshold", type=float, default=0.30)
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
