"""Winner-kernel nondeterminism diagnostics for the PPO lane.

This runner writes only under ``solver/reports/dr_alns_ppo_v2/restoration``.
It does not mutate cost, constraint, or winner public-API semantics.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import io
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from typing import Any

from .alns_crush import INSTANCE_DIRS


RESTORATION_DIR = Path("solver/reports/dr_alns_ppo_v2/restoration")
TARGET_INSTANCE = "100-01-24h"
TARGET_BUNDLE_FILTER = "E-UK100_01"
GOLD_SEED2_COST = 4779.053444002934
GOLD_MEAN_COST = 4878.331796187524
DEFAULT_EVAL_BUDGET = 16_000
DEFAULT_MAX_RUNTIME_SECONDS = 900.0
DEFAULT_SEED = 2
EPS = 1e-9


@dataclass(frozen=True)
class ContextSpec:
    context_id: str
    python_env: str
    mode: str
    algorithms: str = "official_winner_kernel"
    jobs: int = 1


PHASE_ONE_CONTEXTS: tuple[ContextSpec, ...] = (
    ContextSpec("system_direct", "system", "direct"),
    ContextSpec("system_processpool", "system", "processpool"),
    ContextSpec("venv_direct", "venv", "direct"),
    ContextSpec("venv_official_wrapper", "venv", "official_wrapper"),
    ContextSpec("venv_evaluate_policy_official_jobs1", "venv", "evaluate_policy", "official_winner_kernel", 1),
    ContextSpec("venv_evaluate_policy_combo_jobs1", "venv", "evaluate_policy", "alpha_ucb_env,official_winner_kernel", 1),
    ContextSpec("venv_evaluate_policy_combo_jobs2", "venv", "evaluate_policy", "alpha_ucb_env,official_winner_kernel", 2),
)


def collect_env_fingerprint(repo_root: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Collect Python/numpy/ALNS fingerprints for system Python and RL venv."""

    root = Path(repo_root)
    out = _ensure_output_dir(output_dir)
    fingerprints = {
        "system": _fingerprint_for_python(root, _python_for_env(root, "system"), _pythonpath_for_env(root, "system")),
        "venv": _fingerprint_for_python(root, _python_for_env(root, "venv"), _pythonpath_for_env(root, "venv")),
    }
    result = {
        "schema_version": "winner-nondeterminism-env-fingerprint.v1",
        "commit": _git(["rev-parse", "HEAD"], root).strip(),
        "fingerprints": fingerprints,
    }
    _write_json(out / "phase1_env_fingerprints.json", result)
    return result


def run_phase1_matrix(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seed: int = DEFAULT_SEED,
    eval_budget: int = DEFAULT_EVAL_BUDGET,
    max_runtime_seconds: float = DEFAULT_MAX_RUNTIME_SECONDS,
    repeats: int = 3,
    workers: int = 1,
) -> dict[str, Any]:
    """Run the context matrix and classify the observed drift pattern."""

    root = Path(repo_root)
    out = _ensure_output_dir(output_dir)
    collect_env_fingerprint(root, out)
    tasks: list[tuple[ContextSpec, int]] = [
        (context, repeat)
        for context in PHASE_ONE_CONTEXTS
        for repeat in range(1, int(repeats) + 1)
    ]
    started = time.perf_counter()
    rows = _run_tasks(
        tasks,
        lambda task: _run_context_once(
            root,
            out,
            task[0],
            repeat=task[1],
            seed=int(seed),
            eval_budget=int(eval_budget),
            max_runtime_seconds=float(max_runtime_seconds),
        ),
        workers=int(workers),
    )
    rows.sort(key=lambda row: (str(row["context_id"]), int(row["repeat"])))
    classification = classify_context_matrix(rows)
    result = {
        "schema_version": "winner-nondeterminism-context-matrix.v1",
        "gate": "PASS_CONTEXT_MATRIX_CLASSIFIED",
        "commit": _git(["rev-parse", "HEAD"], root).strip(),
        "seed": int(seed),
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "repeats": int(repeats),
        "elapsed_seconds": time.perf_counter() - started,
        "classification": classification,
        "rows": rows,
    }
    _write_csv(out / "phase1_context_matrix.csv", rows)
    _write_json(out / "phase1_context_matrix.json", result)
    (out / "phase1_context_matrix.md").write_text(_phase1_report(result), encoding="utf-8")
    append_log(
        out,
        phase="Phase 1",
        command=(
            "python -m setp_solver.search.winner_nondeterminism phase1 "
            f"--seed {seed} --eval-budget {eval_budget} --max-runtime-seconds {max_runtime_seconds} "
            f"--repeats {repeats} --workers {workers}"
        ),
        stdout=(
            f"classification={classification['classification']} "
            f"system={classification.get('system_anchor')} venv={classification.get('venv_anchor')}"
        ),
        stderr="",
        conclusion=str(classification["conclusion"]),
    )
    return result


