#!/usr/bin/env python3
"""Zero-search multi-trip replay of saved E4/E6 solutions and E5 witnesses."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


REPO = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
E4_DIR = REPO / "baselines/china_e3_e7/e4_joint_routing_20260801"
E6_DIR = REPO / "baselines/china_e3_e7/e6_contractor_participation_20260801"
E5_DIR = REPO / "baselines/china_e3_e7/e5_enroute_nonlinear_20260801"
OUT = REPO / "baselines/china_e3_e7/multitrip_saved_solution_repack_20260801"
FLEET = REPO / "data/ChinaInstances/china81_finite_fleet_authority_v1_20260723"
E5_WITNESS_IDS = (
    "cn-prd-50c-01-V2-LOCATIONS",
    "cn-prd-100c-02-V2-LOCATIONS",
)

# This directory contains a project ``statistics.py`` that must not shadow
# Python's standard-library module imported by PyVRP.
sys.path = [
    entry
    for entry in sys.path
    if Path(entry or ".").resolve() != SCRIPT_DIR
]
for entry in (REPO, REPO / "solver/src", PROTOTYPE, E4_DIR, E6_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from e6_methods import subset_bundle
from joint_soc_wrapper import register_objective, score_fixed_solution
from run_pilot06_direct_15 import load_base as load_e6_base
from run_probe import load_bundle as load_e4_bundle
from setp_solver.check import check_solution
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import exact_china81_score
from setp_solver.search.metaheuristic_baselines import solution_from_dict
from setp_solver.search.multitrip_schedule import (
    prepare_multitrip_solution,
    validate_multitrip_certificate,
)
from setp_solver.solution import Route, Solution, physical_vehicle_id


EXPECTED = {"E4": 90, "E6": 900, "E5_WITNESS": 2}
FIELDS = (
    "record_id",
    "experiment",
    "instance_id",
    "seed",
    "variant",
    "source_path",
    "source_sha256",
    "formal_result",
    "status",
    "failure",
    "original_route_count",
    "original_physical_vehicle_count",
    "packed_physical_vehicle_count",
    "saved_physical_vehicle_count",
    "original_counts_by_depot_type",
    "packed_counts_by_depot_type",
    "certificate_status",
    "certificate_valid",
    "current_checker_violation_count",
    "experiment_checker_violation_count",
    "depot_fleet_violation_count",
    "saved_terminal_charge_count",
    "saved_terminal_charge_kwh",
    "interface_directly_usable",
    "interface_note",
    "certificate_record_sha256",
    "prepared_solution_sha256",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(REPO))


def violation_rows(violations: Any) -> list[dict[str, Any]]:
    return [asdict(item) for item in violations]


def solution_sha(solution: Solution) -> str:
    return canonical_sha(asdict(solution))


def original_counts(solution: Solution) -> Counter[tuple[str, str]]:
    vehicles: dict[str, tuple[str, str]] = {}
    for route in solution.routes:
        vehicles[physical_vehicle_id(route.vehicle_id)] = (
            route.home_depot_id,
            route.vehicle_type.lower(),
        )
    return Counter(vehicles.values())


def packed_counts(certificate: Any) -> Counter[tuple[str, str]]:
    vehicles: dict[str, tuple[str, str]] = {}
    for trip in certificate.trips:
        vehicles[trip.physical_vehicle_id] = (
            trip.home_depot_id,
            trip.vehicle_type.lower(),
        )
    return Counter(vehicles.values())


def counts_text(counts: Counter[tuple[str, str]]) -> str:
    return "|".join(
        f"{depot}:{vehicle_type}:{count}"
        for (depot, vehicle_type), count in sorted(counts.items())
    )


def depot_fleet_failures(
    counts: Counter[tuple[str, str]], bundle: Any
) -> list[str]:
    failures = []
    for (depot, vehicle_type), count in sorted(counts.items()):
        cap = int(bundle.fleet_caps_by_depot[depot][f"num_{vehicle_type}"])
        if count > cap:
            failures.append(f"{depot}:{vehicle_type}:{count}>{cap}")
    return failures


def load_e5_witness(path: Path) -> Solution:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Solution(
        routes=[
            Route(
                str(row["vehicle_id"]),
                str(row["vehicle_type"]),
                str(row["home_depot_id"]),
                [str(node) for node in row["node_sequence"]],
            )
            for row in payload["routes"]
        ]
    )


def source_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    e4_root = E4_DIR / "formal_panel_20260801"
    for path in sorted(e4_root.glob("*/solutions/*.json")):
        if path.name.startswith("._"):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        specs.append(
            {
                "experiment": "E4",
                "path": path,
                "payload": payload,
                "instance_id": str(payload["instance_id"]),
                "seed": int(payload["seed"]),
                "variant": str(payload["objective_mode"]),
            }
        )
    e6_root = E6_DIR / "formal_e6a_panel_20260801/units"
    for path in sorted(e6_root.glob("*/seed_*/solutions/*.json")):
        if path.name.startswith("._"):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        specs.append(
            {
                "experiment": "E6",
                "path": path,
                "payload": payload,
                "instance_id": str(payload["instance_id"]),
                "seed": int(payload["seed"]),
                "variant": "__".join(
                    str(member).removeprefix("D_")
                    for member in payload["coalition"]
                ),
                "coalition": tuple(str(member) for member in payload["coalition"]),
                "metadata_path": path.parents[1] / "metadata.json",
            }
        )
    for instance_id in E5_WITNESS_IDS:
        path = FLEET / "witnesses" / f"{instance_id}.json"
        specs.append(
            {
                "experiment": "E5_WITNESS",
                "path": path,
                "payload": None,
                "instance_id": instance_id,
                "seed": 1,
                "variant": "INITIAL_FLEET_AUTHORITY_WITNESS",
            }
        )
    counts = Counter(spec["experiment"] for spec in specs)
    if dict(counts) != EXPECTED:
        raise RuntimeError(f"source count mismatch: {dict(counts)} != {EXPECTED}")
    return specs


class Bundles:
    def __init__(self) -> None:
        self.e4: dict[str, Any] = {}
        self.e6_base: dict[tuple[str, str], Any] = {}
        self.e6: dict[tuple[str, tuple[str, ...]], Any] = {}
        self.e5: dict[str, Any] = {}

    def for_spec(self, spec: dict[str, Any]) -> Any:
        experiment = spec["experiment"]
        instance_id = spec["instance_id"]
        if experiment == "E4":
            if instance_id not in self.e4:
                self.e4[instance_id] = load_e4_bundle(instance_id)
            bundle = self.e4[instance_id]
            register_objective(bundle, spec["variant"])
            return bundle
        if experiment == "E6":
            metadata = json.loads(spec["metadata_path"].read_text(encoding="utf-8"))
            mapping_sha = str(metadata["mapping_sha256"])
            base_key = (instance_id, mapping_sha)
            if base_key not in self.e6_base:
                self.e6_base[base_key] = load_e6_base(instance_id, mapping_sha)[0]
            coalition_key = (instance_id, spec["coalition"])
            if coalition_key not in self.e6:
                self.e6[coalition_key] = subset_bundle(
                    self.e6_base[base_key], spec["coalition"]
                )
            return self.e6[coalition_key]
        if instance_id not in self.e5:
            self.e5[instance_id] = load_china81_bundle(REPO, instance_id)
        return self.e5[instance_id]


def process(spec: dict[str, Any], bundles: Bundles) -> tuple[dict[str, Any], dict[str, Any]]:
    path = spec["path"]
    experiment = spec["experiment"]
    record_id = "/".join(
        (experiment, spec["instance_id"], f"seed_{spec['seed']:02d}", spec["variant"])
    )
    source_hash = sha256(path)
    base_row: dict[str, Any] = {
        "record_id": record_id,
        "experiment": experiment,
        "instance_id": spec["instance_id"],
        "seed": spec["seed"],
        "variant": spec["variant"],
        "source_path": rel(path),
        "source_sha256": source_hash,
        "formal_result": False,
        "status": "",
        "failure": "",
        "original_route_count": 0,
        "original_physical_vehicle_count": 0,
        "packed_physical_vehicle_count": "",
        "saved_physical_vehicle_count": "",
        "original_counts_by_depot_type": "",
        "packed_counts_by_depot_type": "",
        "certificate_status": "",
        "certificate_valid": False,
        "current_checker_violation_count": "",
        "experiment_checker_violation_count": "",
        "depot_fleet_violation_count": "",
        "saved_terminal_charge_count": 0,
        "saved_terminal_charge_kwh": 0.0,
        "interface_directly_usable": False,
        "interface_note": "",
        "certificate_record_sha256": "",
        "prepared_solution_sha256": "",
    }
    detail: dict[str, Any] = {
        "record_id": record_id,
        "experiment": experiment,
        "source_path": rel(path),
        "source_sha256": source_hash,
        "formal_result": False,
    }
    try:
        bundle = bundles.for_spec(spec)
        solution = (
            load_e5_witness(path)
            if experiment == "E5_WITNESS"
            else solution_from_dict(spec["payload"]["solution"])
        )
        original = original_counts(solution)
        saved_terminals = (
            list(spec["payload"].get("terminal_charges", ()))
            if experiment == "E4"
            else []
        )
        prepared, certificate = prepare_multitrip_solution(
            solution, bundle.instance, bundle.prices
        )
        validate_multitrip_certificate(
            certificate,
            prepared.routes,
            bundle.prices,
            instance=bundle.instance,
        )
        packed = packed_counts(certificate)
        fleet_failures = depot_fleet_failures(packed, bundle)
        current_violations = check_solution(
            prepared, bundle.instance, bundle.prices
        )
        if experiment == "E4":
            register_objective(bundle, spec["variant"])
            experiment_violations = list(
                score_fixed_solution(prepared, bundle, validate_full=True).violations
            )
            interface_usable = not saved_terminals
            status = (
                "PASS_E4_CV_ONLY_DIAGNOSTIC"
                if interface_usable
                else "HALT_E4_MULTITRIP_SOC_ADAPTER_MISSING"
            )
            note = (
                "saved solution has no separate terminal-charge ledger"
                if interface_usable
                else "prepare_multitrip_solution does not receive E4 terminal_charges or its 60-20-80-next-day-60 SOC ledger"
            )
        else:
            _, _, experiment_violations = exact_china81_score(prepared, bundle)
            if experiment == "E6":
                interface_usable = not (
                    current_violations or experiment_violations or fleet_failures
                )
                status = (
                    "PASS_E6_REPACK_DIAGNOSTIC_ONLY"
                    if interface_usable
                    else "HALT_E6_REPACK_VALIDATION_FAILED"
                )
                note = "old coalition costs and allocations are not reusable after multi-trip repacking"
            else:
                interface_usable = not (
                    current_violations or experiment_violations or fleet_failures
                )
                status = (
                    "PASS_E5_INITIAL_WITNESS_DIAGNOSTIC_ONLY"
                    if interface_usable
                    else "HALT_E5_WITNESS_REPACK_VALIDATION_FAILED"
                )
                note = "initial fleet-authority witness only; not an E5 mechanism result"
        if current_violations or experiment_violations or fleet_failures:
            if status.startswith("PASS"):
                status = f"HALT_{experiment}_REPACK_VALIDATION_FAILED"
            interface_usable = False
        detail.update(
            {
                "status": status,
                "failure": "",
                "original_solution_sha256": solution_sha(solution),
                "prepared_solution_sha256": solution_sha(prepared),
                "original_counts_by_depot_type": {
                    f"{depot}|{vehicle_type}": count
                    for (depot, vehicle_type), count in sorted(original.items())
                },
                "packed_counts_by_depot_type": {
                    f"{depot}|{vehicle_type}": count
                    for (depot, vehicle_type), count in sorted(packed.items())
                },
                "saved_terminal_charges": saved_terminals,
                "certificate": certificate.as_dict(),
                "current_checker_violations": violation_rows(current_violations),
                "experiment_checker_violations": violation_rows(experiment_violations),
                "depot_fleet_violations": fleet_failures,
                "interface_directly_usable": interface_usable,
                "interface_note": note,
            }
        )
        base_row.update(
            {
                "status": status,
                "original_route_count": len(solution.routes),
                "original_physical_vehicle_count": sum(original.values()),
                "packed_physical_vehicle_count": sum(packed.values()),
                "saved_physical_vehicle_count": sum(original.values()) - sum(packed.values()),
                "original_counts_by_depot_type": counts_text(original),
                "packed_counts_by_depot_type": counts_text(packed),
                "certificate_status": certificate.status,
                "certificate_valid": True,
                "current_checker_violation_count": len(current_violations),
                "experiment_checker_violation_count": len(experiment_violations),
                "depot_fleet_violation_count": len(fleet_failures),
                "saved_terminal_charge_count": len(saved_terminals),
                "saved_terminal_charge_kwh": sum(
                    float(row["energy_kwh"]) for row in saved_terminals
                ),
                "interface_directly_usable": interface_usable,
                "interface_note": note,
                "prepared_solution_sha256": solution_sha(prepared),
            }
        )
    except Exception as exc:
        base_row["status"] = f"HALT_{experiment}_PREPARE_OR_VALIDATE_FAILED"
        base_row["failure"] = f"{type(exc).__name__}: {exc}"
        base_row["interface_note"] = "failure retained; no repair was guessed"
        detail.update(
            {
                "status": base_row["status"],
                "failure": base_row["failure"],
                "interface_directly_usable": False,
                "interface_note": base_row["interface_note"],
            }
        )
    base_row["certificate_record_sha256"] = canonical_sha(detail)
    return base_row, detail


def source_hashes() -> dict[str, str]:
    paths = (
        Path(__file__).resolve(),
        REPO / "solver/src/setp_solver/search/multitrip_schedule.py",
        REPO / "solver/src/setp_solver/solution.py",
        REPO / "solver/src/setp_solver/check.py",
        E4_DIR / "run_probe.py",
        E4_DIR / "joint_soc_wrapper.py",
        E6_DIR / "run_pilot06_direct_15.py",
        E6_DIR / "e6_methods.py",
        E5_DIR / "run_b2_low_cost.py",
    )
    return {rel(path): sha256(path) for path in paths}


def summaries(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for experiment in EXPECTED:
        selected = [row for row in rows if row["experiment"] == experiment]
        result[experiment] = {
            "source_count": len(selected),
            "certificate_valid_count": sum(bool(row["certificate_valid"]) for row in selected),
            "interface_directly_usable_count": sum(bool(row["interface_directly_usable"]) for row in selected),
            "halt_count": sum(str(row["status"]).startswith("HALT") for row in selected),
            "original_route_count": sum(int(row["original_route_count"] or 0) for row in selected),
            "packed_physical_vehicle_count": sum(int(row["packed_physical_vehicle_count"] or 0) for row in selected),
            "saved_physical_vehicle_count": sum(int(row["saved_physical_vehicle_count"] or 0) for row in selected),
            "solutions_with_vehicle_saving": sum(int(row["saved_physical_vehicle_count"] or 0) > 0 for row in selected),
            "max_saved_physical_vehicles": max(
                (int(row["saved_physical_vehicle_count"] or 0) for row in selected),
                default=0,
            ),
        }
    return result


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def artifact_hashes() -> dict[str, str]:
    return {
        path.name: sha256(path)
        for path in sorted(OUT.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }


def render_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    e4 = summary["E4"]
    e6 = summary["E6"]
    e5 = summary["E5_WITNESS"]
    e4_terminal_count = sum(int(row["saved_terminal_charge_count"]) for row in rows if row["experiment"] == "E4")
    e4_terminal_kwh = sum(float(row["saved_terminal_charge_kwh"]) for row in rows if row["experiment"] == "E4")
    return f"""# 已保存解的多趟实体车零搜索诊断

