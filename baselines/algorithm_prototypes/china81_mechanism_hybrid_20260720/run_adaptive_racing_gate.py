#!/usr/bin/env python3
"""Run G5 development or G6 fresh adaptive-racing evidence."""

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
for path in (ROOT / "solver/src", PACKAGE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hybrid import (  # noqa: E402
    run_adaptive_multiview_hybrid,
    run_homogeneous_hgs_alns_ensemble,
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
    gate = sys.argv[1] if len(sys.argv) > 1 else "g5"
    if gate not in {"g5", "g6"}:
        raise ValueError("gate must be g5 or g6")
    prereg = PACKAGE / (
        "g5_adaptive_racing_preregistration.json"
        if gate == "g5"
        else "g6_fresh_adaptive_racing_preregistration.json"
    )
    out = PACKAGE / (
        "g5_adaptive_racing_diagnostic"
        if gate == "g5"
        else "g6_fresh_adaptive_racing_gate"
    )
    contract = json.loads(prereg.read_text(encoding="utf-8"))
    if gate == "g6":
        g5_decision = json.loads(
            (
                PACKAGE
                / "g5_adaptive_racing_diagnostic/decision.json"
            ).read_text(encoding="utf-8")
        )
        if not g5_decision["passed"]:
            raise RuntimeError("G6 is forbidden because G5 did not pass")
    cases = [str(item) for item in contract["cases"]]
    base_seed = int(contract["base_seed"])
    population_count = int(contract["population_count"])
    population_seconds = float(contract["population_seconds"])
    scout_share = float(contract["scout_share"])
    alns_seconds = float(contract["alns_seconds"])
    workers = int(contract["workers"])
    out.mkdir(parents=True, exist_ok=True)
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
        candidate = run_adaptive_multiview_hybrid(
            bundle,
            common.solution,
            base_seed=base_seed,
            population_seconds=population_seconds,
            alns_seconds=alns_seconds,
            scout_share=scout_share,
            exploitation_population_count=population_count,
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
                "amv_hgs_alns",
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
    if gate == "g5":
        performance_pass = all(
            result["losses"] == 0 and result["wins"] >= 1
            for result in comparisons["by_control"].values()
        )
    else:
        performance_pass = (
            comparisons["versus_best_control"]["losses"] == 0
            and comparisons["versus_best_control"]["wins"] >= 1
        )
    all_feasible = all(bool(row["feasible"]) for row in rows)
    tests = _test_commands()
    tests_pass = all(item["returncode"] == 0 for item in tests)
    passed = performance_pass and all_feasible and tests_pass
    decision = {
        "schema_version": f"resetp.china81-{gate}-decision.v1",
        "decision": (
            f"PASS_{gate.upper()}_AMV_HGS_ALNS"
            if passed
            else f"HOLD_{gate.upper()}_AMV_HGS_ALNS"
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
        "scout_share": scout_share,
        "alns_seconds": alns_seconds,
        "worker_count": workers,
        "equal_hgs_cpu_seconds": 3.0 * population_seconds,
        "claim_boundary": (
            "Seen-case structural diagnostic only."
            if gate == "g5"
            else "Fresh cases, but one seed group only; formal statistics "
            "and the full China81 are not yet justified."
        ),
        "next_gate": (
            "g6_fresh_adaptive_racing"
            if gate == "g5" and passed
            else (
                "multi_seed_confirmation"
                if gate == "g6" and passed
                else "stop_or_pivot"
            )
        ),
    }
    metadata = {
        "schema_version": f"resetp.china81-{gate}-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "preregistration": str(prereg.relative_to(ROOT)),
        "preregistration_sha256": _sha256(prereg),
        "formal_search_allowed": False,
        "test_commands": tests,
    }
    _write_csv(out / "raw_runs.csv", rows)
    _write_json(out / "metadata.json", metadata)
    _write_json(out / "decision.json", decision)
    _write_json(out / "solution_witnesses.json", witnesses)
    (out / "report.md").write_text(
        _report(gate, decision),
        encoding="utf-8",
    )
    _remove_appledouble(PACKAGE)
    files = [
        Path(__file__),
        prereg,
        PACKAGE / "pyvrp_adapter.py",
        PACKAGE / "hybrid.py",
        ROOT / "solver/src/setp_solver/china81_completion.py",
        out / "metadata.json",
        out / "raw_runs.csv",
        out / "decision.json",
        out / "solution_witnesses.json",
        out / "report.md",
    ]
    _write_json(
        out / "artifact_hashes.json",
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
    by_control: dict[str, Any] = {}
    control_names = (
        "homogeneous_cv_only",
        "homogeneous_naive_ev",
        "homogeneous_mechanism_ev",
    )
    for control in control_names:
        by_control[control] = _summarise(
            [
                (
                    instance_id,
                    float(by_key[(instance_id, "amv_hgs_alns")]["objective"]),
                    float(by_key[(instance_id, control)]["objective"]),
                )
                for instance_id in cases
            ]
        )
    versus_best = _summarise(
        [
            (
                instance_id,
                float(by_key[(instance_id, "amv_hgs_alns")]["objective"]),
                min(
                    float(by_key[(instance_id, control)]["objective"])
                    for control in control_names
                ),
            )
            for instance_id in cases
        ]
    )
    return {
        "by_control": by_control,
        "versus_best_control": versus_best,
    }


def _summarise(
    triples: list[tuple[str, float, float]],
) -> dict[str, Any]:
    wins = ties = losses = 0
    details = []
    for instance_id, candidate, control in triples:
        delta = candidate - control
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
                "control_cost": control,
                "candidate_minus_control": delta,
                "result": result,
            }
        )
    return {
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "details": details,
    }


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


def _report(gate: str, decision: dict[str, Any]) -> str:
    lines = [
        f"# China81 {gate.upper()}：AMV-HGS-ALNS 自适应赛马门",
        "",
        f"机器结论：`{decision['decision']}`。",
        "",
    ]
    for label, result in decision["comparisons"]["by_control"].items():
        lines.append(
            f"- 对 `{label}`：{result['wins']} 胜 / "
            f"{result['ties']} 平 / {result['losses']} 负。"
        )
    best = decision["comparisons"]["versus_best_control"]
    lines.extend(
        [
            f"- 对逐题最强同质对照：{best['wins']} 胜 / "
            f"{best['ties']} 平 / {best['losses']} 负。",
            "",
            "候选先用三种路线价值观短侦察，再把剩余算力动态调给",
            "当题表现最好的价值观；总 HGS CPU、并发数和 ALNS 收尾",
            "与三个同质对照相同。完整模型精确目标始终是唯一裁判。",
            "",
            f"边界：{decision['claim_boundary']}",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
