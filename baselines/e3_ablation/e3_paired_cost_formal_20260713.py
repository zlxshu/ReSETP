#!/usr/bin/env python3
"""Formal same-start E3 comparison across paired customer-portfolio classes."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from dataclasses import asdict
import hashlib
import json
import math
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
from setp_solver.search.instance_registry import instance_abs_dir


OUT = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713"
OWNERSHIP_ROOT = ROOT / "baselines/e3_ablation/e3_ownership_class_design_v4_20260713"
ENVELOPE_ROOT = ROOT / "baselines/e3_ablation/e3_common_fleet_envelope_design_v3_20260713"
CONDITIONS = ("geographic", "mixed")
SEEDS = (1, 2, 3)
ARM_BUDGET = 4000
ARMS = (("ownership_fixed", False), ("reassignment_allowed", True))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def load_envelopes() -> list[dict[str, Any]]:
    with (ENVELOPE_ROOT / "fleet_envelopes.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [
        {
            **row,
            "source_scale": int(row["source_scale"]),
            "source_num_cv": int(row["source_num_cv"]),
            "source_num_ev": int(row["source_num_ev"]),
            "common_cap_cv": int(row["common_cap_cv"]),
            "common_cap_ev": int(row["common_cap_ev"]),
        }
        for row in rows
    ]


def load_customer_counts() -> dict[str, int]:
    with (OWNERSHIP_ROOT / "raw_runs.csv").open(newline="", encoding="utf-8") as handle:
        return {row["instance"]: int(row["customer_count"]) for row in csv.DictReader(handle)}


def load_owners(instance: str, condition: str) -> tuple[dict[str, str], Path]:
    path = OWNERSHIP_ROOT / "ownership_maps" / f"{instance}__{condition}.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        owners = {row["customer_id"]: row["owner_depot_id"] for row in csv.DictReader(handle)}
    return owners, path


def prepare_bundle(row: dict[str, Any]) -> Path:
    instance = row["instance"]
    source = instance_abs_dir(ROOT, instance)
    target = OUT / "assets" / instance / "bundle"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("instance.json", "distance_matrix.npy", "carbon_profile.csv", "scenario_manifest.json"):
        shutil.copyfile(source / name, target / name)
    payload = json.loads((target / "instance.json").read_text(encoding="utf-8"))
    payload.setdefault("metadata", {}).update(
        {
            "num_cv": row["common_cap_cv"],
            "num_ev": row["common_cap_ev"],
            "scenario_role": "ample_fleet_customer_sharing_cost_mechanism",
            "source_instance_num_cv": row["source_num_cv"],
            "source_instance_num_ev": row["source_num_ev"],
            "common_fleet_envelope_sha256": sha256(ENVELOPE_ROOT / "fleet_envelopes.csv"),
        }
    )
    write_json(target / "instance.json", payload)
    return target


def validate_start(
    instance: str, condition: str, owners: dict[str, str], bundle_dir: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    witness_path = ENVELOPE_ROOT / "witnesses" / f"{instance}__{condition}__solution.json"
    solution = legacy.solution_from_dict(json.loads(witness_path.read_text(encoding="utf-8")))
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
        raise RuntimeError(f"start {instance}/{condition} failed: {violations}")
    payload = legacy.solution_to_dict(prepared)
    metrics, closure_error = legacy._metric_row(prepared, bundle, prices)
    return payload, {
        "witness_path": str(witness_path.relative_to(ROOT)),
        "witness_sha256": sha256(witness_path),
        "start_sha256": hashlib.sha256(canonical_bytes(payload)).hexdigest(),
        "cost_component_error": float(closure_error),
        **legacy._certificate_stats(certificate),
        **metrics,
    }


def preflight_assets(envelopes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in envelopes:
        bundle_dir = prepare_bundle(item)
        for condition in CONDITIONS:
            owners, owner_path = load_owners(item["instance"], condition)
            start, start_meta = validate_start(item["instance"], condition, owners, bundle_dir)
            start_path = OUT / "assets" / item["instance"] / f"{condition}__common_start.json"
            start_path.write_bytes(canonical_bytes(start))
            write_json(
                OUT / "assets" / item["instance"] / f"{condition}__common_start_meta.json",
                {
                    **start_meta,
                    "ownership_map": str(owner_path.relative_to(ROOT)),
                    "ownership_sha256": sha256(owner_path),
                    "bundle_dir": str(bundle_dir.relative_to(ROOT)),
                    "bundle_instance_sha256": sha256(bundle_dir / "instance.json"),
                },
            )
            rows.append(
                {
                    "instance": item["instance"],
                    "condition": condition,
                    "status": "PASS",
                    "start_sha256": start_meta["start_sha256"],
                    "physical_cv": start_meta["physical_cv"],
                    "physical_ev": start_meta["physical_ev"],
                    "trip_count": start_meta["trip_count"],
                    "total_cost": start_meta["total_cost"],
                    "cost_component_error": start_meta["cost_component_error"],
                }
            )
    with (OUT / "start_preflight.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def run_arm(
    instance: str,
    condition: str,
    seed: int,
    label: str,
    allow_cross: bool,
    contract_sha256: str,
) -> dict[str, Any]:
    bundle_dir = OUT / "assets" / instance / "bundle"
    bundle = load_search_bundle(bundle_dir)
    owners, owner_path = load_owners(instance, condition)
    start_path = OUT / "assets" / instance / f"{condition}__common_start.json"
    start_payload = json.loads(start_path.read_text(encoding="utf-8"))
    start = legacy.solution_from_dict(json.loads(canonical_bytes(start_payload)))
    start_hash = hashlib.sha256(canonical_bytes(legacy.solution_to_dict(start))).hexdigest()
    prices = legacy.prices_for("M1", 0.0)
    started = time.perf_counter()
    with legacy.strict_mode():
        result = run_tvci_alns(
            bundle_dir,
            config=WinnerKernelConfig(
                seed=seed,
                eval_budget=ARM_BUDGET,
                max_runtime_seconds=max(600.0, ARM_BUDGET * 0.5),
                require_charging_signal=False,
            ),
            initial_solution=start,
            prices=prices,
            charging_strategy="naive",
            policy=SearchPolicy(
                require_charging_signal=False,
                max_cv=int(bundle.instance.num_cv or 0),
                max_ev=int(bundle.instance.num_ev or 0),
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
        raise RuntimeError(f"{instance}/{condition}/seed{seed}/{label} emitted no certificate")
    metrics, closure_error = legacy._metric_row(prepared, bundle, prices)
    counts = legacy.score_counts(result)
    run_id = f"{instance}__{condition}__seed{seed}__{label}"
    solution_path = OUT / "solutions" / f"{run_id}.json"
    certificate_path = OUT / "certificates" / f"{run_id}.json"
    write_json(solution_path, legacy.solution_to_dict(prepared))
    write_json(certificate_path, certificate.as_dict())
    return {
        "run_id": run_id,
        "instance": instance,
        "condition": condition,
        "seed": seed,
        "arm": label,
        "allow_reassignment": allow_cross,
        "contract_sha256": contract_sha256,
        "ownership_sha256": sha256(owner_path),
        "start_sha256": start_hash,
        "budget": ARM_BUDGET,
        "evaluations": int(result.get("evaluations", -1)),
        "elapsed_seconds": time.perf_counter() - started,
        "status": "PASS" if int(result.get("evaluations", -1)) == ARM_BUDGET and not violations else "HALT",
        "violation_count": len(violations),
        "violations_json": json.dumps(
            [asdict(item) if hasattr(item, "__dataclass_fields__") else str(item) for item in violations],
            ensure_ascii=False,
            sort_keys=True,
        ),
        "cost_component_error": float(closure_error),
        "cross_site_customer_count": len(prepared.cross_site_services),
        "cross_site_complete_candidates": int(counts.get("cross_site_complete_candidates", 0)),
        "cross_site_legal_candidates": int(counts.get("cross_site_legal_candidates", 0)),
        "cross_site_accepted_candidates": int(counts.get("cross_site_accepted_candidates", 0)),
        "solution_path": str(solution_path.relative_to(ROOT)),
        "solution_sha256": sha256(solution_path),
        "certificate_path": str(certificate_path.relative_to(ROOT)),
        "certificate_sha256": sha256(certificate_path),
        **legacy._certificate_stats(certificate),
        **metrics,
    }


def run_pair(spec: dict[str, Any], contract_sha256: str) -> dict[str, Any]:
    path = OUT / "pairs" / f"{spec['pair_id']}.json"
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("contract_sha256") == contract_sha256 and cached.get("pair_status") == "PASS":
            return cached
    try:
        rows = [
            run_arm(
                spec["instance"], spec["condition"], int(spec["seed"]), label, allow_cross, contract_sha256
            )
            for label, allow_cross in ARMS
        ]
        a, b = rows
        pair_status = "PASS" if (
            a["status"] == b["status"] == "PASS"
            and a["start_sha256"] == b["start_sha256"] == spec["start_sha256"]
            and a["evaluations"] == b["evaluations"] == ARM_BUDGET
            and a["cost_component_error"] <= 1e-6
            and b["cost_component_error"] <= 1e-6
            and a["cross_site_customer_count"] == 0
        ) else "HALT"
        payload = {
            "pair_id": spec["pair_id"],
            "contract_sha256": contract_sha256,
            "pair_status": pair_status,
            "rows": rows,
        }
    except Exception as exc:
        payload = {
            "pair_id": spec["pair_id"],
            "contract_sha256": contract_sha256,
            "pair_status": "HALT",
            "reason": f"{type(exc).__name__}: {exc}",
            "rows": [],
        }
    write_json(path, payload)
    return payload


def exact_two_sided_sign_p(positive: int, negative: int) -> float:
    n = positive + negative
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(0, min(positive, negative) + 1)) / (2 ** n)
    return min(1.0, 2.0 * tail)


def aggregate(specs: list[dict[str, Any]], contract_sha256: str) -> dict[str, Any]:
    pairs = []
    for spec in specs:
        path = OUT / "pairs" / f"{spec['pair_id']}.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("contract_sha256") == contract_sha256:
                pairs.append(payload)
    rows = [row for pair in pairs for row in pair.get("rows", [])]
    row_fields = sorted({key for row in rows for key in row}) if rows else ["run_id"]
    with (OUT / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=row_fields)
        writer.writeheader()
        writer.writerows(rows)

    paired_rows: list[dict[str, Any]] = []
    for pair in pairs:
        if pair.get("pair_status") != "PASS" or len(pair.get("rows", [])) != 2:
            continue
        indexed = {row["arm"]: row for row in pair["rows"]}
        a = indexed["ownership_fixed"]
        b = indexed["reassignment_allowed"]
        paired_rows.append(
            {
                "pair_id": pair["pair_id"],
                "instance": a["instance"],
                "condition": a["condition"],
                "seed": int(a["seed"]),
                "fixed_total_cost": float(a["total_cost"]),
                "shared_total_cost": float(b["total_cost"]),
                "saving_pct": (float(a["total_cost"]) - float(b["total_cost"])) / float(a["total_cost"]) * 100.0,
                "strict_win": bool(float(b["total_cost"]) < float(a["total_cost"]) - 1e-9 and int(b["cross_site_customer_count"]) > 0),
                "cross_site_customer_count": int(b["cross_site_customer_count"]),
                "delta_cost_fix": float(b["cost_fix"]) - float(a["cost_fix"]),
                "delta_cost_km": float(b["cost_km"]) - float(a["cost_km"]),
                "delta_cost_fuel": float(b["cost_fuel"]) - float(a["cost_fuel"]),
                "delta_cost_elec": float(b["cost_elec"]) - float(a["cost_elec"]),
                "delta_total_cost": float(b["total_cost"]) - float(a["total_cost"]),
            }
        )
    paired_fields = list(paired_rows[0]) if paired_rows else ["pair_id"]
    with (OUT / "paired_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=paired_fields)
        writer.writeheader()
        writer.writerows(sorted(paired_rows, key=lambda row: (row["instance"], row["condition"], row["seed"])))

    customer_counts = load_customer_counts()
    network_rows: list[dict[str, Any]] = []
    for instance in sorted({row["instance"] for row in paired_rows}):
        for condition in CONDITIONS:
            selected = [row for row in paired_rows if row["instance"] == instance and row["condition"] == condition]
            if not selected:
                continue
            network_rows.append(
                {
                    "instance": instance,
                    "customer_count": customer_counts[instance],
                    "condition": condition,
                    "seed_count": len(selected),
                    "mean_saving_pct": sum(float(row["saving_pct"]) for row in selected) / len(selected),
                    "strict_win_count": sum(bool(row["strict_win"]) for row in selected),
                    "mean_cross_site_customer_count": sum(int(row["cross_site_customer_count"]) for row in selected) / len(selected),
                    **{
                        f"mean_{name}": sum(float(row[name]) for row in selected) / len(selected)
                        for name in ("delta_cost_fix", "delta_cost_km", "delta_cost_fuel", "delta_cost_elec", "delta_total_cost")
                    },
                }
            )
    network_fields = list(network_rows[0]) if network_rows else ["instance"]
    with (OUT / "network_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=network_fields)
        writer.writeheader()
        writer.writerows(network_rows)

    expected_pairs = len(specs)
    completed_pairs = len(pairs)
    passed_pairs = sum(pair.get("pair_status") == "PASS" for pair in pairs)
    full_complete = completed_pairs == passed_pairs == expected_pairs
    complete_seed1 = all(
        any(
            pair.get("pair_id") == spec["pair_id"] and pair.get("pair_status") == "PASS"
            for pair in pairs
        )
        for spec in specs
        if int(spec["seed"]) == 1
    )
    decision: dict[str, Any] = {
        "status": "FORMAL_COMPLETE" if full_complete else "SEED1_CONTRACT_PASS" if complete_seed1 else "IN_PROGRESS_OR_HALT",
        "contract_sha256": contract_sha256,
        "expected_pairs": expected_pairs,
        "completed_pairs": completed_pairs,
        "passed_pairs": passed_pairs,
        "formal_complete": full_complete,
        "seed1_contract_complete": complete_seed1,
        "result_direction_used_as_execution_gate": False,
    }
    if full_complete:
        by_instance_condition = {(row["instance"], row["condition"]): row for row in network_rows}
        effect_rows = []
        for instance in sorted({row["instance"] for row in network_rows}):
            geographic = by_instance_condition[(instance, "geographic")]
            mixed = by_instance_condition[(instance, "mixed")]
            effect_rows.append(
                {
                    "instance": instance,
                    "customer_count": customer_counts[instance],
                    "geographic_mean_saving_pct": geographic["mean_saving_pct"],
                    "mixed_mean_saving_pct": mixed["mean_saving_pct"],
                    "mixed_minus_geographic_pct_points": float(mixed["mean_saving_pct"]) - float(geographic["mean_saving_pct"]),
                }
            )
        with (OUT / "portfolio_effect_summary.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(effect_rows[0]))
            writer.writeheader()
            writer.writerows(effect_rows)
        geographic_values = [float(row["geographic_mean_saving_pct"]) for row in effect_rows]
        mixed_values = [float(row["mixed_mean_saving_pct"]) for row in effect_rows]
        effect_values = [float(row["mixed_minus_geographic_pct_points"]) for row in effect_rows]
        def signs(values: list[float]) -> tuple[int, int]:
            return sum(value > 1e-9 for value in values), sum(value < -1e-9 for value in values)
        geo_pos, geo_neg = signs(geographic_values)
        mix_pos, mix_neg = signs(mixed_values)
        effect_pos, effect_neg = signs(effect_values)
        decision.update(
            {
                "geographic_mean_saving_pct": sum(geographic_values) / len(geographic_values),
                "mixed_mean_saving_pct": sum(mixed_values) / len(mixed_values),
                "mean_mixed_minus_geographic_pct_points": sum(effect_values) / len(effect_values),
                "geographic_positive_networks": geo_pos,
                "mixed_positive_networks": mix_pos,
                "mixed_greater_than_geographic_networks": effect_pos,
                "geographic_sign_test_p_two_sided": exact_two_sided_sign_p(geo_pos, geo_neg),
                "mixed_sign_test_p_two_sided": exact_two_sided_sign_p(mix_pos, mix_neg),
                "portfolio_effect_sign_test_p_two_sided": exact_two_sided_sign_p(effect_pos, effect_neg),
                "paper_classification": (
                    "spatial portfolio structure consistently increases customer-sharing value"
                    if effect_pos >= 8 and mix_pos >= 8
                    else "customer-sharing value depends on the individual network"
                    if effect_pos >= 3 or mix_pos >= 3
                    else "customer-sharing cost value is limited under the tested conditions"
                ),
            }
        )
    write_json(OUT / "decision.json", decision)
    return decision


def report(decision: dict[str, Any]) -> str:
    lines = [
        "# 客户组合与协同成本正式比较",
        "",
        f"状态：`{decision['status']}`。合同内共 {decision['completed_pairs']}/{decision['expected_pairs']} 对完成，{decision['passed_pairs']} 对通过。",
        "",
        "每一对都从同一份各自经营排班出发，一边固定客户归属，一边允许客户跨车场重新分配；两边计算次数、费用、车队上限和充电规则相同。公平、碳交易和跨场代理费在本实验中关闭。",
    ]
    if decision.get("formal_complete"):
        lines.extend(
            [
                "",
                f"地理聚集客户组合的平均成本变化为 {decision['geographic_mean_saving_pct']:.6f}%，空间混合客户组合为 {decision['mixed_mean_saving_pct']:.6f}%。",
                f"9 张地图中，空间混合组合的共享价值高于地理聚集组合的有 {decision['mixed_greater_than_geographic_networks']} 张。",
                f"预注册归类：{decision['paper_classification']}。",
                "",
                "这些数字只回答车辆不构成瓶颈时客户共享的成本价值；共同车队上限不是最少车辆，不能用来声称合作减少实体车。",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "当前只作合同收集状态，不解释结果方向。第一粒种子全部过合同后，按预注册顺序补种子 2、3。",
            ]
        )
    return "\n".join(lines) + "\n"


def artifact_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("prepare", "seed1", "remaining", "all"), default="prepare")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 2:
        raise SystemExit("workers must be 1 or 2")
    OUT.mkdir(parents=True, exist_ok=True)
    envelopes = load_envelopes()
    preflight = preflight_assets(envelopes)
    if len(preflight) != 18 or any(row["status"] != "PASS" for row in preflight):
        raise SystemExit("start preflight did not pass all 18 inputs")

    source_paths = (
        Path(__file__).resolve(),
        ROOT / "baselines/e3_ablation/e3_v3_runner.py",
        ROOT / "solver/src/setp_solver/cost.py",
        ROOT / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
        ROOT / "solver/src/setp_solver/search/e3_multitrip_runtime.py",
        ROOT / "solver/src/setp_solver/search/multitrip_schedule.py",
    )
    metadata = {
        "schema": "setp.e3.paired_cost_formal.v2",
        "instances": [row["instance"] for row in envelopes],
        "conditions": list(CONDITIONS),
        "seeds": list(SEEDS),
        "arms": {label: allow for label, allow in ARMS},
        "arm_budget": ARM_BUDGET,
        "fairness_enabled": False,
        "carbon_weight": 0.0,
        "carbon_price": 0.0,
        "cross_site_fee": 0.0,
        "charging_strategy": "immediate feasible",
        "fleet_role": "common ample-fleet cap fixed before cooperation search; not a minimum-fleet estimate",
        "statistical_unit": "base network; three seeds are averaged within each network-condition",
        "source_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
        ).stdout.strip(),
        "ownership_decision_sha256": sha256(OWNERSHIP_ROOT / "decision.json"),
        "fleet_envelope_decision_sha256": sha256(ENVELOPE_ROOT / "decision.json"),
        "source_hashes": {str(path.relative_to(ROOT)): sha256(path) for path in source_paths},
    }
    metadata_bytes = canonical_bytes(metadata)
    contract_sha256 = hashlib.sha256(metadata_bytes).hexdigest()
    metadata["contract_sha256"] = contract_sha256
    write_json(OUT / "metadata.json", metadata)

    start_meta = {
        (row["instance"], row["condition"]): row
        for row in preflight
    }
    specs = [
        {
            "pair_id": f"{item['instance']}__{condition}__seed{seed}",
            "instance": item["instance"],
            "source_scale": item["source_scale"],
            "condition": condition,
            "seed": seed,
            "start_sha256": start_meta[(item["instance"], condition)]["start_sha256"],
            "contract_sha256": contract_sha256,
        }
        for item in envelopes
        for condition in CONDITIONS
        for seed in SEEDS
    ]
    with (OUT / "task_manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(specs[0]))
        writer.writeheader()
        writer.writerows(specs)

    selected = []
    if args.stage in {"seed1", "all"}:
        selected.extend(spec for spec in specs if int(spec["seed"]) == 1)
    if args.stage in {"remaining", "all"}:
        selected.extend(spec for spec in specs if int(spec["seed"]) in {2, 3})
    if selected:
        selected.sort(key=lambda spec: (int(spec["source_scale"]), spec["condition"], int(spec["seed"])))
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(run_pair, spec, contract_sha256): spec for spec in selected}
            for future in as_completed(futures):
                payload = future.result()
                print(json.dumps({"pair_id": payload["pair_id"], "pair_status": payload["pair_status"]}, ensure_ascii=False), flush=True)

    decision = aggregate(specs, contract_sha256)
    (OUT / "report.md").write_text(report(decision), encoding="utf-8")
    write_json(OUT / "artifact_hashes.json", artifact_hashes())
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    if args.stage == "prepare":
        return 0
    return 0 if decision["status"] in {"SEED1_CONTRACT_PASS", "FORMAL_COMPLETE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
