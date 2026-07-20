#!/usr/bin/env python3
"""Development gate for exact-model elite migration inside genuine HGS."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
PREREG = PACKAGE / "h3_epochal_migration_preregistration.json"
OUT = PACKAGE / "h3_epochal_migration_gate"
for path in (ROOT / "solver/src", PACKAGE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from epochal_hgs import run_epochal_mechanism_hgs  # noqa: E402
from pyvrp_adapter import run_pyvrp_hgs_population_archive  # noqa: E402
from run_true_hgs_h0 import _remove_appledouble, _test_commands  # noqa: E402
from setp_solver.algorithms.resetp_alns.support.construction import (  # noqa: E402
    build_initial_solution,
)
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    complete_china81_route_skeleton,
    exact_china81_score,
)


def main() -> int:
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    _remove_appledouble(PACKAGE)
    rows: list[dict[str, Any]] = []
    witnesses: dict[str, Any] = {}
    wins = ties = losses = 0
    for case in prereg["case_modes"]:
        instance_id = str(case["instance_id"])
        mode = str(case["route_proxy_mode"])
        bundle = load_china81_bundle(ROOT, instance_id)
        common = complete_china81_route_skeleton(
            build_initial_solution(
                bundle.instance,
                bundle.time_profile,
                bundle.prices,
                introduce_ev=False,
                require_charging_signal=False,
            ),
            bundle,
        )
        control = run_pyvrp_hgs_population_archive(
            bundle,
            common.solution,
            seed=int(prereg["base_seed"]),
            runtime_seconds=float(prereg["total_hgs_seconds"]),
            route_proxy_mode=mode,
            max_archive_candidates=int(
                prereg["max_archive_candidates"]
            ),
        )
        candidate = run_epochal_mechanism_hgs(
            bundle,
            common.solution,
            base_seed=int(prereg["base_seed"]),
            total_hgs_seconds=float(prereg["total_hgs_seconds"]),
            route_proxy_mode=mode,
            epoch_count=int(prereg["epoch_count"]),
            exact_elite_count=int(prereg["exact_elite_count"]),
            max_archive_candidates=int(
                prereg["max_archive_candidates"]
            ),
        )
        control_obj, control_breakdown, control_violations = (
            exact_china81_score(control.completion.solution, bundle)
        )
        candidate_obj, candidate_breakdown, candidate_violations = (
            exact_china81_score(candidate.completion.solution, bundle)
        )
        delta = candidate_obj - control_obj
        if delta < -1.0e-9:
            result = "win"
            wins += 1
        elif delta > 1.0e-9:
            result = "loss"
            losses += 1
        else:
            result = "tie"
            ties += 1
        rows.append(
            {
                "instance_id": instance_id,
                "route_proxy_mode": mode,
                "base_seed": prereg["base_seed"],
                "total_hgs_seconds": prereg["total_hgs_seconds"],
                "control_objective": control_obj,
                "candidate_objective": candidate_obj,
                "candidate_minus_control": delta,
                "result": result,
                "control_elapsed_seconds": control.elapsed_seconds,
                "candidate_elapsed_seconds": candidate.elapsed_seconds,
                "control_feasible": not control_violations,
                "candidate_feasible": not candidate_violations,
                "control_archive_completions": control.stats[
                    "archive_candidates_completed"
                ],
                "candidate_archive_completions": sum(
                    epoch.stats["archive_candidates_completed"]
                    for epoch in candidate.epochs
                ),
            }
        )
        witnesses[instance_id] = {
            "control": {
                "stats": control.stats,
                "solution": asdict(control.completion.solution),
                "independent_breakdown": control_breakdown,
            },
            "candidate": {
                "stats": candidate.stats,
                "epochs": [
                    epoch.stats for epoch in candidate.epochs
                ],
                "solution": asdict(candidate.completion.solution),
                "independent_breakdown": candidate_breakdown,
            },
        }
    all_feasible = all(
        bool(row["control_feasible"])
        and bool(row["candidate_feasible"])
        for row in rows
    )
    tests = _test_commands()
    tests_passed = all(item["returncode"] == 0 for item in tests)
    passed = losses == 0 and wins >= 1 and all_feasible and tests_passed
    decision = {
        "schema_version": (
            "resetp.china81-h3-epochal-migration-decision.v1"
        ),
        "decision": (
            "PASS_EXACT_ELITE_MIGRATION_DEVELOPMENT_SIGNAL"
            if passed
            else "STOP_EXACT_ELITE_MIGRATION_NO_SIGNAL"
        ),
        "passed": passed,
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "all_feasible": all_feasible,
        "tests_passed": tests_passed,
        "details": rows,
        "claim_boundary": (
            "Seen development cases and views selected from H1. Passing only "
            "authorizes a separately preregistered fresh-case test."
        ),
        "next_gate": (
            "fresh_replicate_03_epochal_migration"
            if passed
            else "stop_epochal_migration"
        ),
    }
    metadata = {
        "schema_version": (
            "resetp.china81-h3-epochal-migration-metadata.v1"
        ),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_executable": sys.executable,
        "preregistration": str(PREREG.relative_to(ROOT)),
        "preregistration_sha256": _sha256(PREREG),
        "formal_search_allowed": False,
        "test_commands": tests,
    }
    _write_csv(OUT / "raw_runs.csv", rows)
    _write_json(OUT / "metadata.json", metadata)
    _write_json(OUT / "decision.json", decision)
    _write_json(OUT / "solution_witnesses.json", witnesses)
    (OUT / "report.md").write_text(
        "\n".join(
            [
                "# China81 H3：完整机制精英回迁 HGS 开发门",
                "",
                f"机器结论：`{decision['decision']}`。",
                "",
                f"同算 HGS 时间下：{wins} 胜 / {ties} 平 / {losses} 负。",
                "",
                "对照把两秒连续用于一次 HGS；候选拆为两个一秒阶段，",
                "并把第一阶段由完整 ReSETP 模型选出的四个精英送回",
                "第二阶段繁殖。两边最终都做同样上限的种群完整重排。",
                "",
                f"边界：{decision['claim_boundary']}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _remove_appledouble(PACKAGE)
    files = [
        Path(__file__),
        PREREG,
        PACKAGE / "epochal_hgs.py",
        PACKAGE / "pyvrp_adapter.py",
        OUT / "metadata.json",
        OUT / "raw_runs.csv",
        OUT / "decision.json",
        OUT / "solution_witnesses.json",
        OUT / "report.md",
    ]
    _write_json(
        OUT / "artifact_hashes.json",
        {
            "schema_version": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "files": {
                str(path.relative_to(ROOT)): _sha256(path)
                for path in sorted(files)
            },
        },
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if passed else 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
