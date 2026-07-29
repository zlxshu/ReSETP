"""Result-independent E3 paper exhibit reductions.

The formal E3 campaign has 810 rows:

* 3 regions x 9 customer sizes x 3 disjoint maps;
* 5 common seeds;
* 2 paired responsibility arms.

Paper exhibits must not treat those 810 rows as independent observations.
This module first reduces them to the preregistered 27 region-size cells and
then, only for the compact paper table/figure, to nine region-size-layer rows.
No result-direction gate is applied here.
"""

from __future__ import annotations

from collections import defaultdict
from math import fsum
from typing import Any, Iterable

try:
    from .statistics import _normalise_formal_row
except ImportError:  # pragma: no cover - direct script compatibility
    from statistics import _normalise_formal_row


CONTROL_ARM = "status_quo_responsibility"
TREATMENT_ARM = "optimized_responsibility_cooperation"
ARMS = (CONTROL_ARM, TREATMENT_ARM)


def fmean(values: Iterable[float]) -> float:
    items = list(values)
    if not items:
        raise ValueError("fmean requires at least one value")
    return fsum(items) / len(items)

REGIONS = ("jjj", "prd", "cy")
REGION_LABELS = {
    "jjj": "京津冀",
    "prd": "珠三角",
    "cy": "成渝",
}
CUSTOMER_SIZES = (10, 15, 20, 25, 50, 75, 100, 150, 200)
MAP_INDICES = (1, 2, 3)
SEEDS = (1, 2, 3, 4, 5)
SIZE_LAYERS = (
    ("10/15/20", (10, 15, 20)),
    ("25/50/75", (25, 50, 75)),
    ("100/150/200", (100, 150, 200)),
)
COMPLETE_CANDIDATE_BUDGET = 80


def _float(row: dict[str, str], field: str) -> float:
    raw = str(row.get(field, "")).strip()
    if not raw:
        raise ValueError(f"E3 exhibit row is missing {field}")
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(
            f"E3 exhibit row has non-numeric {field}: {raw}"
        ) from exc


def _int(row: dict[str, str], field: str) -> int:
    value = _float(row, field)
    integer = int(value)
    if value != integer:
        raise ValueError(
            f"E3 exhibit row has non-integral {field}: {value}"
        )
    return integer


