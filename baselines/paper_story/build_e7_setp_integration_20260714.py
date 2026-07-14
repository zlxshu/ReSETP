#!/usr/bin/env python3
"""Build E7 manuscript tables from sealed, independently audited evidence."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import statistics
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
VALUE = ROOT / "baselines/e7_dynamic/e7_full_day_value_audit_formal_20260714"
EMISSIONS = ROOT / "baselines/e7_dynamic/e7_dynamic_emission_intensity_formal_20260714"
PARTICIPATION = ROOT / "baselines/e7_dynamic/e7_ex_post_participation_formal_20260714"
PAPER = ROOT / "docs/paper_submission_final"
TABLES = PAPER / "generated_tables"
OUT = PAPER / "e7_integration_20260714"
AUDIT = OUT / "audit"
EXPECTED_STREAMS = [1, 2, 3, 4, 5]


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


def validate_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / "artifact_hashes.json"
    manifest = read_json(manifest_path)
    listed = {str(row["path"]): row for row in manifest.get("artifacts", [])}
    actual: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._"):
            actual[str(path.resolve().relative_to(ROOT.resolve()))] = path
    if set(listed) != set(actual):
        raise RuntimeError(f"artifact inventory does not close: {root}")
    for relative, path in actual.items():
        if listed[relative]["sha256"] != sha256(path):
            raise RuntimeError(f"artifact hash differs: {relative}")
        if int(listed[relative]["bytes"]) != path.stat().st_size:
            raise RuntimeError(f"artifact byte count differs: {relative}")
    return {
        "path": str(root.relative_to(ROOT)),
        "manifest_sha256": sha256(manifest_path),
        "artifact_count": len(listed),
    }


def require_streams(rows: list[dict[str, str]], label: str) -> None:
    observed = [int(row["stream_seed"]) for row in rows]
    if observed != EXPECTED_STREAMS:
        raise RuntimeError(f"{label} does not retain streams 1--5 exactly once: {observed}")


def load_evidence() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    value_decision = read_json(VALUE / "decision.json")
    emission_decision = read_json(EMISSIONS / "decision.json")
    participation_decision = read_json(PARTICIPATION / "decision.json")
    if value_decision.get("status") != "PASS":
        raise RuntimeError("E7 full-day value audit did not pass")
    if emission_decision.get("verdict") != "E7_DYNAMIC_EMISSION_INTENSITY_AUDIT_PASS":
        raise RuntimeError("E7 emission-intensity audit did not pass")
    if participation_decision.get("verdict") != "E7_EX_POST_PARTICIPATION_AUDIT_PASS":
        raise RuntimeError("E7 participation audit did not pass")

    value_rows = read_csv(VALUE / "paired_value_summary.csv")
    emission_rows = read_csv(EMISSIONS / "paired_summary.csv")
    participation_rows = read_csv(PARTICIPATION / "paired_summary.csv")
    require_streams(value_rows, "value table")
    require_streams(emission_rows, "emission table")
    require_streams(participation_rows, "participation table")

    values: list[dict[str, Any]] = []
    emissions: list[dict[str, Any]] = []
    participation: list[dict[str, Any]] = []
    for row in value_rows:
        if row["workload_equal"] != "False" or row["cost_change_percent"]:
            raise RuntimeError("E7 value row violates the different-workload reporting rule")
        values.append(
            {
                "stream_seed": int(row["stream_seed"]),
                "net_benefit_change_gbp": float(row["net_benefit_change"]),
                "net_benefit_change_percent": float(row["net_benefit_change_percent"]),
            }
        )
    for row in emission_rows:
        emissions.append(
            {
                "stream_seed": int(row["stream_seed"]),
                "total_emission_intensity_change_percent": float(
                    row["E_total_intensity_change_percent"]
                ),
                "fuel_emission_intensity_change_percent": float(
                    row["E_cv_direct_intensity_change_percent"]
                ),
                "electricity_intensity_change_percent": float(
                    row["electricity_kwh_intensity_change_percent"]
                ),
            }
        )
    for row in participation_rows:
        participation.append(
            {
                "stream_seed": int(row["stream_seed"]),
                "D0_profit_ratio": float(row["D0_profit_ratio"]),
                "D1_profit_ratio": float(row["D1_profit_ratio"]),
                "both_depots_no_worse": row["both_depots_no_worse"] == "True",
            }
        )

    value_mean = statistics.mean(row["net_benefit_change_percent"] for row in values)
    value_median = statistics.median(row["net_benefit_change_percent"] for row in values)
    if abs(value_mean - float(value_decision["paper_summary"]["mean_net_benefit_change_percent"])) > 1e-12:
        raise RuntimeError("E7 value mean differs from the sealed decision")
    if abs(value_median - float(value_decision["paper_summary"]["median_net_benefit_change_percent"])) > 1e-12:
        raise RuntimeError("E7 value median differs from the sealed decision")
    if sum(row["both_depots_no_worse"] for row in participation) != 2:
        raise RuntimeError("E7 participation count differs from the sealed decision")

    summary = {
        "value": value_decision["paper_summary"],
        "emissions": emission_decision,
        "participation": participation_decision,
        "evidence": {
            "value": validate_manifest(VALUE),
            "emissions": validate_manifest(EMISSIONS),
            "participation": validate_manifest(PARTICIPATION),
        },
    }
    return values, emissions, participation, summary


def write_value_table(rows: list[dict[str, Any]]) -> None:
    mean_value = statistics.mean(row["net_benefit_change_percent"] for row in rows)
    lines = [
        r"\begin{tabular}{cc}",
        r"\toprule",
        r"订单变化序列 & 经营净收益相对变化/\% \\",
        r"\midrule",
    ]
    lines.extend(
        f"{row['stream_seed']} & {row['net_benefit_change_percent']:.3f} \\\\"
        for row in rows
    )
    lines.extend(
        [
            r"\midrule",
            f"平均 & {mean_value:.3f} \\\\",
            r"\bottomrule",
            r"\end{tabular}",
            "",
        ]
    )
    (TABLES / "e7_dynamic_value.tex").write_text("\n".join(lines), encoding="utf-8")


def write_emission_table(rows: list[dict[str, Any]]) -> None:
    mean_total = statistics.mean(
        row["total_emission_intensity_change_percent"] for row in rows
    )
    mean_fuel = statistics.mean(
        row["fuel_emission_intensity_change_percent"] for row in rows
    )
    mean_electricity = statistics.mean(
        row["electricity_intensity_change_percent"] for row in rows
    )
    lines = [
        r"\begin{tabular}{cccc}",
        r"\toprule",
        r"订单变化序列 & \makecell[c]{总排放强度\\变化/\%} & \makecell[c]{燃油车直接排放强度\\变化/\%} & \makecell[c]{电动车用电强度\\变化/\%} \\",
        r"\midrule",
    ]
    lines.extend(
        (
            f"{row['stream_seed']} & "
            f"{row['total_emission_intensity_change_percent']:.3f} & "
            f"{row['fuel_emission_intensity_change_percent']:.3f} & "
            f"{row['electricity_intensity_change_percent']:.3f} \\\\"
        )
        for row in rows
    )
    lines.extend(
        [
            r"\midrule",
            f"平均 & {mean_total:.3f} & {mean_fuel:.3f} & {mean_electricity:.3f} \\\\",
            r"\bottomrule",
            r"\end{tabular}",
            "",
        ]
    )
    (TABLES / "e7_dynamic_emissions.tex").write_text("\n".join(lines), encoding="utf-8")


def write_participation_table(rows: list[dict[str, Any]]) -> None:
    lines = [
        r"\begin{tabular}{cccc}",
        r"\toprule",
        r"订单变化序列 & 车场$D_0$收益比 & 车场$D_1$收益比 & 双方均满足参与条件 \\",
        r"\midrule",
    ]
    lines.extend(
        (
            f"{row['stream_seed']} & {row['D0_profit_ratio']:.4f} & "
            f"{row['D1_profit_ratio']:.4f} & "
            f"{'是' if row['both_depots_no_worse'] else '否'} \\\\"
        )
        for row in rows
    )
    lines.extend([r"\bottomrule", r"\end{tabular}", ""])
    (TABLES / "e7_dynamic_participation.tex").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    values, emissions, participation, summary = load_evidence()
    TABLES.mkdir(parents=True, exist_ok=True)
    AUDIT.mkdir(parents=True, exist_ok=True)
    write_value_table(values)
    write_emission_table(emissions)
    write_participation_table(participation)
    write_json = lambda path, payload: path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    write_json(AUDIT / "e7_paper_values.json", summary)
    for name, rows in (
        ("e7_dynamic_value.csv", values),
        ("e7_dynamic_emissions.csv", emissions),
        ("e7_dynamic_participation.csv", participation),
    ):
        with (AUDIT / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(f"built audited E7 manuscript tables in {TABLES}")


if __name__ == "__main__":
    main()
