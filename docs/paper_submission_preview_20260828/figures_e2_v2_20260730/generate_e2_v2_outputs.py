#!/usr/bin/env python3
"""Generate E2 aggregate figures from sealed data only.

This script does not call a solver, re-evaluate a solution, or alter any sealed
artifact. It reads:

1. the 2,025-row O/F/E/M/MV final-cost ledger; and
2. all 405 formal ``trajectory_observations.json`` files from the sealed v7
   campaign.

It then validates the sealed hashes and endpoint identities before producing a
fixed-denominator aggregate convergence curve and a five-arm performance
profile.
"""

from __future__ import annotations

import bisect
import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import PercentFormatter


REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = Path(__file__).resolve().parent

COMPARISON_DIR = (
    REPO_ROOT
    / "baselines/algorithm_prototypes/china81_vs_opensource_20260727"
)
COMPARISON_RAW = COMPARISON_DIR / "raw_runs.json"
COMPARISON_HASHES = COMPARISON_DIR / "artifact_hashes.json"

FINAL_V7_DIR = (
    REPO_ROOT
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v7_small_archive_ledger_20260724"
)
FINAL_GATE_DIR = FINAL_V7_DIR / "full_gate"
FINAL_GATE_HASHES = FINAL_GATE_DIR / "artifact_hashes.json"
TRAJECTORY_ROOT = FINAL_GATE_DIR / "tasks"

EXPECTED_COMPARISON_RAW_SHA256 = (
    "4291ee24707bcf834c6cf6ff6b308a14eab4b4a6a3011681408935e8693e070c"
)
TRAJECTORY_SCHEMA = "resetp.d6-e2-staged-trajectories.v1"
TASK_PREFIX = "D6-E2-STAGED__"

FINAL_ARM_ORDER = ("O", "F", "E", "M", "MV")
TRAJECTORY_ARM_ORDER = ("F", "E", "M", "MV")
ARM_LABELS = {
    "O": "O（纯距离开源）",
    "F": "HGS-F",
    "E": "HGS-E",
    "M": "HGS-M",
    "MV": "MV-HGS-SP",
}
TRAJECTORY_KEYS = {
    "F": "HGS-F",
    "E": "HGS-E",
    "M": "HGS-M",
    "MV": "MV-HGS-SP",
}

STYLES = {
    "O": {
        "color": "#666666",
        "linestyle": (0, (1.2, 2.0)),
        "linewidth": 1.55,
        "zorder": 1,
    },
    "F": {
        "color": "#1F77B4",
        "linestyle": (0, (6, 2)),
        "linewidth": 1.55,
        "zorder": 2,
    },
    "E": {
        "color": "#2CA02C",
        "linestyle": (0, (3, 2)),
        "linewidth": 1.55,
        "zorder": 2,
    },
    "M": {
        "color": "#9467BD",
        "linestyle": (0, (8, 2, 2, 2)),
        "linewidth": 1.55,
        "zorder": 2,
    },
    "MV": {
        "color": "#D62728",
        "linestyle": "-",
        "linewidth": 2.35,
        "zorder": 4,
    },
}

TIME_GRID_STEP_MIN = 0.05
TAU_GRID_STEP = 0.0001
COST_TOL = 1e-9
RATIO_TOL = 1e-12


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def compare_cost(cost_a: float, cost_b: float) -> str:
    """Return W/T/L from lower-is-better algorithm A's perspective."""
    if cost_a < cost_b - COST_TOL:
        return "W"
    if cost_a > cost_b + COST_TOL:
        return "L"
    return "T"


def configure_matplotlib() -> None:
    font_path = Path("/System/Library/Fonts/STHeiti Light.ttc")
    if not font_path.is_file():
        raise FileNotFoundError(f"Required Chinese font not found: {font_path}")
    font_name = mpl.font_manager.FontProperties(fname=font_path).get_name()
    mpl.rcParams.update(
        {
            "font.family": font_name,
            "axes.unicode_minus": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "axes.linewidth": 0.8,
            "xtick.major.width": 0.8,
            "ytick.major.width": 0.8,
        }
    )


