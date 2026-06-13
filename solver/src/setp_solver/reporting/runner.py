from __future__ import annotations

import argparse
from pathlib import Path
import shutil
from typing import Any

from .converters import convert_legacy_reports
from .figures import (
    figure_f1_route_map,
    figure_f2_algorithm_performance,
    figure_f3_two_layer_bars,
    figure_f3_two_layer_waterfall,
    figure_f4_48slot_charging,
    figure_f5_carbon_heatmap,
    figure_f6_fairness_frontier,
)
from .registry import RUNNERS, get_runner, register_runner
from .samples import build_figure_sources, build_table_sources
from .schema import write_records
from .tables import write_table_fragment


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[4]


@register_runner("w0")
def run_w0(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    records, warnings = convert_legacy_reports(args.reports_dir)
    w0_dir = output_dir / "w0_schema"
    csv_path = w0_dir / "experiment_records.csv"
    json_path = w0_dir / "experiment_records.json"
    write_records(records, csv_path, json_path)
    warnings_path = w0_dir / "conversion_warnings.txt"
    warnings_path.write_text("\n".join(warnings) + ("\n" if warnings else ""), encoding="utf-8")
    return {"records_csv": csv_path, "records_json": json_path, "warnings": warnings_path, "count": len(records)}


@register_runner("w1")
def run_w1(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    repo_root = Path(args.repo_root)
    records_csv = Path(args.records_csv) if getattr(args, "records_csv", None) else output_dir / "w0_schema" / "experiment_records.csv"
    table_sources = build_table_sources(repo_root, Path(args.reports_dir), output_dir, records_csv)
    tex_paths: dict[str, Path] = {}
    for table_id, source in table_sources.items():
        tex_path = output_dir / "tables" / f"{table_id.lower()}_{_table_slug(table_id)}.tex"
        write_table_fragment(table_id, source, tex_path)
        tex_paths[table_id] = tex_path
    return {"sources": table_sources, "tex": tex_paths}


@register_runner("w2")
def run_w2(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    repo_root = Path(args.repo_root)
    figure_sources = build_figure_sources(repo_root, Path(args.reports_dir), output_dir)
    figures_dir = output_dir / "figures"
    _cleanup_stale_figure_outputs(figures_dir)
    outputs = {
        "F1": figure_f1_route_map(figure_sources["F1_nodes"], figure_sources["F1_routes"], figures_dir / "f1_route_map_sample"),
        "F2": figure_f2_algorithm_performance(figure_sources["F2_curves"], figure_sources["F2_finals"], figures_dir / "f2_algorithm_performance_sample"),
        "F3": figure_f3_two_layer_waterfall(figure_sources["F3"], figures_dir / "f3_two_layer_carbon_waterfall"),
        "F3B": figure_f3_two_layer_bars(figure_sources["F3"], figures_dir / "f3_two_layer_carbon_bars"),
        "F4": figure_f4_48slot_charging(figure_sources["F4"], figures_dir / "f4_48slot_charging"),
        "F5": figure_f5_carbon_heatmap(figure_sources["F5"], figures_dir / "f5_carbon_heatmap_sample"),
        "F6": figure_f6_fairness_frontier(figure_sources["F6"], figures_dir / "f6_fairness_frontier_sample"),
    }
    return {"sources": figure_sources, "figures": outputs}


@register_runner("build-samples")
def run_build_samples(args: argparse.Namespace) -> dict[str, Any]:
    w0 = run_w0(args)
    args.records_csv = str(w0["records_csv"])
    w1 = run_w1(args)
    w2 = run_w2(args)
    summary_path = Path(args.output_dir) / "HALT_FOR_USER_summary.md"
    summary_path.write_text(_summary_markdown(w0, w1, w2), encoding="utf-8")
    _cleanup_appledouble(Path(args.output_dir))
    return {"w0": w0, "w1": w1, "w2": w2, "summary": summary_path}


@register_runner("formal-backfill")
def run_formal_backfill(args: argparse.Namespace) -> dict[str, Any]:
    """Build paper-ready tables/figures only from formal-runner CSV outputs."""

    repo_root = Path(args.repo_root)
    output_dir = Path(args.output_dir)
    formal_dir = Path(getattr(args, "formal_dir", "") or repo_root / "solver" / "reports" / "formal")
    tables_out = output_dir / "formal_backfill" / "tables"
    figures_out = output_dir / "formal_backfill" / "figures"
    missing: list[str] = []
    tex_paths: dict[str, Path] = {}
    table_sources = {
        "T1": formal_dir / "tables" / "t1_instances.csv",
        "T3": formal_dir / "tables" / "t3_algorithm_comparison.csv",
        "T4": formal_dir / "tables" / "t4_solution_decomposition.csv",
        "T5": formal_dir / "tables" / "t5_ablation.csv",
        "T6": formal_dir / "tables" / "t6_two_layer_carbon.csv",
        "T7": formal_dir / "tables" / "t7_carbon_sensitivity.csv",
        "T8": formal_dir / "tables" / "t8_fairness_threshold.csv",
        "T9": formal_dir / "tables" / "t9_dynamic.csv",
    }
    for table_id, source in table_sources.items():
        if not source.exists():
            missing.append(f"{table_id}:{source}")
            continue
        tex_path = tables_out / f"{table_id.lower()}_{_table_slug(table_id)}.tex"
        write_table_fragment(table_id, source, tex_path)
        tex_paths[table_id] = tex_path

    figure_paths: dict[str, tuple[Path, Path]] = {}
    f1_nodes = formal_dir / "figures" / "f1_route_nodes.csv"
    f1_routes = formal_dir / "figures" / "f1_route_lines.csv"
    if f1_nodes.exists() and f1_routes.exists():
        figure_paths["F1"] = figure_f1_route_map(f1_nodes, f1_routes, figures_out / "f1_route_map", watermark=False)
    else:
        missing.append(f"F1:{f1_nodes},{f1_routes}")
    f2_curves = formal_dir / "figures" / "f2_algorithm_curves.csv"
    f2_finals = formal_dir / "figures" / "f2_algorithm_finals.csv"
    if f2_curves.exists() and f2_finals.exists():
        figure_paths["F2"] = figure_f2_algorithm_performance(f2_curves, f2_finals, figures_out / "f2_algorithm_performance", watermark=False)
    else:
        missing.append(f"F2:{f2_curves},{f2_finals}")
    f3 = formal_dir / "figures" / "f3_two_layer_carbon.csv"
    if f3.exists():
        figure_paths["F3"] = figure_f3_two_layer_waterfall(f3, figures_out / "f3_two_layer_carbon_waterfall")
        figure_paths["F3B"] = figure_f3_two_layer_bars(f3, figures_out / "f3_two_layer_carbon_bars")
    else:
        missing.append(f"F3:{f3}")
    f4 = formal_dir / "figures" / "f4_48slot_charging.csv"
    if f4.exists():
        figure_paths["F4"] = figure_f4_48slot_charging(f4, figures_out / "f4_48slot_charging")
    else:
        missing.append(f"F4:{f4}")
    f5 = formal_dir / "figures" / "f5_carbon_heatmap.csv"
    if f5.exists():
        figure_paths["F5"] = figure_f5_carbon_heatmap(f5, figures_out / "f5_carbon_heatmap", watermark=False)
    else:
        missing.append(f"F5:{f5}")
    f6 = formal_dir / "figures" / "f6_fairness_frontier.csv"
    if f6.exists():
        figure_paths["F6"] = figure_f6_fairness_frontier(f6, figures_out / "f6_fairness_frontier", watermark=False)
    else:
        missing.append(f"F6:{f6}")

    summary_path = output_dir / "formal_backfill" / "HALT_FOR_USER_summary.md"
    paper_copies = _copy_selected_formal_outputs_to_paper(repo_root, tex_paths, figure_paths)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    gate = "PASS" if not missing else "HALT_Z5"
    summary_path.write_text(_formal_summary_markdown(gate, formal_dir, tex_paths, figure_paths, missing, paper_copies), encoding="utf-8")
    return {"gate": gate, "formal_dir": formal_dir, "tex": tex_paths, "figures": figure_paths, "missing": missing, "paper_copies": paper_copies, "summary": summary_path}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 SETP 统一报告 schema、表格样张和图形样张。")
    parser.add_argument("runner", choices=sorted(RUNNERS), nargs="?", default="build-samples")
    parser.add_argument("--repo-root", default=str(repo_root_from_here()))
    parser.add_argument("--reports-dir", default=str(repo_root_from_here() / "solver" / "reports"))
    parser.add_argument("--output-dir", default=str(repo_root_from_here() / "solver" / "reports" / "reporting_samples"))
    parser.add_argument("--formal-dir", default=str(repo_root_from_here() / "solver" / "reports" / "formal"))
    args = parser.parse_args(argv)
    result = get_runner(args.runner)(args)
    print(_console_summary(args.runner, result))
    return 0


def _table_slug(table_id: str) -> str:
    return {
        "T1": "instances",
        "T2": "parameters",
        "T3": "algorithm_comparison",
        "T4": "solution_decomposition",
        "T5": "ablation",
        "T6": "two_layer_carbon",
        "T7": "carbon_sensitivity",
        "T8": "fairness_threshold",
        "T9": "dynamic",
    }[table_id]


def _console_summary(name: str, result: dict[str, Any]) -> str:
    if name == "build-samples":
        return f"HALT_FOR_USER 汇总：{result['summary']}"
    if name == "formal-backfill":
        return f"GATE Z5 {result['gate']} 汇总：{result['summary']}"
    return f"{name} 已完成：{result}"


def _formal_summary_markdown(
    gate: str,
    formal_dir: Path,
    tex_paths: dict[str, Path],
    figure_paths: dict[str, tuple[Path, Path]],
    missing: list[str],
    paper_copies: dict[str, Path],
) -> str:
    lines = [
        f"# {gate}: formal backfill",
        "",
        f"formal CSV root: `{formal_dir}`",
        "",
        "## Tables",
    ]
    for table_id, path in sorted(tex_paths.items()):
        lines.append(f"- {table_id}: `{path}`")
    lines.extend(["", "## Figures"])
    for figure_id, paths in sorted(figure_paths.items()):
        lines.append(f"- {figure_id}: `{paths[0]}` / `{paths[1]}`")
    if missing:
        lines.extend(["", "## Missing formal sources"])
        lines.extend(f"- {item}" for item in missing)
    if paper_copies:
        lines.extend(["", "## Paper copies"])
        for item, path in sorted(paper_copies.items()):
            lines.append(f"- {item}: `{path}`")
    lines.append("")
    lines.append("HALT_FOR_USER" if missing else "GATE Z5 PASS")
    return "\n".join(lines) + "\n"


def _copy_selected_formal_outputs_to_paper(
    repo_root: Path,
    tex_paths: dict[str, Path],
    figure_paths: dict[str, tuple[Path, Path]],
) -> dict[str, Path]:
    copied: dict[str, Path] = {}
    table_targets = {
        "T3": "t3_algorithm_comparison.tex",
        "T4": "t4_solution_decomposition.tex",
        "T5": "t5_ablation.tex",
        "T7": "t7_carbon_sensitivity.tex",
        "T9": "t9_dynamic.tex",
    }
    table_dir = repo_root / "docs" / "paper_submission_final" / "generated_tables"
    figure_dir = repo_root / "docs" / "paper_submission_final" / "generated_figures"
    table_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)
    for table_id, filename in table_targets.items():
        source = tex_paths.get(table_id)
        if source is None:
            continue
        target = table_dir / filename
        shutil.copy2(source, target)
        copied[table_id] = target
    figure_targets = {
        "F1": "figure_f1_route_map",
        "F2": "figure_f2_algorithm_performance",
        "F5": "figure_f5_carbon_heatmap",
    }
    for figure_id, stem in figure_targets.items():
        paths = figure_paths.get(figure_id)
        if paths is None:
            continue
        for source in paths:
            suffix = source.suffix.lower()
            target = figure_dir / f"{stem}{suffix}"
            shutil.copy2(source, target)
            copied[f"{figure_id}{suffix}"] = target
    return copied


def _summary_markdown(w0: dict[str, Any], w1: dict[str, Any], w2: dict[str, Any]) -> str:
    lines = [
        "# HALT_FOR_USER：报告管线样张汇总",
        "",
        "本轮未运行新实验；仅转换或重放 `solver/reports/` 下已有 JSON/CSV 文件来生成表图样张。",
        "",
        "## W0 统一数据结构",
        f"- 样式说明: `{Path(__file__).resolve().parent / 'STYLE_NOTES.md'}`",
        f"- CSV: `{w0['records_csv']}`",
        f"- JSON: `{w0['records_json']}`",
        f"- 转换警告: `{w0['warnings']}`",
        f"- 已转换记录数: {w0['count']}",
        "",
        "## W1 表格",
    ]
    for table_id, path in sorted(w1["tex"].items()):
        source = w1["sources"][table_id]
        lines.append(f"- {table_id}: `{path}`，来源 `{source}`")
    lines.extend(["", "## W2 图形"])
    for figure_id, paths in sorted(w2["figures"].items()):
        pdf_path, png_path = paths
        lines.append(f"- {figure_id}: `{pdf_path}` 与 `{png_path}`")
    lines.extend(
        [
            "",
            "## 说明",
            "- 陈婉茹2023表5 → T3 算法对比；陈婉茹2023表8 → T5 消融；陈婉茹2023表10 → T7 碳敏感。",
            "- 陈婉茹2023图3 → F1 双panel路线图；陈婉茹2023图2 → F2 阶梯收敛线。",
            "- Shi2025 Fig.5 → F4 峰/平/谷充电占比；Soriano2023 Fig.6 → F6 成本比公平前沿。",
            "- F3 和 F4 使用现有 T0/T1 报告数据。F3 的纯油车层由现有 T0 路线集确定性重放得到，不运行搜索。",
            "- F6 以现有 X1 公平报告和独立运营成本为锚点；因当前 reports 尚无完整 θ 扫描，其余 θ 点为样式外推并保留“样张”水印。",
            "- 当前 T1 槽数据中，朴素充电峰值约在 10-13.5h，而不是预期的傍晚峰；渲染器保持文件读数不变。",
            "- F1、F2、F5 是形态样张，并以“样张”水印标注。",
            "- T5、T7、T8、T9 在正式 runner 尚未齐备处使用“样张”行。",
            "",
            "HALT_FOR_USER",
        ]
    )
    return "\n".join(lines) + "\n"


def _cleanup_appledouble(output_dir: Path) -> None:
    for path in output_dir.rglob("._*"):
        if path.is_file() or path.is_symlink():
            path.unlink()


def _cleanup_stale_figure_outputs(figures_dir: Path) -> None:
    for name in ("f3_two_layer_carbon.pdf", "f3_two_layer_carbon.png"):
        path = figures_dir / name
        if path.exists():
            path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
