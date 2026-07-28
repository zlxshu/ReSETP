from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import time
from pathlib import Path
from typing import Any

from setp_instance_lab.build_curriculum_instances import (
    CurriculumSpec,
    DEFAULT_TEMPLATE_MANIFEST,
    build_config_for_spec,
    validate_generated_bundle,
    _load_template_config,
    _manifest_bundle_path,
)
from setp_instance_lab.generator import generate_scenario
from setp_instance_lab.io import write_scenario_bundle

from .pilot20_learned_destroy_phaseA import (
    DEFAULT_WORKER,
    REQUIRED_WORKER_NUMPY,
    PhaseAEpisode,
    _episode_row,
    _mean,
    _parse_int_list,
    _require_torch_available,
    _scale_label,
    run_learned_episode,
)
from .pilot21_learned_destroy_big import PASS_STATUS, REPORT_ROOT_TOKEN, WEAK_STATUS
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
from .pilot23_stabilize import (
    best_validation_metadata,
    linear_annealed_lr,
    ppo_update_learned_stable,
)


DEFAULT_OUTPUT_DIR = Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot24_data_generalization")
DEFAULT_GENERATED_ROOT = Path("models/data_bundle/generated_instances/pilot24_data_generalization")
PASS_STAGE0 = "G0_PASS"
PASS_STAGE1 = "G1_PASS"
HALT_INSUFFICIENT_DATA = "HALT_INSUFFICIENT_DATA"
HALT_NO_VALIDATION_GAIN = "HALT_NO_VALIDATION_GAIN"
HALT_POLICY_UNSTABLE = "HALT_POLICY_UNSTABLE_V3"
HALT_NO_GENERALIZATION = "HALT_NO_GENERALIZATION"
HALT_INTEGRITY = "HALT_INTEGRITY"
_REQUIRED_BUNDLE_FILES = ("instance.json", "distance_matrix.npy", "carbon_profile.csv", "nodes.csv", "scenario_manifest.json")
_BASE_IDS_25C = tuple(f"E-UK25_{idx:02d}" for idx in range(2, 21))


