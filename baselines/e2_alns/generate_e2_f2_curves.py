#!/usr/bin/env python3
"""Generate the approved zero-search E2 F2 convergence figure.

The figure is made only from history_json already stored in the formal 810-row
matrix. It does not run a solver and does not change any experiment result.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


INSTANCES = (
    "L-main-threeshift-25c-01",
    "L-main-threeshift-100c-01",
    "L-main-threeshift-200c-01",
)
ALGORITHMS = (
    "staged_hybrid_carbon_aware",
    "GA",
    "PSO",
    "VNS",
    "ACO",
    "GA-VNS",
    "LNS",
    "GWO",
    "IWD",
)
LABELS = {
    "staged_hybrid_carbon_aware": "Staged ALNS-LNS hybrid",
    "GA": "GA",
    "PSO": "PSO",
    "VNS": "VNS",
    "ACO": "ACO",
    "GA-VNS": "GA-VNS",
    "LNS": "LNS",
    "GWO": "GWO",
    "IWD": "IWD",
}
COLORS = {
    "staged_hybrid_carbon_aware": "#1f4e79",
    "GA": "#b45f06",
    "PSO": "#38761d",
    "VNS": "#674ea7",
    "ACO": "#a61c00",
    "GA-VNS": "#1155cc",
    "LNS": "#666666",
    "GWO": "#e69138",
    "IWD": "#45818e",
}
LINESTYLES = {
    "staged_hybrid_carbon_aware": "-",
    "GA": "--",
    "PSO": "-.",
    "VNS": ":",
    "ACO": (0, (5, 1)),
    "GA-VNS": (0, (3, 1, 1, 1)),
    "LNS": (0, (7, 2)),
    "GWO": (0, (2, 2)),
    "IWD": (0, (6, 1, 1, 1)),
}


def incumbent_at(points: list[dict], grid: np.ndarray) -> np.ndarray:
    """Return a right-continuous incumbent curve on the common eval grid."""
    clean = []
    for point in points:
        try:
            clean.append((int(float(point["eval"])), float(point["best_cost"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not clean:
        raise ValueError("history_json has no usable eval/best_cost points")
    clean.sort()
    evals = np.asarray([item[0] for item in clean], dtype=int)
    costs = np.asarray([item[1] for item in clean], dtype=float)
    # Duplicate eval entries can occur at stage boundaries; retain the best.
    unique: dict[int, float] = {}
    for evaluation, cost in zip(evals, costs):
        unique[evaluation] = min(cost, unique.get(evaluation, float("inf")))
    evals = np.asarray(sorted(unique), dtype=int)
    costs = np.asarray([unique[evaluation] for evaluation in evals], dtype=float)
    positions = np.searchsorted(evals, grid, side="right") - 1
    positions = np.clip(positions, 0, len(costs) - 1)
    return costs[positions]


def load_curves(raw_path: Path, grid: np.ndarray) -> list[dict]:
    with raw_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected = {(instance, algorithm, seed) for instance in INSTANCES for algorithm in ALGORITHMS for seed in range(1, 11)}
    observed = {(row["instance"], row["algorithm"], int(float(row["seed"]))) for row in rows}
    missing = sorted(expected - observed)
    if missing:
        raise RuntimeError(f"F2 source matrix is incomplete; missing {missing[:3]} and {len(missing) - min(3, len(missing))} more")

    values: list[dict] = []
    for instance in INSTANCES:
        for algorithm in ALGORITHMS:
            selected = [row for row in rows if row["instance"] == instance and row["algorithm"] == algorithm]
            curves = [incumbent_at(json.loads(row["history_json"]), grid) for row in selected]
            matrix = np.vstack(curves)
            for index, evaluation in enumerate(grid):
                values.append(
                    {
                        "instance": instance,
                        "algorithm": algorithm,
                        "algorithm_label": LABELS[algorithm],
                        "eval": int(evaluation),
                        "seed_count": matrix.shape[0],
                        "mean_best_cost": float(np.mean(matrix[:, index])),
                        "median_best_cost": float(np.median(matrix[:, index])),
                        "q10_best_cost": float(np.quantile(matrix[:, index], 0.10)),
                        "q90_best_cost": float(np.quantile(matrix[:, index], 0.90)),
                    }
                )
    return values


def write_csv(path: Path, values: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(values[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(values)


def draw(values: list[dict], png_path: Path, pdf_path: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(18, 5.4), sharex=True)
    for axis, instance in zip(axes, INSTANCES):
        for algorithm in ALGORITHMS:
            series = [row for row in values if row["instance"] == instance and row["algorithm"] == algorithm]
            x = np.asarray([row["eval"] for row in series])
            mean = np.asarray([row["mean_best_cost"] for row in series])
            q10 = np.asarray([row["q10_best_cost"] for row in series])
            q90 = np.asarray([row["q90_best_cost"] for row in series])
            axis.plot(
                x,
                mean,
                color=COLORS[algorithm],
                linestyle=LINESTYLES[algorithm],
                linewidth=2.0 if algorithm == "staged_hybrid_carbon_aware" else 1.35,
                label=LABELS[algorithm],
            )
            axis.fill_between(x, q10, q90, color=COLORS[algorithm], alpha=0.055, linewidth=0)
        size = instance.split("-")[-2]
        axis.set_title(f"{size} instance", fontsize=12, color="#222222")
        axis.set_xlabel("Complete candidate evaluations")
        axis.grid(axis="y", color="#d9d9d9", linewidth=0.7)
        axis.set_xlim(0, 4000)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
    axes[0].set_ylabel("Current best total cost")
    fig.suptitle("E2 convergence by complete evaluation count", fontsize=15, y=1.03)
    fig.text(0.5, 0.985, "Mean across 10 seeds; shaded band = 10th--90th percentile; same start and 4000-evaluation budget", ha="center", fontsize=10, color="#555555")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=5, bbox_to_anchor=(0.5, -0.02), frameon=False)
    fig.tight_layout(rect=(0, 0.08, 1, 0.95))
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=220, bbox_inches="tight")
    fig.savefig(pdf_path, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=Path("baselines/e2_alns/e2_final_10seed_20260711/formal/raw_runs.csv"))
    parser.add_argument("--output", type=Path, default=Path("baselines/e2_alns/e2_final_10seed_20260711/figures"))
    args = parser.parse_args()
    grid = np.arange(0, 4001, 100, dtype=int)
    values = load_curves(args.raw, grid)
    write_csv(args.output / "f2_convergence_curves.csv", values)
    draw(values, args.output / "figure_f2_convergence.png", args.output / "figure_f2_convergence.pdf")
    (args.output / "README.md").write_text(
        "# E2 F2 convergence materials\n\n"
        "Generated only from `formal/raw_runs.csv` history_json; no new solver run.\n"
        "Three representative instances (25c, 100c, 200c) show nine algorithms, with ten-seed means and 10th--90th percentile bands.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
