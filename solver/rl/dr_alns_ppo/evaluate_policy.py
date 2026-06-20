from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
from pathlib import Path
from typing import Any

from stable_baselines3 import PPO

from .async_block_policy import is_async_block_model_path, load_async_block_policy
from .baselines import (
    normalize_result_row,
    run_alpha_ucb_env_policy,
    run_alpha_ucb_block_policy,
    run_official_winner_kernel,
    run_ppo_block_policy,
    run_ppo_policy,
    run_random_block_policy,
    run_random_policy,
    write_rows_csv,
)
from .bundle_manifest import load_manifest


def parse_seeds(value: str) -> list[int]:
    seeds = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not seeds:
        raise ValueError("at least one seed is required")
    return seeds


def evaluate(args: argparse.Namespace) -> list[dict]:
    manifest = load_manifest(args.manifest)
    bundles = _filter_bundles(_selected_bundles(manifest, args.split), args.bundle_filter)
    seeds = parse_seeds(args.seeds)
    algorithms = parse_algorithms(args.algorithms)
    if any(algorithm in {"ppo_full", "ppo_operator_only", "ppo_reduced_full", "ppo_block"} for algorithm in algorithms) and not args.model:
        raise ValueError("--model is required when evaluating PPO algorithms")
    all_tasks = [
        (algorithm, bundle_dir, seed)
        for bundle_dir in bundles
        for seed in seeds
        for algorithm in algorithms
    ]
    worker_args = {
        "model_path": str(args.model),
        "eval_budget": int(args.eval_budget),
        "base_temperature": float(args.base_temperature),
        "deterministic": not args.stochastic_ppo,
        "official_max_runtime_seconds": float(args.official_max_runtime_seconds),
        "block_size": int(args.block_size),
    }
    rows: list[dict]
    output_dir = Path(args.output_dir)
    partial_csv = output_dir / "comparison.partial.csv"
    rows = load_existing_rows(args.resume_comparison) if args.resume_comparison else []
    tasks = filter_tasks_for_resume(
        all_tasks,
        rows,
        eval_budget=int(args.eval_budget),
        rerun_underbudget=bool(args.rerun_underbudget),
    )
    rerun_keys = {_task_key(*task) for task in tasks}
    if rerun_keys:
        rows = [row for row in rows if _row_key(row) not in rerun_keys]
    if args.jobs > 1 and len(tasks) > 1:
        with concurrent.futures.ProcessPoolExecutor(max_workers=min(int(args.jobs), len(tasks))) as executor:
            futures = [
                executor.submit(_evaluate_one_task, algorithm, bundle_dir, seed, worker_args)
                for algorithm, bundle_dir, seed in tasks
            ]
            for future in concurrent.futures.as_completed(futures):
                rows.append(future.result())
                write_rows_csv(partial_csv, sorted(rows, key=_sort_key))
    else:
        for algorithm, bundle_dir, seed in tasks:
            rows.append(_evaluate_one_task(algorithm, bundle_dir, seed, worker_args))
            write_rows_csv(partial_csv, sorted(rows, key=_sort_key))
    rows.sort(key=_sort_key)
    write_rows_csv(output_dir / "comparison.csv", rows)
    return rows


