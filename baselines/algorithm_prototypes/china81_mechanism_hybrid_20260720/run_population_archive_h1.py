#!/usr/bin/env python3
"""Test exact ReSETP re-ranking of genuine HGS populations."""

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
PREREG = PACKAGE / "h1_population_archive_preregistration.json"
OUT = PACKAGE / "h1_population_archive_gate"
for path in (ROOT / "solver/src", PACKAGE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

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
        for mode in prereg["route_proxy_modes"]:
            run = run_pyvrp_hgs_population_archive(
                bundle,
                common.solution,
                seed=int(prereg["seed"]),
                runtime_seconds=float(prereg["seconds_per_run"]),
                route_proxy_mode=str(mode),
                max_archive_candidates=int(
                    prereg["max_archive_candidates_per_population"]
                ),
            )
            objective, breakdown, violations = exact_china81_score(
                run.completion.solution,
                bundle,
            )
            proxy_objective = run.proxy_best.completion.objective
            delta = objective - proxy_objective
            rows.append(
                {
                    "instance_id": instance_id,
                    "route_proxy_mode": mode,
                    "seed": prereg["seed"],
                    "runtime_seconds": prereg["seconds_per_run"],
                    "elapsed_seconds": run.elapsed_seconds,
                    "proxy_best_exact_objective": proxy_objective,
                    "archive_best_exact_objective": objective,
                    "archive_minus_proxy": delta,
                    "strict_archive_improvement": delta < -1.0e-9,
                    "archive_not_worse": delta <= 1.0e-9,
                    "feasible": not violations,
                    "violation_count": len(violations),
                    "archive_candidates_completed": run.stats[
                        "archive_candidates_completed"
                    ],
                    "population_size": run.stats["population_size"],
                    "hgs_iterations": run.stats["hgs_iterations"],
                }
            )
            witnesses[f"{instance_id}::{mode}"] = {
                "stats": run.stats,
                "archive_exact_objectives": list(
                    run.archive_exact_objectives
                ),
                "solution": asdict(run.completion.solution),
                "independent_breakdown": breakdown,
            }
    strict_improvements = sum(
        bool(row["strict_archive_improvement"]) for row in rows
    )
    all_not_worse = all(bool(row["archive_not_worse"]) for row in rows)
    all_feasible = all(bool(row["feasible"]) for row in rows)
    tests = _test_commands()
    tests_passed = all(item["returncode"] == 0 for item in tests)
    passed = (
        strict_improvements >= 1
        and all_not_worse
        and all_feasible
        and tests_passed
    )
    per_case = {}
    for instance_id in prereg["cases"]:
        matching = [
            row for row in rows if row["instance_id"] == instance_id
        ]
        per_case[str(instance_id)] = {
            "best_proxy_objective": min(
                float(row["proxy_best_exact_objective"])
                for row in matching
            ),
            "best_archive_objective": min(
                float(row["archive_best_exact_objective"])
                for row in matching
            ),
        }
    decision = {
        "schema_version": "resetp.china81-h1-population-archive-decision.v1",
        "decision": (
            "PASS_HGS_EXACT_POPULATION_RERANKING_SIGNAL"
            if passed
            else "STOP_HGS_EXACT_POPULATION_RERANKING_NO_SIGNAL"
        ),
        "passed": passed,
        "strict_improvement_count": strict_improvements,
        "pair_count": len(rows),
        "all_archive_pairs_not_worse": all_not_worse,
        "all_feasible": all_feasible,
        "tests_passed": tests_passed,
        "per_case_best_across_views": per_case,
        "claim_boundary": prereg["claim_boundary"],
        "next_gate": (
            "fresh_case_multiview_population_migration"
            if passed
            else "stop_population_reranking_component"
        ),
    }
    metadata = {
        "schema_version": "resetp.china81-h1-population-archive-metadata.v1",
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
                "# China81 H1：HGS 种群完整模型重排门",
                "",
                f"机器结论：`{decision['decision']}`。",
                "",
                f"九个配对中严格改善 {strict_improvements} 个；"
                f"全部不倒退：{all_not_worse}；全部可行：{all_feasible}。",
                "",
                "本门没有增加 HGS 搜索，只把同一次 HGS 最终种群中的",
                "可行个体交给完整 ReSETP 模型重新判分。",
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
        PACKAGE / "pyvrp_adapter.py",
        ROOT / "solver/src/setp_solver/china81_completion.py",
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
