#!/usr/bin/env python3
"""S5: generate sealed E2 tables, Appendix A1, and Figure 4."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
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

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
S1 = ROOT / "baselines/e2_final_campaign_20260720/p2p3_threeview/preflight_gate"
S2 = ROOT / "baselines/e2_final_campaign_20260720/p2p3_threeview/full_gate"
S3 = ROOT / "baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate"
S4 = ROOT / "baselines/e2_final_campaign_20260720/p2p3_threeview/table4_gate"
P1 = ROOT / "baselines/e2_final_campaign_20260720/mv_hgs_sp_final/p1_formal_gate"
VISUAL_CONTRACT = ROOT / "docs/paper_submission_final/e2_e3_preview_20260714/SETP_VISUAL_CONTRACT.md"
P1_DECISION = P1 / "decision.json"
ARMS = ("cv_only", "naive_ev", "mechanism_ev", "MV-HGS-SP")


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


def _build_table5() -> tuple[list[dict[str, Any]], list[str]]:
    decision = json.loads(P1_DECISION.read_text(encoding="utf-8"))
    p1_rows = _read_csv(P1 / "raw_runs.csv")
    hybrid_by_instance: dict[str, list[float]] = defaultdict(list)
    for row in p1_rows:
        hybrid_by_instance[row["instance_id"]].append(float(row["hybrid_cost"]))
    fields = [
        "instance", "n", "BKS", "VCGP_error_pct", "MDFIHA_error_pct",
        "ETGA_error_pct", "MV-HGS-SP_Best", "MV-HGS-SP_Avg",
        "MV-HGS-SP_Best_error_pct", "MV-HGS-SP_Avg_error_pct",
    ]
    rows: list[dict[str, Any]] = []
    for item in decision["table5"]:
        values = hybrid_by_instance.get(item["instance"], [])
        if len(values) != 10:
            raise RuntimeError(f"P1 instance {item['instance']} has {len(values)} raw rows, expected 10")
        avg = statistics.fmean(values)
        bks = float(item["bks"])
        rows.append({
            "instance": item["instance"], "n": item["n"], "BKS": bks,
            "VCGP_error_pct": item["vcgp_error_pct"], "MDFIHA_error_pct": item["mdfiha_error_pct"],
            "ETGA_error_pct": item["etga_error_pct"], "MV-HGS-SP_Best": item["hybrid_best"],
            "MV-HGS-SP_Avg": avg,
            "MV-HGS-SP_Best_error_pct": item["hybrid_error_pct"],
            "MV-HGS-SP_Avg_error_pct": 100.0 * (avg - bks) / bks,
        })
    return rows, fields


def _tex_table5(rows: list[dict[str, Any]]) -> str:
    lines = [
        r"\begin{tabular}{lrrrrrrrr}", r"\toprule",
        r"实例 & $n$ & BKS & VCGP误差/\% & MDFIHA误差/\% & ETGA误差/\% & MV-HGS-SP Best & Avg & Best/Avg误差/\% \\",
        r"\midrule",
    ]
    for row in rows:
        lines.append(
            f"{row['instance']} & {int(row['n'])} & {row['BKS']:.3f} & {row['VCGP_error_pct']:.3f} & "
            f"{row['MDFIHA_error_pct']:.3f} & {row['ETGA_error_pct']:.3f} & {row['MV-HGS-SP_Best']:.3f} & "
            f"{row['MV-HGS-SP_Avg']:.3f} & {row['MV-HGS-SP_Best_error_pct']:.3f}/{row['MV-HGS-SP_Avg_error_pct']:.3f}" + r" \\",
        )
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    return "\n".join(lines) + "\n"


def _build_table6(s3_rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    for seed in range(1, 11):
        row: dict[str, Any] = {"row": str(seed)}
        for arm in ARMS:
            match = [item for item in s3_rows if int(item["seed"]) == seed and item["arm"] == arm and item["status"] == "OK"]
            if len(match) != 1:
                raise RuntimeError(f"S3 table6 row missing/duplicated seed={seed}, arm={arm}")
            row[f"{arm}_cost"] = float(match[0]["cost"])
            row[f"{arm}_cpu_seconds"] = float(match[0]["cpu_seconds"])
        rows.append(row)
    for label, fn in (("Min", min), ("Avg", statistics.fmean), ("Max", max)):
        row = {"row": label}
        for arm in ARMS:
            values = [float(item[f"{arm}_cost"]) for item in rows[:10]]
            cpus = [float(item[f"{arm}_cpu_seconds"]) for item in rows[:10]]
            row[f"{arm}_cost"] = fn(values)
            row[f"{arm}_cpu_seconds"] = fn(cpus)
        rows.append(row)
    fields = ["row"] + [f"{arm}_{metric}" for arm in ARMS for metric in ("cost", "cpu_seconds")]
    return rows, fields


def _tex_table6(rows: list[dict[str, Any]]) -> str:
    lines = [
        r"\begin{tabular}{lrrrrrrrr}", r"\toprule",
        "行 & " + " & ".join(f"{arm} (值/CPU s)" for arm in ARMS) + r" \\",
        r"\midrule",
    ]
    for row in rows:
        cells = [f"{row[f'{arm}_cost']:.3f}/{row[f'{arm}_cpu_seconds']:.2f}" for arm in ARMS]
        lines.append(str(row["row"]) + " & " + " & ".join(cells) + r" \\")
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    return "\n".join(lines) + "\n"


def _tex_table4(rows: list[dict[str, str]]) -> str:
    lines = [
        r"\begin{tabular}{lrrrrrrrr}", r"\toprule",
        "路径 & 距离/km & 成本/元 & 时间/h & 油耗/L & 电耗/kWh & 碳排放/kg & num & 装载率/\\% " + r" \\",
        r"\midrule",
    ]
    for row in rows:
        lines.append(
            f"{row['路径']} & {float(row['距离(km)']):.3f} & {float(row['成本(元)']):.3f} & {float(row['时间(h)']):.3f} & "
            f"{float(row['油耗(L)']):.3f} & {float(row['电耗(kWh)']):.3f} & {float(row['碳排放(kg)']):.3f} & "
            f"{float(row['num(满足时窗客户数)']):.0f} & {float(row['装载率(%)']):.2f}" + r" \\",
        )
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    return "\n".join(lines) + "\n"


def _trajectory_curve(s3_rows: list[dict[str, str]], arm: str) -> tuple[np.ndarray, np.ndarray]:
    paths = [S3 / row["trajectory_file"] for row in s3_rows if row["arm"] == arm and row["status"] == "OK"]
    if len(paths) != 10 or any(not path.is_file() for path in paths):
        raise RuntimeError(f"S3 trajectory set incomplete for {arm}")
    payloads = [json.loads(path.read_text(encoding="utf-8"))["points"] for path in paths]
    max_time = max(float(point["elapsed_seconds"]) for points in payloads for point in points)
    grid = np.linspace(0.0, max_time, 180)
    values = []
    for points in payloads:
        points = sorted(points, key=lambda item: float(item["elapsed_seconds"]))
        curve = []
        for t in grid:
            eligible = [float(point["cost"]) for point in points if float(point["elapsed_seconds"]) <= t + 1.0e-9]
            curve.append(min(eligible) if eligible else float(points[0]["cost"]))
        values.append(curve)
    return grid / 60.0, np.median(np.asarray(values, dtype=float), axis=0)


def _plot_figure4(s3_rows: list[dict[str, str]]) -> None:
    plt.rcParams.update({
        "font.family": ["Times New Roman", "Songti SC"], "font.size": 8.0,
        "axes.labelsize": 8.0, "xtick.labelsize": 7.2, "ytick.labelsize": 7.2,
        "legend.fontsize": 7.0, "axes.unicode_minus": False,
        "figure.facecolor": "white", "axes.facecolor": "white",
        "pdf.fonttype": 42, "ps.fonttype": 42,
    })
    fig, ax = plt.subplots(figsize=(4.30, 2.80))
    styles = [
        ("cv_only", "cv-only", "#1F77B4", "-"),
        ("naive_ev", "naive-EV", "#D55E00", "--"),
        ("mechanism_ev", "mechanism-EV", "#2CA02C", ":"),
        ("MV-HGS-SP", "MV-HGS-SP", "#9467BD", "-."),
    ]
    curve_rows: list[dict[str, Any]] = []
    for arm, label, color, linestyle in styles:
        x, y = _trajectory_curve(s3_rows, arm)
        ax.plot(x, y, color=color, linestyle=linestyle, linewidth=0.62, drawstyle="steps-post", label=label)
        curve_rows.extend({"arm": arm, "time_min": float(xx), "median_exact_cost": float(yy)} for xx, yy in zip(x, y, strict=True))
    finite_y = [row["median_exact_cost"] for row in curve_rows if math.isfinite(row["median_exact_cost"])]
    ymin, ymax = min(finite_y), max(finite_y)
    margin = max((ymax - ymin) * 0.05, 1.0)
    ax.set_xlim(left=0.0)
    ax.set_ylim(ymin - margin, ymax + margin)
    ax.set_xlabel("Time (min)")
    ax.set_ylabel("Cost (CNY)")
    ax.grid(False)
    ax.legend(loc="upper right", frameon=True, fancybox=False, edgecolor="#777777", framealpha=1.0, borderpad=0.2, handlelength=1.7)
    ax.tick_params(direction="out", length=2.0, width=0.468)
    for spine in ax.spines.values():
        spine.set_linewidth(0.468)
    fig.subplots_adjust(left=0.14, right=0.985, bottom=0.18, top=0.975)
    fig.savefig(OUT / "figure4_convergence.pdf", bbox_inches="tight")
    fig.savefig(OUT / "figure4_convergence.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    _write_csv(OUT / "figure4_curve_data.csv", curve_rows, ["arm", "time_min", "median_exact_cost"])


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        _require_pass(S1 / "decision.json", "PASS_S1_THREEVIEW_PREFLIGHT")
        _require_pass(S2 / "decision.json", "PASS_S2_FULL_THREEVIEW")
        _require_pass(S3 / "decision.json", "PASS_S3_REPRESENTATIVE")
        _require_pass(S4 / "decision.json", "PASS_S4_ROUTE_DETAIL")
        p1_decision = json.loads(P1_DECISION.read_text(encoding="utf-8"))
        if p1_decision.get("decision") != "P1_FORMAL_PUBLIC_COMPLETE":
            raise RuntimeError(f"P1 decision is {p1_decision.get('decision')!r}")
        s3_rows = _read_csv(S3 / "raw_runs.csv")
        if len(s3_rows) != 40:
            raise RuntimeError(f"S3 raw row count is {len(s3_rows)}, expected 40")
        s4_rows = _read_csv(S4 / "route_details.csv")
        if len(s4_rows) < 3:
            raise RuntimeError("S4 route detail CSV is too short")
        table5, table5_fields = _build_table5()
        table6, table6_fields = _build_table6(s3_rows)
        shutil.copyfile(S4 / "route_details.csv", OUT / "table4_route_details.csv")
        shutil.copyfile(S2 / "appendix_a1.csv", OUT / "appendix_a1.csv")
        shutil.copyfile(S2 / "appendix_a1_numeric.csv", OUT / "appendix_a1_numeric.csv")
        _write_csv(OUT / "table5_public.csv", table5, table5_fields)
        _write_csv(OUT / "table6_representative.csv", table6, table6_fields)
        (OUT / "table4_route_details.tex").write_text(_tex_table4(s4_rows), encoding="utf-8")
        (OUT / "table5_public.tex").write_text(_tex_table5(table5), encoding="utf-8")
        (OUT / "table6_representative.tex").write_text(_tex_table6(table6), encoding="utf-8")
        _plot_figure4(s3_rows)
        decision = {
            "schema_version": "resetp.e2-final-campaign.s5-artifacts.v1",
            "decision": "PASS_S5_ARTIFACTS",
            "input_decisions": {
                "s1": "PASS_S1_THREEVIEW_PREFLIGHT", "s2": "PASS_S2_FULL_THREEVIEW",
                "s3": "PASS_S3_REPRESENTATIVE", "s4": "PASS_S4_ROUTE_DETAIL",
                "p1": "P1_FORMAL_PUBLIC_COMPLETE",
            },
            "table5_rows": len(table5), "table6_rows": len(table6),
            "table4_rows": len(s4_rows), "appendix_a1_rows": len(_read_csv(OUT / "appendix_a1.csv")),
            "figure4_curve_count": 4,
            "claim_boundary": "S5 is deterministic table/figure materialization from sealed evidence. It does not modify TeX or create a superiority/equal-compute claim.",
        }
    except Exception as exc:
        decision = {
            "schema_version": "resetp.e2-final-campaign.s5-artifacts.v1",
            "decision": "HALT_S5_INPUT_GATE", "error_type": type(exc).__name__, "error": str(exc),
        }
        _write_json(OUT / "decision.json", decision)
        return 2
    _write_json(OUT / "decision.json", decision)
    metadata = {
        "schema_version": "resetp.e2-final-campaign.s5-artifacts-metadata.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": " ".join([sys.executable, *sys.argv]), "git_head": _git_head(),
        "branch": "codex/reporting-pipeline", "python": sys.version,
        "python_executable": sys.executable, "platform": platform.platform(),
        "numpy_version": np.__version__, "matplotlib_version": matplotlib.__version__,
        "visual_contract_sha256": _sha256(VISUAL_CONTRACT),
        "input_sha256": {
            "s1_decision": _sha256(S1 / "decision.json"), "s2_raw": _sha256(S2 / "raw_runs.csv"),
            "s3_raw": _sha256(S3 / "raw_runs.csv"), "s4_route_details": _sha256(S4 / "route_details.csv"),
            "p1_decision": _sha256(P1_DECISION),
        },
        "integrity_flags": [],
    }
    _write_json(OUT / "metadata.json", metadata)
    (OUT / "report.md").write_text(
        "# S5 Unified artifacts\n\n"
        "Decision: `PASS_S5_ARTIFACTS`.\n\n"
        f"Generated Table 4 ({decision['table4_rows']} rows), Table 5 ({decision['table5_rows']} rows), Table 6 ({decision['table6_rows']} rows), Figure 4 (4 median exact-incumbent curves), and Appendix A1 ({decision['appendix_a1_rows']} rows) from sealed inputs.\n\n"
        "No TeX semantic section was edited and no value was manually filled. Figure 4 uses step-wise medians over ten seeds and exact-cost trajectory observations.\n",
        encoding="utf-8",
    )
    hash_paths = [
        OUT / "task_card.md", OUT / "run_s5_artifacts.py", OUT / "table4_route_details.csv",
        OUT / "table4_route_details.tex", OUT / "table5_public.csv", OUT / "table5_public.tex",
        OUT / "table6_representative.csv", OUT / "table6_representative.tex", OUT / "appendix_a1.csv",
        OUT / "appendix_a1_numeric.csv", OUT / "figure4_convergence.pdf", OUT / "figure4_convergence.png",
        OUT / "figure4_curve_data.csv", OUT / "metadata.json", OUT / "decision.json", OUT / "report.md",
    ]
    _write_json(OUT / "artifact_hashes.json", {
        "schema_version": "resetp.artifact-hashes.v1", "algorithm": "sha256",
        "appledouble_excluded": True,
        "files": {str(path.relative_to(ROOT)): _sha256(path) for path in hash_paths if path.exists() and not path.name.startswith("._")},
    })
    _write_json(OUT / "done.json", {"decision": "PASS_S5_ARTIFACTS", "artifact_hashes": "artifact_hashes.json", "completed_at_utc": datetime.now(timezone.utc).isoformat()})
    print("[S5] PASS_S5_ARTIFACTS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
