#!/usr/bin/env python3
"""S1: preregistered three-view China81 feasibility/discrimination gate.

This runner intentionally imports the frozen P3 runner and reuses its mother
single-view convergence logic. It only changes ``route_proxy_mode`` and writes
new evidence under ``p2p3_threeview/preflight_gate``; it never touches P3 rows.
"""
from __future__ import annotations

import csv
import hashlib
import json
import multiprocessing as mp
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = ROOT / "baselines/e2_final_campaign_20260720/mv_hgs_sp_final"
OUT = Path(__file__).resolve().parent
P3_PATH = PACKAGE / "run_p3_china81_formal.py"
INSTANCE_IDS = (
    "cn-cy-25c-01-V2-LOCATIONS",
    "cn-prd-75c-01-V2-LOCATIONS",
    "cn-cy-200c-01-V2-LOCATIONS",
)
MODES = ("cv_only", "naive_ev", "mechanism_ev")
SEED = 1
WORKERS = 6

for path in (ROOT / "solver/src", PACKAGE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_p3_china81_formal as p3  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNAVAILABLE"


def _protected_hashes() -> dict[str, str]:
    paths = [
        ROOT / "solver/src/setp_solver/cost.py",
        ROOT / "solver/src/setp_solver/check.py",
        ROOT / "solver/src/setp_solver/search/evaluation.py",
        ROOT / "solver/src/setp_solver/prices.py",
        ROOT / "docs/paper_submission_final/paper_main.tex",
        P3_PATH,
    ]
    return {
        str(path.relative_to(ROOT)): _sha256(path)
        for path in paths
        if path.exists()
    }


def _serialize_violations(violations: Any) -> list[str]:
    try:
        return [str(item) for item in violations]
    except TypeError:
        return [str(violations)]


def _run_unit(args: tuple[str, str]) -> dict[str, Any]:
    instance_id, mode = args
    started = perf_counter()
    row: dict[str, Any] = {
        "instance_id": instance_id,
        "tier": p3._tier_of(instance_id),
        "seed": SEED,
        "route_proxy_mode": mode,
        "status": "ERROR",
        "cost": None,
        "cpu_seconds": None,
        "hgs_elapsed_seconds": None,
        "hgs_iterations": None,
        "violation_count": None,
        "violations": "",
        "error_type": "",
        "error": "",
    }
    try:
        caps = p3.TIER_CAPS[p3._tier_of(instance_id)]
        bundle = p3.load_china81_bundle(ROOT, instance_id)
        common = p3.complete_china81_route_skeleton(
            p3.build_initial_solution(
                bundle.instance,
                bundle.time_profile,
                bundle.prices,
                introduce_ev=False,
                require_charging_signal=False,
            ),
            bundle,
        )
        problem = p3.build_pyvrp_problem(bundle, route_proxy_mode=mode)
        stop = p3.MultipleCriteria(
            [p3.NoImprovement(int(caps["K_M"])), p3.MaxRuntime(caps["CAP_M"])]
        )
        epoch = p3._run_epoch(
            bundle,
            problem,
            common.solution,
            seed=SEED,
            stop=stop,
            warm_elites=(),
        )
        completion = min(
            (*epoch.elite_completions, common),
            key=lambda item: item.objective,
        )
        objective, _breakdown, violations = p3.exact_china81_score(
            completion.solution, bundle
        )
        row.update(
            {
                "status": "OK" if not violations else "INFEASIBLE",
                "cost": float(objective),
                "cpu_seconds": perf_counter() - started,
                "hgs_elapsed_seconds": float(epoch.elapsed_seconds),
                "hgs_iterations": int(epoch.stats.get("hgs_iterations", -1)),
                "violation_count": len(violations),
                "violations": json.dumps(
                    _serialize_violations(violations), ensure_ascii=False
                ),
            }
        )
        if violations:
            row["error_type"] = "EXACT_SCORE_VIOLATION"
            row["error"] = "complete/exact scoring returned violations"
    except Exception as exc:  # preserve every failed unit as a raw row
        row.update(
            {
                "cpu_seconds": perf_counter() - started,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
    return row


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_raw(rows: list[dict[str, Any]]) -> Path:
    path = OUT / "raw_runs.csv"
    fields = [
        "instance_id",
        "tier",
        "seed",
        "route_proxy_mode",
        "status",
        "cost",
        "cpu_seconds",
        "hgs_elapsed_seconds",
        "hgs_iterations",
        "violation_count",
        "violations",
        "error_type",
        "error",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _decision(rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected = len(INSTANCE_IDS) * len(MODES)
    ok_rows = [row for row in rows if row["status"] == "OK"]
    infeasible = [row for row in rows if row["status"] != "OK"]
    large = {
        row["route_proxy_mode"]: float(row["cost"])
        for row in ok_rows
        if row["instance_id"] == "cn-cy-200c-01-V2-LOCATIONS"
    }
    distinct_large = len(set(large.values()))
    if len(rows) != expected:
        verdict = "HALT_S1_INCOMPLETE_RAW_ROWS"
        reason = f"expected {expected} rows, observed {len(rows)}"
    elif infeasible:
        verdict = "HALT_S1_VIEW_INFEASIBLE_OR_ERROR"
        reason = "one or more views failed completion/exact feasibility"
    elif distinct_large < 2:
        verdict = "HALT_S1_NO_VIEW_DISCRIMINATION"
        reason = "200-customer exact costs collapsed to one value"
    else:
        verdict = "PASS_S1_THREEVIEW_PREFLIGHT"
        reason = (
            "all three views are exactly feasible and the 200-customer costs have "
            f"{distinct_large} distinct value(s)"
        )
    return {
        "schema_version": "resetp.e2-final-campaign.s1-threeview-preflight.v1",
        "decision": verdict,
        "reason": reason,
        "expected_rows": expected,
        "observed_rows": len(rows),
        "ok_rows": len(ok_rows),
        "non_ok_rows": len(infeasible),
        "large_instance_costs": large,
        "large_instance_distinct_cost_count": distinct_large,
        "all_exact_scores_feasible": not infeasible and len(ok_rows) == expected,
        "claim_boundary": (
            "S1 is a preflight feasibility/discrimination gate only. It does not "
            "support a superiority claim and does not authorize changing the "
            "route proxies, evaluator, instance, or stopping rules."
        ),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tasks = [(instance_id, mode) for instance_id in INSTANCE_IDS for mode in MODES]
    print(
        f"[S1] starting {len(tasks)} independent units with {WORKERS} workers",
        flush=True,
    )
    with mp.Pool(processes=WORKERS) as pool:
        rows = list(pool.imap_unordered(_run_unit, tasks))
    rows.sort(key=lambda row: (row["instance_id"], row["route_proxy_mode"]))
    raw_path = _write_raw(rows)
    decision = _decision(rows)
    metadata = {
        "schema_version": "resetp.e2-final-campaign.s1-threeview-preflight-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": " ".join([sys.executable, *sys.argv]),
        "git_head": _git_head(),
        "branch": "codex/reporting-pipeline",
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "numpy_version": __import__("numpy").__version__,
        "pyvrp_version": getattr(__import__("pyvrp"), "__version__", "unknown"),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", "UNSET"),
        "workers": WORKERS,
        "seed": SEED,
        "instances": list(INSTANCE_IDS),
        "route_proxy_modes": list(MODES),
        "tier_caps": {str(key): value for key, value in p3.TIER_CAPS.items()},
        "stop_rule": "NoImprovement(K_M) OR MaxRuntime(CAP_M), copied from P3",
        "runner_reused": str(P3_PATH.relative_to(ROOT)),
        "protected_file_sha256": _protected_hashes(),
        "raw_runs_sha256": _sha256(raw_path),
    }
    _write_json(OUT / "metadata.json", metadata)
    _write_json(OUT / "decision.json", decision)
    lines = [
        "# S1 Three-view preflight",
        "",
        f"Decision: `{decision['decision']}`.",
        f"Rows: {decision['observed_rows']}/{decision['expected_rows']}; exact-feasible rows: {decision['ok_rows']}.",
        f"200-customer exact costs: `{json.dumps(decision['large_instance_costs'], ensure_ascii=False, sort_keys=True)}`.",
        f"Reason: {decision['reason']}.",
        "",
        "This gate is feasibility/discrimination evidence only. It does not alter the evaluator, model, instance, or stopping contract.",
    ]
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    hash_paths = [
        P3_PATH,
        OUT / "task_card.md",
        OUT / "run_s1_threeview_preflight.py",
        OUT / "metadata.json",
        raw_path,
        OUT / "decision.json",
        OUT / "report.md",
    ]
    _write_json(
        OUT / "artifact_hashes.json",
        {
            "schema_version": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "appledouble_excluded": True,
            "files": {
                str(path.relative_to(ROOT)): _sha256(path)
                for path in hash_paths
                if path.exists() and not path.name.startswith("._")
            },
        },
    )
    _write_json(
        OUT / "done.json",
        {
            "decision": decision["decision"],
            "raw_rows": decision["observed_rows"],
            "artifact_hashes": "artifact_hashes.json",
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    print(f"[S1] {decision['decision']}", flush=True)
    return 0 if decision["decision"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
