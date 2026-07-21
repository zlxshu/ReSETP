#!/usr/bin/env python3
"""C-arm rebalance validation against recorded P0 arm A/B results.

P0 finding: arm C (equal thirds: 30%/30%/30% views + 10% SP) ties arm A
(single mechanism_ev view, full T) overall and loses on cy-150. Diagnosis:
the equal split sacrifices backbone depth for diversity that SP does not
recover.

Pre-registered bounded fix (single revision, no further tuning):
  mechanism_ev backbone 70% T, cv_only 12.5% T, naive_ev 12.5% T, SP 5% T.

This runner re-runs ONLY the rebalanced C arm on the same 15 units
(3 instances x seeds 1-5, same wall clocks) and compares against the
A/B/C objectives recorded in p0_gate/decision.json.

Pass rule (pre-registered): zero losses vs recorded A across all 15 units
AND >= 2 strict wins vs A in the cy-150 stratum. Fail -> claim ladder D,
no second revision.
"""

from __future__ import annotations

import csv
import hashlib
import json
import multiprocessing as mp
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
PROTO = ROOT / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
OUT = PACKAGE / "rebalance_gate"
P0_DECISION = PACKAGE / "p0_gate" / "decision.json"

for path in (ROOT / "solver/src", PROTO, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from epochal_hgs import _run_exact_epoch  # noqa: E402
from pyvrp_adapter import build_pyvrp_problem  # noqa: E402
from route_pool_sp import (  # noqa: E402
    _route_pool_records,
    _solve_set_partitioning,
)
from setp_solver.algorithms.resetp_alns.support.construction import (  # noqa: E402
    build_initial_solution,
)
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    complete_china81_route_skeleton,
)

WALL_CLOCK = {
    "cn-jjj-25c-03-V2-LOCATIONS": 60.0,
    "cn-prd-75c-03-V2-LOCATIONS": 180.0,
    "cn-cy-150c-03-V2-LOCATIONS": 360.0,
}
SEEDS = (1, 2, 3, 4, 5)
VIEW_SHARES = {"mechanism_ev": 0.70, "cv_only": 0.125, "naive_ev": 0.125}
SP_SHARE = 0.05
EXACT_ELITES_PER_VIEW = 8
MAX_ARCHIVE_PER_VIEW = 24
WORKERS = 5
EPS = 1.0e-6


def _run_rebalanced_c(instance_id: str, seed: int) -> dict[str, Any]:
    import os

    smoke = os.environ.get("REBAL_SMOKE_TIME_LIMIT_SECONDS")
    runtime = float(smoke) if smoke else WALL_CLOCK[instance_id]
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
    started = perf_counter()
    sp_time = max(1.0, runtime * SP_SHARE)
    view_epochs: dict[str, Any] = {}
    for mode, share in VIEW_SHARES.items():
        problem = build_pyvrp_problem(bundle, route_proxy_mode=mode)
        view_epochs[mode] = _run_exact_epoch(
            bundle,
            problem,
            common.solution,
            seed=int(seed),
            runtime_seconds=max(0.5, runtime * share),
            warm_elites=(),
            exact_elite_count=EXACT_ELITES_PER_VIEW,
            max_archive_candidates=MAX_ARCHIVE_PER_VIEW,
        )
    parent_completions = [
        completion
        for epoch in view_epochs.values()
        for completion in epoch.elite_completions
    ]
    parent = min(parent_completions, key=lambda item: item.objective)
    records = _route_pool_records(bundle, view_epochs)
    recombined, sp_stats = _solve_set_partitioning(
        bundle, records, time_limit_seconds=sp_time
    )
    selected_source = "best_exact_hgs_parent"
    final_objective = parent.objective
    if recombined is not None:
        recombined_completion = complete_china81_route_skeleton(recombined, bundle)
        if recombined_completion.objective < parent.objective - 1.0e-9:
            final_objective = recombined_completion.objective
            selected_source = "set_partitioning_recombination"
    elapsed = perf_counter() - started
    return {
        "instance_id": instance_id,
        "seed": seed,
        "wall_clock_T": runtime,
        "C2_rebalanced_cost": float(final_objective),
        "C2_elapsed_seconds": elapsed,
        "C2_selected_source": selected_source,
        "C2_route_pool_size": len(records),
        "C2_backbone_share": VIEW_SHARES["mechanism_ev"],
    }


