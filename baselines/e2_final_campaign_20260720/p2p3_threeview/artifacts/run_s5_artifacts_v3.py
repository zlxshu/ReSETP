#!/usr/bin/env python3
"""S5-REV-V3: deterministic presentation repair over the sealed v2 outputs.

This revision does not run a solver and does not touch the S1--S4 raw ledger,
the P1 raw ledger, any evaluator, or TeX.  It preserves the v2 hash manifest
and writes only suffixed v3 artifacts plus the current canonical hash manifest.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import shutil
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import run_s5_artifacts_v2 as v2


ROOT = v2.ROOT
OUT = v2.OUT
P1 = v2.P1
P1_DECISION = v2.P1_DECISION
S4 = v2.S4
S4_ROUTE_DETAILS_V2 = v2.S4_ROUTE_DETAILS_V2
S2_EXCEPTION_ID = v2.S2_EXCEPTION_ID
APPLEDOUBLE_FLAG = v2.APPLEDOUBLE_FLAG
PAPER_ARMS = v2.PAPER_ARMS

TABLE5_ERROR_FIELDS = (
    "VCGP_Best_error_pct",
    "MDFIHA_Best_error_pct",
    "MDFIHA-ETGA_Best_error_pct",
    "PyVRP-HGS_Best_error_pct",
    "PyVRP-HGS_avg_error_pct",
    "MV-HGS-SP_Best_error_pct",
    "MV-HGS-SP_avg_error_pct",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_csv_with_fields(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise RuntimeError(f"CSV has no header: {path}")
        return list(reader), list(reader.fieldnames)


def _near(left: float, right: float) -> bool:
    return math.isclose(float(left), float(right), rel_tol=1.0e-12, abs_tol=1.0e-9)


def _tex_number(value: float, places: int = 3, bold: bool = False) -> str:
    rendered = f"{float(value):.{places}f}"
    return rf"\textbf{{{rendered}}}" if bold else rendered


def _preserve_v2_manifest() -> Path:
    current = OUT / "artifact_hashes.json"
    archive = OUT / "artifact_hashes_v2.json"
    if not current.is_file():
        raise RuntimeError("canonical v2 artifact_hashes.json is missing")
    if not archive.exists():
        shutil.copyfile(current, archive)
    if _sha256(archive) != _sha256(current):
        raise RuntimeError("artifact_hashes_v2.json exists but does not preserve the current v2 manifest")
    return archive


def _clean_output_appledouble() -> int:
    removed = 0
    for path in OUT.iterdir():
        if path.is_file() and path.name.startswith("._"):
            path.unlink()
            removed += 1
    return removed


def _build_table5_v3() -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    decision = json.loads(P1_DECISION.read_text(encoding="utf-8"))
    p1_rows = v2._read_csv(P1 / "raw_runs.csv")
    mother_by_instance: dict[str, list[float]] = {}
    hybrid_by_instance: dict[str, list[float]] = {}
    for row in p1_rows:
        mother_by_instance.setdefault(row["instance_id"], []).append(float(row["mother_cost"]))
        hybrid_by_instance.setdefault(row["instance_id"], []).append(float(row["hybrid_cost"]))

    fields = ["instance", "n", "BKS", *TABLE5_ERROR_FIELDS]
    rows: list[dict[str, Any]] = []
    mother_avg_errors: list[float] = []
    hybrid_avg_errors: list[float] = []
    for item in decision["table5"]:
        instance = item["instance"]
        mother_values = mother_by_instance.get(instance, [])
        hybrid_values = hybrid_by_instance.get(instance, [])
        if len(mother_values) != 10 or len(hybrid_values) != 10:
            raise RuntimeError(f"P1 instance {instance} does not have 10 mother/hybrid rows")
        bks = float(item["bks"])
        mother_avg_error = 100.0 * (statistics.fmean(mother_values) - bks) / bks
        hybrid_avg_error = 100.0 * (statistics.fmean(hybrid_values) - bks) / bks
        mother_avg_errors.append(mother_avg_error)
        hybrid_avg_errors.append(hybrid_avg_error)
        rows.append({
            "instance": instance,
            "n": item["n"],
            "BKS": bks,
            "VCGP_Best_error_pct": float(item["vcgp_error_pct"]),
            "MDFIHA_Best_error_pct": float(item["mdfiha_error_pct"]),
            "MDFIHA-ETGA_Best_error_pct": float(item["etga_error_pct"]),
            "PyVRP-HGS_Best_error_pct": float(item["mother_error_pct"]),
            "PyVRP-HGS_avg_error_pct": mother_avg_error,
            "MV-HGS-SP_Best_error_pct": float(item["hybrid_error_pct"]),
            "MV-HGS-SP_avg_error_pct": hybrid_avg_error,
        })

    p1_avg = decision["avg_row_error_pct"]
    avg_row = {
        "instance": "Avg",
        "n": "",
        "BKS": "",
        "VCGP_Best_error_pct": float(p1_avg["vcgp_error_pct"]),
        "MDFIHA_Best_error_pct": float(p1_avg["mdfiha_error_pct"]),
        "MDFIHA-ETGA_Best_error_pct": float(p1_avg["etga_error_pct"]),
        "PyVRP-HGS_Best_error_pct": float(p1_avg["mother_error_pct"]),
        "PyVRP-HGS_avg_error_pct": statistics.fmean(mother_avg_errors),
        "MV-HGS-SP_Best_error_pct": float(p1_avg["hybrid_error_pct"]),
        "MV-HGS-SP_avg_error_pct": statistics.fmean(hybrid_avg_errors),
    }
    rows.append(avg_row)
    audit = {
        "avg_best_errors_source": "P1 decision.json avg_row_error_pct",
        "avg_seed_average_errors_source": "P1 raw_runs.csv, mean of per-instance ten-seed average errors",
        "avg_row": avg_row,
        "p1_best_error_recheck": {
            "PyVRP-HGS": statistics.fmean(row["PyVRP-HGS_Best_error_pct"] for row in rows[:-1]),
            "MV-HGS-SP": statistics.fmean(row["MV-HGS-SP_Best_error_pct"] for row in rows[:-1]),
        },
    }
    if not _near(audit["p1_best_error_recheck"]["PyVRP-HGS"], avg_row["PyVRP-HGS_Best_error_pct"]):
        raise RuntimeError("P1 mother Best average does not match decision avg_row_error_pct")
    if not _near(audit["p1_best_error_recheck"]["MV-HGS-SP"], avg_row["MV-HGS-SP_Best_error_pct"]):
        raise RuntimeError("P1 hybrid Best average does not match decision avg_row_error_pct")
    return rows, fields, audit


def _tex_table5_v3(rows: list[dict[str, Any]]) -> str:
    lines = [
        r"\begin{tabular}{@{}lrrrrrrrrr@{}}",
        r"\toprule",
        r"实例 & $n$ & BKS & VCGP Best./\% & MDFIHA Best./\% & MDFIHA-ETGA Best./\% & \multicolumn{2}{c}{PyVRP-HGS} & \multicolumn{2}{c}{MV-HGS-SP}\\",
        r" &  &  &  &  &  & Best./\% & avg./\% & Best./\% & avg./\%\\",
        r"\midrule",
    ]
    for row in rows:
        values = [float(row[field]) for field in TABLE5_ERROR_FIELDS]
        minimum = min(values)
        metric_cells = [
            _tex_number(value, bold=_near(value, minimum))
            for value in values
        ]
        if row["instance"] == "Avg":
            prefix = ["Avg", "--", "--"]
        else:
            prefix = [str(row["instance"]), str(int(row["n"])), f"{float(row['BKS']):.3f}"]
        lines.append(" & ".join([*prefix, *metric_cells]) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    return "\n".join(lines) + "\n"


def _tex_table6_v3(rows: list[dict[str, Any]]) -> str:
    lines = [
        r"\begin{tabular}{@{}lrrrrrrrr@{}}",
        r"\toprule",
        r"种子/统计量 & \multicolumn{2}{c}{HGS-F} & \multicolumn{2}{c}{HGS-E} & \multicolumn{2}{c}{HGS-M} & \multicolumn{2}{c}{MV-HGS-SP}\\",
        r" & 成本/元 & CPU/s & 成本/元 & CPU/s & 成本/元 & CPU/s & 成本/元 & CPU/s\\",
        r"\midrule",
    ]
    for row in rows:
        costs = [float(row[f"{arm}_cost"]) for arm in PAPER_ARMS]
        minimum = min(costs)
        cells: list[str] = [str(row["seed"])]
        for arm, cost in zip(PAPER_ARMS, costs, strict=True):
            cpu = float(row[f"{arm}_cpu_seconds"])
            cells.extend([
                _tex_number(cost, bold=_near(cost, minimum)),
                f"{cpu:.2f}",
            ])
        lines.append(" & ".join(cells) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    return "\n".join(lines) + "\n"


def _tex_summary_v3(rows: list[dict[str, Any]]) -> str:
    lines = [
        r"\begin{tabular}{@{}llrrrrrrrr@{}}",
        r"\toprule",
        r"城市群 & 规模层 & \multicolumn{2}{c}{HGS-F} & \multicolumn{2}{c}{HGS-E} & \multicolumn{2}{c}{HGS-M} & \multicolumn{2}{c}{MV-HGS-SP}\\",
        r" &  & Best. & avg. & Best. & avg. & Best. & avg. & Best. & avg.\\",
        r"\midrule",
    ]
    for row in rows:
        bests = [float(row[f"{arm}_Best"]) for arm in PAPER_ARMS]
        avgs = [float(row[f"{arm}_avg"]) for arm in PAPER_ARMS]
        best_min = min(bests)
        avg_min = min(avgs)
        cells = [str(row["city_group"]), str(row["tiers"])]
        for best, avg in zip(bests, avgs, strict=True):
            cells.extend([
                _tex_number(best, bold=_near(best, best_min)),
                _tex_number(avg, bold=_near(avg, avg_min)),
            ])
        lines.append(" & ".join(cells) + r" \\")
    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"% Each cell is the mean of per-instance Best or five-seed average costs; registered HGS-E infeasible seed remains excluded only from that instance's HGS-E Best/avg.",
    ])
    return "\n".join(lines) + "\n"


def _aggregate_load_rate() -> dict[str, Any]:
    table4_dir = str(S4)
    if table4_dir not in sys.path:
        sys.path.insert(0, table4_dir)
    import run_s4_route_detail_v2 as s4  # noqa: E402

    _, _, _, _, solution, bundle = s4.v1._load_best()
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    total_actual = 0.0
    total_capacity = 0.0
    route_audit: list[dict[str, Any]] = []
    for route in solution.routes:
        loads = s4.v1._arc_loads(route.node_sequence, node_lookup)
        capacity = bundle.instance.payload_capacity_kg(route.vehicle_type, fallback=1.0)
        max_load = max(loads, default=0.0)
        total_actual += max_load
        total_capacity += capacity
        route_audit.append({
            "vehicle_id": route.vehicle_id,
            "vehicle_type": route.vehicle_type,
            "max_actual_load_kg": max_load,
            "capacity_kg": capacity,
            "route_load_rate_pct": 100.0 * max_load / capacity,
        })
    if total_capacity <= 0.0:
        raise RuntimeError("non-positive total vehicle capacity")
    return {
        "definition": "sum of route maximum actual loads / sum of route vehicle capacities",
        "route_count": len(route_audit),
        "total_actual_load_kg": total_actual,
        "total_capacity_kg": total_capacity,
        "aggregate_load_rate_pct": 100.0 * total_actual / total_capacity,
        "routes": route_audit,
    }


def _table4_v3(load_audit: dict[str, Any]) -> tuple[list[dict[str, str]], list[str], dict[str, Any]]:
    rows, fields = _read_csv_with_fields(S4_ROUTE_DETAILS_V2)
    total_rows = [row for row in rows if row["路径"] == "合计"]
    if len(total_rows) != 1:
        raise RuntimeError("S4 v2 route detail must contain exactly one 合计 row")
    total_row = dict(total_rows[0])
    total_row["装载率(%)"] = float(load_audit["aggregate_load_rate_pct"])
    output = [
        total_row if row["路径"] == "合计" else dict(row)
        for row in rows
    ]
    changed_fields = [
        field for before, after in zip(rows, output, strict=True)
        for field in fields
        if before[field] != str(after[field])
    ]
    if changed_fields != ["装载率(%)"]:
        raise RuntimeError(f"S5 v3 table4 changed unexpected fields: {changed_fields}")
    return output, fields, {
        "source": str(S4_ROUTE_DETAILS_V2.relative_to(ROOT)),
        "changed_row": "合计",
        "changed_field": "装载率(%)",
        "source_value": float(total_rows[0]["装载率(%)"]),
        "v3_value": float(total_row["装载率(%)"]),
        "load_audit": load_audit,
    }


def _copy_v2_outputs() -> list[Path]:
    pairs = [
        ("figure4_convergence_v2.pdf", "figure4_convergence_v3.pdf"),
        ("figure4_convergence_v2.png", "figure4_convergence_v3.png"),
        ("figure4_curve_data_v2.csv", "figure4_curve_data_v3.csv"),
        ("china81_pairwise_tests_v2.csv", "china81_pairwise_tests_v3.csv"),
    ]
    copied: list[Path] = []
    for source_name, target_name in pairs:
        source = OUT / source_name
        target = OUT / target_name
        if not source.is_file():
            raise RuntimeError(f"missing v2 output: {source}")
        shutil.copyfile(source, target)
        copied.append(target)
    return copied


def _all_hash_paths(
    archive: Path,
    task_card: Path,
    monitor_config: Path,
    script: Path,
    decision: Path,
    metadata: Path,
    report: Path,
) -> list[Path]:
    names = [
        "table4_route_details_v3.csv", "table4_route_details_v3.tex",
        "table5_public_v3.csv", "table5_public_v3.tex",
        "table6_representative_v3.csv", "table6_representative_v3.tex",
        "china81_summary_v3.csv", "china81_summary_v3.tex",
        "china81_pairwise_tests_v3.csv",
        "figure4_convergence_v3.pdf", "figure4_convergence_v3.png",
        "figure4_curve_data_v3.csv",
    ]
    return [
        archive, task_card, monitor_config, script,
        *(OUT / name for name in names), decision, metadata, report,
    ]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    decision_path = OUT / "decision_v3.json"
    metadata_path = OUT / "metadata_v3.json"
    report_path = OUT / "report_v3.md"
    done_path = OUT / "done_v3.json"
    task_card = OUT / "task_card_v3.md"
    monitor_config = OUT / "monitor_v4.json"
    script_path = Path(__file__).resolve()
    try:
        v2_manifest = _preserve_v2_manifest()
        v2._require_pass(OUT / "decision_v2.json", "PASS_S5_ARTIFACTS")
        table5, table5_fields, table5_audit = _build_table5_v3()
        s3_rows = v2._read_csv(v2.S3 / "raw_runs.csv")
        if len(s3_rows) != 40:
            raise RuntimeError(f"S3 raw row count is {len(s3_rows)}, expected 40")
        table6, table6_fields = v2._table6_v2(s3_rows)
        _, values, s2_context = v2._load_s2_records()
        instance_stats = v2._instance_statistics(s2_context["tiers"], values)
        summary, summary_fields = v2._summary_rows(instance_stats)
        tests, _ = v2._pairwise_tests(values)
        table4, table4_fields, table4_audit = _table4_v3(_aggregate_load_rate())

        v2._write_csv(OUT / "table4_route_details_v3.csv", table4, table4_fields)
        v2._write_csv(OUT / "table5_public_v3.csv", table5, table5_fields)
        v2._write_csv(OUT / "table6_representative_v3.csv", table6, table6_fields)
        v2._write_csv(OUT / "china81_summary_v3.csv", summary, summary_fields)
        v2._write_csv(OUT / "china81_pairwise_tests_v3.csv", tests, list(tests[0].keys()))
        (OUT / "table4_route_details_v3.tex").write_text(v2._tex_table4(table4), encoding="utf-8")
        (OUT / "table5_public_v3.tex").write_text(_tex_table5_v3(table5), encoding="utf-8")
        (OUT / "table6_representative_v3.tex").write_text(_tex_table6_v3(table6), encoding="utf-8")
        (OUT / "china81_summary_v3.tex").write_text(_tex_summary_v3(summary), encoding="utf-8")
        _copy_v2_outputs()

        removed = _clean_output_appledouble()
        flags = [APPLEDOUBLE_FLAG] if removed else []
        decision = {
            "schema_version": "resetp.e2-final-campaign.s5-artifacts.v3",
            "decision": "PASS_S5_ARTIFACTS",
            "revision": "S5-REV-V3",
            "source_decision_v2": "decision_v2.json",
            "v2_outputs_preserved": True,
            "data_values_changed": False,
            "table5_rows": len(table5),
            "table5_columns": table5_fields,
            "table6_rows": len(table6),
            "china81_summary_rows": len(summary),
            "table4_rows": len(table4),
            "table4_load_rate_revision": table4_audit,
            "figure4_copied_without_value_change": True,
            "pairwise_tests_copied_without_value_change": True,
            "s2_registered_exception_id": S2_EXCEPTION_ID,
            "claim_boundary": "S5 v3 is deterministic presentation materialization from sealed evidence; it authorizes no superiority, equal-compute, or model claim.",
            "integrity_flags": flags,
        }
        _write_json(decision_path, decision)
        metadata = {
            "schema_version": "resetp.e2-final-campaign.s5-artifacts-metadata.v3",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "command": " ".join([sys.executable, *sys.argv]),
            "git_head": v2._git_head(),
            "branch": "codex/reporting-pipeline",
            "python": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "source_sha256": {
                "v2_decision": v2._sha256(OUT / "decision_v2.json"),
                "v2_manifest_archive": v2._sha256(v2_manifest),
                "s2_raw": v2._sha256(v2.S2 / "raw_runs.csv"),
                "s3_raw": v2._sha256(v2.S3 / "raw_runs.csv"),
                "s4_route_details_v2": v2._sha256(S4_ROUTE_DETAILS_V2),
                "p1_raw": v2._sha256(P1 / "raw_runs.csv"),
                "p1_decision": v2._sha256(P1_DECISION),
            },
            "table5_average_row_audit": table5_audit,
            "table4_load_rate_audit": table4_audit,
            "presentation_repairs": [
                "Table 5 adds PyVRP-HGS mother Best/avg error columns and uses BKS-relative errors for every algorithm metric.",
                "Table 5 appends the P1 decision-based Avg row and bolds the minimum error in each row.",
                "Table 6 bolds only row-wise minimum costs, including Min/Avg/Max; CPU cells are never bold.",
                "China81 summary bolds row-wise minimum Best and avg costs independently.",
                "Table 4 replaces the invalid total load-rate maximum with sum(route maximum actual loads)/sum(route capacities).",
            ],
            "s2_registered_exception_id": S2_EXCEPTION_ID,
            "integrity_flags": flags,
        }
        _write_json(metadata_path, metadata)
        report = (
            "# S5-REV-V3 unified artifacts\n\n"
            "Decision: PASS_S5_ARTIFACTS; revision: S5-REV-V3.\n\n"
            "This was a deterministic presentation repair over the sealed S5 v2 "
            "materialization. No solver was run, no raw CSV, witness, evaluator, "
            "protected TeX, or statistical input was modified. All v2 files and "
            "the v2 artifact hash manifest are preserved.\n\n"
            "## Repairs\n\n"
            "Table 5 now has the requested columns: VCGP Best error, MDFIHA Best "
            "error, MDFIHA-ETGA Best error, PyVRP-HGS Best/avg error, and "
            "MV-HGS-SP Best/avg error, all relative to BKS; BKS remains the "
            "reference-value column. Its final Avg row uses "
            "P1 decision.json avg_row_error_pct for the Best columns and sealed "
            "P1 raw_runs.csv for the ten-seed average columns. Row-wise minimum "
            "errors are bold.\n\n"
            "Table 6 bolds only the minimum cost in every seed and Min/Avg/Max "
            "row; CPU values are not bold. The China81 summary independently "
            "bolds the minimum Best and avg cost in every row.\n\n"
            "For Table 4, the route-level definition is maximum actual load divided "
            "by vehicle capacity. The total row therefore uses the additive "
            "capacity-weighted quantity sum(route maximum actual loads) divided "
            "by sum(route capacities): "
            f"{table4_audit['load_audit']['total_actual_load_kg']:.3f} kg / "
            f"{table4_audit['load_audit']['total_capacity_kg']:.3f} kg = "
            f"{table4_audit['v3_value']:.6f} percent. Only the total-row "
            "装载率 cell differs from table4_route_details_v2.csv.\n\n"
            f"The registered S2 exception {S2_EXCEPTION_ID} remains unchanged; "
            "HGS-E is feasible on 404/405 units and the affected instance uses "
            "four feasible seeds for Best/avg. No failed row was rerun or "
            "replaced.\n\n"
            "Figure 4, its curve data, and the paired-test CSV are copied "
            "byte-for-byte from v2 because none of the four requested repairs "
            "changes their values.\n"
        )
        report_path.write_text(report, encoding="utf-8")

        removed_after = _clean_output_appledouble()
        if removed_after:
            flags = list(dict.fromkeys([*flags, APPLEDOUBLE_FLAG]))
            decision["integrity_flags"] = flags
            metadata["integrity_flags"] = flags
            _write_json(decision_path, decision)
            _write_json(metadata_path, metadata)
            report_path.write_text(
                report_path.read_text(encoding="utf-8")
                + f"\nIntegrity flag: {APPLEDOUBLE_FLAG}; AppleDouble sidecars were removed before hash refresh.\n",
                encoding="utf-8",
            )

        hash_paths = _all_hash_paths(
            v2_manifest, task_card, monitor_config, script_path,
            decision_path, metadata_path, report_path,
        )
        missing = [str(path) for path in hash_paths if not path.is_file()]
        if missing:
            raise RuntimeError(f"missing v3 hash inputs: {missing}")
        _write_json(OUT / "artifact_hashes.json", {
            "schema_version": "resetp.artifact-hashes.s5-v3",
            "algorithm": "sha256",
            "source_manifest_v2": "artifact_hashes_v2.json",
            "appledouble_excluded": True,
            "integrity_flags": flags,
            "files": {
                str(path.relative_to(ROOT)): _sha256(path)
                for path in hash_paths
                if path.is_file() and not path.name.startswith("._")
            },
        })
        _write_json(done_path, {
            "decision": "PASS_S5_ARTIFACTS",
            "revision": "S5-REV-V3",
            "artifact_hashes": "artifact_hashes.json",
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        _write_json(decision_path, {
            "schema_version": "resetp.e2-final-campaign.s5-artifacts.v3",
            "decision": "HALT_S5_V3_INPUT_OR_RENDER_GATE",
            "revision": "S5-REV-V3",
            "error_type": type(exc).__name__,
            "error": str(exc),
        })
        print(f"[S5 v3] HALT_S5_V3_INPUT_OR_RENDER_GATE: {exc}", file=sys.stderr, flush=True)
        return 2
    print("[S5 v3] PASS_S5_ARTIFACTS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
