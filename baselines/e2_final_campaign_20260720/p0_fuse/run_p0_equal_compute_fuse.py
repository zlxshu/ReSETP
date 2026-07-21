#!/usr/bin/env python3
"""P0: China81 equal-compute four-arm fuse gate for MV-HGS-SP.

Arms (all equal wall-clock T per instance, single-threaded):
  A - single-view HGS (mechanism_ev), full T
  B - multi-restart control: same single view, 3 independent seeds x T/3, keep best
  C - MV-HGS-SP full (three-view HGS + exact set-partitioning recombination), T total
  D - independent ReSETP mechanism ALNS + same completer, full T

This gate answers whether the multi-view + SP increment survives equal compute,
per docs/handoff/e2_final_algorithm_experiment_construction_20260720.md P0.
"""

from __future__ import annotations

from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any
from typing import Optional

ROOT = Path(__file__).resolve().parents[3]
HYBRID_PKG = ROOT / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
OUT = Path(__file__).resolve().parent / "p0_gate"
for path in (ROOT / "solver/src", HYBRID_PKG, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hybrid import run_project_alns  # noqa: E402
from pyvrp_adapter import run_pyvrp_hgs_skeleton  # noqa: E402
from route_pool_sp import run_hgs_route_pool_recombination  # noqa: E402
from run_true_hgs_h0 import _remove_appledouble  # noqa: E402
from setp_solver.algorithms.resetp_alns.support.construction import (  # noqa: E402
    build_initial_solution,
)
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    complete_china81_route_skeleton,
    exact_china81_score,
)

# Wall clock per instance, seconds. Pre-registered before any P0 result seen.
_DEFAULT_CASES = {
    "cn-jjj-25c-03-V2-LOCATIONS": 60.0,
    "cn-prd-75c-03-V2-LOCATIONS": 180.0,
    "cn-cy-150c-03-V2-LOCATIONS": 360.0,
}
_DEFAULT_SEEDS = (1, 2, 3, 4, 5)
SP_SHARE = 0.10  # fraction of T given to set-partitioning inside arm C


def _coerce_cases(payload: Optional[str]) -> dict[str, float]:
    if not payload:
        return _DEFAULT_CASES
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "P0_CASES must be JSON dict like '{\"cn-cy-150c...\": 360.0}'"
        ) from exc
    if not isinstance(raw, dict):
        raise ValueError("P0_CASES JSON must be a dict")
    out: dict[str, float] = {}
    for key, value in raw.items():
        out[str(key)] = float(value)
    return out


def _coerce_seeds(payload: Optional[str]) -> tuple[int, ...]:
    if not payload:
        return _DEFAULT_SEEDS
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "P0_SEEDS must be JSON list like '[1,2,3,4,5]'"
        ) from exc
    if not isinstance(raw, list):
        raise ValueError("P0_SEEDS JSON must be a list")
    return tuple(int(v) for v in raw)


def _route_view_histogram(solution, view_epochs) -> dict[str, int]:
    """Count how many of the final solution's routes match each view's elite pool by signature."""
    from setp_solver.algorithms.resetp_alns.operators.strong_bridge import (
        solution_signature_hash,
    )

    histogram: dict[str, int] = {mode: 0 for mode in view_epochs}
    view_route_sigs: dict[str, set[str]] = {}
    for mode, epoch in view_epochs.items():
        sigs: set[str] = set()
        for completion in epoch.elite_completions:
            for route in completion.solution.routes:
                sigs.add(f"{route.vehicle_id}:{tuple(route.node_sequence)}")
        view_route_sigs[mode] = sigs
    for route in solution.routes:
        key = f"{route.vehicle_id}:{tuple(route.node_sequence)}"
        for mode, sigs in view_route_sigs.items():
            if key in sigs:
                histogram[mode] += 1
    return histogram


def run_arm_a(bundle, common, seed: int, runtime: float):
    started = perf_counter()
    run = run_pyvrp_hgs_skeleton(
        bundle, common.solution, seed=seed, runtime_seconds=runtime,
        route_proxy_mode="mechanism_ev",
    )
    return run.completion.objective, perf_counter() - started


