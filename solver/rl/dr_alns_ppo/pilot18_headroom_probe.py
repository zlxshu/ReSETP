from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import time
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from .action_space import (
    ALPHA_UCB_CHOICE,
    BLOCK_CANDIDATE_GENERATOR_CHOICES,
    BLOCK_DESTROY_IDS,
    BLOCK_EXPLORATION_RATIOS,
    BLOCK_Q_RATIOS,
    BLOCK_REPAIR_IDS,
    BLOCK_SEARCH_CONTROL_CHOICES,
    BLOCK_THRESHOLD_RATIOS,
    block_action_nvecs,
)
from .async_block_policy import BlockActorCritic, load_async_block_policy
from .baselines import normalize_result_row, solution_signature_hash
from .block_env import BlockAlnsEnv
from .pilot08_eval_tools import DEFAULT_WORKER, REQUIRED_NUMPY, run_sa_row
from . import pilot17_allscale_eval_tools as p17


PILOT18_DIR = Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot18")
PILOT17_COMPARISON_ROWS = p17.PILOT17_DIR / "pilot17_comparison_rows.csv"

EVAL_BUDGET = 20
BLOCK_SIZE = 4
SEEDS = (1, 2, 3)
BUDGET_MULTIPLIERS = (1, 4, 16)
MAX_RUNTIME_SECONDS = 1200.0
BEST_STATIC_META = (0.40, 0.0025, 0.15)
EXPECTED_DR_ACTION_NVEC = (7, 4, 5, 4, 4, 4, 3)

BASELINE_ALGORITHMS = ("winner_static_meta", "scikit-opt-SA")

RUN_ROW_FIELDS = [
    "algorithm",
    "bundle",
    "bundle_id",
    "scale",
    "seed",
    "budget_multiplier",
    "eval_budget",
    "best_obj",
    "actual_evals",
    "candidate_scores",
    "repair_delta_count",
    "violation_count",
    "feasible",
    "wall_clock_capped",
    "budget_reached",
    "elapsed_seconds",
    "runtime_target_seconds",
    "worker_python_executable",
    "worker_python_version",
    "worker_numpy_version",
    "solution_signature_hash",
    "operator_base_id",
    "control_mode",
    "operator_counts",
    "destroy_counts",
    "repair_counts",
    "q_ratio_counts",
    "meta_q_ratio",
    "meta_threshold_ratio",
    "meta_exploration_ratio",
]

HEADROOM_FIELDS = [
    "scale",
    "bundle",
    "bundle_id",
    "seed",
    "obj_B",
    "obj_4B",
    "obj_16B",
    "best_obj_extended",
    "headroom_pct",
    "algorithm_at_B",
    "algorithm_at_4B",
    "algorithm_at_16B",
    "wall_clock_capped_B",
    "wall_clock_capped_4B",
    "wall_clock_capped_16B",
    "runtime_seconds_B",
    "runtime_seconds_4B",
    "runtime_seconds_16B",
    "actual_evals_B",
    "actual_evals_4B",
    "actual_evals_16B",
    "violation_B",
    "violation_4B",
    "violation_16B",
    "worker_B",
    "numpy_B",
]

SCALE_SUMMARY_FIELDS = [
    "scale",
    "bundle_id",
    "seed_count",
    "mean_headroom_pct",
    "min_headroom_pct",
    "max_headroom_pct",
    "mean_late_gain_after_dr_stop_pct",
    "mean_dr_eval_fraction",
    "dr_early_stop_seed_count",
    "capped_seed_count",
    "verdict",
]

TRAJECTORY_FIELDS = [
    "algorithm",
    "bundle",
    "bundle_id",
    "scale",
    "seed",
    "budget_multiplier",
    "eval_budget",
    "step_index",
    "actual_evals",
    "best_obj",
    "current_obj",
    "candidate_obj",
    "reward",
    "elapsed_seconds",
    "wall_clock_capped",
    "violation_count",
    "feasible",
    "action_destroy",
    "action_repair",
    "action_q",
    "action_threshold",
    "action_exploration",
    "action_candidate_generator",
    "action_search_control",
    "requested_destroy",
    "requested_repair",
    "requested_q_ratio",
    "requested_threshold_ratio",
    "requested_exploration_ratio",
    "requested_candidate_generator",
    "requested_search_control",
    "search_control_stop_requested",
    "block_best_delta",
    "block_current_delta",
    "block_improved_best_count",
    "block_improved_current_count",
    "block_accepted_count",
    "block_rejected_count",
    "worker_python_executable",
    "worker_python_version",
    "worker_numpy_version",
    "pilot17_best_obj",
    "pilot17_actual_evals",
]


def budget_values(base_budget: int = EVAL_BUDGET, multipliers: tuple[int, ...] = BUDGET_MULTIPLIERS) -> list[int]:
    return [int(base_budget) * int(multiplier) for multiplier in multipliers]


def select_representative_bundles(bundles: list[str]) -> list[str]:
    selected = p17.selection_bundles(bundles)
    expected_scales = [50, 75, 100, 150, 200]
    actual_scales = [p17.scale_from_bundle(bundle) for bundle in selected]
    if actual_scales != expected_scales:
        raise RuntimeError(f"HALT_BUNDLE: expected representative scales {expected_scales}, got {actual_scales}")
    return selected


def static_meta_action_tuple(
    *,
    q_ratio: float = BEST_STATIC_META[0],
    threshold_ratio: float = BEST_STATIC_META[1],
    exploration_ratio: float = BEST_STATIC_META[2],
) -> tuple[int, int, int, int, int]:
    return (
        BLOCK_DESTROY_IDS.index(ALPHA_UCB_CHOICE),
        BLOCK_REPAIR_IDS.index(ALPHA_UCB_CHOICE),
        _nearest_index(BLOCK_Q_RATIOS, q_ratio),
        _nearest_index(BLOCK_THRESHOLD_RATIOS, threshold_ratio),
        _nearest_index(BLOCK_EXPLORATION_RATIOS, exploration_ratio),
    )


