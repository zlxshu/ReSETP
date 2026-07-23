"""Paper-facing chart adapter for future China E3--E7 results.

No figure is emitted when the input contains no sealed formal result rows.
That behaviour is deliberate: a blank chart is still a misleading artifact.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from .contract import ROOT, load_contract, read_csv
except ImportError:  # pragma: no cover - direct script compatibility
    from contract import ROOT, load_contract, read_csv


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
        "schema": "resetp.china.e3-e7-figure-specs.v1",
        "global": {
            "font_family": "STIXGeneral",
            "figure_policy": "只从正式 raw_runs 和独立复算结果生成；无结果时不生成 PDF/PNG。",
            "caption_policy": "中文学术图题，不写内部 F/E 编号，不根据结果改变坐标轴范围。",
            "palette": {
                "control": "#6B7280",
                "treatment": "#1F5A85",
                "secondary": "#C77C2B",
                "warning": "#9A3412"
            }
        },
        "families": {
            "E3": {
                "form": "paired_slope_or_dot_interval",
                "output_stem": "e3_responsibility",
                "x": "27个地区—规模统计单元",
                "y": "总成本改善(%)",
                "caption": "责任错配与跨场协同的配对成本变化"
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


def _metric_value(row: dict[str, str], metric: str) -> float | None:
    value = row.get(metric, "")
    if metric == "feasible":
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "pass", "feasible"}:
            return 1.0
        if normalized in {"0", "false", "no", "fail", "infeasible"}:
            return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _plot_if_data(
    family_id: str,
    rows: list[dict[str, str]],
    output_dir: Path,
    spec: dict[str, Any],
) -> dict[str, Any]:
    complete = [row for row in rows if row.get("record_type") == "formal_run" and row.get("status") == "complete" and row.get("family") == family_id]
    if not complete:
        return {
            "family": family_id,
            "status": "NO_FORMAL_RESULTS_NO_FIGURE",
            "reason": "raw_runs.csv currently contains no complete formal rows",
        }
    try:
        import matplotlib.pyplot as plt  # type: ignore
    except ImportError as exc:
        return {"family": family_id, "status": "HALT_MATPLOTLIB_MISSING", "reason": str(exc)}

    arms: list[str] = []
    values: dict[str, list[float]] = {}
    metric = {
        "E3": "total_cost",
        "E4": "charging_emissions",
        "E5": "feasible",
        "E6": "member_min_benefit",
        "E7": "total_cost",
    }[family_id]
    for row in complete:
        arm = row.get("arm", "")
        if arm not in arms:
            arms.append(arm)
        value = _metric_value(row, metric)
        if value is None:
            continue
        values.setdefault(arm, []).append(value)
    if not values or any(not values.get(arm) for arm in arms[:2]):
        return {"family": family_id, "status": "HALT_MISSING_PLOT_METRIC"}
    output_dir.mkdir(parents=True, exist_ok=True)
    figure = plt.figure(figsize=(6.4, 3.6))
    axis = figure.add_subplot(111)
    axis.boxplot([values[arm] for arm in arms if values.get(arm)], labels=[arm for arm in arms if values.get(arm)], patch_artist=False)
    axis.set_title(spec["families"][family_id]["caption"])
    axis.set_ylabel(spec["families"][family_id]["y"])
    axis.grid(axis="y", color="#D1D5DB", linewidth=0.5, alpha=0.7)
    figure.tight_layout()
    stem = spec["families"][family_id]["output_stem"]
    pdf = output_dir / f"{stem}.pdf"
    png = output_dir / f"{stem}.png"
    figure.savefig(pdf)
    figure.savefig(png, dpi=220)
    plt.close(figure)
    return {
        "family": family_id,
        "status": "FIGURE_GENERATED_FROM_FORMAL_ROWS",
        "files": [str(pdf), str(png)],
    }


def generate_figures(
    raw_path: Path,
    output_dir: Path,
    *,
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    contract = load_contract(repo_root)
    rows = read_csv(raw_path) if raw_path.is_file() else []
    spec = figure_specs(contract)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "figure_specs.json", spec)
    statuses = [
        _plot_if_data(family["id"], rows, output_dir, spec)
        for family in contract["families"]
    ]
    decision = {
        "schema": "resetp.china.e3-e7-figure-decision.v1",
        "raw_path": str(raw_path),
        "formal_rows": sum(row.get("record_type") == "formal_run" for row in rows),
        "status": "NO_FORMAL_RESULTS_NO_FIGURES" if not any(item["status"].startswith("FIGURE") for item in statuses) else "FIGURE_REVIEW_REQUIRED",
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
                "图表规格已固定；当前没有正式 raw 行，因此没有生成任何结果 PDF/PNG。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    files = [output_dir / name for name in ("figure_specs.json", "decision.json", "report.md")]
    _write_json(
        output_dir / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "algorithm": "sha256",
            "files": {_display_path(path, repo_root): _sha256(path) for path in files},
        },
    )
    return decision
