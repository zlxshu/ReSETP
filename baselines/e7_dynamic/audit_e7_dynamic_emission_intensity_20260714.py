#!/usr/bin/env python3
"""Zero-search audit of realised E7 emissions per kilogram served.

The two E7 arms can realise slightly different full-day workloads because an
event that arrives after dispatch is locked for one arm but still editable for
the other.  Absolute emissions are therefore not treated as a paired treatment
effect.  This audit divides the independently reconstructed full-day emissions
ledger by the actually served demand and reports a descriptive paired change.
It does not claim that E7 used forecast-aware charging during online search.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
from typing import Any

import validate_e7_records_independent_20260714 as record_audit


REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = REPO_ROOT / "baselines/e7_dynamic/e7_v2_20260714/formal_shared_start_400_route_fix"
VALUE_DIR = REPO_ROOT / "baselines/e7_dynamic/e7_full_day_value_audit_formal_20260714"
EXPECTED_STREAMS = (1, 2, 3, 4, 5)
EXPECTED_ARMS = ("cooperative", "independent")
FIELDS = (
    "E_total",
    "E_cv_direct",
    "E_ev_indirect",
    "fuel_liters",
    "electricity_kwh",
    "distance_total",
)
TOL = 1e-9


class AuditError(RuntimeError):
    pass


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError as exc:
        raise AuditError(f"path leaves repository: {path}") from exc


def current_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.PIPE,
        ).strip()
    except subprocess.CalledProcessError as exc:
        raise AuditError("cannot read current audit commit") from exc


def validate_sources() -> dict[str, Any]:
    commit = current_commit()
    paths = (
        Path(__file__).resolve(),
        (Path(__file__).resolve().parent / "validate_e7_records_independent_20260714.py").resolve(),
    )
    evidence: dict[str, Any] = {}
    for path in paths:
        rel = relative(path)
        working_hash = sha256(path)
        committed_hash = hashlib.sha256(
            record_audit.git_blob(REPO_ROOT, commit, rel)
        ).hexdigest()
        if working_hash != committed_hash:
            raise AuditError(f"audit source differs from HEAD: {rel}")
        evidence[rel] = {"commit": commit, "sha256": working_hash}
    return evidence


def validate_value_evidence() -> dict[str, Any]:
    decision = read_json(VALUE_DIR / "decision.json")
    if decision.get("status") != "PASS":
        raise AuditError("full-day value audit did not pass")
    manifest = read_json(VALUE_DIR / "artifact_hashes.json")
    listed = {str(row["path"]): row for row in manifest.get("artifacts", [])}
    actual: dict[str, Path] = {}
    for path in VALUE_DIR.rglob("*"):
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._"):
            actual[relative(path)] = path
    if set(listed) != set(actual):
        raise AuditError("full-day value audit inventory does not close")
    for rel, path in actual.items():
        if listed[rel]["sha256"] != sha256(path):
            raise AuditError(f"full-day value evidence drifted: {rel}")
        if int(listed[rel]["bytes"]) != path.stat().st_size:
            raise AuditError(f"full-day value byte count drifted: {rel}")
    return {
        "path": relative(VALUE_DIR),
        "artifact_count": len(listed),
        "manifest_sha256": sha256(VALUE_DIR / "artifact_hashes.json"),
    }


def arm_row(stream: int, arm: str) -> dict[str, Any]:
    if stream not in EXPECTED_STREAMS or arm not in EXPECTED_ARMS:
        raise AuditError("unexpected stream or arm")
    stage_path = RUN_DIR / "stage_evidence" / f"stream{stream}__{arm}.json"
    stages = read_json(stage_path)
    if not stages:
        raise AuditError(f"stream {stream} {arm} has no stage evidence")
    parts = stages[-1]["cost_breakdown"]
    ledger = read_json(VALUE_DIR / "service_ledgers" / f"stream{stream}__{arm}.json")
    demand = float(ledger["served_demand_kg"])
    if demand <= 0:
        raise AuditError(f"stream {stream} {arm} has non-positive served demand")
    total = float(parts["E_total"])
    direct = float(parts["E_cv_direct"])
    indirect = float(parts["E_ev_indirect"])
    if abs(total - direct - indirect) > TOL * max(1.0, abs(total)):
        raise AuditError(f"stream {stream} {arm} emissions do not close")
    if abs(float(parts["total_cost"]) - float(ledger["final_total_cost"])) > TOL * max(
        1.0, abs(float(parts["total_cost"]))
    ):
        raise AuditError(f"stream {stream} {arm} cost/value ledgers disagree")
    row: dict[str, Any] = {
        "stream_seed": stream,
        "arm": arm,
        "served_customer_count": int(ledger["served_customer_count"]),
        "served_demand_kg": demand,
        "total_cost": float(parts["total_cost"]),
    }
    for field in FIELDS:
        value = float(parts[field])
        row[field] = value
        row[f"{field}_per_kg"] = value / demand
    row["emissions_closure_error"] = total - direct - indirect
    return row


def paired_row(cooperative: dict[str, Any], independent: dict[str, Any]) -> dict[str, Any]:
    if cooperative["stream_seed"] != independent["stream_seed"]:
        raise AuditError("cannot pair different event streams")
    row: dict[str, Any] = {
        "stream_seed": int(cooperative["stream_seed"]),
        "cooperative_demand_kg": cooperative["served_demand_kg"],
        "independent_demand_kg": independent["served_demand_kg"],
        "workload_equal": abs(
            float(cooperative["served_demand_kg"]) - float(independent["served_demand_kg"])
        ) <= TOL,
    }
    for field in FIELDS:
        key = f"{field}_per_kg"
        baseline = float(independent[key])
        if baseline <= 0:
            raise AuditError(f"non-positive independent intensity: {field}")
        row[f"cooperative_{key}"] = cooperative[key]
        row[f"independent_{key}"] = independent[key]
        row[f"{field}_intensity_change_percent"] = (
            100.0 * (float(cooperative[key]) - baseline) / baseline
        )
    return row


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def artifact_manifest(output: Path) -> dict[str, Any]:
    artifacts = []
    for path in sorted(output.rglob("*")):
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
            and "__pycache__" not in path.parts
            and ".pytest_cache" not in path.parts
        ):
            artifacts.append(
                {"path": relative(path), "sha256": sha256(path), "bytes": path.stat().st_size}
            )
    return {
        "algorithm": "sha256",
        "excluded": ["artifact_hashes.json", "._*", "__pycache__", ".pytest_cache"],
        "artifacts": artifacts,
    }


def run_audit(output: Path) -> dict[str, Any]:
    output = output.resolve()
    if output.exists():
        raise AuditError("output directory must be new")
    source_evidence = validate_sources()
    value_evidence = validate_value_evidence()
    replay = record_audit.validate_formal_run(REPO_ROOT, RUN_DIR)
    if replay.get("verdict") != "RECORD_LAYER_PASS":
        raise AuditError("formal E7 record replay did not pass")

    raw = [arm_row(stream, arm) for stream in EXPECTED_STREAMS for arm in EXPECTED_ARMS]
    indexed = {(int(row["stream_seed"]), str(row["arm"])): row for row in raw}
    paired = [
        paired_row(indexed[(stream, "cooperative")], indexed[(stream, "independent")])
        for stream in EXPECTED_STREAMS
    ]
    total_changes = [float(row["E_total_intensity_change_percent"]) for row in paired]
    fuel_changes = [float(row["E_cv_direct_intensity_change_percent"]) for row in paired]
    electric_changes = [float(row["electricity_kwh_intensity_change_percent"]) for row in paired]
    decision = {
        "status": "PASS",
        "verdict": "E7_DYNAMIC_EMISSION_INTENSITY_AUDIT_PASS",
        "stream_count": len(paired),
        "all_pairs_had_different_realised_workload": all(not row["workload_equal"] for row in paired),
        "higher_total_emission_intensity_stream_count": sum(value > 0 for value in total_changes),
        "higher_fuel_emission_intensity_stream_count": sum(value > 0 for value in fuel_changes),
        "lower_electricity_intensity_stream_count": sum(value < 0 for value in electric_changes),
        "mean_total_emission_intensity_change_percent": statistics.mean(total_changes),
        "median_total_emission_intensity_change_percent": statistics.median(total_changes),
        "minimum_total_emission_intensity_change_percent": min(total_changes),
        "maximum_total_emission_intensity_change_percent": max(total_changes),
        "mean_fuel_emission_intensity_change_percent": statistics.mean(fuel_changes),
        "mean_electricity_intensity_change_percent": statistics.mean(electric_changes),
        "maximum_absolute_emissions_closure_error": max(
            abs(float(row["emissions_closure_error"])) for row in raw
        ),
        "interpretation": (
            "descriptive realised emissions per served kilogram; not a same-workload "
            "causal effect and not evidence that E7 used online forecast-aware charging"
        ),
    }
    metadata = {
        "contract_id": "E7_DYNAMIC_EMISSION_INTENSITY_AUDIT_V1",
        "scope": "formal_zero_search_audit",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_run": relative(RUN_DIR),
        "source_value_audit": value_evidence,
        "audit_commit": current_commit(),
        "audit_source": source_evidence,
        "streams": list(EXPECTED_STREAMS),
        "arms": list(EXPECTED_ARMS),
        "normalizer": "full-day served demand in kilograms",
        "result_direction_used_to_continue": False,
    }
    output.mkdir(parents=True, exist_ok=False)
    write_csv(output / "raw_runs.csv", raw)
    write_csv(output / "paired_summary.csv", paired)
    write_json(output / "independent_validation.json", replay)
    write_json(output / "metadata.json", metadata)
    write_json(output / "decision.json", decision)
    detail = [
        "| {stream} | {total:.3f}% | {fuel:.3f}% | {electric:.3f}% |".format(
            stream=int(row["stream_seed"]),
            total=float(row["E_total_intensity_change_percent"]),
            fuel=float(row["E_cv_direct_intensity_change_percent"]),
            electric=float(row["electricity_kwh_intensity_change_percent"]),
        )
        for row in paired
    ]
    report = [
        "# E7 动态订单下的单位货量排放",
        "",
        "## 判定",
        "",
        "机械复核通过。全天排放账、燃油车直接排放、电动车间接排放和实际完成货量逐组闭合。两种经营方式因发车时刻不同而完成了略有差异的工作，故本报告不直接比较排放总量，而按实际完成货量折算单位货量排放。",
        "",
        "五条订单变化序列中，合作经营的单位货量总排放均高于各自经营，平均增加{total:.3f}%；燃油车直接排放强度五条均上升，平均增加{fuel:.3f}%，而用电强度五条均下降，平均下降{electric:.3f}%。在本批成本导向的滚动安排中，少用电没有抵消多烧油形成的排放增加，说明动态合作的经济收益不会自动转化为低碳收益。".format(
            total=float(decision["mean_total_emission_intensity_change_percent"]),
            fuel=float(decision["mean_fuel_emission_intensity_change_percent"]),
            electric=abs(float(decision["mean_electricity_intensity_change_percent"])),
        ),
        "",
        "| 订单变化序列 | 单位货量总排放变化 | 燃油车直接排放强度变化 | 用电强度变化 |",
        "|---:|---:|---:|---:|",
        *detail,
        "",
        "## 证据边界",
        "",
        "这是一项对已实现全天安排的描述性核算。两边完成的订单并非逐项完全相同，单位货量也不能消除客户位置、时间窗和服务时长差异，因此不能把上述百分比解释为控制相同工作量后的普遍因果效应。动态搜索以成本为目标，未在每次调整中调用按预测碳强度择时的充电程序；充电择时的独立效果仍由E4给出。",
        "",
    ]
    (output / "report.md").write_text("\n".join(report), encoding="utf-8")
    write_json(output / "artifact_hashes.json", artifact_manifest(output))
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_audit(args.output_dir)
    except AuditError as exc:
        raise SystemExit(f"HALT: {exc}") from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
