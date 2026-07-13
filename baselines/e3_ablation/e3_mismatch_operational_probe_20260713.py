#!/usr/bin/env python3
"""Cheap operational-only probe after the 25% mismatch structural stop."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e3_ablation import e3_v3_runner as legacy
from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy
from setp_solver.algorithms.resetp_alns.kernel.winner import WinnerKernelConfig, run_tvci_alns
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.e3_multitrip_runtime import hard_violations, prepare_solution
from setp_solver.search.evaluation import EvaluationContext, cross_depot_violations

V11 = ROOT / "baselines/e3_ablation/e3_v11_clean_20260713"
OUT = ROOT / "baselines/e3_ablation/e3_mismatch_probe_20260713"
ZERO_BUNDLE = V11 / "assets/200c/derived_bundles/zero_gamma"
OWNER_FILE = OUT / "ownership_25.csv"
INSTANCE = "L-main-threeshift-200c-01"
CAPS = {"D0": {"cv": 7, "ev": 7}, "D1": {"cv": 7, "ev": 7}}


def owners() -> dict[str, str]:
    with OWNER_FILE.open(newline="", encoding="utf-8") as handle:
        return {row["customer_id"]: row["home_depot_id"] for row in csv.DictReader(handle)}


def main() -> int:
    owner_map = owners()
    bundle = load_search_bundle(ZERO_BUNDLE)
    prices = legacy.prices_for("M1", 0.0)
    start = legacy.solution_from_dict(json.loads((V11 / "assets/200c/shared_start.json").read_text(encoding="utf-8")))
    context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices, carbon_weight=0.0, customer_home_depot=owner_map, allow_cross_depot=True)
    started = time.perf_counter()
    with legacy.strict_mode(CAPS):
        result = run_tvci_alns(
            ZERO_BUNDLE,
            config=WinnerKernelConfig(seed=1, eval_budget=200, max_runtime_seconds=600.0),
            initial_solution=start,
            prices=prices,
            policy=SearchPolicy(max_cv=14, max_ev=14, allow_cross_depot=True),
            carbon_weight=0.0,
            fairness_enabled=False,
            customer_home_depot=owner_map,
        )
    with legacy.strict_mode(CAPS):
        prepared, certificate = prepare_solution(result["best_solution"], context)
        violations = [*hard_violations(prepared, context), *cross_depot_violations(prepared, context)]
    counts = legacy.score_counts(result)
    row = {
        "status": "OK" if int(result.get("evaluations", -1)) == 200 and not violations else "HALT_CONTRACT",
        "actual_evals": int(result.get("evaluations", -1)),
        "elapsed_seconds": time.perf_counter() - started,
        "total_cost": float(legacy._metric_row(prepared, bundle, prices)[0]["total_cost"]),
        "cross_site_customer_count": len(prepared.cross_site_services),
        "cross_site_attempted_candidates": int(counts.get("cross_site_complete_candidates", 0)),
        "cross_site_legal_candidates": int(counts.get("cross_site_legal_candidates", 0)),
        "cross_site_accepted_candidates": int(counts.get("cross_site_accepted_candidates", 0)),
        "physical_total": certificate.vehicle_counts["cv"] + certificate.vehicle_counts["ev"] if certificate else None,
        "reason": "; ".join(str(item) for item in violations),
        "fairness_enabled": False,
        "start_source": "frozen v11 shared structural start",
    }
    (OUT / "operational_probe.json").write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "operational_probe_report.md").write_text(
        "# 25%错配无公平操作探针\n\n"
        "这不是正式证据，只判断错配后跨场搜索能否动起来。\n\n"
        f"状态：{row['status']}；跨场尝试 {row['cross_site_attempted_candidates']}，合法 {row['cross_site_legal_candidates']}，采纳 {row['cross_site_accepted_candidates']}，最终跨场客户 {row['cross_site_customer_count']}。\n",
        encoding="utf-8",
    )
    print(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if row["status"] == "OK" else 2


if __name__ == "__main__":
    raise SystemExit(main())