## 结论

FACT：本诊断没有重跑搜索，没有修改路线、车型、车场、参数、预算或正式结果。它只把已保存路线交给现有 `prepare_multitrip_solution`，查看同车型、同车场的路线能否按时间先后装入同一辆实体车。`formal_result=false`。

FACT：E4 共 {e4['source_count']} 份正式保存解，通用函数产生 {e4['certificate_valid_count']} 份可自检的排班证书；{e4['solutions_with_vehicle_saving']} 份找到实体车复用，合计少用 {e4['saved_physical_vehicle_count']} 辆，单份最多少用 {e4['max_saved_physical_vehicles']} 辆。但这些解另存 {e4_terminal_count} 笔、{e4_terminal_kwh:.6f} kWh 返场补电，通用函数的输入中没有这个字段，也没有 E4 的 60%-20%-80%-次日60% 连续电量规则。因此结论是 `HALT_E4_MULTITRIP_SOC_ADAPTER_MISSING`：排班数可作诊断，不能替换 E4 的成本和排放结果。

FACT：E6 共 {e6['source_count']} 份联盟保存解，{e6['certificate_valid_count']} 份产生并通过排班证书自检；{e6['solutions_with_vehicle_saving']} 份找到实体车复用，合计少用 {e6['saved_physical_vehicle_count']} 辆，单份最多少用 {e6['max_saved_physical_vehicles']} 辆。其中 {e6['interface_directly_usable_count']} 份同时通过当前完整检查器，{e6['halt_count']} 份在通用证书通过后仍被完整检查器拒绝，失败都发生在第二趟电动车的趟间补电记账，原文已逐份保留。这只是旧路线的装车证据；旧联盟成本、Shapley、核和核仁均不能沿用。

