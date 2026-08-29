#!/usr/bin/env python3
"""Generate E2 presentation artifacts from sealed data only.

This script performs no solver calls and no model re-evaluation. It reads the
sealed final-value ledger and one sealed trajectory file, validates registered
counts, and writes a figure plus an aggregate ablation table.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt


REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = Path(__file__).resolve().parent

COMPARISON_DIR = (
    REPO_ROOT
    / "baselines/algorithm_prototypes/china81_vs_opensource_20260727"
)
FINAL_V7_DIR = (
    REPO_ROOT
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v7_small_archive_ledger_20260724"
)
FINAL_GATE_DIR = FINAL_V7_DIR / "full_gate"
COMPARISON_RAW = COMPARISON_DIR / "raw_runs.json"
COMPARISON_HASHES = COMPARISON_DIR / "artifact_hashes.json"
FINAL_V7_HASHES = FINAL_GATE_DIR / "artifact_hashes.json"
CASE_REGISTRATION = FINAL_V7_DIR / "s3_trajectory_case_registration_v2.json"

DISPLAY_INSTANCE = "cn-prd-100c-01-V2-LOCATIONS"
DISPLAY_SEED = 1
DISPLAY_TASK = (
    FINAL_GATE_DIR
    / "tasks"
    / f"D6-E2-STAGED__{DISPLAY_INSTANCE}__seed{DISPLAY_SEED}"
)
DISPLAY_TRAJECTORY = DISPLAY_TASK / "trajectory_observations.json"

ARM_ORDER = ("O", "F", "E", "M", "MV")
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
WITNESS_KEYS = TRAJECTORY_KEYS
TOL = 1e-9

EXPECTED_COMPARISON_RAW_SHA256 = (
    "4291ee24707bcf834c6cf6ff6b308a14eab4b4a6a3011681408935e8693e070c"
)
EXPECTED_TRAJECTORY_SHA256 = (
    "fabeb5fcc0faf8288da3c1cdda1c3964472689998d4ca470e647bb3aeb974c66"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def assert_sealed_source_hashes() -> None:
    comparison_manifest = load_json(COMPARISON_HASHES)
    manifest_raw = comparison_manifest["artifacts"]["raw_runs.json"]
    actual_raw = sha256(COMPARISON_RAW)
    assert manifest_raw == EXPECTED_COMPARISON_RAW_SHA256
    assert actual_raw == EXPECTED_COMPARISON_RAW_SHA256

    final_manifest = load_json(FINAL_V7_HASHES)
    relative_trajectory = DISPLAY_TRAJECTORY.relative_to(FINAL_GATE_DIR).as_posix()
    manifest_trajectory = final_manifest["artifacts"][relative_trajectory]
    actual_trajectory = sha256(DISPLAY_TRAJECTORY)
    assert manifest_trajectory == EXPECTED_TRAJECTORY_SHA256
    assert actual_trajectory == EXPECTED_TRAJECTORY_SHA256


def compare_cost(lower_is_better_a: float, cost_b: float) -> str:
    """Return W/T/L from algorithm A's perspective."""
    if lower_is_better_a < cost_b - TOL:
        return "W"
    if lower_is_better_a > cost_b + TOL:
        return "L"
    return "T"


def validate_final_rows(rows: list[dict]) -> dict[tuple[str, int, str], dict]:
    assert len(rows) == 2025
    counts = Counter(row["arm"] for row in rows)
    assert counts == Counter({arm: 405 for arm in ARM_ORDER})
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
    return index


def audit_vehicle_counts(rows: list[dict]) -> None:
    """Verify route_count equals unique vehicle IDs for all 2,025 rows."""
    witness_cache: dict[Path, dict] = {}
    for row in rows:
        witness_path = REPO_ROOT / row["witness_path"]
        witness = witness_cache.get(witness_path)
        if witness is None:
            witness = load_json(witness_path)
            witness_cache[witness_path] = witness

        solution = witness if row["arm"] == "O" else witness[WITNESS_KEYS[row["arm"]]]
        routes = solution["routes"]
        vehicle_ids = [route["vehicle_id"] for route in routes]
        assert len(routes) == int(row["route_count"])
        assert len(vehicle_ids) == len(set(vehicle_ids))


