"""Run the frozen six-task zero-search proxy-misranking gate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import multiprocessing
import os
import platform
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from rce_hgs_misrank_20260725.audit_core import AuditTask, run_audit_task

CAMPAIGN_RELATIVE = Path(
    "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v7_small_archive_ledger_20260724/full_gate/tasks"
)
OUTPUT_RELATIVE = Path(
    "baselines/e2_final_campaign_20260720/"
    "rce_hgs_proxy_misrank_gate_20260725"
)
CONTRACT_RELATIVE = Path(
    "docs/handoff/"
    "e2_resource_coupled_hgs_misranking_audit_contract_20260725.md"
)
LOCKED = (
    ("cn-jjj-50c-02-V2-LOCATIONS", 1),
    ("cn-jjj-50c-02-V2-LOCATIONS", 2),
    ("cn-cy-100c-01-V2-LOCATIONS", 1),
    ("cn-cy-100c-01-V2-LOCATIONS", 2),
    ("cn-prd-200c-02-V2-LOCATIONS", 1),
    ("cn-prd-200c-02-V2-LOCATIONS", 2),
)
PROTECTED_RELATIVE = (
    Path("solver/src/setp_solver/cost.py"),
    Path("solver/src/setp_solver/check.py"),
    Path("solver/src/setp_solver/search/evaluation.py"),
    Path("solver/src/setp_solver/prices.py"),
    Path("solver/src/setp_solver/china81_completion.py"),
    Path(
        "baselines/algorithm_prototypes/"
        "china81_mechanism_hybrid_20260720/pyvrp_adapter.py"
    ),
)
RAW_FIELDS = (
    "task_id",
    "instance_id",
    "seed",
    "candidate_signature",
    "action_type",
    "source_route",
    "target_route",
    "source_pos",
    "target_pos",
    "aux",
    "proxy_score",
    "proxy_feasible",
    "exact_status",
    "exact_objective",
    "exact_improvement",
    "exact_violation_count",
    "exact_completion_seconds",
    "error",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _task_paths(root: Path, instance_id: str, seed: int) -> AuditTask:
    task_dir = (
        root
        / CAMPAIGN_RELATIVE
        / f"D6-E2-STAGED__{instance_id}__seed{seed}"
    )
    witness = task_dir / "solution_witnesses.json"
    raw = task_dir / "raw_runs.csv"
    if not witness.is_file() or not raw.is_file():
        raise FileNotFoundError(
            f"missing protected v7 task artifacts at {task_dir}"
        )
    return AuditTask(
        instance_id=instance_id,
        seed=seed,
        witness_path=str(witness.resolve()),
        raw_run_path=str(raw.resolve()),
    )


def _frozen_hashes(root: Path, tasks: list[AuditTask]) -> dict[str, str]:
    paths = [
        root / CONTRACT_RELATIVE,
        Path(__file__).resolve(),
        Path(__file__).with_name("audit_core.py").resolve(),
        *[Path(task.witness_path) for task in tasks],
        *[Path(task.raw_run_path) for task in tasks],
        *[root / path for path in PROTECTED_RELATIVE],
    ]
    return {
        str(path.resolve().relative_to(root)): _sha256(path.resolve())
        for path in paths
    }


def _write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _artifact_hashes(output: Path) -> dict[str, str]:
    files = [
        path
        for path in output.iterdir()
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and not path.name.endswith(".tmp")
    ]
    return {
        path.name: _sha256(path)
        for path in sorted(files, key=lambda item: item.name)
    }


def _decision(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    inversion_tasks = sum(
        bool(row["strict_proxy_exact_inversion"])
        for row in summaries
    )
    improving_tasks = sum(
        bool(row["has_strict_improvement"])
        for row in summaries
    )
    missed_tasks = sum(
        bool(row["best_improvement_missed_by_proxy_top8"])
        for row in summaries
    )
    tiers = {}
    for row in summaries:
        tier = int(row["instance_id"].split("-")[2].removesuffix("c"))
        item = tiers.setdefault(
            tier,
            {"has_improvement": False, "missed_top8": False},
        )
        item["has_improvement"] = (
            item["has_improvement"]
            or bool(row["has_strict_improvement"])
        )
        item["missed_top8"] = (
            item["missed_top8"]
            or bool(row["best_improvement_missed_by_proxy_top8"])
        )
    qualifying_tiers = sum(
        item["has_improvement"] and item["missed_top8"]
        for item in tiers.values()
    )
    all_closed = (
        len(summaries) == 6
        and all(row["baseline_replay_closed"] for row in summaries)
        and all(row["candidate_count"] == 96 for row in summaries)
        and all(
            row["exact_pass_count"] + row["exact_failure_count"] == 96
            for row in summaries
        )
    )
    passed = (
        all_closed
        and inversion_tasks >= 5
        and improving_tasks >= 4
        and missed_tasks >= 4
        and qualifying_tiers >= 2
    )
    return {
        "schema": "resetp.e2.rce-hgs-proxy-misrank.v1",
        "verdict": (
            "PASS_RCE_HGS_PROXY_MISRANK_CAUSAL_GATE"
            if passed
            else "STOP_RCE_HGS_NO_VERIFIED_PROXY_MISRANK_HEADROOM"
        ),
        "paper_evidence": False,
        "performance_experiment": False,
        "search_runs": 0,
        "accepted_candidates": 0,
        "completed_tasks": len(summaries),
        "ledger_closed": all_closed,
        "strict_inversion_tasks": inversion_tasks,
        "tasks_with_strict_improvement": improving_tasks,
        "tasks_best_improvement_missed_by_proxy_top8": missed_tasks,
        "qualifying_size_tiers": qualifying_tiers,
        "required": {
            "strict_inversion_tasks": 5,
            "tasks_with_strict_improvement": 4,
            "tasks_best_improvement_missed_by_proxy_top8": 4,
            "qualifying_size_tiers": 2,
        },
        "next_authority": (
            "ONLY_SIX_CUSTOMER_RESOURCE_EVALUATOR_EQUIVALENCE_CONTRACT"
            if passed
            else "FINAL_STOP_NO_RESCUE_ON_LOCKED_TASKS"
        ),
    }


def _run_parallel(
    root: Path,
    tasks: list[AuditTask],
    workers: int,
    exact_candidates: bool,
) -> list[dict[str, Any]]:
    context = multiprocessing.get_context("spawn")
    outputs = []
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=context,
    ) as executor:
        futures = {
            executor.submit(
                run_audit_task,
                str(root),
                task,
                exact_candidates=exact_candidates,
            ): task
            for task in tasks
        }
        for future in as_completed(futures):
            outputs.append(future.result())
    return sorted(
        outputs,
        key=lambda item: item["summary"]["task_id"],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument(
        "--mode",
        choices=("engineering", "formal"),
        required=True,
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--output")
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    if not (root / ".git").exists():
        raise SystemExit(f"invalid repository root: {root}")
    if args.workers != 6:
        raise SystemExit("frozen gate requires exactly six workers")
    tasks = [
        _task_paths(root, instance_id, seed)
        for instance_id, seed in LOCKED
    ]
    frozen_before = _frozen_hashes(root, tasks)
    output = (
        Path(args.output).resolve()
        if args.output
        else (root / OUTPUT_RELATIVE / args.mode).resolve()
    )
    output.mkdir(parents=True, exist_ok=False)

    results = _run_parallel(
        root,
        tasks,
        args.workers,
        exact_candidates=args.mode == "formal",
    )
    frozen_after = _frozen_hashes(root, tasks)
    if frozen_before != frozen_after:
        raise RuntimeError("protected input or source hash drift")

    summaries = [result["summary"] for result in results]
    rows = [
        row
        for result in results
        for row in result["rows"]
    ]
    metadata = {
        "schema": "resetp.e2.rce-hgs-proxy-misrank.metadata.v1",
        "mode": args.mode,
        "repo_root": str(root),
        "runner_module": __name__,
        "runner_file": str(Path(__file__).resolve()),
        "python": sys.version,
        "platform": platform.platform(),
        "pid": os.getpid(),
        "workers": args.workers,
        "task_count": len(tasks),
        "candidate_count_per_task": 96,
        "search_runs": 0,
        "accepted_candidates": 0,
        "frozen_hashes": frozen_before,
        "task_summaries": summaries,
    }
    _write_json(output / "metadata.json", metadata)
    with (output / "raw_runs.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    if args.mode == "formal":
        decision = _decision(summaries)
    else:
        engineering_pass = (
            len(summaries) == 6
            and len(rows) == 576
            and all(row["baseline_replay_closed"] for row in summaries)
            and all(row["candidate_count"] == 96 for row in summaries)
            and all(
                set(row["action_counts"].values()) == {24}
                for row in summaries
            )
            and all(
                row["exact_status"] == "NOT_RUN_ENGINEERING_ONLY"
                for row in rows
            )
        )
        decision = {
            "schema": "resetp.e2.rce-hgs-proxy-misrank.engineering.v1",
            "verdict": (
                "PASS_RCE_HGS_ZERO_SEARCH_ENGINEERING_GATE"
                if engineering_pass
                else "HALT_RCE_HGS_ZERO_SEARCH_ENGINEERING_GATE"
            ),
            "candidate_exact_evaluations": 0,
            "search_runs": 0,
            "accepted_candidates": 0,
            "completed_tasks": len(summaries),
            "candidate_rows": len(rows),
        }
    _write_json(output / "decision.json", decision)
    report = (
        "# RCE-HGS proxy misranking gate\n\n"
        f"- Mode: `{args.mode}`\n"
        f"- Verdict: `{decision['verdict']}`\n"
        f"- Tasks: {len(summaries)}/6\n"
        f"- Candidate rows: {len(rows)}\n"
        "- HGS searches: 0\n"
        "- Accepted candidates: 0\n"
        "- Protected three-view/v7 artifacts modified: no\n"
    )
    (output / "report.md").write_text(report, encoding="utf-8")
    _write_json(
        output / "artifact_hashes.json",
        _artifact_hashes(output),
    )
    _write_json(
        output / "done.json",
        {
            "mode": args.mode,
            "verdict": decision["verdict"],
            "completed_tasks": len(summaries),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