class Pilot24Halt(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = str(status)
        self.message = str(message)


def run(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    _require_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    progress_path = output_dir / "pilot24_progress.log"
    state_path = output_dir / "pilot24_state.json"
    state = _load_state(state_path) if args.resume else {}
    final_status = str(state.get("final_status", "RUNNING") or "RUNNING")
    final_reason = str(state.get("final_reason", "") or "")

    try:
        _enforce_resume_guard(state, resume=bool(args.resume))
        _log(progress_path, "Pilot24 start")
        preflight = run_preflight(args, output_dir)
        os.environ["SETP_WORKER_PYTHON"] = str(Path(args.worker_python).resolve())
        state["preflight"] = preflight
        state["data_fix_records"] = data_fix_records()
        _save_state(state_path, state)
        _write_json(output_dir / "pilot24_data_fix_records.json", state["data_fix_records"])

        if not _stage_done(state, "stage0"):
            _check_wall(started, args.max_wall_seconds)
            manifest = run_stage0(args, output_dir, progress_path)
            stage0 = summarize_stage0(manifest, min_train_count=int(args.min_train_bundles))
            state["data_manifest"] = manifest
            state["stage0"] = stage0
            state["completed_stage"] = "stage0"
            _save_state(state_path, state)
            _write_json(output_dir / "pilot24_stage0_summary.json", stage0)
            _log(progress_path, f"Stage0 verdict={stage0['gate_status']}: {stage0['gate_reason']}")
            if stage0["gate_status"] != PASS_STAGE0:
                raise Pilot24Halt(stage0["gate_status"], stage0["gate_reason"])

        if not _stage_done(state, "stage1"):
            _check_wall(started, args.max_wall_seconds)
            stage1 = run_stage1(args, output_dir, progress_path, state, started)
            state["stage1"] = stage1
            state["completed_stage"] = "stage1"
            _save_state(state_path, state)
            _write_json(output_dir / "pilot24_stage1_summary.json", stage1)
            _log(progress_path, f"Stage1 verdict={stage1['gate_status']}: {stage1['gate_reason']}")
            if stage1["gate_status"] != PASS_STAGE1:
                raise Pilot24Halt(stage1["gate_status"], stage1["gate_reason"])

        if not _stage_done(state, "stage2"):
            _check_wall(started, args.max_wall_seconds)
            rows = run_stage2(args, output_dir, progress_path, state)
            stage2 = summarize_stage2(rows, pass_threshold=float(args.stage2_pass_threshold))
            state["stage2"] = stage2
            state["completed_stage"] = "stage2"
            _save_state(state_path, state)
            _write_json(output_dir / "pilot24_stage2_summary.json", stage2)
            _log(progress_path, f"Stage2 verdict={stage2['status']}: {stage2['reason']}")

        final_status = str((state.get("stage2") or {}).get("status") or state.get("final_status") or "UNKNOWN")
        final_reason = str((state.get("stage2") or {}).get("reason") or state.get("final_reason") or "")
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        return 0 if final_status in {PASS_STATUS, WEAK_STATUS} else 2
    except Pilot24Halt as exc:
        final_status = exc.status
        final_reason = exc.message
        state["final_status"] = final_status
        state["final_reason"] = final_reason
        _write_stage2_skipped_marker(output_dir, final_status, final_reason)
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
        _write_json(output_dir / "pilot24_report.json", state)
        _write_report(output_dir / "pilot24_report.md", state)


def run_preflight(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    worker_python = Path(args.worker_python).resolve()
    if not worker_python.exists():
        raise Pilot24Halt("HALT_WORKER_INTEGRITY", f"py313 worker missing: {worker_python}")
    worker = _run_python_json(
        worker_python,
        "import json,sys,numpy; print(json.dumps({'exe':sys.executable,'version':sys.version.split()[0],'numpy':numpy.__version__}))",
    )
    if str(worker.get("numpy")) != REQUIRED_WORKER_NUMPY:
        raise Pilot24Halt("HALT_WORKER_INTEGRITY", f"worker NumPy drift: {worker.get('numpy')} != {REQUIRED_WORKER_NUMPY}")
    _require_torch_available()
    import torch

    if not torch.cuda.is_available():
        raise Pilot24Halt("HALT_PREFLIGHT", "py312 torch CUDA is not available")
    template = Path(args.template_manifest)
    if not template.exists():
        raise Pilot24Halt("HALT_PREFLIGHT", f"template manifest missing: {template}")
    usage = shutil.disk_usage(output_dir.resolve().anchor or ".")
    free_gb = float(usage.free) / (1024.0**3)
    if free_gb < float(args.min_free_disk_gb):
        raise Pilot24Halt("HALT_PREFLIGHT", f"free disk {free_gb:.1f}GB < {args.min_free_disk_gb}GB")
    preflight = {
        "worker": worker,
        "torch_version": str(torch.__version__),
        "cuda_available": True,
        "cuda_device": torch.cuda.get_device_name(0),
        "cuda_total_gb": float(torch.cuda.get_device_properties(0).total_memory) / (1024.0**3),
        "disk_free_gb": free_gb,
        "scale_customers": int(args.scale_customers),
        "generated_root": str(Path(args.generated_root)),
        "required_bundle_files": _REQUIRED_BUNDLE_FILES,
        "git": _git_snapshot(),
    }
    _write_json(output_dir / "pilot24_preflight.json", preflight)
    return preflight


def run_stage0(args: argparse.Namespace, output_dir: Path, progress_path: Path) -> dict[str, Any]:
    manifest_path = output_dir / "pilot24_data_manifest.json"
    if bool(args.resume) and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        validate_data_manifest(manifest)
        return manifest
    root = Path(".").resolve()
    output_root = Path(args.generated_root)
    template_config = _load_template_config(Path(args.template_manifest))
    rows: dict[str, list[dict[str, Any]]] = {"train": [], "val": [], "test": []}
    rejected: list[dict[str, Any]] = []
    attempts: dict[str, int] = {}
    split_targets = {
        "train": (int(args.train_bundle_count), int(args.train_seed_start)),
        "val": (int(args.val_bundle_count), int(args.val_seed_start)),
        "test": (int(args.test_bundle_count), int(args.test_seed_start)),
    }
    max_multiplier = max(1, int(args.stage0_max_attempt_multiplier))
    for split, (target_count, seed_start) in split_targets.items():
        max_attempts = max(target_count, target_count * max_multiplier)
        for index in range(max_attempts):
            if len(rows[split]) >= target_count:
                break
            spec = _spec_for_offset(seed_start, index, int(args.scale_customers))
            bundle_dir = output_root / spec.scenario_id
            if not bundle_dir.exists():
                _log(progress_path, f"Stage0 generate split={split} idx={index} scenario={spec.scenario_id}")
                scenario_config, manifest_config = build_config_for_spec(root, template_config, spec)
                scenario = generate_scenario(scenario_config)
                write_scenario_bundle(scenario, bundle_dir, config=manifest_config)
            try:
                bundle_manifest = validate_pilot24_bundle(bundle_dir, expected_n=spec.n_customers)
            except Exception as exc:  # Stage0 data repair: skip bad generated bundles and keep sampling.
                rejected_row = {
                    "split": split,
                    "path": _manifest_bundle_path(root, bundle_dir),
                    "scenario_id": spec.scenario_id,
                    "base_id": spec.base_id,
                    "seed": int(spec.seed),
                    "reason": str(exc),
                }
                rejected.append(rejected_row)
                _log(progress_path, f"Stage0 reject split={split} idx={index} scenario={spec.scenario_id}: {exc}")
                continue
            rows[split].append(
                {
                    "split": split,
                    "path": _manifest_bundle_path(root, bundle_dir),
                    "scenario_id": spec.scenario_id,
                    "base_id": spec.base_id,
                    "seed": int(spec.seed),
                    "n_customers": int(bundle_manifest["validation"]["customer_count"]),
                    "validation_passed": bool(bundle_manifest["validation"]["passed"]),
                }
            )
        attempts[split] = index + 1 if target_count else 0
        if len(rows[split]) < target_count:
            _write_json(output_dir / "pilot24_stage0_rejected_bundles.json", rejected)
            raise Pilot24Halt(
                HALT_INSUFFICIENT_DATA,
                f"Stage0 could only collect {len(rows[split])}/{target_count} valid {split} bundles after {max_attempts} attempts",
            )
    manifest = build_data_manifest(rows, scale_customers=int(args.scale_customers))
    manifest["generation_attempts"] = attempts
    manifest["rejected_bundles"] = rejected
    validate_data_manifest(manifest)
    _write_json(manifest_path, manifest)
    _write_json(output_dir / "pilot24_stage0_rejected_bundles.json", rejected)
    return manifest


def run_stage1(
    args: argparse.Namespace,
    output_dir: Path,
    progress_path: Path,
    state: dict[str, Any],
    started: float,
) -> dict[str, Any]:
    import torch
    from .learned_destroy_policy import make_learned_destroy_actor_critic, save_learned_destroy_policy, load_learned_destroy_policy

    manifest = state.get("data_manifest") or json.loads((output_dir / "pilot24_data_manifest.json").read_text(encoding="utf-8"))
    train_bundles = [str(row["path"]) for row in manifest["splits"]["train"]]
    total_groups = int(math.ceil(int(args.stage1_train_episodes) / max(1, int(args.pomo_rollouts))))
    if total_groups > len(train_bundles):
        raise Pilot24Halt(HALT_INSUFFICIENT_DATA, f"fresh-per-batch needs {total_groups} train bundles, got {len(train_bundles)}")
    train_schedule = list((state.get("stage1_progress") or {}).get("train_schedule") or [])
    if not train_schedule:
        rng = random.Random(int(args.seed))
        train_schedule = rng.sample(train_bundles, total_groups)

    model_path = output_dir / "pilot24_learned_destroy_model.pt"
    best_model_path = output_dir / "pilot24_best_validation_model.pt"
    checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    latest_checkpoint = _latest_checkpoint(checkpoint_dir)
    train_state = dict(state.get("stage1_progress") or {})
    if bool(args.resume) and latest_checkpoint is not None:
        model = load_learned_destroy_policy(latest_checkpoint)
        start_group = int(train_state.get("next_group", 0))
    else:
        model = make_learned_destroy_actor_critic(seed=int(args.seed), hidden_size=int(args.hidden_size))
        start_group = 0
    model.train()
    optimizer = torch.optim.Adam(model.parameters(), lr=float(args.learning_rate))
    update_rows = _read_csv(output_dir / "pilot24_update_log.csv") if args.resume else []
    episode_rows = _read_csv(output_dir / "pilot24_training_episode_log.csv") if args.resume else []
    validation_rows = _read_csv(output_dir / "pilot24_validation_rows.csv") if args.resume else []
    initial_validation_mean = _initial_validation_mean(validation_rows)
    best_validation_mean = _best_validation_mean(validation_rows)
    if initial_validation_mean is None:
        initial_summary = validate_policy(model, manifest["splits"]["val"], args, output_dir, progress_path, update_index=-1, tag="initial")
        validation_rows.append(initial_summary)
        _write_csv(output_dir / "pilot24_validation_rows.csv", validation_rows)
        initial_validation_mean = float(initial_summary["validation_mean_obj"])
        best_validation_mean = float(initial_summary["validation_mean_obj"])
        _save_best_validation_checkpoint(
            best_model_path,
            output_dir / "pilot24_best_validation_metadata.json",
            model,
            initial_summary,
            update_index=-1,
            group_index=-1,
            reason="initial_validation_baseline",
        )

    for group_index in range(start_group, total_groups):
        _check_wall(started, args.max_wall_seconds)
        bundle = train_schedule[group_index]
        group: list[PhaseAEpisode] = []
        for rollout_idx in range(int(args.pomo_rollouts)):
            episode_index = group_index * int(args.pomo_rollouts) + rollout_idx
            if episode_index >= int(args.stage1_train_episodes):
                break
            seed = int(args.seed) + episode_index
            episode = run_learned_episode(
                model,
                bundle,
                seed=seed,
                eval_budget=int(args.stage1_eval_budget),
                max_customers=int(args.max_customers),
                deterministic=False,
            )
            group.append(episode)
            row = _episode_row(episode)
            row["pomo_group"] = int(group_index)
            row["pomo_rollout"] = int(rollout_idx)
            row["fresh_bundle"] = str(bundle)
            episode_rows.append(row)
            _write_csv(output_dir / "pilot24_training_episode_log.csv", episode_rows)
        batch = flatten_pomo_shared_baseline([group])
        update_index = len(update_rows)
        lr = linear_annealed_lr(
            initial_lr=float(args.learning_rate),
            final_lr=float(args.final_learning_rate),
            update_index=update_index,
            total_updates=max(1, total_groups),
        )
        for param_group in optimizer.param_groups:
            param_group["lr"] = lr
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
                manifest["splits"]["val"],
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
            _write_csv(output_dir / "pilot24_validation_rows.csv", validation_rows)
            if best_validation_mean is None or float(validation_summary["validation_mean_obj"]) < float(best_validation_mean):
                best_validation_mean = float(validation_summary["validation_mean_obj"])
                _save_best_validation_checkpoint(
                    best_model_path,
                    output_dir / "pilot24_best_validation_metadata.json",
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
            "bundle": str(bundle),
            "episode_index": int(min((group_index + 1) * int(args.pomo_rollouts), int(args.stage1_train_episodes)) - 1),
            "pomo_rollouts": int(args.pomo_rollouts),
            "learning_rate": float(lr),
            "target_kl": float(args.target_kl),
            "best_checkpoint_saved": bool(best_checkpoint_saved),
            **metrics,
            **{key: validation_summary.get(key, "") for key in ("validation_mean_obj", "validation_gain_pct_vs_initial", "validation_zero_violations")},
        }
        update_rows.append(update_row)
        _write_csv(output_dir / "pilot24_update_log.csv", update_rows)
        _log(progress_path, f"Stage1 update {update_index} group={group_index} lr={lr:.6g} kl={metrics.get('approx_kl')} val_gain={update_row.get('validation_gain_pct_vs_initial')}")
        if (update_index + 1) % int(args.checkpoint_every_updates) == 0:
            ckpt = checkpoint_dir / f"pilot24_learned_destroy_update_{update_index + 1:04d}.pt"
            save_learned_destroy_policy(ckpt, model, metadata={"update_index": update_index, "group_index": group_index, "learning_rate": lr})
            _log(progress_path, f"Stage1 checkpoint {ckpt}")
        train_state["next_group"] = group_index + 1
        train_state["train_schedule"] = train_schedule
        state["stage1_progress"] = train_state
        _save_state(output_dir / "pilot24_state.json", state)

    final_validation = validate_policy(model, manifest["splits"]["val"], args, output_dir, progress_path, update_index=len(update_rows), tag="final")
    final_validation["validation_gain_pct_vs_initial"] = _improvement_pct(initial_validation_mean, float(final_validation["validation_mean_obj"]))
    validation_rows.append(final_validation)
    _write_csv(output_dir / "pilot24_validation_rows.csv", validation_rows)
    if best_validation_mean is None or float(final_validation["validation_mean_obj"]) < float(best_validation_mean):
        _save_best_validation_checkpoint(
            best_model_path,
            output_dir / "pilot24_best_validation_metadata.json",
            model,
            final_validation,
            update_index=len(update_rows),
            group_index=total_groups,
            reason="final_validation_mean_obj_improved",
        )
    save_learned_destroy_policy(model_path, model, metadata={"train_episodes": int(args.stage1_train_episodes), "pomo_rollouts": int(args.pomo_rollouts)})
    return summarize_stage1(
        update_rows,
        validation_rows,
        best_model_path,
        threshold_pct=float(args.validation_gain_threshold),
        rollback_tolerance_pct=float(args.validation_rollback_tolerance),
        kl_ok_threshold=float(args.kl_ok_threshold),
        recent_count=int(args.validation_recent_count),
        train_schedule=train_schedule,
    )


def validate_policy(
    model: Any,
    val_rows: list[dict[str, Any]],
    args: argparse.Namespace,
    output_dir: Path,
    progress_path: Path,
    *,
    update_index: int,
    tag: str,
) -> dict[str, Any]:
    rows_path = output_dir / "pilot24_validation_detail_rows.csv"
    detail_rows = _read_csv(rows_path)
    completed = {(row.get("tag"), row.get("bundle"), int(row.get("seed") or 0)) for row in detail_rows}
    current_rows = [row for row in detail_rows if row.get("tag") == tag]
    for row_spec in val_rows:
        bundle = str(row_spec["path"])
        for seed in _parse_int_list(args.validation_eval_seeds):
            key = (tag, bundle, int(seed))
            if key in completed:
                continue
            _log(progress_path, f"Stage1 validation {tag} bundle={bundle} seed={seed}")
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


def run_stage2(args: argparse.Namespace, output_dir: Path, progress_path: Path, state: dict[str, Any]) -> list[dict[str, Any]]:
    from .learned_destroy_policy import load_learned_destroy_policy

    manifest = state.get("data_manifest") or json.loads((output_dir / "pilot24_data_manifest.json").read_text(encoding="utf-8"))
    model_path = Path((state.get("stage1") or {}).get("best_model_path") or output_dir / "pilot24_best_validation_model.pt")
    model = load_learned_destroy_policy(model_path)
    rows_path = output_dir / "pilot24_independent_test.csv"
    rows = _read_csv(rows_path) if args.resume else []
    completed = {(row.get("algorithm"), row.get("bundle"), int(row.get("seed") or 0)) for row in rows}
    for row_spec in manifest["splits"]["test"]:
        bundle = str(row_spec["path"])
        for seed in _parse_int_list(args.test_eval_seeds):
            for algorithm in ("learned_destroy", "operator_select", "random_operator", "worst_removal_fixed"):
                key = (algorithm, bundle, int(seed))
                if key in completed:
                    continue
                _log(progress_path, f"Stage2 independent-test {algorithm} bundle={bundle} seed={seed}")
                row = _run_algorithm_row(
                    algorithm,
                    model,
                    bundle,
                    seed=int(seed),
                    eval_budget=int(args.stage2_eval_budget),
                    max_customers=int(args.max_customers),
                )
                row["evidence_role"] = "INDEPENDENT_TEST"
                rows.append(row)
                _write_csv(rows_path, rows)
    return rows


def make_split_specs(
    *,
    scale_customers: int,
    train_count: int,
    val_count: int,
    test_count: int,
    train_seed_start: int,
    val_seed_start: int,
    test_seed_start: int,
) -> dict[str, list[CurriculumSpec]]:
    if int(scale_customers) != 25:
        raise ValueError("Pilot24 default implementation supports the selected smallest scale: 25c")
    return {
        "train": _specs_for_range(train_seed_start, train_count, scale_customers),
        "val": _specs_for_range(val_seed_start, val_count, scale_customers),
        "test": _specs_for_range(test_seed_start, test_count, scale_customers),
    }


def summarize_stage0(manifest: dict[str, Any], *, min_train_count: int) -> dict[str, Any]:
    validation = validate_data_manifest(manifest)
    train_count = len(manifest["splits"]["train"])
    status = PASS_STAGE0 if train_count >= int(min_train_count) and validation["complete"] and not validation["overlap"] else HALT_INSUFFICIENT_DATA
    reason = (
        f"train_count={train_count}, min_train_count={min_train_count}, "
        f"val_count={len(manifest['splits']['val'])}, test_count={len(manifest['splits']['test'])}, "
        f"complete={validation['complete']}, overlap={validation['overlap']}, scale={manifest.get('scale_customers')}c"
    )
    return {"gate_status": status, "gate_reason": reason, **validation}


def summarize_stage1(
    update_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    best_model_path: Path,
    *,
    threshold_pct: float,
    rollback_tolerance_pct: float,
    kl_ok_threshold: float,
    recent_count: int,
    train_schedule: list[str],
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
    no_reuse = len(set(train_schedule)) == len(train_schedule)
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
        and no_reuse
    ):
        status = PASS_STAGE1
    elif (math.isfinite(best_gain) and best_gain >= float(threshold_pct)) or not kl_ok or not stable_keep:
        status = HALT_POLICY_UNSTABLE
    else:
        status = HALT_NO_VALIDATION_GAIN
    reason = (
        f"best_validation_gain={best_gain:.3f}%, final_validation_gain={final_gain:.3f}%, "
        f"recent_slope={recent_slope:.6g}, stable_keep={stable_keep}, finite_losses={finite_losses}, "
        f"kl_ok={kl_ok}, zero_violations={zero_violations}, entropy_floor_ok={entropy_floor_ok}, fresh_no_reuse={no_reuse}"
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
        "stable_keep": stable_keep,
        "finite_losses": finite_losses,
        "approx_kl_ok": kl_ok,
        "max_approx_kl": max(kls) if kls else None,
        "entropy_floor_ok": entropy_floor_ok,
        "validation_zero_violations": zero_violations,
        "fresh_no_reuse": no_reuse,
        "fresh_group_count": len(train_schedule),
    }


def summarize_stage2(rows: list[dict[str, Any]], *, pass_threshold: float) -> dict[str, Any]:
    summary = _comparison_summary(rows)
    if not summary["worker_ok"]:
        status = "HALT_WORKER_INTEGRITY"
    elif not summary["zero_violations"]:
        status = HALT_INTEGRITY
    elif summary["avg_vs_operator"] >= float(pass_threshold) and summary["avg_vs_random"] > 0.0 and summary["avg_vs_worst"] > 0.0:
        status = PASS_STATUS
    elif summary["avg_vs_operator"] > 0.0:
        status = WEAK_STATUS
    else:
        status = HALT_NO_GENERALIZATION
    reason = (
        f"avg_vs_operator={summary['avg_vs_operator']:.3f}%, avg_vs_random={summary['avg_vs_random']:.3f}%, "
        f"avg_vs_worst={summary['avg_vs_worst']:.3f}%, zero_violations={summary['zero_violations']}, worker_ok={summary['worker_ok']}"
    )
    return {"status": status, "reason": reason, **summary}


def build_data_manifest(rows: dict[str, list[dict[str, Any]]], *, scale_customers: int) -> dict[str, Any]:
    seeds = {split: [int(row["seed"]) for row in split_rows] for split, split_rows in rows.items()}
    paths = {split: [str(row["path"]) for row in split_rows] for split, split_rows in rows.items()}
    return {
        "schema_version": "pilot24-data-generalization.v1",
        "scale_customers": int(scale_customers),
        "splits": rows,
        "seed_ranges": {split: {"min": min(values), "max": max(values), "count": len(values)} for split, values in seeds.items()},
        "overlap": {
            "seed_overlap": _seed_overlap(seeds),
            "path_overlap": _path_overlap(paths),
        },
    }


def validate_data_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    required = {"train", "val", "test"}
    splits = manifest.get("splits")
    if not isinstance(splits, dict) or set(splits) != required:
        raise ValueError("pilot24 data manifest must contain train/val/test splits")
    all_rows = [row for split_rows in splits.values() for row in split_rows]
    incomplete = []
    invalid = []
    for row in all_rows:
        missing = _missing_bundle_files(Path(row["path"]))
        if missing:
            incomplete.append({"path": row["path"], "missing": missing})
        if row.get("validation_passed") is not True:
            invalid.append(row["path"])
    seed_overlap = _seed_overlap({split: [int(row["seed"]) for row in rows] for split, rows in splits.items()})
    path_overlap = _path_overlap({split: [str(row["path"]) for row in rows] for split, rows in splits.items()})
    return {
        "complete": not incomplete and not invalid,
        "overlap": bool(seed_overlap or path_overlap),
        "seed_overlap": seed_overlap,
        "path_overlap": path_overlap,
        "incomplete": incomplete,
        "invalid": invalid,
        "train_count": len(splits["train"]),
        "val_count": len(splits["val"]),
        "test_count": len(splits["test"]),
    }


def validate_pilot24_bundle(bundle_dir: Path, *, expected_n: int) -> dict[str, Any]:
    manifest = validate_generated_bundle(bundle_dir, expected_n=expected_n)
    missing = _missing_bundle_files(bundle_dir)
    if missing:
        raise FileNotFoundError(f"{bundle_dir}: missing {', '.join(missing)}")
    return manifest


def data_fix_records() -> list[dict[str, str]]:
    return [
        {
            "fix": "LARGE_SAME_SCALE_GENERATED_POOL",
            "symptom": "Pilot23 validation learned but independent cross-scale test failed.",
            "source": "Neural CO training relies on many same-distribution, same-scale generated instances.",
            "change": "Pilot24 generates train/val/test 25c pools by disjoint seed ranges with complete carbon bundles.",
            "why_only_this": "It removes the identified data cause without changing the learned-destroy algorithm.",
        },
        {
            "fix": "FRESH_PER_BATCH_POMO",
            "symptom": "Earlier pilots repeatedly trained on a tiny fixed set of bundles.",
            "source": "POMO-style training samples fresh problem instances per batch and uses grouped rollouts per instance.",
            "change": "Each Stage1 POMO group uses one unused train bundle and multiple rollouts on that bundle.",
            "why_only_this": "It preserves the stable PPO/reward stack while replacing the overfit data regime.",
        },
        {
            "fix": "SAME_SCALE_TEST",
            "symptom": "Pilot23 had to test 25c-trained policies on 50/100c bundles because old 25c test bundles were incomplete.",
            "source": "Generalization claims need independent test data from the intended distribution before cross-scale claims.",
            "change": "Pilot24 tests the best-validation checkpoint only on held-out generated 25c bundles.",
            "why_only_this": "This isolates data generalization from cross-scale extrapolation.",
        },
    ]


def _specs_for_range(seed_start: int, count: int, scale_customers: int) -> list[CurriculumSpec]:
    return [_spec_for_offset(seed_start, offset, scale_customers) for offset in range(int(count))]


def _spec_for_offset(seed_start: int, offset: int, scale_customers: int) -> CurriculumSpec:
    base_ids = _BASE_IDS_25C if int(scale_customers) == 25 else ()
    if not base_ids:
        raise ValueError(f"unsupported Pilot24 scale: {scale_customers}")
    seed = int(seed_start) + int(offset)
    base_id = base_ids[int(offset) % len(base_ids)]
    return CurriculumSpec(base_id, int(scale_customers), seed)


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
        "scale_improvement_pct": {scale: _mean(values) for scale, values in sorted(by_scale.items())},
        "row_count": len(rows),
    }


def _initial_validation_mean(rows: list[dict[str, Any]]) -> float | None:
    for row in rows:
        if str(row.get("tag", "")) == "initial" and _is_number(row.get("validation_mean_obj")):
            return float(row["validation_mean_obj"])
    return None


def _best_validation_mean(rows: list[dict[str, Any]]) -> float | None:
    values = [float(row["validation_mean_obj"]) for row in rows if _is_number(row.get("validation_mean_obj"))]
    return min(values) if values else None


def _missing_bundle_files(bundle: Path) -> list[str]:
    return [name for name in _REQUIRED_BUNDLE_FILES if not (bundle / name).is_file()]


def _seed_overlap(seeds: dict[str, list[int]]) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    for left, right in (("train", "val"), ("train", "test"), ("val", "test")):
        overlap = sorted(set(seeds[left]) & set(seeds[right]))
        if overlap:
            result[f"{left}_{right}"] = overlap
    return result


def _path_overlap(paths: dict[str, list[str]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for left, right in (("train", "val"), ("train", "test"), ("val", "test")):
        overlap = sorted(set(paths[left]) & set(paths[right]))
        if overlap:
            result[f"{left}_{right}"] = overlap
    return result


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _enforce_resume_guard(state: dict[str, Any], *, resume: bool) -> None:
    if not resume:
        return
    status = str(state.get("final_status", ""))
    guarded = {
        PASS_STATUS,
        WEAK_STATUS,
        HALT_INSUFFICIENT_DATA,
        HALT_NO_VALIDATION_GAIN,
        HALT_POLICY_UNSTABLE,
        HALT_NO_GENERALIZATION,
        HALT_INTEGRITY,
        "HALT_WORKER_INTEGRITY",
        "HALT_PREFLIGHT",
        "HALT_SELF_REPAIR_FAILED",
    }
    if status in guarded:
        raise Pilot24Halt("HALT_RESUME_GUARD", f"HALT_RESUME_GUARD: refusing to resume from conclusive Pilot24 state {status}; use --no-resume for a fresh run")


def _stage_done(state: dict[str, Any], stage: str) -> bool:
    order = ["stage0", "stage1", "stage2"]
    completed = str(state.get("completed_stage", ""))
    return completed in order and order.index(completed) >= order.index(stage)


def _check_wall(started: float, max_wall_seconds: int) -> None:
    if time.monotonic() - started > int(max_wall_seconds):
        raise Pilot24Halt("HALT_WALL_CLOCK", f"wall clock reached {max_wall_seconds}s")


def _require_output_dir(path: Path) -> None:
    if REPORT_ROOT_TOKEN not in path.as_posix():
        raise ValueError(f"Pilot24 outputs must stay under {REPORT_ROOT_TOKEN}")


def _write_stage2_skipped_marker(output_dir: Path, final_status: str, final_reason: str) -> None:
    path = output_dir / "pilot24_independent_test.csv"
    if path.exists():
        return
    _write_csv(path, [{"algorithm": "SKIPPED_STAGE2", "evidence_role": "SKIPPED", "status": str(final_status), "reason": str(final_reason)}])


def _write_report(path: Path, state: dict[str, Any]) -> None:
    status = str(state.get("final_status", "UNKNOWN"))
    reason = str(state.get("final_reason", ""))
    stage0 = state.get("stage0") or {}
    stage1 = state.get("stage1") or {}
    stage2 = state.get("stage2") or {}
    manifest = state.get("data_manifest") or {}
    if status == PASS_STATUS:
        next_step = "DR 留：同规模独立 test 已泛化，绿灯 Phase B。"
        dr_decision = "留"
    elif status == WEAK_STATUS:
        next_step = "弱正结果；DR 暂留作消融/小规模机制，不直接扩大。"
        dr_decision = "暂留"
    elif status == HALT_NO_GENERALIZATION:
        next_step = "数据做干净后仍不泛化，按用户拍板止损 DR，转 future-work。"
        dr_decision = "去"
    elif status in {HALT_NO_VALIDATION_GAIN, HALT_POLICY_UNSTABLE}:
        next_step = "数据修后 validation 闸未过，不进独立 test；DR 不再扩训，转 future-work。"
        dr_decision = "去"
    elif status == HALT_INSUFFICIENT_DATA:
        next_step = "样本池未达 G0，先补数据或降低目标规模，不做算法结论。"
        dr_decision = "未定"
    else:
        next_step = "先处理 HALT 原因，再决定 DR 去留。"
        dr_decision = "未定"
    lines = [
        "# Pilot24 Learned-Destroy Data Generalization Report",
        "",
        f"Final verdict: `{status}`",
        f"Stop reason: {reason}",
        "",
        "## 人话结论",
        "",
        f"- 样本够不够/干不干净：{stage0.get('gate_reason', 'Stage0 未完成')}",
        f"- 数据自修：跳过无效生成样本 {len(manifest.get('rejected_bundles', []))} 个；generation_attempts={manifest.get('generation_attempts', {})}",
        f"- 同规模 validation：{stage1.get('gate_reason', 'Stage1 未运行或未完成')}",
        f"- 同规模独立 test：{stage2.get('reason', 'Stage2 未运行或未完成')}",
        f"- 最终判级：`{status}`；DR 去留：{dr_decision}",
        f"- 下一步：{next_step}",
        f"- 跑到哪：{state.get('completed_stage', 'none')}；墙钟 {float(state.get('wall_time_seconds') or 0.0):.1f}s",
        "",
        "## 数据修落地",
        "",
    ]
    for item in state.get("data_fix_records") or data_fix_records():
        lines.append(f"- {item['fix']}：症状={item['symptom']}；出处={item['source']}；改哪={item['change']}；为什么只改这={item['why_only_this']}")
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "- `pilot24_data_manifest.json`",
            "- `pilot24_update_log.csv`",
            "- `pilot24_validation_rows.csv`",
            "- `pilot24_independent_test.csv`",
            "- `pilot24_report.json`",
            "- `pilot24_best_validation_model.pt`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pilot24 learned-destroy data generalization")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    run_parser.add_argument("--generated-root", default=str(DEFAULT_GENERATED_ROOT))
    run_parser.add_argument("--template-manifest", default=str(DEFAULT_TEMPLATE_MANIFEST))
    run_parser.add_argument("--worker-python", default=str(DEFAULT_WORKER))
    run_parser.add_argument("--resume", action="store_true", default=True)
    run_parser.add_argument("--no-resume", dest="resume", action="store_false")
    run_parser.add_argument("--max-wall-seconds", type=int, default=21600)
    run_parser.add_argument("--min-free-disk-gb", type=float, default=5.0)
    run_parser.add_argument("--seed", type=int, default=1)
    run_parser.add_argument("--scale-customers", type=int, default=25)
    run_parser.add_argument("--train-bundle-count", type=int, default=250)
    run_parser.add_argument("--val-bundle-count", type=int, default=30)
    run_parser.add_argument("--test-bundle-count", type=int, default=30)
    run_parser.add_argument("--min-train-bundles", type=int, default=200)
    run_parser.add_argument("--train-seed-start", type=int, default=24000)
    run_parser.add_argument("--val-seed-start", type=int, default=25000)
    run_parser.add_argument("--test-seed-start", type=int, default=26000)
    run_parser.add_argument("--stage0-max-attempt-multiplier", type=int, default=10)
    run_parser.add_argument("--stage1-train-episodes", type=int, default=1000)
    run_parser.add_argument("--stage1-eval-budget", type=int, default=120)
    run_parser.add_argument("--pomo-rollouts", type=int, default=4)
    run_parser.add_argument("--validation-eval-seeds", default="301")
    run_parser.add_argument("--validation-eval-budget", type=int, default=120)
    run_parser.add_argument("--validation-every-updates", type=int, default=25)
    run_parser.add_argument("--validation-gain-threshold", type=float, default=3.0)
    run_parser.add_argument("--validation-rollback-tolerance", type=float, default=3.0)
    run_parser.add_argument("--validation-recent-count", type=int, default=3)
    run_parser.add_argument("--checkpoint-every-updates", type=int, default=25)
    run_parser.add_argument("--test-eval-seeds", default="901")
    run_parser.add_argument("--stage2-eval-budget", type=int, default=120)
    run_parser.add_argument("--stage2-pass-threshold", type=float, default=2.0)
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