def build_table_rows(
    rows: list[dict],
    index: dict[tuple[str, int, str], dict],
) -> list[dict]:
    by_arm: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_arm[row["arm"]].append(row)

    unit_keys = sorted({(row["instance_id"], int(row["seed"])) for row in rows})
    adjacent_pairs = (("O", "F"), ("F", "E"), ("E", "M"), ("M", "MV"))
    adjacent_counts: dict[tuple[str, str], Counter] = {}
    for lower_arm, higher_arm in adjacent_pairs:
        counts: Counter = Counter()
        for instance_id, seed in unit_keys:
            higher_cost = float(index[(instance_id, seed, higher_arm)]["final_cost"])
            lower_cost = float(index[(instance_id, seed, lower_arm)]["final_cost"])
            counts[compare_cost(higher_cost, lower_cost)] += 1
        adjacent_counts[(lower_arm, higher_arm)] = counts

    assert adjacent_counts[("O", "F")] == Counter(W=268, T=115, L=22)
    assert adjacent_counts[("F", "E")] == Counter(W=290, T=86, L=29)
    assert adjacent_counts[("E", "M")] == Counter(W=79, T=249, L=77)
    assert adjacent_counts[("M", "MV")] == Counter(W=114, T=291, L=0)

    staircase_count = 0
    for instance_id, seed in unit_keys:
        costs = {
            arm: float(index[(instance_id, seed, arm)]["final_cost"])
            for arm in ARM_ORDER
        }
        if all(
            costs[higher] <= costs[lower] + TOL
            for lower, higher in adjacent_pairs
        ):
            staircase_count += 1
    assert staircase_count == 299

    table_rows: list[dict] = []
    mv_gap_o = None
    for arm in ARM_ORDER:
        arm_rows = by_arm[arm]
        per_instance: dict[str, list[float]] = defaultdict(list)
        for row in arm_rows:
            per_instance[row["instance_id"]].append(float(row["final_cost"]))

        direct_counts: Counter = Counter()
        paired_gaps = []
        for instance_id, seed in unit_keys:
            arm_cost = float(index[(instance_id, seed, arm)]["final_cost"])
            mv_cost = float(index[(instance_id, seed, "MV")]["final_cost"])
            direct_counts[compare_cost(mv_cost, arm_cost)] += 1
            if arm == "MV":
                paired_gaps.append(0.0)
            else:
                paired_gaps.append(100.0 * (arm_cost - mv_cost) / arm_cost)

        if arm == "O":
            mv_gap_o = statistics.fmean(paired_gaps)

        adjacent_next = ""
        adjacent_w = adjacent_t = adjacent_l = ""
        pair = next((pair for pair in adjacent_pairs if pair[0] == arm), None)
        if pair is not None:
            adjacent_next = ARM_LABELS[pair[1]]
            adjacent_w = adjacent_counts[pair]["W"]
            adjacent_t = adjacent_counts[pair]["T"]
            adjacent_l = adjacent_counts[pair]["L"]

        protocol = (
            "NEW_DISTANCE_ONLY_O_20260727; NoImprovement(3000)"
            if arm == "O"
            else "SEALED_V7_ARCHIVE_20260724; fixed 25000 iterations/view"
        )
        table_rows.append(
            {
                "arm": ARM_LABELS[arm],
                "arm_code": arm,
                "n_units": len(arm_rows),
                "mean_instance_best_cost_cny": statistics.fmean(
                    min(costs) for costs in per_instance.values()
                ),
                "mean_run_cost_cny": statistics.fmean(
                    float(row["final_cost"]) for row in arm_rows
                ),
                "gap_pct_mv_improvement_over_arm": statistics.fmean(paired_gaps),
                "mean_vehicle_count": statistics.fmean(
                    int(row["route_count"]) for row in arm_rows
                ),
                "mean_cpu_time_min": statistics.fmean(
                    float(row["cpu_seconds"]) for row in arm_rows
                )
                / 60.0,
                "mv_vs_arm_wins": direct_counts["W"],
                "mv_vs_arm_ties": direct_counts["T"],
                "mv_vs_arm_losses": direct_counts["L"],
                "adjacent_next_arm": adjacent_next,
                "adjacent_transition_wins": adjacent_w,
                "adjacent_transition_ties": adjacent_t,
                "adjacent_transition_losses": adjacent_l,
                "batch_protocol": protocol,
            }
        )

    assert mv_gap_o is not None
    assert math.isclose(mv_gap_o, 1.919118015025895, abs_tol=1e-12)
    assert (
        table_rows[0]["mv_vs_arm_wins"],
        table_rows[0]["mv_vs_arm_ties"],
        table_rows[0]["mv_vs_arm_losses"],
    ) == (354, 46, 5)
    return table_rows


