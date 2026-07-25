"""Paper-facing chart adapter for future China E3--E7 results.

No figure is emitted when the input contains no sealed formal result rows.
That behaviour is deliberate: a blank chart is still a misleading artifact.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

try:
    from .contract import ROOT, load_contract, read_csv
    from .e3_exhibits import (
        REGION_LABELS,
        REGIONS,
        SIZE_LAYERS,
        build_e3_cell_rows,
        build_e3_layer_rows,
    )
except ImportError:  # pragma: no cover - direct script compatibility
    from contract import ROOT, load_contract, read_csv
    from e3_exhibits import (
        REGION_LABELS,
        REGIONS,
        SIZE_LAYERS,
        build_e3_cell_rows,
        build_e3_layer_rows,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def figure_specs(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "resetp.china.e3-e7-figure-specs.v2",
        "global": {
            "font_family": "Songti SC with Times New Roman fallback",
            "font_size_pt": 8.0,
            "axis_line_width_pt": 0.468,
            "bar_edge_width_pt": 0.45,
            "figure_size_in": [4.30, 2.80],
            "figure_policy": "只从正式 raw_runs 和独立复算结果生成；无结果时不生成 PDF/PNG。",
            "caption_policy": "中文学术图题，不写内部 F/E 编号；坐标范围使用预先固定的含零点留白规则，不按结论方向改轴。",
            "reference_shell": {
                "paper": "陈婉茹等（2023）",
                "figure": "图5",
                "use": "并列分组柱、颜色与纹理双重编码、细边框",
            },
            "palette": {
                "jjj": "#4C78A8",
                "prd": "#F2A65A",
                "cy": "#8A8A8A",
            }
        },
        "families": {
            "E3": {
                "analytical_question": "解除责任锁并允许双向跨场协同后，三个城市群在小、中、大规模层的总成本是否下降。",
                "form": "grouped_bar_from_nine_region_layer_rows",
                "output_stem": "e3_responsibility",
                "source_grain": "810 formal rows -> 27 paired region-size cells -> 9 display rows",
                "x": "客户规模",
                "y": "成本降低(%)",
                "x_categories": [
                    layer for layer, _sizes in SIZE_LAYERS
                ],
                "series": [
                    REGION_LABELS[region] for region in REGIONS
                ],
                "axis_rule": "纵轴必须包含0；上下界由全部9个柱值按同一12%留白公式一次性计算；禁止断轴。",
                "caption": "责任错配与跨场协同的配对成本变化",
            },
            "E4": {
                "form": "paired_effect_with_day_distribution",
                "output_stem": "e4_charging",
                "x": "地区/电网日",
                "y": "充电侧排放变化(%)",
                "caption": "碳感知充电择时的充电侧排放变化",
                "diagnostic_record_type": "daily_replay",
                "calendar_panel_days": 28,
            },
            "E5": {
                "form": "feasibility_and_cost_two_panel",
                "output_stem": "e5_physics",
                "x": "运行臂",
                "y": "可行率与完整模型成本",
                "caption": "非线性充电物理对可行性与成本的影响"
            },
            "E6": {
                "form": "cost_fairness_frontier",
                "output_stem": "e6_fairness",
                "x": "最低成员收益/公平约束",
                "y": "系统成本变化",
                "caption": "公平参与约束的系统成本—成员收益边界"
            },
            "E7": {
                "form": "dynamic_interaction_panel",
                "output_stem": "e7_interaction",
                "x": "滚动阶段",
                "y": "成本、排放、协同与公平诊断",
                "caption": "动态需求下协同、公平与时变碳机制的交互诊断",
                "diagnostic_record_type": "stage_diagnostic",
                "calendar_panel_days": 28,
            }
        },
        "source_families": [family["id"] for family in contract["families"]],
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_status(path: Path, payload: Any) -> None:
    _write_json(path, payload)


def _write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def _released(
    raw_path: Path,
    aggregate_dir: Path,
) -> tuple[bool, str]:
    decision_path = aggregate_dir / "decision.json"
    certificate_path = (
        aggregate_dir / "independent_recalc_certificate.json"
    )
    if not decision_path.is_file() or not certificate_path.is_file():
        return False, "independent recalc decision/certificate is absent"
    try:
        decision = json.loads(
            decision_path.read_text(encoding="utf-8")
        )
        certificate = json.loads(
            certificate_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"cannot read independent recalc release: {exc}"
    if (
        decision.get("status") != "AGGREGATE_READY_FOR_REVIEW"
        or decision.get("independent_recalc_complete") is not True
    ):
        return False, "aggregate decision has not released E3 evidence"
    if (
        certificate.get("status") != "PASS_INDEPENDENT_RECALC"
        or certificate.get("task_count") != 810
        or certificate.get("pair_count") != 405
        or certificate.get("raw_runs_sha256") != _sha256(raw_path)
    ):
        return False, "independent recalc certificate does not bind the 810-row raw file"
    return True, "PASS"


def _choose_cjk_font() -> str:
    from matplotlib import font_manager  # type: ignore

    candidates = (
        "Songti SC",
        "STSong",
        "SimSun",
        "Noto Serif CJK SC",
        "PingFang SC",
    )
    for candidate in candidates:
        try:
            font_manager.findfont(
                candidate,
                fallback_to_default=False,
            )
        except ValueError:
            continue
        return candidate
    raise RuntimeError(
        "no approved CJK font is installed for E3 paper figures"
    )


def _axis_limits(values: list[float]) -> tuple[float, float]:
    """Return an honest, deterministic, zero-inclusive bar-chart domain."""

    if not values or any(not math.isfinite(value) for value in values):
        raise ValueError("E3 figure has no finite bar values")
    lower = min(0.0, min(values))
    upper = max(0.0, max(values))
    span = upper - lower
    if span <= 1.0e-12:
        return -1.0, 1.0
    padding = 0.12 * span
    if lower < 0:
        lower -= padding
    if upper > 0:
        upper += padding
    return lower, upper


def _plot_e3(
    rows: list[dict[str, str]],
    output_dir: Path,
    spec: dict[str, Any],
) -> dict[str, Any]:
    try:
        import matplotlib.pyplot as plt  # type: ignore
    except ImportError as exc:
        return {
            "family": "E3",
            "status": "HALT_MATPLOTLIB_MISSING",
            "reason": str(exc),
        }
    cell_rows = build_e3_cell_rows(rows)
    layer_rows = build_e3_layer_rows(cell_rows)
    display_rows = [
        row for row in layer_rows if row["region"] != "overall"
    ]
    font = _choose_cjk_font()
    plt.rcParams.update(
        {
            "font.family": [font, "Times New Roman"],
            "font.size": 8.0,
            "axes.labelsize": 8.0,
            "xtick.labelsize": 7.2,
            "ytick.labelsize": 7.2,
            "legend.fontsize": 7.0,
            "axes.unicode_minus": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    colors = spec["global"]["palette"]
    hatches = {"jjj": "", "prd": "///", "cy": "\\\\\\"}
    layer_labels = [label for label, _sizes in SIZE_LAYERS]
    positions = list(range(len(layer_labels)))
    width = 0.22
    offsets = {
        "jjj": -width,
        "prd": 0.0,
        "cy": width,
    }

    figure, axis = plt.subplots(figsize=(4.30, 2.80))
    plotted_values: list[float] = []
    for region in REGIONS:
        region_rows = [
            row for row in display_rows if row["region"] == region
        ]
        values = [
            float(row["cost_reduction_percent"])
            for row in region_rows
        ]
        plotted_values.extend(values)
        axis.bar(
            [position + offsets[region] for position in positions],
            values,
            width=width,
            label=REGION_LABELS[region],
            color=colors[region],
            hatch=hatches[region],
            edgecolor="#222222",
            linewidth=0.45,
            zorder=2,
        )
    axis.axhline(
        0.0,
        color="#222222",
        linewidth=0.468,
        zorder=1,
    )
    # The registered visual contract keeps legends inside the upper-right
    # corner. Reserve a full blank bar group there instead of covering data.
    axis.set_xlim(-0.55, len(layer_labels) + 0.25)
    axis.set_ylim(*_axis_limits(plotted_values))
    axis.set_xticks(positions, layer_labels)
    axis.set_xlabel("客户规模")
    axis.set_ylabel("成本降低(%)")
    axis.grid(False)
    for spine in axis.spines.values():
        spine.set_visible(True)
        spine.set_color("#222222")
        spine.set_linewidth(0.468)
    axis.tick_params(
        axis="both",
        direction="out",
        width=0.468,
        length=2.4,
        pad=2.0,
    )
    axis.legend(
        loc="upper right",
        frameon=False,
        ncol=1,
        handlelength=1.5,
        handletextpad=0.45,
        borderaxespad=0.35,
        labelspacing=0.3,
    )
    figure.subplots_adjust(
        left=0.15,
        right=0.985,
        bottom=0.19,
        top=0.975,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = spec["families"]["E3"]["output_stem"]
    pdf = output_dir / f"{stem}.pdf"
    png = output_dir / f"{stem}.png"
    cell_csv = output_dir / "e3_paired_cells.csv"
    layer_csv = output_dir / "e3_region_layer_rows.csv"
    figure.savefig(pdf)
    figure.savefig(png, dpi=300)
    plt.close(figure)
    _write_csv(
        cell_csv,
        cell_rows,
        list(cell_rows[0]),
    )
    _write_csv(
        layer_csv,
        layer_rows,
        list(layer_rows[0]),
    )
    return {
        "family": "E3",
        "status": "FIGURE_GENERATED_FROM_27_PAIRED_CELLS",
        "source_formal_rows": 810,
        "source_pairs": 405,
        "source_cells": len(cell_rows),
        "display_rows": len(display_rows),
        "font": font,
        "axis_limits": list(_axis_limits(plotted_values)),
        "broken_axis": False,
        "files": [
            str(pdf),
            str(png),
            str(cell_csv),
            str(layer_csv),
        ],
    }


def generate_figures(
    raw_path: Path,
    output_dir: Path,
    *,
    repo_root: Path = ROOT,
    aggregate_dir: Path | None = None,
) -> dict[str, Any]:
    contract = load_contract(repo_root)
    rows = read_csv(raw_path) if raw_path.is_file() else []
    spec = figure_specs(contract)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "figure_specs.json", spec)
    formal_families = {
        str(row.get("family", "")).strip()
        for row in rows
        if str(row.get("record_type", "")).strip() == "formal_run"
    }
    if not formal_families:
        statuses = [
            {
                "family": family["id"],
                "status": "NO_FORMAL_RESULTS_NO_FIGURE",
                "reason": (
                    "raw_runs.csv currently contains no complete formal rows"
                ),
            }
            for family in contract["families"]
        ]
    else:
        release_root = (
            aggregate_dir
            if aggregate_dir is not None
            else raw_path.parent / "aggregates"
        )
        released, release_reason = _released(
            raw_path,
            release_root,
        )
        statuses = []
        for family in contract["families"]:
            family_id = family["id"]
            if family_id not in formal_families:
                statuses.append(
                    {
                        "family": family_id,
                        "status": "NO_FORMAL_RESULTS_NO_FIGURE",
                    }
                )
            elif not released:
                statuses.append(
                    {
                        "family": family_id,
                        "status": (
                            "HALT_FIGURE_UNTIL_INDEPENDENT_RECALC"
                        ),
                        "reason": release_reason,
                    }
                )
            elif family_id == "E3":
                try:
                    statuses.append(
                        _plot_e3(rows, output_dir, spec)
                    )
                except (RuntimeError, ValueError) as exc:
                    statuses.append(
                        {
                            "family": "E3",
                            "status": "HALT_E3_EXHIBIT_DATA",
                            "reason": str(exc),
                        }
                    )
            else:
                statuses.append(
                    {
                        "family": family_id,
                        "status": (
                            "NO_DEDICATED_PUBLISHER_RENDERER"
                        ),
                        "reason": (
                            "A generic raw-row boxplot is prohibited; "
                            "this family needs its registered reference shell."
                        ),
                    }
                )
    generated = [
        item
        for item in statuses
        if item["status"].startswith("FIGURE_GENERATED")
    ]
    decision = {
        "schema": "resetp.china.e3-e7-figure-decision.v2",
        "raw_path": str(raw_path),
        "aggregate_dir": (
            str(aggregate_dir) if aggregate_dir is not None else None
        ),
        "formal_rows": sum(row.get("record_type") == "formal_run" for row in rows),
        "status": (
            "NO_FORMAL_RESULTS_NO_FIGURES"
            if not formal_families
            else (
                "FIGURE_REVIEW_REQUIRED"
                if generated
                else "HALT_NO_RELEASED_FIGURE"
            )
        ),
        "families": statuses,
        "scientific_claim_allowed": False,
    }
    _write_status(output_dir / "decision.json", decision)
    (output_dir / "report.md").write_text(
        "\n".join(
            [
                "# 中国 E3–E7 图表生成状态",
                "",
                f"状态：`{decision['status']}`。",
                "",
                (
                    "E3 只允许把810条正式结果先配成27个地区—规模单元，"
                    "再生成九个城市群—规模层柱值；不会直接对810条原始行"
                    "画箱线图，也不会按结果方向改变坐标轴。"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    files = [
        path
        for path in output_dir.iterdir()
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    ]
    _write_json(
        output_dir / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "files": {_display_path(path, repo_root): _sha256(path) for path in files},
        },
    )
    return decision