def headroom_pct(obj_at_b: float, best_extended_obj: float) -> float:
    if not math.isfinite(float(obj_at_b)) or abs(float(obj_at_b)) <= 1e-12:
        return math.nan
    return (float(obj_at_b) - float(best_extended_obj)) / float(obj_at_b) * 100.0


def classify_scale_verdict(
    *,
    mean_headroom_pct: float,
    mean_late_gain_after_dr_stop_pct: float,
    mean_dr_eval_fraction: float,
) -> str:
    if math.isfinite(mean_headroom_pct) and mean_headroom_pct > 10.0:
        return "VERDICT_ROOM_EXISTS"
    if (
        math.isfinite(mean_late_gain_after_dr_stop_pct)
        and mean_late_gain_after_dr_stop_pct >= 0.5
        and math.isfinite(mean_dr_eval_fraction)
        and mean_dr_eval_fraction <= 0.60
    ):
        return "VERDICT_DR_INTERFACE_GAP"
    if math.isfinite(mean_headroom_pct) and mean_headroom_pct < 3.0:
        return "VERDICT_NO_HEADROOM"
    return "VERDICT_MODEST_ROOM"


def classify_overall_verdict(scale_rows: list[dict[str, Any]]) -> str:
    verdicts = {str(row.get("verdict")) for row in scale_rows}
    if "VERDICT_ROOM_EXISTS" in verdicts:
        return "VERDICT_ROOM_EXISTS"
    if "VERDICT_DR_INTERFACE_GAP" in verdicts:
        return "VERDICT_DR_INTERFACE_GAP"
    if verdicts and verdicts == {"VERDICT_NO_HEADROOM"}:
        return "VERDICT_NO_HEADROOM"
    return "VERDICT_MODEST_ROOM"


def late_gain_after_dr_stop(
    trajectory_rows: list[dict[str, Any]],
    *,
    bundle: str,
    seed: int,
    dr_actual_evals: int,
    final_obj: float,
) -> float:
    rows = [
        row
        for row in trajectory_rows
        if str(row.get("algorithm")) == "winner_static_meta"
        and str(row.get("bundle")) == str(bundle)
        and int(row.get("seed") or -1) == int(seed)
        and int(row.get("budget_multiplier") or 0) == 1
    ]
    if not rows or int(dr_actual_evals) <= 0:
        return math.nan
    rows.sort(key=lambda row: (int(row.get("actual_evals") or 0), int(row.get("step_index") or 0)))
    at_stop = None
    for row in rows:
        if int(row.get("actual_evals") or 0) >= int(dr_actual_evals):
            at_stop = row
            break
    if at_stop is None:
        at_stop = rows[-1]
    obj_at_stop = float(at_stop.get("best_obj"))
    if abs(obj_at_stop) <= 1e-12:
        return math.nan
    return max(0.0, (obj_at_stop - float(final_obj)) / obj_at_stop * 100.0)


def ensure_environment() -> None:
    configured = os.environ.get("SETP_WORKER_PYTHON")
    if configured and str(Path(configured).resolve()) != str(Path(DEFAULT_WORKER).resolve()):
        raise RuntimeError(
            "HALT_ENV: SETP_WORKER_PYTHON must point to "
            f"{DEFAULT_WORKER}, got {configured}"
        )
    os.environ["SETP_WORKER_PYTHON"] = DEFAULT_WORKER
    if not Path(DEFAULT_WORKER).is_file():
        raise RuntimeError(f"HALT_ENV: missing worker interpreter {DEFAULT_WORKER}")
    actual_nvec = block_action_nvecs(candidate_generator_mode=True, search_control_mode=True)
    if tuple(actual_nvec) != EXPECTED_DR_ACTION_NVEC:
        raise RuntimeError(f"HALT_ENV: action_nvec mismatch expected {EXPECTED_DR_ACTION_NVEC}, got {actual_nvec}")


