from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv, VecMonitor

from .bundle_manifest import load_manifest
from .env import SetpAlnsEnv


def make_env(bundle_dir: str, *, seed: int, eval_budget: int, base_temperature: float, control_mode: str):
    def _factory() -> SetpAlnsEnv:
        return SetpAlnsEnv(
            bundle_dir,
            seed=seed,
            eval_budget=eval_budget,
            base_temperature=base_temperature,
            control_mode=control_mode,
        )

    return _factory


class EvalCountCallback(BaseCallback):
    def __init__(self, output_csv: Path, env_specs: list[dict[str, Any]], *, append: bool = False) -> None:
        super().__init__()
        self.output_csv = output_csv
        self.env_specs = env_specs
        self.append = append
        self.episode_index = 0
        self._handle = None
        self._writer = None

    def _on_training_start(self) -> None:
        self.output_csv.parent.mkdir(parents=True, exist_ok=True)
        write_header = not self.append or not self.output_csv.exists() or self.output_csv.stat().st_size == 0
        self._handle = self.output_csv.open("a" if self.append else "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._handle,
            fieldnames=[
                "event",
                "episode_index",
                "env_index",
                "bundle",
                "seed",
                "actual_evals",
                "candidate_scores",
                "repair_delta_count",
                "best_obj",
                "feasible",
            ],
        )
        if write_header:
            self._writer.writeheader()
        self._handle.flush()

    def _on_step(self) -> bool:
        infos = self.locals.get("infos", [])
        dones = self.locals.get("dones", [])
        for env_index, done in enumerate(dones):
            if not done:
                continue
            info = infos[env_index]
            self._write_row("episode_end", env_index, info)
        return True

    def _on_training_end(self) -> None:
        if self._handle is not None:
            self._handle.flush()
            self._handle.close()
            self._handle = None
            self._writer = None

    def _write_row(self, event: str, env_index: int, info: dict[str, Any]) -> None:
        if self._writer is None or self._handle is None:
            return
        spec = self.env_specs[env_index]
        self._writer.writerow(
            {
                "event": event,
                "episode_index": self.episode_index,
                "env_index": env_index,
                "bundle": spec["bundle"],
                "seed": spec["seed"],
                "actual_evals": int(info.get("actual_evals", 0)),
                "candidate_scores": int(info.get("candidate_scores", 0)),
                "repair_delta_count": int(info.get("repair_delta_count", 0)),
                "best_obj": float(info.get("best_obj", 0.0)),
                "feasible": int(info.get("violation_count", 1) == 0),
            }
        )
        self.episode_index += 1
        self._handle.flush()


def build_vec_env(
    bundles: list[str],
    *,
    seed: int,
    eval_budget: int,
    base_temperature: float,
    control_mode: str,
    output_dir: Path,
    vec_env: str,
    env_repeats: int = 1,
    monitor_filename: str = "monitor.csv",
):
    env_specs = build_env_specs(bundles, seed=seed, env_repeats=env_repeats)
    factories = [
        make_env(
            spec["bundle"],
            seed=spec["seed"],
            eval_budget=eval_budget,
            base_temperature=base_temperature,
            control_mode=control_mode,
        )
        for spec in env_specs
    ]
    if vec_env == "subproc" and len(factories) > 1:
        venv = SubprocVecEnv(factories, start_method="spawn")
    else:
        venv = DummyVecEnv(factories)
    monitor = VecMonitor(
        venv,
        filename=str(output_dir / monitor_filename),
        info_keywords=("actual_evals", "candidate_scores", "repair_delta_count", "best_obj", "violation_count"),
    )
    return monitor, env_specs


def build_env_specs(bundles: list[str], *, seed: int, env_repeats: int = 1) -> list[dict[str, Any]]:
    if int(env_repeats) < 1:
        raise ValueError("--env-repeats must be >= 1")
    return [
        {
            "bundle": bundle_dir,
            "seed": int(seed) + repeat_idx * len(bundles) + bundle_idx,
            "repeat": repeat_idx,
        }
        for repeat_idx in range(int(env_repeats))
        for bundle_idx, bundle_dir in enumerate(bundles)
    ]