def load_existing_rows(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            row: dict[str, Any] = dict(raw)
            for key in ("operator_counts", "destroy_counts", "repair_counts", "q_ratio_counts"):
                value = row.get(key)
                row[key] = json.loads(value) if value else {}
            feasible = str(row.get("feasible", "")).strip().lower()
            if feasible in {"0", "1"}:
                row["feasible"] = bool(int(feasible))
            elif feasible in {"true", "false"}:
                row["feasible"] = feasible == "true"
            rows.append(normalize_result_row(row))
    return rows


def filter_tasks_for_resume(
    tasks: list[tuple[str, str, int]],
    rows: list[dict[str, Any]],
    *,
    eval_budget: int,
    rerun_underbudget: bool,
) -> list[tuple[str, str, int]]:
    existing = {_row_key(row): row for row in rows}
    pending: list[tuple[str, str, int]] = []
    for task in tasks:
        key = _task_key(*task)
        row = existing.get(key)
        if row is None:
            pending.append(task)
        elif rerun_underbudget and int(row["actual_evals"]) != int(eval_budget):
            pending.append(task)
    return pending


def _evaluate_one_task(algorithm: str, bundle_dir: str, seed: int, args: dict) -> dict:
    if algorithm == "ppo_full":
        model = PPO.load(args["model_path"])
        return run_ppo_policy(
            model,
            bundle_dir,
            seed=seed,
            eval_budget=args["eval_budget"],
            base_temperature=args["base_temperature"],
            deterministic=args["deterministic"],
            control_mode="ppo_full",
        )
    if algorithm == "ppo_operator_only":
        model = PPO.load(args["model_path"])
        row = run_ppo_policy(
            model,
            bundle_dir,
            seed=seed,
            eval_budget=args["eval_budget"],
            base_temperature=args["base_temperature"],
            deterministic=args["deterministic"],
            control_mode="operator_only",
        )
        row["algorithm"] = "ppo_operator_only"
        return normalize_result_row(row)
    if algorithm == "ppo_reduced_full":
        model = PPO.load(args["model_path"])
        row = run_ppo_policy(
            model,
            bundle_dir,
            seed=seed,
            eval_budget=args["eval_budget"],
            base_temperature=args["base_temperature"],
            deterministic=args["deterministic"],
            control_mode="reduced_full",
        )
        row["algorithm"] = "ppo_reduced_full"
        return normalize_result_row(row)
    if algorithm == "ppo_block":
        model = (
            load_async_block_policy(args["model_path"])
            if is_async_block_model_path(args["model_path"])
            else PPO.load(args["model_path"])
        )
        return run_ppo_block_policy(
            model,
            bundle_dir,
            seed=seed,
            eval_budget=args["eval_budget"],
            block_size=args["block_size"],
            deterministic=args["deterministic"],
        )
    if algorithm == "random_full":
        return run_random_policy(
            bundle_dir,
            seed=seed,
            eval_budget=args["eval_budget"],
            base_temperature=args["base_temperature"],
        )
    if algorithm == "random_block":
        return run_random_block_policy(
            bundle_dir,
            seed=seed,
            eval_budget=args["eval_budget"],
            block_size=args["block_size"],
        )
    if algorithm == "alpha_ucb_env":
        return run_alpha_ucb_env_policy(
            bundle_dir,
            seed=seed,
            eval_budget=args["eval_budget"],
            base_temperature=args["base_temperature"],
        )
    if algorithm == "alpha_ucb_block":
        return run_alpha_ucb_block_policy(
            bundle_dir,
            seed=seed,
            eval_budget=args["eval_budget"],
            block_size=args["block_size"],
        )
    if algorithm == "official_winner_kernel":
        return run_official_winner_kernel(
            bundle_dir,
            seed=seed,
            eval_budget=args["eval_budget"],
            max_runtime_seconds=args["official_max_runtime_seconds"],
        )
    raise ValueError(f"unknown algorithm: {algorithm}")


def parse_algorithms(value: str) -> tuple[str, ...]:
    algorithms = tuple(item.strip() for item in value.split(",") if item.strip())
    if not algorithms:
        raise ValueError("at least one algorithm is required")
    allowed = {
        "random_full",
        "alpha_ucb_env",
        "official_winner_kernel",
        "ppo_full",
        "ppo_operator_only",
        "ppo_reduced_full",
        "random_block",
        "alpha_ucb_block",
        "ppo_block",
    }
    unknown = sorted(set(algorithms) - allowed)
    if unknown:
        raise ValueError(f"unknown algorithm(s): {', '.join(unknown)}")
    return algorithms


def _selected_bundles(manifest: dict[str, Any], split: str) -> list[str]:
    if split == "train":
        return list(manifest["train"])
    if split == "held_out":
        return list(manifest["held_out"])
    if split == "formal_eval":
        return list(manifest["formal_eval"])
    if split == "all":
        return list(manifest["held_out"]) + list(manifest["formal_eval"])
    raise ValueError(f"unknown split: {split}")


def _filter_bundles(bundles: list[str], filters: str | None) -> list[str]:
    if not filters:
        return bundles
    needles = [item.strip() for item in str(filters).split(",") if item.strip()]
    selected = [bundle for bundle in bundles if any(needle in bundle for needle in needles)]
    if not selected:
        raise ValueError(f"--bundle-filter matched no bundles: {filters}")
    return selected


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate DR-ALNS-PPO v2 policies and winner-bottom baselines.")
    parser.add_argument("--manifest", default="solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json")
    parser.add_argument("--model")
    parser.add_argument(
        "--algorithms",
        default="random_full,alpha_ucb_env",
        help="Comma-separated algorithms: random_full,alpha_ucb_env,official_winner_kernel,ppo_full,ppo_operator_only,ppo_reduced_full,random_block,alpha_ucb_block,ppo_block.",
    )
    parser.add_argument("--split", choices=("train", "held_out", "formal_eval", "all"), default="held_out")
    parser.add_argument("--bundle-filter", help="Comma-separated substrings used to narrow the selected split.")
    parser.add_argument("--eval-budget", type=int, default=16000)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--base-temperature", type=float, default=100.0)
    parser.add_argument("--block-size", type=int, default=128)
    parser.add_argument("--stochastic-ppo", action="store_true")
    parser.add_argument("--official-max-runtime-seconds", type=float, default=900.0)
    parser.add_argument("--jobs", type=int, default=min(2, max(1, os.cpu_count() or 1)))
    parser.add_argument("--resume-comparison", help="Existing comparison CSV to keep completed rows and only run missing tasks.")
    parser.add_argument("--rerun-underbudget", action="store_true", help="With --resume-comparison, rerun rows whose actual_evals differs from eval_budget.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    rows = evaluate(parse_args(argv))
    print(f"DR_ALNS_PPO_EVAL_OK rows={len(rows)}")
    return 0


def _task_key(algorithm: str, bundle: str, seed: int) -> tuple[str, str, int]:
    return (str(algorithm), str(bundle), int(seed))


def _row_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return _task_key(str(row["algorithm"]), str(row["bundle"]), int(row["seed"]))


def _sort_key(row: dict[str, Any]) -> tuple[str, int, str]:
    return (str(row["bundle"]), int(row["seed"]), str(row["algorithm"]))


if __name__ == "__main__":
    raise SystemExit(main())
