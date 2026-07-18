"""Run the pre-registered 0/1/2/5 contextual-expert behaviour gate."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = (
    REPO
    / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
)
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    LEGACY,
    REPO,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from contextual_expert_fixtures import (  # noqa: E402
    PLATEAU_BUNDLE,
    PRICES_280,
    RESPONSIBILITY_BUNDLE,
    all_cv_plateau,
    plateau_solution,
    responsibility_binding_solution,
    responsibility_nonbinding_solution,
)
from contextual_expert_solver import (  # noqa: E402
    ContextualExpertConfig,
    run_contextual_expert_alns,
)
from initial_pool import solution_signature_hash  # noqa: E402
from prototype import independent_cost  # noqa: E402
from setp_solver.algorithms.resetp_alns.support.mechanism_prescription import (  # noqa: E402
    CARBON_TIME,
    FLEET_CHARGE,
    RESPONSIBILITY,
)
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.solution import Solution  # noqa: E402


OUTPUT_FILES = (
    "metadata.json",
    "raw_runs.csv",
    "decision.json",
    "solution_witnesses.json",
    "report.md",
)
PROTECTED_FILES = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)
SOURCE_FILES = (
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "run_contextual_expert_behavior_gate.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "contextual_expert_solver.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "contextual_expert_fixtures.py",
    "solver/src/setp_solver/algorithms/resetp_alns/support/"
    "mechanism_prescription.py",
    "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/"
    "v5_carbon_retiming_solver.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/"
    "v6_monotone_mechanism_solver.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/"
    "v7_responsibility_solver.py",
    "docs/handoff/context_gated_exact_mechanism_contract_20260719.md",
)
BUDGETS = (0, 1, 2, 5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=HERE / "contextual_expert_behavior_gate",
    )
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    cases = (
        _case(
            RESPONSIBILITY,
            RESPONSIBILITY_BUNDLE,
            responsibility_binding_solution,
            responsibility_nonbinding_solution,
            responsibility_exact_candidates=1,
        ),
        _case(
            FLEET_CHARGE,
            PLATEAU_BUNDLE,
            all_cv_plateau,
            plateau_solution,
        ),
        _case(
            CARBON_TIME,
            PLATEAU_BUNDLE,
            plateau_solution,
            all_cv_plateau,
        ),
    )
    rows: list[dict[str, Any]] = []
    witnesses: dict[str, Any] = {}
    for case in cases:
        for binding_label, builder in (
            ("binding", case["binding_builder"]),
            ("nonbinding", case["nonbinding_builder"]),
        ):
            start_solution = builder()
            start_signature = solution_signature_hash(start_solution)
            witnesses.setdefault(
                start_signature,
                {
                    "kind": "start",
                    "mechanism_id": case["mechanism_id"],
                    "binding": binding_label,
                    "bundle": _relative(case["bundle"]),
                    "solution": asdict(start_solution),
                },
            )
            for budget in BUDGETS:
                row_started = time.perf_counter()
                result = run_contextual_expert_alns(
                    case["bundle"],
                    seed=1,
                    prices=PRICES_280,
                    initial_solution=start_solution,
                    config=ContextualExpertConfig(
                        total_eval_budget=budget,
                        assessment_interval=20,
                        per_mechanism_cooldown=60,
                        enabled_mechanisms=(
                            case["mechanism_id"],
                        ),
                        responsibility_exact_candidates=int(
                            case["responsibility_exact_candidates"]
                        ),
                    ),
                )
                elapsed = time.perf_counter() - row_started
                activity = dict(result.mechanism_activity)
                diagnostics = dict(
                    activity.get("mechanism_diagnostics", {})
                )
                mechanism_id = str(case["mechanism_id"])
                attempts = int(
                    dict(diagnostics.get("attempts", {})).get(
                        mechanism_id,
                        0,
                    )
                )
                changed = int(
                    dict(diagnostics.get("changed", {})).get(
                        mechanism_id,
                        0,
                    )
                )
                accepted = int(
                    dict(diagnostics.get("accepted", {})).get(
                        mechanism_id,
                        0,
                    )
                )
                best_improved = int(
                    dict(
                        diagnostics.get("best_improved", {})
                    ).get(mechanism_id, 0)
                )
                scope_violations = int(
                    dict(
                        diagnostics.get("scope_violations", {})
                    ).get(mechanism_id, 0)
                )
                score_counts = dict(activity.get("score_counts", {}))
                channel_sum = sum(
                    int(value)
                    for key, value in score_counts.items()
                    if str(key).startswith("candidate_channel:")
                )
                final_signature = solution_signature_hash(
                    result.best_solution
                )
                final_recomputed = independent_cost(
                    case["bundle"],
                    result.best_solution,
                    PRICES_280,
                )
                witnesses.setdefault(
                    final_signature,
                    {
                        "kind": "final",
                        "mechanism_id": mechanism_id,
                        "binding": binding_label,
                        "budget": budget,
                        "bundle": _relative(case["bundle"]),
                        "solution": asdict(result.best_solution),
                    },
                )
                mechanism_evaluations = int(
                    activity["mechanism_candidate_evaluations"]
                )
                generic_evaluations = int(
                    activity["generic_candidate_evaluations"]
                )
                budget_closed = (
                    int(result.evaluations)
                    == int(activity["candidate_scores"])
                    == int(activity["actual_moves"])
                    == int(channel_sum)
                    == int(budget)
                    == mechanism_evaluations
                    + generic_evaluations
                )
                rows.append(
                    {
                        "mechanism_id": mechanism_id,
                        "binding": binding_label,
                        "bundle": _relative(case["bundle"]),
                        "budget": int(budget),
                        "seed": 1,
                        "evaluations": int(result.evaluations),
                        "candidate_scores": int(
                            activity["candidate_scores"]
                        ),
                        "actual_moves": int(
                            activity["actual_moves"]
                        ),
                        "candidate_channel_sum": int(channel_sum),
                        "mechanism_candidate_evaluations": (
                            mechanism_evaluations
                        ),
                        "generic_candidate_evaluations": (
                            generic_evaluations
                        ),
                        "attempts": attempts,
                        "changed": changed,
                        "accepted": accepted,
                        "best_improved": best_improved,
                        "scope_violations": scope_violations,
                        "search_loop_count": int(
                            activity["search_loop_count"]
                        ),
                        "search_restart_count": int(
                            activity["search_restart_count"]
                        ),
                        "budget_closed": bool(budget_closed),
                        "feasible": bool(result.feasible),
                        "start_cost": float(
                            independent_cost(
                                case["bundle"],
                                start_solution,
                                PRICES_280,
                            )
                        ),
                        "final_cost": float(result.best_cost),
                        "final_recomputed_cost": float(
                            final_recomputed
                        ),
                        "objective_match": abs(
                            float(result.best_cost)
                            - float(final_recomputed)
                        )
                        <= 1.0e-7,
                        "start_signature": start_signature,
                        "final_signature": final_signature,
                        "elapsed_seconds": float(elapsed),
                        "events_json": json.dumps(
                            diagnostics.get("events", []),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    }
                )

    decision = _decision(rows)
    metadata = {
        "schema_version": (
            "resetp.context-gated-exact-mechanism-behaviour.v1"
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_short": _git("status", "--short"),
        "elapsed_seconds": time.perf_counter() - started,
        "battery_kwh": 280.0,
        "budgets": list(BUDGETS),
        "seed": 1,
        "formal_l_main_activated": False,
        "stage2_activated": False,
        "claim_boundary": (
            "Mechanism behaviour and budget closure only; no algorithm "
            "performance claim."
        ),
        "contract_repo_relative": (
            "docs/handoff/"
            "context_gated_exact_mechanism_contract_20260719.md"
        ),
        "source_hashes": {
            path: _sha256(REPO / path) for path in SOURCE_FILES
        },
        "protected_file_hashes": {
            path: _sha256(REPO / path) for path in PROTECTED_FILES
        },
        "input_hashes": _input_hashes(
            {
                Path(case["bundle"])
                for case in cases
            }
        ),
    }
    _write_csv(output_dir / "raw_runs.csv", rows)
    _write_json(output_dir / "decision.json", decision)
    _write_json(output_dir / "metadata.json", metadata)
    _write_json(
        output_dir / "solution_witnesses.json",
        witnesses,
    )
    (output_dir / "report.md").write_text(
        _report(rows, decision),
        encoding="utf-8",
    )
    artifact_hashes = {
        name: _sha256(output_dir / name)
        for name in OUTPUT_FILES
    }
    _write_json(
        output_dir / "artifact_hashes.json",
        artifact_hashes,
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if decision["passed"] else 2


def _case(
    mechanism_id: str,
    bundle: Path,
    binding_builder: Callable[[], Solution],
    nonbinding_builder: Callable[[], Solution],
    *,
    responsibility_exact_candidates: int = 8,
) -> dict[str, Any]:
    return {
        "mechanism_id": mechanism_id,
        "bundle": Path(bundle),
        "binding_builder": binding_builder,
        "nonbinding_builder": nonbinding_builder,
        "responsibility_exact_candidates": int(
            responsibility_exact_candidates
        ),
    }


def _decision(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    if len(rows) != 24:
        failures.append(f"row_count:{len(rows)}")
    for row in rows:
        tag = (
            f"{row['mechanism_id']}:{row['binding']}:B{row['budget']}"
        )
        if not row["budget_closed"]:
            failures.append(f"{tag}:budget_not_closed")
        if not row["feasible"] or not row["objective_match"]:
            failures.append(f"{tag}:replay_or_feasibility")
        if row["search_loop_count"] != 1:
            failures.append(f"{tag}:search_loop_count")
        if row["search_restart_count"] != 0:
            failures.append(f"{tag}:search_restart")
        if row["scope_violations"] != 0:
            failures.append(f"{tag}:scope_violation")
        if row["budget"] == 0:
            if (
                row["attempts"]
                or row["mechanism_candidate_evaluations"]
            ):
                failures.append(f"{tag}:zero_budget_activity")
            continue
        if row["binding"] == "binding":
            if row["mechanism_candidate_evaluations"] != 1:
                failures.append(f"{tag}:binding_candidate_count")
            if (
                row["changed"] != 1
                or row["accepted"] != 1
                or row["best_improved"] != 1
            ):
                failures.append(f"{tag}:binding_not_improved")
        elif row["mechanism_candidate_evaluations"] != 0:
            failures.append(f"{tag}:nonbinding_was_charged")
    passed = not failures
    return {
        "verdict": (
            "PASS_CONTEXT_GATED_EXPERT_BEHAVIOUR"
            if passed
            else "STOP_CONTEXT_GATED_EXPERT_BEHAVIOUR"
        ),
        "passed": bool(passed),
        "failures": failures,
        "row_count": len(rows),
        "all_budget_closed": all(
            bool(row["budget_closed"]) for row in rows
        ),
        "all_feasible_and_replayed": all(
            bool(row["feasible"] and row["objective_match"])
            for row in rows
        ),
        "scope_violation_count": sum(
            int(row["scope_violations"]) for row in rows
        ),
        "binding_complete_candidate_count": sum(
            int(row["mechanism_candidate_evaluations"])
            for row in rows
            if row["binding"] == "binding"
        ),
        "nonbinding_complete_candidate_count": sum(
            int(row["mechanism_candidate_evaluations"])
            for row in rows
            if row["binding"] == "nonbinding"
        ),
        "next_allowed_step": (
            "old_v8_three_instance_training_gate"
            if passed
            else "repair_behaviour_only"
        ),
        "formal_search_allowed": False,
        "stage2_allowed": False,
    }


def _report(
    rows: list[dict[str, Any]],
    decision: dict[str, Any],
) -> str:
    lines = [
        "# 当前病灶驱动精确专家：0/1/2/5 行为门",
        "",
        f"结论：`{decision['verdict']}`。",
        "",
        "| 机制 | 状态 | B | 机制收费 | 普通收费 | 接受 | 越界 | 预算闭合 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            "| {mechanism_id} | {binding} | {budget} | "
            "{mechanism_candidate_evaluations} | "
            "{generic_candidate_evaluations} | {accepted} | "
            "{scope_violations} | {budget_closed} |".format(**row)
        )
    lines.extend(
        [
            "",
            "本门只证明三位专家在绑定状态下能形成一个有归属、"
            "可行且严格改善的共同评分候选，在不绑定状态下不收费，"
            "并且搜索始终只有一条连续轨迹。它不证明候选算法比任何"
            " ALNS 或 HGS 更强，也不授权阶段二或正式全量实验。",
            "",
        ]
    )
    return "\n".join(lines)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _input_hashes(bundle_dirs: set[Path]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for bundle in sorted(bundle_dirs):
        for path in sorted(bundle.iterdir()):
            if path.is_file() and not path.name.startswith("._"):
                hashes[_relative(path)] = _sha256(path)
    return hashes


def _relative(path: Path) -> str:
    return str(Path(path).resolve().relative_to(REPO))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
