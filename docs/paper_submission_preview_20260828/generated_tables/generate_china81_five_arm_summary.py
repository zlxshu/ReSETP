#!/usr/bin/env python3
"""Generate the strict five-arm China81 stratified LaTeX table body."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from statistics import mean

from table_common import (
    ARMS, ARM_LABELS, EPS, LAYERS, LAYER_LABELS, REGION_LABELS, REGIONS,
    InputError, Run, load_runs, tex_number, visible_dry_run_warning,
)


def _instance_statistics(runs: list[Run]) -> dict[tuple[str, str], tuple[float, float]]:
    costs: dict[tuple[str, str], list[float]] = defaultdict(list)
    for run in runs:
        costs[(run.instance_id, run.arm)].append(run.cost)
    result = {}
    for key, values in costs.items():
        if len(values) != 5:
            raise InputError(f"{key} needs exactly five seed costs, found {len(values)}")
        result[key] = (min(values), mean(values))
    return result


def _aggregate(
    runs: list[Run], instances: set[str], arm: str,
    stats: dict[tuple[str, str], tuple[float, float]],
) -> tuple[float, float]:
    if not instances:
        raise InputError("cannot aggregate an empty stratum")
    values = [stats[(instance_id, arm)] for instance_id in sorted(instances)]
    return mean(item[0] for item in values), mean(item[1] for item in values)


def render(runs: list[Run], *, format_dry_run: bool, source: Path) -> str:
    stats = _instance_statistics(runs)
    metadata = {run.instance_id: (run.region, run.size_layer, run.customer_count) for run in runs}
    present = {(region, layer) for region, layer, _count in metadata.values()}
    rows: list[tuple[str, str, set[str]]] = []
    for region in REGIONS:
        for layer in LAYERS:
            if (region, layer) not in present:
                continue
            instances = {key for key, value in metadata.items() if value[:2] == (region, layer)}
            counts = sorted({metadata[key][2] for key in instances})
            label = "/".join(map(str, counts)) if format_dry_run else LAYER_LABELS[layer]
            rows.append((REGION_LABELS[region], label, instances))
    all_instances = set(metadata)
    rows.append(("总体", "干跑子集" if format_dry_run else "全部9层", all_instances))

    lines = [
        "% Generated from raw_runs.csv; do not edit numeric cells by hand.",
    ]
    if format_dry_run:
        lines.append("% !!! FORMAT DRY RUN FROM INVALIDATED OVERSUBSCRIBED BATCH; NEVER USE IN PAPER !!!")
    lines.extend([
        "\\begin{tabular*}{\\linewidth}{@{\\extracolsep{\\fill}}cc" + "rr" * len(ARMS) + "@{}}",
        "\\toprule",
    ])
    if format_dry_run:
        lines.extend(visible_dry_run_warning(2 + 2 * len(ARMS)))
    header = " & ".join(f"\\multicolumn{{2}}{{c}}{{{ARM_LABELS[arm]}}}" for arm in ARMS)
    lines.append(f"\\multirow{{2}}{{*}}{{城市群}} & \\multirow{{2}}{{*}}{{规模层}} & {header}\\\\")
    start = 3
    lines.append("".join(f"\\cmidrule(lr){{{start + 2*i}-{start + 2*i + 1}}}" for i in range(len(ARMS))))
    lines.append(" & & " + " & ".join("\\multicolumn{1}{c}{Best.} & \\multicolumn{1}{c}{avg.}" for _ in ARMS) + "\\\\")
    lines.append("\\midrule")
    for region_label, layer_label, instances in rows:
        values = [_aggregate(runs, instances, arm, stats) for arm in ARMS]
        best_min = min(value[0] for value in values)
        avg_min = min(value[1] for value in values)
        cells = []
        for best, avg in values:
            cells.extend((tex_number(best, bold=abs(best-best_min) <= EPS), tex_number(avg, bold=abs(avg-avg_min) <= EPS)))
        lines.append(f"{region_label} & {layer_label} & " + " & ".join(cells) + "\\\\")
    lines.extend(("\\bottomrule", "\\end{tabular*}", ""))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_runs", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--format-dry-run", action="store_true")
    args = parser.parse_args()
    try:
        runs = load_runs(args.raw_runs, format_dry_run=args.format_dry_run)
        text = render(runs, format_dry_run=args.format_dry_run, source=args.raw_runs)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    except InputError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