def write_table_csv(table_rows: list[dict]) -> None:
    output_path = OUTPUT_DIR / "table_e2_ablation.csv"
    fieldnames = list(table_rows[0])
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in table_rows:
            formatted = dict(row)
            for field in (
                "mean_instance_best_cost_cny",
                "mean_run_cost_cny",
                "gap_pct_mv_improvement_over_arm",
                "mean_vehicle_count",
                "mean_cpu_time_min",
            ):
                formatted[field] = f"{float(row[field]):.12f}"
            writer.writerow(formatted)


def write_table_tex(table_rows: list[dict]) -> None:
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{E2算法消融结果}",
        r"\label{tab:e2_ablation}",
        r"\small",
        r"\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}lrrrrrr@{}}",
        r"\toprule",
        r"算法臂 & Best（元） & Avg（元） & Gap（\%） & 车辆数 & CPU（min） & MV胜/平/负 \\",
        r"\midrule",
    ]
    for row in table_rows:
        is_mv = row["arm_code"] == "MV"
        arm = r"\textbf{MV-HGS-SP}" if is_mv else row["arm"]
        best = f"{row['mean_instance_best_cost_cny']:.3f}"
        avg = f"{row['mean_run_cost_cny']:.3f}"
        if is_mv:
            best = rf"\textbf{{{best}}}"
            avg = rf"\textbf{{{avg}}}"
        gap = f"{row['gap_pct_mv_improvement_over_arm']:.3f}"
        vehicles = f"{row['mean_vehicle_count']:.3f}"
        cpu = f"{row['mean_cpu_time_min']:.3f}"
        direct = (
            f"{row['mv_vs_arm_wins']}/"
            f"{row['mv_vs_arm_ties']}/"
            f"{row['mv_vs_arm_losses']}"
        )
        lines.append(
            f"{arm} & {best} & {avg} & {gap} & {vehicles} & {cpu} & {direct} \\\\"
        )
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabular*}",
            (
                r"\tabnote{Best为81个算例各自5个种子最优成本的等权均值，"
                r"Avg为405个实例--种子单元成本的等权均值。"
                r"Gap$=100\times\mathrm{mean}[(C_{\rm arm}-C_{\rm MV})/C_{\rm arm}]$，"
                r"正值表示MV-HGS-SP成本较低；车辆数为每个封存方案中唯一"
                r"vehicle\_id的数量。CPU仅作描述：O臂与其余四臂非同批、"
                r"非同机、非同停止规则且非等算力。}"
            ),
            r"\end{table}",
            "",
        ]
    )
    (OUTPUT_DIR / "table_e2_ablation.tex").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def configure_matplotlib() -> None:
    font_path = Path("/System/Library/Fonts/STHeiti Light.ttc")
    if not font_path.exists():
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


def build_trajectory_rows(
    final_index: dict[tuple[str, int, str], dict],
) -> tuple[list[dict], dict[str, list[dict]]]:
    registration = load_json(CASE_REGISTRATION)
    assert registration["selected_instance_id"] == DISPLAY_INSTANCE
    assert registration["result_rows_read_for_this_selection"] == 0
    assert registration["may_be_called_statistically_representative"] is False

    data = load_json(DISPLAY_TRAJECTORY)
    assert data["schema"] == "resetp.d6-e2-staged-trajectories.v1"
    assert set(data["curves"]) == set(TRAJECTORY_KEYS.values())

    output_rows: list[dict] = []
    plotted: dict[str, list[dict]] = {}
    for arm in ("F", "E", "M", "MV"):
        source_points = data["curves"][TRAJECTORY_KEYS[arm]]
        assert source_points
        best_so_far = math.inf
        arm_points: list[dict] = []
        last_time = -math.inf
        for point_index, point in enumerate(source_points, start=1):
            elapsed_seconds = float(point["elapsed_seconds"])
            observed_cost = float(point["objective"])
            assert elapsed_seconds >= last_time
            last_time = elapsed_seconds
            best_so_far = min(best_so_far, observed_cost)
            row = {
                "arm": ARM_LABELS[arm],
                "arm_code": arm,
                "instance_id": DISPLAY_INSTANCE,
                "seed": DISPLAY_SEED,
                "point_index": point_index,
                "elapsed_seconds": elapsed_seconds,
                "elapsed_minutes": elapsed_seconds / 60.0,
                "observed_cost_cny": observed_cost,
                "best_so_far_cost_cny": best_so_far,
                "phase": point["phase"],
                "source": point["source"],
            }
            arm_points.append(row)
            output_rows.append(row)

        sealed_final = float(
            final_index[(DISPLAY_INSTANCE, DISPLAY_SEED, arm)]["final_cost"]
        )
        assert math.isclose(
            float(source_points[-1]["objective"]), sealed_final, abs_tol=TOL
        )
        assert math.isclose(best_so_far, sealed_final, abs_tol=TOL)
        plotted[arm] = arm_points
    return output_rows, plotted