def write_skipped_bisect(repo_root: str | Path, output_dir: str | Path, classification: dict[str, Any]) -> dict[str, Any]:
    """Write Phase 2/3 skipped artifacts when evidence points to environment drift."""

    root = Path(repo_root)
    out = _ensure_output_dir(output_dir)
    rows = [
        {
            "probe_id": "phase2_skipped",
            "status": "skipped",
            "reason": classification["classification"],
            "conclusion": classification["conclusion"],
        }
    ]
    result = {
        "schema_version": "winner-nondeterminism-bisect.v1",
        "commit": _git(["rev-parse", "HEAD"], root).strip(),
        "classification": classification,
        "rows": rows,
    }
    _write_csv(out / "phase2_bisect_probes.csv", rows)
    _write_json(out / "phase2_bisect_probes.json", result)
    (out / "phase2_bisect_probes.md").write_text(
        "# Phase 2 Bisect Probes\n\n"
        f"- status: `skipped`\n"
        f"- reason: `{classification['classification']}`\n"
        f"- conclusion: {classification['conclusion']}\n",
        encoding="utf-8",
    )
    (out / "phase3_root_cause.md").write_text(_root_cause_report(classification), encoding="utf-8")
    append_log(
        out,
        phase="Phase 2/3",
        command="python -m setp_solver.search.winner_nondeterminism phase2-skipped",
        stdout=f"classification={classification['classification']}",
        stderr="",
        conclusion=str(classification["conclusion"]),
    )
    return result


def run_phase4_venv_anchor(
    repo_root: str | Path,
    output_dir: str | Path,
    *,
    seeds: list[int],
    eval_budget: int = DEFAULT_EVAL_BUDGET,
    max_runtime_seconds: float = DEFAULT_MAX_RUNTIME_SECONDS,
    workers: int = 1,
) -> dict[str, Any]:
    """Build the RL-venv deterministic anchor for environment-drift cases."""

    root = Path(repo_root)
    out = _ensure_output_dir(output_dir)
    started = time.perf_counter()
    tasks = [("official_winner_kernel", int(seed)) for seed in seeds] + [("scikit-opt-SA", int(seed)) for seed in seeds]
    rows = _run_tasks(
        tasks,
        lambda task: _run_phase4_task(
            root,
            out,
            algorithm=str(task[0]),
            seed=int(task[1]),
            eval_budget=int(eval_budget),
            max_runtime_seconds=float(max_runtime_seconds),
        ),
        workers=int(workers),
    )
    rows.sort(key=lambda row: (str(row["algorithm"]), int(row["seed"])))
    alpha_seed2 = _run_evaluate_policy(
        root,
        out / "phase4_alpha_seed2",
        seed=DEFAULT_SEED,
        eval_budget=int(eval_budget),
        max_runtime_seconds=float(max_runtime_seconds),
        algorithms="alpha_ucb_env",
        jobs=1,
        python_env="venv",
    )
    for alpha_row in alpha_seed2["algorithm_rows"]:
        alpha_row = dict(alpha_row)
        alpha_row["context_id"] = "phase4_alpha_seed2"
        alpha_row["repeat"] = 1
        alpha_row["python_env"] = "venv"
        rows.append(_phase4_row_from_eval_policy(alpha_row))
    summary = _phase4_summary(rows)
    result = {
        "schema_version": "winner-nondeterminism-venv-anchor.v1",
        "commit": _git(["rev-parse", "HEAD"], root).strip(),
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "elapsed_seconds": time.perf_counter() - started,
        "summary": summary,
        "rows": rows,
    }
    _write_csv(out / "phase4_determinism_matrix.csv", rows)
    _write_json(out / "phase4_determinism_matrix.json", result)
    _write_json(out / "venv_winner_anchor.json", result)
    (out / "phase4_determinism_matrix.md").write_text(_phase4_report(result), encoding="utf-8")
    append_log(
        out,
        phase="Phase 4",
        command=(
            "python -m setp_solver.search.winner_nondeterminism phase4 "
            f"--seeds {','.join(str(seed) for seed in seeds)} --eval-budget {eval_budget}"
        ),
        stdout=(
            f"winner_mean={summary.get('winner_mean')} sa_mean={summary.get('fair_sa_mean')} "
            f"gate={summary.get('gate')}"
        ),
        stderr="",
        conclusion=str(summary.get("conclusion", "")),
    )
    return result


