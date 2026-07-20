#!/usr/bin/env python3
"""Equal-compute multiview versus homogeneous-population gate."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
PREREG = PACKAGE / "g4_equal_compute_preregistration.json"
OUT = PACKAGE / "g4_equal_compute_gate"
for path in (ROOT / "solver/src", PACKAGE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hybrid import (  # noqa: E402
    run_homogeneous_hgs_alns_ensemble,
    run_multiview_mechanism_hybrid,
)
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
    cases = [str(item) for item in prereg["cases"]]
    base_seed = int(prereg["base_seed"])
    population_count = int(prereg["population_count"])
    population_seconds = float(prereg["population_seconds"])
    alns_seconds = float(prereg["alns_seconds"])
    workers = int(prereg["workers"])
    OUT.mkdir(parents=True, exist_ok=True)
    _remove_appledouble(PACKAGE)

    rows: list[dict[str, Any]] = []
    witnesses: dict[str, Any] = {}
    for instance_id in cases:
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
        controls = {
            mode: run_homogeneous_hgs_alns_ensemble(
                bundle,
                common.solution,
                base_seed=base_seed,
                route_proxy_mode=mode,
                population_seconds=population_seconds,
                alns_seconds=alns_seconds,
                population_count=population_count,
                max_workers=workers,
            )
            for mode in ("cv_only", "naive_ev", "mechanism_ev")
        }
        candidate = run_multiview_mechanism_hybrid(
            bundle,
            common.solution,
            seed=base_seed,
            population_seconds=population_seconds,
            alns_seconds=alns_seconds,
            max_workers=workers,
        )
        arms = [
            *[
                (
                    f"homogeneous_{mode}",
                    run.completion,
                    run.elapsed_seconds,
                    run.stats,
                )
                for mode, run in controls.items()
            ],
            (
                "mvhgs_alns",
                candidate.completion,
                candidate.elapsed_seconds,
                candidate.stats,
            ),
        ]
        for arm, completion, elapsed, details in arms:
            objective, breakdown, violations = exact_china81_score(
                completion.solution,
                bundle,
            )
            rows.append(
                {
                    "instance_id": instance_id,
                    "base_seed": base_seed,
                    "arm": arm,
                    "population_count": population_count,
                    "population_seconds": population_seconds,
                    "alns_seconds": alns_seconds,
                    "worker_count": workers,
                    "elapsed_seconds": elapsed,
                    "objective": objective,
                    "feasible": not violations,
                    "violation_count": len(violations),
                    "route_count": len(completion.solution.routes),
                    "ev_route_count": sum(
                        route.vehicle_type.lower() == "ev"
                        for route in completion.solution.routes
                    ),
                    "charging_action_count": len(
                        completion.solution.charging_actions
                    ),
                    "distance_m": breakdown["distance_total"],
                    "emissions_kg": breakdown["E_total"],
                    "solution_sha256": _solution_hash(
                        completion.solution
                    ),
                }
            )
            witnesses[f"{instance_id}::{arm}"] = {
                "details": details,
                "completion_activity": completion.activity,
                "solution": asdict(completion.solution),
                "independent_breakdown": breakdown,
            }

    comparisons = _comparisons(rows, cases)
    performance_pass = all(
        item["losses"] == 0 and item["wins"] >= 1
        for item in comparisons.values()
    )
    all_feasible = all(bool(row["feasible"]) for row in rows)
    tests = _test_commands()
    tests_pass = all(item["returncode"] == 0 for item in tests)
    passed = performance_pass and all_feasible and tests_pass
    decision = {
        "schema_version": "resetp.china81-g4-equal-compute-decision.v1",
        "decision": (
            "PASS_MVHGS_ALNS_EQUAL_COMPUTE_MULTIVIEW_VALUE"
            if passed
            else "HOLD_MVHGS_ALNS_EQUAL_COMPUTE_GATE"
        ),
        "passed": passed,
        "performance_passed": performance_pass,
        "all_feasible": all_feasible,
        "tests_passed": tests_pass,
        "comparisons": comparisons,
        "case_count": len(cases),
        "base_seed": base_seed,
        "population_count": population_count,
        "population_seconds": population_seconds,
        "alns_seconds": alns_seconds,
        "worker_count": workers,
        "equal_compute": True,
        "claim_boundary": (
            "Equal population count, per-population seconds, workers, and "
            "ALNS tail; three pre-registered cases and one seed group only. "
            "Multi-seed confirmation is still required."
        ),
        "next_gate": (
            "three_seed_confirmation"
            if passed
            else "stop_or_redesign_multiview_without_parameter_scan"
        ),
    }
    metadata = {
        "schema_version": "resetp.china81-g4-equal-compute-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
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
        _report(decision),
        encoding="utf-8",
    )
    _remove_appledouble(PACKAGE)
    files = [
        Path(__file__),
        PREREG,
        PACKAGE / "pyvrp_adapter.py",
        PACKAGE / "hybrid.py",
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


def _comparisons(
    rows: list[dict[str, Any]],
    cases: list[str],
) -> dict[str, Any]:
    by_key = {
        (str(row["instance_id"]), str(row["arm"])): row
        for row in rows
    }
    output: dict[str, Any] = {}
    for control in (
        "homogeneous_cv_only",
        "homogeneous_naive_ev",
        "homogeneous_mechanism_ev",
    ):
        wins = ties = losses = 0
        details = []
        for instance_id in cases:
            candidate = float(
                by_key[(instance_id, "mvhgs_alns")]["objective"]
            )
            baseline = float(
                by_key[(instance_id, control)]["objective"]
            )
            delta = candidate - baseline
            if delta < -1.0e-9:
                result = "win"
                wins += 1
            elif delta > 1.0e-9:
                result = "loss"
                losses += 1
            else:
                result = "tie"
                ties += 1
            details.append(
                {
                    "instance_id": instance_id,
                    "candidate_cost": candidate,
                    "control_cost": baseline,
                    "candidate_minus_control": delta,
                    "result": result,
                }
            )
        output[f"mvhgs_alns_vs_{control}"] = {
            "wins": wins,
            "ties": ties,
            "losses": losses,
            "details": details,
        }
    return output


def _test_commands() -> list[dict[str, Any]]:
    return [
        _run_command(
            [
                "/opt/anaconda3/bin/python3.13",
                "-m",
                "pytest",
                "-q",
                "solver/tests/test_china81_bundle_20260720.py",
                "solver/tests/test_china81_profiled_road_matrices_nl3b_20260720.py",
                "solver/tests/test_china81_shared_completion_20260720.py",
                "solver/tests/test_china81_in_memory_winner_20260720.py",
            ]
        ),
        _run_command(
            [
                "/opt/anaconda3/bin/ruff",
                "check",
                "solver/src/setp_solver/china81.py",
                "solver/src/setp_solver/china81_completion.py",
                "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
                str(PACKAGE.relative_to(ROOT)),
            ]
        ),
    ]


def _run_command(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _solution_hash(solution: Any) -> str:
    payload = json.dumps(
        asdict(solution),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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


def _remove_appledouble(path: Path) -> None:
    for sidecar in path.rglob("._*"):
        if sidecar.is_file():
            sidecar.unlink()


def _report(decision: dict[str, Any]) -> str:
    lines = [
        "# China81 G4：MVHGS-ALNS 等算力多视角价值门",
        "",
        f"机器结论：`{decision['decision']}`。",
        "",
    ]
    for label, result in decision["comparisons"].items():
        lines.append(
            f"- `{label}`：{result['wins']} 胜 / "
            f"{result['ties']} 平 / {result['losses']} 负。"
        )
    lines.extend(
        [
            "",
            "候选和三个对照都使用三个 HGS 种群、相同单种群时长、三个",
            "worker，以及同样的机制 ALNS 收尾。唯一差别是候选让三个",
            "种群看不同的路线代价，而对照把算力重复在同一种视角。",
            "",
            "边界：只是一组种子和三道开发题，证明多视角有增量价值，",
            "尚不能替代多种子和正式 China81 统计。",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
