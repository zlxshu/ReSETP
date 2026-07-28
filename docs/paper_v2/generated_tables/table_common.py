"""Strict CSV loading shared by the China81 LaTeX table generators."""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ARMS = ("O", "F", "E", "M", "MV")
ARM_LABELS = {
    "O": "O",
    "F": "HGS-F",
    "E": "HGS-E",
    "M": "HGS-M",
    "MV": "MV-HGS-SP",
}
REGIONS = ("jjj", "prd", "cy")
REGION_LABELS = {"jjj": "京津冀", "prd": "珠三角", "cy": "成渝"}
LAYERS = ("small", "medium", "large")
LAYER_COUNTS = {
    "small": (10, 15, 20),
    "medium": (25, 50, 75),
    "large": (100, 150, 200),
}
LAYER_LABELS = {key: "/".join(map(str, values)) for key, values in LAYER_COUNTS.items()}
SEEDS = (1, 2, 3, 4, 5)
EPS = 1.0e-9


class InputError(RuntimeError):
    """The input is incomplete or violates the frozen China81 table contract."""


@dataclass(frozen=True)
class Run:
    instance_id: str
    region: str
    size_layer: str
    customer_count: int
    seed: int
    arm: str
    cost: float

    @property
    def unit(self) -> tuple[str, int]:
        return self.instance_id, self.seed


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def _selected_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if not rows:
        raise InputError("CSV has no data rows")
    if "selected_final_attempt" not in rows[0]:
        raise InputError("missing required column: selected_final_attempt")
    return [row for row in rows if _truthy(row.get("selected_final_attempt", ""))]


def load_runs(path: Path, *, format_dry_run: bool) -> list[Run]:
    required = {
        "instance_id", "region", "size_layer", "customer_count", "seed", "arm",
        "selected_final_attempt", "status", "final_cost", "feasible",
        "violation_count", "independent_violation_count",
    }
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise InputError("CSV header is missing")
            missing = sorted(required - set(reader.fieldnames))
            if missing:
                raise InputError(f"missing required columns: {', '.join(missing)}")
            source_rows = list(reader)
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc

    rows = _selected_rows(source_rows)
    runs: list[Run] = []
    seen: set[tuple[str, int, str]] = set()
    for line_no, row in enumerate(rows, start=2):
        try:
            key = (row["instance_id"], int(row["seed"]), row["arm"])
            count = int(row["customer_count"])
            cost = float(row["final_cost"])
            violations = int(row["violation_count"])
            independent_violations = int(row["independent_violation_count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InputError(f"invalid numeric/key field near selected row {line_no}: {exc}") from exc
        if key in seen:
            raise InputError(f"duplicate selected final row: {key}")
        seen.add(key)
        if row["arm"] not in ARMS:
            raise InputError(f"unknown arm at selected row {line_no}: {row['arm']!r}")
        if row["region"] not in REGIONS or row["size_layer"] not in LAYERS:
            raise InputError(f"unknown region/size layer at selected row {line_no}")
        if row["status"] != "PASS" or not _truthy(row["feasible"]):
            raise InputError(f"non-PASS or infeasible selected row: {key}")
        if violations != 0 or independent_violations != 0:
            raise InputError(f"violations in selected row {key}: {violations}/{independent_violations}")
        if not math.isfinite(cost) or cost <= 0:
            raise InputError(f"invalid final_cost in selected row {key}: {cost}")
        runner_layer = "small" if count <= 25 else ("medium" if count <= 100 else "large")
        if runner_layer != row["size_layer"]:
            raise InputError(
                f"customer_count/size_layer mismatch in {key}: {count}/{row['size_layer']}"
            )
        paper_layer = next(
            (layer for layer, counts in LAYER_COUNTS.items() if count in counts), None
        )
        if paper_layer is None:
            raise InputError(f"customer_count outside the frozen nine-size ladder in {key}: {count}")
        runs.append(
            Run(row["instance_id"], row["region"], paper_layer, count,
                int(row["seed"]), row["arm"], cost)
        )

    by_unit: dict[tuple[str, int], set[str]] = defaultdict(set)
    for run in runs:
        by_unit[run.unit].add(run.arm)
    incomplete = {unit: sorted(set(ARMS) - arms) for unit, arms in by_unit.items() if arms != set(ARMS)}
    if incomplete:
        preview = "; ".join(f"{unit}: missing {arms}" for unit, arms in list(incomplete.items())[:5])
        raise InputError(f"incomplete five-arm units: {preview}")

    instances: dict[str, tuple[str, str, int]] = {}
    seeds_by_instance: dict[str, set[int]] = defaultdict(set)
    for run in runs:
        identity = (run.region, run.size_layer, run.customer_count)
        if run.instance_id in instances and instances[run.instance_id] != identity:
            raise InputError(f"inconsistent metadata for {run.instance_id}")
        instances[run.instance_id] = identity
        seeds_by_instance[run.instance_id].add(run.seed)
    bad_seeds = {key: sorted(value) for key, value in seeds_by_instance.items() if value != set(SEEDS)}
    if bad_seeds:
        raise InputError(f"instances without exactly seeds 1--5: {bad_seeds}")

    if format_dry_run:
        if not runs:
            raise InputError("format dry run needs at least one complete stratum")
        by_region_count: dict[tuple[str, int], set[str]] = defaultdict(set)
        for instance_id, (region, _layer, count) in instances.items():
            by_region_count[(region, count)].add(instance_id)
        bad = {key: len(value) for key, value in by_region_count.items() if len(value) != 3}
        if bad:
            raise InputError(f"dry-run region/count cells must contain exactly 3 instances: {bad}")
    else:
        if len(runs) != 81 * 5 * 5:
            raise InputError(f"formal input requires 2025 selected rows, found {len(runs)}")
        expected_cells = {(region, count) for region in REGIONS for count in sum(LAYER_COUNTS.values(), ())}
        actual_cells: dict[tuple[str, int], set[str]] = defaultdict(set)
        for instance_id, (region, _layer, count) in instances.items():
            actual_cells[(region, count)].add(instance_id)
        if set(actual_cells) != expected_cells:
            missing = sorted(expected_cells - set(actual_cells))
            extra = sorted(set(actual_cells) - expected_cells)
            raise InputError(f"formal region/count coverage mismatch; missing={missing}, extra={extra}")
        bad = {key: len(value) for key, value in actual_cells.items() if len(value) != 3}
        if bad:
            raise InputError(f"formal region/count cells must contain exactly 3 instances: {bad}")
    return runs


def visible_dry_run_warning(columns: int) -> list[str]:
    return [
        f"\\multicolumn{{{columns}}}{{c}}{{\\textbf{{格式干跑：已作废超订批次，禁止用于论文}}}}\\\\",
        "\\midrule",
    ]


def tex_number(value: float, *, bold: bool = False) -> str:
    rendered = f"{value:.2f}"
    return f"\\textbf{{{rendered}}}" if bold else rendered