def parse_task_identity(path: Path) -> tuple[str, int]:
    task_name = path.parent.name
    if not task_name.startswith(TASK_PREFIX):
        raise AssertionError(f"Unexpected task directory: {task_name}")
    body = task_name[len(TASK_PREFIX) :]
    instance_id, seed_text = body.rsplit("__seed", 1)
    return instance_id, int(seed_text)


def load_and_validate_final_ledger() -> tuple[
    list[dict], dict[tuple[str, int, str], dict]
]:
    comparison_manifest = load_json(COMPARISON_HASHES)
    manifest_hash = comparison_manifest["artifacts"]["raw_runs.json"]
    actual_hash = sha256(COMPARISON_RAW)
    assert manifest_hash == EXPECTED_COMPARISON_RAW_SHA256
    assert actual_hash == EXPECTED_COMPARISON_RAW_SHA256

    rows = load_json(COMPARISON_RAW)
    assert len(rows) == 2025
    assert Counter(row["arm"] for row in rows) == Counter(
        {arm: 405 for arm in FINAL_ARM_ORDER}
    )
    assert len({row["instance_id"] for row in rows}) == 81
    assert {int(row["seed"]) for row in rows} == {1, 2, 3, 4, 5}
    assert all(row["status"] == "PASS" for row in rows)
    assert all(row["feasible"] is True for row in rows)
    assert all(int(row["violation_count"]) == 0 for row in rows)

    index: dict[tuple[str, int, str], dict] = {}
    for row in rows:
        key = (row["instance_id"], int(row["seed"]), row["arm"])
        assert key not in index
        index[key] = row
    assert len(index) == 2025
    return rows, index


def validate_trajectory_manifest() -> list[Path]:
    manifest = load_json(FINAL_GATE_HASHES)
    registered = {
        key: value
        for key, value in manifest["artifacts"].items()
        if key.endswith("trajectory_observations.json")
    }
    actual_files = sorted(TRAJECTORY_ROOT.glob("*/trajectory_observations.json"))
    actual_relatives = {
        path.relative_to(FINAL_GATE_DIR).as_posix() for path in actual_files
    }
    assert len(actual_files) == 405
    assert len(registered) == 405
    assert actual_relatives == set(registered)
    for path in actual_files:
        relative = path.relative_to(FINAL_GATE_DIR).as_posix()
        assert sha256(path) == registered[relative]
    return actual_files


