#!/usr/bin/env python3
"""Generate MV-vs-O paired outcomes and five-arm ladder counts as LaTeX."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from statistics import mean

from table_common import (
    ARM_LABELS, EPS, LAYER_LABELS, LAYERS, REGION_LABELS, REGIONS,
    InputError, Run, load_runs, visible_dry_run_warning,
)


def _outcome(new: float, old: float) -> str:
    if new < old - EPS:
        return "改善"
    if new > old + EPS:
        return "回退"
    return "持平"


def render(runs: list[Run], *, format_dry_run: bool) -> str:
    costs = {(run.instance_id, run.seed, run.arm): run.cost for run in runs}
    unit_meta = {(run.instance_id, run.seed): (run.region, run.size_layer) for run in runs}
    units = sorted(unit_meta)
    pairs = []
    for instance_id, seed in units:
        o = costs[(instance_id, seed, "O")]
        mv = costs[(instance_id, seed, "MV")]
        region, layer = unit_meta[(instance_id, seed)]
        pairs.append((region, layer, _outcome(mv, o), 100.0 * (o - mv) / o))

    groups = []
    for region in REGIONS:
        selected = [row for row in pairs if row[0] == region]
        if selected:
            groups.append(("城市群", REGION_LABELS[region], selected))
    for layer in LAYERS:
        selected = [row for row in pairs if row[1] == layer]
        if selected:
            if format_dry_run:
                counts = sorted({run.customer_count for run in runs if run.size_layer == layer})
                label = "/".join(map(str, counts))
            else:
                label = LAYER_LABELS[layer]
            groups.append(("规模层", label, selected))
    groups.append(("总体", "干跑子集" if format_dry_run else "全部", pairs))

    lines = ["% Generated from raw_runs.csv; do not edit numeric cells by hand."]
    if format_dry_run:
        lines.append("% !!! FORMAT DRY RUN FROM INVALIDATED OVERSUBSCRIBED BATCH; NEVER USE IN PAPER !!!")
    lines.extend((
        "\\begin{tabular*}{\\linewidth}{@{\\extracolsep{\\fill}}llrrrrr@{}}",
        "\\toprule",
    ))
    if format_dry_run:
        lines.extend(visible_dry_run_warning(7))
    lines.extend((
        "分组 & 层级 & 配对数 & 改善 & 持平 & 回退 & 平均成本改善(\\%)\\\\",
        "\\midrule",
    ))
    for kind, label, selected in groups:
        counts = {name: sum(row[2] == name for row in selected) for name in ("改善", "持平", "回退")}
        lines.append(
            f"{kind} & {label} & {len(selected)} & {counts['改善']} & {counts['持平']} & "
            f"{counts['回退']} & {mean(row[3] for row in selected):.3f}\\\\"
        )
    lines.extend(("\\bottomrule", "\\end{tabular*}", "\\par\\smallskip"))

    transitions = (("O", "F"), ("F", "E"), ("E", "M"), ("M", "MV"))
    transition_counts = {}
    nonincreasing = 0
    for old_arm, new_arm in transitions:
        outcomes = [
            _outcome(costs[(instance_id, seed, new_arm)], costs[(instance_id, seed, old_arm)])
            for instance_id, seed in units
        ]
        transition_counts[(old_arm, new_arm)] = {
            name: outcomes.count(name) for name in ("改善", "持平", "回退")
        }
    for instance_id, seed in units:
        sequence = [costs[(instance_id, seed, arm)] for arm in ("O", "F", "E", "M", "MV")]
        nonincreasing += all(new <= old + EPS for old, new in zip(sequence, sequence[1:]))
    lines.extend((
        "\\begin{tabular*}{\\linewidth}{@{\\extracolsep{\\fill}}lrrrr@{}}",
        "\\toprule",
    ))
    if format_dry_run:
        lines.extend(visible_dry_run_warning(5))
    lines.extend(("逐层转换 & 单元数 & 改善 & 持平 & 回退\\\\", "\\midrule"))
    for old_arm, new_arm in transitions:
        counts = transition_counts[(old_arm, new_arm)]
        lines.append(
            f"{ARM_LABELS[old_arm]}$\\to${ARM_LABELS[new_arm]} & {len(units)} & "
            f"{counts['改善']} & {counts['持平']} & {counts['回退']}\\\\"
        )
    lines.extend((
        "\\midrule",
        f"\\multicolumn{{4}}{{l}}{{完整非增阶梯成立的算例--种子单元数}} & {nonincreasing}\\\\",
        "\\bottomrule",
        "\\end{tabular*}",
        "",
    ))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_runs", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--format-dry-run", action="store_true")
    args = parser.parse_args()
    try:
        runs = load_runs(args.raw_runs, format_dry_run=args.format_dry_run)
        text = render(runs, format_dry_run=args.format_dry_run)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    except InputError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

