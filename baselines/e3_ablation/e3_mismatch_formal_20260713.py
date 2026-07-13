#!/usr/bin/env python3
"""Pre-registered E3 ownership-mismatch formal run.

This runner is deliberately small: one frozen ownership map, ten search seeds,
and the already-gated 4,000-evaluation cooperation arm.  Independent operation
is recorded first under the original asset cap; when that cannot close, a
measurement-only start records the extra vehicles required.  The measurement
start is a reference, never a replacement for the sealed 14+14 fleet.
"""

from __future__ import annotations

import csv
from math import comb
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e3_ablation import e3_mismatch_fair_probe_20260713 as probe
from baselines.e3_ablation import e3_v3_runner as legacy
from baselines.e3_ablation.e3_mismatch_probe_20260713 import owners_from_frozen, write_owner_map

V11 = ROOT / "baselines/e3_ablation/e3_v11_clean_20260713"
OUT_BASE = ROOT / "baselines/e3_ablation"
SEEDS = tuple(range(1, 11))
M0_BUDGET = 200
COOP_BUDGET = 4000
ORIGINAL_CAPS = {"D0": {"cv": 7, "ev": 7}, "D1": {"cv": 7, "ev": 7}}


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exact_two_sided_sign_p(values: list[float]) -> float:
    nonzero = [value for value in values if abs(value) > 1e-12]
    if not nonzero:
        return 1.0
    positive = sum(value > 0 for value in nonzero)
    negative = len(nonzero) - positive
    n = len(nonzero)
    tail = sum(comb(n, k) for k in range(max(positive, negative), n + 1)) / (2 ** n)
    return min(1.0, 2.0 * tail)


def asset_status(caps: dict[str, dict[str, int]]) -> dict[str, str]:
    rows: dict[str, str] = {}
    for depot, values in caps.items():
        rows[depot] = "ASSET_INFEASIBLE" if any(
            int(values[key]) > int(ORIGINAL_CAPS[depot][key]) for key in ("cv", "ev")
        ) else "WITHIN_ASSET"
    return rows


