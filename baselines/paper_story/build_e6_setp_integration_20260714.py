#!/usr/bin/env python3
"""Build the SETP-facing E6 figure from audited formal evidence only."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np
import pandas as pd
from fontTools.ttLib import TTCollection


ROOT = Path(__file__).resolve().parents[2]
FORMAL = ROOT / "baselines/e6_fairness/e6_participation_formal_20260714"
AUDITED = ROOT / "baselines/e6_fairness/e6_participation_audit_20260714"
MAIN = ROOT / "docs/paper_submission_final"
MAIN_FIG = MAIN / "generated_figures"
OUT = MAIN / "e6_integration_20260714"
FIG = OUT / "figures"
AUDIT = OUT / "audit"

CONDITION_LABELS = {
    "geographic": "地理聚集",
    "mixed": "空间交错",
}


def configure() -> None:
    """Match the manuscript-wide SETP visual contract."""
    songti_ttc = Path("/System/Library/Fonts/Supplemental/Songti.ttc")
    songti_regular = Path(tempfile.gettempdir()) / "resetp-songti-sc-regular.ttf"
    if songti_ttc.exists() and not songti_regular.exists():
        TTCollection(songti_ttc).fonts[6].save(songti_regular)
    if songti_regular.exists():
        font_manager.fontManager.addfont(songti_regular)
    plt.rcParams.update({
        "font.family": ["Times New Roman", "Songti SC"],
        "font.size": 6.62,
        "axes.labelsize": 6.62,
        "xtick.labelsize": 6.62,
        "ytick.labelsize": 6.62,
        "legend.fontsize": 6.1,
        "axes.unicode_minus": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })


def load_and_validate() -> tuple[pd.DataFrame, dict]:
    """Read audited network statistics and independently check their paper metric."""
    formal_decision = json.loads((FORMAL / "decision.json").read_text(encoding="utf-8"))
    audit_decision = json.loads((AUDITED / "decision.json").read_text(encoding="utf-8"))
    if formal_decision.get("status") != "FORMAL_COMPLETE":
        raise RuntimeError("E6 formal matrix is not complete")
    if audit_decision.get("status") != "PASS":
        raise RuntimeError("E6 independent audit did not pass")
    if formal_decision["contract_sha256"] != audit_decision["contract_sha256"]:
        raise RuntimeError("formal and audit contracts differ")

    raw = pd.read_csv(FORMAL / "paired_results.csv")
    raw["paper_participation_premium_pct"] = (
        100.0
        * (raw["no_loss_total_cost"] - raw["unrestricted_total_cost"])
        / raw["unrestricted_total_cost"]
    )
    recomputed = (
        raw.groupby(["instance", "condition"], as_index=False)
        .agg(
            seed_count=("seed", "nunique"),
            mean_participation_premium_vs_unrestricted_pct=(
                "paper_participation_premium_pct", "mean"
            ),
        )
    )
    audited = pd.read_csv(AUDITED / "network_summary.csv")
    merged = audited.merge(
        recomputed,
        on=["instance", "condition"],
        suffixes=("_audit", "_recomputed"),
        validate="one_to_one",
    )
    error = np.abs(
        merged["mean_participation_premium_vs_unrestricted_pct_audit"]
        - merged["mean_participation_premium_vs_unrestricted_pct_recomputed"]
    )
    if len(merged) != 18 or int(merged["seed_count_recomputed"].min()) != 3:
        raise RuntimeError("expected 18 network-condition rows with three seeds each")
    if float(error.max()) > 1e-10:
        raise RuntimeError(f"audited paper metric mismatch: {error.max():.3e}")

    # The formal preflight stores customer counts by depot. Summing the two
    # entries gives the plotted network size without borrowing another result set.
    assets = pd.read_csv(FORMAL / "asset_preflight.csv")
    counts = (
        assets.groupby(["instance", "condition", "ownership_sha256"], as_index=False)
        .agg(customer_count=("customer_count", "sum"), depot_count=("depot_id", "nunique"))
    )
    if not (counts["depot_count"] == 2).all():
        raise RuntimeError("each E6 network-condition must contain exactly two depots")
    count_check = counts.groupby("instance")["customer_count"].nunique()
    if not (count_check == 1).all():
        raise RuntimeError("customer count differs between E6 conditions")
    counts = counts[["instance", "condition", "customer_count"]]

    plot_data = merged.merge(
        counts, on=["instance", "condition"], validate="one_to_one"
    )[[
        "instance",
        "customer_count",
        "condition",
        "mean_participation_premium_vs_unrestricted_pct_audit",
        "mean_saving_with_participation_vs_independent_pct",
    ]].rename(columns={
        "mean_participation_premium_vs_unrestricted_pct_audit":
            "mean_participation_premium_pct",
    })
    plot_data = plot_data.sort_values(["customer_count", "condition"]).reset_index(drop=True)

    summary = {
        "contract_sha256": audit_decision["contract_sha256"],
        "paper_metric_definition": audit_decision["paper_metric_definition"],
        "conditions": audit_decision["condition_summary"],
        "max_network_metric_recomputation_error": float(error.max()),
        "network_condition_rows": int(len(plot_data)),
        "seeds_per_network_condition": 3,
    }
    return plot_data, summary


def plot_participation_premium(data: pd.DataFrame) -> None:
    """One story only: the system-cost increment of the participation floor."""
    pivot = data.pivot(
        index="customer_count", columns="condition", values="mean_participation_premium_pct"
    ).sort_index()
    x = np.arange(len(pivot))
    width = 0.34
    fig, ax = plt.subplots(figsize=(3.65, 2.30))

    # Whole-figure grammar follows the manuscript's Chen et al. grouped bars:
    # restrained grayscale, thin outlines, hatching, no grid and an in-panel legend.
    geographic_bars = ax.bar(
        x - width / 2,
        pivot["geographic"],
        width=width,
        color="white",
        edgecolor="#262626",
        linewidth=0.35,
        hatch="////",
        label=CONDITION_LABELS["geographic"],
    )
    mixed_bars = ax.bar(
        x + width / 2,
        pivot["mixed"],
        width=width,
        color="#BFBFBF",
        edgecolor="#262626",
        linewidth=0.35,
        hatch="....",
        label=CONDITION_LABELS["mixed"],
    )
    ax.axhline(0, color="black", linewidth=0.45)
    for bars in (geographic_bars, mixed_bars):
        for bar in bars:
            if abs(float(bar.get_height())) <= 1e-12:
                ax.text(
                    float(bar.get_x() + bar.get_width() / 2),
                    0.08,
                    "0",
                    ha="center",
                    va="bottom",
                    fontsize=5.5,
                )
    ax.set_xticks(x, [str(int(value)) for value in pivot.index])
    ax.set_xlabel("客户数")
    ax.set_ylabel("系统成本增幅/%")
    ax.set_ylim(0, max(8.6, float(pivot.to_numpy().max()) * 1.10))
    legend = ax.legend(
        loc="upper right",
        ncol=1,
        frameon=True,
        fancybox=False,
        edgecolor="#262626",
        framealpha=1.0,
        borderpad=0.20,
        labelspacing=0.18,
        handlelength=1.15,
        handletextpad=0.35,
    )
    legend.get_frame().set_linewidth(0.35)
    ax.tick_params(direction="out", length=2.0, width=0.468)
    for spine in ax.spines.values():
        spine.set_linewidth(0.468)
    fig.subplots_adjust(left=0.15, right=0.98, bottom=0.19, top=0.97)

    for folder in (FIG, MAIN_FIG):
        folder.mkdir(parents=True, exist_ok=True)
        fig.savefig(folder / "e6_participation_cost.pdf", bbox_inches="tight")
        fig.savefig(folder / "e6_participation_cost.png", dpi=450, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    configure()
    data, summary = load_and_validate()
    AUDIT.mkdir(parents=True, exist_ok=True)
    data.to_csv(AUDIT / "e6_paper_network_metrics.csv", index=False)
    (AUDIT / "e6_paper_values.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    plot_participation_premium(data)
    print(f"built audited E6 paper exhibit in {OUT}")


if __name__ == "__main__":
    main()
