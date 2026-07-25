#!/usr/bin/env python3
"""Audit, classify and render sealed E3 results without changing them.

Evidence completeness and result direction are deliberately separate.  A
complete but weak or adverse result remains a valid sealed result; it is not
silently dropped, relabelled or converted into a paper-strength conclusion.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean, median
from typing import Any


REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from baselines.china_e3_e7.charts import generate_figures  # noqa: E402
from baselines.china_e3_e7.e3_exhibits import (  # noqa: E402
    CONTROL_ARM,
    TREATMENT_ARM,
    build_e3_cell_rows,
    build_e3_layer_rows,
)
from baselines.china_e3_e7.release_v6_config import (  # noqa: E402
    E3_AGGREGATE as DEFAULT_AGGREGATE,
    E3_FIGURES as DEFAULT_FIGURES,
    E3_FORMAL as DEFAULT_FORMAL,
    E3_RESULT_AUDIT as DEFAULT_OUT,
    E3_RESULT_PREREGISTRATION,
    E3_TABLES as DEFAULT_TABLES,
)
from baselines.china_e3_e7.statistics import (  # noqa: E402
    _normalise_formal_row,
)
from baselines.china_e3_e7.tables import render_tables  # noqa: E402


ABS_TOL = 1.0e-9


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("result audit cannot write an empty CSV")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _comparison(
    control: float,
    treatment: float,
    tolerance: float = ABS_TOL,
) -> str:
    difference = control - treatment
    if difference > tolerance:
        return "treatment_win"
    if difference < -tolerance:
        return "treatment_loss"
    return "tie"


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "wins": sum(
            row["comparison"] == "treatment_win" for row in rows
        ),
        "ties": sum(row["comparison"] == "tie" for row in rows),
        "losses": sum(
            row["comparison"] == "treatment_loss" for row in rows
        ),
    }


def _summary_float(
    row: dict[str, Any],
    field: str,
) -> float | None:
    value = row.get(field)
    if value is None or str(value).strip() == "":
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _has_reciprocal_direction(
    directions: set[str],
) -> bool:
    for direction in directions:
        if "->" not in direction:
            continue
        origin, destination = direction.split("->", 1)
        if f"{destination}->{origin}" in directions:
            return True
    return False


def evaluate_e3_release_gate(
    normalized_rows: list[dict[str, str]],
    cell_rows: list[dict[str, Any]],
    total_cost_summary: dict[str, Any],
    preregistration: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate only thresholds fixed before formal E3 search."""

    exposure = preregistration["mechanism_exposure_gate"]
    paper = preregistration["paper_strength_gate"]
    layer_rows = [
        row
        for row in build_e3_layer_rows(cell_rows)
        if row["region"] != "overall"
    ]
    cell_comparisons = [
        _comparison(
            float(row["control_cost_mean"]),
            float(row["treatment_cost_mean"]),
        )
        for row in cell_rows
    ]
    active_cells = sum(
        int(row["treatment_cross_site_active_tasks"]) > 0
        for row in cell_rows
    )
    candidate_directions_by_region: dict[str, set[str]] = defaultdict(
        set
    )
    for row in normalized_rows:
        if row.get("arm") != TREATMENT_ARM:
            continue
        try:
            directions = json.loads(
                row.get(
                    "cross_depot_candidate_directions_json",
                    "{}",
                )
                or "{}"
            )
        except json.JSONDecodeError as exc:
            raise ValueError(
                "invalid E3 candidate-direction evidence"
            ) from exc
        for direction, count in directions.items():
            if float(count) > 0.0:
                candidate_directions_by_region[
                    str(row["region"])
                ].add(str(direction))
    reciprocal_by_region = {
        region: _has_reciprocal_direction(directions)
        for region, directions in candidate_directions_by_region.items()
    }
    expected_regions = {"jjj", "prd", "cy"}
    reciprocal_all_regions = (
        set(reciprocal_by_region) == expected_regions
        and all(reciprocal_by_region.values())
    )
    mean_reduction = _summary_float(
        total_cost_summary,
        "mean_reduction_percent",
    )
    randomization_p = _summary_float(
        total_cost_summary,
        "randomization_p",
    )
    ci_low = _summary_float(total_cost_summary, "ci_low")
    treatment_service = [
        float(row["service_level"])
        for row in normalized_rows
        if row["arm"] == TREATMENT_ARM
    ]
    checks = {
        "complete_27_cell_matrix": len(cell_rows) == 27,
        "control_cross_site_zero": all(
            abs(
                float(row.get("cross_site_service_count") or 0.0)
            )
            <= ABS_TOL
            for row in normalized_rows
            if row["arm"] == CONTROL_ARM
        ),
        "treatment_active_cells": (
            active_cells
            >= int(
                exposure[
                    "treatment_cross_site_active_cells_minimum"
                ]
            )
        ),
        "reciprocal_candidate_directions_each_region": (
            reciprocal_all_regions
            if exposure[
                "reciprocal_candidate_directions_required_in_each_region"
            ]
            else True
        ),
        "treatment_service_level": (
            100.0 * fmean(treatment_service)
            >= float(
                exposure[
                    "treatment_service_level_percent_minimum"
                ]
            )
            - 1.0e-12
        ),
        "mean_cell_cost_reduction": (
            mean_reduction is not None
            and mean_reduction
            >= float(
                paper[
                    "mean_cell_cost_reduction_percent_minimum"
                ]
            )
        ),
        "positive_cell_count": (
            cell_comparisons.count("treatment_win")
            >= int(paper["positive_cell_count_minimum"])
        ),
        "cell_loss_count": (
            cell_comparisons.count("treatment_loss")
            <= int(paper["cell_loss_count_maximum"])
        ),
        "positive_region_scale_layers": (
            sum(
                float(row["cost_reduction_percent"]) > 0.0
                for row in layer_rows
            )
            >= int(
                paper[
                    "positive_region_scale_layer_count_minimum"
                ]
            )
        ),
        "positive_cost_difference_interval": (
            ci_low is not None and ci_low > 0.0
        ),
        "single_family_randomization_p": (
            randomization_p is not None
            and randomization_p
            <= float(
                paper[
                    "single_family_randomization_p_maximum_before_full_holm"
                ]
            )
        ),
    }
    provisional_pass = all(checks.values())
    return {
        "status": (
            "PASS_E3_PROVISIONAL_PAPER_STRENGTH_PENDING_FIVE_FAMILY_HOLM"
            if provisional_pass
            else "HOLD_E3_RESULT_NOT_PAPER_STRONG"
        ),
        "passed": provisional_pass,
        "checks": checks,
        "observed": {
            "treatment_active_cells": active_cells,
            "reciprocal_candidate_directions_by_region": {
                region: sorted(directions)
                for region, directions in sorted(
                    candidate_directions_by_region.items()
                )
            },
            "reciprocal_direction_pass_by_region": (
                reciprocal_by_region
            ),
            "positive_cells": cell_comparisons.count(
                "treatment_win"
            ),
            "tied_cells": cell_comparisons.count("tie"),
            "adverse_cells": cell_comparisons.count(
                "treatment_loss"
            ),
            "positive_region_scale_layers": sum(
                float(row["cost_reduction_percent"]) > 0.0
                for row in layer_rows
            ),
            "mean_cell_cost_reduction_percent": mean_reduction,
            "single_family_randomization_p": randomization_p,
            "cost_difference_ci_low": ci_low,
        },
        "five_family_holm_status": (
            "PENDING_UNTIL_E3_TO_E7_PRIMARY_RESULTS_EXIST"
        ),
        "final_headline_gate_passed": False,
    }


