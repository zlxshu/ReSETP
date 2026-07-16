#!/usr/bin/env python3
"""Build the SETP-facing E4 figure and tables from sealed evidence only."""

from __future__ import annotations

import hashlib
import json
import statistics
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np
import pandas as pd
from fontTools.ttLib import TTCollection


ROOT = Path(__file__).resolve().parents[2]
E4 = ROOT / "baselines/e4_e5/e4_forecast_timing_formal_20260713"
E3 = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713"
CARBON = ROOT / "data/Carbon/时变碳强度/Carbon_Intensity_Data.csv"
MAIN = ROOT / "docs/paper_submission_final"
MAIN_FIG = MAIN / "generated_figures"
MAIN_TAB = MAIN / "generated_tables"
OUT = MAIN / "e4_integration_20260714"
FIG = OUT / "figures"
TAB = OUT / "tables"
AUDIT = OUT / "audit"
REPRESENTATIVE = "L-main-threeshift-75c-01"
SEEDS = (1, 2, 3)

CONDITION_LABELS = {"geographic": "按地理关系划分", "mixed": "空间交错"}
ARM_LABELS = {"ownership_fixed": "固定客户分工", "reassignment_allowed": "允许跨场重分工"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def configure() -> None:
    songti_ttc = Path("/System/Library/Fonts/Supplemental/Songti.ttc")
    songti_regular = Path(tempfile.gettempdir()) / "resetp-songti-sc-regular.ttf"
    if songti_ttc.exists() and not songti_regular.exists():
        TTCollection(songti_ttc).fonts[6].save(songti_regular)
    if songti_regular.exists():
        font_manager.fontManager.addfont(songti_regular)
    plt.rcParams.update({
        "font.family": ["Times New Roman", "Songti SC"],
        # The two manuscript panels are enlarged by roughly 1.13--1.15 at
        # inclusion.  A 7.1 pt source size therefore lands at the journal's
        # required 8 pt final figure text instead of the former 6.9--7.6 pt.
        "font.size": 7.2,
        "axes.labelsize": 7.2,
        "xtick.labelsize": 7.2,
        "ytick.labelsize": 7.2,
        "legend.fontsize": 7.2,
        "axes.unicode_minus": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })


def write_both(relative: str, content: str) -> None:
    for folder in (TAB, MAIN_TAB):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / relative).write_text(content, encoding="utf-8")


def save_figure(fig: plt.Figure, stem: str) -> None:
    for folder in (FIG, MAIN_FIG):
        folder.mkdir(parents=True, exist_ok=True)
        fig.savefig(folder / f"{stem}.pdf", bbox_inches="tight")
        fig.savefig(folder / f"{stem}.png", dpi=450, bbox_inches="tight")
    plt.close(fig)


def parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)


def carbon_source() -> dict[datetime, tuple[float, float]]:
    rows = pd.read_csv(CARBON)
    return {
        parse_utc(row["Datetime (UTC)"]): (
            float(row["Actual Carbon Intensity (gCO2/kWh)"]),
            float(row["Forecast Carbon Intensity (gCO2/kWh)"]),
        )
        for _, row in rows.iterrows()
    }


def day_profile(source: dict[datetime, tuple[float, float]], day: date) -> np.ndarray:
    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return np.asarray([
        source[midnight + timedelta(minutes=30 * (slot + 1))]
        for slot in range(48)
    ], dtype=float)


def select_representative_day(days: list[str]) -> tuple[date, float, float]:
    source = carbon_source()
    ranges: list[tuple[date, float]] = []
    for value in days:
        day = date.fromisoformat(value)
        actual = day_profile(source, day)[:, 0]
        ranges.append((day, float(actual.max() - actual.min())))
    median_range = float(statistics.median(item[1] for item in ranges))
    selected = min(ranges, key=lambda item: (abs(item[1] - median_range), item[0]))
    return selected[0], selected[1], median_range