FACT：E5 没有保存 B2 最终解，因此只纳入与当前 B2 两个算例对应的 {e5['source_count']} 份初始车队权威 witness。{e5['certificate_valid_count']} 份通过排班自检，合计少用 {e5['saved_physical_vehicle_count']} 辆。这不是 E5 非线性充电效应结果。

INFERENCE：这一诊断只证明现有贪心排班函数找到了某个可行装车方案，不证明实体车数已达数学最小值，也不证明允许多趟后重新搜索仍会选择这些路线。

## 文件

`raw_runs.csv` 每份输入一行；`schedule_certificates.jsonl` 保留每份的完整排班证书、检查结果或失败文本；`metadata.json`、`decision.json`、`artifact_hashes.json` 记录范围、判定与哈希。运行脚本的 `--check` 会重新核对输入、源码、证书记录和五件套哈希。
"""


def write_outputs(rows: list[dict[str, Any]], details: list[dict[str, Any]]) -> None:
    OUT.mkdir(parents=True, exist_ok=False)
    with (OUT / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with (OUT / "schedule_certificates.jsonl").open("w", encoding="utf-8") as handle:
        for detail in details:
            handle.write(json.dumps(detail, ensure_ascii=False, sort_keys=True) + "\n")
    summary = summaries(rows)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.saved-solution-multitrip-repack-diagnostic.v1",
            "created_at": datetime.now(UTC).isoformat(),
            "formal_result": False,
            "search_executed": False,
            "source_expected_counts": EXPECTED,
            "source_observed_counts": {
                key: value["source_count"] for key, value in summary.items()
            },
            "method": "call existing prepare_multitrip_solution on every saved route set; no route search",
            "source_code_sha256": source_hashes(),
            "summary": summary,
        },
    )
    write_json(
        OUT / "decision.json",
        {
            "formal_result": False,
            "status": "HALT_E4_ADAPTER_MISSING__E6_897_PASS_3_CHECKER_HALT__E5_WITNESS_ONLY",
            "e4": "HALT_E4_MULTITRIP_SOC_ADAPTER_MISSING",
            "e6": "897_DIAGNOSTIC_PASS__3_BETWEEN_TRIP_EV_LEDGER_HALT__REPRICE_AND_REALLOCATION_REQUIRED",
            "e5": "INITIAL_WITNESS_DIAGNOSTIC_ONLY_NO_FINAL_B2_SOLUTION",
            "summary": summary,
        },
    )
    (OUT / "report.md").write_text(
        render_report(summary, rows), encoding="utf-8"
    )
    write_json(OUT / "artifact_hashes.json", artifact_hashes())


def read_rows() -> list[dict[str, Any]]:
    with (OUT / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def check_outputs() -> dict[str, Any]:
    failures: list[str] = []
    rows = read_rows()
    if len(rows) != sum(EXPECTED.values()):
        failures.append(f"raw row count is {len(rows)}")
    counts = Counter(row["experiment"] for row in rows)
    if dict(counts) != EXPECTED:
        failures.append(f"raw experiment counts are {dict(counts)}")
    ids = [row["record_id"] for row in rows]
    if len(ids) != len(set(ids)):
        failures.append("duplicate record_id")
    for row in rows:
        source = REPO / row["source_path"]
        if not source.is_file() or sha256(source) != row["source_sha256"]:
            failures.append(f"source drift: {row['record_id']}")
        try:
            original = int(row["original_physical_vehicle_count"])
            packed = int(row["packed_physical_vehicle_count"])
            saved = int(row["saved_physical_vehicle_count"])
            if original - packed != saved or saved < 0:
                failures.append(f"count arithmetic: {row['record_id']}")
        except ValueError:
            if not row["status"].startswith("HALT"):
                failures.append(f"missing counts without HALT: {row['record_id']}")
    details = [
        json.loads(line)
        for line in (OUT / "schedule_certificates.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    detail_by_id = {item["record_id"]: item for item in details}
    if len(details) != len(rows) or len(detail_by_id) != len(details):
        failures.append("certificate record count or uniqueness mismatch")
    for row in rows:
        detail = detail_by_id.get(row["record_id"])
        if detail is None or canonical_sha(detail) != row["certificate_record_sha256"]:
            failures.append(f"certificate hash mismatch: {row['record_id']}")
    metadata = json.loads((OUT / "metadata.json").read_text(encoding="utf-8"))
    for path_text, expected_hash in metadata["source_code_sha256"].items():
        path = REPO / path_text
        if not path.is_file() or sha256(path) != expected_hash:
            failures.append(f"source code drift: {path_text}")
    expected_artifacts = json.loads((OUT / "artifact_hashes.json").read_text(encoding="utf-8"))
    if expected_artifacts != artifact_hashes():
        failures.append("artifact hash mismatch")
    decision = json.loads((OUT / "decision.json").read_text(encoding="utf-8"))
    if decision.get("formal_result") is not False or metadata.get("formal_result") is not False:
        failures.append("formal_result is not false")
    return {
        "status": "PASS" if not failures else "FAIL",
        "row_count": len(rows),
        "experiment_counts": dict(counts),
        "failure_count": len(failures),
        "failures": failures[:20],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        result = check_outputs()
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    specs = source_specs()
    bundles = Bundles()
    rows: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    for spec in specs:
        row, detail = process(spec, bundles)
        rows.append(row)
        details.append(detail)
    write_outputs(rows, details)
    print(json.dumps(summaries(rows), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