def load_and_validate_trajectories(
    files: list[Path],
    final_index: dict[tuple[str, int, str], dict],
) -> tuple[dict, dict]:
    """Return normalized step trajectories and integrity metrics."""
    curves: dict[
        str, dict[tuple[str, int], dict[str, list[float] | float]]
    ] = {arm: {} for arm in TRAJECTORY_ARM_ORDER}
    point_counts: dict[str, Counter] = {
        arm: Counter() for arm in TRAJECTORY_ARM_ORDER
    }
    first_times: dict[str, list[float]] = defaultdict(list)
    end_times: dict[str, list[float]] = defaultdict(list)
    unit_references: dict[tuple[str, int], float] = {}
    initial_objectives: list[float] = []
    endpoint_matches = 0
    minimum_matches = 0
    reference_equals_mv_final = 0
    total_observed_points = 0
    units: set[tuple[str, int]] = set()

    for path in files:
        unit = parse_task_identity(path)
        assert unit not in units
        units.add(unit)
        data = load_json(path)
        assert data["schema"] == TRAJECTORY_SCHEMA
        assert set(data["curves"]) == set(TRAJECTORY_KEYS.values())
        initial_objective = float(data["initial_objective"])
        assert math.isfinite(initial_objective) and initial_objective > 0
        initial_objectives.append(initial_objective)

        observed_costs = [initial_objective]
        for arm in TRAJECTORY_ARM_ORDER:
            points = data["curves"][TRAJECTORY_KEYS[arm]]
            assert points
            observed_costs.extend(float(point["objective"]) for point in points)
        reference = min(observed_costs)
        unit_references[unit] = reference

        mv_final = float(final_index[unit + ("MV",)]["final_cost"])
        assert math.isclose(reference, mv_final, rel_tol=0.0, abs_tol=COST_TOL)
        reference_equals_mv_final += 1

        for arm in TRAJECTORY_ARM_ORDER:
            points = data["curves"][TRAJECTORY_KEYS[arm]]
            total_observed_points += len(points)
            point_counts[arm][len(points)] += 1

            elapsed_minutes = [0.0]
            observed = [initial_objective]
            previous_seconds = -math.inf
            for point in points:
                elapsed_seconds = float(point["elapsed_seconds"])
                objective = float(point["objective"])
                assert math.isfinite(elapsed_seconds) and elapsed_seconds >= 0
                assert math.isfinite(objective) and objective > 0
                assert elapsed_seconds >= previous_seconds
                previous_seconds = elapsed_seconds
                elapsed_minutes.append(elapsed_seconds / 60.0)
                observed.append(objective)

            sealed_final = float(final_index[unit + (arm,)]["final_cost"])
            assert math.isclose(
                observed[-1], sealed_final, rel_tol=0.0, abs_tol=COST_TOL
            )
            endpoint_matches += 1
            assert math.isclose(
                min(observed), sealed_final, rel_tol=0.0, abs_tol=COST_TOL
            )
            minimum_matches += 1

            best_costs: list[float] = []
            best = math.inf
            for objective in observed:
                best = min(best, objective)
                best_costs.append(best)
            normalized_gaps = [
                100.0 * (cost / reference - 1.0) for cost in best_costs
            ]

            first_times[arm].append(elapsed_minutes[1])
            end_times[arm].append(elapsed_minutes[-1])
            curves[arm][unit] = {
                "times_min": elapsed_minutes,
                "gaps_pct": normalized_gaps,
                "end_min": elapsed_minutes[-1],
            }

    assert len(units) == 405
    assert all(len(curves[arm]) == 405 for arm in TRAJECTORY_ARM_ORDER)
    assert endpoint_matches == 1620
    assert minimum_matches == 1620
    assert reference_equals_mv_final == 405

    integrity = {
        "trajectory_file_count": len(files),
        "trajectory_unit_count": len(units),
        "trajectory_observed_point_count": total_observed_points,
        "trajectory_endpoint_matches_final_ledger": endpoint_matches,
        "trajectory_minimum_matches_final_ledger": minimum_matches,
        "normalization_reference_equals_mv_final_count": reference_equals_mv_final,
        "point_count_distribution_by_arm": {
            arm: {str(count): frequency for count, frequency in sorted(counter.items())}
            for arm, counter in point_counts.items()
        },
        "first_observation_seconds_by_arm": {
            arm: {
                "minimum": min(values) * 60.0,
                "median": statistics.median(values) * 60.0,
                "maximum": max(values) * 60.0,
            }
            for arm, values in first_times.items()
        },
        "trajectory_end_minutes_by_arm": {
            arm: {
                "minimum": min(values),
                "median": statistics.median(values),
                "maximum": max(values),
            }
            for arm, values in end_times.items()
        },
        "initial_objective": {
            "minimum": min(initial_objectives),
            "median": statistics.median(initial_objectives),
            "maximum": max(initial_objectives),
        },
        "normalization_reference": {
            "minimum": min(unit_references.values()),
            "median": statistics.median(unit_references.values()),
            "maximum": max(unit_references.values()),
        },
    }
    return curves, integrity


