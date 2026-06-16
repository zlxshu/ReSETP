from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from stable_baselines3 import PPO

from .env import SetpAlnsEnv


RESULT_COLUMNS = [
    "algorithm",
    "bundle",
    "seed",
    "eval_budget",
    "best_obj",
    "actual_evals",
    "candidate_scores",
    "repair_delta_count",
    "operator_base_id",
    "control_mode",
    "violation_count",
    "feasible",
    "solution_signature_hash",
    "operator_counts",
    "destroy_counts",
    "repair_counts",
    "q_ratio_counts",
]


def run_random_policy(
    bundle_dir: str,
    *,
    seed: int,
    eval_budget: int,
    base_temperature: float = 100.0,
) -> dict[str, Any]:
    env = SetpAlnsEnv(bundle_dir, seed=seed, eval_budget=eval_budget, base_temperature=base_temperature, control_mode="ppo_full")
    try:
        env.action_space.seed(seed)
        return _run_env_policy(
            env,
            lambda _obs: env.action_space.sample(),
            algorithm="random_full",
            bundle_dir=bundle_dir,
            seed=seed,
            eval_budget=eval_budget,
        )
    finally:
        env.close()


def run_ppo_policy(
    model: PPO,
    bundle_dir: str,
    *,
    seed: int,
    eval_budget: int,
    base_temperature: float = 100.0,
    deterministic: bool = True,
    control_mode: str = "ppo_full",
) -> dict[str, Any]:
    env = SetpAlnsEnv(bundle_dir, seed=seed, eval_budget=eval_budget, base_temperature=base_temperature, control_mode=control_mode)
    try:
        return _run_env_policy(
            env,
            lambda obs: model.predict(obs, deterministic=deterministic)[0],
            algorithm=control_mode,
            bundle_dir=bundle_dir,
            seed=seed,
            eval_budget=eval_budget,
        )
    finally:
        env.close()


def run_alpha_ucb_env_policy(
    bundle_dir: str,
    *,
    seed: int,
    eval_budget: int,
    base_temperature: float = 100.0,
) -> dict[str, Any]:
    from setp_solver.search.alns_wouda import _make_operator_selector

    env = SetpAlnsEnv(
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        base_temperature=base_temperature,
        control_mode="kernel_default",
    )
    try:
        selector = _make_operator_selector(int(env.action_space.nvec[0]), int(env.action_space.nvec[1]))
        rng = _np_rng(seed)

        def _action(_obs: Any) -> tuple[int, int]:
            if env.last_response is None:
                raise RuntimeError("env has no response before alpha-ucb action")
            d_idx, r_idx = selector(rng, None, None)
            env._pending_alpha_ucb = (int(d_idx), int(r_idx), selector)  # type: ignore[attr-defined]
            return (int(d_idx), int(r_idx))

        row = _run_env_policy(
            env,
            _action,
            algorithm="alpha_ucb_env",
            bundle_dir=bundle_dir,
            seed=seed,
            eval_budget=eval_budget,
            update_alpha_ucb=True,
        )
        return row
    finally:
        env.close()


def run_official_winner_kernel(
    bundle_dir: str,
    *,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float = 900.0,
) -> dict[str, Any]:
    from setp_solver.search.candidates import solution_signature_hash as solver_solution_signature_hash
    from setp_solver.search.winner_operators import WinnerKernelConfig, operator_base_id, run_winner_kernel

    result = run_winner_kernel(
        bundle_dir,
        config=WinnerKernelConfig(
            seed=int(seed),
            eval_budget=int(eval_budget),
            max_runtime_seconds=float(max_runtime_seconds),
        ),
    )
    solution = result["best_solution"]
    return normalize_result_row(
        {
            "algorithm": "official_winner_kernel",
            "bundle": bundle_dir,
            "seed": seed,
            "eval_budget": eval_budget,
            "best_obj": float(result["best_cost"]),
            "actual_evals": int(result["evaluations"]),
            "candidate_scores": int(result["evaluations"]),
            "repair_delta_count": 0,
            "operator_base_id": operator_base_id,
            "control_mode": "official_kernel",
            "violation_count": int(result["violation_count"]),
            "feasible": bool(result["feasible"]),
            "solution_signature_hash": solver_solution_signature_hash(solution),
            "operator_counts": {},
            "destroy_counts": {},
            "repair_counts": {},
            "q_ratio_counts": {},
        }
    )