def write_phase5_self_check(
    repo_root: str | Path,
    output_dir: str | Path,
    phase1: dict[str, Any],
    phase4: dict[str, Any] | None,
) -> dict[str, Any]:
    """Write the no-training PPO self-check gate."""

    root = Path(repo_root)
    out = _ensure_output_dir(output_dir)
    classification = dict(phase1["classification"])
    phase4_summary = dict((phase4 or {}).get("summary") or {})
    environment_drift = classification.get("classification") == "environment_numeric_drift"
    if environment_drift and phase4_summary.get("gate") == "PASS_VENV_SELF_CHECK":
        gate = "PASS_VENV_SELF_CHECK"
        reason = "RL venv has an internally deterministic winner anchor and beats the venv fair-SA baseline."
    elif environment_drift:
        gate = "HALT_VENV_SELF_CHECK"
        reason = "Environment drift is confirmed, but the RL venv self-check did not pass the venv fairness gate."
    elif classification.get("classification") == "deterministic_same_anchor":
        gate = "PASS_SYSTEM_ANCHOR_SELF_CHECK"
        reason = "All contexts match the system winner anchor."
    else:
        gate = "HALT_CODE_NONDETERMINISM"
        reason = "Same-environment nondeterminism or mixed path drift remains; do not train PPO."
    result = {
        "schema_version": "winner-nondeterminism-self-check.v1",
        "commit": _git(["rev-parse", "HEAD"], root).strip(),
        "gate": gate,
        "started_training": False,
        "reason": reason,
        "phase1_classification": classification,
        "phase4_summary": phase4_summary,
        "system_reference": {
            "seed2_best_cost": GOLD_SEED2_COST,
            "ten_seed_mean_cost": GOLD_MEAN_COST,
        },
    }
    _write_json(out / "phase5_self_check.json", result)
    _write_json(out / "self_check.json", result)
    (out / "gate_report.md").write_text(_gate_report(result), encoding="utf-8")
    append_log(
        out,
        phase="Phase 5",
        command="python -m setp_solver.search.winner_nondeterminism phase5",
        stdout=f"gate={gate}",
        stderr="",
        conclusion=reason,
    )
    return result


