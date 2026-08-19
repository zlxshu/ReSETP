#!/usr/bin/env python3
"""One cheap E3 wiring probe; never makes a paper-effect claim.

The probe uses one preregistered medium network and the frozen spatially
mixed ownership map.  It first builds one independent incumbent with a total
200-evaluation budget.  Two 200-evaluation arms then start from byte-identical
copies of that incumbent.  The only intended difference is whether a customer
may be reassigned across depots.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e3_ablation import e3_v3_runner as legacy
from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy
from setp_solver.algorithms.resetp_alns.kernel.winner import (
    WinnerKernelConfig,
    run_staged_alns_lns_hybrid,
    run_tvci_alns,
)
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.e3_multitrip_runtime import hard_violations, prepare_solution
from setp_solver.search.evaluation import EvaluationContext, cross_depot_violations
from baselines.e3_ablation._legacy_subbundle import (
    _subinstance_for_depot,
    _write_subbundle,
)
from setp_solver.solution import ChargingAction, Route, Solution


INSTANCE = "L-main-threeshift-100c-01"
OUT = ROOT / "baselines/e3_ablation/e3_same_start_wiring_probe_20260713"
OWNERSHIP = (
    ROOT
    / "baselines/e3_ablation/e3_ownership_class_design_v3_20260713"
    / "ownership_maps"
    / f"{INSTANCE}__mixed.csv"
)
ASSET_MANIFEST = ROOT / "baselines/e3_ablation/e3_v11_clean_20260713/assets/100c/asset_manifest.json"
TOTAL_INDEPENDENT_BUDGET = 200
ARM_BUDGET = 200
SEED = 1


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def canonical_solution_bytes(solution: Solution) -> bytes:
    return (
        json.dumps(legacy.solution_to_dict(solution), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def solution_fingerprint(solution: Solution) -> str:
    return hashlib.sha256(canonical_solution_bytes(solution)).hexdigest()


def load_owners() -> dict[str, str]:
    with OWNERSHIP.open(newline="", encoding="utf-8") as handle:
        return {row["customer_id"]: row["owner_depot_id"] for row in csv.DictReader(handle)}


def prefixed_solution(solution: Solution, depot: str) -> Solution:
    mapping = {route.vehicle_id: f"{depot}_{route.vehicle_id}" for route in solution.routes}
    return Solution(
        routes=[replace(route, vehicle_id=mapping[route.vehicle_id]) for route in solution.routes],
        charging_actions=[
            replace(action, vehicle_id=mapping.get(action.vehicle_id, f"{depot}_{action.vehicle_id}"))
            for action in solution.charging_actions
        ],
    )


def create_subbundles(owners: dict[str, str], source_bundle: Path, caps: dict[str, dict[str, int]]) -> None:
    source = load_search_bundle(source_bundle)
    for depot, local_caps in sorted(caps.items()):
        instance = replace(
            _subinstance_for_depot(source.instance, depot, owners),
            num_cv=int(local_caps["cv"]),
            num_ev=int(local_caps["ev"]),
        )
        target = OUT / "subbundles" / depot
        _write_subbundle(target, instance, source_bundle, depot)
        payload = json.loads((target / "instance.json").read_text(encoding="utf-8"))
        payload.setdefault("metadata", {}).update(
            {
                "num_cv": int(local_caps["cv"]),
                "num_ev": int(local_caps["ev"]),
                "ownership_sha256": sha256(OWNERSHIP),
                "probe_only": True,
            }
        )
        write_json(target / "instance.json", payload)


def build_independent_start(
    owners: dict[str, str], source_bundle: Path, caps: dict[str, dict[str, int]]
) -> tuple[Solution, dict[str, Any]]:
    prices = legacy.prices_for("M1", 0.0)
    merged_routes: list[Route] = []
    merged_actions: list[ChargingAction] = []
    rows: dict[str, Any] = {}
    depots = sorted(caps)
    used = 0
    for index, depot in enumerate(depots):
        budget = TOTAL_INDEPENDENT_BUDGET // len(depots)
        if index == len(depots) - 1:
            budget = TOTAL_INDEPENDENT_BUDGET - used
        bundle_dir = OUT / "subbundles" / depot
        bundle = load_search_bundle(bundle_dir)
        routes = legacy._short_trips(bundle.instance, independent=True, prices=prices)
        routes = legacy._assign_types_within_assets(
            routes,
            bundle.instance,
            prices,
            {depot: caps[depot]},
        )
        initial = Solution(routes=routes)
        started = time.perf_counter()
        with legacy.strict_mode({depot: caps[depot]}):
            result = run_staged_alns_lns_hybrid(
                bundle_dir,
                config=WinnerKernelConfig(
                    seed=SEED * 100 + index,
                    eval_budget=budget,
                    max_runtime_seconds=300.0,
                    require_charging_signal=False,
                ),
                initial_solution=initial,
                prices=prices,
                policy=SearchPolicy(
                    require_charging_signal=False,
                    max_cv=int(caps[depot]["cv"]),
                    max_ev=int(caps[depot]["ev"]),
                    allow_cross_depot=False,
                ),
                carbon_weight=0.0,
            )
        if not result.get("feasible") or int(result.get("evaluations", -1)) != budget:
            raise RuntimeError(
                f"independent start failed at {depot}: feasible={result.get('feasible')}, "
                f"evaluations={result.get('evaluations')}/{budget}"
            )
        found = prefixed_solution(result["best_solution"], depot)
        merged_routes.extend(found.routes)
        merged_actions.extend(found.charging_actions)
        used += int(result["evaluations"])
        rows[depot] = {
            "budget": budget,
            "evaluations": int(result["evaluations"]),
            "elapsed_seconds": time.perf_counter() - started,
            "route_count": len(found.routes),
            "best_cost": float(result["best_cost"]),
        }

    full = load_search_bundle(source_bundle)
    merged = Solution(routes=merged_routes, charging_actions=merged_actions)
    context = EvaluationContext(
        full.instance,
        full.carbon_profile,
        prices=prices,
        carbon_weight=0.0,
        customer_home_depot=owners,
        allow_cross_depot=False,
    )
    with legacy.strict_mode(caps):
        prepared, certificate = prepare_solution(merged, context)
        violations = [*hard_violations(prepared, context), *cross_depot_violations(prepared, context)]
    if certificate is None or violations:
        raise RuntimeError(f"merged independent start failed strict checks: {violations}")
    metrics, closure_error = legacy._metric_row(prepared, full, prices)
    rows["merged"] = {
        "evaluations": used,
        "total_cost": float(metrics["total_cost"]),
        "cost_component_error": float(closure_error),
        **legacy._certificate_stats(certificate),
    }
    (OUT / "common_start.json").write_bytes(canonical_solution_bytes(prepared))
    write_json(OUT / "common_start_certificate.json", certificate.as_dict())
    write_json(OUT / "independent_subruns.json", rows)
    return prepared, rows


def run_arm(
    common_start_payload: dict[str, Any],
    owners: dict[str, str],
    source_bundle: Path,
    caps: dict[str, dict[str, int]],
    *,
    label: str,
    allow_cross: bool,
) -> dict[str, Any]:
    start = legacy.solution_from_dict(common_start_payload)
    start_hash = solution_fingerprint(start)
    bundle = load_search_bundle(source_bundle)
    prices = legacy.prices_for("M1", 0.0)
    policy = SearchPolicy(
        require_charging_signal=False,
        max_cv=sum(int(item["cv"]) for item in caps.values()),
        max_ev=sum(int(item["ev"]) for item in caps.values()),
        allow_cross_depot=allow_cross,
    )
    started = time.perf_counter()
    with legacy.strict_mode(caps):
        result = run_tvci_alns(
            source_bundle,
            config=WinnerKernelConfig(
                seed=SEED,
                eval_budget=ARM_BUDGET,
                max_runtime_seconds=300.0,
                require_charging_signal=False,
            ),
            initial_solution=start,
            prices=prices,
            charging_strategy="naive",
            policy=policy,
            carbon_weight=0.0,
            fairness_enabled=False,
            customer_home_depot=owners,
        )
    best = legacy.annotate_cross_site(result["best_solution"], owners)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        carbon_weight=0.0,
        fairness_enabled=False,
        customer_home_depot=owners,
        allow_cross_depot=allow_cross,
    )
    with legacy.strict_mode(caps):
        prepared, certificate = prepare_solution(best, context)
        violations = [*hard_violations(prepared, context), *cross_depot_violations(prepared, context)]
    if certificate is None:
        raise RuntimeError(f"{label} returned no strict vehicle certificate")
    metrics, closure_error = legacy._metric_row(prepared, bundle, prices)
    counts = legacy.score_counts(result)
    status = "PASS" if int(result.get("evaluations", -1)) == ARM_BUDGET and not violations else "HALT"
    row = {
        "arm": label,
        "allow_cross_depot": allow_cross,
        "status": status,
        "start_sha256": start_hash,
        "budget": ARM_BUDGET,
        "evaluations": int(result.get("evaluations", -1)),
        "elapsed_seconds": time.perf_counter() - started,
        "violation_count": len(violations),
        "violations": [asdict(item) if hasattr(item, "__dataclass_fields__") else str(item) for item in violations],
        "total_cost": float(metrics["total_cost"]),
        "cost_component_error": float(closure_error),
        "cross_site_customer_count": len(prepared.cross_site_services),
        "cross_site_complete_candidates": int(counts.get("cross_site_complete_candidates", 0)),
        "cross_site_legal_candidates": int(counts.get("cross_site_legal_candidates", 0)),
        "cross_site_accepted_candidates": int(counts.get("cross_site_accepted_candidates", 0)),
        **legacy._certificate_stats(certificate),
    }
    write_json(OUT / f"{label}.json", row)
    write_json(OUT / f"{label}_solution.json", legacy.solution_to_dict(prepared))
    write_json(OUT / f"{label}_certificate.json", certificate.as_dict())
    return row


def git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(ASSET_MANIFEST.read_text(encoding="utf-8"))
    caps = {depot: {kind: int(value) for kind, value in item.items()} for depot, item in manifest["base_caps"].items()}
    source_bundle = ROOT / manifest["derived_bundles"]["zero_gamma"]
    owners = load_owners()
    create_subbundles(owners, source_bundle, caps)

    metadata = {
        "schema": "setp.e3.same_start_wiring_probe.v1",
        "purpose": "mechanical wiring check only; forbidden as a paper effect estimate",
        "instance": INSTANCE,
        "ownership_condition": "spatially mixed customer portfolios",
        "ownership_sha256": sha256(OWNERSHIP),
        "asset_manifest_sha256": sha256(ASSET_MANIFEST),
        "source_bundle": str(source_bundle.relative_to(ROOT)),
        "fixed_depot_assets": caps,
        "independent_total_budget": TOTAL_INDEPENDENT_BUDGET,
        "arm_budget": ARM_BUDGET,
        "seed": SEED,
        "fairness_enabled": False,
        "carbon_weight": 0.0,
        "carbon_price": 0.0,
        "cross_site_fee": 0.0,
        "source_commit": git_head(),
        "source_hashes": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in (
                Path(__file__).resolve(),
                ROOT / "baselines/e3_ablation/e3_v3_runner.py",
                ROOT / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
                ROOT / "solver/src/setp_solver/search/e3_multitrip_runtime.py",
                ROOT / "solver/src/setp_solver/search/multitrip_schedule.py",
            )
        },
    }
    write_json(OUT / "metadata.json", metadata)

    try:
        common_start, subruns = build_independent_start(owners, source_bundle, caps)
        common_payload = legacy.solution_to_dict(common_start)
        common_hash = solution_fingerprint(common_start)
        arm_a = run_arm(common_payload, owners, source_bundle, caps, label="no_reassignment", allow_cross=False)
        arm_b = run_arm(common_payload, owners, source_bundle, caps, label="reassignment_allowed", allow_cross=True)
        same_start = arm_a["start_sha256"] == arm_b["start_sha256"] == common_hash
        exact_budgets = (
            subruns["merged"]["evaluations"] == TOTAL_INDEPENDENT_BUDGET
            and arm_a["evaluations"] == arm_b["evaluations"] == ARM_BUDGET
        )
        clean_checks = (
            arm_a["status"] == arm_b["status"] == "PASS"
            and arm_a["cost_component_error"] <= 1e-6
            and arm_b["cost_component_error"] <= 1e-6
            and arm_a["cross_site_customer_count"] == 0
        )
        cross_path_exercised = bool(
            arm_b["cross_site_complete_candidates"] > 0
            and arm_b["cross_site_legal_candidates"] > 0
        )
        passed = bool(same_start and exact_budgets and clean_checks and cross_path_exercised)
        decision = {
            "status": "PASS" if passed else "HALT",
            "same_start": same_start,
            "exact_budgets": exact_budgets,
            "strict_checks_clean": clean_checks,
            "cross_reassignment_path_exercised": cross_path_exercised,
            "common_start_sha256": common_hash,
            "no_reassignment": arm_a,
            "reassignment_allowed": arm_b,
            "result_direction_is_not_a_gate": True,
            "next_step": (
                "write the formal paired protocol before any full run"
                if passed
                else "stop; diagnose the failed mechanical gate without increasing the budget"
            ),
        }
    except Exception as exc:
        decision = {
            "status": "HALT",
            "reason": f"{type(exc).__name__}: {exc}",
            "result_direction_is_not_a_gate": True,
            "next_step": "stop; diagnose the failed mechanical gate without increasing the budget",
        }
    write_json(OUT / "decision.json", decision)

    if decision["status"] == "PASS":
        a = decision["no_reassignment"]
        b = decision["reassignment_allowed"]
        report = (
            "# 同起点接线检查\n\n"
            "判决：通过。这一步只证明比较接线是干净的，不能作为论文中的效果数字。\n\n"
            f"两种运行都从同一个文件出发，起点指纹为 `{decision['common_start_sha256']}`；"
            f"两边各完成 {ARM_BUDGET} 次尝试。关闭客户改派时没有跨车场客户；"
            f"允许改派时，搜索形成了 {b['cross_site_complete_candidates']} 个完整跨车场候选，"
            f"其中 {b['cross_site_legal_candidates']} 个通过全部硬性检查。\n\n"
            f"本次短跑的成本方向是 {a['total_cost']:.6f} 对 {b['total_cost']:.6f}。"
            "这个方向不参与通过判定，也不得写成效果结论。\n"
        )
    else:
        report = (
            "# 同起点接线检查\n\n"
            f"判决：停止。{decision.get('reason', '至少一项机械检查未通过。')}\n\n"
            "没有启动正式运行，也不从本次结果推断合作是否有效。\n"
        )
    (OUT / "report.md").write_text(report, encoding="utf-8")

    raw_fields = [
        "arm", "allow_cross_depot", "start_sha256", "budget", "evaluations", "elapsed_seconds",
        "status", "violation_count", "total_cost", "cost_component_error", "cross_site_customer_count",
        "cross_site_complete_candidates", "cross_site_legal_candidates", "cross_site_accepted_candidates",
        "physical_cv", "physical_ev", "physical_total", "trip_count", "vehicle_work_hours",
        "between_trip_gap_hours", "max_trips_per_vehicle",
    ]
    with (OUT / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=raw_fields, extrasaction="ignore")
        writer.writeheader()
        for key in ("no_reassignment", "reassignment_allowed"):
            if isinstance(decision.get(key), dict):
                writer.writerow(decision[key])

    hashes = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    write_json(OUT / "artifact_hashes.json", hashes)
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if decision["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