def run_alns_wouda_strengthened(
    bundle_dir: str,
    *,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float = 3600.0,
) -> dict[str, Any]:
    repo_root = _repo_root()
    script = r"""
import json
import sys
from setp_solver.search.alns_wouda import run_alns_wouda
from setp_solver.search.candidates import solution_signature_hash

bundle_dir = sys.argv[1]
seed = int(sys.argv[2])
eval_budget = int(sys.argv[3])
max_runtime_seconds = float(sys.argv[4])
result = run_alns_wouda(
    bundle_dir,
    iterations=None,
    seed=seed,
    eval_budget=eval_budget,
    max_runtime_seconds=max_runtime_seconds,
)
payload = {
    "algorithm": "alns_wouda_strengthened",
    "bundle": bundle_dir,
    "seed": seed,
    "eval_budget": eval_budget,
    "best_obj": float(result.best_obj),
    "actual_evals": int(result.evaluations),
    "candidate_scores": int(result.candidate_scores),
    "repair_delta_count": int(result.repair_delta_count),
    "feasible": bool(result.feasible),
    "solution_signature_hash": solution_signature_hash(result.best_solution),
    "operator_counts": result.operator_counts,
    "destroy_counts": result.destroy_operator_counts,
    "repair_counts": result.repair_operator_counts,
    "q_ratio_counts": {},
}
print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(repo_root / "solver" / "src"), str(repo_root / "models" / "src")])
    env["PYTHONNOUSERSITE"] = "1"
    bundle_path = str(_resolve_path(bundle_dir, repo_root))
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script, bundle_path, str(seed), str(eval_budget), str(max_runtime_seconds)],
            cwd=repo_root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=max(30.0, float(max_runtime_seconds) + 60.0),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"ALNS-Wouda subprocess timed out after {exc.timeout}s for bundle={bundle_dir} seed={seed}"
        ) from exc
    if proc.returncode != 0:
        raise RuntimeError(f"ALNS-Wouda subprocess failed rc={proc.returncode}: {proc.stderr[-4000:]}")
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"ALNS-Wouda subprocess produced no JSON output; stderr={proc.stderr[-4000:]}")
    row = json.loads(lines[-1])
    row["bundle"] = bundle_dir
    return normalize_result_row(row)


def write_rows_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(_csv_row(normalize_result_row(row)))


def normalize_result_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = {key: row.get(key, "") for key in RESULT_COLUMNS}
    normalized["seed"] = int(normalized["seed"])
    normalized["eval_budget"] = int(normalized["eval_budget"])
    normalized["best_obj"] = float(normalized["best_obj"])
    normalized["actual_evals"] = int(normalized["actual_evals"])
    normalized["candidate_scores"] = int(normalized["candidate_scores"])
    normalized["repair_delta_count"] = int(normalized["repair_delta_count"])
    normalized["operator_base_id"] = str(normalized.get("operator_base_id", "") or "")
    normalized["control_mode"] = str(normalized.get("control_mode", "") or "")
    normalized["violation_count"] = int(normalized.get("violation_count", 0) or 0)
    normalized["feasible"] = _coerce_bool(normalized["feasible"])
    for key in ("operator_counts", "destroy_counts", "repair_counts", "q_ratio_counts"):
        if normalized[key] in ("", None):
            normalized[key] = {}
    return normalized


def solution_signature_hash(solution_payload: dict[str, Any]) -> str:
    payload = json.dumps(solution_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _run_env_policy(
    env: SetpAlnsEnv,
    action_fn: Callable[[Any], Any],
    *,
    algorithm: str,
    bundle_dir: str,
    seed: int,
    eval_budget: int,
    update_alpha_ucb: bool = False,
) -> dict[str, Any]:
    obs, _info = env.reset(seed=seed)
    if env.last_response is None:
        raise RuntimeError("env reset did not populate last_response")
    best_response = env.last_response
    last_response = env.last_response
    destroy_counts: dict[str, int] = {}
    repair_counts: dict[str, int] = {}
    q_ratio_counts: dict[str, int] = {}
    terminated = False
    truncated = False
    while not (terminated or truncated):
        action = action_fn(obs)
        obs, _reward, terminated, truncated, info = env.step(action)
        last_response = info
        trace = info.get("trace", {}) or {}
        if update_alpha_ucb:
            d_idx, r_idx, selector = getattr(env, "_pending_alpha_ucb")
            selector.update(None, d_idx, r_idx, _outcome_index(info))
        _inc(destroy_counts, str(trace.get("destroy_id", "")))
        _inc(repair_counts, str(trace.get("repair_id", "")))
        q_ratio = trace.get("q_ratio")
        if q_ratio is not None:
            _inc(q_ratio_counts, f"{float(q_ratio):.6f}")
        if float(info.get("best_obj", float("inf"))) <= float(best_response.get("best_obj", float("inf"))) + 1e-9:
            if info.get("improved_best"):
                best_response = info
    best_solution = best_response.get("solution", {})
    row = {
        "algorithm": algorithm,
        "bundle": bundle_dir,
        "seed": seed,
        "eval_budget": eval_budget,
        "best_obj": float(last_response.get("best_obj", best_response.get("best_obj", 0.0))),
        "actual_evals": int(last_response.get("actual_evals", 0)),
        "candidate_scores": int(last_response.get("candidate_scores", 0)),
        "repair_delta_count": int(last_response.get("repair_delta_count", 0)),
        "operator_base_id": str((last_response.get("trace", {}) or {}).get("operator_base_id", "")),
        "control_mode": str((last_response.get("trace", {}) or {}).get("control_mode", "")),
        "violation_count": int(best_response.get("violation_count", 1)),
        "feasible": int(best_response.get("violation_count", 1)) == 0,
        "solution_signature_hash": solution_signature_hash(best_solution),
        "operator_counts": {},
        "destroy_counts": destroy_counts,
        "repair_counts": repair_counts,
        "q_ratio_counts": q_ratio_counts,
    }
    return normalize_result_row(row)


def _csv_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["feasible"] = int(bool(out["feasible"]))
    for key in ("operator_counts", "destroy_counts", "repair_counts", "q_ratio_counts"):
        out[key] = json.dumps(out.get(key, {}), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return out


def _inc(counts: dict[str, int], key: str) -> None:
    if not key:
        return
    counts[key] = int(counts.get(key, 0)) + 1


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes"}:
        return True
    if text in {"0", "false", "no", ""}:
        return False
    return bool(value)


def _outcome_index(info: dict[str, Any]) -> int:
    if info.get("improved_best"):
        return 0
    if info.get("improved_current"):
        return 1
    if info.get("accepted"):
        return 2
    return 3


def _np_rng(seed: int):
    import numpy as np

    return np.random.default_rng(int(seed))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_path(path: str | Path, repo_root: Path) -> Path:
    value = Path(path)
    if not value.is_absolute():
        value = repo_root / value
    return value.resolve()
