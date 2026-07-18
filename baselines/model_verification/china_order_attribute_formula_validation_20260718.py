#!/usr/bin/env python3
"""Validate the approved China order-attribute formulas and manuscript wording.

This is a zero-search audit. It reads the frozen 1,222-row empirical table,
the machine contract, and the TeX source; it neither builds China81 instances
nor calls the routing solver.
"""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/ChinaInstances/china_order_attribute_calibration_v2_20260718/empirical_order_attribute_rows.csv"
CONTRACT = ROOT / "data/ChinaInstances/china_order_attribute_contract_v2_20260718.json"
PAPER = ROOT / "docs/paper_submission_final/paper_main.tex"
OUT = ROOT / "baselines/model_verification/china_order_attribute_formula_validation_20260718"

VOLUMES = [Decimal("1.0"), Decimal("1.5"), Decimal("2.0"), Decimal("2.5"), Decimal("3.0")]
EXPECTED_DEMAND = [139, 208, 278, 347, 417]
EXPECTED_SERVICE = [Decimal("6"), Decimal("9"), Decimal("12"), Decimal("15"), Decimal("18")]


def demand_kg(volume_m3: Decimal) -> int:
    value = volume_m3 / Decimal("7.2") * Decimal("1000")
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def service_minutes(volume_m3: Decimal) -> Decimal:
    return volume_m3 * Decimal("0.1") * Decimal("60")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    tex = PAPER.read_text(encoding="utf-8")
    with SOURCE.open(encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))

    rows: list[dict[str, str]] = []
    for volume, expected_q, expected_s in zip(VOLUMES, EXPECTED_DEMAND, EXPECTED_SERVICE):
        actual_q = demand_kg(volume)
        actual_s = service_minutes(volume)
        share_error = abs(Decimal(actual_q) / Decimal("1000") - volume / Decimal("7.2"))
        ok = actual_q == expected_q and actual_s == expected_s and share_error <= Decimal("0.0005")
        rows.append(
            {
                "volume_m3": str(volume),
                "demand_kg": str(actual_q),
                "expected_demand_kg": str(expected_q),
                "service_minutes": str(actual_s),
                "expected_service_minutes": str(expected_s),
                "capacity_share_rounding_error": str(share_error),
                "status": "PASS" if ok else "FAIL",
            }
        )

    source_checks: list[tuple[str, bool, str]] = []
    source_checks.append(("source_row_count", len(source_rows) == 1222, f"rows={len(source_rows)}"))

    widths = [Decimal(row["delivery_width_minute"]) for row in source_rows]
    width_min = min(widths)
    width_median = Decimal(str(statistics.median(widths)))
    width_max = max(widths)
    summary = contract["time_window_profiles"]["base_empirical_delivery"]["window_width_minutes_summary"]
    source_checks.append(
        (
            "window_summary",
            abs(width_min - Decimal(str(summary["min"]))) <= Decimal("0.0000005")
            and abs(width_median - Decimal(str(summary["median"]))) <= Decimal("0.0000005")
            and abs(width_max - Decimal(str(summary["max"]))) <= Decimal("0.0000005"),
            f"min={width_min}, median={width_median}, max={width_max}",
        )
    )

    row_semantics_ok = True
    for row in source_rows:
        volume = Decimal(row["Volume of goods (m3)"])
        early = Decimal(row["delivery_early_minute"])
        late = Decimal(row["delivery_late_minute"])
        width = Decimal(row["delivery_width_minute"])
        if abs((late - early) - width) > Decimal("0.000001"):
            row_semantics_ok = False
            break
        if int(row["demand_kg_capacity_share_proxy"]) != demand_kg(volume):
            row_semantics_ok = False
            break
        if abs(Decimal(row["service_minutes_literature_rule"]) - service_minutes(volume)) > Decimal("0.000001"):
            row_semantics_ok = False
            break
    source_checks.append(
        (
            "joint_empirical_row_semantics",
            row_semantics_ok,
            "all rows retain volume, mapped demand, service duration, delivery-window start and width jointly",
        )
    )

    contract_ok = (
        contract["formal_search_allowed"] is False
        and contract["time_window_profiles"]["base_empirical_delivery"]["user_approved"] is True
        and contract["time_window_profiles"]["base_empirical_delivery"]["joint_fields_may_not_be_resampled_independently"] is True
        and contract["service_time_rule"]["user_approved"] is True
        and contract["demand_conversion_rule"]["observed_shipment_weight_claim_allowed"] is False
        and contract["service_time_rule"]["observed_stop_duration_claim_allowed"] is False
    )
    source_checks.append(
        (
            "machine_contract_boundaries",
            contract_ok,
            f"status={contract['status']}, formal_search_allowed={contract['formal_search_allowed']}",
        )
    )

    tex_tokens = (
        r"q_i=\operatorname{round}\!\left(\frac{v_i^{\mathrm{ord}}}{7.2}\times1000\right)",
        r"\sigma_{ir}=0.1v_i^{\mathrm{ord}}\times60=6v_i^{\mathrm{ord}}",
        "容量占比场景代理",
        "不代表实测停站时长",
        "不拆分各字段独立抽样",
        r"\cite{ref:65}",
    )
    missing_tokens = [token for token in tex_tokens if token not in tex]
    source_checks.append(
        (
            "tex_formula_and_boundaries",
            not missing_tokens,
            "all required formula, boundary and citation tokens present" if not missing_tokens else f"missing={missing_tokens}",
        )
    )

    formula_pass = all(row["status"] == "PASS" for row in rows)
    checks_pass = all(ok for _, ok, _ in source_checks)
    decision = {
        "status": "PASS" if formula_pass and checks_pass else "HALT",
        "formula_rows_passed": sum(row["status"] == "PASS" for row in rows),
        "formula_rows_total": len(rows),
        "audit_checks_passed": sum(ok for _, ok, _ in source_checks),
        "audit_checks_total": len(source_checks),
        "search_evaluations": 0,
        "stage2_started": False,
        "formal_instance_generation_authorized": False,
    }

    with (OUT / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    metadata = {
        "purpose": "numeric, unit, empirical-row and TeX audit of approved China order-attribute methods",
        "audit_date": "2026-07-18",
        "method": "Decimal arithmetic plus full 1,222-row deterministic replay",
        "source": str(SOURCE.relative_to(ROOT)),
        "contract": str(CONTRACT.relative_to(ROOT)),
        "paper": str(PAPER.relative_to(ROOT)),
        "source_sha256": sha256(SOURCE),
        "contract_sha256": sha256(CONTRACT),
        "paper_sha256": sha256(PAPER),
        "checks": [{"check": name, "status": "PASS" if ok else "FAIL", "detail": detail} for name, ok, detail in source_checks],
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = [
        "# 中国订单属性公式与时间窗联合抽样验证",
        "",
        f"结论：{decision['status']}。本验证未运行算法搜索，也未生成正式China81实例。",
        "",
        "五档体积均正确映射为139/208/278/347/417 kg和6/9/12/15/18 min；公斤值仅为容量占比场景代理，服务时长仅为文献案例参数。",
        "",
        "| 检查 | 结果 | 证据 |",
        "|---|---|---|",
        *[f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |" for name, ok, detail in source_checks],
        "",
        "边界：该PASS只验证订单属性方法、论文公式和手册同步，不启动阶段二，不授权正式实例或算法搜索。",
        "",
    ]
    (OUT / "report.md").write_text("\n".join(report), encoding="utf-8")
    hashes = {
        path.name: sha256(path)
        for path in sorted(OUT.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    (OUT / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(decision, ensure_ascii=False))
    if decision["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