def build_bucketed_phase_plan(
    bundles: list[str],
    *,
    total_timesteps: int,
    n_steps: int,
    env_repeats: int,
) -> list[dict[str, Any]]:
    if not bundles:
        raise ValueError("at least one training bundle is required")
    if int(total_timesteps) < 1:
        raise ValueError("--timesteps must be >= 1")
    phase_timesteps = int(n_steps) * int(env_repeats)
    if phase_timesteps < 1:
        raise ValueError("--n-steps * --env-repeats must be >= 1")
    phases: list[dict[str, Any]] = []
    scheduled = 0
    phase_index = 0
    while scheduled < int(total_timesteps):
        bundle = bundles[phase_index % len(bundles)]
        phases.append(
            {
                "phase_index": phase_index,
                "bundle": bundle,
                "requested_timesteps": min(phase_timesteps, int(total_timesteps) - scheduled),
                "rollout_timesteps": phase_timesteps,
            }
        )
        scheduled += phase_timesteps
        phase_index += 1
    return phases


def train(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(args.manifest)
    train_bundles = list(manifest["train"])
    if args.schedule == "bucketed":
        train_bucketed(args, train_bundles, output_dir)
        return
    venv = None
    try:
        venv, env_specs = build_vec_env(
            train_bundles,
            seed=args.seed,
            eval_budget=args.eval_budget,
            base_temperature=args.base_temperature,
            control_mode=args.control_mode,
            output_dir=output_dir,
            vec_env=args.vec_env,
            env_repeats=args.env_repeats,
        )
        model = PPO(
            "MlpPolicy",
            venv,
            seed=args.seed,
            verbose=args.verbose,
            n_steps=args.n_steps,
            batch_size=args.batch_size,
            n_epochs=args.n_epochs,
            learning_rate=args.learning_rate,
        )
        config = {
            "manifest": str(args.manifest),
            "train_bundles": train_bundles,
            "timesteps": int(args.timesteps),
            "eval_budget": int(args.eval_budget),
            "seed": int(args.seed),
            "base_temperature": float(args.base_temperature),
            "control_mode": args.control_mode,
            "policy": "MlpPolicy",
            "vec_env": args.vec_env,
            "env_repeats": int(args.env_repeats),
            "schedule": args.schedule,
            "n_steps": int(args.n_steps),
            "batch_size": int(args.batch_size),
            "n_epochs": int(args.n_epochs),
            "learning_rate": float(args.learning_rate),
        }
        (output_dir / "training_config.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        callback = EvalCountCallback(output_dir / "env_eval_counts.csv", env_specs)
        model.learn(total_timesteps=int(args.timesteps), callback=callback, progress_bar=bool(args.progress_bar))
        model.save(output_dir / "model.zip")
    finally:
        if venv is not None:
            venv.close()


def train_bucketed(args: argparse.Namespace, train_bundles: list[str], output_dir: Path) -> None:
    phases = build_bucketed_phase_plan(
        train_bundles,
        total_timesteps=int(args.timesteps),
        n_steps=int(args.n_steps),
        env_repeats=int(args.env_repeats),
    )
    config = {
        "manifest": str(args.manifest),
        "train_bundles": train_bundles,
        "timesteps": int(args.timesteps),
        "eval_budget": int(args.eval_budget),
        "seed": int(args.seed),
        "base_temperature": float(args.base_temperature),
        "control_mode": args.control_mode,
        "policy": "MlpPolicy",
        "vec_env": args.vec_env,
        "env_repeats": int(args.env_repeats),
        "schedule": args.schedule,
        "n_steps": int(args.n_steps),
        "batch_size": int(args.batch_size),
        "n_epochs": int(args.n_epochs),
        "learning_rate": float(args.learning_rate),
        "phase_count": len(phases),
    }
    (output_dir / "training_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    phase_log_path = output_dir / "bucketed_phase_log.csv"
    with phase_log_path.open("w", newline="", encoding="utf-8") as phase_handle:
        phase_writer = csv.DictWriter(
            phase_handle,
            fieldnames=[
                "phase_index",
                "bundle",
                "seed",
                "requested_timesteps",
                "rollout_timesteps",
                "model_timesteps_after_phase",
                "monitor_file",
            ],
        )
        phase_writer.writeheader()
        model = None
        for phase in phases:
            phase_seed = int(args.seed) + int(phase["phase_index"]) * int(args.env_repeats)
            monitor_file = f"monitor_phase_{int(phase['phase_index']):04d}.csv"
            venv = None
            try:
                venv, env_specs = build_vec_env(
                    [str(phase["bundle"])],
                    seed=phase_seed,
                    eval_budget=args.eval_budget,
                    base_temperature=args.base_temperature,
                    control_mode=args.control_mode,
                    output_dir=output_dir,
                    vec_env=args.vec_env,
                    env_repeats=args.env_repeats,
                    monitor_filename=monitor_file,
                )
                if model is None:
                    model = PPO(
                        "MlpPolicy",
                        venv,
                        seed=args.seed,
                        verbose=args.verbose,
                        n_steps=args.n_steps,
                        batch_size=args.batch_size,
                        n_epochs=args.n_epochs,
                        learning_rate=args.learning_rate,
                    )
                else:
                    model.set_env(venv)
                callback = EvalCountCallback(output_dir / "env_eval_counts.csv", env_specs, append=True)
                model.learn(
                    total_timesteps=int(phase["requested_timesteps"]),
                    callback=callback,
                    progress_bar=bool(args.progress_bar),
                    reset_num_timesteps=False,
                )
                phase_writer.writerow(
                    {
                        "phase_index": int(phase["phase_index"]),
                        "bundle": str(phase["bundle"]),
                        "seed": phase_seed,
                        "requested_timesteps": int(phase["requested_timesteps"]),
                        "rollout_timesteps": int(phase["rollout_timesteps"]),
                        "model_timesteps_after_phase": int(model.num_timesteps),
                        "monitor_file": monitor_file,
                    }
                )
                phase_handle.flush()
            finally:
                if venv is not None:
                    venv.close()
            if model is not None and int(model.num_timesteps) >= int(args.timesteps):
                break
        if model is None:
            raise RuntimeError("bucketed training did not create a PPO model")
        _merge_monitor_files(output_dir)
        model.save(output_dir / "model.zip")


def _merge_monitor_files(output_dir: Path) -> None:
    monitor_files = sorted(output_dir.glob("monitor_phase_*.csv"))
    out = output_dir / "monitor.csv"
    with out.open("w", newline="", encoding="utf-8") as handle:
        handle.write('#{"t_start": 0.0, "env_id": "bucketed"}\n')
        wrote_header = False
        for monitor_file in monitor_files:
            for line in monitor_file.read_text(encoding="utf-8").splitlines():
                if not line or line.startswith("#"):
                    continue
                if not wrote_header:
                    handle.write(line + "\n")
                    wrote_header = True
                elif line.startswith("r,"):
                    continue
                else:
                    handle.write(line + "\n")
        if not wrote_header:
            handle.write("r,l,t,actual_evals,candidate_scores,repair_delta_count,best_obj,violation_count\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train PPO for the isolated DR-ALNS-PPO lane.")
    parser.add_argument("--manifest", default="solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json")
    parser.add_argument("--timesteps", type=int, required=True)
    parser.add_argument("--eval-budget", type=int, default=16000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--base-temperature", type=float, default=100.0)
    parser.add_argument("--control-mode", choices=("ppo_full", "operator_only"), default="ppo_full")
    parser.add_argument("--vec-env", choices=("subproc", "dummy"), default="subproc")
    parser.add_argument(
        "--schedule",
        choices=("mixed", "bucketed"),
        default="mixed",
        help="mixed runs all bundles in one synchronous VecEnv; bucketed cycles homogeneous per-bundle VecEnvs.",
    )
    parser.add_argument(
        "--env-repeats",
        type=int,
        default=1,
        help="Repeat the training bundle list with distinct seeds to increase vectorized environment parallelism.",
    )
    parser.add_argument("--n-steps", type=int, default=1024)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--n-epochs", type=int, default=5)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--verbose", type=int, default=1)
    parser.add_argument("--progress-bar", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    train(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
