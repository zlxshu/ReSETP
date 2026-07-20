#!/usr/bin/env python3
"""Development gate for genuine-HGS exact route-pool recombination."""

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
PREREG = PACKAGE / "h4_route_pool_preregistration.json"
OUT = PACKAGE / "h4_route_pool_gate"
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
    wins = ties = losses = 0
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
        run = run_hgs_route_pool_recombination(
            bundle,
            common.solution,
            seed=int(prereg["seed"]),
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
                prereg["set_partitioning_time_limit_seconds"]
            ),
        )
        objective, breakdown, violations = exact_china81_score(
            run.completion.solution,
            bundle,
        )
        parent = run.parent_completion.objective
        delta = objective - parent
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
                "seed": prereg["seed"],
                "hgs_seconds_per_view": prereg[
                    "hgs_seconds_per_view"
                ],
                "best_parent_objective": parent,
                "final_objective": objective,
                "final_minus_parent": delta,
                "result": result,
                "feasible": not violations,
                "violation_count": len(violations),
                "route_pool_size": run.stats["route_pool_size"],
                "selected_source": run.stats["selected_source"],
                "sp_success": run.stats["set_partitioning"]["success"],
                "sp_mip_gap": run.stats["set_partitioning"]["mip_gap"],
                "elapsed_seconds": run.elapsed_seconds,
            }
        )
        witnesses[str(instance_id)] = {
            "stats": run.stats,
            "solution": asdict(run.completion.solution),
            "independent_breakdown": breakdown,
            "view_epochs": {
                mode: epoch.stats
                for mode, epoch in run.view_epochs.items()
            },
        }
    all_feasible = all(bool(row["feasible"]) for row in rows)
    tests = _test_commands()
    tests_passed = all(item["returncode"] == 0 for item in tests)
    passed = losses == 0 and wins >= 1 and all_feasible and tests_passed
    decision = {
        "schema_version": "resetp.china81-h4-route-pool-decision.v1",
        "decision": (
            "PASS_GENUINE_HGS_ROUTE_POOL_RECOMBINATION_SIGNAL"
            if passed
            else "STOP_GENUINE_HGS_ROUTE_POOL_NO_SIGNAL"
        ),
        "passed": passed,
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "all_feasible": all_feasible,
        "tests_passed": tests_passed,
        "details": rows,
        "claim_boundary": prereg["claim_boundary"],
        "next_gate": (
            "fresh_replicate_03_route_pool"
            if passed
            else "stop_current_route_pool_regime"
        ),
    }
    metadata = {
        "schema_version": "resetp.china81-h4-route-pool-metadata.v1",
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
                "# China81 H4：真实 HGS 精确路线池重组门",
                "",
                f"机器结论：`{decision['decision']}`。",
                "",
                f"相对同批最强父方案：{wins} 胜 / {ties} 平 / "
                f"{losses} 负。",
                "",
                "三个真实 HGS 视角先各自产生完整模型精英；精确路线",
                "选择器只使用这些已可行路线，并在完整模型复算后仅保留",
                "严格更好的重组。",
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