def classify_context_matrix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify whether the matrix shows code nondeterminism or environment drift."""

    if not rows:
        raise ValueError("rows must not be empty")
    by_context: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_context.setdefault(str(row["context_id"]), []).append(row)
    context_summary = {context: _context_summary(values) for context, values in sorted(by_context.items())}
    failed = {context: summary for context, summary in context_summary.items() if summary["success_count"] != summary["row_count"]}
    unstable = {context: summary for context, summary in context_summary.items() if not bool(summary["stable"])}
    system_values = [
        float(summary["anchor_best_obj"])
        for context, summary in context_summary.items()
        if str(summary["python_env"]) == "system" and summary["anchor_best_obj"] is not None
    ]
    venv_values = [
        float(summary["anchor_best_obj"])
        for context, summary in context_summary.items()
        if str(summary["python_env"]) == "venv" and summary["anchor_best_obj"] is not None
    ]
    system_anchor = _stable_anchor(system_values)
    venv_anchor = _stable_anchor(venv_values)
    if failed:
        classification = "context_run_failed"
        conclusion = "At least one context failed; fix or document the runner/environment failure before diagnosing determinism."
    elif unstable:
        classification = "code_nondeterminism"
        conclusion = "At least one context is internally unstable across repeats; inspect code-level randomness or ordering."
    elif system_anchor is not None and venv_anchor is not None and abs(system_anchor - venv_anchor) <= EPS:
        classification = "deterministic_same_anchor"
        conclusion = "All successful contexts agree with one deterministic anchor."
    elif system_anchor is not None and venv_anchor is not None:
        classification = "environment_numeric_drift"
        conclusion = "System Python and RL venv are each internally deterministic but converge to different anchors; use environment-local gates."
    else:
        classification = "mixed_context_drift"
        conclusion = "The matrix does not reduce to a clean environment split; continue with targeted bisection before changing code."
    return {
        "classification": classification,
        "conclusion": conclusion,
        "system_anchor": system_anchor,
        "venv_anchor": venv_anchor,
        "system_delta_from_gold": None if system_anchor is None else system_anchor - GOLD_SEED2_COST,
        "venv_delta_from_gold": None if venv_anchor is None else venv_anchor - GOLD_SEED2_COST,
        "failed_contexts": sorted(failed),
        "unstable_contexts": sorted(unstable),
        "context_summary": context_summary,
    }


def self_check_gate_for_summary(classification: dict[str, Any], phase4_summary: dict[str, Any]) -> str:
    """Pure helper used by tests and report generation."""

    if classification.get("classification") == "environment_numeric_drift":
        return "PASS_VENV_SELF_CHECK" if phase4_summary.get("gate") == "PASS_VENV_SELF_CHECK" else "HALT_VENV_SELF_CHECK"
    if classification.get("classification") == "deterministic_same_anchor":
        return "PASS_SYSTEM_ANCHOR_SELF_CHECK"
    return "HALT_CODE_NONDETERMINISM"


def _run_context_once(
    root: Path,
    out: Path,
    context: ContextSpec,
    *,
    repeat: int,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    if context.mode == "direct":
        payload = _run_python_json(
            root,
            _python_for_env(root, context.python_env),
            _pythonpath_for_env(root, context.python_env),
            _direct_script(),
            [str(seed), str(eval_budget), str(max_runtime_seconds)],
            timeout=max(60.0, max_runtime_seconds + 120.0),
        )
    elif context.mode == "processpool":
        payload = _run_python_json(
            root,
            _python_for_env(root, context.python_env),
            _pythonpath_for_env(root, context.python_env),
            _processpool_script(),
            [str(seed), str(eval_budget), str(max_runtime_seconds)],
            timeout=max(60.0, max_runtime_seconds + 120.0),
        )
    elif context.mode == "official_wrapper":
        payload = _run_python_json(
            root,
            _python_for_env(root, context.python_env),
            _pythonpath_for_env(root, context.python_env),
            _official_wrapper_script(),
            [str(seed), str(eval_budget), str(max_runtime_seconds)],
            timeout=max(60.0, max_runtime_seconds + 120.0),
        )
    elif context.mode == "evaluate_policy":
        payload = _run_evaluate_policy(
            root,
            out / "phase1_evaluate_policy" / f"{context.context_id}_repeat{repeat}",
            seed=seed,
            eval_budget=eval_budget,
            max_runtime_seconds=max_runtime_seconds,
            algorithms=context.algorithms,
            jobs=context.jobs,
            python_env=context.python_env,
        )
    else:
        raise ValueError(f"unknown context mode: {context.mode}")
    row = _row_from_payload(context, payload, repeat=repeat)
    row["elapsed_seconds"] = time.perf_counter() - started
    return row


def _run_phase4_task(
    root: Path,
    out: Path,
    *,
    algorithm: str,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
) -> dict[str, Any]:
    if algorithm == "official_winner_kernel":
        payload = _run_python_json(
            root,
            _python_for_env(root, "venv"),
            _pythonpath_for_env(root, "venv"),
            _official_wrapper_script(),
            [str(seed), str(eval_budget), str(max_runtime_seconds)],
            timeout=max(60.0, max_runtime_seconds + 120.0),
        )
        row = _phase4_row_from_payload("official_winner_kernel", payload, seed)
    elif algorithm == "scikit-opt-SA":
        payload = _run_python_json(
            root,
            _python_for_env(root, "venv"),
            _pythonpath_for_env(root, "venv"),
            _sa_script(),
            [str(seed), str(eval_budget), str(max_runtime_seconds)],
            timeout=max(60.0, max_runtime_seconds + 120.0),
        )
        row = _phase4_row_from_payload("scikit-opt-SA", payload, seed)
    else:
        raise ValueError(f"unknown phase4 algorithm: {algorithm}")
    row["output_scope"] = str(out)
    return row


def _run_evaluate_policy(
    root: Path,
    output_dir: Path,
    *,
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
    algorithms: str,
    jobs: int,
    python_env: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(_python_for_env(root, python_env)),
        "-m",
        "dr_alns_ppo.evaluate_policy",
        "--manifest",
        "solver/reports/dr_alns_ppo_v2/training_bundle_manifest.json",
        "--split",
        "formal_eval",
        "--bundle-filter",
        TARGET_BUNDLE_FILTER,
        "--algorithms",
        algorithms,
        "--eval-budget",
        str(eval_budget),
        "--seeds",
        str(seed),
        "--output-dir",
        str(output_dir),
        "--jobs",
        str(jobs),
        "--official-max-runtime-seconds",
        str(max_runtime_seconds),
    ]
    proc = _run_command(
        command,
        cwd=root,
        env=_env_for_pythonpath(root, _pythonpath_for_env(root, python_env)),
        timeout=max(60.0, max_runtime_seconds * max(1, len(algorithms.split(","))) + 180.0),
    )
    csv_path = output_dir / "comparison.csv"
    if not csv_path.exists():
        csv_path = output_dir / "comparison.partial.csv"
    rows = _read_csv(csv_path) if csv_path.exists() else []
    official = next((row for row in rows if row.get("algorithm") == "official_winner_kernel"), None)
    alpha = next((row for row in rows if row.get("algorithm") == "alpha_ucb_env"), None)
    primary = official or alpha or (rows[0] if rows else {})
    return {
        "success": proc.returncode == 0 and bool(primary),
        "best_obj": _float(primary.get("best_obj")),
        "evaluations": _int(primary.get("actual_evals")),
        "candidate_scores": _int(primary.get("candidate_scores")),
        "violation_count": _int(primary.get("violation_count")),
        "feasible": _coerce_bool(primary.get("feasible")),
        "solution_signature_hash": str(primary.get("solution_signature_hash", "")),
        "operator_base_id": str(primary.get("operator_base_id", "")),
        "control_mode": str(primary.get("control_mode", "")),
        "algorithm_rows": rows,
        "alpha_best_obj": None if alpha is None else _float(alpha.get("best_obj")),
        "command": " ".join(command),
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-2000:],
        "stderr_tail": proc.stderr[-2000:],
    }


def _winner_kernel_payload(repo_root: str | Path, seed: int, eval_budget: int, max_runtime_seconds: float) -> dict[str, Any]:
    """Importable worker used by the process-pool context."""

    from .candidates import solution_signature_hash
    from .winner_operators import WinnerKernelConfig, operator_base_id, run_winner_kernel

    root = Path(repo_root)
    result = run_winner_kernel(
        root / INSTANCE_DIRS[TARGET_INSTANCE],
        config=WinnerKernelConfig(
            seed=int(seed),
            eval_budget=int(eval_budget),
            max_runtime_seconds=float(max_runtime_seconds),
        ),
    )
    return {
        "success": True,
        "best_obj": float(result["best_cost"]),
        "evaluations": int(result["evaluations"]),
        "candidate_scores": int(result["evaluations"]),
        "violation_count": int(result["violation_count"]),
        "feasible": bool(result["feasible"]),
        "solution_signature_hash": solution_signature_hash(result["best_solution"]),
        "operator_base_id": operator_base_id,
        "control_mode": "direct_kernel",
        "returncode": 0,
    }


def _direct_script() -> str:
    return r"""