def summarize_e3_results(
    raw_rows: list[dict[str, str]],
    total_cost_summary: dict[str, Any],
    preregistration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a result-direction report while preserving every E3 row."""

    normalized = [_normalise_formal_row(row) for row in raw_rows]
    cell_source = build_e3_cell_rows(normalized)
    pair_groups: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in normalized:
        pair_id = str(row.get("pair_id", "")).strip()
        arm = str(row.get("arm", "")).strip()
        if not pair_id or arm not in {CONTROL_ARM, TREATMENT_ARM}:
            raise ValueError("E3 result audit found an invalid pair or arm")
        if arm in pair_groups[pair_id]:
            raise ValueError(f"duplicate E3 pair arm: {pair_id}/{arm}")
        pair_groups[pair_id][arm] = row
    if (
        len(pair_groups) != 405
        or any(set(arms) != {CONTROL_ARM, TREATMENT_ARM}
               for arms in pair_groups.values())
    ):
        raise ValueError(
            "E3 result audit requires exactly 405 complete paired tasks"
        )

    pair_rows: list[dict[str, Any]] = []
    for pair_id, arms in sorted(pair_groups.items()):
        control = float(arms[CONTROL_ARM]["total_cost"])
        treatment = float(arms[TREATMENT_ARM]["total_cost"])
        pair_rows.append(
            {
                "pair_id": pair_id,
                "instance_id": arms[CONTROL_ARM]["instance_id"],
                "seed": int(float(arms[CONTROL_ARM]["seed"])),
                "control_cost": control,
                "treatment_cost": treatment,
                "difference_control_minus_treatment": (
                    control - treatment
                ),
                "reduction_percent": (
                    100.0 * (control - treatment) / control
                ),
                "comparison": _comparison(control, treatment),
            }
        )

    cell_rows: list[dict[str, Any]] = []
    for row in cell_source:
        control = float(row["control_cost_mean"])
        treatment = float(row["treatment_cost_mean"])
        cell_rows.append(
            {
                **row,
                "difference_control_minus_treatment": (
                    control - treatment
                ),
                "comparison": _comparison(control, treatment),
            }
        )

    control_cross_site = [
        float(row.get("cross_site_service_count") or 0.0)
        for row in normalized
        if row["arm"] == CONTROL_ARM
    ]
    treatment_cross_site = [
        float(row.get("cross_site_service_count") or 0.0)
        for row in normalized
        if row["arm"] == TREATMENT_ARM
    ]
    if any(abs(value) > ABS_TOL for value in control_cross_site):
        raise ValueError(
            "frozen-responsibility control contains cross-site service"
        )
    treatment_service = [
        float(row["service_level"])
        for row in normalized
        if row["arm"] == TREATMENT_ARM
    ]

    mean_delta = _summary_float(total_cost_summary, "mean_delta")
    randomization_p = _summary_float(
        total_cost_summary,
        "randomization_p",
    )
    ci_low = _summary_float(total_cost_summary, "ci_low")
    ci_high = _summary_float(total_cost_summary, "ci_high")
    if (
        total_cost_summary.get("status") != "PASS_DATA_COMPLETE"
        or int(float(total_cost_summary.get("n_cells", 0))) != 27
        or mean_delta is None
        or randomization_p is None
        or ci_low is None
        or ci_high is None
    ):
        raise ValueError(
            "E3 primary total-cost summary is absent or incomplete"
        )

    cell_counts = _counts(cell_rows)
    if (
        mean_delta > ABS_TOL
        and ci_low > 0.0
        and randomization_p < 0.05
        and cell_counts["wins"] > cell_counts["losses"]
    ):
        effect_pattern = (
            "POSITIVE_SINGLE_FAMILY_PENDING_FIVE_FAMILY_HOLM"
        )
    elif mean_delta > ABS_TOL:
        effect_pattern = "POSITIVE_DESCRIPTIVE_NOT_YET_PAPER_STRONG"
    elif mean_delta < -ABS_TOL:
        effect_pattern = "ADVERSE_RESULT"
    else:
        effect_pattern = "NO_MEAN_DIFFERENCE"

    result = {
        "schema": "resetp.china-e3-result-summary.v1",
        "formal_rows": len(normalized),
        "paired_tasks": len(pair_rows),
        "paired_cells": len(cell_rows),
        "pair_counts": _counts(pair_rows),
        "cell_counts": cell_counts,
        "mean_pair_reduction_percent": fmean(
            float(row["reduction_percent"]) for row in pair_rows
        ),
        "median_pair_reduction_percent": median(
            float(row["reduction_percent"]) for row in pair_rows
        ),
        "mean_cell_reduction_percent": _summary_float(
            total_cost_summary,
            "mean_reduction_percent",
        ),
        "median_cell_reduction_percent": _summary_float(
            total_cost_summary,
            "median_reduction_percent",
        ),
        "mean_cost_difference_control_minus_treatment": mean_delta,
        "cost_difference_ci": [ci_low, ci_high],
        "single_family_randomization_p": randomization_p,
        "wilcoxon_p": _summary_float(
            total_cost_summary,
            "wilcoxon_p",
        ),
        "sign_test_p": _summary_float(
            total_cost_summary,
            "sign_p",
        ),
        "holm_adjusted_p": None,
        "holm_status": (
            "PENDING_UNTIL_ALL_FIVE_PRE_REGISTERED_FAMILIES_EXIST"
        ),
        "control_cross_site_service_mean": fmean(
            control_cross_site
        ),
        "treatment_cross_site_service_mean": fmean(
            treatment_cross_site
        ),
        "treatment_cross_site_active_tasks": sum(
            value > ABS_TOL for value in treatment_cross_site
        ),
        "treatment_service_level_percent": (
            100.0 * fmean(treatment_service)
        ),
        "effect_pattern": effect_pattern,
        "paper_numeric_fill_allowed": True,
        "paper_headline_claim_allowed": False,
        "paper_claim_boundary": (
            "All sealed numbers and unfavorable cells may be reported. "
            "A five-family corrected headline claim remains unavailable "
            "until the other four preregistered primary families exist; "
            "the active-family Holm value is intentionally not reported."
        ),
        "pair_rows": pair_rows,
        "cell_rows": cell_rows,
    }
    if preregistration is not None:
        result["pre_registered_result_gate"] = (
            evaluate_e3_release_gate(
                normalized,
                cell_source,
                total_cost_summary,
                preregistration,
            )
        )
    return result


def _load_primary_summary(path: Path) -> dict[str, str]:
    rows = read_csv(path)
    matches = [
        row
        for row in rows
        if (
            row.get("family") == "E3"
            and row.get("contrast_role") == "primary"
            and row.get("metric") == "total_cost"
        )
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "aggregate summary has no unique E3 total-cost primary row"
        )
    return matches[0]


def run(
    formal_root: Path,
    aggregate_dir: Path,
    out_dir: Path,
    table_dir: Path,
    figure_dir: Path,
) -> dict[str, Any]:
    formal_decision = json.loads(
        (formal_root / "decision.json").read_text(encoding="utf-8")
    )
    aggregate_decision = json.loads(
        (aggregate_dir / "decision.json").read_text(encoding="utf-8")
    )
    certificate = json.loads(
        (
            aggregate_dir / "independent_recalc_certificate.json"
        ).read_text(encoding="utf-8")
    )
    replay_done = json.loads(
        (aggregate_dir / "done.json").read_text(encoding="utf-8")
    )
    raw_path = formal_root / "raw_runs.csv"
    if (
        formal_decision.get("verdict")
        != "PASS_E3_FORMAL_RAW_COMPLETE"
        or aggregate_decision.get("status")
        != "AGGREGATE_READY_FOR_REVIEW"
        or aggregate_decision.get("independent_recalc_complete")
        is not True
        or certificate.get("status") != "PASS_INDEPENDENT_RECALC"
        or certificate.get("task_count") != 810
        or certificate.get("pair_count") != 405
        or certificate.get("raw_runs_sha256") != sha256(raw_path)
        or replay_done.get("status")
        != "PASS_E3_INDEPENDENT_RECALC_AND_AGGREGATION"
    ):
        raise RuntimeError(
            "E3 result audit prerequisites are not sealed and complete"
        )

    preregistration = json.loads(
        E3_RESULT_PREREGISTRATION.read_text(encoding="utf-8")
    )
    if (
        preregistration.get("registered_before_formal_e3_search")
        is not True
        or preregistration.get("experiment_id")
        != "CHINA-E3-FORMAL-RELEASE-001"
    ):
        raise RuntimeError("E3 result gate is not preregistered")
    summary = summarize_e3_results(
        read_csv(raw_path),
        _load_primary_summary(aggregate_dir / "summary.csv"),
        preregistration,
    )
    pair_rows = summary.pop("pair_rows")
    cell_rows = summary.pop("cell_rows")

    table_decision = render_tables(
        aggregate_dir,
        table_dir,
        repo_root=REPO,
    )
    figure_decision = generate_figures(
        raw_path,
        figure_dir,
        repo_root=REPO,
        aggregate_dir=aggregate_dir,
    )
    if (
        table_decision.get("status") != "TABLE_REVIEW_REQUIRED"
        or figure_decision.get("status")
        != "FIGURE_REVIEW_REQUIRED"
    ):
        raise RuntimeError(
            "E3 publisher table or figure did not render from sealed data"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / "paired_task_results.csv", pair_rows)
    write_csv(out_dir / "paired_cell_results.csv", cell_rows)
    write_json(out_dir / "result_summary.json", summary)
    metadata = {
        "schema": "resetp.china-e3-result-audit.metadata.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "formal_root": str(formal_root),
        "aggregate_dir": str(aggregate_dir),
        "table_dir": str(table_dir),
        "figure_dir": str(figure_dir),
        "formal_raw_runs_sha256": sha256(raw_path),
        "independent_recalc_certificate_sha256": sha256(
            aggregate_dir / "independent_recalc_certificate.json"
        ),
        "aggregate_decision_sha256": sha256(
            aggregate_dir / "decision.json"
        ),
        "source_hashes": {
            str(path.relative_to(REPO)): sha256(path)
            for path in (
                Path(__file__).resolve(),
                E3_RESULT_PREREGISTRATION,
                REPO / "baselines/china_e3_e7/statistics.py",
                REPO / "baselines/china_e3_e7/e3_exhibits.py",
                REPO / "baselines/china_e3_e7/charts.py",
                REPO / "baselines/china_e3_e7/tables.py",
            )
        },
    }
    write_json(out_dir / "metadata.json", metadata)
    decision = {
        "schema": "resetp.china-e3-result-audit.decision.v1",
        "verdict": "PASS_E3_RESULT_AUDIT_EVIDENCE_COMPLETE",
        "effect_pattern": summary["effect_pattern"],
        "pre_registered_result_gate": summary[
            "pre_registered_result_gate"
        ],
        "formal_rows": summary["formal_rows"],
        "paired_tasks": summary["paired_tasks"],
        "paired_cells": summary["paired_cells"],
        "paper_numeric_fill_allowed": True,
        "paper_headline_claim_allowed": False,
        "five_family_holm_pending": True,
        "unfavorable_results_preserved": True,
        "result_direction_not_used_as_data_integrity_gate": True,
        "table_decision": table_decision["status"],
        "figure_decision": figure_decision["status"],
        "result_preregistration": str(
            E3_RESULT_PREREGISTRATION.relative_to(REPO)
        ),
        "result_preregistration_sha256": sha256(
            E3_RESULT_PREREGISTRATION
        ),
    }
    write_json(out_dir / "decision.json", decision)
    (out_dir / "report.md").write_text(
        "\n".join(
            [
                "# E3 正式结果审查",
                "",
                f"证据判定：`{decision['verdict']}`。",
                f"结果形态：`{summary['effect_pattern']}`。",
                (
                    "预注册论文强度门："
                    f"`{summary['pre_registered_result_gate']['status']}`。"
                ),
                "",
                (
                    "810条正式结果均已独立复算并组成405个同题同种子配对，"
                    "再按预注册层级汇总为27个地区—规模单元。"
                ),
                (
                    "表格和图片只从这些封存结果生成；负向单元、平局和不显著"
                    "结果均保留。"
                ),
                (
                    "当前只完成E3，不能把仅对当前活动实验计算的Holm值冒充"
                    "五个主要实验共同校正结果，因此论文头条结论仍等待E4--E7。"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    artifacts = {
        str(path.relative_to(out_dir)): sha256(path)
        for path in sorted(out_dir.rglob("*"))
        if (
            path.is_file()
            and path.name not in {"artifact_hashes.json", "done.json"}
            and not path.name.startswith("._")
            and "__pycache__" not in path.parts
        )
    }
    write_json(
        out_dir / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": [
                "artifact_hashes.json",
                "done.json",
                "._*",
                "__pycache__",
                ".pytest_cache",
                "*.tmp",
            ],
            "artifacts": artifacts,
        },
    )
    write_json(
        out_dir / "done.json",
        {
            "schema": "resetp.china-e3-result-audit.done.v1",
            "status": "PASS_E3_RESULT_AUDIT_COMPLETE",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "decision_sha256": sha256(out_dir / "decision.json"),
            "artifact_hashes_sha256": sha256(
                out_dir / "artifact_hashes.json"
            ),
        },
    )
    return decision


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--formal-root",
        type=Path,
        default=DEFAULT_FORMAL,
    )
    parser.add_argument(
        "--aggregate-dir",
        type=Path,
        default=DEFAULT_AGGREGATE,
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--table-dir", type=Path, default=DEFAULT_TABLES)
    parser.add_argument(
        "--figure-dir",
        type=Path,
        default=DEFAULT_FIGURES,
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    result = run(
        arguments.formal_root.resolve(),
        arguments.aggregate_dir.resolve(),
        arguments.out_dir.resolve(),
        arguments.table_dir.resolve(),
        arguments.figure_dir.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
