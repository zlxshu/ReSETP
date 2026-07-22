#!/usr/bin/env python3
"""S5 v2: materialize the final China81 summary and renamed artifacts.

This is a deterministic reporting step.  It reads sealed S1--S4/P1 evidence,
does not run a solver, and deliberately does not create the superseded A1
81-row appendix.  The legacy S5 outputs remain in this directory as v1
provenance; every v2 output has an explicit suffix.
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
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

import run_s5_artifacts as legacy  # noqa: E402


ROOT = legacy.ROOT
OUT = Path(__file__).resolve().parent
S1 = legacy.S1
S2 = legacy.S2
S3 = legacy.S3
S4 = legacy.S4
S4_DECISION_V2 = legacy.S4_DECISION_V2
S4_ROUTE_DETAILS_V2 = legacy.S4_ROUTE_DETAILS_V2
P1 = legacy.P1
P1_DECISION = legacy.P1_DECISION
VISUAL_CONTRACT = legacy.VISUAL_CONTRACT
S2_DECISION_V2 = legacy.S2_DECISION_V2
S2_EXCEPTION_INSTANCE = "cn-jjj-200c-01-V2-LOCATIONS"
S2_EXCEPTION_ID = "S2-INFEASIBLE-UNIT-001"
APPLEDOUBLE_FLAG = "HASH_CONTAMINATED_APPLEDOUBLE"

ENGINE_TO_PAPER = {
    "cv_only": "HGS-F",
    "naive_ev": "HGS-E",
    "mechanism_ev": "HGS-M",
    "MV-HGS-SP": "MV-HGS-SP",
}
PAPER_ARMS = ("HGS-F", "HGS-E", "HGS-M", "MV-HGS-SP")
NEW_MODES = ("cv_only", "naive_ev")
CITY_GROUPS = {
    "cy": "成渝",
    "jjj": "京津冀",
    "prd": "珠三角",
}
# The sealed ledger contains nine tiers.  Three contiguous triples give the
# requested three scale layers and retain every one of the 81 instances.
SCALE_BANDS = (
    ("S", "10/15/20", (10, 15, 20)),
    ("M", "25/50/75", (25, 50, 75)),
    ("L", "100/150/200", (100, 150, 200)),
)
EPS = 1.0e-12


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNAVAILABLE"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _require_pass(path: Path, expected: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("decision") != expected:
        raise RuntimeError(f"{path} decision is {payload.get('decision')!r}, expected {expected}")
    return payload


def _float(value: str | float | int, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"non-numeric {label}: {value!r}") from exc
    if not math.isfinite(result):
        raise RuntimeError(f"non-finite {label}: {value!r}")
    return result


def _preserve_v1_manifest() -> None:
    current = OUT / "artifact_hashes.json"
    v1 = OUT / "artifact_hashes_v1.json"
    if current.is_file() and not v1.exists():
        shutil.copyfile(current, v1)


def _load_s2_records() -> tuple[list[dict[str, str]], dict[tuple[str, int, str], float | None], dict[str, Any]]:
    rows = _read_csv(S2 / "raw_runs.csv")
    if len(rows) != 810:
        raise RuntimeError(f"S2 raw row count is {len(rows)}, expected 810")
    key_counts: defaultdict[tuple[str, int, str], int] = defaultdict(int)
    grouped: defaultdict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
    tiers: dict[str, int] = {}
    for row in rows:
        instance = row["instance_id"]
        seed = int(row["seed"])
        mode = row["route_proxy_mode"]
        key = (instance, seed, mode)
        key_counts[key] += 1
        grouped[(instance, seed)].append(row)
        tiers[instance] = int(row["tier"])
        if mode not in NEW_MODES:
            raise RuntimeError(f"unexpected S2 new mode {mode!r}")
        if row["status"] == "OK" and int(row["violation_count"] or 0) != 0:
            raise RuntimeError(f"S2 row has violations: {instance}, seed={seed}, mode={mode}")
    if any(count != 1 for count in key_counts.values()):
        raise RuntimeError("S2 has duplicate new-unit keys")
    if len(key_counts) != 810:
        raise RuntimeError(f"S2 unique new-unit key count is {len(key_counts)}, expected 810")
    if len(tiers) != 81 or set(tiers.values()) != {10, 15, 20, 25, 50, 75, 100, 150, 200}:
        raise RuntimeError("S2 instance/tier set is not the sealed China81 nine-tier set")

    values: dict[tuple[str, int, str], float | None] = {}
    for (instance, seed), pair in grouped.items():
        modes = {row["route_proxy_mode"] for row in pair}
        if modes != set(NEW_MODES) or len(pair) != 2:
            raise RuntimeError(f"S2 pair is incomplete for {instance}, seed={seed}: {modes}")
        by_mode = {row["route_proxy_mode"]: row for row in pair}
        for mode in NEW_MODES:
            row = by_mode[mode]
            if row["status"] == "OK":
                values[(instance, seed, ENGINE_TO_PAPER[mode])] = _float(row["cost"], "S2 cost")
            else:
                if not (instance == S2_EXCEPTION_INSTANCE and seed == 2 and mode == "naive_ev"):
                    raise RuntimeError(f"unregistered S2 non-OK row: {instance}, seed={seed}, mode={mode}")
                values[(instance, seed, "HGS-E")] = None
            for row2 in pair:
                mech = _float(row2["reused_mechanism_ev_cost"], "reused HGS-M cost")
                full = _float(row2["reused_mv_hgs_sp_cost"], "reused MV-HGS-SP cost")
                if (instance, seed, "HGS-M") in values and not math.isclose(values[(instance, seed, "HGS-M")], mech, rel_tol=0.0, abs_tol=EPS):
                    raise RuntimeError(f"inconsistent reused HGS-M value: {instance}, seed={seed}")
                if (instance, seed, "MV-HGS-SP") in values and not math.isclose(values[(instance, seed, "MV-HGS-SP")], full, rel_tol=0.0, abs_tol=EPS):
                    raise RuntimeError(f"inconsistent reused MV-HGS-SP value: {instance}, seed={seed}")
                values[(instance, seed, "HGS-M")] = mech
                values[(instance, seed, "MV-HGS-SP")] = full
    exception = {
        "approval_register_id": S2_EXCEPTION_ID,
        "instance_id": S2_EXCEPTION_INSTANCE,
        "seed": 2,
        "arm": "HGS-E",
        "usable_seed_count": 4,
        "feasible_rate": "404/405",
        "raw_row_retained": True,
        "rerun": False,
    }
    return rows, values, {"tiers": tiers, "exception": exception}


def _instance_statistics(
    tiers: dict[str, int], values: dict[tuple[str, int, str], float | None],
) -> dict[tuple[str, str], dict[str, Any]]:
    output: dict[tuple[str, str], dict[str, Any]] = {}
    for instance, tier in sorted(tiers.items()):
        city_key = instance.split("-")[1]
        if city_key not in CITY_GROUPS:
            raise RuntimeError(f"unknown China81 city group in {instance}")
        for arm in PAPER_ARMS:
            costs = [
                values[(instance, seed, arm)]
                for seed in range(1, 6)
                if values[(instance, seed, arm)] is not None
            ]
            if not costs:
                raise RuntimeError(f"no feasible values for {instance}, {arm}")
            output[(instance, arm)] = {
                "instance_id": instance,
                "city_key": city_key,
                "tier": tier,
                "arm": arm,
                "best": min(costs),
                "avg": statistics.fmean(costs),
                "feasible_seeds": len(costs),
                "total_seeds": 5,
            }
    return output


def _summary_rows(instance_stats: dict[tuple[str, str], dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    for city_key, city_label in CITY_GROUPS.items():
        for band_key, band_label, band_tiers in SCALE_BANDS:
            stratum_instances = sorted({
                key[0] for key, value in instance_stats.items()
                if value["city_key"] == city_key and value["tier"] in band_tiers
            })
            items = [
                instance_stats[(instance_id, "HGS-F")]
                for instance_id in stratum_instances
            ]
            if len(items) != 9:
                raise RuntimeError(f"stratum {city_key}/{band_key} has {len(items)} instances, expected 9")
            rows.append(_make_summary_row(city_key, city_label, band_key, band_label, items, instance_stats))

    all_instances = sorted({key[0] for key in instance_stats})
    all_items = [
        instance_stats[(instance_id, "HGS-F")]
        for instance_id in all_instances
    ]
    rows.append(_make_summary_row("ALL", "总体", "ALL", "全部9层", all_items, instance_stats))
    fields = ["city_group_code", "city_group", "scale_band", "tiers", "instance_count"]
    for arm in PAPER_ARMS:
        fields.extend([
            f"{arm}_Best", f"{arm}_avg",
            f"{arm}_Best_error_pct", f"{arm}_avg_error_pct",
            f"{arm}_feasible_units", f"{arm}_total_units",
        ])
    return rows, fields


def _make_summary_row(
    city_key: str, city_label: str, band_key: str, band_label: str,
    anchor_items: list[dict[str, Any]], instance_stats: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    instances = [item["instance_id"] for item in anchor_items]
    row: dict[str, Any] = {
        "city_group_code": city_key,
        "city_group": city_label,
        "scale_band": band_key,
        "tiers": band_label,
        "instance_count": len(instances),
    }
    averages: dict[str, float] = {}
    bests: dict[str, float] = {}
    for arm in PAPER_ARMS:
        stats = [instance_stats[(instance, arm)] for instance in instances]
        bests[arm] = statistics.fmean(item["best"] for item in stats)
        averages[arm] = statistics.fmean(item["avg"] for item in stats)
        row[f"{arm}_Best"] = bests[arm]
        row[f"{arm}_avg"] = averages[arm]
        row[f"{arm}_feasible_units"] = sum(item["feasible_seeds"] for item in stats)
        row[f"{arm}_total_units"] = sum(item["total_seeds"] for item in stats)
    best_best = min(bests.values())
    best_avg = min(averages.values())
    for arm in PAPER_ARMS:
        row[f"{arm}_Best_error_pct"] = 100.0 * (bests[arm] - best_best) / best_best
        row[f"{arm}_avg_error_pct"] = 100.0 * (averages[arm] - best_avg) / best_avg
    return row


def _tex_summary(rows: list[dict[str, Any]]) -> str:
    lines = [
        r"\begin{tabular}{@{}llrrrrrrrr@{}}",
        r"\toprule",
        r"城市群 & 规模层 & \multicolumn{2}{c}{HGS-F} & \multicolumn{2}{c}{HGS-E} & \multicolumn{2}{c}{HGS-M} & \multicolumn{2}{c}{MV-HGS-SP}\\",
        r" &  & Best. & avg. & Best. & avg. & Best. & avg. & Best. & avg.\\",
        r"\midrule",
    ]
    for row in rows:
        cells = [
            row["city_group"], row["tiers"],
            *[f"{float(row[f'{arm}_Best']):.3f}" for arm in PAPER_ARMS],
        ]
        # Reorder the flattened values as Best/avg pairs per arm.
        cells = [row["city_group"], row["tiers"]]
        for arm in PAPER_ARMS:
            cells.extend([f"{float(row[f'{arm}_Best']):.3f}", f"{float(row[f'{arm}_avg']):.3f}"])
        lines.append(" & ".join(cells) + r" \\")
    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"% Each cell is the mean of per-instance Best or five-seed average costs; S2's registered HGS-E infeasible seed remains excluded only from that instance's HGS-E Best/avg.",
    ])
    return "\n".join(lines) + "\n"


def _table6_v2(s3_rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    for seed in range(1, 11):
        row: dict[str, Any] = {"seed": seed}
        for engine, label in ENGINE_TO_PAPER.items():
            if engine == "MV-HGS-SP":
                source_arm = engine
            else:
                source_arm = engine
            matches = [item for item in s3_rows if int(item["seed"]) == seed and item["arm"] == source_arm]
            if len(matches) != 1:
                raise RuntimeError(f"S3 table6 row missing/duplicated seed={seed}, arm={source_arm}")
            item = matches[0]
            row[f"{label}_status"] = item["status"]
            feasible = item["status"] == "OK" and int(item["violation_count"] or 0) == 0
            row[f"{label}_cost"] = _float(item["cost"], f"S3 {label} cost") if feasible else math.nan
            row[f"{label}_cpu_seconds"] = _float(item["cpu_seconds"], f"S3 {label} CPU") if feasible else math.nan
        rows.append(row)
    for label, fn in (("Min", min), ("Avg", statistics.fmean), ("Max", max)):
        row = {"seed": label}
        for paper_arm in PAPER_ARMS:
            costs = [float(item[f"{paper_arm}_cost"]) for item in rows if math.isfinite(float(item[f"{paper_arm}_cost"]))]
            cpus = [float(item[f"{paper_arm}_cpu_seconds"]) for item in rows if math.isfinite(float(item[f"{paper_arm}_cpu_seconds"]))]
            if not costs or not cpus:
                raise RuntimeError(f"S3 table6 arm {paper_arm} has no feasible values")
            row[f"{paper_arm}_cost"] = fn(costs)
            row[f"{paper_arm}_cpu_seconds"] = fn(cpus)
            row[f"{paper_arm}_status"] = f"{len(costs)}/{len(rows)} feasible"
        rows.append(row)
    fields = ["seed"] + [field for arm in PAPER_ARMS for field in (
        f"{arm}_cost", f"{arm}_cpu_seconds", f"{arm}_status")]
    return rows, fields


def _tex_table6_v2(rows: list[dict[str, Any]]) -> str:
    lines = [
        r"\begin{tabular}{@{}lrrrrrrrr@{}}",
        r"\toprule",
        r"种子/统计量 & \multicolumn{2}{c}{HGS-F} & \multicolumn{2}{c}{HGS-E} & \multicolumn{2}{c}{HGS-M} & \multicolumn{2}{c}{MV-HGS-SP}\\",
        r" & 成本/元 & CPU/s & 成本/元 & CPU/s & 成本/元 & CPU/s & 成本/元 & CPU/s\\",
        r"\midrule",
    ]
    for row in rows:
        cells = [str(row["seed"])]
        for arm in PAPER_ARMS:
            cost = float(row[f"{arm}_cost"])
            cpu = float(row[f"{arm}_cpu_seconds"])
            cells.append("--/--" if not math.isfinite(cost) else f"{cost:.3f}/{cpu:.2f}")
        # Use one cell per arm for the compact table; the header remains two-column semantic.
        lines.append(str(row["seed"]) + " & " + " & ".join(
            f"{float(row[f'{arm}_cost']):.3f} & {float(row[f'{arm}_cpu_seconds']):.2f}"
            if math.isfinite(float(row[f"{arm}_cost"])) else "-- & --"
            for arm in PAPER_ARMS
        ) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    return "\n".join(lines) + "\n"


def _plot_figure4_v2(s3_rows: list[dict[str, str]]) -> None:
    plt.rcParams.update({
        "font.family": ["Times New Roman", "Songti SC"], "font.size": 8.0,
        "axes.labelsize": 8.0, "xtick.labelsize": 7.2, "ytick.labelsize": 7.2,
        "legend.fontsize": 7.0, "axes.unicode_minus": False,
        "figure.facecolor": "white", "axes.facecolor": "white",
        "pdf.fonttype": 42, "ps.fonttype": 42,
    })
    fig, ax = plt.subplots(figsize=(4.30, 2.80))
    styles = [
        ("cv_only", "HGS-F", "#1F77B4", "-"),
        ("naive_ev", "HGS-E", "#D55E00", "--"),
        ("mechanism_ev", "HGS-M", "#2CA02C", ":"),
        ("MV-HGS-SP", "MV-HGS-SP", "#9467BD", "-."),
    ]
    curve_rows: list[dict[str, Any]] = []
    for engine, label, color, linestyle in styles:
        x, y = legacy._trajectory_curve(s3_rows, engine)
        ax.plot(x, y, color=color, linestyle=linestyle, linewidth=0.62,
                drawstyle="steps-post", label=label)
        curve_rows.extend(
            {"arm": label, "time_min": float(xx), "median_exact_cost": float(yy)}
            for xx, yy in zip(x, y, strict=True)
        )
    finite_y = [row["median_exact_cost"] for row in curve_rows if math.isfinite(row["median_exact_cost"])]
    ymin, ymax = min(finite_y), max(finite_y)
    margin = max((ymax - ymin) * 0.05, 1.0)
    ax.set_xlim(left=0.0)
    ax.set_ylim(ymin - margin, ymax + margin)
    ax.set_xlabel("Time (min)")
    ax.set_ylabel("Cost (CNY)")
    ax.grid(False)
    ax.legend(loc="upper right", frameon=True, fancybox=False,
              edgecolor="#777777", framealpha=1.0, borderpad=0.2, handlelength=1.7)
    ax.tick_params(direction="out", length=2.0, width=0.468)
    for spine in ax.spines.values():
        spine.set_linewidth(0.468)
    fig.subplots_adjust(left=0.14, right=0.985, bottom=0.18, top=0.975)
    fig.savefig(OUT / "figure4_convergence_v2.pdf", bbox_inches="tight")
    fig.savefig(OUT / "figure4_convergence_v2.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    _write_csv(OUT / "figure4_curve_data_v2.csv", curve_rows,
               ["arm", "time_min", "median_exact_cost"])


def _rankdata(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and ordered[end][1] == ordered[cursor][1]:
            end += 1
        rank = (cursor + 1 + end) / 2.0
        for index, _ in ordered[cursor:end]:
            ranks[index] = rank
        cursor = end
    return ranks


def _wilcoxon_two_sided(differences: list[float]) -> tuple[float, float, int, str]:
    nonzero = [float(value) for value in differences if abs(float(value)) > EPS]
    if not nonzero:
        return math.nan, 1.0, 0, "all_zero"
    absolute = [abs(value) for value in nonzero]
    ranks = _rankdata(absolute)
    w_plus = sum(rank for rank, value in zip(ranks, nonzero, strict=True) if value > 0.0)
    w_minus = sum(rank for rank, value in zip(ranks, nonzero, strict=True) if value < 0.0)
    n = len(nonzero)
    mean = n * (n + 1) / 4.0
    tie_sizes: list[int] = []
    cursor = 0
    ordered = sorted(absolute)
    while cursor < n:
        end = cursor + 1
        while end < n and ordered[end] == ordered[cursor]:
            end += 1
        if end - cursor > 1:
            tie_sizes.append(end - cursor)
        cursor = end
    variance = n * (n + 1) * (2 * n + 1) / 24.0
    variance -= sum(size**3 - size for size in tie_sizes) / 48.0
    if variance <= 0.0:
        return min(w_plus, w_minus), 1.0, n, "degenerate"
    correction = 0.5 if w_plus > mean else -0.5 if w_plus < mean else 0.0
    z = (w_plus - mean - correction) / math.sqrt(variance)
    p_value = math.erfc(abs(z) / math.sqrt(2.0))
    return min(w_plus, w_minus), min(1.0, max(0.0, p_value)), n, "normal_approximation_tie_corrected"


def _holm(pvalues: list[float]) -> list[float]:
    indexed = sorted(enumerate(pvalues), key=lambda item: item[1])
    result = [1.0] * len(pvalues)
    running = 0.0
    total = len(pvalues)
    for rank, (index, p_value) in enumerate(indexed):
        running = max(running, min(1.0, (total - rank) * p_value))
        result[index] = running
    return result


def _pairwise_tests(values: dict[tuple[str, int, str], float | None]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tests: list[dict[str, Any]] = []
    raw_pvalues: list[float] = []
    for baseline in ("HGS-F", "HGS-E", "HGS-M"):
        differences: list[float] = []
        paired_keys = []
        for instance in sorted({key[0] for key in values}):
            for seed in range(1, 6):
                mv = values.get((instance, seed, "MV-HGS-SP"))
                base = values.get((instance, seed, baseline))
                if mv is None or base is None:
                    continue
                differences.append(mv - base)
                paired_keys.append((instance, seed))
        statistic, p_value, nonzero, method = _wilcoxon_two_sided(differences)
        wins = sum(value < -EPS for value in differences)
        ties = sum(abs(value) <= EPS for value in differences)
        losses = sum(value > EPS for value in differences)
        mean_gain = statistics.fmean(
            100.0 * (base - mv) / base
            for instance, seed in paired_keys
            for mv, base in [(values[(instance, seed, "MV-HGS-SP")], values[(instance, seed, baseline)])]
        )
        median_gain = statistics.median(
            100.0 * (values[(instance, seed, baseline)] - values[(instance, seed, "MV-HGS-SP")])
            / values[(instance, seed, baseline)]
            for instance, seed in paired_keys
        )
        raw_pvalues.append(p_value)
        tests.append({
            "primary": "MV-HGS-SP",
            "baseline": baseline,
            "paired_units": len(differences),
            "nonzero_pairs": nonzero,
            "wins_mv_lower": wins,
            "ties": ties,
            "losses_mv_higher": losses,
            "mean_gain_pct": mean_gain,
            "median_gain_pct": median_gain,
            "wilcoxon_statistic": statistic,
            "wilcoxon_p_raw": p_value,
            "wilcoxon_method": method,
        })
    for row, adjusted in zip(tests, _holm(raw_pvalues), strict=True):
        row["wilcoxon_p_holm"] = adjusted
    return tests, {
        "family": "three global MV-HGS-SP versus single-view comparisons",
        "alternative": "two-sided",
        "zero_difference_rule": "discard absolute differences <= 1e-12",
        "holm_comparisons": 3,
        "note": "S2 HGS-E exception leaves 404 paired units for HGS-E and 405 for HGS-F/HGS-M.",
    }


def _tex_table4(rows: list[dict[str, str]]) -> str:
    return legacy._tex_table4(rows)


def _append_flag(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    flags = list(payload.get("integrity_flags", []))
    if APPLEDOUBLE_FLAG not in flags:
        flags.append(APPLEDOUBLE_FLAG)
    payload["integrity_flags"] = flags
    _write_json(path, payload)


def _clean_appledouble() -> bool:
    sidecars = [path for path in OUT.rglob("._*") if path.is_file()]
    for path in sidecars:
        path.unlink()
    return bool(sidecars)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    decision_path = OUT / "decision_v2.json"
    metadata_path = OUT / "metadata_v2.json"
    report_path = OUT / "report_v2.md"
    try:
        _preserve_v1_manifest()
        _require_pass(S1 / "decision.json", "PASS_S1_THREEVIEW_PREFLIGHT")
        s2_decision = json.loads(S2_DECISION_V2.read_text(encoding="utf-8"))
        if s2_decision.get("decision") != "PASS_S2_FULL_THREEVIEW_WITH_REGISTERED_INFEASIBLE_UNIT":
            raise RuntimeError(f"unexpected S2 v2 decision: {s2_decision.get('decision')!r}")
        _require_pass(S3 / "decision.json", "PASS_S3_REPRESENTATIVE")
        _require_pass(S4_DECISION_V2, "PASS_S4_ROUTE_DETAIL")
        _require_pass(P1_DECISION, "P1_FORMAL_PUBLIC_COMPLETE")
        s3_rows = _read_csv(S3 / "raw_runs.csv")
        if len(s3_rows) != 40:
            raise RuntimeError(f"S3 raw row count is {len(s3_rows)}, expected 40")
        s4_rows = _read_csv(S4_ROUTE_DETAILS_V2)
        if len(s4_rows) < 3:
            raise RuntimeError("S4 route detail CSV is too short")
        _, values, s2_context = _load_s2_records()
        tiers = s2_context["tiers"]
        instance_stats = _instance_statistics(tiers, values)
        summary, summary_fields = _summary_rows(instance_stats)
        tests, test_context = _pairwise_tests(values)
        table5, table5_fields = legacy._build_table5()
        table6, table6_fields = _table6_v2(s3_rows)

        shutil.copyfile(S4_ROUTE_DETAILS_V2, OUT / "table4_route_details_v2.csv")
        _write_csv(OUT / "table5_public_v2.csv", table5, table5_fields)
        _write_csv(OUT / "table6_representative_v2.csv", table6, table6_fields)
        _write_csv(OUT / "china81_summary_v2.csv", summary, summary_fields)
        _write_csv(OUT / "china81_pairwise_tests_v2.csv", tests, list(tests[0].keys()))
        (OUT / "table4_route_details_v2.tex").write_text(_tex_table4(s4_rows), encoding="utf-8")
        (OUT / "table5_public_v2.tex").write_text(legacy._tex_table5(table5), encoding="utf-8")
        (OUT / "table6_representative_v2.tex").write_text(_tex_table6_v2(table6), encoding="utf-8")
        (OUT / "china81_summary_v2.tex").write_text(_tex_summary(summary), encoding="utf-8")
        _plot_figure4_v2(s3_rows)

        decision = {
            "schema_version": "resetp.e2-final-campaign.s5-artifacts.v2",
            "decision": "PASS_S5_ARTIFACTS",
            "input_decisions": {
                "s1": "PASS_S1_THREEVIEW_PREFLIGHT",
                "s2": s2_decision["decision"],
                "s3": "PASS_S3_REPRESENTATIVE",
                "s4": "PASS_S4_ROUTE_DETAIL",
                "p1": "P1_FORMAL_PUBLIC_COMPLETE",
            },
            "v1_superseded_outputs_preserved": True,
            "appendix_a1_generated": False,
            "appendix_a1_v1_preserved_as_historical_evidence": True,
            "china81_summary_rows": len(summary),
            "china81_summary_structure": "3 city groups x 3 contiguous tier bands + Overall",
            "china81_instance_ledger_rows": 810,
            "table5_rows": len(table5),
            "table6_rows": len(table6),
            "table4_rows": len(s4_rows),
            "figure4_curve_count": 4,
            "algorithm_naming_map": {
                "cv_only": "HGS-F", "naive_ev": "HGS-E",
                "mechanism_ev": "HGS-M", "MV-HGS-SP": "MV-HGS-SP",
            },
            "s2_registered_exception": s2_context["exception"],
            "pairwise_test_context": test_context,
            "claim_boundary": "S5 is deterministic reporting materialization from sealed evidence; it authorizes no superiority, equal-compute, or model claim.",
        }
        _write_json(decision_path, decision)
        metadata = {
            "schema_version": "resetp.e2-final-campaign.s5-artifacts-metadata.v2",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "command": " ".join([sys.executable, *sys.argv]),
            "git_head": _git_head(),
            "branch": "codex/reporting-pipeline",
            "python": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "numpy_version": np.__version__,
            "matplotlib_version": matplotlib.__version__,
            "visual_contract_sha256": _sha256(VISUAL_CONTRACT),
            "input_sha256": {
                "s1_decision": _sha256(S1 / "decision.json"),
                "s2_decision_v2": _sha256(S2_DECISION_V2),
                "s2_raw": _sha256(S2 / "raw_runs.csv"),
                "s3_raw": _sha256(S3 / "raw_runs.csv"),
                "s4_decision_v2": _sha256(S4_DECISION_V2),
                "s4_route_details_v2": _sha256(S4_ROUTE_DETAILS_V2),
                "p1_decision": _sha256(P1_DECISION),
                "algorithm_naming_map": _sha256(ROOT / "docs/handoff/algorithm_naming_map_20260722.md"),
            },
            "scale_band_definition": [
                {"label": key, "tiers": list(tiers), "display": label}
                for key, label, tiers in SCALE_BANDS
            ],
            "s2_registered_exception_id": S2_EXCEPTION_ID,
            "s2_feasible_counts": {"HGS-F": "405/405", "HGS-E": "404/405", "HGS-M": "405/405", "MV-HGS-SP": "405/405"},
            "integrity_flags": [],
        }
        _write_json(metadata_path, metadata)
        report_path.write_text(
            "# S5 v2 unified artifacts\n\n"
            "Decision: `PASS_S5_ARTIFACTS` (v2). The earlier v1 materialization is preserved and superseded.\n\n"
            "## Scope\n\n"
            "This run is deterministic materialization from sealed S1/S2/S3/S4/P1 artifacts; it runs no solver and does not edit TeX or any protected evaluator. The v2 output contains Table 4, Table 5, renamed representative Table 6, renamed Figure 4, a 10-row China81 summary (three city groups × three contiguous tier bands plus Overall), and three global paired tests. It does not generate an A1 81-row appendix. The old v1 A1 files remain only as historical provenance.\n\n"
            "The nine sealed tiers are reported in contiguous bands S=(10,15,20), M=(25,50,75), and L=(100,150,200); this is an aggregation-only reporting rule and does not alter the raw ledger.\n\n"
            "## Naming and statistics\n\n"
            "The output maps `cv_only` to HGS-F, `naive_ev` to HGS-E, `mechanism_ev` to HGS-M, and retains MV-HGS-SP. China81 cells are means across instances of each instance's Best and seed-average exact costs. Pairwise tests compare MV-HGS-SP with each single-view arm at the common instance-seed level using a two-sided Wilcoxon signed-rank statistic with zero differences discarded, tie-corrected normal approximation, and three-comparison Holm adjustment.\n\n"
            f"The registered S2 exception `{S2_EXCEPTION_ID}` remains visible: HGS-E is feasible on 404/405 units, and its one affected instance uses four feasible seeds for Best/avg; the failed raw row was not rerun, replaced, filtered, or overwritten.\n\n"
            "Table 6 and Figure 4 are convergent-run quality/CPU disclosures, not equal-compute evidence.\n\n",
            encoding="utf-8",
        )
        contaminated = _clean_appledouble()
        if contaminated:
            _append_flag(decision_path)
            _append_flag(metadata_path)
            report_path.write_text(
                report_path.read_text(encoding="utf-8")
                + f"Integrity flag: {APPLEDOUBLE_FLAG}; AppleDouble sidecars were removed before hash refresh.\n",
                encoding="utf-8",
            )
        hash_paths = [
            OUT / "artifact_hashes_v1.json",
            OUT / "task_card_v2.md", OUT / "monitor_v3.json", OUT / "run_s5_artifacts_v2.py",
            OUT / "table4_route_details_v2.csv", OUT / "table4_route_details_v2.tex",
            OUT / "table5_public_v2.csv", OUT / "table5_public_v2.tex",
            OUT / "table6_representative_v2.csv", OUT / "table6_representative_v2.tex",
            OUT / "china81_summary_v2.csv", OUT / "china81_summary_v2.tex",
            OUT / "china81_pairwise_tests_v2.csv",
            OUT / "figure4_convergence_v2.pdf", OUT / "figure4_convergence_v2.png",
            OUT / "figure4_curve_data_v2.csv", metadata_path, decision_path, report_path,
        ]
        _write_json(OUT / "artifact_hashes.json", {
            "schema_version": "resetp.artifact-hashes.s5-v2",
            "algorithm": "sha256",
            "source_manifest_v1": "artifact_hashes_v1.json",
            "appledouble_excluded": True,
            "integrity_flags": json.loads(metadata_path.read_text(encoding="utf-8")).get("integrity_flags", []),
            "files": {
                str(path.relative_to(ROOT)): _sha256(path)
                for path in hash_paths
                if path.is_file() and not path.name.startswith("._")
            },
        })
        _write_json(OUT / "done_v2.json", {
            "decision": "PASS_S5_ARTIFACTS",
            "artifact_hashes": "artifact_hashes.json",
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        _write_json(decision_path, {
            "schema_version": "resetp.e2-final-campaign.s5-artifacts.v2",
            "decision": "HALT_S5_INPUT_GATE",
            "error_type": type(exc).__name__,
            "error": str(exc),
        })
        print(f"[S5 v2] HALT_S5_INPUT_GATE: {exc}", file=sys.stderr, flush=True)
        return 2
    print("[S5 v2] PASS_S5_ARTIFACTS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
