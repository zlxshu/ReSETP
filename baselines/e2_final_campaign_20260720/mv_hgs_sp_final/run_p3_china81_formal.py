#!/usr/bin/env python3
"""P3: China81 full 81-instance formal three-arm battle (Chen-2023 lineage).

Arms per (instance, seed), sharing phase 1 for structural zero-loss:
  mother   = single mechanism_ev-view HGS run to its own convergence,
             scored by the full nonlinear ReSETP completion.
  ablation = mother phase 1 + rotating-view continuation epochs
             (cv_only / naive_ev / mechanism_ev), NO set-partitioning.
  full     = mother phase 1 + rotating-view epochs + exact SP route-pool
             recombination each round (the frozen MV-HGS-SP engine that
             passed G-CHINA-REP).

BKS-v0 protocol (v3 contract section 9): the per-instance best across the
mother and ablation arms over all seeds is sealed as China81-BKS-v0; a
full-arm solution strictly below it is recorded as the project's current
best-known ("项目当前最好已知解"), never as a public BKS.

Resumable: completed (instance, seed) rows in raw_runs.csv are skipped.
"""
from __future__ import annotations

import csv
import hashlib
import json
import multiprocessing as mp
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
PROTO = ROOT / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
OUT = PACKAGE / "p3_china81_gate"
INSTANCE_DIR = (
    ROOT
    / "data/ChinaInstances/china81_local_directed_matrices_v9_20260718/instances"
)

for path in (ROOT / "solver/src", PROTO, ROOT, str(PACKAGE)):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from pyvrp.stop import MaxRuntime, MultipleCriteria, NoImprovement  # noqa: E402

from run_china81_convergence_gate import _run_epoch  # noqa: E402
from pyvrp_adapter import build_pyvrp_problem  # noqa: E402
from route_pool_sp import _route_pool_records, _solve_set_partitioning  # noqa: E402
from setp_solver.algorithms.resetp_alns.support.construction import (  # noqa: E402
    build_initial_solution,
)
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    complete_china81_route_skeleton,
    exact_china81_score,
)

SEEDS = (1, 2, 3, 4, 5)
ROTATION = ("cv_only", "naive_ev", "mechanism_ev")
MAX_EPOCHS = 4
STALL_EPOCHS = 2
SP_TIME = 10.0
WORKERS = 4
EPS = 1.0e-6

TIER_CAPS = {
    10: {"K_M": 3000, "CAP_M": 60.0, "K_E": 1500, "CAP_E": 20.0},
    15: {"K_M": 3000, "CAP_M": 60.0, "K_E": 1500, "CAP_E": 20.0},
    20: {"K_M": 3000, "CAP_M": 60.0, "K_E": 1500, "CAP_E": 20.0},
    25: {"K_M": 3000, "CAP_M": 90.0, "K_E": 1500, "CAP_E": 30.0},
    50: {"K_M": 3000, "CAP_M": 150.0, "K_E": 1500, "CAP_E": 40.0},
    75: {"K_M": 3000, "CAP_M": 180.0, "K_E": 1500, "CAP_E": 45.0},
    100: {"K_M": 3000, "CAP_M": 240.0, "K_E": 1500, "CAP_E": 60.0},
    150: {"K_M": 3000, "CAP_M": 300.0, "K_E": 1500, "CAP_E": 75.0},
    200: {"K_M": 3000, "CAP_M": 420.0, "K_E": 1500, "CAP_E": 90.0},
}


def _instance_list() -> list[str]:
    names = sorted(p.name for p in INSTANCE_DIR.iterdir() if p.is_dir())
    return names


def _tier_of(instance_id: str) -> int:
    match = re.search(r"-(\d+)c-", instance_id)
    if not match:
        raise ValueError(f"cannot parse size tier from {instance_id}")
    return int(match.group(1))