def add_action(load: np.ndarray, row: pd.Series, power_kw: float) -> None:
    energy = float(row.energy_kwh)
    if energy <= 1e-12:
        return
    start = float(row.charge_start_second) / 3600.0 + 24.0 * int(row.charge_day_offset)
    end = start + energy / power_kw
    if start < -24.0 - 1e-8 or end > 24.0 + 1e-8:
        raise RuntimeError(f"charging action outside display window: {start}..{end}")
    for index in range(96):
        left = -24.0 + 0.5 * index
        right = left + 0.5
        overlap = max(0.0, min(end, right) - max(start, left))
        load[index] += overlap * power_kw


def selected_loads(day: date) -> tuple[np.ndarray, np.ndarray, dict[str, object]]:
    actions = pd.read_csv(E4 / "action_runs.csv")
    selected = actions[
        (actions.instance == REPRESENTATIVE)
        & (actions.condition == "geographic")
        & (actions.arm == "ownership_fixed")
        & (actions.operating_day == day.isoformat())
        & actions.timing_rule.isin(["immediate", "forecast_timed"])
    ]
    expected = {(rule, seed) for rule in ("immediate", "forecast_timed") for seed in SEEDS}
    found = set(zip(selected.timing_rule, selected.seed.astype(int)))
    if found != expected:
        raise RuntimeError(f"incomplete representative groups: {found}")

    certificate = E3 / "certificates" / f"{REPRESENTATIVE}__geographic__seed1__ownership_fixed.json"
    power_kw = float(json.loads(certificate.read_text(encoding="utf-8"))["depot_charge_power_kw"])
    loads: dict[str, list[np.ndarray]] = {"immediate": [], "forecast_timed": []}
    energies: dict[str, list[float]] = {"immediate": [], "forecast_timed": []}
    for rule in loads:
        for seed in SEEDS:
            group = selected[(selected.timing_rule == rule) & (selected.seed == seed)]
            load = np.zeros(96, dtype=float)
            for _, row in group.iterrows():
                add_action(load, row, power_kw)
            action_energy = float(group.energy_kwh.sum())
            if abs(load.sum() - action_energy) > 1e-6:
                raise RuntimeError(f"load reconstruction mismatch: {rule}/seed{seed}")
            loads[rule].append(load)
            energies[rule].append(action_energy)
    immediate = np.mean(np.stack(loads["immediate"]), axis=0)
    forecast = np.mean(np.stack(loads["forecast_timed"]), axis=0)
    if abs(immediate.sum() - forecast.sum()) > 1e-6:
        raise RuntimeError("timing rules deliver different charging energy")
    return immediate, forecast, {
        "depot_power_kw": power_kw,
        "mean_total_energy_kwh": float(immediate.sum()),
        "per_seed_energy_kwh": energies,
    }