def _true(row: dict[str, str], field: str) -> bool:
    return str(row.get(field, "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "pass",
        "feasible",
    }


def _map_index(row: dict[str, str]) -> int:
    return _int(row, "map_index")


def _attempts(row: dict[str, str]) -> int:
    for field in (
        "complete_candidate_attempts",
        "search_evaluations",
    ):
        if str(row.get(field, "")).strip():
            return _int(row, field)
    raise ValueError(
        "E3 exhibit row is missing complete-candidate attempt count"
    )


def _mean(rows: Iterable[dict[str, Any]], field: str) -> float:
    values = [float(row[field]) for row in rows]
    if not values:
        raise ValueError(f"cannot average empty E3 exhibit field: {field}")
    return fmean(values)


def build_e3_cell_rows(
    source_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Validate and reduce sealed E3 rows to 27 paired cells."""

    rows = [
        _normalise_formal_row(source)
        for source in source_rows
    ]
    rows = [
        row
        for row in rows
        if row.get("record_type") == "formal_run"
        and row.get("family") == "E3"
        and row.get("status") == "complete"
        and row.get("arm") in ARMS
    ]
    if len(rows) != 810:
        raise ValueError(
            f"E3 exhibits require exactly 810 complete formal rows, got "
            f"{len(rows)}"
        )

    grouped: dict[
        tuple[str, int, int, int, str],
        list[dict[str, str]],
    ] = defaultdict(list)
    for row in rows:
        region = str(row.get("region", "")).strip().lower()
        size = _int(row, "customer_size")
        map_index = _map_index(row)
        seed = _int(row, "seed")
        arm = str(row.get("arm", "")).strip()
        if region not in REGIONS:
            raise ValueError(f"unexpected E3 region: {region}")
        if size not in CUSTOMER_SIZES:
            raise ValueError(f"unexpected E3 customer size: {size}")
        if map_index not in MAP_INDICES:
            raise ValueError(f"unexpected E3 map index: {map_index}")
        if seed not in SEEDS:
            raise ValueError(f"unexpected E3 seed: {seed}")
        if not _true(row, "feasible"):
            raise ValueError(
                f"E3 exhibit input contains an infeasible formal row: "
                f"{row.get('instance_id')} / seed {seed} / {arm}"
            )
        if _attempts(row) != COMPLETE_CANDIDATE_BUDGET:
            raise ValueError(
                f"E3 exhibit input has a non-80 attempt count: "
                f"{row.get('instance_id')} / seed {seed} / {arm}"
            )
        if (
            str(row.get("wallclock_safety_triggered", ""))
            .strip()
            .lower()
            in {"1", "true", "yes"}
        ):
            raise ValueError(
                f"E3 exhibit input contains a wall-clock safety trigger: "
                f"{row.get('instance_id')} / seed {seed} / {arm}"
            )
        grouped[(region, size, map_index, seed, arm)].append(row)

    expected_keys = {
        (region, size, map_index, seed, arm)
        for region in REGIONS
        for size in CUSTOMER_SIZES
        for map_index in MAP_INDICES
        for seed in SEEDS
        for arm in ARMS
    }
    observed_keys = set(grouped)
    if observed_keys != expected_keys:
        missing = sorted(expected_keys - observed_keys)
        extra = sorted(observed_keys - expected_keys)
        raise ValueError(
            "E3 exhibit key matrix is incomplete: "
            f"missing={missing[:3]}, extra={extra[:3]}"
        )
    duplicates = [
        key for key, values in grouped.items() if len(values) != 1
    ]
    if duplicates:
        raise ValueError(
            f"E3 exhibit input has duplicate formal rows: "
            f"{duplicates[:3]}"
        )

    cells: list[dict[str, Any]] = []
    for region in REGIONS:
        for size in CUSTOMER_SIZES:
            by_arm: dict[str, list[dict[str, str]]] = {
                arm: [
                    grouped[(region, size, map_index, seed, arm)][0]
                    for map_index in MAP_INDICES
                    for seed in SEEDS
                ]
                for arm in ARMS
            }
            control_cost = fmean(
                _float(row, "total_cost")
                for row in by_arm[CONTROL_ARM]
            )
            treatment_cost = fmean(
                _float(row, "total_cost")
                for row in by_arm[TREATMENT_ARM]
            )
            treatment_cross_site_values = [
                _float(row, "cross_site_service_count")
                for row in by_arm[TREATMENT_ARM]
            ]
            treatment_cross_site_active_tasks = sum(
                value > 0.0
                for value in treatment_cross_site_values
            )
            cells.append(
                {
                    "region": region,
                    "region_label": REGION_LABELS[region],
                    "customer_size": size,
                    "map_count": len(MAP_INDICES),
                    "seed_count": len(SEEDS),
                    "rows_per_arm": (
                        len(MAP_INDICES) * len(SEEDS)
                    ),
                    "control_cost_mean": control_cost,
                    "treatment_cost_mean": treatment_cost,
                    "cost_reduction_percent": (
                        100.0
                        * (control_cost - treatment_cost)
                        / control_cost
                    ),
                    "treatment_cross_site_service_mean": fmean(
                        treatment_cross_site_values
                    ),
                    "treatment_cross_site_active_tasks": (
                        treatment_cross_site_active_tasks
                    ),
                    "treatment_cross_site_active_rate_percent": (
                        100.0
                        * treatment_cross_site_active_tasks
                        / len(treatment_cross_site_values)
                    ),
                    "treatment_service_level_percent": (
                        100.0
                        * fmean(
                            _float(row, "service_level")
                            for row in by_arm[TREATMENT_ARM]
                        )
                    ),
                }
            )
    if len(cells) != 27:
        raise AssertionError(
            f"E3 cell reduction produced {len(cells)} cells"
        )
    return cells


def build_e3_layer_rows(
    cell_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Reduce 27 cells to nine compact paper rows plus an overall row."""

    lookup = {
        (str(row["region"]), int(row["customer_size"])): row
        for row in cell_rows
    }
    expected = {
        (region, size)
        for region in REGIONS
        for size in CUSTOMER_SIZES
    }
    if set(lookup) != expected:
        raise ValueError(
            "E3 layer reduction requires the complete 27-cell matrix"
        )

    result: list[dict[str, Any]] = []
    for region in REGIONS:
        for layer_label, sizes in SIZE_LAYERS:
            selected = [lookup[(region, size)] for size in sizes]
            control_cost = _mean(selected, "control_cost_mean")
            treatment_cost = _mean(
                selected,
                "treatment_cost_mean",
            )
            result.append(
                {
                    "region": region,
                    "region_label": REGION_LABELS[region],
                    "scale_layer": layer_label,
                    "customer_sizes": "/".join(
                        str(size) for size in sizes
                    ),
                    "cell_count": len(selected),
                    "control_cost_mean": control_cost,
                    "treatment_cost_mean": treatment_cost,
                    "cost_reduction_percent": (
                        100.0
                        * (control_cost - treatment_cost)
                        / control_cost
                    ),
                    "treatment_cross_site_service_mean": _mean(
                        selected,
                        "treatment_cross_site_service_mean",
                    ),
                    "treatment_cross_site_active_cell_count": sum(
                        int(
                            row[
                                "treatment_cross_site_active_tasks"
                            ]
                        )
                        > 0
                        for row in selected
                    ),
                    "treatment_cross_site_active_rate_percent": _mean(
                        selected,
                        "treatment_cross_site_active_rate_percent",
                    ),
                    "treatment_service_level_percent": _mean(
                        selected,
                        "treatment_service_level_percent",
                    ),
                }
            )

    control_cost = _mean(cell_rows, "control_cost_mean")
    treatment_cost = _mean(cell_rows, "treatment_cost_mean")
    result.append(
        {
            "region": "overall",
            "region_label": "总体",
            "scale_layer": "全部",
            "customer_sizes": "10--200",
            "cell_count": len(cell_rows),
            "control_cost_mean": control_cost,
            "treatment_cost_mean": treatment_cost,
            "cost_reduction_percent": (
                100.0
                * (control_cost - treatment_cost)
                / control_cost
            ),
            "treatment_cross_site_service_mean": _mean(
                cell_rows,
                "treatment_cross_site_service_mean",
            ),
            "treatment_cross_site_active_cell_count": sum(
                int(row["treatment_cross_site_active_tasks"]) > 0
                for row in cell_rows
            ),
            "treatment_cross_site_active_rate_percent": _mean(
                cell_rows,
                "treatment_cross_site_active_rate_percent",
            ),
            "treatment_service_level_percent": _mean(
                cell_rows,
                "treatment_service_level_percent",
            ),
        }
    )
    return result
