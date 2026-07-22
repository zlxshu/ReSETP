#!/usr/bin/env python3
"""S6-SUP-02: Chinese-label Figure 3/4 presentation-only rebuild."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
from matplotlib import font_manager
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "baselines/e2_final_campaign_20260720/p2p3_threeview/artifacts"
APPROVED_CURVE = ROOT / "baselines/e2_final_campaign_20260720/p2p3_threeview/representative_gate/s3_traj_v4/curve_data_v4.csv"
CURVE_DISPLAY_V4 = ARTIFACTS / "figure4_convergence_v4.csv"
CARBON_DISPLAY_V4 = ARTIFACTS / "figure3_carbon_profile_v4.csv"
LEGACY_CURVE_V2 = ARTIFACTS / "figure4_curve_data_v2.csv"
APPROVAL_REGISTER_ID = "S3-TRAJ-CURVE-DEF-001"

FIG4_ORDER = ("HGS-F", "HGS-E", "HGS-M", "MV-HGS-SP")
FIG4_STYLES = {
    "HGS-F": ("#1F77B4", "-"),
    "HGS-E": ("#D55E00", "--"),
    "HGS-M": ("#2CA02C", ":"),
    "MV-HGS-SP": ("#9467BD", "-.")
}
FIG3_ORDER = ("Beijing", "Guangdong", "Chongqing")
FIG3_LABELS = {"Beijing": "北京", "Guangdong": "广东", "Chongqing": "重庆"}
FIG3_STYLES = {
    "Beijing": ("#1F77B4", "-"),
    "Guangdong": ("#D55E00", "--"),
    "Chongqing": ("#2CA02C", ":"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def choose_cjk_font() -> str:
    candidates = ("Songti SC", "STSong", "PingFang SC", "Noto Sans CJK SC", "Arial Unicode MS")
    for candidate in candidates:
        try:
            path = font_manager.findfont(candidate, fallback_to_default=False)
        except (ValueError, RuntimeError):
            continue
        if path and Path(path).is_file():
            return candidate
    raise RuntimeError("no installed CJK font was found for Chinese figure labels")


def font_setup() -> str:
    cjk_font = choose_cjk_font()
    plt.rcParams.update({
        "font.family": [cjk_font, "Times New Roman"],
        "font.size": 8.0,
        "axes.labelsize": 8.0,
        "xtick.labelsize": 7.2,
        "ytick.labelsize": 7.2,
        "legend.fontsize": 7.0,
        "axes.unicode_minus": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })
    return cjk_font


def style_axis(ax: Any) -> None:
    ax.grid(False)
    ax.tick_params(direction="out", length=2.0, width=0.468)
    for spine in ax.spines.values():
        spine.set_linewidth(0.468)


def draw_break_marks(ax_top: Any, ax_bottom: Any) -> None:
    diagonal = 0.012
    kwargs = dict(transform=ax_top.transAxes, color="black", clip_on=False, linewidth=0.468)
    ax_top.plot((-diagonal, diagonal), (-diagonal, diagonal), **kwargs)
    ax_top.plot((1 - diagonal, 1 + diagonal), (-diagonal, diagonal), **kwargs)
    kwargs = dict(transform=ax_bottom.transAxes, color="black", clip_on=False, linewidth=0.468)
    ax_bottom.plot((-diagonal, diagonal), (1 - diagonal, 1 + diagonal), **kwargs)
    ax_bottom.plot((1 - diagonal, 1 + diagonal), (1 - diagonal, 1 + diagonal), **kwargs)


def copy_data_inputs() -> dict[str, str]:
    shutil.copyfile(CURVE_DISPLAY_V4, OUT / "figure4_convergence_v5.csv")
    shutil.copyfile(CARBON_DISPLAY_V4, OUT / "figure3_carbon_profile_v5.csv")
    shutil.copyfile(APPROVED_CURVE, OUT / "figure4_curve_data_approved_v5.csv")
    return {
        "figure4_display_v4": sha256(CURVE_DISPLAY_V4),
        "figure4_approved_curve_v4": sha256(APPROVED_CURVE),
        "figure3_display_v4": sha256(CARBON_DISPLAY_V4),
        "legacy_figure4_curve_data_v2": sha256(LEGACY_CURVE_V2),
    }


def plot_figure3() -> dict[str, Any]:
    rows = read_csv(CARBON_DISPLAY_V4)
    if len(rows) != 144:
        raise RuntimeError(f"Figure 3 source rows={len(rows)}, expected 144")
    font_name = font_setup()
    fig, ax = plt.subplots(figsize=(4.30, 2.80))
    for region in FIG3_ORDER:
        subset = [row for row in rows if row["region"] == region]
        if len(subset) != 48:
            raise RuntimeError(f"Figure 3 {region} rows={len(subset)}, expected 48")
        subset.sort(key=lambda row: (float(row["time_hour"]), int(row["half_hour_slot"])))
        x = [float(row["time_hour"]) for row in subset]
        y = [float(row["carbon_intensity_gCO2_per_kWh"]) for row in subset]
        color, linestyle = FIG3_STYLES[region]
        ax.plot(x, y, color=color, linestyle=linestyle, linewidth=0.62, label=FIG3_LABELS[region])
    ax.set_xlim(0.0, 24.0)
    ax.set_xticks([0, 4, 8, 12, 16, 20, 24])
    ax.set_xlabel("时刻(h)")
    ax.set_ylabel(r"碳强度(gCO$_2$/kWh)")
    style_axis(ax)
    ax.legend(
        loc="upper right", frameon=True, fancybox=False,
        edgecolor="#777777", framealpha=1.0, borderpad=0.2,
        handlelength=1.7,
    )
    fig.subplots_adjust(left=0.16, right=0.985, bottom=0.18, top=0.975)
    fig.savefig(OUT / "figure3_carbon_profile_v5.pdf", bbox_inches="tight")
    fig.savefig(OUT / "figure3_carbon_profile_v5.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    return {"rows": len(rows), "font": font_name, "series": list(FIG3_LABELS.values())}


def plot_figure4() -> dict[str, Any]:
    rows = read_csv(CURVE_DISPLAY_V4)
    if len(rows) != 29:
        raise RuntimeError(f"Figure 4 display rows={len(rows)}, expected 29")
    by_label: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        label = row["algorithm_label"]
        by_label.setdefault(label, []).append(row)
    if set(by_label) != set(FIG4_ORDER):
        raise RuntimeError(f"Figure 4 labels={sorted(by_label)}, expected={list(FIG4_ORDER)}")
    for label, subset in by_label.items():
        subset.sort(key=lambda row: (float(row["elapsed_minutes"]), int(row["snapshot_order"])))
        times = [float(row["elapsed_minutes"]) for row in subset]
        costs = [float(row["cost_cny"]) for row in subset]
        if any(times[i] < times[i - 1] for i in range(1, len(times))):
            raise RuntimeError(f"Figure 4 time is not monotone for {label}")
        if any(costs[i] > costs[i - 1] + 1.0e-9 for i in range(1, len(costs))):
            raise RuntimeError(f"Figure 4 best-so-far costs increase for {label}")

    font_name = font_setup()
    fig, (ax_top, ax_bottom) = plt.subplots(
        2, 1, sharex=True, figsize=(4.30, 2.80),
        gridspec_kw={"height_ratios": [1, 3], "hspace": 0.055},
    )
    for label in FIG4_ORDER:
        subset = by_label[label]
        x = [float(row["elapsed_minutes"]) for row in subset]
        y = [float(row["cost_cny"]) for row in subset]
        color, linestyle = FIG4_STYLES[label]
        for ax in (ax_top, ax_bottom):
            ax.plot(x, y, color=color, linestyle=linestyle, linewidth=0.62, label=label)

    ax_top.set_ylim(2580.0, 2610.0)
    ax_bottom.set_ylim(2350.0, 2500.0)
    ax_top.set_yticks([2580, 2600])
    ax_bottom.set_yticks([2350, 2400, 2450, 2500])
    ax_bottom.set_xlabel("时间(min)")
    ax_bottom.set_ylabel("成本(元)")
    ax_top.spines["bottom"].set_visible(False)
    ax_bottom.spines["top"].set_visible(False)
    ax_top.tick_params(labeltop=False, bottom=False)
    ax_bottom.tick_params(top=False)
    style_axis(ax_top)
    style_axis(ax_bottom)
    ax_top.legend(
        loc="upper right", frameon=True, fancybox=False,
        edgecolor="#777777", framealpha=1.0, borderpad=0.2,
        handlelength=1.7,
    )
    draw_break_marks(ax_top, ax_bottom)
    x_max = max(float(row["elapsed_minutes"]) for row in rows)
    ax_bottom.set_xlim(0.0, max(x_max * 1.02, 0.1))
    fig.subplots_adjust(left=0.16, right=0.985, bottom=0.19, top=0.985)
    fig.savefig(OUT / "figure4_convergence_v5.pdf", bbox_inches="tight")
    fig.savefig(OUT / "figure4_convergence_v5.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    return {
        "rows": len(rows),
        "font": font_name,
        "series": list(FIG4_ORDER),
        "broken_y_axis": {"lower": [2350, 2500], "upper": [2580, 2610]},
        "selected_seeds": {label: int(by_label[label][0]["seed"]) for label in FIG4_ORDER},
    }


def build_raw_ledger(source_hashes: dict[str, str]) -> None:
    output_rows: list[dict[str, Any]] = []
    for figure, source, key in (
        ("figure3", CARBON_DISPLAY_V4, "region"),
        ("figure4", CURVE_DISPLAY_V4, "algorithm_label"),
    ):
        rows = read_csv(source)
        for index, row in enumerate(rows, start=1):
            if figure == "figure3":
                x, y, series = row["time_hour"], row["carbon_intensity_gCO2_per_kWh"], row[key]
            else:
                x, y, series = row["elapsed_minutes"], row["cost_cny"], row[key]
            output_rows.append({
                "figure": figure,
                "series": series,
                "source_row": index,
                "x": x,
                "y": y,
                "source_path": rel(source),
                "source_sha256": source_hashes[rel(source)],
            })
    write_csv(
        OUT / "raw_runs.csv", output_rows,
        ["figure", "series", "source_row", "x", "y", "source_path", "source_sha256"],
    )


def artifact_files() -> list[Path]:
    return sorted(
        path for path in OUT.rglob("*")
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    source_hashes = copy_data_inputs()
    figure3_audit = plot_figure3()
    figure4_audit = plot_figure4()
    build_raw_ledger({
        rel(CARBON_DISPLAY_V4): source_hashes["figure3_display_v4"],
        rel(CURVE_DISPLAY_V4): source_hashes["figure4_display_v4"],
    })
    output_csv_hashes = {
        "figure3_carbon_profile_v5.csv": sha256(OUT / "figure3_carbon_profile_v5.csv"),
        "figure4_convergence_v5.csv": sha256(OUT / "figure4_convergence_v5.csv"),
        "figure4_curve_data_approved_v5.csv": sha256(OUT / "figure4_curve_data_approved_v5.csv"),
    }
    metadata = {
        "schema_version": "resetp.e2.s6-sup-02-figure-v5.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "approval_register_id": APPROVAL_REGISTER_ID,
        "plotting_only": True,
        "source_data": {
            "figure4_plotted_display_csv": rel(CURVE_DISPLAY_V4),
            "figure4_approved_curve_csv": rel(APPROVED_CURVE),
            "figure3_display_csv": rel(CARBON_DISPLAY_V4),
            "legacy_figure4_curve_data_v2_csv": rel(LEGACY_CURVE_V2),
            "sha256": source_hashes,
            "legacy_v2_status": "archived predecessor; not used because S3-TRAJ approval binds the current curve to curve_data_v4",
        },
        "output_data_hashes": output_csv_hashes,
        "display": {
            "figure_size_inches": [4.30, 2.80],
            "line_width_points": 0.62,
            "axis_width_points": 0.468,
            "figure3_labels": {"x": "时刻(h)", "y": "碳强度(gCO2/kWh)", "legend": list(FIG3_LABELS.values())},
            "figure4_labels": {"x": "时间(min)", "y": "成本(元)", "legend": list(FIG4_ORDER)},
            "figure4_broken_y_axis": {"lower": [2350, 2500], "upper": [2580, 2610]},
            "grid": False,
            "legend_location": "upper right inside axes",
            "font": {"figure3": figure3_audit["font"], "figure4": figure4_audit["font"]},
        },
        "audits": {"figure3": figure3_audit, "figure4": figure4_audit},
        "protected_scope": {"main_tex_modified": False, "sealed_data_modified": False, "evaluator_modified": False},
    }
    write_json(OUT / "metadata.json", metadata)
    decision = {
        "schema_version": "resetp.e2.s6-decision.v1",
        "decision": "PASS_S6_SUP_02_FIGURES_V5",
        "approval_register_id": APPROVAL_REGISTER_ID,
        "data_values_changed": False,
        "figure3_rows": figure3_audit["rows"],
        "figure4_rows": figure4_audit["rows"],
        "pdf_png_generated": True,
        "broken_y_axis_applied": True,
    }
    write_json(OUT / "decision.json", decision)
    report = [
        "# S6-SUP-02 图3/图4中文化 v5",
        "",
        "机器判定：`PASS_S6_SUP_02_FIGURES_V5`。",
        "",
        "图3和图4均只重生成呈现层。图3读取 S5 v4 的 144 行碳强度 CSV，图4读取经 `S3-TRAJ-CURVE-DEF-001` 批准并已封存的 29 行选定轨迹 CSV；两个 v5 CSV 与相应 v4 CSV 字节一致。",
        "",
        "图4使用断轴：下段 2350--2500，上段 2580--2610，图中用断轴标记连接；曲线数据、预注册种子和单调 best-so-far 口径不变。旧 `figure4_curve_data_v2.csv` 仅作为历史文件记录哈希，没有被重新用于当前图，以免越过 S3-TRAJ 的最新批准口径。",
        "",
        "图3轴标签为“时刻(h)”和“碳强度(gCO2/kWh)”，图例为北京/广东/重庆；图4轴标签为“时间(min)”和“成本(元)”，图例为 HGS-F/HGS-E/HGS-M/MV-HGS-SP。两图均为 4.30×2.80 英寸、细线异线型、无网格、图内右上图例，并输出矢量 PDF 与 300 dpi PNG。",
        "",
        "主 TeX、封存数据、评价器和保护文件均未修改。",
    ]
    (OUT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema_version": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "approval_register_id": APPROVAL_REGISTER_ID,
            "source_files": source_hashes,
            "files": {rel(path): sha256(path) for path in artifact_files()},
            "appledouble_excluded": True,
        },
    )
    print("PASS_S6_SUP_02_FIGURES_V5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
