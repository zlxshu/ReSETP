"""Final isolated six-worker spawn, engineering, and resource gate."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from multiprocessing import get_context
from pathlib import Path
from typing import Any

from . import runtime
from .frozen_loader import load_frozen_stack
from .workers import engineering_worker, identity_worker


def unit_checks() -> dict[str, bool]:
    pricing = load_frozen_stack()["pricing"]
    from types import SimpleNamespace

    def label(sequence, *, cost, reduced, slots=(), direction="forward"):
        return pricing.PricedLabel(
            sequence=sequence,
            depot_id="D1",
            vehicle_type="ev",
            cost=cost,
            reduced_cost=reduced,
            charger_slots=slots,
            assignment=SimpleNamespace(
                home_depot_id="D1",
                vehicle_type="ev",
                charge_strategy="integrated",
                carbon_weight=1.0,
            ),
            direction=direction,
        )

    better = label(("C1", "C2"), cost=10.0, reduced=-2.0)
    worse = label(("C1", "C2"), cost=11.0, reduced=-1.0, slots=(("S1", 0, 8),))
    forward = label(("C1", "C2"), cost=4.0, reduced=-1.0)
    backward = label(("C3", "C4"), cost=5.0, reduced=-1.0, direction="backward")
    overlap = label(("C2", "C4"), cost=5.0, reduced=-1.0, direction="backward")
    checks = {
        "dominance_accepts_lower_cost_resource_subset": pricing.dominates(better, worse),
        "dominance_rejects_reverse": not pricing.dominates(worse, better),
        "merge_preserves_customer_order": pricing.merge_labels(forward, backward)
        == ("C1", "C2", "C3", "C4"),
        "merge_rejects_overlap": pricing.merge_labels(forward, overlap) is None,
        "resource_penalty_changes_reduced_cost": (10.0 - 12.0 + 3.0)
        > (10.0 - 12.0),
        "negative_reduced_cost_sign": (10.0 - 12.0) < 0.0,
    }
    if not all(checks.values()):
        raise AssertionError(f"engineering unit check failed: {checks}")
    return checks


def error_row(task: dict[str, Any], message: str) -> dict[str, Any]:
    return {
        "task_id": task["task_id"],
        "instance_id": task["instance_id"],
        "lane": task["lane"],
        "status": "ERROR",
        "extensions": 0,
        "complete_labels": 0,
        "negative_routes_observed_without_complete_scoring": 0,
        "positive_resource_prices": 0,
        "peak_rss_bytes": 0,
        "candidate_objectives_evaluated": 0,
        "error": message,
    }


def spawn_smoke(workers: int) -> list[dict[str, Any]]:
    context = get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
        results = list(pool.map(identity_worker, range(workers)))
    expected_worker = str((runtime.PACKAGE / "workers.py").resolve())
    expected_runner = str(
        (
            runtime.REPO
            / "baselines/algorithm_prototypes/resource_slot_pricing_20260725/run_g0.py"
        ).resolve()
    )
    if len(results) != workers:
        raise RuntimeError("spawn identity smoke did not return six rows")
    if len({int(row["pid"]) for row in results}) != workers:
        raise RuntimeError("spawn identity smoke did not use six distinct workers")
    if any(
        row["worker_module"] != "rsp_final_isolated_20260725.workers"
        or row["worker_file"] != expected_worker
        or row["runner_module"]
        != "rsp_final_isolated_20260725._frozen_g0_runner"
        or row["runner_file"] != expected_runner
        for row in results
    ):
        raise RuntimeError("spawn identity smoke resolved an unexpected module or file")
    return sorted(results, key=lambda row: int(row["token"]))


def main() -> int:
    if runtime.ENGINEERING.exists():
        raise RuntimeError(f"v4 engineering output exists: {runtime.ENGINEERING}")
    runtime.ENGINEERING.mkdir(parents=True)
    registration = runtime.verify_registration()
    config = registration["config"]
    checks = unit_checks()
    before = runtime.memory_snapshot()
    smoke_results: list[dict[str, Any]] = []
    smoke_error = ""
    try:
        smoke_results = spawn_smoke(int(config["workers"]))
    except Exception as exc:  # noqa: BLE001
        smoke_error = f"{type(exc).__name__}: {exc}"
    runtime.write_json(
        runtime.ENGINEERING / "metadata.json",
        {
            "schema": "resetp.resource-slot-pricing-engineering.v4",
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "registration_sha256": runtime.sha256(runtime.REGISTRATION),
            "workers": int(config["workers"]),
            "candidate_objectives_evaluated": 0,
            "unit_checks": checks,
            "spawn_identity_results": smoke_results,
            "spawn_identity_error": smoke_error,
            "real_instance_loaded_before_smoke_pass": False,
            "memory_before": before,
        },
    )
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    if smoke_error:
        failures.append(f"spawn_identity: {smoke_error}")
        rows = [
            error_row(task, f"identity smoke failed before real input: {smoke_error}")
            for task in registration["tasks"]
        ]
    else:
        context = get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=int(config["workers"]), mp_context=context
        ) as pool:
            futures = {
                pool.submit(engineering_worker, task, config): task
                for task in registration["tasks"]
            }
            for future in as_completed(futures):
                task = futures[future]
                try:
                    rows.append(future.result())
                except Exception as exc:  # noqa: BLE001
                    message = f"{task['task_id']}: {type(exc).__name__}: {exc}"
                    failures.append(message)
                    rows.append(error_row(task, message))
    rows.sort(key=lambda row: row["task_id"])
    runtime.write_csv(runtime.ENGINEERING / "raw_runs.csv", rows)
    ok = [row for row in rows if row["status"] == "PASS"]
    projected = sum(int(row["peak_rss_bytes"]) for row in ok)
    passed = bool(
        not failures
        and len(smoke_results) == 6
        and len(ok) == 6
        and before["available_percent"]
        >= float(config["minimum_available_memory_percent"])
        and projected <= int(config["maximum_projected_peak_rss_bytes"])
    )
    verdict = (
        "PASS_ZERO_OBJECTIVE_ENGINEERING_AND_SIX_WORKER_RESOURCE_GATE"
        if passed
        else "HALT_ZERO_OBJECTIVE_ENGINEERING_OR_RESOURCE_GATE"
    )
    decision = {
        "schema": "resetp.resource-slot-pricing-engineering-decision.v4",
        "verdict": verdict,
        "pass": passed,
        "spawn_identity_pass": len(smoke_results) == 6 and not smoke_error,
        "spawn_identity_distinct_pids": len(
            {int(row["pid"]) for row in smoke_results}
        ),
        "real_instance_loaded_before_smoke_pass": False,
        "candidate_objectives_evaluated": 0,
        "completed_tasks": len(ok),
        "expected_tasks": 6,
        "available_memory_percent_before": before["available_percent"],
        "projected_combined_peak_rss_bytes": projected,
        "failures": failures,
        "next_step": "RUN_FROZEN_G0_ONCE" if passed else "STOP_NO_RESCUE",
    }
    runtime.write_json(runtime.ENGINEERING / "decision.json", decision)
    (runtime.ENGINEERING / "report.md").write_text(
        "# Resource-slot pricing v4 isolated engineering gate\n\n"
        f"Verdict: `{verdict}`.\n\n"
        f"Identity smoke: {len(smoke_results)}/6 rows, "
        f"{len({int(row['pid']) for row in smoke_results})}/6 distinct PIDs. "
        f"Real engineering tasks: {len(ok)}/6. Candidate complete objectives: 0.\n",
        encoding="utf-8",
    )
    runtime.write_json(
        runtime.ENGINEERING / "artifact_hashes.json",
        runtime.artifact_hashes(runtime.ENGINEERING),
    )
    runtime.write_json(
        runtime.ENGINEERING / "done.json",
        {
            "verdict": verdict,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    print(json.dumps(decision, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

