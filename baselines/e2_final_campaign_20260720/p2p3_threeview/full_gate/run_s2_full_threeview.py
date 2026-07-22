#!/usr/bin/env python3
"""S2: full China81 single-view runs for cv_only and naive_ev.

The P3 mother/full columns are read-only reused evidence.  New computation is
limited to the two preregistered route-proxy modes and uses the exact P3
single-view convergence engine.
"""
from __future__ import annotations

import csv
import hashlib
import json
import multiprocessing as mp
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = ROOT / "baselines/e2_final_campaign_20260720/mv_hgs_sp_final"
OUT = Path(__file__).resolve().parent
P3_RAW = PACKAGE / "p3_china81_gate/raw_runs.csv"
S1_DECISION = ROOT / "baselines/e2_final_campaign_20260720/p2p3_threeview/preflight_gate/decision.json"
P3_RUNNER = PACKAGE / "run_p3_china81_formal.py"
MODES = ("cv_only", "naive_ev")
SEEDS = (1, 2, 3, 4, 5)
WORKERS = 6

for path in (ROOT / "solver/src", PACKAGE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_p3_china81_formal as p3  # noqa: E402

RAW_FIELDS = [
    "instance_id", "tier", "seed", "route_proxy_mode", "status", "cost",
    "cpu_seconds", "hgs_elapsed_seconds", "hgs_iterations",
    "violation_count", "violations", "error_type", "error",
    "reused_mechanism_ev_cost", "reused_mechanism_ev_cpu_seconds",
    "reused_mv_hgs_sp_cost", "reused_mv_hgs_sp_cpu_seconds",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True,
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
        P3_RUNNER,
    ]
    return {
        str(path.relative_to(ROOT)): _sha256(path)
        for path in paths if path.exists()
    }


def _serialize_violations(violations: Any) -> list[str]:
    try:
        return [str(item) for item in violations]
    except TypeError:
        return [str(violations)]


def _run_unit(args: tuple[str, int, str]) -> dict[str, Any]:
    instance_id, seed, mode = args
    started = perf_counter()
    row: dict[str, Any] = {
        "instance_id": instance_id,
        "tier": p3._tier_of(instance_id),
        "seed": seed,
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
        "reused_mechanism_ev_cost": None,
        "reused_mechanism_ev_cpu_seconds": None,
        "reused_mv_hgs_sp_cost": None,
        "reused_mv_hgs_sp_cpu_seconds": None,
    }
    try:
        caps = p3.TIER_CAPS[p3._tier_of(instance_id)]
        bundle = p3.load_china81_bundle(ROOT, instance_id)
        common = p3.complete_china81_route_skeleton(
            p3.build_initial_solution(
                bundle.instance, bundle.time_profile, bundle.prices,
                introduce_ev=False, require_charging_signal=False,
            ),
            bundle,
        )
        problem = p3.build_pyvrp_problem(bundle, route_proxy_mode=mode)
        stop = p3.MultipleCriteria(
            [p3.NoImprovement(int(caps["K_M"])), p3.MaxRuntime(caps["CAP_M"])]
        )
        epoch = p3._run_epoch(
            bundle, problem, common.solution, seed=seed, stop=stop,
            warm_elites=(),
        )
        completion = min(
            (*epoch.elite_completions, common), key=lambda item: item.objective
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
    except Exception as exc:  # preserve a failed unit as raw evidence
        row.update(
            {
                "cpu_seconds": perf_counter() - started,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
    return row


def _read_p3_reuse() -> dict[tuple[str, int], dict[str, float]]:
    if not P3_RAW.is_file():
        raise RuntimeError(f"missing read-only P3 raw data: {P3_RAW}")
    rows = list(csv.DictReader(P3_RAW.open(encoding="utf-8")))
    expected_ids = set(p3._instance_list())
    expected_keys = {(instance_id, seed) for instance_id in expected_ids for seed in SEEDS}
    observed: dict[tuple[str, int], dict[str, float]] = {}
    for row in rows:
        key = (row["instance_id"], int(row["seed"]))
        if key in observed:
            raise RuntimeError(f"duplicate P3 reuse key: {key}")
        observed[key] = {
            "mechanism_ev_cost": float(row["mother_cost"]),
            "mechanism_ev_cpu_seconds": float(row["mother_cpu_seconds"]),
            "mv_hgs_sp_cost": float(row["full_cost"]),
            "mv_hgs_sp_cpu_seconds": float(row["full_cpu_seconds"]),
        }
    missing = sorted(expected_keys - set(observed))
    extra = sorted(set(observed) - expected_keys)
    if missing or extra or len(rows) != len(expected_keys):
        raise RuntimeError(
            f"P3 reuse ledger incomplete: rows={len(rows)} expected={len(expected_keys)} "
            f"missing={missing[:3]} extra={extra[:3]}"
        )
    return observed


def _existing_ok_keys(raw_path: Path) -> set[tuple[str, int, str]]:
    if not raw_path.exists():
        return set()
    rows = list(csv.DictReader(raw_path.open(encoding="utf-8")))
    if rows and list(rows[0]) != RAW_FIELDS:
        raise RuntimeError("existing S2 raw schema differs; preserve it and HALT")
    keys: set[tuple[str, int, str]] = set()
    for row in rows:
        key = (row["instance_id"], int(row["seed"]), row["route_proxy_mode"])
        if row["status"] != "OK":
            raise RuntimeError(f"existing S2 raw contains non-OK row: {key}")
        if key in keys:
            raise RuntimeError(f"existing S2 raw contains duplicate key: {key}")
        keys.add(key)
    return keys


def _append_row(raw_path: Path, row: dict[str, Any], *, write_header: bool) -> None:
    with raw_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)
        handle.flush()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _summary_rows(
    raw_rows: list[dict[str, str]],
    reuse: dict[tuple[str, int], dict[str, float]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_key = {
        (row["instance_id"], int(row["seed"],)): row
        for row in raw_rows
    }
    _ = by_key
    detailed: list[dict[str, Any]] = []
    appendix: list[dict[str, Any]] = []
    for instance_id in p3._instance_list():
        new_by_mode: dict[str, list[float]] = {}
        for mode in MODES:
            values = [
                float(row["cost"])
                for row in raw_rows
                if row["instance_id"] == instance_id
                and row["route_proxy_mode"] == mode
                and row["status"] == "OK"
            ]
            new_by_mode[mode] = values
        reused = [reuse[(instance_id, seed)] for seed in SEEDS]

        def stats(values: list[float]) -> tuple[float, float]:
            return min(values), sum(values) / len(values)

        cv_best, cv_avg = stats(new_by_mode["cv_only"])
        naive_best, naive_avg = stats(new_by_mode["naive_ev"])
        mech_best, mech_avg = stats([row["mechanism_ev_cost"] for row in reused])
        full_best, full_avg = stats([row["mv_hgs_sp_cost"] for row in reused])
        n = p3._tier_of(instance_id)
        appendix.append(
            {
                "instance_id": instance_id,
                "n": n,
                "cv_only Best.avg.": f"Best={cv_best:.6f}; Avg={cv_avg:.6f}",
                "naive_ev Best.avg.": f"Best={naive_best:.6f}; Avg={naive_avg:.6f}",
                "mechanism_ev Best.avg.(复用)": f"Best={mech_best:.6f}; Avg={mech_avg:.6f}",
                "MV-HGS-SP Best.avg.(复用)": f"Best={full_best:.6f}; Avg={full_avg:.6f}",
            }
        )
        detailed.append(
            {
                "instance_id": instance_id, "n": n,
                "cv_only_best": cv_best, "cv_only_avg": cv_avg,
                "naive_ev_best": naive_best, "naive_ev_avg": naive_avg,
                "mechanism_ev_best": mech_best, "mechanism_ev_avg": mech_avg,
                "mv_hgs_sp_best": full_best, "mv_hgs_sp_avg": full_avg,
            }
        )
    return appendix, detailed


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _make_decision(
    raw_rows: list[dict[str, str]],
    reuse: dict[tuple[str, int], dict[str, float]],
) -> dict[str, Any]:
    expected = len(p3._instance_list()) * len(SEEDS) * len(MODES)
    keys = [
        (row["instance_id"], int(row["seed"]), row["route_proxy_mode"])
        for row in raw_rows
    ]
    non_ok = [row for row in raw_rows if row["status"] != "OK"]
    violations = [row for row in raw_rows if int(row["violation_count"] or 0) != 0]
    duplicate_count = len(keys) - len(set(keys))
    if len(raw_rows) != expected or duplicate_count:
        verdict = "HALT_S2_INCOMPLETE_OR_DUPLICATE_RAW"
        reason = f"expected {expected} unique new rows, observed {len(raw_rows)}, duplicates {duplicate_count}"
    elif non_ok or violations:
        verdict = "HALT_S2_VIEW_INFEASIBLE_OR_ERROR"
        reason = f"non-OK rows={len(non_ok)}, rows with violations={len(violations)}"
    elif len(reuse) != len(p3._instance_list()) * len(SEEDS):
        verdict = "HALT_S2_P3_REUSE_INCOMPLETE"
        reason = "P3 mechanism/full reuse ledger is incomplete"
    else:
        verdict = "PASS_S2_FULL_THREEVIEW"
        reason = "810 new exact-feasible rows and complete P3 mechanism/full reuse ledger"
    return {
        "schema_version": "resetp.e2-final-campaign.s2-full-threeview.v1",
        "decision": verdict,
        "reason": reason,
        "expected_new_rows": expected,
        "observed_new_rows": len(raw_rows),
        "duplicate_new_key_count": duplicate_count,
        "non_ok_new_rows": len(non_ok),
        "violation_rows": len(violations),
        "p3_reuse_rows": len(reuse),
        "p3_reuse_is_read_only": True,
        "claim_boundary": (
            "S2 produces Appendix A1 descriptive data. It does not authorize a "
            "superiority claim, equal-compute claim, or changes to the evaluator "
            "or route-proxy contract."
        ),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if not S1_DECISION.is_file():
        raise SystemExit(f"missing S1 decision: {S1_DECISION}")
    s1 = json.loads(S1_DECISION.read_text(encoding="utf-8"))
    if s1.get("decision") != "PASS_S1_THREEVIEW_PREFLIGHT":
        decision = {
            "schema_version": "resetp.e2-final-campaign.s2-full-threeview.v1",
            "decision": "HALT_S2_S1_NOT_PASS",
            "reason": f"S1 decision is {s1.get('decision')!r}",
        }
        _write_json(OUT / "decision.json", decision)
        return 2

    reuse = _read_p3_reuse()
    raw_path = OUT / "raw_runs.csv"
    done = _existing_ok_keys(raw_path)
    tasks = [
        (instance_id, seed, mode)
        for instance_id in p3._instance_list()
        for seed in SEEDS
        for mode in MODES
        if (instance_id, seed, mode) not in done
    ]
    print(
        f"[S2] {len(done)} new units complete; {len(tasks)} remaining; "
        f"{WORKERS} workers",
        flush=True,
    )
    write_header = not raw_path.exists()
    if tasks:
        with mp.Pool(processes=WORKERS) as pool:
            for row in pool.imap_unordered(_run_unit, tasks):
                reused_row = reuse[(row["instance_id"], int(row["seed"]))]
                row.update(
                    {
                        "reused_mechanism_ev_cost": reused_row["mechanism_ev_cost"],
                        "reused_mechanism_ev_cpu_seconds": reused_row["mechanism_ev_cpu_seconds"],
                        "reused_mv_hgs_sp_cost": reused_row["mv_hgs_sp_cost"],
                        "reused_mv_hgs_sp_cpu_seconds": reused_row["mv_hgs_sp_cpu_seconds"],
                    }
                )
                _append_row(raw_path, row, write_header=write_header)
                write_header = False
                print(
                    f"[S2] {row['instance_id']} seed={row['seed']} "
                    f"mode={row['route_proxy_mode']} status={row['status']} "
                    f"cost={row['cost']}", flush=True,
                )

    raw_rows = list(csv.DictReader(raw_path.open(encoding="utf-8"))) if raw_path.exists() else []
    decision = _make_decision(raw_rows, reuse)
    appendix, detailed = _summary_rows(raw_rows, reuse) if raw_rows else ([], [])
    appendix_fields = [
        "instance_id", "n", "cv_only Best.avg.", "naive_ev Best.avg.",
        "mechanism_ev Best.avg.(复用)", "MV-HGS-SP Best.avg.(复用)",
    ]
    detail_fields = [
        "instance_id", "n", "cv_only_best", "cv_only_avg", "naive_ev_best",
        "naive_ev_avg", "mechanism_ev_best", "mechanism_ev_avg",
        "mv_hgs_sp_best", "mv_hgs_sp_avg",
    ]
    if detailed:
        _write_csv(OUT / "appendix_a1.csv", appendix, appendix_fields)
        _write_csv(OUT / "appendix_a1_numeric.csv", detailed, detail_fields)
    _write_json(OUT / "decision.json", decision)
    metadata = {
        "schema_version": "resetp.e2-final-campaign.s2-full-threeview-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": " ".join([sys.executable, *sys.argv]),
        "git_head": _git_head(), "branch": "codex/reporting-pipeline",
        "python": sys.version, "python_executable": sys.executable,
        "platform": platform.platform(),
        "numpy_version": __import__("numpy").__version__,
        "pyvrp_version": getattr(__import__("pyvrp"), "__version__", "unknown"),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", "UNSET"),
        "workers": WORKERS, "seeds": list(SEEDS), "route_proxy_modes": list(MODES),
        "instance_count": len(p3._instance_list()),
        "new_unit_count": len(p3._instance_list()) * len(SEEDS) * len(MODES),
        "stop_rule": "NoImprovement(K_M) OR MaxRuntime(CAP_M), copied from P3 mother",
        "runner_reused": str(P3_RUNNER.relative_to(ROOT)),
        "s1_decision_sha256": _sha256(S1_DECISION),
        "p3_raw_runs_sha256": _sha256(P3_RAW),
        "protected_file_sha256": _protected_hashes(),
        "integrity_flags": [],
        "raw_runs_sha256": _sha256(raw_path) if raw_path.exists() else None,
    }
    _write_json(OUT / "metadata.json", metadata)
    report_lines = [
        "# S2 Full three-view China81 gate", "",
        f"Decision: `{decision['decision']}`.",
        f"New rows: {decision['observed_new_rows']}/{decision['expected_new_rows']}; non-OK: {decision['non_ok_new_rows']}; violation rows: {decision['violation_rows']}.",
        f"P3 read-only reuse rows: {decision['p3_reuse_rows']}.", "",
        "`cv_only` and `naive_ev` are the only newly computed arms. `mechanism_ev` and `MV-HGS-SP` are reused from the sealed P3 raw ledger.",
        "This gate is Appendix A1 descriptive evidence only; it does not establish superiority or equal-compute performance.",
    ]
    (OUT / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    hash_paths = [
        P3_RUNNER, P3_RAW, S1_DECISION, OUT / "task_card.md",
        OUT / "run_s2_full_threeview.py", OUT / "raw_runs.csv",
        OUT / "appendix_a1.csv", OUT / "appendix_a1_numeric.csv",
        OUT / "metadata.json", OUT / "decision.json", OUT / "report.md",
    ]
    _write_json(
        OUT / "artifact_hashes.json",
        {
            "schema_version": "resetp.artifact-hashes.v1",
            "algorithm": "sha256", "appledouble_excluded": True,
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
            "raw_rows": decision["observed_new_rows"],
            "artifact_hashes": "artifact_hashes.json",
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    print(f"[S2] {decision['decision']}", flush=True)
    return 0 if decision["decision"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