def _continuation(
    bundle,
    caps: dict[str, float],
    seed: int,
    mother_epoch,
    mother_completion,
    *,
    use_sp: bool,
) -> tuple[float, int]:
    """Run rotating-view continuation from the shared phase-1 state."""
    global_best = mother_completion.objective
    best_completion = mother_completion
    view_epochs = {"mechanism_ev": mother_epoch}
    elites = mother_epoch.elite_skeletons
    stall = 0
    epochs_run = 0
    for epoch_index in range(MAX_EPOCHS):
        improved = False
        if use_sp:
            pool = _route_pool_records(bundle, view_epochs)
            sp_solution, _stats = _solve_set_partitioning(
                bundle, pool, time_limit_seconds=SP_TIME
            )
            if sp_solution is not None:
                sp_completion = complete_china81_route_skeleton(sp_solution, bundle)
                if sp_completion.objective < global_best - EPS:
                    global_best = sp_completion.objective
                    best_completion = sp_completion
                    improved = True
        mode = ROTATION[epoch_index % len(ROTATION)]
        problem = build_pyvrp_problem(bundle, route_proxy_mode=mode)
        epoch_stop = MultipleCriteria(
            [NoImprovement(int(caps["K_E"])), MaxRuntime(caps["CAP_E"])]
        )
        epoch_seed = int(seed) + 1009 * (epoch_index + 1)
        epoch = _run_epoch(
            bundle, problem, best_completion.solution,
            seed=epoch_seed, stop=epoch_stop,
            warm_elites=(best_completion.solution, *elites),
        )
        epoch_best = min(epoch.elite_completions, key=lambda item: item.objective)
        if epoch_best.objective < global_best - EPS:
            global_best = epoch_best.objective
            best_completion = epoch_best
            improved = True
        view_epochs[mode] = epoch
        elites = epoch.elite_skeletons
        epochs_run += 1
        stall = 0 if improved else stall + 1
        if stall >= STALL_EPOCHS:
            break
    _, _, violations = exact_china81_score(best_completion.solution, bundle)
    if violations:
        raise RuntimeError(
            f"infeasible continuation result on seed {seed}: {len(violations)}"
        )
    return float(global_best), epochs_run


def _run_unit(args: tuple[str, int]) -> dict[str, Any]:
    instance_id, seed = args
    caps = TIER_CAPS[_tier_of(instance_id)]
    bundle = load_china81_bundle(ROOT, instance_id)
    common = complete_china81_route_skeleton(
        build_initial_solution(
            bundle.instance, bundle.time_profile, bundle.prices,
            introduce_ev=False, require_charging_signal=False,
        ),
        bundle,
    )
    started = perf_counter()
    mother_problem = build_pyvrp_problem(bundle, route_proxy_mode="mechanism_ev")
    mother_stop = MultipleCriteria(
        [NoImprovement(int(caps["K_M"])), MaxRuntime(caps["CAP_M"])]
    )
    mother_epoch = _run_epoch(
        bundle, mother_problem, common.solution,
        seed=seed, stop=mother_stop, warm_elites=(),
    )
    mother_completion = min(
        (*mother_epoch.elite_completions, common),
        key=lambda item: item.objective,
    )
    mother_cost = float(mother_completion.objective)
    mother_cpu = perf_counter() - started

    abl_started = perf_counter()
    ablation_cost, abl_epochs = _continuation(
        bundle, caps, seed, mother_epoch, mother_completion, use_sp=False
    )
    ablation_cpu = mother_cpu + (perf_counter() - abl_started)

    full_started = perf_counter()
    full_cost, full_epochs = _continuation(
        bundle, caps, seed, mother_epoch, mother_completion, use_sp=True
    )
    full_cpu = mother_cpu + (perf_counter() - full_started)

    def _vs(a: float, b: float) -> str:
        delta = a - b
        return "win" if delta < -EPS else ("loss" if delta > EPS else "tie")

    return {
        "instance_id": instance_id,
        "tier": _tier_of(instance_id),
        "seed": seed,
        "mother_cost": mother_cost,
        "mother_cpu_seconds": mother_cpu,
        "ablation_cost": ablation_cost,
        "ablation_cpu_seconds": ablation_cpu,
        "ablation_epochs": abl_epochs,
        "full_cost": full_cost,
        "full_cpu_seconds": full_cpu,
        "full_epochs": full_epochs,
        "full_vs_mother": _vs(full_cost, mother_cost),
        "full_vs_ablation": _vs(full_cost, ablation_cost),
        "ablation_vs_mother": _vs(ablation_cost, mother_cost),
        "full_improvement_pct_vs_mother": 100.0 * (mother_cost - full_cost) / mother_cost,
    }