def build_aggregate_convergence(curves: dict) -> tuple[list[dict], dict]:
    maximum_end = max(
        float(curve["end_min"])
        for arm_curves in curves.values()
        for curve in arm_curves.values()
    )
    grid_end = (
        math.ceil((maximum_end - 1e-12) / TIME_GRID_STEP_MIN)
        * TIME_GRID_STEP_MIN
    )
    grid_count = int(round(grid_end / TIME_GRID_STEP_MIN)) + 1
    time_grid = [index * TIME_GRID_STEP_MIN for index in range(grid_count)]

    rows: list[dict] = []
    plotted: dict[str, tuple[list[float], list[float]]] = {}
    selected_times = {0.0, 0.25, 0.5, 1.0, 2.0, 5.0, grid_end}
    selected_metrics: dict[str, dict] = defaultdict(dict)

    for arm in TRAJECTORY_ARM_ORDER:
        arm_means: list[float] = []
        for time_min in time_grid:
            fixed_denominator_values: list[float] = []
            active_values: list[float] = []
            carried_forward_count = 0
            for curve in curves[arm].values():
                times = curve["times_min"]
                gaps = curve["gaps_pct"]
                point_index = bisect.bisect_right(times, time_min) - 1
                assert point_index >= 0
                value = float(gaps[point_index])
                fixed_denominator_values.append(value)
                if time_min <= float(curve["end_min"]) + 1e-12:
                    active_values.append(value)
                else:
                    carried_forward_count += 1

            assert len(fixed_denominator_values) == 405
            mean_gap = statistics.fmean(fixed_denominator_values)
            median_gap = statistics.median(fixed_denominator_values)
            active_mean = (
                statistics.fmean(active_values) if active_values else None
            )
            arm_means.append(mean_gap)
            row = {
                "time_min": time_min,
                "arm": ARM_LABELS[arm],
                "arm_code": arm,
                "mean_normalized_gap_pct": mean_gap,
                "median_normalized_gap_pct": median_gap,
                "fixed_denominator_n": 405,
                "carried_forward_n": carried_forward_count,
                "active_only_n": len(active_values),
                "active_only_mean_normalized_gap_pct": active_mean,
            }
            rows.append(row)
            if any(abs(time_min - selected) <= 1e-12 for selected in selected_times):
                selected_metrics[f"{time_min:.2f}"][arm] = {
                    "mean_gap_pct": mean_gap,
                    "median_gap_pct": median_gap,
                    "active_only_n": len(active_values),
                    "active_only_mean_gap_pct": active_mean,
                }
        plotted[arm] = (time_grid, arm_means)

    metadata = {
        "time_grid_step_minutes": TIME_GRID_STEP_MIN,
        "time_grid_end_minutes": grid_end,
        "time_grid_point_count": len(time_grid),
        "selected_time_metrics": dict(selected_metrics),
        "normalization": (
            "For each instance-seed unit, divide each plotted arm's cumulative "
            "best complete-model checkpoint cost by the minimum complete-model "
            "cost observed across F/E/M/MV at any recorded time, then subtract "
            "one and multiply by 100."
        ),
        "time_zero": (
            "The sealed trajectory field initial_objective is assigned to all "
            "four arms at t=0; it is their shared complete-model initial solution."
        ),
        "after_termination": (
            "Last observation carried forward; no interpolation or smoothing."
        ),
    }
    return rows, {"plotted": plotted, "metadata": metadata}


def write_aggregate_csv(rows: list[dict]) -> None:
    fieldnames = list(rows[0])
    path = OUTPUT_DIR / "fig_e2_aggregate_convergence_data.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            formatted = dict(row)
            for field in (
                "time_min",
                "mean_normalized_gap_pct",
                "median_normalized_gap_pct",
                "active_only_mean_normalized_gap_pct",
            ):
                value = formatted[field]
                formatted[field] = "" if value is None else f"{float(value):.12f}"
            writer.writerow(formatted)


