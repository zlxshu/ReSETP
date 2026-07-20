#!/usr/bin/env python3
"""Pre-registered three-case China81 mechanism diagnostic."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
PREREG = PACKAGE / "g2_three_case_preregistration.json"
OUT = PACKAGE / "g2_three_case_diagnostic"
for path in (ROOT / "solver/src", PACKAGE, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hybrid import (  # noqa: E402
    run_project_alns,
    run_staged_mechanism_hybrid,
)
from mechanism_split import mechanism_resource_split  # noqa: E402
from pyvrp_adapter import run_pyvrp_hgs_skeleton  # noqa: E402
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
    seed = int(prereg["seed"])
    seconds = float(prereg["search_seconds_per_primary_arm"])
    hgs_share = float(prereg["hybrid_hgs_share"])
    max_route_orders = int(
        prereg["diagnostic_postprocessor"]["max_route_orders"]
    )
    OUT.mkdir(parents=True, exist_ok=True)
    _remove_appledouble(PACKAGE)

    raw_rows: list[dict[str, Any]] = []
    witnesses: dict[str, Any] = {}
    for instance_id in cases:
        bundle = load_china81_bundle(ROOT, instance_id)
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
        cv = run_pyvrp_hgs_skeleton(
            bundle,
            common.solution,
            seed=seed,
            runtime_seconds=seconds,
            route_proxy_mode="cv_only",
        )
        naive = run_pyvrp_hgs_skeleton(
            bundle,
            common.solution,
            seed=seed,
            runtime_seconds=seconds,
            route_proxy_mode="naive_ev",
        )
        alns = run_project_alns(
            bundle,
            common.solution,
            seed=seed,
            runtime_seconds=seconds,
            mechanism_mode=False,
        )
        hybrid = run_staged_mechanism_hybrid(
            bundle,
            common.solution,
            seed=seed,
            runtime_seconds=seconds,
            hgs_share=hgs_share,
        )
        split_started = perf_counter()
        split = mechanism_resource_split(
            hybrid.completion.solution,
            bundle,
            max_route_orders=max_route_orders,
        )
        split_elapsed = perf_counter() - split_started
        arms = [
            (
                "pyvrp_hgs_cv_only",
                cv.completion,
                cv.elapsed_seconds,
                seconds,
                {"engine_stats": cv.stats},
            ),
            (
                "pyvrp_hgs_naive_ev",
                naive.completion,
                naive.elapsed_seconds,
                seconds,
                {"engine_stats": naive.stats},
            ),
            (
                "project_alns",
                alns.completion,
                alns.elapsed_seconds,
                seconds,
                {
                    "evaluations": alns.evaluations,
                    "mechanism_mode": False,
                },
            ),
            (
                "pma_hgs_alns_vns",
                hybrid.completion,
                hybrid.elapsed_seconds,
                seconds,
                {"hybrid_stats": hybrid.stats},
            ),
            (
                "pma_plus_mechanism_split_diagnostic",
                split.completion,
                hybrid.elapsed_seconds + split_elapsed,
                seconds,
                {
                    "primary_gate_member": False,
                    "split_elapsed_seconds": split_elapsed,
                    "split_activity": split.activity,
                },
            ),
        ]
        for arm, completion, elapsed, search_seconds, details in arms:
            objective, breakdown, violations = exact_china81_score(
                completion.solution,
                bundle,
            )
            raw_rows.append(
                {
                    "instance_id": instance_id,
                    "seed": seed,
                    "arm": arm,
                    "primary_gate_member": (
                        arm
                        != "pma_plus_mechanism_split_diagnostic"
                    ),
                    "search_seconds": search_seconds,
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

    comparisons = _comparisons(raw_rows, cases)
    time_proxy_pass = (
        comparisons["hybrid_vs_naive_ev"]["losses"] == 0
        and comparisons["hybrid_vs_naive_ev"]["wins"] >= 1
    )
    broad_pass = (
        comparisons["hybrid_vs_cv_only"]["wins"] >= 2
        and comparisons["hybrid_vs_project_alns"]["wins"] >= 2
    )
    split_pass = comparisons["split_vs_hybrid"]["wins"] >= 1
    all_feasible = all(
        bool(row["feasible"])
        for row in raw_rows
    )
    tests = _test_commands()
    tests_pass = all(
        item["returncode"] == 0
        for item in tests
    )
    decision_label = (
        "CONTINUE_TIME_CARBON_PROXY"
        if time_proxy_pass
        else "STOP_TIME_CARBON_PROXY_NO_INCREMENTAL_VALUE"
    )
    split_label = (
        "CONTINUE_MECHANISM_SPLIT"
        if split_pass
        else "STOP_MECHANISM_SPLIT_NO_INCREMENTAL_VALUE"
    )
    decision = {
        "schema_version": "resetp.china81-g2-decision.v1",
        "decision": (
            "PASS_G2_DIAGNOSTIC"
            if all_feasible and tests_pass
            else "HOLD_G2_PIPELINE_OR_FEASIBILITY"
        ),
        "pipeline_passed": all_feasible and tests_pass,
        "time_carbon_proxy_decision": decision_label,
        "broad_mother_signal_passed": broad_pass,
        "mechanism_split_decision": split_label,
        "comparisons": comparisons,
        "case_count": len(cases),
        "seed": seed,
        "search_seconds_per_primary_arm": seconds,
        "claim_boundary": (
            "Three pre-registered cases, one seed, two seconds. "
            "This diagnoses components; it is not a formal China81 result."
        ),
        "next_action": (
            "keep_only_components_with_incremental_value_and_redesign"
            if all_feasible and tests_pass
            else "repair_pipeline_before_any_more_search"
        ),
    }
    metadata = {
        "schema_version": "resetp.china81-g2-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "preregistration": str(PREREG.relative_to(ROOT)),
        "preregistration_sha256": _sha256(PREREG),
        "cases": cases,
        "seed": seed,
        "search_seconds_per_primary_arm": seconds,
        "hybrid_hgs_share": hgs_share,
        "test_commands": tests,
        "formal_search_allowed": False,
    }
    _write_csv(OUT / "raw_runs.csv", raw_rows)
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
        PACKAGE / "mechanism_split.py",
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
    return 0 if all_feasible and tests_pass else 1


def _comparisons(
    rows: list[dict[str, Any]],
    cases: list[str],
) -> dict[str, Any]:
    by_key = {
        (str(row["instance_id"]), str(row["arm"])): row
        for row in rows
    }
    pairs = {
        "hybrid_vs_cv_only": (
            "pma_hgs_alns_vns",
            "pyvrp_hgs_cv_only",
        ),
        "hybrid_vs_naive_ev": (
            "pma_hgs_alns_vns",
            "pyvrp_hgs_naive_ev",
        ),
        "hybrid_vs_project_alns": (
            "pma_hgs_alns_vns",
            "project_alns",
        ),
        "split_vs_hybrid": (
            "pma_plus_mechanism_split_diagnostic",
            "pma_hgs_alns_vns",
        ),
    }
    output: dict[str, Any] = {}
    for label, (candidate, control) in pairs.items():
        details = []
        wins = ties = losses = 0
        for instance_id in cases:
            candidate_cost = float(
                by_key[(instance_id, candidate)]["objective"]
            )
            control_cost = float(
                by_key[(instance_id, control)]["objective"]
            )
            delta = candidate_cost - control_cost
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
                    "candidate_cost": candidate_cost,
                    "control_cost": control_cost,
                    "candidate_minus_control": delta,
                    "result": result,
                }
            )
        output[label] = {
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
    comparisons = decision["comparisons"]
    time_proxy = comparisons["hybrid_vs_naive_ev"]
    broad_cv = comparisons["hybrid_vs_cv_only"]
    broad_alns = comparisons["hybrid_vs_project_alns"]
    split = comparisons["split_vs_hybrid"]
    return f"""# China81 G2：三题预注册机制诊断

管道结论：`{decision["decision"]}`。

机制时变代理相对朴素异构电动车母体为
`{time_proxy["wins"]}胜/{time_proxy["ties"]}平/{time_proxy["losses"]}负`，
机器裁决为 `{decision["time_carbon_proxy_decision"]}`。这项裁决只回答
“分时电价与碳进入路线代理是否在三题中增加价值”，不否定异构车型
进入路线生成本身的价值。

完整混合体相对 CV-only HGS 为
`{broad_cv["wins"]}胜/{broad_cv["ties"]}平/{broad_cv["losses"]}负`，
相对项目 ALNS 为
`{broad_alns["wins"]}胜/{broad_alns["ties"]}平/{broad_alns["losses"]}负`。

资源扩展 Split 相对冻结混合体为
`{split["wins"]}胜/{split["ties"]}平/{split["losses"]}负`，机器裁决为
`{decision["mechanism_split_decision"]}`。Split 是额外后处理诊断，不
冒充等墙钟主臂。

边界：三道预注册题、一个种子、每主臂两秒，只用于决定部件去留，
不能写成 China81 正式算法结论。
"""


if __name__ == "__main__":
    raise SystemExit(main())