def _completed_units(csv_path: Path) -> set[tuple[str, int]]:
    if not csv_path.exists():
        return set()
    with csv_path.open(encoding="utf-8") as handle:
        return {(row["instance_id"], int(row["seed"])) for row in csv.DictReader(handle)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUT / "raw_runs.csv"
    done = _completed_units(csv_path)
    instances = _instance_list()
    tasks = [
        (instance_id, seed)
        for instance_id in instances
        for seed in SEEDS
        if (instance_id, seed) not in done
    ]
    print(
        f"[P3-CHINA81] {len(done)} units complete; {len(tasks)} remaining "
        f"across {WORKERS} workers ({len(instances)} instances x {len(SEEDS)} seeds)",
        flush=True,
    )
    fieldnames = [
        "instance_id", "tier", "seed",
        "mother_cost", "mother_cpu_seconds",
        "ablation_cost", "ablation_cpu_seconds", "ablation_epochs",
        "full_cost", "full_cpu_seconds", "full_epochs",
        "full_vs_mother", "full_vs_ablation", "ablation_vs_mother",
        "full_improvement_pct_vs_mother",
    ]
    write_header = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        handle.flush()
        if tasks:
            with mp.Pool(processes=WORKERS) as pool:
                for row in pool.imap_unordered(_run_unit, tasks):
                    writer.writerow(row)
                    handle.flush()
                    print(
                        f"[P3-CHINA81] {row['instance_id']} seed={row['seed']} "
                        f"mother={row['mother_cost']:.2f} abl={row['ablation_cost']:.2f} "
                        f"full={row['full_cost']:.2f} "
                        f"fvm={row['full_vs_mother']} fva={row['full_vs_ablation']}",
                        flush=True,
                    )
    _finalize(csv_path)
    return 0


def _finalize(csv_path: Path) -> None:
    with csv_path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    fvm = {"win": 0, "tie": 0, "loss": 0}
    fva = {"win": 0, "tie": 0, "loss": 0}
    for row in rows:
        fvm[row["full_vs_mother"]] += 1
        fva[row["full_vs_ablation"]] += 1
    by_tier: dict[int, dict[str, int]] = {}
    for row in rows:
        tier = int(row["tier"])
        bucket = by_tier.setdefault(tier, {"win": 0, "tie": 0, "loss": 0})
        bucket[row["full_vs_mother"]] += 1
    bks_v0: dict[str, float] = {}
    project_best: dict[str, dict[str, Any]] = {}
    instances = sorted({row["instance_id"] for row in rows})
    for instance_id in instances:
        matching = [row for row in rows if row["instance_id"] == instance_id]
        sealed = min(
            min(float(row["mother_cost"]) for row in matching),
            min(float(row["ablation_cost"]) for row in matching),
        )
        bks_v0[instance_id] = sealed
        full_best = min(float(row["full_cost"]) for row in matching)
        project_best[instance_id] = {
            "bks_v0": sealed,
            "full_best": full_best,
            "project_best_known_by_full": full_best < sealed - EPS,
        }
    n_project_best = sum(
        1 for value in project_best.values() if value["project_best_known_by_full"]
    )
    decision = {
        "schema_version": "resetp.e2-final-campaign.p3-china81-formal.v1",
        "decision": (
            "P3_CHINA81_FORMAL_COMPLETE"
            if len(instances) == 81 and all(
                len([row for row in rows if row["instance_id"] == inst]) == len(SEEDS)
                for inst in instances
            )
            else "P3_CHINA81_FORMAL_PARTIAL"
        ),
        "instances_complete": len(instances),
        "seed_units_total": len(rows),
        "full_vs_mother": fvm,
        "full_vs_ablation": fva,
        "full_vs_mother_by_tier": {str(k): v for k, v in sorted(by_tier.items())},
        "project_best_known_count": n_project_best,
        "project_best": project_best,
        "claim_boundary": (
            "Three arms share phase 1 (structural zero-loss for both hybrid arms). "
            "China81-BKS-v0 = per-instance best of mother+ablation arms across "
            "seeds; a strictly better full-arm value is the project's current "
            "best-known solution, never a public BKS. CPU disclosed per arm."
        ),
    }
    metadata = {
        "schema_version": "resetp.e2-final-campaign.p3-china81-formal-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "workers": WORKERS,
        "seeds": list(SEEDS),
        "tier_caps": {str(k): v for k, v in TIER_CAPS.items()},
        "max_epochs": MAX_EPOCHS,
        "stall_epochs": STALL_EPOCHS,
        "sp_time": SP_TIME,
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "report.md").write_text(
        "\n".join([
            "# P3 China81 全量三臂正式批（血缘口径）",
            "",
            f"机器结论：`{decision['decision']}`。",
            f"完成 {len(instances)}/81 题，{len(rows)} 个种子单元。",
            f"完整体 vs 母体：{fvm}",
            f"完整体 vs 去SP消融：{fva}",
            f"完整体刷新 China81-BKS-v0 的题数：{n_project_best}",
            "",
        ]), encoding="utf-8",
    )
    files = [Path(__file__), csv_path, OUT / "metadata.json", OUT / "decision.json", OUT / "report.md"]
    (OUT / "artifact_hashes.json").write_text(
        json.dumps({
            "schema_version": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "files": {str(p.relative_to(ROOT)): _sha256(p) for p in files},
        }, ensure_ascii=False, indent=2), encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
