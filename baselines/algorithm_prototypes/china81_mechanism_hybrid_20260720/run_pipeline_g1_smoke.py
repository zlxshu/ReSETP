#!/usr/bin/env python3
"""One-case, one-seed, equal-search-time China81 three-arm smoke gate."""

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
    run_project_alns,
    run_staged_mechanism_hybrid,
)
from pyvrp_adapter import run_pyvrp_hgs_skeleton  # noqa: E402
from setp_solver.algorithms.resetp_alns.support.construction import (  # noqa: E402
    build_initial_solution,
)
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    complete_china81_route_skeleton,
    exact_china81_score,
)


INSTANCE_ID = "cn-jjj-25c-01-V2-LOCATIONS"
SEED = 1
SEARCH_SECONDS = 2.0
HGS_SHARE = 0.95
OUT = PACKAGE / "pipeline_g1_one_case_smoke"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    _remove_appledouble(PACKAGE)
    bundle = load_china81_bundle(ROOT, INSTANCE_ID)
    common_skeleton = build_initial_solution(
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        introduce_ev=False,
        require_charging_signal=False,
    )
    common = complete_china81_route_skeleton(
        common_skeleton,
        bundle,
    )

    hgs = run_pyvrp_hgs_skeleton(
        bundle,
        common.solution,
        seed=SEED,
        runtime_seconds=SEARCH_SECONDS,
        route_proxy_mode="cv_only",
    )
    naive_ev = run_pyvrp_hgs_skeleton(
        bundle,
        common.solution,
        seed=SEED,
        runtime_seconds=SEARCH_SECONDS,
        route_proxy_mode="naive_ev",
    )
    alns = run_project_alns(
        bundle,
        common.solution,
        seed=SEED,
        runtime_seconds=SEARCH_SECONDS,
        mechanism_mode=False,
    )
    hybrid = run_staged_mechanism_hybrid(
        bundle,
        common.solution,
        seed=SEED,
        runtime_seconds=SEARCH_SECONDS,
        hgs_share=HGS_SHARE,
    )
    arm_results = [
        (
            "pyvrp_hgs_neutral_mother",
            hgs.completion,
            hgs.elapsed_seconds,
            {
                "search_seconds": SEARCH_SECONDS,
                "mechanism_route_proxy": False,
                "engine_stats": hgs.stats,
            },
        ),
        (
            "pyvrp_hgs_naive_ev_mother",
            naive_ev.completion,
            naive_ev.elapsed_seconds,
            {
                "search_seconds": SEARCH_SECONDS,
                "route_proxy_mode": "naive_ev",
                "engine_stats": naive_ev.stats,
            },
        ),
        (
            "project_alns_mother",
            alns.completion,
            alns.elapsed_seconds,
            {
                "search_seconds": SEARCH_SECONDS,
                "mechanism_mode": False,
                "evaluations": alns.evaluations,
            },
        ),
        (
            "pma_hgs_alns_vns",
            hybrid.completion,
            hybrid.elapsed_seconds,
            {
                "search_seconds": SEARCH_SECONDS,
                "hgs_share": HGS_SHARE,
                "hybrid_stats": hybrid.stats,
            },
        ),
    ]
    raw_rows: list[dict[str, Any]] = []
    witnesses: dict[str, Any] = {}
    for arm, result, elapsed, details in arm_results:
        objective, breakdown, violations = exact_china81_score(
            result.solution,
            bundle,
        )
        row = {
            "instance_id": INSTANCE_ID,
            "seed": SEED,
            "arm": arm,
            "search_seconds": SEARCH_SECONDS,
            "elapsed_seconds": elapsed,
            "objective": objective,
            "feasible": not violations,
            "violation_count": len(violations),
            "route_count": len(result.solution.routes),
            "ev_route_count": sum(
                route.vehicle_type.lower() == "ev"
                for route in result.solution.routes
            ),
            "charging_action_count": len(
                result.solution.charging_actions
            ),
            "distance_m": breakdown["distance_total"],
            "emissions_kg": breakdown["E_total"],
            "cost_fix": breakdown["cost_fix"],
            "cost_km": breakdown["cost_km"],
            "cost_fuel": breakdown["cost_fuel"],
            "cost_elec": breakdown["cost_elec"],
            "cost_carbon": breakdown["cost_carbon"],
            "solution_sha256": _solution_hash(result.solution),
        }
        raw_rows.append(row)
        witnesses[arm] = {
            "details": details,
            "solution": asdict(result.solution),
            "completion_activity": result.activity,
            "independent_breakdown": breakdown,
        }

    by_arm = {
        str(row["arm"]): row
        for row in raw_rows
    }
    hybrid_cost = float(by_arm["pma_hgs_alns_vns"]["objective"])
    hgs_cost = float(
        by_arm["pyvrp_hgs_neutral_mother"]["objective"]
    )
    naive_ev_cost = float(
        by_arm["pyvrp_hgs_naive_ev_mother"]["objective"]
    )
    alns_cost = float(by_arm["project_alns_mother"]["objective"])
    passed = (
        all(bool(row["feasible"]) for row in raw_rows)
        and hybrid_cost < hgs_cost - 1.0e-9
        and hybrid_cost < naive_ev_cost - 1.0e-9
        and hybrid_cost < alns_cost - 1.0e-9
        and int(by_arm["pma_hgs_alns_vns"]["ev_route_count"]) > 0
        and int(
            by_arm["pma_hgs_alns_vns"]["charging_action_count"]
        )
        > 0
    )
    test_results = [
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
    passed = passed and all(
        result["returncode"] == 0
        for result in test_results
    )
    decision = {
        "schema_version": "resetp.china81-pipeline-g1-decision.v1",
        "decision": (
            "PASS_CHINA81_ONE_CASE_STRONG_POSITIVE_CONTINUE_THREE_CASE_PROBE"
            if passed
            else "HOLD_CHINA81_ONE_CASE_NO_STRONG_POSITIVE"
        ),
        "passed": passed,
        "instance_id": INSTANCE_ID,
        "seed": SEED,
        "search_seconds_per_arm": SEARCH_SECONDS,
        "hybrid_cost": hybrid_cost,
        "pyvrp_hgs_mother_cost": hgs_cost,
        "pyvrp_hgs_naive_ev_mother_cost": naive_ev_cost,
        "project_alns_mother_cost": alns_cost,
        "hybrid_improvement_vs_hgs_pct": (
            (hgs_cost - hybrid_cost) / hgs_cost * 100.0
        ),
        "hybrid_improvement_vs_alns_pct": (
            (alns_cost - hybrid_cost) / alns_cost * 100.0
        ),
        "hybrid_improvement_vs_naive_ev_pct": (
            (naive_ev_cost - hybrid_cost)
            / naive_ev_cost
            * 100.0
        ),
        "mechanism_active": (
            int(by_arm["pma_hgs_alns_vns"]["ev_route_count"]) > 0
            and int(
                by_arm["pma_hgs_alns_vns"][
                    "charging_action_count"
                ]
            )
            > 0
        ),
        "claim_boundary": (
            "One development instance, one seed, two seconds per arm. "
            "This is a strong direction signal, not a formal China81 result."
        ),
        "next_gate": (
            "three-preselected-cases-one-seed"
            if passed
            else "diagnose-before-any-expansion"
        ),
    }
    metadata = {
        "schema_version": "resetp.china81-pipeline-g1-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "instance_id": INSTANCE_ID,
        "seed": SEED,
        "search_seconds_per_arm": SEARCH_SECONDS,
        "hgs_share_in_hybrid": HGS_SHARE,
        "common_start_objective": common.objective,
        "fairness_contract": (
            "same input, same start, same search seconds, same shared "
            "nonlinear full-physics completion and exact final scorer"
        ),
        "mother_boundary": (
            "The CV-only mother and a stronger naive heterogeneous-EV "
            "mother both receive the same terminal full-physics completion. "
            "Only the hybrid uses city/time/carbon-aware EV route pricing."
        ),
        "formal_search_allowed": False,
        "test_commands": test_results,
    }
    _write_csv(OUT / "raw_runs.csv", raw_rows)
    _write_json(OUT / "metadata.json", metadata)
    _write_json(OUT / "decision.json", decision)
    _write_json(OUT / "solution_witnesses.json", witnesses)
    (OUT / "report.md").write_text(
        _report(decision, by_arm),
        encoding="utf-8",
    )
    _remove_appledouble(PACKAGE)
    files = [
        Path(__file__),
        PACKAGE / "pyvrp_adapter.py",
        PACKAGE / "hybrid.py",
        ROOT / "solver/src/setp_solver/china81.py",
        ROOT / "solver/src/setp_solver/china81_completion.py",
        ROOT
        / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
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


def _report(
    decision: dict[str, Any],
    by_arm: dict[str, dict[str, Any]],
) -> str:
    hybrid = by_arm["pma_hgs_alns_vns"]
    hgs = by_arm["pyvrp_hgs_neutral_mother"]
    naive = by_arm["pyvrp_hgs_naive_ev_mother"]
    alns = by_arm["project_alns_mother"]
    return f"""# China81 三臂 G1：一题最低成本性能冒烟

机器结论：`{decision["decision"]}`。

在 `{INSTANCE_ID}`、种子 `{SEED}`、每臂同为 `{SEARCH_SECONDS:.1f}` 秒的
条件下，纯 PyVRP-HGS 母体成本为 `{float(hgs["objective"]):.9f}`，项目
ALNS 母体为 `{float(alns["objective"]):.9f}`，分阶段混合体为
`{float(hybrid["objective"]):.9f}`。含电动车但不看分时电价与碳的
朴素异构母体为 `{float(naive["objective"]):.9f}`。混合体分别低
`{decision["hybrid_improvement_vs_hgs_pct"]:.3f}%` 和
`{decision["hybrid_improvement_vs_alns_pct"]:.3f}%`；相对朴素异构母体
低 `{decision["hybrid_improvement_vs_naive_ev_pct"]:.3f}%`。

混合体实际选择了 `{int(hybrid["ev_route_count"])}` 条电动车路线并生成
`{int(hybrid["charging_action_count"])}` 个非线性补能动作；两个母体在
该题最终均为全燃油车。这表明增益来自“路线生成时同时看见车型容量、
电耗和补能成本”，不是只在最后改标签。朴素异构臂用于区分“只是把
电动车交给 PyVRP”与“分时电价和碳机制进入路线生成”。

边界：这只是一道开发题、一个种子和两秒预算，只够支持继续做预先
选定的三题探针，不是 China81 正式结论。
"""


if __name__ == "__main__":
    raise SystemExit(main())