import json
import sys
from pathlib import Path
from setp_solver.search.winner_nondeterminism import _winner_kernel_payload
seed = int(sys.argv[1])
eval_budget = int(sys.argv[2])
max_runtime_seconds = float(sys.argv[3])
payload = _winner_kernel_payload(Path.cwd(), seed, eval_budget, max_runtime_seconds)
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
"""


def _processpool_script() -> str:
    return r"""
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from setp_solver.search.winner_nondeterminism import _winner_kernel_payload
seed = int(sys.argv[1])
eval_budget = int(sys.argv[2])
max_runtime_seconds = float(sys.argv[3])
with ProcessPoolExecutor(max_workers=1) as pool:
    payload = pool.submit(_winner_kernel_payload, Path.cwd(), seed, eval_budget, max_runtime_seconds).result()
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
"""


def _official_wrapper_script() -> str:
    return r"""
import json
import sys
from setp_solver.search.alns_crush import INSTANCE_DIRS
from dr_alns_ppo.baselines import run_official_winner_kernel
seed = int(sys.argv[1])
eval_budget = int(sys.argv[2])
max_runtime_seconds = float(sys.argv[3])
row = run_official_winner_kernel(
    INSTANCE_DIRS["100-01-24h"],
    seed=seed,
    eval_budget=eval_budget,
    max_runtime_seconds=max_runtime_seconds,
)
payload = {
    "success": True,
    "best_obj": float(row["best_obj"]),
    "evaluations": int(row["actual_evals"]),
    "candidate_scores": int(row["candidate_scores"]),
    "violation_count": int(row["violation_count"]),
    "feasible": bool(row["feasible"]),
    "solution_signature_hash": str(row["solution_signature_hash"]),
    "operator_base_id": str(row["operator_base_id"]),
    "control_mode": str(row["control_mode"]),
    "returncode": 0,
}
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
"""


def _sa_script() -> str:
    return r"""
import json
import sys
from setp_solver.search.alns_crush import INSTANCE_DIRS
from setp_solver.search.candidates import run_candidate, solution_signature_hash
from setp_solver.search.bundle import load_search_bundle
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
seed = int(sys.argv[1])
eval_budget = int(sys.argv[2])
max_runtime_seconds = float(sys.argv[3])
result = run_candidate(
    "scikit-opt-SA",
    INSTANCE_DIRS["100-01-24h"],
    seed=seed,
    eval_budget=eval_budget,
    max_runtime_seconds=max_runtime_seconds,
)
bundle = load_search_bundle(INSTANCE_DIRS["100-01-24h"])
violations = check_solution(result.best_solution, bundle.instance, DEFAULT_PRICES) if result.best_solution is not None else ["missing_solution"]
payload = {
    "success": result.best_solution is not None,
    "best_obj": float(result.best_cost) if result.best_cost is not None else float("nan"),
    "evaluations": int(result.evals),
    "candidate_scores": int(result.candidate_scores),
    "violation_count": len(violations),
    "feasible": bool(result.feasible),
    "solution_signature_hash": solution_signature_hash(result.best_solution) if result.best_solution is not None else "",
    "operator_base_id": "",
    "control_mode": "fair_sa",
    "returncode": 0,
}
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
"""


def _fingerprint_for_python(root: Path, python_exe: Path, pythonpath: str) -> dict[str, Any]:
    script = r"""
import contextlib
import io
import json
import os
import sys
payload = {
    "executable": sys.executable,
    "python_version": sys.version,
    "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
    "pythonpath": os.environ.get("PYTHONPATH"),
}
try:
    import numpy as np
    payload["numpy_version"] = np.__version__
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        np.show_config()
    payload["numpy_show_config"] = buf.getvalue()
except Exception as exc:
    payload["numpy_error"] = repr(exc)
try:
    from setp_solver.search.alns_wouda import _make_operator_selector
    selector = _make_operator_selector(6, 3)
    import alns
    payload["alns_module_file"] = getattr(alns, "__file__", "")
    payload["alns_selector_type"] = f"{type(selector).__module__}.{type(selector).__name__}"
