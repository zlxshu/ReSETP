#!/usr/bin/env python3
"""ReSETP root control console — one-click entry for VS Code / terminal.

Edit:
  - CONTROL_CONSOLE.yaml      → what to run (batch / select / range)
  - PARAMETERS_CONSOLE.yaml   → how to run (params, paths, figure style)

Then:
  - VS Code: open this file → Run Python File / F5 (launch: ReSETP Control Console)
  - Terminal: python CONTROL_CONSOLE.py
  - Flags:    python CONTROL_CONSOLE.py --dry-run
              python CONTROL_CONSOLE.py --mode select --live
              python CONTROL_CONSOLE.py --list
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure repo root is importable when launched from VS Code with cwd=repo.
REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from console.config import (  # noqa: E402
    DEFAULT_CONTROL,
    DEFAULT_PARAMS,
    apply_env_overrides,
    load_yaml,
    resolve_repo_root,
)
from console.planner import plan_jobs  # noqa: E402
from console.registry import ARTIFACT_ORDER, EXPERIMENT_ORDER  # noqa: E402
from console.runner import ensure_io_tree, preflight, run_job, write_run_report  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ReSETP control console")
    p.add_argument("--control", type=Path, default=DEFAULT_CONTROL, help="Path to CONTROL_CONSOLE.yaml")
    p.add_argument("--params", type=Path, default=DEFAULT_PARAMS, help="Path to PARAMETERS_CONSOLE.yaml")
    p.add_argument("--mode", choices=["batch", "select", "range"], default=None, help="Override mode")
    p.add_argument("--dry-run", action="store_true", help="Force dry-run (no heavy solvers)")
    p.add_argument("--live", action="store_true", help="Force live hooks (overrides yaml dry_run)")
    p.add_argument("--list", action="store_true", help="List experiments/artifacts and exit")
    p.add_argument("--self-check", action="store_true", help="Validate YAML + IO tree + preflight only")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.list:
        print("Experiments:", ", ".join(EXPERIMENT_ORDER))
        print("Artifacts:  ", ", ".join(ARTIFACT_ORDER))
        print("Modes:      batch | select | range")
        print("Console:    ", DEFAULT_CONTROL)
        print("Parameters: ", DEFAULT_PARAMS)
        return 0

    try:
        control = apply_env_overrides(load_yaml(args.control))
        params = load_yaml(args.params)
    except Exception as exc:  # noqa: BLE001
        print(f"[CONTROL] FAIL load config: {exc}", file=sys.stderr)
        return 2

    if args.mode:
        control["mode"] = args.mode
    if args.live:
        control["dry_run"] = False
    if args.dry_run:
        control["dry_run"] = True

    repo = resolve_repo_root(params)
    io_paths = ensure_io_tree(repo, params)

    print("=== ReSETP Control Console ===")
    print(f"repo:     {repo}")
    print(f"control:  {args.control}")
    print(f"params:   {args.params}")
    print(f"mode:     {control.get('mode')}")
    print(f"dry_run:  {control.get('dry_run', True)}")
    print(f"input:    {io_paths['input_root']}")
    print(f"output:   {io_paths['output_root']}")

    try:
        notes = preflight(repo, params)
        for line in notes:
            print(f"[preflight] {line}")
        jobs = plan_jobs(control)
    except Exception as exc:  # noqa: BLE001
        print(f"[CONTROL] FAIL plan: {exc}", file=sys.stderr)
        return 2

    print(f"[plan] {len(jobs)} job(s):")
    for j in jobs:
        inst = f" instances={list(j.instances)}" if j.instances else " instances=<formal default>"
        print(f"  - {j.job_id}: {j.experiment}/{j.artifact} ({j.kind}){inst}")

    if args.self_check:
        print("[CONTROL] self-check OK (no jobs executed)")
        return 0

    dry_run = bool(control.get("dry_run", True))
    on_error = str(control.get("on_error", "halt")).lower()
    results = []
    for job in jobs:
        print(f"[run] {job.job_id} ...")
        result = run_job(repo, params, job, dry_run=dry_run)
        results.append(result)
        print(f"      -> {result.status} ({result.seconds:.2f}s) {result.message}")
        if result.status == "ERROR" and on_error == "halt":
            print("[CONTROL] halt on error", file=sys.stderr)
            break

    report = write_run_report(
        repo,
        params,
        results,
        meta={
            "mode": control.get("mode"),
            "dry_run": dry_run,
            "control_file": str(args.control),
            "params_file": str(args.params),
        },
    )
    print(f"[report] {report}")

    errors = sum(1 for r in results if r.status == "ERROR")
    if errors:
        print(f"[CONTROL] DONE with {errors} error(s)", file=sys.stderr)
        return 1
    print("[CONTROL] DONE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