def run_arm_b(bundle, common, seed: int, runtime: float):
    started = perf_counter()
    share = runtime / 3.0
    best = None
    for offset in range(3):
        run = run_pyvrp_hgs_skeleton(
            bundle, common.solution, seed=seed * 1000 + offset, runtime_seconds=share,
            route_proxy_mode="mechanism_ev",
        )
        if best is None or run.completion.objective < best:
            best = run.completion.objective
    return best, perf_counter() - started


def run_arm_c(bundle, common, seed: int, runtime: float):
    sp_time = max(1.0, runtime * SP_SHARE)
    hgs_per_view = max(0.5, (runtime - sp_time) / 3.0)
    started = perf_counter()
    run = run_hgs_route_pool_recombination(
        bundle, common.solution, seed=seed,
        hgs_seconds_per_view=hgs_per_view,
        exact_elites_per_view=8,
        max_archive_candidates_per_view=24,
        sp_time_limit_seconds=sp_time,
    )
    histogram = _route_view_histogram(run.solution, run.view_epochs)
    return run.completion.objective, perf_counter() - started, run.stats, histogram


def run_arm_d(bundle, common, seed: int, runtime: float):
    started = perf_counter()
    run = run_project_alns(
        bundle, common.solution, seed=seed, runtime_seconds=runtime,
        mechanism_mode=True,
    )
    return run.completion.objective, perf_counter() - started


