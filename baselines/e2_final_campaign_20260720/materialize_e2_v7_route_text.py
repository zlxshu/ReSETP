#!/usr/bin/env python3
"""Materialize the V7 route-detail paper block from sealed S4/S5 evidence."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
CAMPAIGN = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v7_small_archive_ledger_20260724"
)
S4 = CAMPAIGN / "table4_gate"
S5 = CAMPAIGN / "artifacts"
OUT = CAMPAIGN / "route_text_gate"
PREREGISTRATION = CAMPAIGN / "route_text_preregistration_v1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def verify_manifest(root: Path) -> None:
    payload = read_json(root / "artifact_hashes.json")
    artifacts = payload.get("artifacts", payload.get("files"))
    if not isinstance(artifacts, dict) or not artifacts:
        raise RuntimeError(f"empty artifact manifest: {root}")
    for relative, expected in artifacts.items():
        path = root / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"artifact hash drift: {path}")


def require_pass(root: Path, expected: str) -> dict[str, Any]:
    decision = read_json(root / "decision.json")
    if decision.get("verdict") != expected:
        raise RuntimeError(
            f"{root}: expected {expected}, got {decision.get('verdict')}"
        )
    verify_manifest(root)
    return decision


def validate_preregistration() -> None:
    payload = read_json(PREREGISTRATION)
    if (
        payload.get("operation")
        != "ZERO_SEARCH_SEALED_ROUTE_TEXT_MATERIALIZATION"
        or payload.get("result_rows_read_before_freeze") != 0
        or payload.get("search_executions") != 0
    ):
        raise RuntimeError("route-text preregistration is invalid")
    for relative, expected in payload["source_hashes"].items():
        path = REPO / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"route-text source drift: {relative}")


def as_float(row: dict[str, str], key: str) -> float:
    return float(row[key])


def main() -> int:
    validate_preregistration()
    s4_decision = require_pass(
        S4,
        "PASS_D6_CORRECTED_S4_ROUTE_DETAIL",
    )
    require_pass(
        S5,
        "PASS_E2_STAGED_V7_S5_ARTIFACTS",
    )

    rows = read_csv(S5 / "table_route_details.csv")
    detail = [row for row in rows if row["路径"] not in {"均值", "合计"}]
    totals = [row for row in rows if row["路径"] == "合计"]
    means = [row for row in rows if row["路径"] == "均值"]
    if not detail or len(totals) != 1 or len(means) != 1:
        raise RuntimeError("route-detail table lacks detail/mean/total rows")
    total = totals[0]
    mean = means[0]

    customer_total = int(total["num"])
    if sum(int(row["num"]) for row in detail) != customer_total:
        raise RuntimeError("route customer total does not close")
    fuel_routes = [row for row in detail if as_float(row, "油耗_L") > 0.0]
    electric_routes = [
        row for row in detail if as_float(row, "电耗_kWh") > 0.0
    ]
    if len(fuel_routes) + len(electric_routes) != len(detail):
        raise RuntimeError("route type cannot be identified from energy use")

    route_costs = [as_float(row, "成本_CNY") for row in detail]
    route_distances = [as_float(row, "距离_km") for row in detail]
    route_times = [as_float(row, "时间_h") for row in detail]
    load_rates = [
        float(row["装载率_pct"])
        for row in detail
        if row["装载率_pct"] not in {"", "-"}
    ]
    if len(load_rates) != len(detail):
        raise RuntimeError("route load rates are incomplete")

    note_payload = read_json(S5 / "table_notes.json")
    route_note = str(note_payload["route_detail"])
    narrative = (
        "% Generated from sealed V7 PASS evidence; do not hand-edit.\n"
        "\\subsubsection{最终解分析}\n\n"
        f"迭代展示算例{s4_decision['case_instance_id']}中，"
        f"MV-HGS-SP十次运行的最低成本解来自种子"
        f"{int(s4_decision['best_seed'])}。"
        "该完整解已经全局检查器和精确计分器复算，"
        "逐路线指标由同一评价口径重新计算，结果见"
        "表\\ref{tab:final-solution}。\n\n"
        f"该解总成本为{as_float(total, '成本_CNY'):.3f}元，"
        f"由{len(detail)}条配送趟构成，覆盖{customer_total}个客户；"
        f"单趟成本为{min(route_costs):.3f}--"
        f"{max(route_costs):.3f}元，"
        f"行驶距离为{min(route_distances):.3f}--"
        f"{max(route_distances):.3f}~km，"
        f"用时为{min(route_times):.3f}--"
        f"{max(route_times):.3f}~h。"
        f"其中燃油车趟{len(fuel_routes)}条、电动车趟"
        f"{len(electric_routes)}条，总油耗"
        f"{as_float(total, '油耗_L'):.3f}~L、总电耗"
        f"{as_float(total, '电耗_kWh'):.3f}~kWh，"
        f"全解碳排放为{as_float(total, '碳排放_kg'):.3f}~kg。"
        f"各趟平均装载率为{as_float(mean, '装载率_pct'):.2f}\\%，"
        f"最低装载率为{min(load_rates):.2f}\\%。"
        "这些数值用于描述最优解结构，"
        "不把不同路线之间的能耗或排放差异"
        "解释为车型替换的因果效应。\n\n"
        "\\begin{table}[H]\n"
        "\\centering\n"
        "\\caption{仿真实验最终路径表}\n"
        "\\label{tab:final-solution}\n"
        "\\setptabsetup\n"
        "\\input{../../baselines/e2_final_campaign_20260720/"
        "corrected_china81_rerun_v7_small_archive_ledger_20260724/"
        "artifacts/table_route_details.tex}\n"
        f"\\tabnote{{注：{route_note}}}\n"
        "\\end{table}\n"
    )

    OUT.mkdir(parents=True, exist_ok=True)
    narrative_path = OUT / "route_detail_narrative.tex"
    narrative_path.write_text(narrative, encoding="utf-8")
    decision = {
        "schema": "resetp.e2-v7-route-text.decision.v1",
        "verdict": "PASS_E2_V7_ROUTE_TEXT_MATERIALIZATION",
        "search_executions": 0,
        "source_result_rows_changed": 0,
        "case_instance_id": s4_decision["case_instance_id"],
        "best_seed": int(s4_decision["best_seed"]),
        "route_count": len(detail),
        "customer_count": customer_total,
        "narrative_sha256": sha256(narrative_path),
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.e2-v7-route-text.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in (
                    S4 / "decision.json",
                    S4 / "route_details.csv",
                    S5 / "decision.json",
                    S5 / "table_route_details.csv",
                    S5 / "table_route_details.tex",
                    S5 / "table_notes.json",
                    Path(__file__).resolve(),
                    PREREGISTRATION,
                )
            },
        },
    )
    (OUT / "report.md").write_text(
        "# E2 V7 route-detail paper text\n\n"
        f"Decision: `{decision['verdict']}`.\n\n"
        "The route-detail paragraph and table wrapper were generated "
        "without search from sealed S4/S5 PASS evidence. No solution, "
        "route, score, unit or claim boundary was changed.\n",
        encoding="utf-8",
    )
    artifacts = {
        path.name: sha256(path)
        for path in (
            narrative_path,
            OUT / "decision.json",
            OUT / "metadata.json",
            OUT / "report.md",
        )
    }
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": [
                "artifact_hashes.json",
                "done.json",
                "._*",
                "__pycache__",
                "*.tmp",
            ],
            "artifacts": artifacts,
        },
    )
    write_json(
        OUT / "done.json",
        {
            "schema": "resetp.e2-v7-route-text-done.v1",
            "verdict": decision["verdict"],
            "decision_sha256": sha256(OUT / "decision.json"),
            "narrative_sha256": sha256(narrative_path),
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