def plot_aggregate_convergence(plotted: dict) -> None:
    configure_matplotlib()
    fig, ax = plt.subplots(figsize=(6.30, 4.00))
    all_y: list[float] = []
    for arm in TRAJECTORY_ARM_ORDER:
        x_values, y_values = plotted[arm]
        all_y.extend(y_values)
        ax.plot(
            x_values,
            y_values,
            label=ARM_LABELS[arm],
            solid_capstyle="round",
            dash_capstyle="round",
            **STYLES[arm],
        )

    ax.set_xlim(0.0, max(plotted["MV"][0]))
    ax.set_ylim(0.0, max(all_y) * 1.06)
    ax.set_xlabel("运行时间（min）", fontsize=10.5)
    ax.set_ylabel("平均相对差距（%）", fontsize=10.5)
    ax.tick_params(axis="both", labelsize=9.0, direction="out", length=3.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(False)
    ax.legend(
        loc="upper right",
        frameon=False,
        fontsize=8.8,
        handlelength=3.2,
        borderaxespad=0.6,
        labelspacing=0.45,
    )
    fig.tight_layout(pad=0.8)
    pdf_metadata = {
        "Title": "E2聚合收敛曲线",
        "Subject": "405 instance-seed units; normalized complete-model gaps",
        "Creator": "generate_e2_v2_outputs.py",
        "CreationDate": None,
        "ModDate": None,
    }
    fig.savefig(
        OUTPUT_DIR / "fig_e2_aggregate_convergence.pdf",
        format="pdf",
        bbox_inches="tight",
        metadata=pdf_metadata,
    )
    fig.savefig(
        OUTPUT_DIR / "fig_e2_aggregate_convergence.png",
        format="png",
        dpi=300,
        bbox_inches="tight",
    )
    plt.close(fig)


def build_performance_profile(
    final_rows: list[dict],
    final_index: dict[tuple[str, int, str], dict],
) -> tuple[list[dict], list[dict], dict]:
    units = sorted(
        {(row["instance_id"], int(row["seed"])) for row in final_rows}
    )
    assert len(units) == 405

    ratio_rows: list[dict] = []
    ratios_by_arm: dict[str, list[float]] = defaultdict(list)
    best_counts: Counter = Counter()
    for instance_id, seed in units:
        costs = {
            arm: float(final_index[(instance_id, seed, arm)]["final_cost"])
            for arm in FINAL_ARM_ORDER
        }
        best_cost = min(costs.values())
        for arm in FINAL_ARM_ORDER:
            ratio = costs[arm] / best_cost
            is_best = math.isclose(
                costs[arm], best_cost, rel_tol=0.0, abs_tol=COST_TOL
            )
            ratios_by_arm[arm].append(ratio)
            best_counts[arm] += int(is_best)
            ratio_rows.append(
                {
                    "instance_id": instance_id,
                    "seed": seed,
                    "arm": ARM_LABELS[arm],
                    "arm_code": arm,
                    "final_cost_cny": costs[arm],
                    "unit_best_cost_cny": best_cost,
                    "tau_ratio": ratio,
                    "is_unit_best": is_best,
                }
            )

    maximum_ratio = max(max(values) for values in ratios_by_arm.values())
    tau_max = math.ceil((maximum_ratio - RATIO_TOL) * 100.0) / 100.0
    start_index = int(round(1.0 / TAU_GRID_STEP))
    end_index = int(round(tau_max / TAU_GRID_STEP))
    tau_grid = [index * TAU_GRID_STEP for index in range(start_index, end_index + 1)]

    profile_rows: list[dict] = []
    plotted: dict[str, tuple[list[float], list[float]]] = {}
    for arm in FINAL_ARM_ORDER:
        sorted_ratios = sorted(ratios_by_arm[arm])
        shares: list[float] = []
        for tau in tau_grid:
            count = bisect.bisect_right(sorted_ratios, tau + RATIO_TOL)
            share = count / len(sorted_ratios)
            shares.append(share)
            profile_rows.append(
                {
                    "tau": tau,
                    "arm": ARM_LABELS[arm],
                    "arm_code": arm,
                    "unit_count_at_or_below_tau": count,
                    "unit_share_at_or_below_tau": share,
                    "total_unit_count": 405,
                }
            )
        plotted[arm] = (tau_grid, shares)

    assert best_counts == Counter({"MV": 400, "M": 290, "E": 279, "F": 97, "O": 51})
    metadata = {
        "tau_grid_step": TAU_GRID_STEP,
        "tau_axis_max": tau_max,
        "maximum_observed_tau": maximum_ratio,
        "best_unit_counts": dict(best_counts),
        "best_unit_shares": {
            arm: best_counts[arm] / 405 for arm in FINAL_ARM_ORDER
        },
        "definition": (
            "tau = arm final complete-model cost / minimum final complete-model "
            "cost among O/F/E/M/MV in the same instance-seed unit."
        ),
        "tie_rule": f"Absolute cost tolerance {COST_TOL:g}.",
    }
    return ratio_rows, profile_rows, {"plotted": plotted, "metadata": metadata}


def write_performance_profile_csvs(
    ratio_rows: list[dict], profile_rows: list[dict]
) -> None:
    ratio_path = OUTPUT_DIR / "fig_e2_performance_profile_ratios.csv"
    with ratio_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ratio_rows[0]))
        writer.writeheader()
        for row in ratio_rows:
            formatted = dict(row)
            for field in ("final_cost_cny", "unit_best_cost_cny", "tau_ratio"):
                formatted[field] = f"{float(row[field]):.12f}"
            formatted["is_unit_best"] = str(row["is_unit_best"]).lower()
            writer.writerow(formatted)

    curve_path = OUTPUT_DIR / "fig_e2_performance_profile_curve.csv"
    with curve_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(profile_rows[0]))
        writer.writeheader()
        for row in profile_rows:
            formatted = dict(row)
            formatted["tau"] = f"{float(row['tau']):.12f}"
            formatted["unit_share_at_or_below_tau"] = (
                f"{float(row['unit_share_at_or_below_tau']):.12f}"
            )
            writer.writerow(formatted)