def run_level(share: float, map_seed: int, output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    base = owners_from_frozen()
    owners = probe.generate_owners_at_share(base, share, map_seed)
    percentage = int(share * 100)
    write_owner_map(output / f"ownership_{percentage}.csv", owners, base)
    write_json(output / "ownership_generator.json", {
        "schema": "setp.e3.synthetic_ownership.v1",
        "instance": "L-main-threeshift-200c-01",
        "share": share,
        "map_seed": map_seed,
        "selection": "sorted customers, equal reciprocal swaps, fixed before all searches, no result-based selection",
        "moved_count": sum(owners[c] != base[c] for c in owners),
        "base_owner_rows_sha256": sha256(legacy.OWNER_ROWS),
    })

    # Keep the imported probe's model contract unchanged; only its output root,
    # per-seed random seed, and explicitly gated budgets vary here.
    probe.M0_BUDGET = M0_BUDGET
    rows: list[dict[str, object]] = []
    started_level = time.perf_counter()
    for seed in SEEDS:
        seed_root = output / f"seed{seed}"
        seed_root.mkdir(parents=True, exist_ok=True)
        start, measurement_caps = probe.build_measurement_start(
            owners,
            search_seed=seed,
            out_root=seed_root,
        )
        coop = probe.run_cooperation(
            start,
            owners,
            search_seed=seed,
            out_root=seed_root,
            budget=COOP_BUDGET,
        )
        status_by_depot = asset_status(measurement_caps)
        saving = float(coop["saving_pct_vs_measurement_start"])
        strict_win = bool(
            coop["status"] == "OK"
            and saving > 0.0
            and int(coop["cross_site_customer_count"]) > 0
        )
        row = {
            "run_id": f"E3b_mismatch_{percentage}pct_seed{seed}",
            "share": share,
            "seed": seed,
            "map_seed": map_seed,
            "m0_budget_per_depot": M0_BUDGET,
            "cooperation_budget": COOP_BUDGET,
            "measurement_caps": measurement_caps,
            "asset_status_by_depot": status_by_depot,
            "asset_infeasible_any": any(value == "ASSET_INFEASIBLE" for value in status_by_depot.values()),
            "strict_win": strict_win,
            **coop,
        }
        write_json(seed_root / "run_summary.json", row)
        rows.append(row)
        print(json.dumps({"share": share, "seed": seed, "strict_win": strict_win, "saving_pct": saving, "cross_customers": coop["cross_site_customer_count"], "status": coop["status"]}, ensure_ascii=False, sort_keys=True), flush=True)

    # A flat CSV is the audit surface; nested details remain in each run JSON.
    flat_fields = [
        "run_id", "share", "seed", "map_seed", "m0_budget_per_depot", "cooperation_budget",
        "asset_infeasible_any", "strict_win", "status", "actual_evals", "elapsed_seconds",
        "independent_cost", "total_cost", "saving_pct_vs_measurement_start",
        "cross_site_service_count", "cross_site_customer_count", "cross_site_attempted_candidates",
        "cross_site_legal_candidates", "cross_site_accepted_candidates", "fairness_rejected_candidates",
        "physical_total", "fairness_ok", "measurement_caps", "asset_status_by_depot",
    ]
    with (output / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=flat_fields)
        writer.writeheader()
        for row in rows:
            flat = {key: row.get(key, "") for key in flat_fields}
            for key in ("measurement_caps", "asset_status_by_depot"):
                flat[key] = json.dumps(flat[key], ensure_ascii=False, sort_keys=True)
            writer.writerow(flat)

    savings = [float(row["saving_pct_vs_measurement_start"]) for row in rows if row["status"] == "OK"]
    strict_wins = sum(bool(row["strict_win"]) for row in rows)
    exact_p = exact_two_sided_sign_p(savings)
    vehicle_rows = [
        {
            "seed": row["seed"],
            "measurement_caps": row["measurement_caps"],
            "asset_status_by_depot": row["asset_status_by_depot"],
            "cooperation_physical_total": row["physical_total"],
        }
        for row in rows
    ]
    decision = {
        "schema": "setp.e3.mismatch_formal.decision.v1",
        "status": "PASS" if all(row["status"] == "OK" for row in rows) else "HALT_CONTRACT",
        "share": share,
        "map_seed": map_seed,
        "seeds": list(SEEDS),
        "m0_budget_per_depot": M0_BUDGET,
        "cooperation_budget": COOP_BUDGET,
        "strict_wins": strict_wins,
        "n": len(rows),
        "mean_saving_pct": sum(savings) / len(savings) if savings else None,
        "min_saving_pct": min(savings) if savings else None,
        "max_saving_pct": max(savings) if savings else None,
        "exact_two_sided_sign_p": exact_p,
        "vehicle_rows": vehicle_rows,
        "pre_registered_ideal_rule": "strict wins >= 6/10 and exact two-sided sign p < 0.05",
        "ideal_rule_met": bool(strict_wins >= 6 and exact_p < 0.05),
        "comparison_boundary": "收益节省相对各自经营的测量起点；测量车数不是正式新增资产，合作始终锁定原始14+14",
        "elapsed_seconds": time.perf_counter() - started_level,
    }
    if decision["status"] != "PASS":
        decision["verdict"] = "HALT_E3_MISMATCH_FORMAL_CONTRACT"
    elif decision["ideal_rule_met"]:
        decision["verdict"] = "E3_MISMATCH_FORMAL_IDEAL"
    else:
        decision["verdict"] = "E3_MISMATCH_FORMAL_INTERMEDIATE"
    write_json(output / "metadata.json", {
        "schema": "setp.e3.mismatch_formal.metadata.v1",
        "experiment": "E3b ownership mismatch axis",
        "instance": "L-main-threeshift-200c-01",
        "share": share,
        "map_seed": map_seed,
        "seeds": list(SEEDS),
        "m0_budget_per_depot": M0_BUDGET,
        "cooperation_budget": COOP_BUDGET,
        "source": "v11 sealed assets; additive output only",
        "operator_contract": "default TVCI-ALNS kernel; no new operator",
    })
    write_json(output / "decision.json", decision)
    lines = [
        f"# {percentage}%客户归属错配正式批次",
        "",
        "这批是预先锁死的十个搜索种子，不是为了挑好看的结果。客户归属表只生成一次，所有种子共用。",
        "",
        f"十个种子中，合作相对各自经营测量起点严格胜出 {strict_wins}/10；平均节省 {decision['mean_saving_pct']:.3f}%；精确符号检验概率 {exact_p:.6g}。",
        f"节省范围 {decision['min_saving_pct']:.3f}% 到 {decision['max_saving_pct']:.3f}%；正式理想规则：胜出至少6/10且概率小于0.05，结果为 `{decision['verdict']}`。",
        "",
        "车辆口径：合作臂始终只用原始14辆油车+14辆电车；各自经营若超过本车场7+7，只记录为资产内不可行，并把实际需要的车数作为测量值。",
        "这不是对所有算例的普遍保证，只是同一200客户算例、固定错配表下的条件性证据；旧v11与E2封存文件不改。",
        "",
        "逐种子证据见 `raw_runs.csv` 与各 `seed*/run_summary.json`；成本七项见各运行的合作/独立成本分项字段。",
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    hashes = {
        str(path.relative_to(output)): sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    write_json(output / "artifact_hashes.json", hashes)
    return 0 if decision["status"] == "PASS" else 2


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--share", type=float, choices=(0.25, 0.5), required=True)
    parser.add_argument("--map-seed", type=int, default=20260713)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    return run_level(args.share, args.map_seed, output)


if __name__ == "__main__":
    raise SystemExit(main())
