#!/usr/bin/env python3
"""Same-start E3 wiring probe under the preregistered common fleet envelope."""

from __future__ import annotations

from dataclasses import asdict
import csv
import hashlib
import json
from pathlib import Path
import shutil
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
from setp_solver.algorithms.resetp_alns.kernel.winner import WinnerKernelConfig, run_tvci_alns
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.e3_multitrip_runtime import hard_violations, prepare_solution
from setp_solver.search.evaluation import EvaluationContext, cross_depot_violations


INSTANCE = "L-main-threeshift-100c-01"
ARM_BUDGET = 200
SEED = 1
OUT = ROOT / "baselines/e3_ablation/e3_same_start_wiring_probe_v2_20260713"
ENVELOPE_ROOT = ROOT / "baselines/e3_ablation/e3_common_fleet_envelope_design_v2_20260713"
OWNERSHIP_ROOT = ROOT / "baselines/e3_ablation/e3_ownership_class_design_v3_20260713"
SOURCE_BUNDLE = ROOT / "baselines/e3_ablation/e3_v11_clean_20260713/assets/100c/derived_bundles/zero_gamma"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def load_owners() -> tuple[dict[str, str], Path]:
    path = OWNERSHIP_ROOT / "ownership_maps" / f"{INSTANCE}__mixed.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        owners = {row["customer_id"]: row["owner_depot_id"] for row in csv.DictReader(handle)}
    return owners, path


def load_caps() -> dict[str, int]:
    with (ENVELOPE_ROOT / "fleet_envelopes.csv").open(newline="", encoding="utf-8") as handle:
        row = next(item for item in csv.DictReader(handle) if item["instance"] == INSTANCE)
    return {"cv": int(row["common_cap_cv"]), "ev": int(row["common_cap_ev"])}


def create_bundle(caps: dict[str, int]) -> Path:
    target = OUT / "bundle"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("instance.json", "distance_matrix.npy", "carbon_profile.csv", "scenario_manifest.json"):
        shutil.copyfile(SOURCE_BUNDLE / name, target / name)
    payload = json.loads((target / "instance.json").read_text(encoding="utf-8"))
    payload.setdefault("metadata", {}).update(
        {
            "num_cv": caps["cv"],
            "num_ev": caps["ev"],
            "e3_common_fleet_envelope_sha256": sha256(ENVELOPE_ROOT / "fleet_envelopes.csv"),
            "scenario_role": "ample_fleet_cost_mechanism_probe",
        }
    )
    write_json(target / "instance.json", payload)
    return target


def validate_start(payload: dict[str, Any], owners: dict[str, str], bundle_dir: Path) -> tuple[dict[str, Any], str]:
    solution = legacy.solution_from_dict(payload)
    solution = legacy.annotate_cross_site(solution, owners)
    bundle = load_search_bundle(bundle_dir)
    prices = legacy.prices_for("M1", 0.0)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        carbon_weight=0.0,
        fairness_enabled=False,
        customer_home_depot=owners,
        allow_cross_depot=False,
    )
    with legacy.strict_mode():
        prepared, certificate = prepare_solution(solution, context)
        violations = [*hard_violations(prepared, context), *cross_depot_violations(prepared, context)]
    if certificate is None or violations or prepared.cross_site_services:
        raise RuntimeError(f"common start failed: {violations}")
    clean_payload = legacy.solution_to_dict(prepared)
    start_hash = hashlib.sha256(canonical_bytes(clean_payload)).hexdigest()
    (OUT / "common_start.json").write_bytes(canonical_bytes(clean_payload))
    write_json(OUT / "common_start_certificate.json", certificate.as_dict())
    return clean_payload, start_hash