def plot_performance_profile(plotted: dict, metadata: dict) -> None:
    configure_matplotlib()
    fig, ax = plt.subplots(figsize=(6.30, 4.00))
    for arm in FINAL_ARM_ORDER:
        x_values, y_values = plotted[arm]
        ax.step(
            x_values,
            y_values,
            where="post",
            label=ARM_LABELS[arm],
            solid_capstyle="round",
            dash_capstyle="round",
            **STYLES[arm],
        )

    annotation_offsets = {
        "O": -0.035,
        "F": 0.025,
        "E": -0.030,
        "M": 0.025,
        "MV": -0.035,
    }
    for arm in FINAL_ARM_ORDER:
        share = float(metadata["best_unit_shares"][arm])
        ax.plot(
            [1.0],
            [share],
            marker="o",
            markersize=3.8 if arm != "MV" else 4.4,
            markerfacecolor=STYLES[arm]["color"],
            markeredgewidth=0,
            zorder=6,
        )
        ax.annotate(
            f"{100.0 * share:.1f}%",
            xy=(1.0, share),
            xytext=(5, 7 if annotation_offsets[arm] > 0 else -9),
            textcoords="offset points",
            fontsize=7.5,
            color=STYLES[arm]["color"],
            ha="left",
            va="center",
        )

    tau_max = float(metadata["tau_axis_max"])
    ax.set_xlim(1.0, tau_max)
    ax.set_ylim(0.0, 1.025)
    tick_step = 0.02
    x_ticks = np.arange(1.0, tau_max + tick_step / 2.0, tick_step)
    ax.set_xticks(x_ticks)
    ax.set_xlabel(r"成本比值 $\tau$", fontsize=10.5)
    ax.set_ylabel(r"成本比值不超过 $\tau$ 的单元占比", fontsize=10.5)
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1.0, decimals=0))
    ax.tick_params(axis="both", labelsize=9.0, direction="out", length=3.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(False)
    ax.legend(
        loc="lower right",
        frameon=False,
        fontsize=8.5,
        handlelength=3.2,
        borderaxespad=0.6,
        labelspacing=0.4,
    )
    fig.tight_layout(pad=0.8)
    pdf_metadata = {
        "Title": "E2算法性能剖面",
        "Subject": "405 instance-seed units; final complete-model cost ratios",
        "Creator": "generate_e2_v2_outputs.py",
        "CreationDate": None,
        "ModDate": None,
    }
    fig.savefig(
        OUTPUT_DIR / "fig_e2_performance_profile.pdf",
        format="pdf",
        bbox_inches="tight",
        metadata=pdf_metadata,
    )
    fig.savefig(
        OUTPUT_DIR / "fig_e2_performance_profile.png",
        format="png",
        dpi=300,
        bbox_inches="tight",
    )
    plt.close(fig)


def build_final_comparison_metrics(
    final_rows: list[dict],
    final_index: dict[tuple[str, int, str], dict],
) -> dict:
    units = sorted(
        {(row["instance_id"], int(row["seed"])) for row in final_rows}
    )
    mv_vs_arm: dict[str, dict] = {}
    for arm in ("O", "F", "E", "M"):
        counts: Counter = Counter()
        improvements: list[float] = []
        for unit in units:
            arm_cost = float(final_index[unit + (arm,)]["final_cost"])
            mv_cost = float(final_index[unit + ("MV",)]["final_cost"])
            counts[compare_cost(mv_cost, arm_cost)] += 1
            improvements.append(100.0 * (arm_cost - mv_cost) / arm_cost)
        mv_vs_arm[arm] = {
            "wins": counts["W"],
            "ties": counts["T"],
            "losses": counts["L"],
            "paired_mean_improvement_pct": statistics.fmean(improvements),
        }

    assert (
        mv_vs_arm["O"]["wins"],
        mv_vs_arm["O"]["ties"],
        mv_vs_arm["O"]["losses"],
    ) == (354, 46, 5)
    assert (
        mv_vs_arm["F"]["wins"],
        mv_vs_arm["F"]["ties"],
        mv_vs_arm["F"]["losses"],
    ) == (307, 98, 0)
    assert (
        mv_vs_arm["E"]["wins"],
        mv_vs_arm["E"]["ties"],
        mv_vs_arm["E"]["losses"],
    ) == (125, 280, 0)
    assert (
        mv_vs_arm["M"]["wins"],
        mv_vs_arm["M"]["ties"],
        mv_vs_arm["M"]["losses"],
    ) == (114, 291, 0)
    assert math.isclose(
        mv_vs_arm["O"]["paired_mean_improvement_pct"],
        1.919118015025895,
        rel_tol=0.0,
        abs_tol=1e-12,
    )

    adjacent_pairs = (("O", "F"), ("F", "E"), ("E", "M"), ("M", "MV"))
    staircase_count = 0
    for unit in units:
        costs = {
            arm: float(final_index[unit + (arm,)]["final_cost"])
            for arm in FINAL_ARM_ORDER
        }
        if all(
            costs[higher] <= costs[lower] + COST_TOL
            for lower, higher in adjacent_pairs
        ):
            staircase_count += 1
    assert staircase_count == 299

    return {
        "mv_vs_arm": mv_vs_arm,
        "complete_nonincreasing_staircase_units": staircase_count,
        "total_units": 405,
        "batch_boundary": {
            "O": "NoImprovement(3000) new batch",
            "F_E_M_MV": "2026-07-24 sealed v7 fixed 25000 iterations per view",
            "same_batch": False,
            "same_machine": False,
            "same_stopping_rule": False,
            "equal_compute": False,
        },
    }


def write_artifact_hashes() -> bool:
    artifact_names = (
        "fig_e2_aggregate_convergence.pdf",
        "fig_e2_aggregate_convergence.png",
        "fig_e2_aggregate_convergence_data.csv",
        "fig_e2_performance_profile.pdf",
        "fig_e2_performance_profile.png",
        "fig_e2_performance_profile_ratios.csv",
        "fig_e2_performance_profile_curve.csv",
        "validation_summary.json",
        "generate_e2_v2_outputs.py",
        "report.md",
    )
    if not all((OUTPUT_DIR / name).is_file() for name in artifact_names):
        return False

    artifacts = {name: sha256(OUTPUT_DIR / name) for name in artifact_names}
    manifest = {
        "algorithm": "sha256",
        "schema": "resetp.e2-v2-presentation-artifact-hashes.v1",
        "artifacts": artifacts,
        "source_artifacts": {
            COMPARISON_RAW.relative_to(REPO_ROOT).as_posix(): sha256(
                COMPARISON_RAW
            ),
            COMPARISON_HASHES.relative_to(REPO_ROOT).as_posix(): sha256(
                COMPARISON_HASHES
            ),
            FINAL_GATE_HASHES.relative_to(REPO_ROOT).as_posix(): sha256(
                FINAL_GATE_HASHES
            ),
        },
        "exclusions": [
            "artifact_hashes.json",
            "done.json",
            "._*",
            "__pycache__",
            ".pytest_cache",
        ],
    }
    write_json(OUTPUT_DIR / "artifact_hashes.json", manifest)
    return True


def main() -> None:
    final_rows, final_index = load_and_validate_final_ledger()
    trajectory_files = validate_trajectory_manifest()
    curves, trajectory_integrity = load_and_validate_trajectories(
        trajectory_files, final_index
    )

    aggregate_rows, aggregate_bundle = build_aggregate_convergence(curves)
    write_aggregate_csv(aggregate_rows)
    plot_aggregate_convergence(aggregate_bundle["plotted"])

    ratio_rows, profile_rows, profile_bundle = build_performance_profile(
        final_rows, final_index
    )
    write_performance_profile_csvs(ratio_rows, profile_rows)
    plot_performance_profile(
        profile_bundle["plotted"], profile_bundle["metadata"]
    )

    validation_summary = {
        "schema": "resetp.e2-v2-validation-summary.v1",
        "new_experiments_run": 0,
        "source_boundaries": [
            COMPARISON_DIR.relative_to(REPO_ROOT).as_posix(),
            FINAL_V7_DIR.relative_to(REPO_ROOT).as_posix(),
        ],
        "excluded_sources": [
            "baselines/e2_alns/",
            "baselines/e2_final_campaign_20260720/p2p3_threeview/",
            "all earlier E2 batches",
        ],
        "source_hashes": {
            COMPARISON_RAW.relative_to(REPO_ROOT).as_posix(): sha256(
                COMPARISON_RAW
            ),
            COMPARISON_HASHES.relative_to(REPO_ROOT).as_posix(): sha256(
                COMPARISON_HASHES
            ),
            FINAL_GATE_HASHES.relative_to(REPO_ROOT).as_posix(): sha256(
                FINAL_GATE_HASHES
            ),
        },
        "final_ledger": {
            "row_count": len(final_rows),
            "unit_count": 405,
            "arm_count": 5,
            "instance_count": 81,
            "seeds": [1, 2, 3, 4, 5],
        },
        "trajectory_integrity": trajectory_integrity,
        "aggregate_convergence": aggregate_bundle["metadata"],
        "performance_profile": profile_bundle["metadata"],
        "final_comparison": build_final_comparison_metrics(
            final_rows, final_index
        ),
    }
    write_json(OUTPUT_DIR / "validation_summary.json", validation_summary)
    hashes_written = write_artifact_hashes()
    print(
        json.dumps(
            {
                "new_experiments_run": 0,
                "final_rows_validated": len(final_rows),
                "trajectory_files_validated": len(trajectory_files),
                "trajectory_points_validated": trajectory_integrity[
                    "trajectory_observed_point_count"
                ],
                "aggregate_rows_written": len(aggregate_rows),
                "performance_ratio_rows_written": len(ratio_rows),
                "performance_curve_rows_written": len(profile_rows),
                "artifact_hashes_written": hashes_written,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
