#!/usr/bin/env python3
"""Three-seed robustness gate for the frozen MV-HGS-SP architecture."""

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
PREREG = PACKAGE / "h6_multiseed_route_pool_preregistration.json"
OUT = PACKAGE / "h6_multiseed_route_pool_gate"
for path in (ROOT / "solver/src", PACKAGE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from route_pool_sp import run_hgs_route_pool_recombination  # noqa: E402
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
    for instance_id in prereg["cases"]:
        bundle = load_china81_bundle(ROOT, str(instance_id))
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
        for seed in prereg["seeds"]:
            run = run_hgs_route_pool_recombination(
                bundle,
                common.solution,
                seed=int(seed),
                hgs_seconds_per_view=float(
                    prereg["hgs_seconds_per_view"]
                ),
                exact_elites_per_view=int(
                    prereg["exact_elites_per_view"]
                ),
                max_archive_candidates_per_view=int(
                    prereg["max_archive_candidates_per_view"]
                ),
                sp_time_limit_seconds=float(
                    prereg[
                        "set_partitioning_time_limit_seconds"
                    ]
                ),
            )
            objective, breakdown, violations = exact_china81_score(
                run.completion.solution,
                bundle,
            )
            parent = run.parent_completion.objective
            delta = objective - parent
            result = (
                "win"
                if delta < -1.0e-9
                else ("loss" if delta > 1.0e-9 else "tie")
            )
            rows.append(
                {
                    "instance_id": instance_id,
                    "seed": seed,
                    "best_parent_objective": parent,
                    "final_objective": objective,
                    "final_minus_parent": delta,
                    "relative_improvement_percent": (
                        100.0 * (parent - objective) / parent
                    ),
                    "result": result,
                    "feasible": not violations,
                    "violation_count": len(violations),
                    "route_pool_size": run.stats["route_pool_size"],
                    "selected_source": run.stats[
                        "selected_source"
                    ],
                    "sp_success": run.stats[
                        "set_partitioning"
                    ]["success"],
                    "sp_mip_gap": run.stats[
                        "set_partitioning"
                    ]["mip_gap"],
                    "elapsed_seconds": run.elapsed_seconds,
                }
            )
            witnesses[f"{instance_id}::seed-{seed}"] = {
                "stats": run.stats,
                "solution": asdict(run.completion.solution),
                "independent_breakdown": breakdown,
                "view_epochs": {
                    mode: epoch.stats
                    for mode, epoch in run.view_epochs.items()
                },
            }
    wins = sum(row["result"] == "win" for row in rows)
    ties = sum(row["result"] == "tie" for row in rows)
    losses = sum(row["result"] == "loss" for row in rows)
    by_stratum: dict[str, dict[str, int]] = {}
    for label in ("jjj-25", "prd-75", "cy-150"):
        matching = [
            row for row in rows if label in row["instance_id"]
        ]
        by_stratum[label] = {
            "wins": sum(row["result"] == "win" for row in matching),
            "ties": sum(row["result"] == "tie" for row in matching),
            "losses": sum(
                row["result"] == "loss" for row in matching
            ),
        }
    all_feasible = all(bool(row["feasible"]) for row in rows)
    tests = _test_commands()
    tests_passed = all(item["returncode"] == 0 for item in tests)
    passed = (
        losses == 0
        and wins >= 4
        and by_stratum["prd-75"]["wins"] >= 1
        and by_stratum["cy-150"]["wins"] >= 1
        and all_feasible
        and tests_passed
    )
    decision = {
        "schema_version": (
            "resetp.china81-h6-multiseed-route-pool-decision.v1"
        ),
        "decision": (
            "PASS_MV_HGS_SP_THREE_SEED_ROBUSTNESS"
            if passed
            else "HOLD_MV_HGS_SP_THREE_SEED_ROBUSTNESS"
        ),
        "passed": passed,
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "by_stratum": by_stratum,
        "all_feasible": all_feasible,
        "tests_passed": tests_passed,
        "details": rows,
        "claim_boundary": prereg["claim_boundary"],
        "next_gate": (
            "freeze_for_user_review"
            if passed
            else "stop_and_report_without_rescue"
        ),
    }
    metadata = {
        "schema_version": (
            "resetp.china81-h6-multiseed-route-pool-metadata.v1"
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
                "# China81 H6：MV-HGS-SP 三种子稳健性门",
                "",
                f"机器结论：`{decision['decision']}`。",
                "",
                f"九个配对单元：{wins} 胜 / {ties} 平 / "
                f"{losses} 负。",
                "",
                f"分层结果：`{json.dumps(by_stratum, ensure_ascii=False)}`。",
                "",
                "本门通过后冻结结构，不继续增加算法零件；完整 81 题",
                "和公开 V13 仍需用户复盘后单独放行。",
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
        PACKAGE / "route_pool_sp.py",
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
