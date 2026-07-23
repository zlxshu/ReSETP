#!/usr/bin/env python3
"""Materialize corrected D6 S5 tables and figures without running search."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from scipy.stats import wilcoxon  # noqa: E402


REPO = Path(__file__).resolve().parents[3]
CAMPAIGN = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v2_20260723"
)
FULL = CAMPAIGN / "full_gate"
S3 = CAMPAIGN / "representative_gate"
TRAJ = S3 / "trajectories"
S4 = CAMPAIGN / "table4_gate"
PUBLIC_REPLAY = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_20260723/"
    "public_p1_no_search_replay"
)
FULL_REPLAY = CAMPAIGN / "full_witness_replay"
P1 = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "mv_hgs_sp_final/p1_formal_gate"
)
RUNTIME = (
    REPO
    / "data/ChinaInstances/"
    "china81_runtime_parameter_authority_v4_20260723"
)
OUT = CAMPAIGN / "artifacts"
ARMS = ("HGS-F", "HGS-E", "HGS-M", "MV-HGS-SP")
REGION_NAME = {"jjj": "京津冀", "prd": "珠三角", "cy": "成渝"}
SCALE_BANDS = {
    "S": {10, 15, 20},
    "M": {25, 50, 75},
    "L": {100, 150, 200},
}
EPS = 1.0e-9


def configure_publication_fonts() -> None:
    plt.rcParams.update(
        {
            "font.family": ["Times New Roman", "Songti SC"],
            "font.size": 8.0,
            "axes.labelsize": 8.0,
            "xtick.labelsize": 7.0,
            "ytick.labelsize": 7.0,
            "legend.fontsize": 7.0,
            "axes.unicode_minus": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write empty CSV")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def require_verdict(path: Path, key: str, expected: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get(key) != expected:
        raise RuntimeError(f"{path}: expected {expected!r}")
    return payload


def public_table() -> list[dict[str, Any]]:
    decision = json.loads((P1 / "decision.json").read_text(encoding="utf-8"))
    p1_rows = read_csv(P1 / "raw_runs.csv")
    output: list[dict[str, Any]] = []
    for source in decision["table5"]:
        instance = source["instance"]
        matching = [row for row in p1_rows if row["instance_id"] == instance]
        bks = float(source["bks"])
        mother_avg = statistics.fmean(
            float(row["mother_cost"]) for row in matching
        )
        hybrid_avg = statistics.fmean(
            float(row["hybrid_cost"]) for row in matching
        )
        output.append(
            {
                "instances": instance,
                "n": int(source["n"]),
                "BKS": f"{bks:.3f}",
                "VCGP_Best_error_pct": f"{float(source['vcgp_error_pct']):.2f}",
                "MDFIHA_Best_error_pct": f"{float(source['mdfiha_error_pct']):.2f}",
                "MDFIHA-ETGA_Best_error_pct": f"{float(source['etga_error_pct']):.2f}",
                "PyVRP-HGS_Best_error_pct": f"{float(source['mother_error_pct']):.2f}",
                "PyVRP-HGS_avg_error_pct": f"{100.0 * (mother_avg - bks) / bks:.2f}",
                "MV-HGS-SP_Best_error_pct": f"{float(source['hybrid_error_pct']):.2f}",
                "MV-HGS-SP_avg_error_pct": f"{100.0 * (hybrid_avg - bks) / bks:.2f}",
            }
        )
    return output


def representative_table() -> list[dict[str, Any]]:
    source = read_csv(S3 / "raw_runs.csv")
    rows: list[dict[str, Any]] = []
    for seed in range(1, 11):
        row: dict[str, Any] = {"seed_or_stat": str(seed)}
        for arm in ARMS:
            match = next(
                item
                for item in source
                if item["arm"] == arm and int(item["seed"]) == seed
            )
            row[f"{arm}_cost_cny"] = float(match["cost"])
            row[f"{arm}_cpu_min"] = float(match["cpu_seconds"]) / 60.0
        rows.append(row)
    for label, reducer in (
        ("Min", min),
        ("Avg", statistics.fmean),
        ("Max", max),
    ):
        row = {"seed_or_stat": label}
        for arm in ARMS:
            arm_rows = [item for item in source if item["arm"] == arm]
            row[f"{arm}_cost_cny"] = reducer(
                float(item["cost"]) for item in arm_rows
            )
            row[f"{arm}_cpu_min"] = reducer(
                float(item["cpu_seconds"]) / 60.0
                for item in arm_rows
            )
        rows.append(row)
    return rows


def _band(tier: int) -> str:
    for label, values in SCALE_BANDS.items():
        if tier in values:
            return label
    raise ValueError(f"unknown China81 tier: {tier}")


def china81_summary(
    full_rows: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_instance: dict[str, list[dict[str, str]]] = {}
    for row in full_rows:
        by_instance.setdefault(row["instance_id"], []).append(row)
    if len(by_instance) != 81:
        raise RuntimeError("corrected full gate must contain 81 instances")
    per_instance: dict[str, dict[str, Any]] = {}
    for instance_id, rows in by_instance.items():
        if len(rows) != 5:
            raise RuntimeError(f"{instance_id}: expected five seeds")
        item: dict[str, Any] = {
            "instance_id": instance_id,
            "region": rows[0]["region"],
            "tier": int(rows[0]["tier"]),
        }
        for arm in ARMS:
            values = [float(row[f"{arm}_cost"]) for row in rows]
            item[f"{arm}_Best"] = min(values)
            item[f"{arm}_avg"] = statistics.fmean(values)
        per_instance[instance_id] = item
    groups: list[tuple[str, str, list[dict[str, Any]]]] = []
    for region in ("jjj", "prd", "cy"):
        for band in ("S", "M", "L"):
            items = [
                row
                for row in per_instance.values()
                if row["region"] == region
                and _band(int(row["tier"])) == band
            ]
            groups.append((region, band, items))
    groups.append(("overall", "All", list(per_instance.values())))
    summary: list[dict[str, Any]] = []
    for region, band, items in groups:
        if (region != "overall" and len(items) != 9) or (
            region == "overall" and len(items) != 81
        ):
            raise RuntimeError(f"bad summary group {region}/{band}")
        row: dict[str, Any] = {
            "region_code": region,
            "region": REGION_NAME.get(region, "总体"),
            "scale_band": band,
            "tiers": (
                "/".join(
                    str(value)
                    for value in sorted(SCALE_BANDS[band])
                )
                if band in SCALE_BANDS
                else "10--200"
            ),
            "instance_count": len(items),
        }
        for arm in ARMS:
            row[f"{arm}_Best"] = statistics.fmean(
                float(item[f"{arm}_Best"]) for item in items
            )
            row[f"{arm}_avg"] = statistics.fmean(
                float(item[f"{arm}_avg"]) for item in items
            )
            row[f"{arm}_Best_gap_to_MV_pct"] = statistics.fmean(
                100.0
                * (
                    float(item[f"{arm}_Best"])
                    - float(item["MV-HGS-SP_Best"])
                )
                / float(item["MV-HGS-SP_Best"])
                for item in items
            )
            row[f"{arm}_avg_gap_to_MV_pct"] = statistics.fmean(
                100.0
                * (
                    float(item[f"{arm}_avg"])
                    - float(item["MV-HGS-SP_avg"])
                )
                / float(item["MV-HGS-SP_avg"])
                for item in items
            )
        summary.append(row)
    paired: list[dict[str, Any]] = []
    for arm in ARMS[:-1]:
        run_differences = [
            float(row[f"{arm}_cost"])
            - float(row["MV-HGS-SP_cost"])
            for row in full_rows
        ]
        run_wins = sum(value > EPS for value in run_differences)
        run_losses = sum(value < -EPS for value in run_differences)
        paired.append(
            {
                "analysis_scope": "instance_seed_descriptive",
                "comparison": f"MV-HGS-SP_vs_{arm}",
                "paired_units": len(run_differences),
                "wins": run_wins,
                "ties": (
                    len(run_differences)
                    - run_wins
                    - run_losses
                ),
                "losses": run_losses,
                "wilcoxon_statistic": "",
                "one_sided_p_value": "",
                "holm_adjusted_p_value": "",
                "inferential_role": "descriptive_only",
            }
        )
        instance_differences = [
            float(item[f"{arm}_avg"])
            - float(item["MV-HGS-SP_avg"])
            for item in per_instance.values()
        ]
        cell_differences = [
            statistics.fmean(
                float(item[f"{arm}_avg"])
                - float(item["MV-HGS-SP_avg"])
                for item in per_instance.values()
                if item["region"] == region
                and int(item["tier"]) == tier
            )
            for region in ("jjj", "prd", "cy")
            for tier in sorted(
                value
                for values in SCALE_BANDS.values()
                for value in values
            )
        ]
        for scope, differences, role in (
            (
                "instance_five_seed_mean_primary",
                instance_differences,
                "primary",
            ),
            (
                "region_size_cell_sensitivity",
                cell_differences,
                "sensitivity",
            ),
        ):
            wins = sum(value > EPS for value in differences)
            losses = sum(value < -EPS for value in differences)
            nonzero = [
                value
                for value in differences
                if abs(value) > EPS
            ]
            if nonzero:
                test = wilcoxon(
                    nonzero,
                    alternative="greater",
                    zero_method="wilcox",
                    method="auto",
                )
                statistic = float(test.statistic)
                p_value = float(test.pvalue)
            else:
                statistic = 0.0
                p_value = 1.0
            paired.append(
                {
                    "analysis_scope": scope,
                    "comparison": f"MV-HGS-SP_vs_{arm}",
                    "paired_units": len(differences),
                    "wins": wins,
                    "ties": len(differences) - wins - losses,
                    "losses": losses,
                    "wilcoxon_statistic": statistic,
                    "one_sided_p_value": p_value,
                    "holm_adjusted_p_value": "",
                    "inferential_role": role,
                }
            )
    for scope in (
        "instance_five_seed_mean_primary",
        "region_size_cell_sensitivity",
    ):
        indices = [
            index
            for index, row in enumerate(paired)
            if row["analysis_scope"] == scope
        ]
        ordered = sorted(
            indices,
            key=lambda index: float(
                paired[index]["one_sided_p_value"]
            ),
        )
        running = 0.0
        for rank, index in enumerate(ordered):
            candidate = min(
                1.0,
                (len(ordered) - rank)
                * float(paired[index]["one_sided_p_value"]),
            )
            running = max(running, candidate)
            paired[index]["holm_adjusted_p_value"] = running
    return summary, paired


def plot_carbon() -> dict[str, Any]:
    rows = [
        row
        for row in read_csv(RUNTIME / "tariff_carbon_48slot_calendar.csv")
        if row["date"] == "2025-02-12"
    ]
    selections = (
        ("beijing", "京津冀", "#3B6FB6", "-"),
        ("guangzhou", "珠三角", "#D97904", "--"),
        ("chongqing", "成渝", "#2B8C5A", "-."),
    )
    curve_rows: list[dict[str, Any]] = []
    fig, ax = plt.subplots(figsize=(4.3, 2.8))
    for city, label, color, style in selections:
        city_rows = sorted(
            (row for row in rows if row["city"] == city),
            key=lambda row: int(row["half_hour_slot"]),
        )
        if len(city_rows) != 48:
            raise RuntimeError(f"{city}: expected 48 slots")
        x = [float(row["minute_of_day"]) / 60.0 for row in city_rows]
        y = [
            1000.0 * float(row["carbon_factor_kgco2e_per_kwh"])
            for row in city_rows
        ]
        ax.plot(x, y, color=color, linestyle=style, linewidth=1.0, label=label)
        curve_rows.extend(
            {
                "region_label": label,
                "representative_city": city,
                "scenario_date": row["date"],
                "half_hour_slot": int(row["half_hour_slot"]),
                "time_h": float(row["minute_of_day"]) / 60.0,
                "carbon_intensity_gco2_per_kwh": 1000.0
                * float(row["carbon_factor_kgco2e_per_kwh"]),
                "carbon_source_column": row["carbon_source_column"],
            }
            for row in city_rows
        )
    ax.set_xlabel("时刻(h)", fontsize=8)
    ax.set_ylabel(r"碳强度(gCO$_2$/kWh)", fontsize=8)
    ax.tick_params(labelsize=7, direction="in")
    ax.legend(
        loc="lower left",
        fontsize=6.5,
        frameon=False,
        handlelength=2.2,
        labelspacing=0.25,
    )
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_linewidth(0.7)
    ax.margins(x=0.02, y=0.06)
    fig.tight_layout(pad=0.5)
    fig.savefig(OUT / "figure3_carbon_profile.pdf")
    fig.savefig(OUT / "figure3_carbon_profile.png", dpi=300)
    plt.close(fig)
    write_csv(OUT / "figure3_carbon_profile.csv", curve_rows)
    return {
        "rows": len(curve_rows),
        "scenario_date": "2025-02-12",
        "representative_city_by_region": {
            label: city for city, label, _, _ in selections
        },
    }


def plot_convergence() -> dict[str, Any]:
    rows = read_csv(TRAJ / "curve_data.csv")
    styles = {
        "HGS-F": ("#333333", "-", "o", 0.85, 2),
        "HGS-E": ("#D97904", "--", "s", 0.85, 2),
        "HGS-M": ("#1559A6", (0, (3, 1, 1, 1)), "^", 0.95, 3),
        "MV-HGS-SP": ("#B3261E", "-.", "D", 1.15, 4),
    }
    fig, ax = plt.subplots(figsize=(4.3, 2.8))
    for arm in ARMS:
        arm_rows = sorted(
            (row for row in rows if row["algorithm"] == arm),
            key=lambda row: int(row["point_order"]),
        )
        if len(arm_rows) < 2:
            raise RuntimeError(f"{arm}: insufficient curve points")
        x = [float(row["elapsed_minutes"]) for row in arm_rows]
        y = [float(row["cost_cny"]) for row in arm_rows]
        color, style, marker, width, zorder = styles[arm]
        marker_every = max(1, len(x) // 6)
        ax.step(
            x,
            y,
            where="post",
            color=color,
            linestyle=style,
            linewidth=width,
            marker=marker,
            markevery=marker_every,
            markersize=2.4,
            label=arm,
            zorder=zorder,
        )
    ax.set_xlabel("时间(min)", fontsize=8)
    ax.set_ylabel("成本(元)", fontsize=8)
    ax.tick_params(labelsize=7, direction="in")
    ax.legend(
        loc="upper right",
        fontsize=6.3,
        frameon=False,
        handlelength=2.5,
        labelspacing=0.25,
    )
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_linewidth(0.7)
    ax.margins(x=0.025, y=0.06)
    fig.tight_layout(pad=0.5)
    fig.savefig(OUT / "figure4_convergence.pdf")
    fig.savefig(OUT / "figure4_convergence.png", dpi=300)
    plt.close(fig)
    write_csv(
        OUT / "figure4_convergence.csv",
        [
            {
                "algorithm": row["algorithm"],
                "selected_seed": int(row["selected_seed"]),
                "point_order": int(row["point_order"]),
                "time_min": float(row["elapsed_minutes"]),
                "cost_cny": float(row["cost_cny"]),
                "source": row["source"],
            }
            for row in rows
        ],
    )
    return {
        "rows": len(rows),
        "algorithms": sorted({row["algorithm"] for row in rows}),
        "broken_axis": False,
        "x_axis": "时间(min)",
        "y_axis": "成本(元)",
    }


def tex_table_representative(rows: list[dict[str, Any]]) -> str:
    lines = [
        r"\begin{tabular}{c*{8}{r}}",
        r"\toprule",
        r"\multirow{2}{*}{序号} & \multicolumn{2}{c}{HGS-F} & \multicolumn{2}{c}{HGS-E} & \multicolumn{2}{c}{HGS-M} & \multicolumn{2}{c}{MV-HGS-SP}\\",
        r"\cmidrule(lr){2-3}\cmidrule(lr){4-5}\cmidrule(lr){6-7}\cmidrule(lr){8-9}",
        r" & 值 & CPU & 值 & CPU & 值 & CPU & 值 & CPU\\",
        r"\midrule",
    ]
    for row in rows:
        cells = [str(row["seed_or_stat"])]
        for arm in ARMS:
            cells.extend(
                [
                    f"{float(row[f'{arm}_cost_cny']):.2f}",
                    f"{float(row[f'{arm}_cpu_min']):.2f}",
                ]
            )
        lines.append(" & ".join(cells) + r"\\")
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    return "\n".join(lines) + "\n"


def tex_table_summary(rows: list[dict[str, Any]]) -> str:
    lines = [
        r"\begin{tabular}{ccc*{8}{r}}",
        r"\toprule",
        r"\multirow{2}{*}{城市群} & \multirow{2}{*}{规模层} & \multirow{2}{*}{算例数} & \multicolumn{2}{c}{HGS-F} & \multicolumn{2}{c}{HGS-E} & \multicolumn{2}{c}{HGS-M} & \multicolumn{2}{c}{MV-HGS-SP}\\",
        r"\cmidrule(lr){4-5}\cmidrule(lr){6-7}\cmidrule(lr){8-9}\cmidrule(lr){10-11}",
        r" & & & Best. & avg. & Best. & avg. & Best. & avg. & Best. & avg.\\",
        r"\midrule",
    ]
    for row in rows:
        cells = [
            str(row["region"]),
            str(row["scale_band"]),
            str(row["instance_count"]),
        ]
        for arm in ARMS:
            cells.extend(
                [
                    f"{float(row[f'{arm}_Best']):.2f}",
                    f"{float(row[f'{arm}_avg']):.2f}",
                ]
            )
        lines.append(" & ".join(cells) + r"\\")
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    return "\n".join(lines) + "\n"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    configure_publication_fonts()
    require_verdict(
        FULL / "decision.json",
        "verdict",
        "PASS_D6_CORRECTED_CHINA81_E2_RAW",
    )
    require_verdict(
        S3 / "decision.json",
        "verdict",
        "PASS_D6_CORRECTED_S3_REPRESENTATIVE",
    )
    require_verdict(
        TRAJ / "decision.json",
        "verdict",
        "PASS_D6_CORRECTED_S3_TRAJECTORIES",
    )
    require_verdict(
        S4 / "decision.json",
        "verdict",
        "PASS_D6_CORRECTED_S4_ROUTE_DETAIL",
    )
    require_verdict(
        PUBLIC_REPLAY / "decision.json",
        "verdict",
        "PASS_PUBLIC_P1_PRESERVATION_NO_SEARCH",
    )
    full_replay_decision = require_verdict(
        FULL_REPLAY / "decision.json",
        "verdict",
        "PASS_D6_CORRECTED_FULL_WITNESS_REPLAY",
    )
    if (
        full_replay_decision.get(
            "all_static_charge_day_offsets_zero"
        )
        is not True
        or full_replay_decision.get(
            "all_static_charging_within_registered_day"
        )
        is not True
        or full_replay_decision.get(
            "all_depot_charging_finishes_before_departure"
        )
        is not True
    ):
        raise RuntimeError(
            "corrected full replay did not close the 2025-02-12 day boundary"
        )
    require_verdict(
        RUNTIME / "decision.json",
        "verdict",
        "PASS_CITY_DATE_SLOT_PARAMETER_AUTHORITY",
    )
    full_rows = read_csv(FULL / "raw_runs.csv")
    if len(full_rows) != 405:
        raise RuntimeError("corrected full raw must contain 405 rows")
    table5 = public_table()
    table8a = representative_table()
    summary, paired = china81_summary(full_rows)
    table4 = read_csv(S4 / "route_details.csv")
    write_csv(OUT / "table5_public.csv", table5)
    write_csv(OUT / "table8a_representative.csv", table8a)
    write_csv(OUT / "table8b_china81_summary.csv", summary)
    write_csv(OUT / "china81_pairwise_tests.csv", paired)
    write_csv(OUT / "table4_route_details.csv", table4)
    (OUT / "table8a_representative.tex").write_text(
        tex_table_representative(table8a),
        encoding="utf-8",
    )
    (OUT / "table8b_china81_summary.tex").write_text(
        tex_table_summary(summary),
        encoding="utf-8",
    )
    figure3 = plot_carbon()
    figure4 = plot_convergence()
    decision = {
        "schema": "resetp.d6-corrected-s5.decision.v1",
        "verdict": "PASS_D6_CORRECTED_S5_ARTIFACTS",
        "solver_executions": 0,
        "public_p1_preserved": True,
        "private_china81_source_rows": len(full_rows),
        "representative_rows": len(table8a),
        "china81_summary_rows": len(summary),
        "route_detail_rows": len(table4),
        "paired_test_rows": len(paired),
        "paired_inference_units": {
            "descriptive": "405 instance-seed runs",
            "primary": "81 instance-level five-seed means",
            "sensitivity": "27 region-size cell means",
        },
        "figure3": figure3,
        "figure4": figure4,
        "claim_boundary": (
            "deterministic materialization from corrected sealed gates; "
            "does not modify raw scores or main TeX"
        ),
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.d6-corrected-s5.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in (
                    FULL / "raw_runs.csv",
                    FULL / "decision.json",
                    S3 / "raw_runs.csv",
                    S3 / "decision.json",
                    TRAJ / "curve_data.csv",
                    TRAJ / "decision.json",
                    S4 / "route_details.csv",
                    S4 / "decision.json",
                    P1 / "raw_runs.csv",
                    P1 / "decision.json",
                    FULL_REPLAY / "raw_runs.csv",
                    FULL_REPLAY / "decision.json",
                    RUNTIME / "tariff_carbon_48slot_calendar.csv",
                    RUNTIME / "decision.json",
                    RUNTIME / "artifact_hashes.json",
                    Path(__file__).resolve(),
                )
            },
            "figure_style": {
                "grid": False,
                "four_spines": True,
                "broken_axis": False,
                "figure_inches": [4.3, 2.8],
                "figure4_axes": ["时间(min)", "成本(元)"],
            },
        },
    )
    (OUT / "report.md").write_text(
        "# D6 corrected S5 artifacts\n\n"
        f"Decision: `{decision['verdict']}`.\n\n"
        "All private tables and Figure 4 are derived from the corrected D6 "
        "full/S3/S4 ledgers. Figure 3 reads the same city-date-slot runtime "
        "authority used by scoring. Public Table 5 is reconstructed from the "
        "sealed P1 ledger after its no-search integrity replay. No solver, "
        "raw score, evaluator or main TeX was changed in S5. The 405 "
        "instance-seed outcomes are descriptive; Wilcoxon-Holm inference "
        "uses 81 five-seed instance means, with 27 region-size cell means "
        "reported as a sensitivity analysis.\n",
        encoding="utf-8",
    )
    for path in OUT.rglob("._*"):
        if path.is_file():
            path.unlink()
    artifacts = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": ["artifact_hashes.json", "._*", "*.tmp"],
            "artifacts": artifacts,
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