def build_figure(days: list[str]) -> dict[str, object]:
    selected_day, selected_range, median_range = select_representative_day(days)
    source = carbon_source()
    profile = np.vstack([
        day_profile(source, selected_day - timedelta(days=1)),
        day_profile(source, selected_day),
    ])
    immediate, forecast, load_meta = selected_loads(selected_day)
    x = np.arange(96) * 0.5 - 23.75
    immediate_emissions = immediate * profile[:, 0] / 1000.0
    forecast_emissions = forecast * profile[:, 0] / 1000.0

    # The three-row grammar follows Cheng et al. (2022), Fig. 6: carbon
    # intensity, realised charging emissions and charging load are aligned on
    # the same time axis.  Solid/dashed encodings remain distinct in grayscale.
    fig, axes = plt.subplots(
        3, 1, figsize=(5.15, 3.92), sharex=True,
        gridspec_kw={"height_ratios": [0.92, 1.0, 1.0], "hspace": 0.13},
    )
    top, middle, bottom = axes
    top.plot(x, profile[:, 0], color="#1F77B4", linewidth=0.72, label="实际碳强度")
    top.plot(x, profile[:, 1], color="#D55E00", linewidth=0.62,
             linestyle=(0, (3.2, 2.0)), label="预测碳强度")
    # Keep the unit outside mathtext so Chinese fallback stays intact in the PDF.
    top.set_ylabel("碳强度/(g CO₂e/kWh)")

    middle.step(x, immediate_emissions, where="mid", color="#1F77B4", linewidth=0.70,
                label="有空即充")
    middle.step(x, forecast_emissions, where="mid", color="#D55E00", linewidth=0.72,
                linestyle=(0, (3.2, 2.0)), label="按预测择时")
    middle.set_ylabel("充电排放/kg CO₂e")

    bottom.step(x, immediate, where="mid", color="#1F77B4", linewidth=0.70,
                label="有空即充")
    bottom.step(x, forecast, where="mid", color="#D55E00", linewidth=0.72,
                linestyle=(0, (3.2, 2.0)),
                label="按预测择时")
    bottom.set_ylabel("每半小时充电量/kWh")
    bottom.set_xlabel("相对运营日零点的时间/h")

    for ax in axes:
        ax.axvline(0, color="#555555", linewidth=0.42)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_linewidth(0.468)
        ax.spines["bottom"].set_linewidth(0.468)
        ax.tick_params(width=0.468, length=2.0, pad=1.5)
        ax.legend(loc="upper right", ncol=2, frameon=False, handlelength=2.4,
                  columnspacing=0.9, handletextpad=0.4, borderaxespad=0.35)
        ax.text(-23.2, 0.955, "前一日", ha="left", va="top",
                transform=ax.get_xaxis_transform(), color="#666666")
        ax.text(0.8, 0.955, "运营日", ha="left", va="top",
                transform=ax.get_xaxis_transform(), color="#666666")
    top_min = min(profile[:, 0].min(), profile[:, 1].min())
    top_max = max(profile[:, 0].max(), profile[:, 1].max())
    top.set_ylim(max(0, top_min * 0.80), top_max * 1.10)
    middle.set_ylim(0, max(immediate_emissions.max(), forecast_emissions.max()) * 1.22)
    bottom.set_ylim(0, max(immediate.max(), forecast.max()) * 1.22)
    bottom.set_xlim(-24, 24)
    bottom.set_xticks(np.arange(-24, 25, 6))
    fig.subplots_adjust(left=0.13, right=0.985, top=0.985, bottom=0.13)
    save_figure(fig, "e4_carbon_intensity_charging")
    return {
        "selection_rule": "actual carbon-intensity range closest to the 28-day median; earliest date breaks ties",
        "selected_operating_day": selected_day.isoformat(),
        "selected_day_actual_range_gco2_per_kwh": selected_range,
        "median_actual_range_gco2_per_kwh": median_range,
        **load_meta,
    }


def build_main_table() -> list[dict[str, object]]:
    summary = pd.read_csv(E4 / "aggregate_summary.csv")
    rows: list[dict[str, object]] = []
    lines = [
        r"\begin{tabular*}{0.84\linewidth}{@{\extracolsep{\fill}}llrr@{}}",
        r"\toprule",
        r"客户归属方式 & 经营方式 & 充电排放下降/\% & 运营总排放下降/\% \\",
        r"\midrule",
    ]
    for condition in ("geographic", "mixed"):
        for arm in ("ownership_fixed", "reassignment_allowed"):
            row = summary[(summary.condition == condition) & (summary.arm == arm)].iloc[0]
            lines.append(
                f"{CONDITION_LABELS[condition]} & {ARM_LABELS[arm]} & "
                f"{row.pooled_charging_reduction_pct:.3f} & "
                f"{row.pooled_total_operational_reduction_pct:.3f} \\\\"
            )
            rows.append({
                "condition": condition,
                "arm": arm,
                "charging_reduction_pct": float(row.pooled_charging_reduction_pct),
                "total_reduction_pct": float(row.pooled_total_operational_reduction_pct),
                "networks_improved": int(row.networks_improved),
                "days_improved": int(row.days_improved),
                "pre_day_share_pct": float(row.pre_day_share_of_positive_total_saving_pct),
            })
    lines += [r"\bottomrule", r"\end{tabular*}"]
    write_both("e4_emissions_summary.tex", "\n".join(lines) + "\n")
    return rows