except Exception as exc:
    payload["alns_error"] = repr(exc)
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
"""
    payload = _run_python_json(root, python_exe, pythonpath, script, [], timeout=60.0)
    return payload


def _run_python_json(root: Path, python_exe: Path, pythonpath: str, script: str, args: list[str], *, timeout: float) -> dict[str, Any]:
    proc = _run_command(
        [str(python_exe), "-c", script, *args],
        cwd=root,
        env=_env_for_pythonpath(root, pythonpath),
        timeout=timeout,
    )
    payload: dict[str, Any]
    try:
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        payload = json.loads(lines[-1]) if lines else {}
    except Exception as exc:
        payload = {"success": False, "parse_error": repr(exc)}
    payload.setdefault("success", proc.returncode == 0)
    payload["command"] = " ".join([str(python_exe), "-c", "<script>", *args])
    payload["returncode"] = proc.returncode
    payload["stdout_tail"] = proc.stdout[-2000:]
    payload["stderr_tail"] = proc.stderr[-2000:]
    return payload


def _run_command(command: list[str], *, cwd: Path, env: dict[str, str], timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            command,
            returncode=124,
            stdout=exc.stdout if isinstance(exc.stdout, str) else "",
            stderr=(exc.stderr if isinstance(exc.stderr, str) else "") + f"\nTIMEOUT after {timeout}s",
        )


def _row_from_payload(context: ContextSpec, payload: dict[str, Any], *, repeat: int) -> dict[str, Any]:
    algorithms = payload.get("algorithm_rows") or []
    return {
        "context_id": context.context_id,
        "repeat": int(repeat),
        "python_env": context.python_env,
        "mode": context.mode,
        "algorithms": context.algorithms,
        "jobs": int(context.jobs),
        "success": bool(payload.get("success", False)),
        "best_obj": _float(payload.get("best_obj")),
        "alpha_best_obj": _optional_float(payload.get("alpha_best_obj")),
        "evaluations": _int(payload.get("evaluations")),
        "candidate_scores": _int(payload.get("candidate_scores")),
        "violation_count": _int(payload.get("violation_count")),
        "feasible": _coerce_bool(payload.get("feasible")),
        "solution_signature_hash": str(payload.get("solution_signature_hash", "")),
        "operator_base_id": str(payload.get("operator_base_id", "")),
        "control_mode": str(payload.get("control_mode", "")),
        "algorithm_row_count": len(algorithms),
        "returncode": int(payload.get("returncode", 0)),
        "stderr_tail": str(payload.get("stderr_tail", ""))[-500:],
        "stdout_tail": str(payload.get("stdout_tail", ""))[-500:],
    }


def _phase4_row_from_payload(algorithm: str, payload: dict[str, Any], seed: int) -> dict[str, Any]:
    return {
        "algorithm": algorithm,
        "seed": int(seed),
        "python_env": "venv",
        "success": bool(payload.get("success", False)),
        "best_obj": _float(payload.get("best_obj")),
        "evaluations": _int(payload.get("evaluations")),
        "candidate_scores": _int(payload.get("candidate_scores")),
        "violation_count": _int(payload.get("violation_count")),
        "feasible": _coerce_bool(payload.get("feasible")),
        "solution_signature_hash": str(payload.get("solution_signature_hash", "")),
        "operator_base_id": str(payload.get("operator_base_id", "")),
        "control_mode": str(payload.get("control_mode", "")),
        "returncode": int(payload.get("returncode", 0)),
        "stderr_tail": str(payload.get("stderr_tail", ""))[-500:],
    }


def _phase4_row_from_eval_policy(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "algorithm": str(row.get("algorithm", "")),
        "seed": _int(row.get("seed")),
        "python_env": "venv",
        "success": True,
        "best_obj": _float(row.get("best_obj")),
        "evaluations": _int(row.get("actual_evals")),
        "candidate_scores": _int(row.get("candidate_scores")),
        "violation_count": _int(row.get("violation_count")),
        "feasible": _coerce_bool(row.get("feasible")),
        "solution_signature_hash": str(row.get("solution_signature_hash", "")),
        "operator_base_id": str(row.get("operator_base_id", "")),
        "control_mode": str(row.get("control_mode", "")),
        "returncode": 0,
        "stderr_tail": "",
    }


def _context_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    successes = [row for row in rows if bool(row.get("success"))]
    values = [float(row["best_obj"]) for row in successes if math.isfinite(float(row["best_obj"]))]
    stable = bool(values) and len(successes) == len(rows) and max(values) - min(values) <= EPS
    return {
        "python_env": rows[0]["python_env"] if rows else "",
        "row_count": len(rows),
        "success_count": len(successes),
        "stable": stable,
        "anchor_best_obj": values[0] if stable else None,
        "min_best_obj": min(values) if values else None,
        "max_best_obj": max(values) if values else None,
        "zero_violation_count": sum(1 for row in successes if int(row.get("violation_count", 1)) == 0),
    }


def _stable_anchor(values: list[float]) -> float | None:
    if not values:
        return None
    if max(values) - min(values) > EPS:
        return None
    return values[0]


def _phase4_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_alg: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_alg.setdefault(str(row["algorithm"]), []).append(row)
    winner_rows = by_alg.get("official_winner_kernel", [])
    sa_rows = by_alg.get("scikit-opt-SA", [])
    winner_costs = [float(row["best_obj"]) for row in winner_rows if row.get("success")]
    sa_costs = [float(row["best_obj"]) for row in sa_rows if row.get("success")]
    zero_violations = all(int(row.get("violation_count", 1)) == 0 for row in winner_rows)
    winner_mean = statistics.fmean(winner_costs) if winner_costs else None
    fair_sa_mean = statistics.fmean(sa_costs) if sa_costs else None
    beats_sa = winner_mean is not None and fair_sa_mean is not None and winner_mean < fair_sa_mean
    gate = "PASS_VENV_SELF_CHECK" if winner_costs and sa_costs and zero_violations and beats_sa else "HALT_VENV_SELF_CHECK"
    return {
        "gate": gate,
        "winner_seed_count": len(winner_costs),
        "fair_sa_seed_count": len(sa_costs),
        "winner_mean": winner_mean,
        "fair_sa_mean": fair_sa_mean,
        "winner_best": min(winner_costs) if winner_costs else None,
        "fair_sa_best": min(sa_costs) if sa_costs else None,
        "winner_zero_violations": zero_violations,
        "winner_beats_fair_sa": beats_sa,
        "conclusion": "RL venv winner is internally usable for the PPO gate." if gate.startswith("PASS") else "RL venv winner does not pass the same-environment PPO gate.",
    }


def _phase1_report(result: dict[str, Any]) -> str:
    classification = result["classification"]
    lines = [
        "# Phase 1 Context Matrix",
        "",
        f"- classification: `{classification['classification']}`",
        f"- conclusion: {classification['conclusion']}",
        f"- system_anchor: {classification.get('system_anchor')}",
        f"- venv_anchor: {classification.get('venv_anchor')}",
        f"- failed_contexts: {classification.get('failed_contexts')}",
        f"- unstable_contexts: {classification.get('unstable_contexts')}",
        "",
        "## Rows",
    ]
    for row in result["rows"]:
        lines.append(
            f"- {row['context_id']} repeat {row['repeat']}: success={row['success']} "
            f"best={row['best_obj']} evals={row['evaluations']} violations={row['violation_count']} "
            f"signature={row['solution_signature_hash']}"
        )
    return "\n".join(lines)


def _root_cause_report(classification: dict[str, Any]) -> str:
    if classification["classification"] == "environment_numeric_drift":
        body = (
            "System Python and the RL venv are each internally deterministic, but they converge to different anchors. "
            "Per policy, do not change dependencies; use environment-local PPO gates."
        )
    else:
        body = str(classification["conclusion"])
    return "\n".join(
        [
            "# Phase 3 Root Cause",
            "",
            f"- classification: `{classification['classification']}`",
            f"- system_anchor: {classification.get('system_anchor')}",
            f"- venv_anchor: {classification.get('venv_anchor')}",
            f"- conclusion: {body}",
        ]
    )


def _phase4_report(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# Phase 4 Determinism Matrix",
        "",
        f"- gate: `{summary['gate']}`",
        f"- winner_mean: {summary.get('winner_mean')}",
        f"- fair_sa_mean: {summary.get('fair_sa_mean')}",
        f"- winner_zero_violations: {summary.get('winner_zero_violations')}",
        f"- conclusion: {summary.get('conclusion')}",
        "",
        "## Rows",
    ]
    for row in result["rows"]:
        lines.append(
            f"- {row['algorithm']} seed {row['seed']}: success={row['success']} "
            f"best={row['best_obj']} evals={row['evaluations']} violations={row['violation_count']}"
        )
    return "\n".join(lines)


def _gate_report(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Winner Nondeterminism PPO Gate",
            "",
            f"- gate: `{result['gate']}`",
            f"- started_training: `{result['started_training']}`",
            f"- reason: {result['reason']}",
            f"- phase1_classification: `{result['phase1_classification']['classification']}`",
            f"- system_seed2_reference: {result['system_reference']['seed2_best_cost']}",
            f"- system_10seed_reference: {result['system_reference']['ten_seed_mean_cost']}",
        ]
    )


def append_log(output_dir: str | Path, *, phase: str, command: str, stdout: str, stderr: str, conclusion: str) -> None:
    path = Path(output_dir) / "nondeterminism_log.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    commit_hash = "unknown"
    try:
        commit_hash = _git(["rev-parse", "HEAD"], _repo_root()).strip()
    except Exception:
        pass
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Winner Kernel Nondeterminism Diagnosis Log\n"
    entry = (
        f"\n## {phase} - {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"- Commit: `{commit_hash}`\n"
        f"- Command: `{command}`\n"
        f"- Stdout: `{stdout}`\n"
        f"- Stderr: `{stderr}`\n"
        f"- Conclusion: {conclusion}\n"
    )
    path.write_text(existing.rstrip() + "\n" + entry, encoding="utf-8")


def _run_tasks(tasks: list[Any], func: Any, *, workers: int) -> list[dict[str, Any]]:
    if int(workers) <= 1 or len(tasks) <= 1:
        return [func(task) for task in tasks]
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(int(workers), len(tasks))) as pool:
        futures = [pool.submit(func, task) for task in tasks]
        for future in as_completed(futures):
            results.append(future.result())
    return results


def _ensure_output_dir(output_dir: str | Path) -> Path:
    out = Path(output_dir)
    expected = RESTORATION_DIR.as_posix()
    if expected not in out.as_posix():
        raise ValueError(f"output_dir must be under {expected}: {out}")
    out.mkdir(parents=True, exist_ok=True)
    return out


def _python_for_env(root: Path, python_env: str) -> Path:
    if python_env == "system":
        return Path(sys.executable)
    if python_env == "venv":
        return root / "solver" / "rl" / ".venv" / "bin" / "python"
    raise ValueError(f"unknown python_env: {python_env}")


def _pythonpath_for_env(root: Path, python_env: str) -> str:
    entries = [root / "solver" / "src", root / "models" / "src"]
    if python_env == "venv":
        entries.insert(0, root / "solver" / "rl")
    return os.pathsep.join(str(path) for path in entries)


def _env_for_pythonpath(root: Path, pythonpath: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONPATH"] = pythonpath
    env["PYTHONNOUSERSITE"] = "1"
    env.setdefault("SETP_ALNS_PARALLEL_WORKERS", "1")
    env["SETP_REPO_ROOT"] = str(root)
    return env


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)
    return proc.stdout


def _write_json(path: str | Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({field for row in rows for field in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _read_csv(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    result = _float(value)
    return result if math.isfinite(result) else None


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


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


def _parse_seed_list(value: str) -> list[int]:
    seeds: list[int] = []
    for item in str(value).split(","):
        item = item.strip()
        if not item:
            continue
        if "-" in item:
            left, right = item.split("-", 1)
            seeds.extend(range(int(left), int(right) + 1))
        else:
            seeds.append(int(item))
    if not seeds:
        raise ValueError("at least one seed is required")
    return seeds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose winner-kernel determinism across Python contexts.")
    parser.add_argument("stage", choices=["fingerprint", "phase1", "phase2-skipped", "phase4", "phase5", "run-all"])
    parser.add_argument("--repo-root", default=str(_repo_root()))
    parser.add_argument("--output-dir", default=str(_repo_root() / RESTORATION_DIR))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--seeds", default="1-10")
    parser.add_argument("--eval-budget", type=int, default=DEFAULT_EVAL_BUDGET)
    parser.add_argument("--max-runtime-seconds", type=float, default=DEFAULT_MAX_RUNTIME_SECONDS)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)
    root = Path(args.repo_root)
    out = Path(args.output_dir)
    if args.stage == "fingerprint":
        result = collect_env_fingerprint(root, out)
    elif args.stage == "phase1":
        result = run_phase1_matrix(
            root,
            out,
            seed=args.seed,
            eval_budget=args.eval_budget,
            max_runtime_seconds=args.max_runtime_seconds,
            repeats=args.repeats,
            workers=args.workers,
        )
    elif args.stage == "phase2-skipped":
        phase1 = json.loads((out / "phase1_context_matrix.json").read_text(encoding="utf-8"))
        result = write_skipped_bisect(root, out, phase1["classification"])
    elif args.stage == "phase4":
        result = run_phase4_venv_anchor(
            root,
            out,
            seeds=_parse_seed_list(args.seeds),
            eval_budget=args.eval_budget,
            max_runtime_seconds=args.max_runtime_seconds,
            workers=args.workers,
        )
    elif args.stage == "phase5":
        phase1 = json.loads((out / "phase1_context_matrix.json").read_text(encoding="utf-8"))
        phase4_path = out / "phase4_determinism_matrix.json"
        phase4 = json.loads(phase4_path.read_text(encoding="utf-8")) if phase4_path.exists() else None
        result = write_phase5_self_check(root, out, phase1, phase4)
    else:
        phase1 = run_phase1_matrix(
            root,
            out,
            seed=args.seed,
            eval_budget=args.eval_budget,
            max_runtime_seconds=args.max_runtime_seconds,
            repeats=args.repeats,
            workers=args.workers,
        )
        classification = phase1["classification"]
        phase4: dict[str, Any] | None = None
        if classification["classification"] == "environment_numeric_drift":
            write_skipped_bisect(root, out, classification)
            phase4 = run_phase4_venv_anchor(
                root,
                out,
                seeds=_parse_seed_list(args.seeds),
                eval_budget=args.eval_budget,
                max_runtime_seconds=args.max_runtime_seconds,
                workers=args.workers,
            )
        elif classification["classification"] == "deterministic_same_anchor":
            write_skipped_bisect(root, out, classification)
        result = write_phase5_self_check(root, out, phase1, phase4)
    print(f"GATE WINNER_NONDETERMINISM {args.stage} {json.dumps(_brief_result(result), ensure_ascii=False)}")
    return 0


def _brief_result(result: dict[str, Any]) -> dict[str, Any]:
    keys = ["gate", "classification", "summary", "commit", "reason"]
    return {key: result[key] for key in keys if key in result}


if __name__ == "__main__":
    raise SystemExit(main())