def _worker(args: tuple[str, int]) -> dict[str, Any]:
    return _run_rebalanced_c(*args)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    recorded = {
        (row["instance_id"], int(row["seed"])): row
        for row in json.loads(P0_DECISION.read_text(encoding="utf-8"))["details"]
    }
    tasks = [
        (instance_id, seed)
        for instance_id in WALL_CLOCK
        for seed in SEEDS
        if (instance_id, seed) in recorded
    ]
    print(f"[REBAL] {len(tasks)} units across {WORKERS} workers", flush=True)
    rows: list[dict[str, Any]] = []
    with mp.Pool(processes=WORKERS) as pool:
        for row in pool.imap_unordered(_worker, tasks):
            key = (row["instance_id"], int(row["seed"]))
            base = recorded[key]
            for label, column in (
                ("A", "A_single_view_hgs"),
                ("B", "B_multi_restart"),
                ("C1", "C_mv_hgs_sp"),
            ):
                delta = row["C2_rebalanced_cost"] - float(base[column])
                row[f"C2_vs_{label}"] = (
                    "win" if delta < -EPS else ("loss" if delta > EPS else "tie")
                )
                row[f"{label}_recorded"] = float(base[column])
            rows.append(row)
            print(
                f"[REBAL] {row['instance_id']} seed={row['seed']} "
                f"C2={row['C2_rebalanced_cost']:.2f} "
                f"A={row['A_recorded']:.2f} vs_A={row['C2_vs_A']} "
                f"vs_B={row['C2_vs_B']} src={row['C2_selected_source']}",
                flush=True,
            )
    rows.sort(key=lambda item: (item["instance_id"], item["seed"]))
    tallies = {}
    for label in ("A", "B", "C1"):
        tallies[label] = {
            "wins": sum(row[f"C2_vs_{label}"] == "win" for row in rows),
            "ties": sum(row[f"C2_vs_{label}"] == "tie" for row in rows),
            "losses": sum(row[f"C2_vs_{label}"] == "loss" for row in rows),
        }
    cy150_wins_vs_a = sum(
        row["C2_vs_A"] == "win"
        for row in rows
        if "cy-150" in row["instance_id"]
    )
    passed = tallies["A"]["losses"] == 0 and cy150_wins_vs_a >= 2
    decision = {
        "schema_version": "resetp.e2-final-campaign.c-rebalance-validation.v1",
        "decision": (
            "PASS_C_REBALANCE_ADOPT_FOR_CAMPAIGN"
            if passed
            else "FAIL_C_REBALANCE_CLAIM_LADDER_D"
        ),
        "passed": passed,
        "pass_rule": (
            "zero losses vs recorded A across 15 units AND >=2 strict wins "
            "vs A in cy-150 stratum; single pre-registered revision, no rescue"
        ),
        "view_shares": VIEW_SHARES,
        "sp_share": SP_SHARE,
        "tally_C2_vs_A": tallies["A"],
        "tally_C2_vs_B": tallies["B"],
        "tally_C2_vs_C1_equal_split": tallies["C1"],
        "cy150_wins_vs_A": cy150_wins_vs_a,
        "details": rows,
        "claim_boundary": (
            "Training-set validation on already-seen P0 units against recorded "
            "P0 objectives (same wall clocks, same machine class, same common "
            "start). Adoption gates campaign config only; fresh-instance "
            "evidence still comes from P2/P3."
        ),
    }
    metadata = {
        "schema_version": "resetp.e2-final-campaign.c-rebalance-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_executable": sys.executable,
        "workers": WORKERS,
        "p0_decision_sha256": _sha256(P0_DECISION),
    }
    fieldnames = list(rows[0].keys()) if rows else []
    with (OUT / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "report.md").write_text(
        "\n".join(
            [
                "# C 臂重平衡验证（70/12.5/12.5 + SP 5%）",
                "",
                f"机器结论：`{decision['decision']}`。",
                "",
                f"C2 vs 已录 A：{tallies['A']}",
                f"C2 vs 已录 B：{tallies['B']}",
                f"C2 vs 已录 C1（旧等分版）：{tallies['C1']}",
                f"cy-150 层对 A 严格胜场：{cy150_wins_vs_a}",
                "",
                "边界：训练集验证（P0 已见单元、对已录成绩），只决定战役配置；",
                "新鲜题证据仍由 P2/P3 产生。单次预注册修订，不再有第二轮。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    files = [
        Path(__file__),
        P0_DECISION,
        OUT / "raw_runs.csv",
        OUT / "metadata.json",
        OUT / "decision.json",
        OUT / "report.md",
    ]
    (OUT / "artifact_hashes.json").write_text(
        json.dumps(
            {
                "schema_version": "resetp.artifact-hashes.v1",
                "algorithm": "sha256",
                "files": {
                    str(path.relative_to(ROOT)): _sha256(path) for path in files
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({k: v for k, v in decision.items() if k != "details"},
                     ensure_ascii=False, indent=2), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