def run_winner_static_meta_row(
    *,
    bundle: str,
    seed: int,
    eval_budget: int,
    block_size: int,
    budget_multiplier: int,
    max_runtime_seconds: float,
    collect_trace: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    action = static_meta_action_tuple()
    started = time.perf_counter()
    env = BlockAlnsEnv(bundle, seed=int(seed), eval_budget=int(eval_budget), block_size=int(block_size))
    trace_rows: list[dict[str, Any]] = []
    destroy_counts: dict[str, int] = {}
    repair_counts: dict[str, int] = {}
    q_counts: dict[str, int] = {}
    capped = False
    try:
        obs, _info = env.reset(seed=int(seed))
        terminated = False
        truncated = False
        step_idx = 0
        best_response = env.last_response or {}
        last_info = env.last_response or {}
        while not (terminated or truncated):
            if time.perf_counter() - started >= float(max_runtime_seconds):
                capped = True
                break
            next_obs, reward, terminated, truncated, step_info = env.step(action)
            elapsed = time.perf_counter() - started
            trace = dict(step_info.get("trace", {}) or {})
            _inc(destroy_counts, str(trace.get("block_requested_destroy_id") or trace.get("destroy_id") or ""))
            _inc(repair_counts, str(trace.get("block_requested_repair_id") or trace.get("repair_id") or ""))
            q_value = trace.get("block_requested_q_ratio", trace.get("q_ratio"))
            if q_value not in (None, ""):
                _inc(q_counts, f"{float(q_value):.6f}")
            if collect_trace:
                trace_rows.append(
                    build_trajectory_row(
                        algorithm="winner_static_meta",
                        bundle=bundle,
                        seed=seed,
                        budget_multiplier=budget_multiplier,
                        eval_budget=eval_budget,
                        step_index=step_idx + 1,
                        action=action,
                        reward=reward,
                        info=step_info,
                        elapsed_seconds=elapsed,
                        wall_clock_capped=False,
                    )
                )
            if float(step_info.get("best_obj", float("inf"))) <= float(best_response.get("best_obj", float("inf"))) + 1e-9:
                best_response = step_info
            obs = next_obs
            last_info = step_info
            step_idx += 1
            if elapsed >= float(max_runtime_seconds) and not terminated:
                capped = True
                break
        elapsed = time.perf_counter() - started
        if trace_rows and capped:
            trace_rows[-1]["wall_clock_capped"] = 1
        row = normalize_result_row(
            {
                "algorithm": "winner_static_meta",
                "bundle": bundle,
                "seed": int(seed),
                "eval_budget": int(eval_budget),
                "best_obj": float(last_info.get("best_obj", best_response.get("best_obj", 0.0))),
                "actual_evals": int(last_info.get("actual_evals", 0)),
                "candidate_scores": int(last_info.get("candidate_scores", 0)),
                "repair_delta_count": int(last_info.get("repair_delta_count", 0)),
                "operator_base_id": str((last_info.get("trace", {}) or {}).get("operator_base_id", "")),
                "control_mode": str((last_info.get("trace", {}) or {}).get("control_mode", "")),
                "violation_count": int(best_response.get("violation_count", 1)),
                "feasible": int(best_response.get("violation_count", 1)) == 0,
                "solution_signature_hash": solution_signature_hash(best_response.get("solution", {})),
                "operator_counts": {},
                "destroy_counts": destroy_counts,
                "repair_counts": repair_counts,
                "q_ratio_counts": q_counts,
                "worker_python_executable": str((last_info.get("trace", {}) or {}).get("worker_python_executable", "")),
                "worker_python_version": str((last_info.get("trace", {}) or {}).get("worker_python_version", "")),
                "worker_numpy_version": str((last_info.get("trace", {}) or {}).get("worker_numpy_version", "")),
            }
        )
        return extend_run_row(
            row,
            budget_multiplier=budget_multiplier,
            elapsed_seconds=elapsed,
            runtime_target_seconds=max_runtime_seconds,
            wall_clock_capped=capped or int(row["actual_evals"]) < int(eval_budget),
        ), trace_rows
    finally:
        env.close()


def run_sa_probe_row(
    *,
    bundle: str,
    seed: int,
    eval_budget: int,
    budget_multiplier: int,
    max_runtime_seconds: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    row = run_sa_row(
        bundle=bundle,
        seed=int(seed),
        eval_budget=int(eval_budget),
        max_runtime_seconds=float(max_runtime_seconds),
        bundle_role="pilot18_headroom",
        required_python=DEFAULT_WORKER,
    )
    elapsed = float(row.get("elapsed_seconds") or (time.perf_counter() - started))
    row["algorithm"] = "scikit-opt-SA"
    return extend_run_row(
        normalize_result_row(row),
        budget_multiplier=budget_multiplier,
        elapsed_seconds=elapsed,
        runtime_target_seconds=max_runtime_seconds,
        wall_clock_capped=int(row.get("actual_evals") or 0) < int(eval_budget),
    )


def replay_dr_trace(
    *,
    model: BlockActorCritic,
    bundle: str,
    seed: int,
    eval_budget: int,
    block_size: int,
    max_runtime_seconds: float,
    pilot17_row: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    model.eval()
    candidate_generator_mode, search_control_mode = p17.infer_block_modes(model)
    actual_nvec = tuple(int(value) for value in model.action_nvec)
    if actual_nvec != EXPECTED_DR_ACTION_NVEC:
        raise RuntimeError(f"HALT_ENV: Pilot16 final model action_nvec mismatch: {actual_nvec}")
    started = time.perf_counter()
    env = BlockAlnsEnv(
        bundle,
        seed=int(seed),
        eval_budget=int(eval_budget),
        block_size=int(block_size),
        candidate_generator_mode=candidate_generator_mode,
        search_control_mode=search_control_mode,
    )
    rows: list[dict[str, Any]] = []
    try:
        obs, info = env.reset(seed=int(seed))
        terminated = False
        truncated = False
        step_idx = 0
        while not (terminated or truncated):
            if time.perf_counter() - started >= float(max_runtime_seconds):
                break
            decision = model.act(obs, deterministic=True, masks=info.get("action_mask"))
            action = tuple(int(value) for value in np.asarray(decision["action"], dtype=np.int64).tolist())
            obs, reward, terminated, truncated, info = env.step(action)
            elapsed = time.perf_counter() - started
            rows.append(
                build_trajectory_row(
                    algorithm="dr_pilot16_final_replay",
                    bundle=bundle,
                    seed=seed,
                    budget_multiplier=1,
                    eval_budget=eval_budget,
                    step_index=step_idx + 1,
                    action=action,
                    reward=reward,
                    info=info,
                    elapsed_seconds=elapsed,
                    wall_clock_capped=elapsed >= float(max_runtime_seconds) and not terminated,
                    pilot17_row=pilot17_row,
                )
            )
            step_idx += 1
        return rows
    finally:
        env.close()


def build_trajectory_row(
    *,
    algorithm: str,
    bundle: str,
    seed: int,
    budget_multiplier: int,
    eval_budget: int,
    step_index: int,
    action: tuple[int, ...],
    reward: float,
    info: dict[str, Any],
    elapsed_seconds: float,
    wall_clock_capped: bool,
    pilot17_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trace = dict(info.get("trace", {}) or {})
    padded = list(action) + ["", ""]
    return {
        "algorithm": algorithm,
        "bundle": bundle,
        "bundle_id": Path(bundle).name,
        "scale": p17.scale_from_bundle(bundle),
        "seed": int(seed),
        "budget_multiplier": int(budget_multiplier),
        "eval_budget": int(eval_budget),
        "step_index": int(step_index),
        "actual_evals": int(info.get("actual_evals") or 0),
        "best_obj": float(info.get("best_obj", 0.0) or 0.0),
        "current_obj": float(info.get("current_obj", 0.0) or 0.0),
        "candidate_obj": float(info.get("candidate_obj", 0.0) or 0.0),
        "reward": float(reward),
        "elapsed_seconds": float(elapsed_seconds),
        "wall_clock_capped": int(bool(wall_clock_capped)),
        "violation_count": int(info.get("violation_count") or 0),
        "feasible": int(info.get("violation_count") or 0) == 0,
        "action_destroy": padded[0],
        "action_repair": padded[1],
        "action_q": padded[2],
        "action_threshold": padded[3],
        "action_exploration": padded[4],
        "action_candidate_generator": padded[5],
        "action_search_control": padded[6],
        "requested_destroy": str(trace.get("block_requested_destroy_id") or trace.get("destroy_id") or ""),
        "requested_repair": str(trace.get("block_requested_repair_id") or trace.get("repair_id") or ""),
        "requested_q_ratio": _blank_or_float(trace.get("block_requested_q_ratio", trace.get("q_ratio"))),
        "requested_threshold_ratio": _blank_or_float(trace.get("block_requested_threshold_ratio", trace.get("threshold_ratio"))),
        "requested_exploration_ratio": _blank_or_float(trace.get("block_requested_exploration_ratio", trace.get("exploration_ratio"))),
        "requested_candidate_generator": str(trace.get("block_requested_candidate_generator", "default") or "default"),
        "requested_search_control": str(trace.get("search_control", "continue") or "continue"),
        "search_control_stop_requested": int(bool(trace.get("search_control_stop_requested"))),
        "block_best_delta": _blank_or_float(trace.get("block_best_delta")),
        "block_current_delta": _blank_or_float(trace.get("block_current_delta")),
        "block_improved_best_count": _blank_or_int(trace.get("block_improved_best_count")),
        "block_improved_current_count": _blank_or_int(trace.get("block_improved_current_count")),
        "block_accepted_count": _blank_or_int(trace.get("block_accepted_count")),
        "block_rejected_count": _blank_or_int(trace.get("block_rejected_count")),
        "worker_python_executable": str(trace.get("worker_python_executable", "")),
        "worker_python_version": str(trace.get("worker_python_version", "")),
        "worker_numpy_version": str(trace.get("worker_numpy_version", "")),
        "pilot17_best_obj": "" if pilot17_row is None else float(pilot17_row.get("best_obj") or math.nan),
        "pilot17_actual_evals": "" if pilot17_row is None else int(pilot17_row.get("actual_evals") or 0),
    }


def extend_run_row(
    row: dict[str, Any],
    *,
    budget_multiplier: int,
    elapsed_seconds: float,
    runtime_target_seconds: float,
    wall_clock_capped: bool,
) -> dict[str, Any]:
    out = dict(row)
    out.update(
        {
            "bundle_id": Path(str(row["bundle"])).name,
            "scale": p17.scale_from_bundle(str(row["bundle"])),
            "budget_multiplier": int(budget_multiplier),
            "elapsed_seconds": float(elapsed_seconds),
            "runtime_target_seconds": float(runtime_target_seconds),
            "wall_clock_capped": int(bool(wall_clock_capped)),
            "budget_reached": int(int(row.get("actual_evals") or 0) >= int(row.get("eval_budget") or 0)),
            "meta_q_ratio": BEST_STATIC_META[0] if str(row.get("algorithm")) == "winner_static_meta" else "",
            "meta_threshold_ratio": BEST_STATIC_META[1] if str(row.get("algorithm")) == "winner_static_meta" else "",
            "meta_exploration_ratio": BEST_STATIC_META[2] if str(row.get("algorithm")) == "winner_static_meta" else "",
        }
    )
    return out


def row_gate_issues(row: dict[str, Any], *, expected_budget: int) -> list[str]:
    issues: list[str] = []
    worker = str(Path(str(row.get("worker_python_executable", ""))).resolve())
    if worker != str(Path(DEFAULT_WORKER).resolve()):
        issues.append("worker_python")
    if str(row.get("worker_numpy_version")) != REQUIRED_NUMPY:
        issues.append("worker_numpy")
    if int(row.get("violation_count") or 0) != 0 or not _bool(row.get("feasible")):
        issues.append("feasibility")
    if not math.isfinite(float(row.get("best_obj", math.nan))):
        issues.append("best_obj")
    if float(row.get("elapsed_seconds") or 0.0) <= 0.0:
        issues.append("elapsed_seconds")
    actual = int(row.get("actual_evals") or 0)
    if actual <= 0 or actual > int(expected_budget):
        issues.append("actual_evals_range")
    return issues


def integrity_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures = []
    capped = []
    for row in rows:
        issues = row_gate_issues(row, expected_budget=int(row.get("eval_budget") or 0))
        if issues:
            failures.append({"row": run_row_id(row), "issues": issues})
        if _bool(row.get("wall_clock_capped")):
            capped.append(
                {
                    "row": run_row_id(row),
                    "actual_evals": int(row.get("actual_evals") or 0),
                    "eval_budget": int(row.get("eval_budget") or 0),
                }
            )
    return {
        "ok": not failures,
        "row_count": len(rows),
        "failures": failures,
        "wall_clock_capped_count": len(capped),
        "wall_clock_capped_rows": capped[:30],
    }


def build_headroom_rows(rows: list[dict[str, Any]], *, base_budget: int) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_key[(str(row["bundle"]), int(row["seed"]), int(row["eval_budget"]))].append(row)
    out: list[dict[str, Any]] = []
    budgets = budget_values(base_budget)
    for bundle in sorted({str(row["bundle"]) for row in rows}, key=lambda value: (p17.scale_from_bundle(value), value)):
        for seed in sorted({int(row["seed"]) for row in rows if str(row["bundle"]) == bundle}):
            winners: dict[int, dict[str, Any]] = {}
            for budget in budgets:
                candidates = by_key.get((bundle, seed, budget), [])
                if not candidates:
                    continue
                winners[budget] = min(candidates, key=lambda row: float(row["best_obj"]))
            if not all(budget in winners for budget in budgets):
                continue
            row_b = winners[base_budget]
            row_4b = winners[base_budget * 4]
            row_16b = winners[base_budget * 16]
            best_extended = min(float(row_4b["best_obj"]), float(row_16b["best_obj"]))
            out.append(
                {
                    "scale": p17.scale_from_bundle(bundle),
                    "bundle": bundle,
                    "bundle_id": Path(bundle).name,
                    "seed": seed,
                    "obj_B": float(row_b["best_obj"]),
                    "obj_4B": float(row_4b["best_obj"]),
                    "obj_16B": float(row_16b["best_obj"]),
                    "best_obj_extended": best_extended,
                    "headroom_pct": headroom_pct(float(row_b["best_obj"]), best_extended),
                    "algorithm_at_B": row_b["algorithm"],
                    "algorithm_at_4B": row_4b["algorithm"],
                    "algorithm_at_16B": row_16b["algorithm"],
                    "wall_clock_capped_B": int(_bool(row_b.get("wall_clock_capped"))),
                    "wall_clock_capped_4B": int(_bool(row_4b.get("wall_clock_capped"))),
                    "wall_clock_capped_16B": int(_bool(row_16b.get("wall_clock_capped"))),
                    "runtime_seconds_B": float(row_b.get("elapsed_seconds") or 0.0),
                    "runtime_seconds_4B": float(row_4b.get("elapsed_seconds") or 0.0),
                    "runtime_seconds_16B": float(row_16b.get("elapsed_seconds") or 0.0),
                    "actual_evals_B": int(row_b.get("actual_evals") or 0),
                    "actual_evals_4B": int(row_4b.get("actual_evals") or 0),
                    "actual_evals_16B": int(row_16b.get("actual_evals") or 0),
                    "violation_B": int(row_b.get("violation_count") or 0),
                    "violation_4B": int(row_4b.get("violation_count") or 0),
                    "violation_16B": int(row_16b.get("violation_count") or 0),
                    "worker_B": row_b.get("worker_python_executable", ""),
                    "numpy_B": row_b.get("worker_numpy_version", ""),
                }
            )
    return out


def build_scale_summary(
    headroom_rows: list[dict[str, Any]],
    trajectory_rows: list[dict[str, Any]],
    pilot17_rows: list[dict[str, Any]],
    *,
    base_budget: int,
) -> list[dict[str, Any]]:
    p17_index = {
        (str(row.get("bundle")), int(row.get("seed") or -1)): row
        for row in pilot17_rows
        if str(row.get("algorithm")) == "ppo_block_best"
    }
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in headroom_rows:
        grouped[int(row["scale"])].append(row)
    out: list[dict[str, Any]] = []
    for scale, group in sorted(grouped.items()):
        headrooms = [float(row["headroom_pct"]) for row in group if math.isfinite(float(row["headroom_pct"]))]
        late_gains = []
        dr_fractions = []
        early_stop_count = 0
        capped_count = 0
        for row in group:
            ppo = p17_index.get((str(row["bundle"]), int(row["seed"])))
            dr_actual = int((ppo or {}).get("actual_evals") or 0)
            if dr_actual:
                fraction = dr_actual / max(float(base_budget), 1.0)
                dr_fractions.append(fraction)
                early_stop_count += int(fraction <= 0.60)
                late_gains.append(
                    late_gain_after_dr_stop(
                        trajectory_rows,
                        bundle=str(row["bundle"]),
                        seed=int(row["seed"]),
                        dr_actual_evals=dr_actual,
                        final_obj=float(row["obj_B"]),
                    )
                )
            capped_count += int(
                _bool(row.get("wall_clock_capped_B"))
                or _bool(row.get("wall_clock_capped_4B"))
                or _bool(row.get("wall_clock_capped_16B"))
            )
        mean_headroom = statistics.fmean(headrooms) if headrooms else math.nan
        finite_late = [value for value in late_gains if math.isfinite(value)]
        mean_late = statistics.fmean(finite_late) if finite_late else math.nan
        mean_dr_fraction = statistics.fmean(dr_fractions) if dr_fractions else math.nan
        verdict = classify_scale_verdict(
            mean_headroom_pct=mean_headroom,
            mean_late_gain_after_dr_stop_pct=mean_late,
            mean_dr_eval_fraction=mean_dr_fraction,
        )
        out.append(
            {
                "scale": scale,
                "bundle_id": Path(str(group[0]["bundle"])).name,
                "seed_count": len(group),
                "mean_headroom_pct": mean_headroom,
                "min_headroom_pct": min(headrooms) if headrooms else math.nan,
                "max_headroom_pct": max(headrooms) if headrooms else math.nan,
                "mean_late_gain_after_dr_stop_pct": mean_late,
                "mean_dr_eval_fraction": mean_dr_fraction,
                "dr_early_stop_seed_count": early_stop_count,
                "capped_seed_count": capped_count,
                "verdict": verdict,
            }
        )
    return out


def run_all(args: argparse.Namespace) -> dict[str, Any]:
    ensure_environment()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    bundles = select_representative_bundles(p17.load_allscale_bundles(args.manifest))
    policy = load_async_block_policy(p17.PILOT16_FINAL_MODEL)
    if tuple(int(value) for value in policy.model.action_nvec) != EXPECTED_DR_ACTION_NVEC:
        raise RuntimeError(f"HALT_ENV: expected Pilot16 final action_nvec {EXPECTED_DR_ACTION_NVEC}, got {policy.model.action_nvec}")
    pilot17_rows = p17.load_rows(PILOT17_COMPARISON_ROWS)
    if not pilot17_rows:
        raise RuntimeError(f"HALT_PILOT17_ARTIFACTS: missing Pilot17 comparison rows at {PILOT17_COMPARISON_ROWS}")

    run_partial = output_dir / "pilot18_baseline_rows.partial.csv"
    trajectory_partial = output_dir / "pilot18_trajectory_rows.partial.csv"
    run_rows = load_run_rows(run_partial) if args.resume else []
    trajectory_rows = load_csv_rows(trajectory_partial) if args.resume else []
    existing_runs = {run_key(row) for row in run_rows}
    existing_trace_rows = {trajectory_row_key(row) for row in trajectory_rows}
    existing_trace_runs = {trajectory_run_key(row) for row in trajectory_rows}

    for bundle in bundles:
        for seed in args.seeds:
            for multiplier, budget in zip(args.budget_multipliers, budget_values(args.eval_budget, args.budget_multipliers)):
                for algorithm in BASELINE_ALGORITHMS:
                    key = (algorithm, bundle, int(seed), int(budget))
                    if key not in existing_runs:
                        if algorithm == "winner_static_meta":
                            row, trace = run_winner_static_meta_row(
                                bundle=bundle,
                                seed=int(seed),
                                eval_budget=int(budget),
                                block_size=args.block_size,
                                budget_multiplier=int(multiplier),
                                max_runtime_seconds=args.max_runtime_seconds,
                                collect_trace=int(multiplier) == 1,
                            )
                            if int(multiplier) == 1:
                                for trace_row in trace:
                                    tkey = trajectory_row_key(trace_row)
                                    if tkey not in existing_trace_rows:
                                        trajectory_rows.append(trace_row)
                                        existing_trace_rows.add(tkey)
                                        existing_trace_runs.add(trajectory_run_key(trace_row))
                                write_csv(trajectory_partial, trajectory_rows, TRAJECTORY_FIELDS)
                        else:
                            row = run_sa_probe_row(
                                bundle=bundle,
                                seed=int(seed),
                                eval_budget=int(budget),
                                budget_multiplier=int(multiplier),
                                max_runtime_seconds=args.max_runtime_seconds,
                            )
                        run_rows.append(row)
                        existing_runs.add(key)
                        write_csv(run_partial, run_rows, RUN_ROW_FIELDS)

            static_trace_key = ("winner_static_meta", bundle, int(seed), 1)
            if static_trace_key not in existing_trace_runs:
                row, trace = run_winner_static_meta_row(
                    bundle=bundle,
                    seed=int(seed),
                    eval_budget=int(args.eval_budget),
                    block_size=args.block_size,
                    budget_multiplier=1,
                    max_runtime_seconds=args.max_runtime_seconds,
                    collect_trace=True,
                )
                rkey = run_key(row)
                if rkey not in existing_runs:
                    run_rows.append(row)
                    existing_runs.add(rkey)
                    write_csv(run_partial, run_rows, RUN_ROW_FIELDS)
                for trace_row in trace:
                    tkey = trajectory_row_key(trace_row)
                    if tkey not in existing_trace_rows:
                        trajectory_rows.append(trace_row)
                        existing_trace_rows.add(tkey)
                        existing_trace_runs.add(trajectory_run_key(trace_row))
                write_csv(trajectory_partial, trajectory_rows, TRAJECTORY_FIELDS)

            ppo_key = ("dr_pilot16_final_replay", bundle, int(seed), 1)
            if ppo_key not in existing_trace_runs:
                pilot17_row = find_pilot17_ppo_row(pilot17_rows, bundle=bundle, seed=int(seed))
                ppo_trace = replay_dr_trace(
                    model=policy.model,
                    bundle=bundle,
                    seed=int(seed),
                    eval_budget=args.eval_budget,
                    block_size=args.block_size,
                    max_runtime_seconds=args.max_runtime_seconds,
                    pilot17_row=pilot17_row,
                )
                for trace_row in ppo_trace:
                    tkey = trajectory_row_key(trace_row)
                    if tkey not in existing_trace_rows:
                        trajectory_rows.append(trace_row)
                        existing_trace_rows.add(tkey)
                        existing_trace_runs.add(trajectory_run_key(trace_row))
                write_csv(trajectory_partial, trajectory_rows, TRAJECTORY_FIELDS)

    run_rows.sort(key=lambda row: (int(row["scale"]), str(row["bundle"]), int(row["seed"]), int(row["eval_budget"]), str(row["algorithm"])))
    trajectory_rows.sort(key=lambda row: (int(row["scale"]), str(row["bundle"]), int(row["seed"]), str(row["algorithm"]), int(row["step_index"])))
    integrity = integrity_summary(run_rows)
    headroom_rows = build_headroom_rows(run_rows, base_budget=args.eval_budget)
    scale_rows = build_scale_summary(headroom_rows, trajectory_rows, pilot17_rows, base_budget=args.eval_budget)
    if not integrity["ok"]:
        status = "HALT_INTEGRITY"
        reason = "At least one Pilot18 run failed worker, NumPy, feasibility, finite-objective, runtime, or eval-count gates."
    elif len(headroom_rows) != len(bundles) * len(args.seeds):
        status = "HALT_INTEGRITY"
        reason = "Headroom table is incomplete; no performance verdict is valid."
    else:
        status = classify_overall_verdict(scale_rows)
        reason = verdict_reason(status)

    summary = {
        "schema_version": "resetp-pilot18-headroom-probe.v1",
        "status": status,
        "reason": reason,
        "eval_budget_B": int(args.eval_budget),
        "block_size": int(args.block_size),
        "budget_multipliers": list(args.budget_multipliers),
        "budgets": budget_values(args.eval_budget, args.budget_multipliers),
        "seeds": list(args.seeds),
        "max_runtime_seconds_per_run": float(args.max_runtime_seconds),
        "worker_python": DEFAULT_WORKER,
        "required_numpy": REQUIRED_NUMPY,
        "action_nvec": EXPECTED_DR_ACTION_NVEC,
        "best_static_meta": {
            "q_ratio": BEST_STATIC_META[0],
            "threshold_ratio": BEST_STATIC_META[1],
            "exploration_ratio": BEST_STATIC_META[2],
            "source": "Pilot10 BEST_STATIC_META",
        },
        "representative_bundles": bundles,
        "integrity": integrity,
        "scale_summary": scale_rows,
        "headroom_rows": headroom_rows,
        "same_machine_note": "All values are x86 same-machine relative measurements; no M1 absolute-number comparison is made.",
        "training_note": "Pilot18 is evaluation-only. It does not run PPO training or change reward/cost/check/evaluation/winner semantics.",
    }

    write_csv(output_dir / "pilot18_headroom_rows.csv", headroom_rows, HEADROOM_FIELDS)
    write_csv(output_dir / "pilot18_scale_summary.csv", scale_rows, SCALE_SUMMARY_FIELDS)
    write_csv(output_dir / "pilot18_trajectory_rows.csv", trajectory_rows, TRAJECTORY_FIELDS)
    write_json(output_dir / "pilot18_headroom_probe.json", summary)
    write_text_lf(output_dir / "pilot18_headroom_probe.md", report_markdown(summary))
    return summary


def find_pilot17_ppo_row(rows: list[dict[str, Any]], *, bundle: str, seed: int) -> dict[str, Any] | None:
    for row in rows:
        if (
            str(row.get("algorithm")) == "ppo_block_best"
            and str(row.get("bundle")) == str(bundle)
            and int(row.get("seed") or -1) == int(seed)
        ):
            return row
    return None


def verdict_reason(status: str) -> str:
    if status == "VERDICT_ROOM_EXISTS":
        return "At least one scale has >10% measured non-DR headroom."
    if status == "VERDICT_DR_INTERFACE_GAP":
        return "No scale exceeded the 10% headroom gate, but at least one scale shows baseline improvement after early DR stopping."
    if status == "VERDICT_NO_HEADROOM":
        return "All scales are below the pre-registered 3% headroom threshold."
    return "Measured headroom is in the pre-registered 3-10% modest-room band."


def report_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Pilot18 DR-ALNS Headroom Probe",
        "",
        f"Status: `{summary.get('status')}`.",
        f"Reason: {summary.get('reason')}",
        "",
        f"Budget B: `{summary.get('eval_budget_B')}`; block_size: `{summary.get('block_size')}`.",
        f"Extended budgets: `{summary.get('budgets')}`; seeds: `{summary.get('seeds')}`.",
        f"Worker: `{summary.get('worker_python')}`; NumPy: `{summary.get('required_numpy')}`.",
        f"DR action_nvec: `{tuple(summary.get('action_nvec', []))}`.",
        "",
        "This is x86 same-machine relative evidence only. Pilot18 does not train PPO and does not change reward, cost, feasibility, evaluation, or winner semantics.",
        "",
        "## Verdict Rules",
        "",
        "Pre-registered rules: `<3%` headroom is `VERDICT_NO_HEADROOM`; baseline late gain after DR early stop is `VERDICT_DR_INTERFACE_GAP`; `>10%` is `VERDICT_ROOM_EXISTS`; otherwise `VERDICT_MODEST_ROOM`.",
        "",
        "## Scale Summary",
        "",
        "| scale | bundle | mean headroom % | late gain after DR stop % | DR eval fraction | capped seeds | verdict |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in summary.get("scale_summary", []):
        lines.append(
            f"| {row['scale']} | {row['bundle_id']} | {float(row['mean_headroom_pct']):.3f} | "
            f"{_fmt_float(row['mean_late_gain_after_dr_stop_pct'])} | {_fmt_float(row['mean_dr_eval_fraction'])} | "
            f"{int(row['capped_seed_count'])} | `{row['verdict']}` |"
        )
    lines.extend(["", "## Integrity", ""])
    integrity = summary.get("integrity", {})
    lines.append(
        f"Integrity ok: `{integrity.get('ok')}`; run rows: `{integrity.get('row_count')}`; "
        f"wall-clock capped rows: `{integrity.get('wall_clock_capped_count')}`."
    )
    failures = integrity.get("failures") or []
    if failures:
        lines.extend(["", "Failures:"])
        for failure in failures[:20]:
            lines.append(f"- `{failure['row']}`: `{failure['issues']}`")
    capped = integrity.get("wall_clock_capped_rows") or []
    if capped:
        lines.extend(["", "Capped rows are treated as reached-budget evidence only up to the cap, not as convergence."])
    return "\n".join(lines) + "\n"


def write_halt_report(output_dir: Path, *, status: str, reason: str, exc: BaseException) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": "resetp-pilot18-headroom-probe.v1",
        "status": status,
        "reason": reason,
        "exception": repr(exc),
        "traceback_tail": traceback.format_exc().splitlines()[-20:],
        "worker_python": DEFAULT_WORKER,
        "required_numpy": REQUIRED_NUMPY,
        "same_machine_note": "No performance verdict was produced.",
    }
    write_json(output_dir / "pilot18_headroom_probe.json", summary)
    lines = [
        "# Pilot18 DR-ALNS Headroom Probe",
        "",
        f"Status: `{status}`.",
        f"Reason: {reason}",
        "",
        "No performance verdict was produced.",
        "",
        "```text",
        repr(exc),
        "```",
    ]
    write_text_lf(output_dir / "pilot18_headroom_probe.md", "\n".join(lines) + "\n")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pilot18 DR-ALNS headroom probe.")
    parser.add_argument("--manifest", default=str(p17.ALLSCALE_MANIFEST))
    parser.add_argument("--output-dir", default=str(PILOT18_DIR))
    parser.add_argument("--eval-budget", type=int, default=EVAL_BUDGET)
    parser.add_argument("--block-size", type=int, default=BLOCK_SIZE)
    parser.add_argument("--seeds", default=",".join(str(seed) for seed in SEEDS))
    parser.add_argument("--budget-multipliers", "--budgets", dest="budget_spec", default=",".join(str(value) for value in BUDGET_MULTIPLIERS))
    parser.add_argument("--max-runtime-seconds", type=float, default=MAX_RUNTIME_SECONDS)
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    args = parser.parse_args(argv)
    args.seeds = tuple(int(part) for part in str(args.seeds).split(",") if part.strip())
    budget_spec = tuple(int(part) for part in str(args.budget_spec).split(",") if part.strip())
    explicit_budgets = tuple(budget_values(args.eval_budget))
    if budget_spec == BUDGET_MULTIPLIERS:
        args.budget_multipliers = BUDGET_MULTIPLIERS
    elif budget_spec == explicit_budgets:
        args.budget_multipliers = BUDGET_MULTIPLIERS
    else:
        raise ValueError(
            f"Pilot18 expects budget multipliers {BUDGET_MULTIPLIERS} or explicit budgets {explicit_budgets}, "
            f"got {budget_spec}"
        )
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = run_all(args)
    except Exception as exc:
        text = str(exc)
        if "HALT_ENV" in text:
            status = "HALT_ENV"
        elif "HALT_BUNDLE" in text:
            status = "HALT_BUNDLE"
        elif "HALT_PILOT17_ARTIFACTS" in text:
            status = "HALT_PILOT17_ARTIFACTS"
        else:
            status = "HALT_RUN"
        summary = write_halt_report(Path(args.output_dir), status=status, reason=text, exc=exc)
    print(f"PILOT18_HEADROOM_DONE status={summary['status']} output={args.output_dir}")
    return 0 if not str(summary["status"]).startswith("HALT") else 2


def run_key(row: dict[str, Any]) -> tuple[str, str, int, int]:
    return (str(row["algorithm"]), str(row["bundle"]), int(row["seed"]), int(row["eval_budget"]))


def trajectory_run_key(row: dict[str, Any]) -> tuple[str, str, int, int]:
    return (str(row["algorithm"]), str(row["bundle"]), int(row["seed"]), int(row["budget_multiplier"]))


def trajectory_row_key(row: dict[str, Any]) -> tuple[str, str, int, int, int]:
    return (
        str(row["algorithm"]),
        str(row["bundle"]),
        int(row["seed"]),
        int(row["budget_multiplier"]),
        int(row["step_index"]),
    )


def run_row_id(row: dict[str, Any]) -> str:
    return f"{row.get('algorithm')}|{Path(str(row.get('bundle'))).name}|seed{row.get('seed')}|B{row.get('eval_budget')}"


def load_run_rows(path: str | Path) -> list[dict[str, Any]]:
    rows = load_csv_rows(path)
    normalized = []
    for row in rows:
        for key in ("seed", "scale", "budget_multiplier", "eval_budget", "actual_evals", "candidate_scores", "repair_delta_count", "violation_count"):
            row[key] = int(float(row.get(key) or 0))
        for key in ("best_obj", "elapsed_seconds", "runtime_target_seconds"):
            row[key] = float(row.get(key) or 0.0)
        for key in ("operator_counts", "destroy_counts", "repair_counts", "q_ratio_counts"):
            if isinstance(row.get(key), str) and row.get(key):
                row[key] = json.loads(str(row[key]))
            elif row.get(key) in ("", None):
                row[key] = {}
        normalized.append(row)
    return normalized


def load_csv_rows(path: str | Path) -> list[dict[str, Any]]:
    value = Path(path)
    if not value.is_file():
        return []
    with value.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(csv_row(row, fieldnames))


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_text_lf(output, json.dumps(json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_text_lf(path: str | Path, text: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def csv_row(row: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    out = {}
    for key in fields:
        value = row.get(key, "")
        if key in {"feasible", "wall_clock_capped", "budget_reached", "search_control_stop_requested"}:
            value = int(_bool(value))
        elif isinstance(value, (dict, list, tuple)):
            value = json.dumps(json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        out[key] = value
    return out


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _nearest_index(values: tuple[float, ...], target: float) -> int:
    return min(range(len(values)), key=lambda idx: abs(float(values[idx]) - float(target)))


def _inc(counts: dict[str, int], key: str) -> None:
    if key:
        counts[key] = int(counts.get(key, 0)) + 1


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes"}


def _blank_or_float(value: Any) -> float | str:
    if value in (None, ""):
        return ""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return ""
    return result if math.isfinite(result) else ""


def _blank_or_int(value: Any) -> int | str:
    if value in (None, ""):
        return ""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return ""


def _fmt_float(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(numeric):
        return ""
    return f"{numeric:.3f}"


if __name__ == "__main__":
    raise SystemExit(main())
