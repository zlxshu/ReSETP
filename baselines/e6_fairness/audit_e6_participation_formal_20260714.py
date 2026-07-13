#!/usr/bin/env python3
"""Independently recompute the E6 participation evidence and paper metrics."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
E6 = ROOT / "baselines/e6_fairness/e6_participation_formal_20260714"
E3 = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713"
AUDIT = ROOT / "baselines/e6_fairness/e6_participation_audit_20260714"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing to write empty CSV: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def exact_two_sided_sign_p(positive: int, negative: int) -> float:
    n = positive + negative
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(positive, negative) + 1)) / 2**n
    return min(1.0, 2.0 * tail)


def dominance_adopted(
    rows: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    independent = rows["independent"]
    unrestricted = rows["unrestricted"]
    no_loss = rows["no_loss"]
    unrestricted_adopted = min(
        (independent, unrestricted, no_loss),
        key=lambda row: float(row["total_cost"]),
    )
    fair_candidates = [independent]
    if bool(unrestricted["both_depots_no_worse"]):
        fair_candidates.append(unrestricted)
    if bool(no_loss["both_depots_no_worse"]):
        fair_candidates.append(no_loss)
    fair_adopted = min(fair_candidates, key=lambda row: float(row["total_cost"]))
    return independent, unrestricted_adopted, fair_adopted


def main() -> int:
    AUDIT.mkdir(parents=True, exist_ok=True)
    metadata = read_json(E6 / "metadata.json")
    decision = read_json(E6 / "decision.json")
    contract = metadata["contract_sha256"]
    pairs = []
    for path in sorted((E6 / "pairs").glob("*.json")):
        if path.name.startswith("._"):
            continue
        payload = read_json(path)
        if payload.get("contract_sha256") == contract:
            pairs.append(payload)

    raw_rows = read_csv(E6 / "raw_runs.csv")
    paired_rows = read_csv(E6 / "paired_results.csv")
    paired_index = {row["spec_id"]: row for row in paired_rows}

    failures: list[str] = []
    if decision.get("status") != "FORMAL_COMPLETE":
        failures.append("decision is not FORMAL_COMPLETE")
    if len(pairs) != 54 or len({pair["spec_id"] for pair in pairs}) != 54:
        failures.append("formal pair count is not 54 unique specifications")
    if any(pair.get("pair_status") != "PASS" for pair in pairs):
        failures.append("at least one pair did not pass")
    if len(raw_rows) != 162 or len(paired_rows) != 54:
        failures.append("raw or paired row count mismatch")
    if any(
        row["status"] != "PASS"
        or int(float(row["budget"])) != 4000
        or int(float(row["evaluations"])) != 4000
        or int(float(row["violation_count"])) != 0
        for row in raw_rows
    ):
        failures.append("a formal arm failed its budget, status, or legality contract")

    max_cost_error = max(abs(float(row["cost_component_error"])) for row in raw_rows)
    max_profit_error = max(
        abs(float(row["profit_cost_allocation_error"])) for row in raw_rows
    )
    max_sub_cost_error = 0.0
    max_sub_profit_error = 0.0
    max_paired_error = 0.0
    paper_seed_rows: list[dict[str, Any]] = []

    for pair in pairs:
        rows = {row["arm"]: row for row in pair["rows"]}
        if set(rows) != {"independent", "unrestricted", "no_loss"}:
            failures.append(f"{pair['spec_id']}: missing arm")
            continue
        if rows["unrestricted"]["start_sha256"] != rows["no_loss"]["start_sha256"]:
            failures.append(f"{pair['spec_id']}: cooperative starts differ")
        sub_rows = pair.get("subproblem_rows", [])
        if len(sub_rows) != 2:
            failures.append(f"{pair['spec_id']}: independent subproblem count is not two")
        for sub_row in sub_rows:
            if int(sub_row["budget"]) != 2000 or int(sub_row["evaluations"]) != 2000:
                failures.append(f"{pair['spec_id']}: independent subproblem budget mismatch")
            for stem in ("solution", "certificate"):
                path = ROOT / sub_row[f"{stem}_path"]
                if not path.is_file() or sha256(path) != sub_row[f"{stem}_sha256"]:
                    failures.append(f"{pair['spec_id']}: {stem} hash mismatch")
        max_sub_cost_error = max(
            max_sub_cost_error, abs(float(pair["subproblem_cost_merge_error"]))
        )
        max_sub_profit_error = max(
            max_sub_profit_error, abs(float(pair["subproblem_profit_merge_error"]))
        )

        independent, unrestricted, fair = dominance_adopted(rows)
        base_cost = float(independent["total_cost"])
        unrestricted_cost = float(unrestricted["total_cost"])
        fair_cost = float(fair["total_cost"])
        if fair_cost + 1e-9 < unrestricted_cost:
            failures.append(f"{pair['spec_id']}: nested feasible-set dominance failed")
        if not bool(fair["both_depots_no_worse"]) or float(fair["minimum_profit_ratio"]) < 1 - 1e-9:
            failures.append(f"{pair['spec_id']}: adopted fair solution violates participation")

        recomputed = {
            "unrestricted_total_cost": unrestricted_cost,
            "no_loss_total_cost": fair_cost,
            "unrestricted_saving_vs_independent_pct":
                (base_cost - unrestricted_cost) / base_cost * 100.0,
            "no_loss_saving_vs_independent_pct":
                (base_cost - fair_cost) / base_cost * 100.0,
            "participation_cost_pct_points":
                (fair_cost - unrestricted_cost) / base_cost * 100.0,
        }
        stored = paired_index[pair["spec_id"]]
        for field, value in recomputed.items():
            max_paired_error = max(max_paired_error, abs(float(stored[field]) - value))

        paper_seed_rows.append(
            {
                "spec_id": pair["spec_id"],
                "instance": independent["instance"],
                "condition": independent["condition"],
                "seed": int(independent["seed"]),
                "saving_with_participation_vs_independent_pct":
                    (base_cost - fair_cost) / base_cost * 100.0,
                "participation_premium_vs_unrestricted_pct":
                    (fair_cost - unrestricted_cost) / unrestricted_cost * 100.0,
                "participation_cost_pct_points_vs_independent":
                    (fair_cost - unrestricted_cost) / base_cost * 100.0,
                "unrestricted_minimum_profit_ratio": float(unrestricted["minimum_profit_ratio"]),
                "fair_minimum_profit_ratio": float(fair["minimum_profit_ratio"]),
                "unrestricted_both_depots_no_worse": bool(unrestricted["both_depots_no_worse"]),
                "fair_cross_site_customer_count": int(fair["cross_site_customer_count"]),
            }
        )

    if max_cost_error > 1e-8 or max_profit_error > 1e-8:
        failures.append("formal cost or profit closure exceeds tolerance")
    if max_sub_cost_error > 1e-8 or max_sub_profit_error > 1e-8:
        failures.append("independent merge closure exceeds tolerance")
    if max_paired_error > 1e-10:
        failures.append("paired-results recomputation mismatch")

    e3_hashes = read_json(E3 / "artifact_hashes.json")
    e3_drift = [
        relative
        for relative, digest in e3_hashes.items()
        if not (E3 / relative).is_file() or sha256(E3 / relative) != digest
    ]
    if e3_drift:
        failures.append("sealed E3 evidence drifted")

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in paper_seed_rows:
        grouped[(row["instance"], row["condition"])].append(row)
    paper_network_rows: list[dict[str, Any]] = []
    for (instance, condition), rows in sorted(grouped.items()):
        paper_network_rows.append(
            {
                "instance": instance,
                "condition": condition,
                "seed_count": len(rows),
                "mean_saving_with_participation_vs_independent_pct": sum(
                    row["saving_with_participation_vs_independent_pct"] for row in rows
                ) / len(rows),
                "mean_participation_premium_vs_unrestricted_pct": sum(
                    row["participation_premium_vs_unrestricted_pct"] for row in rows
                ) / len(rows),
                "mean_participation_cost_pct_points_vs_independent": sum(
                    row["participation_cost_pct_points_vs_independent"] for row in rows
                ) / len(rows),
                "naturally_acceptable_unrestricted_seeds": sum(
                    bool(row["unrestricted_both_depots_no_worse"]) for row in rows
                ),
                "mean_fair_minimum_profit_ratio": sum(
                    row["fair_minimum_profit_ratio"] for row in rows
                ) / len(rows),
            }
        )

    condition_summary: dict[str, Any] = {}
    for condition in ("geographic", "mixed"):
        rows = [row for row in paper_network_rows if row["condition"] == condition]
        premium = [row["mean_participation_premium_vs_unrestricted_pct"] for row in rows]
        saving = [row["mean_saving_with_participation_vs_independent_pct"] for row in rows]
        positive_premium = sum(value > 1e-9 for value in premium)
        negative_premium = sum(value < -1e-9 for value in premium)
        positive_saving = sum(value > 1e-9 for value in saving)
        negative_saving = sum(value < -1e-9 for value in saving)
        condition_summary[condition] = {
            "network_count": len(rows),
            "mean_saving_with_participation_vs_independent_pct": sum(saving) / len(saving),
            "networks_with_positive_saving": positive_saving,
            "saving_sign_test_p_two_sided": exact_two_sided_sign_p(
                positive_saving, negative_saving
            ),
            "mean_participation_premium_vs_unrestricted_pct": sum(premium) / len(premium),
            "networks_with_positive_participation_premium": positive_premium,
            "participation_premium_sign_test_p_two_sided": exact_two_sided_sign_p(
                positive_premium, negative_premium
            ),
        }

    write_csv(AUDIT / "raw_runs.csv", paper_seed_rows)
    write_csv(AUDIT / "network_summary.csv", paper_network_rows)
    verification = {
        "status": "PASS" if not failures else "FAIL",
        "contract_sha256": contract,
        "formal_pairs": len(pairs),
        "formal_raw_rows": len(raw_rows),
        "all_formal_budgets_equal_4000": not any(
            int(float(row["budget"])) != 4000
            or int(float(row["evaluations"])) != 4000
            for row in raw_rows
        ),
        "all_cooperative_starts_identical_within_pair": not any(
            {row["arm"]: row for row in pair["rows"]}["unrestricted"]["start_sha256"]
            != {row["arm"]: row for row in pair["rows"]}["no_loss"]["start_sha256"]
            for pair in pairs
        ),
        "all_formal_solutions_legal": not any(
            int(float(row["violation_count"])) != 0 for row in raw_rows
        ),
        "max_cost_component_error": max_cost_error,
        "max_profit_allocation_error": max_profit_error,
        "max_independent_merge_cost_error": max_sub_cost_error,
        "max_independent_merge_profit_error": max_sub_profit_error,
        "max_paired_results_recomputation_error": max_paired_error,
        "sealed_e3_hash_drift_count": len(e3_drift),
        "paper_metric_definition": (
            "100 * (cost with both-depots-no-worse participation requirement - "
            "unrestricted cooperative cost) / unrestricted cooperative cost; "
            "three seeds are averaged within each network and nine networks receive equal weight"
        ),
        "condition_summary": condition_summary,
        "failures": failures,
    }
    write_json(
        AUDIT / "metadata.json",
        {
            "schema": "setp.e6.participation_independent_audit.v1",
            "formal_contract_sha256": contract,
            "formal_metadata_sha256": sha256(E6 / "metadata.json"),
            "formal_decision_sha256": sha256(E6 / "decision.json"),
            "audit_script": str(Path(__file__).resolve().relative_to(ROOT)),
            "audit_script_sha256": sha256(Path(__file__).resolve()),
            "statistical_unit": (
                "three seeds averaged within each network-condition; "
                "nine base networks receive equal weight"
            ),
            "primary_paper_metric": verification["paper_metric_definition"],
        },
    )
    write_json(AUDIT / "decision.json", verification)
    report_lines = [
        "# E6参与条件正式证据独立复算",
        "",
        f"状态：`{verification['status']}`。独立读取正式方案后复算 {len(pairs)} 组比较、{len(raw_rows)} 行正式搜索。",
        "",
        "机械核查包括：两合作方案起点相同、预算相同、独立子问题预算闭合、方案与证书指纹一致、零违规、成本与收益闭合、双方不吃亏，以及E3封存证据无漂移。",
        "",
        "论文主口径将参与条件的代价定义为：保证双方不吃亏的合作成本相对不限制单方收益的合作成本的增幅。每张网络先对3个种子取平均，再让9张网络等权。",
    ]
    for condition, label in (("geographic", "按地理关系组织客户"), ("mixed", "客户空间交错")):
        row = condition_summary[condition]
        report_lines.extend(
            [
                "",
                f"{label}：保证双方不吃亏后，相对各自经营仍平均节省 {row['mean_saving_with_participation_vs_independent_pct']:.6f}%；参与条件相对不限制收益的合作方案平均增加 {row['mean_participation_premium_vs_unrestricted_pct']:.6f}% 的系统成本。",
            ]
        )
    (AUDIT / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    artifact_hashes = {
        str(path.relative_to(AUDIT)): sha256(path)
        for path in sorted(AUDIT.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    write_json(AUDIT / "artifact_hashes.json", artifact_hashes)
    print(json.dumps(verification, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