def run_arm(
    start_payload: dict[str, Any], start_hash: str, owners: dict[str, str], bundle_dir: Path,
    caps: dict[str, int], label: str, allow_cross: bool,
) -> dict[str, Any]:
    start = legacy.solution_from_dict(json.loads(canonical_bytes(start_payload)))
    observed_start_hash = hashlib.sha256(canonical_bytes(legacy.solution_to_dict(start))).hexdigest()
    bundle = load_search_bundle(bundle_dir)
    prices = legacy.prices_for("M1", 0.0)
    started = time.perf_counter()
    with legacy.strict_mode():
        result = run_tvci_alns(
            bundle_dir,
            config=WinnerKernelConfig(
                seed=SEED,
                eval_budget=ARM_BUDGET,
                max_runtime_seconds=300.0,
                require_charging_signal=False,
            ),
            initial_solution=start,
            prices=prices,
            charging_strategy="naive",
            policy=SearchPolicy(
                require_charging_signal=False,
                max_cv=caps["cv"],
                max_ev=caps["ev"],
                allow_cross_depot=allow_cross,
            ),
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
    with legacy.strict_mode():
        prepared, certificate = prepare_solution(best, context)
        violations = [*hard_violations(prepared, context), *cross_depot_violations(prepared, context)]
    if certificate is None:
        raise RuntimeError(f"{label} emitted no strict certificate")
    metrics, closure_error = legacy._metric_row(prepared, bundle, prices)
    counts = legacy.score_counts(result)
    row = {
        "arm": label,
        "allow_reassignment": allow_cross,
        "start_sha256": observed_start_hash,
        "expected_start_sha256": start_hash,
        "budget": ARM_BUDGET,
        "evaluations": int(result.get("evaluations", -1)),
        "elapsed_seconds": time.perf_counter() - started,
        "status": "PASS" if int(result.get("evaluations", -1)) == ARM_BUDGET and not violations else "HALT",
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


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    owners, ownership_path = load_owners()
    caps = load_caps()
    bundle_dir = create_bundle(caps)
    witness_path = ENVELOPE_ROOT / "witnesses" / f"{INSTANCE}__mixed__solution.json"
    witness_payload = json.loads(witness_path.read_text(encoding="utf-8"))

    metadata = {
        "schema": "setp.e3.same_start_wiring_probe.v2",
        "purpose": "mechanical wiring only; result direction is forbidden as paper evidence",
        "instance": INSTANCE,
        "ownership_condition": "spatially mixed customer portfolios",
        "ownership_sha256": sha256(ownership_path),
        "common_fleet_envelope_sha256": sha256(ENVELOPE_ROOT / "fleet_envelopes.csv"),
        "common_fleet_cap": caps,
        "common_start_witness_sha256": sha256(witness_path),
        "arm_budget": ARM_BUDGET,
        "seed": SEED,
        "fairness_enabled": False,
        "carbon_weight": 0.0,
        "carbon_price": 0.0,
        "cross_site_fee": 0.0,
        "source_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
        ).stdout.strip(),
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
        common_payload, common_hash = validate_start(witness_payload, owners, bundle_dir)
        arm_a = run_arm(common_payload, common_hash, owners, bundle_dir, caps, "ownership_fixed", False)
        arm_b = run_arm(common_payload, common_hash, owners, bundle_dir, caps, "reassignment_allowed", True)
        same_start = arm_a["start_sha256"] == arm_b["start_sha256"] == common_hash
        exact_budgets = arm_a["evaluations"] == arm_b["evaluations"] == ARM_BUDGET
        strict_clean = (
            arm_a["status"] == arm_b["status"] == "PASS"
            and arm_a["cost_component_error"] <= 1e-6
            and arm_b["cost_component_error"] <= 1e-6
            and arm_a["cross_site_customer_count"] == 0
        )
        cross_path = bool(
            arm_b["cross_site_complete_candidates"] > 0
            and arm_b["cross_site_legal_candidates"] > 0
        )
        passed = same_start and exact_budgets and strict_clean and cross_path
        decision = {
            "status": "PASS" if passed else "HALT",
            "same_start": same_start,
            "exact_budgets": exact_budgets,
            "strict_checks_clean": strict_clean,
            "cross_reassignment_path_exercised": cross_path,
            "common_start_sha256": common_hash,
            "ownership_fixed": arm_a,
            "reassignment_allowed": arm_b,
            "result_direction_is_not_a_gate": True,
            "next_step": (
                "freeze the formal paired protocol before broader execution"
                if passed
                else "stop without increasing the budget; repair only the failed mechanical gate"
            ),
        }
    except Exception as exc:
        decision = {
            "status": "HALT",
            "reason": f"{type(exc).__name__}: {exc}",
            "result_direction_is_not_a_gate": True,
            "next_step": "stop without increasing the budget; repair only the failed mechanical gate",
        }
    write_json(OUT / "decision.json", decision)

    rows = [decision[key] for key in ("ownership_fixed", "reassignment_allowed") if isinstance(decision.get(key), dict)]
    fields = [
        "arm", "allow_reassignment", "start_sha256", "expected_start_sha256", "budget", "evaluations",
        "elapsed_seconds", "status", "violation_count", "total_cost", "cost_component_error",
        "cross_site_customer_count", "cross_site_complete_candidates", "cross_site_legal_candidates",
        "cross_site_accepted_candidates", "physical_cv", "physical_ev", "physical_total", "trip_count",
        "vehicle_work_hours", "between_trip_gap_hours", "max_trips_per_vehicle",
    ]
    with (OUT / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    if decision["status"] == "PASS":
        a, b = decision["ownership_fixed"], decision["reassignment_allowed"]
        report = (
            "# 同起点接线检查\n\n"
            "判决：通过。这一步只证明比较接线完整，短跑结果不能作为论文效果数字。\n\n"
            f"两边从同一份起步方案出发，文件指纹为 `{decision['common_start_sha256']}`，各完成 {ARM_BUDGET} 次尝试。"
            f"固定客户归属的一边没有跨车场客户；允许重新分配的一边形成 {b['cross_site_complete_candidates']} 个完整候选，"
            f"其中 {b['cross_site_legal_candidates']} 个通过全部硬性检查。\n\n"
            f"短跑成本方向为 {a['total_cost']:.6f} 对 {b['total_cost']:.6f}。这个方向不参与通过判定，也不得写进正文。\n"
        )
    else:
        report = (
            "# 同起点接线检查\n\n"
            f"判决：停止。{decision.get('reason', '至少一项机械检查未通过。')}\n\n"
            "没有启动正式批次，也不从短跑推断合作是否有效。\n"
        )
    (OUT / "report.md").write_text(report, encoding="utf-8")
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