def write_trajectory_csv(rows: list[dict]) -> None:
    output_path = OUTPUT_DIR / "fig_e2_convergence_data.csv"
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            formatted = dict(row)
            for field in (
                "elapsed_seconds",
                "elapsed_minutes",
                "observed_cost_cny",
                "best_so_far_cost_cny",
            ):
                formatted[field] = f"{float(row[field]):.12f}"
            writer.writerow(formatted)


def write_convergence_figure(plotted: dict[str, list[dict]]) -> None:
    configure_matplotlib()
    styles = {
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

    fig, ax = plt.subplots(figsize=(6.30, 4.00))
    all_x: list[float] = []
    all_y: list[float] = []
    for arm in ("F", "E", "M", "MV"):
        x = [float(point["elapsed_minutes"]) for point in plotted[arm]]
        y = [float(point["best_so_far_cost_cny"]) for point in plotted[arm]]
        all_x.extend(x)
        all_y.extend(y)
        ax.plot(
            x,
            y,
            label=ARM_LABELS[arm],
            solid_capstyle="round",
            dash_capstyle="round",
            **styles[arm],
        )

    x_span = max(all_x) - min(all_x)
    y_span = max(all_y) - min(all_y)
    ax.set_xlim(0.0, max(all_x) + 0.025 * x_span)
    ax.set_ylim(min(all_y) - 0.06 * y_span, max(all_y) + 0.08 * y_span)
    ax.set_xlabel("时间（min）", fontsize=10.5)
    ax.set_ylabel("累计最低完整模型成本（元）", fontsize=10.5)
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
    fig.savefig(
        OUTPUT_DIR / "fig_e2_convergence.pdf",
        format="pdf",
        bbox_inches="tight",
        metadata={
            "Title": "不同算法迭代图",
            "Subject": (
                "Sealed E2 complete-model checkpoint best-so-far trajectories; "
                f"{DISPLAY_INSTANCE}, seed {DISPLAY_SEED}"
            ),
        },
    )
    fig.savefig(
        OUTPUT_DIR / "fig_e2_convergence.png",
        format="png",
        dpi=300,
        bbox_inches="tight",
    )
    plt.close(fig)


def write_artifact_hashes() -> None:
    artifact_names = (
        "fig_e2_convergence.pdf",
        "fig_e2_convergence.png",
        "fig_e2_convergence_data.csv",
        "table_e2_ablation.csv",
        "table_e2_ablation.tex",
        "generate_e2_outputs.py",
        "report.md",
    )
    artifacts = {}
    for name in artifact_names:
        path = OUTPUT_DIR / name
        assert path.is_file()
        artifacts[name] = sha256(path)
    manifest = {
        "algorithm": "sha256",
        "schema": "resetp.e2-presentation-artifact-hashes.v1",
        "artifacts": artifacts,
        "source_artifacts": {
            COMPARISON_RAW.relative_to(REPO_ROOT).as_posix(): sha256(COMPARISON_RAW),
            DISPLAY_TRAJECTORY.relative_to(REPO_ROOT).as_posix(): sha256(
                DISPLAY_TRAJECTORY
            ),
        },
        "exclusions": ["artifact_hashes.json", "done.json", "._*", "__pycache__"],
    }
    (OUTPUT_DIR / "artifact_hashes.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    assert_sealed_source_hashes()
    rows = load_json(COMPARISON_RAW)
    index = validate_final_rows(rows)
    audit_vehicle_counts(rows)
    table_rows = build_table_rows(rows, index)
    write_table_csv(table_rows)
    write_table_tex(table_rows)
    trajectory_rows, plotted = build_trajectory_rows(index)
    write_trajectory_csv(trajectory_rows)
    write_convergence_figure(plotted)
    write_artifact_hashes()
    print(
        json.dumps(
            {
                "new_experiments_run": 0,
                "final_rows_validated": len(rows),
                "formal_trajectory_files": len(
                    list(
                        (FINAL_GATE_DIR / "tasks").glob(
                            "*/trajectory_observations.json"
                        )
                    )
                ),
                "display_instance": DISPLAY_INSTANCE,
                "display_seed": DISPLAY_SEED,
                "display_trajectory_rows": len(trajectory_rows),
                "comparison_raw_sha256": sha256(COMPARISON_RAW),
                "display_trajectory_sha256": sha256(DISPLAY_TRAJECTORY),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