def build_day_table() -> None:
    day = pd.read_csv(E4 / "day_summary.csv")
    index = day.set_index(["operating_day", "condition", "arm"])
    days = sorted(day.operating_day.unique())
    for suffix, subset in (("a", days[:14]), ("b", days[14:])):
        lines = [
            r"\begin{tabular*}{0.92\linewidth}{@{\extracolsep{\fill}}lrrrr@{}}",
            r"\toprule",
            r"运营日 & \multicolumn{2}{c}{按地理关系划分} & \multicolumn{2}{c}{空间交错} \\",
            r"\cmidrule(lr){2-3}\cmidrule(l){4-5}",
            r" & 固定分工 & 跨场重分工 & 固定分工 & 跨场重分工 \\",
            r"\midrule",
        ]
        for operating_day in subset:
            values = []
            for condition in ("geographic", "mixed"):
                for arm in ("ownership_fixed", "reassignment_allowed"):
                    values.append(float(index.loc[(operating_day, condition, arm), "pooled_charging_reduction_pct"]))
            lines.append(operating_day + " & " + " & ".join(f"{value:.3f}" for value in values) + r" \\")
        lines += [r"\bottomrule", r"\end{tabular*}"]
        write_both(f"e4_day_consistency_{suffix}.tex", "\n".join(lines) + "\n")


def build_day_figure() -> None:
    day = pd.read_csv(E4 / "day_summary.csv")
    dates = sorted(day.operating_day.unique())
    positions = np.arange(len(dates))
    figure, axes = plt.subplots(2, 1, figsize=(5.15, 2.78), sharex=True, sharey=True)
    styles = {
        "ownership_fixed": dict(color="#1F77B4", marker="o", linestyle="-"),
        "reassignment_allowed": dict(color="#D55E00", marker="s", linestyle=(0, (3.2, 2.0))),
    }
    short_labels = {"ownership_fixed": "责任固定", "reassignment_allowed": "跨场重分工"}
    condition_titles = {"geographic": "地理聚集", "mixed": "空间交错"}
    for axis, condition in zip(axes, ("geographic", "mixed")):
        for arm in ("ownership_fixed", "reassignment_allowed"):
            block = (
                day[(day.condition == condition) & (day.arm == arm)]
                .set_index("operating_day")
                .loc[dates]
            )
            axis.plot(
                positions,
                block.pooled_charging_reduction_pct,
                linewidth=0.70,
                markersize=2.5,
                markeredgewidth=0.45,
                label=short_labels[arm],
                **styles[arm],
            )
        axis.axhline(0, color="#555555", linewidth=0.48)
        axis.text(0.012, 0.90, condition_titles[condition], transform=axis.transAxes,
                  ha="left", va="top")
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.spines["left"].set_linewidth(0.468)
        axis.spines["bottom"].set_linewidth(0.468)
        axis.tick_params(width=0.468, length=2.0, pad=1.5)
    axes[0].legend(loc="upper right", ncol=2, frameon=False, handlelength=2.4,
                   columnspacing=0.9, handletextpad=0.4, borderaxespad=0.35)
    axes[0].set_ylabel("充电排放降幅/%")
    axes[1].set_ylabel("充电排放降幅/%")
    axes[1].set_xlabel("运营日")
    tick_positions = [0, 4, 8, 12, 16, 20, 24, len(dates) - 1]
    axes[1].set_xticks(tick_positions)
    axes[1].set_xticklabels([dates[index][5:] for index in tick_positions])
    axes[1].set_xlim(-0.4, len(dates) - 0.6)
    figure.subplots_adjust(left=0.12, right=0.985, top=0.985, bottom=0.18, hspace=0.12)
    save_figure(figure, "e4_day_heterogeneity")


def main() -> None:
    configure()
    metadata = json.loads((E4 / "metadata.json").read_text(encoding="utf-8"))
    figure_meta = build_figure(metadata["operating_days"])
    table_rows = build_main_table()
    build_day_figure()
    build_day_table()
    AUDIT.mkdir(parents=True, exist_ok=True)
    audit = {
        "execution_code_commit": metadata["execution_commit"],
        "evidence_record_commit": "9978517db025d47aa454c49a9cf38b424b4fc6d3",
        "source_hashes": {
            "metadata.json": sha256(E4 / "metadata.json"),
            "aggregate_summary.csv": sha256(E4 / "aggregate_summary.csv"),
            "day_summary.csv": sha256(E4 / "day_summary.csv"),
            "action_runs.csv": sha256(E4 / "action_runs.csv"),
            "carbon_csv": sha256(CARBON),
        },
        "figure": figure_meta,
        "main_table": table_rows,
    }
    (AUDIT / "integration_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
