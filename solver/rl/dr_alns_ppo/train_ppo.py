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
    def __init__(self, output_csv: Path, env_specs: list[dict[str, Any]]) -> None:
        super().__init__()
        self.output_csv = output_csv
        self.env_specs = env_specs
        self.episode_index = 0
        self._handle = None
        self._writer = None

    def _on_training_start(self) -> None:
        self.output_csv.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.output_csv.open("w", newline="", encoding="utf-8")
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
):
    env_specs = [
        {"bundle": bundle_dir, "seed": int(seed) + idx}
        for idx, bundle_dir in enumerate(bundles)
    ]
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
        filename=str(output_dir / "monitor.csv"),
        info_keywords=("actual_evals", "candidate_scores", "repair_delta_count", "best_obj", "violation_count"),
    )
    return monitor, env_specs


def train(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(args.manifest)
    train_bundles = list(manifest["train"])
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