def _load_existing_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows: list[dict[str, Any]] = []
        for row in reader:
            parsed = dict(row)
            parsed["seed"] = int(float(parsed["seed"]))
            parsed["wall_clock_T"] = float(parsed["wall_clock_T"])
            parsed["A_single_view_hgs"] = float(parsed["A_single_view_hgs"])
            parsed["A_elapsed"] = float(parsed["A_elapsed"])
            parsed["B_multi_restart"] = float(parsed["B_multi_restart"])
            parsed["B_elapsed"] = float(parsed["B_elapsed"])
            parsed["C_mv_hgs_sp"] = float(parsed["C_mv_hgs_sp"])
            parsed["C_elapsed"] = float(parsed["C_elapsed"])
            parsed["D_independent_alns"] = float(parsed["D_independent_alns"])
            parsed["D_elapsed"] = float(parsed["D_elapsed"])
            rows.append(parsed)
    return rows


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    _remove_appledouble(HYBRID_PKG)

    # Runtime can be overridden for recovery; keep pre-registration by default.
    cases: dict[str, float] = _coerce_cases(sys.argv[1] if len(sys.argv) > 1 else None)
    seeds: tuple[int, ...] = _coerce_seeds(sys.argv[2] if len(sys.argv) > 2 else None)
    rows: list[dict[str, Any]] = []
    done = {
        (row["instance_id"], row["seed"])
        for row in _load_existing_rows(OUT / "raw_runs.csv")
    }
    rows.extend(_load_existing_rows(OUT / "raw_runs.csv"))
    attribution: dict[str, Any] = {}
    if (OUT / "attribution.json").exists():
        with (OUT / "attribution.json").open("r", encoding="utf-8") as handle:
            attribution = json.load(handle)

    for instance_id, T in cases.items():
        bundle = load_china81_bundle(ROOT, instance_id)
        common = complete_china81_route_skeleton(
            build_initial_solution(
                bundle.instance, bundle.time_profile, bundle.prices,
                introduce_ev=False, require_charging_signal=False,
            ),
            bundle,
        )
        for seed in seeds:
            if (instance_id, seed) in done:
                continue
            a_obj, a_t = run_arm_a(bundle, common, seed, T)
            b_obj, b_t = run_arm_b(bundle, common, seed, T)
            c_obj, c_t, c_stats, c_hist = run_arm_c(bundle, common, seed, T)
            d_obj, d_t = run_arm_d(bundle, common, seed, T)
            row = {
                "instance_id": instance_id,
                "seed": seed,
                "wall_clock_T": T,
                "A_single_view_hgs": a_obj,
                "A_elapsed": a_t,
                "B_multi_restart": b_obj,
                "B_elapsed": b_t,
                "C_mv_hgs_sp": c_obj,
                "C_elapsed": c_t,
                "C_selected_source": c_stats["selected_source"],
                "D_independent_alns": d_obj,
                "D_elapsed": d_t,
                "C_vs_A": "win" if c_obj < a_obj - 1e-9 else ("loss" if c_obj > a_obj + 1e-9 else "tie"),
                "C_vs_B": "win" if c_obj < b_obj - 1e-9 else ("loss" if c_obj > b_obj + 1e-9 else "tie"),
                "C_vs_D": "win" if c_obj < d_obj - 1e-9 else ("loss" if c_obj > d_obj + 1e-9 else "tie"),
            }
            attribution[f"{instance_id}::seed-{seed}"] = {
                "route_view_histogram": c_hist,
                "cross_view_recombination": len([v for v in c_hist.values() if v > 0]) > 1,
                "sp_selected_source": c_stats["selected_source"],
            }
            raw_csv = OUT / "raw_runs.csv"
            exists = raw_csv.exists()
            with raw_csv.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
                if not exists:
                    writer.writeheader()
                writer.writerow(row)
            with (OUT / "attribution.json").open("w", encoding="utf-8") as handle:
                json.dump(attribution, handle, ensure_ascii=False, indent=2)
            print(json.dumps(row, ensure_ascii=False))
            rows.append(row)

    expected = len(cases) * len(seeds)
    if len(rows) < expected:
        done_pairs = {(r["instance_id"], r["seed"]) for r in rows}
        remaining = [
            (instance_id, seed)
            for instance_id in cases
            for seed in seeds
            if (instance_id, seed) not in done_pairs
        ]
        decision = {
            "schema_version": "resetp.e2-final-campaign.p0-equal-compute-fuse.resume-partial.v1",
            "decision": "P0_PARTIAL",
            "rows_seen": len(rows),
            "rows_expected": expected,
            "remaining": remaining,
            "next_step": "rerun with same params",
        }
        (OUT / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
        return 2

    # Keep only required file footprint for completed run
    if not rows:
        raise RuntimeError("No rows were produced. Check runtime parameters.")
    def _tally(key: str) -> dict[str, int]:
        return {
            "wins": sum(r[key] == "win" for r in rows),
            "ties": sum(r[key] == "tie" for r in rows),
            "losses": sum(r[key] == "loss" for r in rows),
        }

    tally_a = _tally("C_vs_A")
    tally_b = _tally("C_vs_B")
    tally_d = _tally("C_vs_D")

    c_beats_b = tally_b["losses"] == 0
    c_beats_a = tally_a["losses"] == 0
    c_beats_d = tally_d["losses"] == 0

    if c_beats_a and c_beats_b and c_beats_d:
        claim_tier = "A"
    elif c_beats_d and not c_beats_b:
        claim_tier = "B"
    elif c_beats_a and c_beats_d:
        claim_tier = "C"
    else:
        claim_tier = "D"

    decision = {
        "schema_version": "resetp.e2-final-campaign.p0-equal-compute-fuse.v1",
        "decision": f"P0_EQUAL_COMPUTE_FUSE_CLAIM_TIER_{claim_tier}",
        "tally_C_vs_A": tally_a,
        "tally_C_vs_B": tally_b,
        "tally_C_vs_D": tally_d,
        "claim_tier": claim_tier,
        "next_step": "proceed_to_P1_regardless_of_tier",
        "details": rows,
    }
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_executable": sys.executable,
        "cases": cases,
        "seeds": list(seeds),
        "sp_share": SP_SHARE,
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "attribution.json").write_text(json.dumps(attribution, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "report.md").write_text(
        "\n".join([
            "# P0 等算力四臂保险丝",
            "",
            f"C(MV-HGS-SP) vs A(单视角HGS)：{tally_a}",
            f"C vs B(多重启对照)：{tally_b}",
            f"C vs D(独立机制ALNS)：{tally_d}",
            "",
            f"预注册主张阶梯：`{claim_tier}` 级",
            "",
        ]),
        encoding="utf-8",
    )
    files = [Path(__file__), OUT / "metadata.json", OUT / "raw_runs.csv",
             OUT / "decision.json", OUT / "attribution.json", OUT / "report.md"]
    hashes = {}
    for f in files:
        digest = hashlib.sha256()
        with f.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        try:
            key = str(f.relative_to(ROOT))
        except ValueError:
            key = str(f)
        hashes[key] = digest.hexdigest()
    (OUT / "artifact_hashes.json").write_text(
        json.dumps({"algorithm": "sha256", "files": hashes}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
